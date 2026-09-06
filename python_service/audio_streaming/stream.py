"""Phase 1b delivery router: A/B watermarked, encrypted HLS streaming.

Endpoints (local delivery via LocalFSStore + signed URLs; migrates to R2+Worker later):
  POST /v1/streams/ingest                 -> bake A/B variants + AES for a mastered asset
  POST /v1/streams/{asset_id}/sessions   -> create a per-listener stream session
  GET  /v1/streams/{sid}/playlist.m3u8   -> per-listener A/B manifest + signed URLs
  GET  /v1/streams/{sid}/keys/main       -> per-asset AES key (signed, short TTL)
  GET  /v1/cdn/streams/{sid}/segments/{seq}.ts -> signed segment serve (LocalFSStore)
  GET  /v1/cdn/streams/{sid}/keys/main   -> signed key serve (LocalFSStore)

All signed routes enforce the HMAC + expiry; tampered/expired -> 403. This is access
control + traceability, not DRM.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from .api import require_principal
from .security import Principal


class IngestRequest(BaseModel):
    asset_id: str
    creator_id: str | None = None
    mastered_key: str


router = APIRouter(prefix="/v1/ab", tags=["stream-ab"])


def _ab(request: Request):
    return request.app.state.ab_stream


def _signer(request: Request):
    return request.app.state.url_signer


# --- ingest: bake A/B variants + AES for a mastered asset ---
@router.post("/streams/ingest", tags=["stream-ab"])
async def ingest(request: Request, body: IngestRequest, principal: Principal = Depends(require_principal)):
    asset_id = body.asset_id
    creator_id = body.creator_id
    mastered_key = body.mastered_key
    if not asset_id or not mastered_key:
        raise HTTPException(400, "asset_id and mastered_key required")
    store = request.app.state.media_store
    try:
        mastered = store.get(mastered_key)
    except FileNotFoundError:
        raise HTTPException(404, "mastered asset not found; run P1a upload first")
    rec = await _ab(request).ingest_asset(asset_id, creator_id, mastered, 48000)
    return {
        "asset_id": rec.asset_id,
        "n_segments": rec.n_segments,
        "status": "ingested",
        "note": "two shared A/B variant files per segment; CDN-cacheable",
    }


# --- session: per-listener personalization (the A/B manifest) ---
@router.post("/streams/{asset_id}/sessions", tags=["stream-ab"])
async def create_session(asset_id: str, request: Request,
                         principal: Principal = Depends(require_principal)):
    sess = await _ab(request).create_session(asset_id, principal)
    # Automatically log initial play event if an episode exists
    repo = getattr(request.app.state, "repository", None)
    if repo is not None:
        try:
            ep = await repo.get_episode_by_asset(asset_id)
            if ep is not None:
                await repo.record_play(ep["episode_id"], ep["creator_id"], int(time.time()), 0.0, False)
        except Exception:
            pass
    return {"session_id": sess.session_id, "expires_at": sess.expires_at}


@router.get("/streams/{session_id}/playlist.m3u8", tags=["stream-ab"])
async def playlist(session_id: str, request: Request):
    try:
        base = str(request.base_url).rstrip("/")
        m3u8 = _ab(request).playlist(session_id, base)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return PlainTextResponse(m3u8, media_type="application/vnd.apple.mpegurl")


@router.get("/streams/{session_id}/keys/main", tags=["stream-ab"])
async def key(session_id: str, request: Request):
    try:
        raw = await _ab(request).get_key(session_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return Response(raw, media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


# --- signed CDN serve (LocalFSStore now; Worker+R2 later) ---
@router.get("/cdn/streams/{session_id}/segments/{seq}.ts", tags=["stream-ab-cdn"])
async def serve_segment(session_id: str, seq: int, request: Request, tok: str = ""):
    asset_id, variant = _resolve_asset_variant(request, session_id, seq)
    obj_key = f"assets/{asset_id}/v{variant}/{seq:04d}.ts"
    if not _signer(request).verify(obj_key, tok):
        raise HTTPException(403, "invalid or expired signed URL")
    try:
        data = await _ab(request).get_segment(asset_id, variant, seq)
    except FileNotFoundError:
        raise HTTPException(404, "segment not found")
    return Response(data, media_type="audio/mpegts",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/cdn/streams/{session_id}/keys/main", tags=["stream-ab-cdn"])
async def serve_key(session_id: str, request: Request, tok: str = ""):
    key_path = f"streams/{session_id}/keys/main"
    if not _signer(request).verify(key_path, tok):
        raise HTTPException(403, "invalid or expired signed URL")
    try:
        raw = await _ab(request).get_key(session_id)
    except KeyError:
        raise HTTPException(404, "key not found")
    return Response(raw, media_type="application/octet-stream",
                    headers={"Cache-Control": "no-store"})


def _resolve_asset_variant(request: Request, session_id: str, seq: int):
    ab = _ab(request)
    sess = ab._sessions.get(session_id)
    if sess is None:
        raise HTTPException(404, "unknown session")
    rec = ab._assets.get(sess.asset_id)
    if rec is None:
        raise HTTPException(404, "unknown asset")
    from .watermark_ab import build_manifest
    manifest = build_manifest(rec.asset_id, sess.listener_id, rec.n_segments, ab.wm_settings)
    variant = manifest.choices[seq] if seq < len(manifest.choices) else 0
    return rec.asset_id, variant
