"""Application service for authorization, capabilities, personalized segment creation, and audit events."""

from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from .cache import BackpressureError, BoundedAsyncByteCache, BoundedWorkerPool
from .config import Settings
from .hls import encrypt_segment, segment_iv, segment_key
from .media import PreparedAudio, encode_aac_transport_stream, load_segment, prepare_asset
from .models import AssetRecord, SessionRecord
from .repository import Repository
from .security import Principal, derive_watermark_id, issue_signed_token
from .security import derive_key
from .watermark import SegmentSafeWatermarker


class ServiceError(ValueError):
    """Safe domain exception mapped to a client status code by the API layer."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.status_code = status_code


class StreamingService:
    """Coordinates the costly path while preserving server-only secret material."""

    def __init__(self, settings: Settings, repository: Repository):
        self.settings = settings
        self.repository = repository
        self.worker_pool = BoundedWorkerPool(settings.worker_concurrency)
        self.segment_cache = BoundedAsyncByteCache(settings.session_cache_max_bytes)
        self._watermarkers: dict[str, SegmentSafeWatermarker] = {}
        self._metrics: dict[str, float] = {
            "segment_cache_hits": 0,
            "segment_builds": 0,
            "playlist_requests": 0,
            "playlist_latency_ms_total": 0,
            "segment_requests": 0,
            "segment_latency_ms_total": 0,
            "key_requests": 0,
            "key_latency_ms_total": 0,
        }
        self._metrics_lock = asyncio.Lock()

    @staticmethod
    def _key_derivation_metadata(master_secret: bytes, session_id: str) -> tuple[str, str, str]:
        """Return a non-secret reference for key audit/rotation, never a key or key hash."""

        key_purpose = "hls-segment-aes128"
        derivation_version = "hls-aes128-v1"
        reference = derive_key(master_secret, "hls-key-reference-v1", session_id, length=12).hex()
        return key_purpose, derivation_version, reference

    async def close(self) -> None:
        await self.segment_cache.close()
        await self.worker_pool.close()

    async def register_asset(self, asset_id: str, title: str, audio_b64: str) -> AssetRecord:
        existing = await self.repository.get_asset(asset_id)
        if existing is not None:
            raise ServiceError("asset_id already exists", 409)
        try:
            prepared: PreparedAudio = await self.worker_pool.run(
                lambda: prepare_asset(asset_id, title, audio_b64, self.settings), timeout_seconds=60.0
            )
        except BackpressureError as exc:
            raise ServiceError(str(exc), 503) from exc
        try:
            await self.repository.save_asset(prepared.asset)
        except Exception:
            Path(prepared.asset.source_path).unlink(missing_ok=True)
            raise
        await self.repository.audit("asset_registered", "success", asset_id=asset_id, details={"segments": prepared.asset.segment_count})
        return prepared.asset

    async def set_entitlement(self, asset_id: str, user_id: str, allowed: bool) -> None:
        if await self.repository.get_asset(asset_id) is None:
            raise ServiceError("asset not found", 404)
        await self.repository.set_entitlement(asset_id, user_id, allowed)
        await self.repository.audit("entitlement_updated", "success", asset_id=asset_id, user_id=user_id, details={"allowed": allowed})

    async def create_session(self, principal: Principal, asset_id: str) -> SessionRecord:
        asset = await self.repository.get_asset(asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        if not await self.repository.has_entitlement(asset_id, principal.subject):
            await self.repository.audit("session_create", "denied", asset_id=asset_id, user_id=principal.subject)
            raise ServiceError("asset entitlement required", 403)
        now = int(time.time())
        if await self.repository.active_session_count(principal.subject, now) >= self.settings.max_active_sessions_per_user:
            raise ServiceError("active session limit reached", 429)
        for _ in range(5):
            session_id = secrets.token_urlsafe(24)
            watermark_id = derive_watermark_id(self.settings.watermark_secret, principal.subject, asset_id, session_id)
            record = SessionRecord(
                session_id=session_id,
                asset_id=asset_id,
                user_id=principal.subject,
                watermark_id=watermark_id,
                created_at=now,
                expires_at=now + self.settings.session_ttl_seconds,
                status="active",
            )
            try:
                key_purpose, derivation_version, key_reference = self._key_derivation_metadata(
                    self.settings.segment_key_secret, session_id
                )
                await self.repository.create_session(
                    record,
                    key_purpose=key_purpose,
                    derivation_version=derivation_version,
                    key_reference=key_reference,
                )
                await self.repository.audit("session_create", "success", session_id=session_id, asset_id=asset_id, user_id=principal.subject)
                return record
            except Exception as exc:
                if "watermark_mappings" not in str(exc):
                    raise
        raise ServiceError("could not allocate unique attribution token", 503)

    def _capability(self, kind: str, session: SessionRecord, sequence: int | None = None) -> str:
        claims: dict[str, object] = {"kind": kind, "sid": session.session_id, "asset": session.asset_id, "sub": session.user_id}
        if sequence is not None:
            claims["seq"] = sequence
        ttl = min(self.settings.capability_ttl_seconds, max(1, session.expires_at - int(time.time())))
        return issue_signed_token(self.settings.capability_secret, claims, ttl)

    def playlist_url(self, session: SessionRecord) -> str:
        return f"/v1/streams/{session.session_id}/playlist.m3u8?{urlencode({'cap': self._capability('playlist', session)})}"

    async def validate_session_access(self, principal: Principal, session_id: str, asset_id: str) -> SessionRecord:
        session = await self.repository.get_session(session_id)
        now = int(time.time())
        if session is None or session.asset_id != asset_id or session.status != "active" or session.expires_at <= now:
            raise ServiceError("stream session is unavailable", 404)
        if principal.subject != session.user_id:
            await self.repository.audit("stream_access", "denied", session_id=session_id, asset_id=asset_id, user_id=principal.subject)
            raise ServiceError("stream session is not owned by this user", 403)
        return session

    async def playlist(self, session: SessionRecord) -> str:
        asset = await self.repository.get_asset(session.asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        duration = asset.segment_samples / asset.sample_rate
        target = int(__import__("math").ceil(duration))
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}", "#EXT-X-MEDIA-SEQUENCE:0"]
        for sequence in range(asset.segment_count):
            key_cap = self._capability("hls-key", session)
            iv = segment_iv(session.session_id, sequence).hex()
            key_uri = f"/v1/streams/{session.session_id}/keys/main?{urlencode({'cap': key_cap})}"
            segment_cap = self._capability("segment", session, sequence)
            segment_uri = f"/v1/streams/{session.session_id}/segments/{sequence}.ts?{urlencode({'cap': segment_cap})}"
            lines.extend([f'#EXT-X-KEY:METHOD=AES-128,URI="{key_uri}",IV=0x{iv}', f"#EXTINF:{duration:.3f},", segment_uri])
        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    def _watermarker(self, asset_id: str) -> SegmentSafeWatermarker:
        watermarker = self._watermarkers.get(asset_id)
        if watermarker is None:
            watermarker = SegmentSafeWatermarker(self.settings, self.settings.watermark_secret, asset_id)
            self._watermarkers[asset_id] = watermarker
        return watermarker

    async def encrypted_segment(self, session: SessionRecord, sequence: int) -> bytes:
        asset = await self.repository.get_asset(session.asset_id)
        if asset is None:
            raise ServiceError("asset not found", 404)
        if sequence < 0 or sequence >= asset.segment_count:
            raise ServiceError("segment not found", 404)
        cache_key = f"{session.session_id}:{sequence}"
        before = self.segment_cache.entries

        async def build() -> bytes:
            async with self._metrics_lock:
                self._metrics["segment_builds"] += 1
            def personalize_encode_encrypt() -> bytes:
                segment = load_segment(asset, sequence)
                marked = self._watermarker(asset.asset_id).embed(segment, session.watermark_id, sequence * asset.segment_samples)
                transport_stream = encode_aac_transport_stream(marked, self.settings)
                return encrypt_segment(transport_stream, segment_key(self.settings.segment_key_secret, session.session_id), segment_iv(session.session_id, sequence))
            try:
                return await self.worker_pool.run(personalize_encode_encrypt, timeout_seconds=30.0)
            except BackpressureError as exc:
                raise ServiceError(str(exc), 503) from exc

        payload = await self.segment_cache.get_or_create(cache_key, build)
        if before == self.segment_cache.entries:
            async with self._metrics_lock:
                self._metrics["segment_cache_hits"] += 1
        await self.repository.audit("segment_issued", "success", session_id=session.session_id, asset_id=session.asset_id, user_id=session.user_id, details={"sequence": sequence, "bytes": len(payload)})
        return payload

    async def metrics(self) -> dict[str, float | int]:
        async with self._metrics_lock:
            return {**self._metrics, "cache_entries": self.segment_cache.entries, "cache_bytes": self.segment_cache.bytes_used}

    async def record_latency(self, operation: str, latency_ms: float) -> None:
        """Accumulate safe operation counters for monitoring without exposing caller or secret data."""

        async with self._metrics_lock:
            self._metrics[f"{operation}_requests"] = self._metrics.get(f"{operation}_requests", 0) + 1
            self._metrics[f"{operation}_latency_ms_total"] = self._metrics.get(f"{operation}_latency_ms_total", 0) + latency_ms
