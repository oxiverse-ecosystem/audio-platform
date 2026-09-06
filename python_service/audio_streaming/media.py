"""One-time source validation/normalization and per-segment AAC-in-TS encoding."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import Settings
from .models import AssetRecord


class MediaValidationError(ValueError):
    """Raised for invalid or out-of-bound source assets."""


@dataclass(frozen=True)
class PreparedAudio:
    asset: AssetRecord
    samples: np.ndarray


def decode_source_b64(encoded: str, max_bytes: int) -> bytes:
    """Decode a bounded base64 source and reject oversized/malformed payloads early."""

    if len(encoded) > (max_bytes * 4 // 3) + 8:
        raise MediaValidationError("source exceeds configured maximum")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # base64 errors differ by Python version
        raise MediaValidationError("audio_b64 is not valid base64") from exc
    if not raw or len(raw) > max_bytes:
        raise MediaValidationError("source exceeds configured maximum")
    return raw


def _normalize(raw: bytes, settings: Settings) -> np.ndarray:
    try:
        source, input_rate = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
    except Exception as exc:
        raise MediaValidationError("source could not be decoded as a supported audio file") from exc
    if source.size == 0 or input_rate <= 0:
        raise MediaValidationError("source has no usable samples")
    if source.shape[0] > settings.sample_rate * 60 * 30:
        raise MediaValidationError("source duration exceeds the MVP limit")
    mono = np.mean(source, axis=1, dtype=np.float32)
    if input_rate != settings.sample_rate:
        divisor = int(np.gcd(input_rate, settings.sample_rate))
        mono = resample_poly(mono, settings.sample_rate // divisor, input_rate // divisor).astype(np.float32)
    mono = np.nan_to_num(mono, nan=0.0, posinf=0.0, neginf=0.0)
    rms = float(np.sqrt(np.mean(np.square(mono), dtype=np.float64)))
    if rms > 1e-7:
        mono *= min(0.18 / rms, 1.0)
    peak = float(np.max(np.abs(mono)))
    if peak > 0.98:
        mono *= 0.98 / peak
    return mono.astype(np.float32, copy=False)


def prepare_asset(asset_id: str, title: str, encoded: str, settings: Settings) -> PreparedAudio:
    """Normalize once to fixed mono PCM and align the stored intermediate to HLS segment boundaries."""

    raw = decode_source_b64(encoded, settings.source_max_bytes)
    normalized = _normalize(raw, settings)
    duration_samples = len(normalized)
    segment_count = int(np.ceil(duration_samples / settings.segment_samples))
    padded_samples = segment_count * settings.segment_samples
    if padded_samples > duration_samples:
        normalized = np.pad(normalized, (0, padded_samples - duration_samples))
    assets_dir = settings.data_dir / "prepared-assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / f"{asset_id}.npy"
    with tempfile.NamedTemporaryFile(dir=assets_dir, suffix=".npy", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        np.save(temporary, normalized, allow_pickle=False)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    asset = AssetRecord(
        asset_id=asset_id,
        title=title,
        source_path=str(target),
        source_sha256=hashlib.sha256(raw).hexdigest(),
        sample_rate=settings.sample_rate,
        channels=1,
        segment_samples=settings.segment_samples,
        segment_count=segment_count,
        duration_samples=duration_samples,
        created_at=int(__import__("time").time()),
    )
    return PreparedAudio(asset=asset, samples=normalized)


def load_segment(asset: AssetRecord, sequence: int) -> np.ndarray:
    """Memory-map a prepared intermediate and return exactly one aligned segment."""

    if sequence < 0 or sequence >= asset.segment_count:
        raise IndexError("segment sequence is out of range")
    source = np.load(asset.source_path, mmap_mode="r", allow_pickle=False)
    start = sequence * asset.segment_samples
    return np.asarray(source[start : start + asset.segment_samples], dtype=np.float32).copy()


def encode_aac_transport_stream(samples: np.ndarray, settings: Settings | None = None,
                                sample_rate: int | None = None) -> bytes:
    """Encode one bounded personalized PCM segment as HLS-compatible AAC in MPEG-TS."""

    sr = sample_rate or (settings.sample_rate if settings else 16000)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-c:a", "aac", "-b:a", "96k", "-f", "mpegts", "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            input=np.asarray(samples, dtype="<f4").tobytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required for AAC HLS segment encoding") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("AAC segment encoding timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"AAC segment encoding failed: {exc.stderr.decode('utf-8', 'replace')[:180]}") from exc
    if not result.stdout:
        raise RuntimeError("AAC segment encoder produced no output")
    return result.stdout

