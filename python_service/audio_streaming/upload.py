"""Phase 1a: Upload → queue → repair → studio-enhance → store → delete raw.

Flow (matches the founder's stated flow):
  POST /v1/uploads            -> save raw file, create queued job, start background work
  GET  /v1/uploads/{job_id}  -> poll status (queued/processing/ready/failed) + signed URLs
  GET  /v1/cdn/{asset}/{file}-> serve stored mastered audio (signed, local delivery)

Background work: decode (ffmpeg) -> repair_mobile (declip/trim/deplosive) ->
enhance_then_master (enhancer + mastering broadcast chain) -> encode WAV(24-bit) +
MP3(320k) -> store both via MediaStore -> DELETE the raw file. The raw is never kept.

This is the ingestion point for the streaming stage: a ready job exposes
``mastered_key_*`` in the MediaStore, which the watermarked-serving phase (1b) will
later consume. The watermark is NOT applied here (that happens once at ingest for the
A/B variant scheme; see docs/phase1-architecture.md).
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from .enhancer import EnhancementSettings, enhance_voice
from .jobs import JobRecord, JobsRepository
from .mastering import MasteringSettings, master_voice
from .pipeline import enhance_then_master
from .repair import RepairReport, RepairSettings, repair_mobile
from .security import Principal
from .api import require_principal
from .store import MediaStore, URLSigner


router = APIRouter(prefix="/v1", tags=["upload"])

UPLOAD_LIMIT_BYTES = 200 * 1024 * 1024  # 200 MB raw ceiling
ALLOWED_OUTPUT = {"mp3", "wav"}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class UploadResponse(BaseModel):
    job_id: str
    asset_id: str
    status: str
    status_url: str
    episode_id: str | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    asset_id: str
    title: str
    status: str
    created_at: int
    updated_at: int
    report: dict | None = None
    error: str | None = None
    # Present only when status == ready. Signed, short-TTL local delivery URLs.
    download: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _store(request: Request) -> MediaStore:
    return request.app.state.media_store


def _jobs(request: Request) -> JobsRepository:
    return request.app.state.jobs_repository


def _signer(request: Request) -> URLSigner:
    return request.app.state.url_signer


def _decode_to_mono_48k(src_path: str) -> tuple[np.ndarray, int]:
    """Decode any ffmpeg-readable file to mono 48 kHz float32 via ffmpeg."""
    import subprocess

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to decode uploads but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        decoded = f"{tmp}/decoded.wav"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-acodec", "pcm_f32le", "-ar", "48000", "-ac", "1", decoded],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"could not decode audio: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        data, sr = sf.read(decoded, dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    return data.astype(np.float32), int(sr)


def _encode_outputs(signal: np.ndarray, sample_rate: int, mastered_key_wav: str, mastered_key_mp3: str,
                    store: MediaStore) -> tuple[str, str]:
    """Encode mastered audio to WAV(24-bit) + MP3(320k) and store both. Returns (wav_key, mp3_key)."""
    import subprocess

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode outputs but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = f"{tmp}/mastered.wav"
        sf.write(wav_path, signal, sample_rate, format="WAV", subtype="PCM_24")
        with open(wav_path, "rb") as fh:
            store.put(mastered_key_wav, fh.read())
        mp3_path = f"{tmp}/mastered.mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "320k", mp3_path],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"mp3 encode failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        with open(mp3_path, "rb") as fh:
            store.put(mastered_key_mp3, fh.read())
    return mastered_key_wav, mastered_key_mp3


def _compute_waveform_peaks(samples: np.ndarray, num_peaks: int = 128) -> list[float]:
    """Calculate normalized peak amplitudes across audio signal for true visualizer."""
    if len(samples) == 0:
        return [0.05] * num_peaks
    chunk_size = max(1, len(samples) // num_peaks)
    peaks: list[float] = []
    for i in range(num_peaks):
        start = i * chunk_size
        end = min(len(samples), (i + 1) * chunk_size) if i < num_peaks - 1 else len(samples)
        if start >= len(samples):
            peaks.append(0.05)
            continue
        chunk = samples[start:end]
        if len(chunk) == 0:
            peaks.append(0.05)
        else:
            peak = float(np.max(np.abs(chunk)))
            peaks.append(peak)
    max_p = max(peaks) if peaks else 0.0
    if max_p > 0:
        normalized = [round(max(0.05, min(1.0, p / max_p)), 3) for p in peaks]
    else:
        normalized = [0.05] * num_peaks
    return normalized


def _encode_raw_mp3(signal: np.ndarray, sample_rate: int, raw_key_mp3: str, store: MediaStore) -> str:
    """Encode raw audio to MP3 for synchronized A/B comparison player."""
    import subprocess
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode raw audio but was not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = f"{tmp}/raw.wav"
        sf.write(wav_path, signal, sample_rate, format="WAV", subtype="PCM_16")
        mp3_path = f"{tmp}/raw.mp3"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "192k", mp3_path],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"raw mp3 encode failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        with open(mp3_path, "rb") as fh:
            store.put(raw_key_mp3, fh.read())
    return raw_key_mp3


def _process_job(request: Request, job_id: str, asset_id: str, raw_path: str,
                 owner_user_id: str, output_format: str) -> None:
    """Synchronous processing body (runs inside a thread, off the event loop)."""
    store = _store(request)
    jobs = _jobs(request)
    try:
        # Decode raw -> mono 48k. (Large files: ffmpeg, not base64-in-JSON.)
        samples, sr = _decode_to_mono_48k(raw_path)

        # 0) True waveform peaks & raw audio storage for A/B comparison player
        waveform_peaks = _compute_waveform_peaks(samples, 128)
        raw_key = f"assets/{asset_id}/raw.mp3"
        _encode_raw_mp3(samples, sr, raw_key, store)

        # 1) Mobile repair (declip / trim silence / de-plosive).
        repaired, repair_rep = repair_mobile(samples, sr, RepairSettings())

        # 2) Studio enhancement (noise reduction when needed) + mastering broadcast chain.
        enhanced, enh_rep = enhance_voice(repaired, sr, EnhancementSettings())
        mastered, mas_rep = master_voice(enhanced, sr, MasteringSettings())

        # 3) Encode + store both formats.
        wav_key = f"assets/{asset_id}/mastered.wav"
        mp3_key = f"assets/{asset_id}/mastered.mp3"
        _encode_outputs(mastered, sr, wav_key, mp3_key, store)
        # Delete raw temporary upload file
        Path(raw_path).unlink(missing_ok=True)

        duration_seconds = float(len(mastered)) / float(sr)
        report = {
            "sample_rate": sr,
            "duration_seconds": round(duration_seconds, 2),
            "waveform_peaks": waveform_peaks,
            "repair": _repair_to_dict(repair_rep),
            "enhance": _pipeline_to_dict(enh_rep, mas_rep),
        }
        # Mark ready and sync episode state together
        async def _finalize():
            await jobs.update_status(
                job_id, "ready", mastered_key_wav=wav_key,
                mastered_key_mp3=mp3_key, raw_key_mp3=raw_key, report=report,
            )
            await jobs.record_usage(owner_user_id, asset_id, duration_seconds)

            repo = request.app.state.repository
            ep = await repo.get_episode_by_asset(asset_id)
            if ep is not None:
                if ep.get("publish_on_ready") == 1:
                    try:
                        mastered_pcm = store.get(wav_key)
                        await request.app.state.ab_stream.ingest_asset(asset_id, owner_user_id, mastered_pcm, 48000)
                    except Exception:
                        pass
                    await repo.update_episode_status(
                        ep["episode_id"], "published",
                        duration_seconds=round(duration_seconds, 2),
                        waveform_peaks=waveform_peaks,
                    )
                else:
                    await repo.update_episode_status(
                        ep["episode_id"], "ready",
                        duration_seconds=round(duration_seconds, 2),
                        waveform_peaks=waveform_peaks,
                    )

        fut = asyncio.run_coroutine_threadsafe(_finalize(), request.app.state.loop)
        try:
            fut.result(timeout=30)
        except Exception:
            pass
    except Exception as exc:  # surface failure; never leave a job stuck in processing
        try:
            Path(raw_path).unlink(missing_ok=True)
        except Exception:
            pass
        asyncio.run_coroutine_threadsafe(
            jobs.update_status(job_id, "failed", error=str(exc)[:500]),
            request.app.state.loop,
        )


def _repair_to_dict(r: RepairReport) -> dict:
    return {
        "input_peak_dbfs": round(r.input_peak_dbfs, 2),
        "output_peak_dbfs": round(r.output_peak_dbfs, 2),
        "clipped_samples_before": r.clipped_samples_before,
        "clipped_samples_after": r.clipped_samples_after,
        "declip_applied": r.declip_applied,
        "leading_silence_trimmed_ms": r.leading_silence_trimmed_ms,
        "trailing_silence_trimmed_ms": r.trailing_silence_trimmed_ms,
        "silence_trimmed": r.silence_trimmed,
        "plosive_reduced": r.plosive_reduced,
    }


def _pipeline_to_dict(enh, mas) -> dict:
    return {
        "noise_detected": getattr(enh, "noise_detected", None),
        "input_lufs": round(mas.input_lufs, 2),
        "output_lufs": round(mas.output_lufs, 2),
        "output_true_peak_dbfs": round(mas.output_true_peak_dbfs, 2),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/uploads", response_model=UploadResponse, status_code=202)
async def upload_audio(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    title: str = "Untitled",
    description: str | None = None,
    category: str = "Founder Stories",
    publish_immediate: bool = False,
    creator_id: str | None = None,
    output_format: str = "mp3",
    principal: Principal = Depends(require_principal),
):
    """Accept a raw audio upload, create an episode draft, queue studio processing, return a job id."""
    if output_format not in ALLOWED_OUTPUT:
        raise HTTPException(status_code=422, detail="output_format must be 'mp3' or 'wav'")
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=422, detail="empty upload")
    if len(data) > UPLOAD_LIMIT_BYTES:
        raise HTTPException(status_code=413, detail="upload exceeds 200 MB limit")

    asset_id = uuid.uuid4().hex
    job_id = secrets.token_urlsafe(16)
    uploads_dir = request.app.state.settings.data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    raw_path = uploads_dir / f"{asset_id}.raw"
    raw_path.write_bytes(data)

    now = int(time.time())
    jobs = _jobs(request)
    await jobs.create_job(job_id, principal.subject, creator_id, title, str(raw_path), asset_id, now)

    # Ensure creator user exists in repository so foreign keys succeed
    repo = request.app.state.repository
    user = await repo.get_user_by_id(principal.subject)
    if user is None:
        try:
            await repo.create_user(
                principal.subject, f"{principal.subject}@oxiverse.local",
                principal.subject, "nopass", True, now,
            )
        except Exception:
            pass

    # Create episode record upfront in draft or processing state so creator can safely navigate away
    episode_id = "ep_" + secrets.token_hex(12)
    init_status = "processing" if publish_immediate else "draft"
    pub_ready = 1 if publish_immediate else 0
    await repo.create_episode(
        episode_id, asset_id, principal.subject, (title or "Untitled").strip(),
        description, category, "public", 0.0, now,
        status=init_status, publish_on_ready=pub_ready,
    )

    # Queue the work off the event loop (CPU-bound ffmpeg + DSP).
    loop = asyncio.get_event_loop()
    request.app.state.loop = loop
    loop.run_in_executor(
        None,
        lambda: _process_job(request, job_id, asset_id, str(raw_path), principal.subject, output_format),
    )
    return UploadResponse(
        job_id=job_id, asset_id=asset_id, episode_id=episode_id, status="queued",
        status_url=f"/v1/uploads/{job_id}",
    )


@router.get("/uploads/{job_id}", response_model=JobStatusResponse)
async def get_upload_status(request: Request, job_id: str, principal: Principal = Depends(require_principal)):
    jobs = _jobs(request)
    job: JobRecord | None = await jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_user_id != principal.subject:
        raise HTTPException(status_code=403, detail="not your job")
    download = None
    if job.status == "ready":
        signer = _signer(request)
        download = {}
        if job.mastered_key_mp3:
            download["mp3"] = (
                f"/v1/cdn/{job.asset_id}/mastered.mp3?cap="
                f"{signer.sign(job.mastered_key_mp3, 300)}"
            )
        if job.mastered_key_wav:
            download["wav"] = (
                f"/v1/cdn/{job.asset_id}/mastered.wav?cap="
                f"{signer.sign(job.mastered_key_wav, 300)}"
            )
        if job.raw_key_mp3:
            download["raw"] = (
                f"/v1/cdn/{job.asset_id}/raw.mp3?cap="
                f"{signer.sign(job.raw_key_mp3, 300)}"
            )
    return JobStatusResponse(
        job_id=job.job_id, asset_id=job.asset_id, title=job.title, status=job.status,
        created_at=job.created_at, updated_at=job.updated_at, report=job.report,
        error=job.error, download=download,
    )


@router.get("/cdn/{asset_id}/{filename}")
async def serve_stored(request: Request, asset_id: str, filename: str, cap: str = ""):
    """Signed local delivery of a stored mastered or raw audio file."""
    if filename not in ("mastered.mp3", "mastered.wav", "raw.mp3"):
        raise HTTPException(status_code=404, detail="unknown file")
    key = f"assets/{asset_id}/{filename}"
    signer = _signer(request)
    if not signer.verify(key, cap):
        raise HTTPException(status_code=403, detail="invalid or expired signed URL")
    store = _store(request)
    if not store.exists(key):
        raise HTTPException(status_code=404, detail="not found")
    data = store.get(key)
    media_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav"
    return Response(content=data, media_type=media_type, headers={"Cache-Control": "public, max-age=31536000, immutable"})
