"""Variant streaming service: personalization by manifest, bytes by CDN.

A listener session owns a 32-bit attribution id whose 64-bit codeword selects, per segment,
one of two pre-published variants. Generating a playlist is therefore pure signing work --
no decode, no embed, no encode -- which is what allows one origin instance to serve very many
concurrent listeners while Cloudflare serves the actual audio.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from urllib.parse import urlencode

from .config import Settings
from .ingest import IngestResult, asset_content_iv, segment_object_key
from .models import SessionRecord, VariantAssetRecord
from .repository import Repository
from .security import Principal, derive_watermark_id, issue_signed_token
from .service import ServiceError
from .storage import ObjectStore, sign_object_url
from .variant_watermark import VariantWatermarker


class VariantStreamingService:
    """Authorization, session issuance, and signed manifest generation for CDN delivery."""

    def __init__(self, settings: Settings, repository: Repository, store: ObjectStore):
        self.settings = settings
        self.repository = repository
        self.store = store
        self._watermarkers: dict[str, VariantWatermarker] = {}
        self._metrics: dict[str, float] = {"manifests_issued": 0, "sessions_created": 0, "manifest_latency_ms_total": 0.0}
        self._lock = asyncio.Lock()

    # --- ingest ---------------------------------------------------------------

    async def register_ingested_asset(self, title: str, result: IngestResult) -> VariantAssetRecord:
        if await self.repository.get_variant_asset(result.asset_id) is not None:
            raise ServiceError("asset_id already exists", 409)
        record = VariantAssetRecord(
            asset_id=result.asset_id,
            title=title,
            source_sha256=result.source_sha256,
            sample_rate=result.sample_rate,
            channels=result.channels,
            segment_samples=result.segment_samples,
            segment_count=result.segment_count,
            duration_samples=result.duration_samples,
            created_at=int(time.time()),
        )
        await self.repository.save_variant_asset(record)
        await self.repository.audit(
            "variant_asset_ingested", "success", asset_id=record.asset_id,
            details={"segments": record.segment_count, "objects": result.published_objects},
        )
        return record

    # --- sessions -------------------------------------------------------------

    async def create_session(self, principal: Principal, asset_id: str) -> SessionRecord:
        asset = await self.repository.get_variant_asset(asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        if not await self.repository.has_variant_entitlement(asset_id, principal.subject):
            await self.repository.audit("variant_session_create", "denied", asset_id=asset_id, user_id=principal.subject)
            raise ServiceError("asset entitlement required", 403)
        now = int(time.time())
        if await self.repository.active_variant_session_count(principal.subject, now) >= self.settings.max_active_sessions_per_user:
            raise ServiceError("active session limit reached", 429)
        for _ in range(5):
            session_id = secrets.token_urlsafe(24)
            record = SessionRecord(
                session_id=session_id,
                asset_id=asset_id,
                user_id=principal.subject,
                watermark_id=derive_watermark_id(self.settings.watermark_secret, principal.subject, asset_id, session_id),
                created_at=now,
                expires_at=now + self.settings.session_ttl_seconds,
                status="active",
            )
            try:
                await self.repository.create_variant_session(record)
            except Exception as exc:
                if "watermark_mappings" not in str(exc):
                    raise
                continue
            async with self._lock:
                self._metrics["sessions_created"] += 1
            await self.repository.audit(
                "variant_session_create", "success", session_id=session_id, asset_id=asset_id, user_id=principal.subject
            )
            return record
        raise ServiceError("could not allocate unique attribution token", 503)

    async def validate_session(self, principal: Principal, session_id: str, asset_id: str) -> SessionRecord:
        session = await self.repository.get_variant_session(session_id)
        now = int(time.time())
        if session is None or session.asset_id != asset_id or session.status != "active" or session.expires_at <= now:
            raise ServiceError("stream session is unavailable", 404)
        if principal.subject != session.user_id:
            await self.repository.audit(
                "variant_stream_access", "denied", session_id=session_id, asset_id=asset_id, user_id=principal.subject
            )
            raise ServiceError("stream session is not owned by this user", 403)
        return session

    async def revoke_session(self, principal: Principal, session_id: str) -> None:
        session = await self.repository.get_variant_session(session_id)
        if session is None:
            raise ServiceError("stream session is unavailable", 404)
        if principal.role != "admin" and principal.subject != session.user_id:
            raise ServiceError("stream session is not owned by this user", 403)
        await self.repository.revoke_variant_session(session_id)
        await self.repository.audit(
            "variant_session_revoked", "success", session_id=session_id, asset_id=session.asset_id, user_id=session.user_id
        )

    def _watermarker(self, asset_id: str) -> VariantWatermarker:
        """Cache the per-asset keyed bit permutation used to map segments to codeword bits."""

        watermarker = self._watermarkers.get(asset_id)
        if watermarker is None:
            watermarker = VariantWatermarker(
                self.settings.watermark_secret,
                asset_id,
                self.settings.variant_frame_samples,
                self.settings.variant_watermark_strength,
            )
            self._watermarkers[asset_id] = watermarker
        return watermarker

    # --- capabilities and manifests ------------------------------------------

    def capability(self, kind: str, session: SessionRecord) -> str:
        ttl = min(self.settings.capability_ttl_seconds, max(1, session.expires_at - int(time.time())))
        claims = {"kind": kind, "sid": session.session_id, "asset": session.asset_id, "sub": session.user_id}
        return issue_signed_token(self.settings.capability_secret, claims, ttl)

    def manifest_url(self, session: SessionRecord) -> str:
        query = urlencode({"cap": self.capability("variant-playlist", session)})
        return f"/v1/variant-streams/{session.session_id}/playlist.m3u8?{query}"

    def _segment_url(self, asset_id: str, sequence: int, variant: int, expires_at: int) -> str:
        key = segment_object_key(asset_id, sequence, variant)
        signature = sign_object_url(self.settings.capability_secret, key, expires_at)
        base = self.settings.cdn_base_url or "/v1/cdn"
        return f"{base.rstrip('/')}/{key}?{signature}"

    async def manifest_window(self, session: SessionRecord, sequences: list[int]) -> str:
        """Render a windowed playlist over the given segment indices (metering-friendly)."""

        asset = await self.repository.get_variant_asset(session.asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        watermarker = self._watermarker(asset.asset_id)
        duration = asset.segment_samples / asset.sample_rate
        expires_at = min(int(time.time()) + self.settings.cdn_url_ttl_seconds, session.expires_at)
        key_query = urlencode({"cap": self.capability("variant-key", session)})
        key_uri = f"/v1/variant-streams/{session.session_id}/keys/main?{key_query}"
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{int(duration) + 1}",
                 "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
        for sequence in sequences:
            variant = watermarker.variant_for(session.watermark_id, sequence)
            iv = asset_content_iv(asset.asset_id, sequence, variant).hex()
            lines.append(f'#EXT-X-KEY:METHOD=AES-128,URI="{key_uri}",IV=0x{iv}')
            lines.append(f"#EXTINF:{duration:.3f},")
            lines.append(self._segment_url(asset.asset_id, sequence, variant, expires_at))
        lines.append("#EXT-X-ENDLIST")
        async with self._lock:
            self._metrics["manifests_issued"] += 1
        return "\n".join(lines) + "\n"

    async def manifest(self, session: SessionRecord) -> str:
        """Render the full personalized playlist (kept for completeness; playback uses windows)."""

        asset = await self.repository.get_variant_asset(session.asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        return await self.manifest_window(session, list(range(asset.segment_count)))

    async def record_latency(self, latency_ms: float) -> None:
        async with self._lock:
            self._metrics["manifest_latency_ms_total"] += latency_ms

    async def metrics(self) -> dict[str, float]:
        async with self._lock:
            return dict(self._metrics)
