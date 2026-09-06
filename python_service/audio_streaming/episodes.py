"""Episode discovery: register published episodes, manage drafts, browse/list/search/filter, and time-series analytics."""

from __future__ import annotations

import json
import secrets
import time
from typing import Annotated, Any

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


class RecordPlayRequest(BaseModel):
    duration_listened_seconds: float = 0.0
    completed: bool = False


class UpdateEpisodeRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None


class EpisodeResponse(BaseModel):
    episode_id: str
    asset_id: str
    creator_id: str
    title: str
    description: str | None = None
    category: str = "Founder Stories"
    visibility: str = "public"
    status: str = "published"
    duration_seconds: float = 0.0
    play_count: int = 0
    waveform_peaks: list[float] | None = None
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
    the real duration and true waveform peaks, and marks status as published.
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

    peaks = job.report.get("waveform_peaks") if job.report else None

    # Check if an episode was already created as a draft at upload time
    existing = await repo.get_episode_by_asset(job.asset_id)
    if existing is not None:
        episode_id = existing["episode_id"]
        await repo.update_episode_status(
            episode_id, "published", duration_seconds=duration, waveform_peaks=peaks
        )
    else:
        episode_id = "ep_" + secrets.token_hex(12)
        now = int(time.time())
        await repo.create_episode(
            episode_id, job.asset_id, principal.subject, body.title.strip(),
            body.description, body.category, "public", duration, now,
            status="published", publish_on_ready=0, waveform_peaks=peaks,
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
    """List public published episodes with optional search + category filter."""
    repo = _repo(request)
    episodes = await repo.get_episodes(category=category, search=search, status="published", limit=limit, offset=offset)
    return {"episodes": episodes, "limit": limit, "offset": offset}


@router.get("/episodes/categories")
async def list_categories(request: Request):
    """List distinct categories that have public published episodes."""
    repo = _repo(request)
    categories = await repo.get_categories()
    return {"categories": categories}


@router.get("/episodes/drafts")
async def list_drafts(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List drafts, in-progress processing, and ready-to-publish items for the creator."""
    repo = _repo(request)
    drafts = await repo.get_creator_drafts(principal.subject, limit=limit, offset=offset)
    return {"drafts": drafts}


@router.get("/episodes/me")
async def get_my_episodes(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    status: str | None = None,
):
    """Get episodes by the authenticated creator (optionally filtered by status)."""
    repo = _repo(request)
    episodes = await repo.get_creator_episodes(principal.subject, status=status)
    return {"episodes": episodes}


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode(request: Request, episode_id: str):
    """Get a single episode by id."""
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    return EpisodeResponse(**episode)


@router.patch("/episodes/{episode_id}", response_model=EpisodeResponse)
async def update_episode(
    request: Request,
    episode_id: str,
    body: UpdateEpisodeRequest,
    principal: Annotated[Principal, Depends(require_principal)],
):
    """Update draft or published episode metadata (title, description, category)."""
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    if episode["creator_id"] != principal.subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your episode")

    if body.title is not None and not body.title.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title cannot be empty")

    await repo.update_episode_metadata(
        episode_id,
        title=body.title,
        description=body.description,
        category=body.category,
    )
    updated = await repo.get_episode(episode_id)
    return EpisodeResponse(**updated)


@router.delete("/episodes/{episode_id}")
async def delete_episode(
    request: Request,
    episode_id: str,
    principal: Annotated[Principal, Depends(require_principal)],
):
    """Delete a draft or episode owned by the creator."""
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    if episode["creator_id"] != principal.subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your episode")

    await repo.delete_episode(episode_id)
    return {"deleted": True, "episode_id": episode_id}


@router.post("/episodes/{episode_id}/publish", response_model=EpisodeResponse)
async def publish_draft(
    request: Request,
    episode_id: str,
    principal: Annotated[Principal, Depends(require_principal)],
):
    """Publish a draft episode.

    If studio processing has completed, the episode is immediately published and watermarked.
    If studio processing is still queued or running, publish_on_ready is enabled so the audio
    automatically publishes upon processing completion without requiring user attention.
    """
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")
    if episode["creator_id"] != principal.subject:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your episode")
    if episode["status"] == "published":
        return EpisodeResponse(**episode)

    job = await request.app.state.jobs_repository.get_job_by_asset(episode["asset_id"])
    if job is not None and job.status == "ready" and job.mastered_key_wav:
        # Ingest into ABStream if not already done
        try:
            mastered_pcm = request.app.state.media_store.get(job.mastered_key_wav)
            await request.app.state.ab_stream.ingest_asset(job.asset_id, principal.subject, mastered_pcm, 48000)
        except Exception:
            pass
        duration = float(job.report.get("duration_seconds", episode["duration_seconds"])) if job.report else episode["duration_seconds"]
        peaks = job.report.get("waveform_peaks") if job.report else episode.get("waveform_peaks")
        await repo.update_episode_status(episode_id, "published", duration_seconds=duration, waveform_peaks=peaks)
    else:
        # Mark publish_on_ready = 1 and status = "processing"
        await repo.update_episode_publish_on_ready(episode_id, 1)
        await repo.update_episode_status(episode_id, "processing")

    updated = await repo.get_episode(episode_id)
    return EpisodeResponse(**updated)


@router.post("/episodes/{episode_id}/play")
async def record_episode_play(
    request: Request,
    episode_id: str,
    body: RecordPlayRequest,
):
    """Record a play event, listened duration, and completion status for analytics."""
    repo = _repo(request)
    episode = await repo.get_episode(episode_id)
    if episode is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="episode not found")

    now = int(time.time())
    await repo.record_play(
        episode_id,
        episode["creator_id"],
        now,
        duration_listened_seconds=body.duration_listened_seconds,
        completed=body.completed,
    )
    return {"status": "recorded", "play_count": episode["play_count"] + 1}


# --- analytics (creator dashboard) ---
@router.get("/analytics/me")
async def get_my_analytics(request: Request, principal: Annotated[Principal, Depends(require_principal)]):
    """Get high-level summary analytics for the authenticated creator."""
    repo = _repo(request)
    stats = await repo.get_creator_stats(principal.subject)
    return stats


@router.get("/analytics/creator/timeseries")
async def get_creator_timeseries(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    days: int = Query(default=30, ge=1, le=365),
):
    """Get time-series daily play counts and listener retention metrics for creator dashboard."""
    repo = _repo(request)
    data = await repo.get_creator_timeseries(principal.subject, days=days)
    return data
