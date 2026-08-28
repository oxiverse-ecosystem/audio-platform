"""Single enhancement endpoint: the whole pipeline behind one route.

This router intentionally exposes **one** endpoint -- ``POST /v1/enhance``. It runs the
full audio pipeline (spectral noise reduction when the VAD finds a usable floor, then the
CPU-only studio-mastering chain) and returns the processed audio plus the combined report.
The enhancer and the mastering stage are NOT exposed as separate routes; they are orchestrated
internally by :mod:`audio_streaming.pipeline`.
"""

from __future__ import annotations

import base64
import io
import time

import numpy as np
import soundfile as sf
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from .models import EnhanceRequest, EnhanceResponse
from .pipeline import enhance_then_master
from .security import Principal
from .api import require_principal

router = APIRouter(prefix="/v1", tags=["enhancement"])


def _decode_audio_b64(audio_b64: str) -> tuple[np.ndarray, int]:
    try:
        raw = base64.b64decode(audio_b64, validate=True)
    except Exception as exc:  # noqa: BLE001 - report any decode failure as 422
        raise ValueError("audio_b64 is not valid base64") from exc
    if len(raw) == 0:
        raise ValueError("audio_b64 decoded to an empty payload")
    if len(raw) > 40 * 1024 * 1024:
        raise ValueError("audio payload exceeds 40 MiB limit")

    import shutil
    import subprocess
    import tempfile

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to decode the uploaded audio but was not found on PATH")

    # Decode with ffmpeg (handles MP3/OGG/etc reliably; libsndfile MP3 support is build-dependent).
    with tempfile.TemporaryDirectory() as tmp:
        src = f"{tmp}/in"
        # Write the raw bytes; ffmpeg infers the container from the bytes.
        with open(src, "wb") as fh:
            fh.write(raw)
        decoded = f"{tmp}/decoded.wav"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src, "-acodec", "pcm_f32le", "-ar", "48000", decoded],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise ValueError("could not decode audio (unsupported or corrupt container)")
        try:
            data, sample_rate = sf.read(decoded, dtype="float32", always_2d=False)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("could not read decoded audio") from exc

    if data.ndim > 2:
        raise ValueError("audio must be mono or stereo")
    if not np.isfinite(data).all():
        raise ValueError("decoded audio contains non-finite samples")
    return data, int(sample_rate)


def _encode_payload(signal: np.ndarray, sample_rate: int, output_format: str) -> tuple[str, str, bytes]:
    import shutil
    import subprocess
    import tempfile

    if output_format == "wav":
        buf = io.BytesIO()
        sf.write(buf, signal, sample_rate, format="WAV", subtype="PCM_24")
        return "enhanced.wav", "audio/wav", buf.getvalue()

    # mp3: write an intermediate WAV then let ffmpeg encode it (file-based, reliable on Windows).
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode mp3 output but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = f"{tmp}/pipeline.wav"
        sf.write(wav_path, signal, sample_rate, format="WAV", subtype="PCM_24")
        out_path = f"{tmp}/enhanced.mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "320k", out_path],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg mp3 encode failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        with open(out_path, "rb") as fh:
            payload = fh.read()
    return "enhanced.mp3", "audio/mpeg", payload


def _report_to_dict(report) -> dict:
    mas = report.mastering
    return {
        "noise_detected": report.noise_detected,
        "enhancer_noise_estimation": report.enhancer_noise_estimation,
        "enhancer_vad_speech_ratio": report.enhancer_vad_speech_ratio,
        "enhancer_estimated_noise_floor_dbfs": report.enhancer_estimated_noise_floor_dbfs,
        "enhancer_detected_f0_hz": report.enhancer_detected_f0_hz,
        "mastering": {
            "input_lufs": mas.input_lufs,
            "output_lufs": mas.output_lufs,
            "input_true_peak_dbfs": mas.input_true_peak_dbfs,
            "output_true_peak_dbfs": mas.output_true_peak_dbfs,
            "gain_to_target_db": mas.gain_to_target_db,
            "clipped_after": mas.clipped_after,
        },
    }


@router.post("/enhance", response_model=EnhanceResponse, status_code=status.HTTP_200_OK)
async def enhance(
    request: Request,
    body: EnhanceRequest,
    _: Principal = Depends(require_principal),
):
    """Run the full enhance-then-master pipeline and return processed audio + report.

    Authentication: any valid bearer identity (same as the streaming API). The pipeline
    itself decides whether noise reduction engages; the caller does not choose stages.
    """
    from fastapi.concurrency import run_in_threadpool

    from .enhancer import EnhancementSettings
    from .mastering import MasteringSettings

    def _build_settings(cls, overrides):
        if not overrides:
            return cls()
        # Reject unknown keys so a caller can't smuggle in unsupported fields.
        unknown = set(overrides) - {f.name for f in cls.__dataclass_fields__.values()}
        if unknown:
            raise ValueError(f"unknown {cls.__name__} override keys: {sorted(unknown)}")
        return cls(**overrides)

    try:
        enhancement = _build_settings(EnhancementSettings, body.enhancement)
        mastering = _build_settings(MasteringSettings, body.mastering)
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc), "request_id": request_id},
        )

    started = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        samples, sample_rate = await run_in_threadpool(_decode_audio_b64, body.audio_b64)
        signal, report = await run_in_threadpool(
            enhance_then_master, samples, sample_rate, enhancement, mastering
        )
        filename, media_type, payload = await run_in_threadpool(
            _encode_payload, signal, sample_rate, body.output_format
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc), "request_id": request_id},
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": str(exc), "request_id": request_id},
        )

    try:
        await request.app.state.repository.audit(
            "enhance_processed", "success",
            latency_ms=(time.perf_counter() - started) * 1000,
            details={"noise_detected": report.noise_detected, "output_lufs": report.mastering.output_lufs},
        )
    except Exception:
        pass

    return EnhanceResponse(
        filename=filename,
        media_type=media_type,
        audio_b64=base64.b64encode(payload).decode("ascii"),
        report=_report_to_dict(report),
    )
