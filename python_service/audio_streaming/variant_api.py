"""Variant streaming API: multipart ingest, personalized manifests, and forensic attribution.

The hot path (`/playlist.m3u8`) does no media work. Segment bytes are served by the CDN from
signed, immutable URLs; the dev-only `/v1/cdn` endpoint stands in for Cloudflare locally and
enforces the same signature contract a Worker would.
"""

from __future__ import annotations

import base64
import shutil
import tempfile
import time
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse

from .api import optional_principal, require_admin, require_principal
from .ingest import IngestError, asset_content_key, ingest_asset, segment_object_key
from .billing import BillingError, BillingService, QuotaExceeded
from .models import (
    EntitlementUpdate,
    VariantForensicRequest,
    VariantForensicResponse,
    VariantIngestResponse,
    VariantSessionRequest,
    VariantSessionResponse,
)
from .security import Principal, SecurityError, verify_signed_token
from .service import ServiceError
from .storage import StorageError, verify_object_url
from .variant_watermark import VariantWatermarker


router = APIRouter(prefix="/v1", tags=["variant-streaming"])

ASSET_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,95}$"


def _variant_service(request: Request):
    return request.app.state.variant_service


def _settings(request: Request):
    return request.app.state.settings


async def _session_for_capability(request: Request, principal: Principal | None, session_id: str, cap: str, kind: str):
    try:
        claims = verify_signed_token(_settings(request).capability_secret, cap, required_kind=kind)
    except SecurityError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid stream capability") from exc
    if claims.get("sid") != session_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability scope mismatch")
    asset_id, subject = claims.get("asset"), claims.get("sub")
    if not isinstance(asset_id, str) or not isinstance(subject, str):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability subject mismatch")
    if principal is not None and principal.subject != subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability subject mismatch")
    effective = principal or Principal(subject=subject, role="stream-capability")
    try:
        return await _variant_service(request).validate_session(effective, session_id, asset_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/variant-assets", response_model=VariantIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_variant_asset(
    request: Request,
    _: Annotated[Principal, Depends(require_admin)],
    asset_id: Annotated[str, Form(pattern=ASSET_ID_PATTERN)],
    title: Annotated[str, Form(min_length=1, max_length=256)],
    upload: Annotated[UploadFile, File()],
) -> VariantIngestResponse:
    """Stream an upload to disk, then build and publish both watermarked variants of every segment."""

    settings = _settings(request)
    service = _variant_service(request)
    if await service.repository.get_variant_asset(asset_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="asset_id already exists")
    staging = Path(tempfile.mkdtemp(prefix="ingest-", dir=str(settings.data_dir)))
    source = staging / "source.bin"
    written = 0
    try:
        with source.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > settings.ingest_max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="upload exceeds the configured maximum"
                    )
                handle.write(chunk)
        if written == 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="upload is empty")
        try:
            result = await _run_ingest(request, asset_id, source)
        except IngestError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except StorageError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        try:
            record = await service.register_ingested_asset(title, result)
        except ServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return VariantIngestResponse(
        asset_id=record.asset_id,
        title=record.title,
        sample_rate=record.sample_rate,
        channels=record.channels,
        segment_count=record.segment_count,
        duration_seconds=record.duration_samples / record.sample_rate,
        segment_duration_seconds=result.segment_duration_seconds,
        published_objects=result.published_objects,
    )


async def _run_ingest(request: Request, asset_id: str, source: Path):
    """Run the blocking ingest on the bounded worker pool so the event loop stays responsive."""

    settings = _settings(request)
    store = request.app.state.object_store
    pool = request.app.state.streaming_service.worker_pool
    return await pool.run(lambda: ingest_asset(asset_id, source, settings, store), timeout_seconds=1800.0)


