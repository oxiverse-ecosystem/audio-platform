"""Stable API and internal record models for the streaming service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AssetRegistration(BaseModel):
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$")
    title: str = Field(min_length=1, max_length=256)
    audio_b64: str = Field(min_length=1)
    entitled_user_ids: list[str] = Field(default_factory=list, max_length=10_000)

    @field_validator("entitled_user_ids")
    @classmethod
    def unique_entitlements(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("entitled_user_ids must not contain duplicates")
        return cleaned


class EntitlementUpdate(BaseModel):
    user_id: str = Field(min_length=1, max_length=256)
    allowed: bool


class StreamSessionRequest(BaseModel):
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$")


class StreamSessionResponse(BaseModel):
    session_id: str
    asset_id: str
    expires_at: int
    playlist_url: str


class AttributionVerifyRequest(BaseModel):
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$")
    watermark_id: int = Field(ge=0, le=2**32 - 1)


class AttributionVerifyResponse(BaseModel):
    matched: bool
    session_id: str | None = None
    user_audit_hash: str | None = None
    created_at: int | None = None


class EnhanceRequest(BaseModel):
    """Single enhancement entry point.

    ``audio_b64`` is a base64-encoded WAV/MP3/OGG file. The full pipeline
    (noise reduction when the VAD finds a usable floor, then studio mastering)
    runs server-side; there is no separate enhance or master endpoint.

    ``enhancement`` / ``mastering`` are optional per-request overrides (flat dicts of
    ``EnhancementSettings`` / ``MasteringSettings`` fields) so a caller can tune the
    processing without redeploying -- e.g. ``{"mastering": {"enable_limiter": false}}``
    to keep an already-mastered recording untouched. Unknown keys are rejected.
    """

    audio_b64: str = Field(min_length=1)
    output_format: Literal["mp3", "wav"] = "mp3"
    enhancement: dict[str, object] | None = None
    mastering: dict[str, object] | None = None


class EnhanceResponse(BaseModel):
    """Processed audio plus the full pipeline analysis report.

    ``audio_b64`` is the enhanced audio encoded in the container named by ``filename``
    (``.mp3`` or ``.wav``) and described by ``media_type``. This is the single enhancement
    entry point: the enhancer and mastering stages are not exposed separately.
    """

    filename: str
    media_type: str
    audio_b64: str
    report: dict


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    title: str
    source_path: str
    source_sha256: str
    sample_rate: int
    channels: int
    segment_samples: int
    segment_count: int
    duration_samples: int
    created_at: int


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    asset_id: str
    user_id: str
    watermark_id: int
    created_at: int
    expires_at: int
    status: Literal["active", "revoked", "expired"]


@dataclass(frozen=True)
class VariantAssetRecord:
    """An asset whose segments are pre-published as two watermarked CDN variants."""

    asset_id: str
    title: str
    source_sha256: str
    sample_rate: int
    channels: int
    segment_samples: int
    segment_count: int
    duration_samples: int
    created_at: int


class VariantIngestResponse(BaseModel):
    asset_id: str
    title: str
    sample_rate: int
    channels: int
    segment_count: int
    duration_seconds: float
    segment_duration_seconds: float
    published_objects: int


class VariantSessionRequest(BaseModel):
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$")


class VariantSessionResponse(BaseModel):
    session_id: str
    asset_id: str
    expires_at: int
    manifest_url: str


class VariantForensicSegment(BaseModel):
    """One recovered segment: its index plus base64 PCM float32 samples."""

    sequence: int = Field(ge=0)
    samples_b64: str = Field(min_length=1)


class VariantForensicRequest(BaseModel):
    asset_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$")
    segments: list[VariantForensicSegment] = Field(min_length=1, max_length=512)


class VariantForensicResponse(BaseModel):
    watermark_id: int | None = None
    crc_valid: bool
    matched: bool
    session_id: str | None = None
    user_audit_hash: str | None = None
    created_at: int | None = None


