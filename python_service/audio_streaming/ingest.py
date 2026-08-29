"""Ingest: decode -> 48 kHz stereo -> segment -> embed both variants -> AAC/TS -> encrypt -> publish.

This is the only place a codec runs per unit of content. It runs ONCE per asset at upload
time and produces two immutable, CDN-cacheable files per segment. Playback afterwards costs
the origin nothing but a signed manifest.

Encryption note: the AES-128 key is derived per asset, not per session, because per-session
ciphertext would defeat CDN caching. Per-listener secrecy comes from the signed manifest plus
the short-TTL key endpoint; per-listener *attribution* comes from the variant choices.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import Settings
from .hls import encrypt_segment
from .security import derive_key
from .storage import ObjectStore
from .variant_watermark import VariantWatermarker


class IngestError(ValueError):
    """Raised for an unusable or out-of-bounds source upload."""


@dataclass(frozen=True)
class IngestResult:
    asset_id: str
    source_sha256: str
    sample_rate: int
    channels: int
    segment_samples: int
    segment_count: int
    duration_samples: int
    segment_duration_seconds: float
    published_objects: int


def asset_content_key(master_secret: bytes, asset_id: str) -> bytes:
    """Per-asset AES-128 content key; identical for both variants so segments stay cacheable."""

    return derive_key(master_secret, "variant-content-aes128-v1", asset_id, length=16)


def asset_content_iv(asset_id: str, sequence: int, variant: int) -> bytes:
    """Deterministic public IV; distinct per (asset, segment, variant) as CBC requires."""

    if sequence < 0 or variant not in (0, 1):
        raise ValueError("invalid segment sequence or variant")
    return derive_key(
        b"variant-iv-public-domain-separation", "variant-aes128-iv-v1", asset_id, str(sequence), str(variant), length=16
    )


def segment_object_key(asset_id: str, sequence: int, variant: int) -> str:
    """Stable CDN path. Immutable content, so it can be cached forever."""

    return f"assets/{asset_id}/v{variant}/{sequence:06d}.ts"


def decode_to_pcm(source: Path, settings: Settings) -> np.ndarray:
    """Decode any ffmpeg-readable upload to float32 PCM at the configured rate and channels."""

    if shutil.which("ffmpeg") is None:
        raise IngestError("ffmpeg is required for ingest but was not found on PATH")
    size = source.stat().st_size
    if size == 0:
        raise IngestError("uploaded source is empty")
    if size > settings.ingest_max_bytes:
        raise IngestError("uploaded source exceeds the configured maximum size")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source),
        "-map", "0:a:0", "-t", str(settings.ingest_max_duration_seconds),
        "-ar", str(settings.variant_sample_rate), "-ac", str(settings.variant_channels),
        "-c:a", "pcm_f32le", "-f", "wav", "pipe:1",
    ]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise IngestError("source decoding timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise IngestError(f"source could not be decoded: {exc.stderr.decode('utf-8', 'replace')[:180]}") from exc
    import io

    samples, rate = sf.read(io.BytesIO(result.stdout), dtype="float32", always_2d=True)
    if samples.size == 0:
        raise IngestError("source contains no audio samples")
    if rate != settings.variant_sample_rate:  # pragma: no cover - ffmpeg guarantees the rate
        raise IngestError("decoded sample rate did not match configuration")
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(samples)))
    if peak > 0.98:
        samples = samples * (0.98 / peak)
    return samples.astype(np.float32, copy=False)


def encode_variant_segment(samples: np.ndarray, settings: Settings) -> bytes:
    """Encode one personalized-variant PCM block to AAC in MPEG-TS for HLS delivery."""

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "f32le", "-ar", str(settings.variant_sample_rate), "-ac", str(settings.variant_channels),
        "-i", "pipe:0", "-c:a", "aac", "-b:a", settings.variant_bitrate, "-f", "mpegts", "pipe:1",
    ]
    interleaved = np.asarray(samples, dtype="<f4").reshape(-1)
    try:
        result = subprocess.run(
            command, input=interleaved.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=120
        )
    except subprocess.CalledProcessError as exc:
        raise IngestError(f"variant encoding failed: {exc.stderr.decode('utf-8', 'replace')[:180]}") from exc
    if not result.stdout:
        raise IngestError("variant encoder produced no output")
    return result.stdout


def ingest_asset(
    asset_id: str,
    source: Path,
    settings: Settings,
    store: ObjectStore,
    progress: "callable | None" = None,
) -> IngestResult:
    """Build and publish variant 0 and variant 1 for every segment of one asset."""

    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    pcm = decode_to_pcm(source, settings)
    duration_samples = int(pcm.shape[0])
    segment_samples = settings.variant_segment_samples
    segment_count = max(1, math.ceil(duration_samples / segment_samples))
    padded = segment_count * segment_samples
    if padded > duration_samples:
        pcm = np.pad(pcm, ((0, padded - duration_samples), (0, 0)))

    watermarker = VariantWatermarker(
        settings.watermark_secret, asset_id, settings.variant_frame_samples, settings.variant_watermark_strength
    )
    key = asset_content_key(settings.segment_key_secret, asset_id)
    published = 0
    for sequence in range(segment_count):
        start = sequence * segment_samples
        block = pcm[start : start + segment_samples]
        for variant in (0, 1):
            marked = watermarker.embed(block, start, variant)
            transport_stream = encode_variant_segment(marked, settings)
            payload = encrypt_segment(transport_stream, key, asset_content_iv(asset_id, sequence, variant))
            store.put(segment_object_key(asset_id, sequence, variant), payload, "video/MP2T")
            published += 1
        if progress is not None:
            progress(sequence + 1, segment_count)
    return IngestResult(
        asset_id=asset_id,
        source_sha256=digest.hexdigest(),
        sample_rate=settings.variant_sample_rate,
        channels=settings.variant_channels,
        segment_samples=segment_samples,
        segment_count=segment_count,
        duration_samples=duration_samples,
        segment_duration_seconds=segment_samples / settings.variant_sample_rate,
        published_objects=published,
    )
