"""Episode discovery: register published episodes and browse/list/search/filter."""

from __future__ import annotations

import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from .api import require_principal
from .security import Principal


router = APIRouter(prefix="/v1", tags=["episodes"])


def _repo(request: Request):
    return request.app.state.repository


# --- request/response bodies ---
class CreateEpisodeRequest(BaseModel):
    asset_id: str
    title: str
    description: str | None = None
    category: str = "Founder Stories"


class EpisodeResponse(BaseModel):
    episode_id: str
    asset_id: str
    creator_id: str
    title: str
    description: str | None
    category: str
    visibility: str
    duration_seconds: float
    play_count: int
    created_at: int


# --- endpoints ---
@router.post("/episodes", response_model=EpisodeResponse, status_code=status.HTTP_201_CREATED)
async def create_episode(
    request: Request,
    body: CreateEpisodeRequest,
    principal: Annotated[Principal, Depends(require_principal)],
):
    """Publish a ready upload so it appears in discovery and is immediately playable.

    The referenced upload must have finished studio processing (job status ``ready``).
    Publishing bakes the A/B watermarked HLS segments + AES key so playback works, stores
    the real duration from the processing report, and makes the episode visible to everyone
    on Discovery ("all under one" model; no per-episode visibility).
    """
    repo = _repo(request)
    if not body.title.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title required")

    job = await request.app.state.jobs_repository.get_job_by_asset(body.asset_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found; upload must be completed first")
    if job.owner_user_id != principal.subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your upload")
    if job.status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="upload still processing")
    if not job.mastered_key_wav:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="upload has no mastered output; re-upload")

    # Bake A/B watermarked segments + AES so the episode is playable immediately.
    try:
        mastered_pcm = request.app.state.media_store.get(job.mastered_key_wav)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="mastered asset missing; re-upload")
    rec = await request.app.state.ab_stream.ingest_asset(job.asset_id, principal.subject, mastered_pcm, 48000)

    if job.report and isinstance(job.report.get("duration_seconds"), (int, float)):
        duration = float(job.report["duration_seconds"])
    else:
        duration = round(sum(rec.segment_durations), 2)

    episode_id = "ep_" + secrets.token_hex(12)
    now = int(time.time())
    await repo.create_episode(
        episode_id, job.asset_id, principal.subject, body.title.strip(),
        body.description, body.category, "public", duration, now,
    )
    episode = await repo.get_episode(episode_id)
    return EpisodeResponse(**episode)


@router.get("/episodes")
async def list_episodes(
    request: Request,
    category: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List public episodes with optional search + category filter."""
    repo = _repo(request)
    episodes = await repo.get_episodes(category=category, search=search, limit=limit, offset=offset)
    return {"episodes": episodes, "limit": limit, "offset": offset}


@router.get("/episodes/categories")
async def list_categories(request: Request):
    """List distinct categories that have public episodes."""
    repo = _repo(request)
    categories = await repo.get_categories()
    return {"categories": categories}


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(request: Request, episode_id: str):
    """Get a single episode by id."""
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    return EpisodeResponse(**episode)


# --- analytics (creator dashboard) ---
@router.get("/analytics/me")
async def get_my_analytics(request: Request, principal: Annotated[Principal, Depends(require_principal)]):
    """Get analytics for the authenticated creator."""
    repo = _repo(request)
    stats = await repo.get_creator_stats(principal.subject)
    return stats


@router.get("/episodes/me")
async def get_my_episodes(request: Request, principal: Annotated[Principal, Depends(require_principal)]):
    """Get episodes by the authenticated creator."""
    repo = _repo(request)
    episodes = await repo.get_creator_episodes(principal.subject)
    return {"episodes": episodes}
