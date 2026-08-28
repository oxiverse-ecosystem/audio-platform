"""HTTP API enforcing identity, ownership, expiring capability, and entitlement at every access point."""

from __future__ import annotations

import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse

from .hls import segment_key
from .models import (
    AssetRegistration,
    AttributionVerifyRequest,
    AttributionVerifyResponse,
    EntitlementUpdate,
    StreamSessionRequest,
    StreamSessionResponse,
)
from .security import Principal, SecurityError, verify_identity, verify_signed_token
from .service import ServiceError, StreamingService


router = APIRouter(prefix="/v1", tags=["streaming"])


def _service(request: Request) -> StreamingService:
    return request.app.state.streaming_service


def _settings(request: Request):
    return request.app.state.settings


async def require_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Require a server-signed identity token; bearer identity is also rechecked against stream ownership."""

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer identity required")
    try:
        return verify_identity(_settings(request).auth_secret, authorization.removeprefix("Bearer ").strip())
    except SecurityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer identity") from exc


async def optional_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal | None:
    """Validate an identity if supplied; HLS subrequests instead use their signed capability."""

    if authorization is None:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer identity")
    try:
        return verify_identity(_settings(request).auth_secret, authorization.removeprefix("Bearer ").strip())
    except SecurityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer identity") from exc


async def require_admin(principal: Annotated[Principal, Depends(require_principal)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator role required")
    return principal


def _capability(request: Request, value: str, kind: str, session_id: str, sequence: int | None = None) -> dict[str, object]:
    try:
        claims = verify_signed_token(_settings(request).capability_secret, value, required_kind=kind)
    except SecurityError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid stream capability") from exc
    if claims.get("sid") != session_id or (sequence is not None and claims.get("seq") != sequence):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability scope mismatch")
    return claims


async def _session_for_capability(
    request: Request,
    principal: Principal | None,
    session_id: str,
    capability: str,
    kind: str,
    sequence: int | None = None,
):
    claims = _capability(request, capability, kind, session_id, sequence)
    asset_id = claims.get("asset")
    subject = claims.get("sub")
    if not isinstance(asset_id, str) or not isinstance(subject, str):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability subject mismatch")
    if principal is not None and subject != principal.subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream capability subject mismatch")
    effective_principal = principal or Principal(subject=subject, role="stream-capability")
    try:
        return await _service(request).validate_session_access(effective_principal, session_id, asset_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def register_asset(
    request: Request,
    body: AssetRegistration,
    _: Annotated[Principal, Depends(require_admin)],
):
    service = _service(request)
    try:
        asset = await service.register_asset(body.asset_id, body.title, body.audio_b64)
        for user_id in body.entitled_user_ids:
            await service.set_entitlement(asset.asset_id, user_id, True)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return {
        "asset_id": asset.asset_id,
        "title": asset.title,
        "sample_rate": asset.sample_rate,
        "channels": asset.channels,
        "segment_count": asset.segment_count,
        "duration_seconds": asset.duration_samples / asset.sample_rate,
    }


@router.put("/assets/{asset_id}/entitlements")
async def update_entitlement(
    request: Request,
    asset_id: str,
    body: EntitlementUpdate,
    _: Annotated[Principal, Depends(require_admin)],
):
    try:
        await _service(request).set_entitlement(asset_id, body.user_id, body.allowed)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"asset_id": asset_id, "user_id": body.user_id, "allowed": body.allowed}


@router.post("/stream-sessions", response_model=StreamSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_stream_session(
    request: Request,
    body: StreamSessionRequest,
    principal: Annotated[Principal, Depends(require_principal)],
) -> StreamSessionResponse:
    try:
        session = await _service(request).create_session(principal, body.asset_id)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return StreamSessionResponse(
        session_id=session.session_id,
        asset_id=session.asset_id,
        expires_at=session.expires_at,
        playlist_url=_service(request).playlist_url(session),
    )


@router.get("/streams/{session_id}/playlist.m3u8", response_class=PlainTextResponse)
async def playlist(
    request: Request,
    session_id: str,
    cap: Annotated[str, Query(min_length=16)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> PlainTextResponse:
    session = await _session_for_capability(request, principal, session_id, cap, "playlist")
    started = time.perf_counter()
    manifest = await _service(request).playlist(session)
    await _service(request).repository.audit(
        "playlist_issued", "success", session_id=session_id, asset_id=session.asset_id, user_id=session.user_id,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    await _service(request).record_latency("playlist", (time.perf_counter() - started) * 1000)
    return PlainTextResponse(manifest, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "private, no-store"})


@router.get("/streams/{session_id}/segments/{sequence}.ts")
async def segment(
    request: Request,
    session_id: str,
    sequence: int,
    cap: Annotated[str, Query(min_length=16)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Response:
    session = await _session_for_capability(request, principal, session_id, cap, "segment", sequence)
    started = time.perf_counter()
    try:
        encrypted = await _service(request).encrypted_segment(session, sequence)
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    await _service(request).repository.audit(
        "segment_response", "success", session_id=session_id, asset_id=session.asset_id, user_id=session.user_id,
        latency_ms=(time.perf_counter() - started) * 1000, details={"sequence": sequence},
    )
    await _service(request).record_latency("segment", (time.perf_counter() - started) * 1000)
    return Response(encrypted, media_type="video/MP2T", headers={"Cache-Control": "private, no-store"})


@router.get("/streams/{session_id}/keys/main")
async def hls_key(
    request: Request,
    session_id: str,
    cap: Annotated[str, Query(min_length=16)],
    principal: Annotated[Principal | None, Depends(optional_principal)],
) -> Response:
    session = await _session_for_capability(request, principal, session_id, cap, "hls-key")
    key = segment_key(_settings(request).segment_key_secret, session.session_id)
    started = time.perf_counter()
    metadata = await _service(request).repository.encryption_key_metadata(session.session_id)
    await _service(request).repository.audit(
        "key_issued", "success", session_id=session_id, asset_id=session.asset_id, user_id=session.user_id,
        details={"key_length": len(key), "key_version": metadata["derivation_version"] if metadata else "unknown"},
    )
    await _service(request).record_latency("key", (time.perf_counter() - started) * 1000)
    return Response(key, media_type="application/octet-stream", headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/attribution/verify", response_model=AttributionVerifyResponse)
async def verify_attribution(
    request: Request,
    body: AttributionVerifyRequest,
    _: Annotated[Principal, Depends(require_admin)],
) -> AttributionVerifyResponse:
    match = await _service(request).repository.attribution_lookup(body.asset_id, body.watermark_id)
    await _service(request).repository.audit(
        "attribution_verified", "success" if match else "not_found", asset_id=body.asset_id,
        details={"watermark_id": body.watermark_id},
    )
    if not match:
        return AttributionVerifyResponse(matched=False)
    return AttributionVerifyResponse(matched=True, **match)


@router.get("/operations/metrics")
async def metrics(request: Request, _: Annotated[Principal, Depends(require_admin)]) -> dict[str, float | int]:
    return await _service(request).metrics()