@router.put("/variant-assets/{asset_id}/entitlements")
async def update_variant_entitlement(
    request: Request,
    asset_id: str,
    body: EntitlementUpdate,
    _: Annotated[Principal, Depends(require_admin)],
):
    service = _variant_service(request)
    if await service.repository.get_variant_asset(asset_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    await service.repository.set_variant_entitlement(asset_id, body.user_id, body.allowed)
    await service.repository.audit(
        "variant_entitlement_updated", "success", asset_id=asset_id, user_id=body.user_id,
        details={"allowed": body.allowed},
    )
    return {"asset_id": asset_id, "user_id": body.user_id, "allowed": body.allowed}


@router.post("/variant-streams", response_model=VariantSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_variant_session(
    request: Request,
    body: VariantSessionRequest,
    principal: Annotated[Principal, Depends(require_principal)],
) -> VariantSessionResponse:
    service = _variant_service(request)
    try:
        session = await service.create_session(principal, body.asset_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return VariantSessionResponse(
        session_id=session.session_id,
        asset_id=session.asset_id,
        expires_at=session.expires_at,
        manifest_url=service.manifest_url(session),
    )


@router.get("/variant-streams/{session_id}/playlist.m3u8", response_class=PlainTextResponse)
async def variant_playlist(
    request: Request,
    session_id: str,
    cap: Annotated[str, Query(min_length=16)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
    position: Annotated[int, Query(ge=0)] = 0,
) -> PlainTextResponse:
    """Serve a *windowed, metered* manifest.

    Playback is metered per window, not per episode: the player passes ``position`` (the
    segment index it is about to play), and we debit a bounded sliding window of about 5
    minutes that starts there. Because signed CDN URLs expire, the player must return here to
    fetch more; each return advances the window. Retries are idempotent (the grant ledger
    de-dupes by ``(session, sequence)``), so replaying a window never double-charges.
    When the listener's monthly allowance is exhausted, a 402 is returned so the client can
    show an upgrade prompt.
    """

    session = await _session_for_capability(request, principal, session_id, cap, "variant-playlist")
    service = _variant_service(request)
    settings = _settings(request)
    asset = await service.repository.get_variant_asset(session.asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    seconds_each = asset.segment_samples / asset.sample_rate
    window = int(settings.cdn_url_ttl_seconds / seconds_each)
    window = max(1, min(window, asset.segment_count - position)) if position < asset.segment_count else 0
    sequences = list(range(position, min(position + window, asset.segment_count)))
    billing = BillingService(service.repository)
    started = time.perf_counter()
    try:
        auth = await billing.authorize_playback(
            session_id=session_id,
            user_id=session.user_id,
            asset_id=session.asset_id,
            sequences=sequences,
            seconds_each=int(round(asset.segment_samples / asset.sample_rate)),
            now=int(time.time()),
        )
    except QuotaExceeded as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        await service.repository.audit(
            "variant_manifest_denied", "quota", session_id=session_id, asset_id=session.asset_id,
            user_id=session.user_id, latency_ms=latency_ms, details={"reason": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
            headers={"Cache-Control": "private, no-store"},
        ) from exc
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    try:
        manifest = await service.manifest_window(session, sequences)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    latency_ms = (time.perf_counter() - started) * 1000
    await service.record_latency(latency_ms)
    await service.repository.audit(
        "variant_manifest_issued", "success", session_id=session_id, asset_id=session.asset_id,
        user_id=session.user_id, latency_ms=latency_ms,
        details={"position": position, "window": len(sequences), "granted": auth.newly_granted},
    )
    return PlainTextResponse(
        manifest,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "private, no-store",
            "X-Plan-Code": auth.plan_code,
            "X-Consumed-Seconds": str(auth.consumed_seconds),
            "X-Window-Position": str(position),
            "X-Window-Count": str(len(sequences)),
        },
    )


# --- P2: billing administration (all pricing lives in DB rows, never constants) -

def _billing_service(request: Request) -> BillingService:
    return BillingService(request.app.state.repository)


@router.get("/plans")
async def list_plans(
    request: Request, _: Annotated[Principal, Depends(require_admin)], active_only: bool = True,
) -> list[dict]:
    return await request.app.state.repository.list_plans(active_only=active_only)


@router.put("/plans/{plan_code}")
async def update_plan(
    request: Request, plan_code: str, body: dict, _: Annotated[Principal, Depends(require_admin)],
) -> dict:
    """Edit a plan's price or included hours at runtime (this is how X/Y/Z change)."""

    plan = await request.app.state.repository.get_plan(plan_code)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plan not found")
    updated = dict(plan)
    for key in ("name", "price_paise", "included_seconds", "active"):
        if key in body:
            updated[key] = body[key]
    await request.app.state.repository.upsert_plan(updated)
    return updated


@router.post("/creators", status_code=status.HTTP_201_CREATED)
async def create_creator(
    request: Request, body: dict, _: Annotated[Principal, Depends(require_admin)],
) -> dict:
    creator_id = body.get("creator_id")
    if not creator_id or not isinstance(creator_id, str):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="creator_id required")
    await request.app.state.repository.create_creator(
        creator_id, body.get("display_name", creator_id), body.get("payout_reference"),
    )
    await request.app.state.repository.set_asset_creator(body.get("asset_id"), creator_id)
    return {"creator_id": creator_id}


@router.post("/payouts/compute")
async def compute_payout(
    request: Request, period: str, _: Annotated[Principal, Depends(require_admin)],
) -> dict:
    """Compute and persist creator payouts for a monthly period (YYYY-MM)."""

    return await _billing_service(request).compute_payout(period)


@router.get("/variant-streams/{session_id}/keys/main")
async def variant_key(
    request: Request,
    session_id: str,
    cap: Annotated[str, Query(min_length=16)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Response:
    session = await _session_for_capability(request, principal, session_id, cap, "variant-key")
    key = asset_content_key(_settings(request).segment_key_secret, session.asset_id)
    await _variant_service(request).repository.audit(
        "variant_key_issued", "success", session_id=session_id, asset_id=session.asset_id, user_id=session.user_id,
        details={"key_length": len(key)},
    )
    return Response(key, media_type="application/octet-stream", headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.delete("/variant-streams/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_variant_stream(
    request: Request,
    session_id: str,
    principal: Annotated[Principal, Depends(require_principal)],
) -> Response:
    try:
        await _variant_service(request).revoke_session(principal, session_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cdn/{object_key:path}")
async def development_cdn(request: Request, object_key: str, exp: int, sig: str) -> Response:
    """Local stand-in for Cloudflare: verifies the same signed-URL contract, then serves cacheable bytes."""

    settings = _settings(request)
    if settings.cdn_base_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if not verify_object_url(settings.capability_secret, object_key, exp, sig):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or expired object signature")
    try:
        payload = request.app.state.object_store.get(object_key)
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="object not found") from exc
    return Response(
        payload,
        media_type="video/MP2T",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/variant-attribution/verify", response_model=VariantForensicResponse)
async def verify_variant_attribution(
    request: Request,
    body: VariantForensicRequest,
    _: Annotated[Principal, Depends(require_admin)],
) -> VariantForensicResponse:
    """Recover the codeword from leaked audio segments and map it back to a session."""

    settings = _settings(request)
    service = _variant_service(request)
    asset = await service.repository.get_variant_asset(body.asset_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    segments: list[tuple[int, np.ndarray]] = []
    for item in body.segments:
        try:
            raw = base64.b64decode(item.samples_b64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="samples_b64 is not valid base64"
            ) from exc
        if not raw or len(raw) % 4 != 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="samples must be float32 PCM")
        samples = np.frombuffer(raw, dtype="<f4")
        if asset.channels > 1 and samples.size % asset.channels == 0:
            samples = samples.reshape(-1, asset.channels)
        segments.append((item.sequence, np.ascontiguousarray(samples, dtype=np.float32)))
    watermarker = VariantWatermarker(
        settings.watermark_secret, body.asset_id, settings.variant_frame_samples, settings.variant_watermark_strength
    )
    evidence = watermarker.recover(segments, segment_samples=asset.segment_samples)
    match = None
    if evidence.watermark_id is not None:
        match = await service.repository.variant_attribution_lookup(body.asset_id, evidence.watermark_id)
    await service.repository.audit(
        "variant_attribution_verified", "success" if match else "not_found", asset_id=body.asset_id,
        details={"crc_valid": evidence.crc_valid, "segments": len(segments)},
    )
    return VariantForensicResponse(
        watermark_id=evidence.watermark_id,
        crc_valid=evidence.crc_valid,
        matched=match is not None,
        **(match or {}),
    )


@router.get("/variant-operations/metrics")
async def variant_metrics(request: Request, _: Annotated[Principal, Depends(require_admin)]) -> dict[str, float]:
    return await _variant_service(request).metrics()


__all__ = ["router", "segment_object_key"]
