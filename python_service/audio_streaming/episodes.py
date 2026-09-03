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
    visibility: str = "public"


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
    """Register an episode from a ready upload so it appears in discovery."""
    repo = _repo(request)
    if not body.title.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title required")
    if body.visibility not in ("public", "pack", "private"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid visibility")

    episode_id = "ep_" + secrets.token_hex(12)
    now = int(time.time())
    await repo.create_episode(
        episode_id, body.asset_id, principal.subject, body.title.strip(),
        body.description, body.category, body.visibility, 0.0, now,
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
