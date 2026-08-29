"""Runtime configuration with explicit safe limits for the MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _secret(name: str, default: str, environment: str) -> bytes:
    value = os.getenv(name, default)
    if environment == "production" and value == default:
        raise RuntimeError(f"{name} must be provided in production")
    if len(value) < 32:
        raise RuntimeError(f"{name} must be at least 32 characters")
    return value.encode("utf-8")


@dataclass(frozen=True)
class Settings:
    """Settings are intentionally small and suitable for twelve-factor deployment."""

    environment: str
    data_dir: Path
    database_path: Path
    auth_secret: bytes
    capability_secret: bytes
    watermark_secret: bytes
    segment_key_secret: bytes
    sample_rate: int = 16_000
    channels: int = 1
    frame_samples: int = 512
    frames_per_segment: int = 64
    watermark_strength: float = 0.004
    source_max_bytes: int = 20 * 1024 * 1024
    cache_max_bytes: int = 96 * 1024 * 1024
    session_cache_max_bytes: int = 96 * 1024 * 1024
    worker_concurrency: int = 2
    request_limit_per_minute: int = 180
    capability_ttl_seconds: int = 120
    session_ttl_seconds: int = 20 * 60
    max_active_sessions_per_user: int = 4

    # --- Production A/B variant streaming path (CDN-backed, 48 kHz stereo) ---
    variant_sample_rate: int = 48_000
    variant_channels: int = 2
    variant_frame_samples: int = 4_096
    variant_segment_seconds: float = 4.0
    variant_bitrate: str = "128k"
    variant_watermark_strength: float = 0.0025
    ingest_max_bytes: int = 512 * 1024 * 1024
    ingest_max_duration_seconds: int = 6 * 60 * 60
    cdn_base_url: str = ""
    cdn_url_ttl_seconds: int = 300
    object_store_backend: str = "local"
    object_store_bucket: str = ""
    object_store_endpoint: str = ""
    object_store_access_key: str = ""
    object_store_secret_key: str = ""

    @property
    def segment_samples(self) -> int:
        return self.frame_samples * self.frames_per_segment

    @property
    def variant_segment_samples(self) -> int:
        """Segment length aligned to a whole number of watermark analysis frames."""

        raw = int(self.variant_sample_rate * self.variant_segment_seconds)
        hop = self.variant_frame_samples // 2
        return max(hop * 2, (raw // hop) * hop)

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("AUDIO_ENV", "development").strip().lower()
        data_dir = Path(os.getenv("AUDIO_DATA_DIR", "./runtime-data")).resolve()
        database_path = Path(os.getenv("AUDIO_DATABASE_PATH", str(data_dir / "streaming.db"))).resolve()
        settings = cls(
            environment=environment,
            data_dir=data_dir,
            database_path=database_path,
            auth_secret=_secret("AUDIO_AUTH_SECRET", "development-auth-secret-change-before-production", environment),
            capability_secret=_secret("AUDIO_CAPABILITY_SECRET", "development-capability-secret-change-production", environment),
            watermark_secret=_secret("AUDIO_WATERMARK_SECRET", "development-watermark-secret-change-production", environment),
            segment_key_secret=_secret("AUDIO_SEGMENT_KEY_SECRET", "development-segment-key-secret-change-production", environment),
            sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "16000")),
            channels=int(os.getenv("AUDIO_CHANNELS", "1")),
            frame_samples=int(os.getenv("AUDIO_FRAME_SAMPLES", "512")),
            frames_per_segment=int(os.getenv("AUDIO_FRAMES_PER_SEGMENT", "64")),
            watermark_strength=float(os.getenv("AUDIO_WATERMARK_STRENGTH", "0.004")),
            source_max_bytes=int(os.getenv("AUDIO_SOURCE_MAX_BYTES", str(20 * 1024 * 1024))),
            cache_max_bytes=int(os.getenv("AUDIO_CACHE_MAX_BYTES", str(96 * 1024 * 1024))),
            session_cache_max_bytes=int(os.getenv("AUDIO_SESSION_CACHE_MAX_BYTES", str(96 * 1024 * 1024))),
            worker_concurrency=int(os.getenv("AUDIO_WORKER_CONCURRENCY", "2")),
            request_limit_per_minute=int(os.getenv("AUDIO_REQUEST_LIMIT_PER_MINUTE", "180")),
            capability_ttl_seconds=int(os.getenv("AUDIO_CAPABILITY_TTL_SECONDS", "120")),
            session_ttl_seconds=int(os.getenv("AUDIO_SESSION_TTL_SECONDS", str(20 * 60))),
            max_active_sessions_per_user=int(os.getenv("AUDIO_MAX_ACTIVE_SESSIONS_PER_USER", "4")),
            variant_sample_rate=int(os.getenv("AUDIO_VARIANT_SAMPLE_RATE", "48000")),
            variant_channels=int(os.getenv("AUDIO_VARIANT_CHANNELS", "2")),
            variant_frame_samples=int(os.getenv("AUDIO_VARIANT_FRAME_SAMPLES", "4096")),
            variant_segment_seconds=float(os.getenv("AUDIO_VARIANT_SEGMENT_SECONDS", "4.0")),
            variant_bitrate=os.getenv("AUDIO_VARIANT_BITRATE", "128k"),
            variant_watermark_strength=float(os.getenv("AUDIO_VARIANT_WATERMARK_STRENGTH", "0.0025")),
            ingest_max_bytes=int(os.getenv("AUDIO_INGEST_MAX_BYTES", str(512 * 1024 * 1024))),
            ingest_max_duration_seconds=int(os.getenv("AUDIO_INGEST_MAX_DURATION_SECONDS", str(6 * 60 * 60))),
            cdn_base_url=os.getenv("AUDIO_CDN_BASE_URL", "").strip(),
            cdn_url_ttl_seconds=int(os.getenv("AUDIO_CDN_URL_TTL_SECONDS", "300")),
            object_store_backend=os.getenv("AUDIO_OBJECT_STORE_BACKEND", "local").strip().lower(),
            object_store_bucket=os.getenv("AUDIO_OBJECT_STORE_BUCKET", "").strip(),
            object_store_endpoint=os.getenv("AUDIO_OBJECT_STORE_ENDPOINT", "").strip(),
            object_store_access_key=os.getenv("AUDIO_OBJECT_STORE_ACCESS_KEY", ""),
            object_store_secret_key=os.getenv("AUDIO_OBJECT_STORE_SECRET_KEY", ""),
        )
        if settings.sample_rate <= 0 or settings.channels != 1:
            raise RuntimeError("This MVP accepts only mono PCM normalization at a positive sample rate")
        if settings.segment_samples % settings.frame_samples != 0:
            raise RuntimeError("Segment samples must align to whole watermark frames")
        if settings.worker_concurrency < 1 or settings.worker_concurrency > 16:
            raise RuntimeError("AUDIO_WORKER_CONCURRENCY must be between 1 and 16")
        if settings.variant_channels not in (1, 2):
            raise RuntimeError("AUDIO_VARIANT_CHANNELS must be 1 or 2")
        if settings.variant_frame_samples % 2 != 0:
            raise RuntimeError("AUDIO_VARIANT_FRAME_SAMPLES must be even for overlap-add embedding")
        if settings.variant_segment_samples % (settings.variant_frame_samples // 2) != 0:
            raise RuntimeError("Variant segment length must align to whole watermark hops")
        if settings.object_store_backend not in ("local", "s3"):
            raise RuntimeError("AUDIO_OBJECT_STORE_BACKEND must be 'local' or 's3'")
        if settings.object_store_backend == "s3" and not (
            settings.object_store_bucket and settings.object_store_endpoint
            and settings.object_store_access_key and settings.object_store_secret_key
        ):
            raise RuntimeError("S3/R2 object storage requires bucket, endpoint, and credentials")
        if environment == "production" and not settings.cdn_base_url:
            raise RuntimeError("AUDIO_CDN_BASE_URL must be provided in production")
        return settings
