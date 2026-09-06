"""FastAPI app factory; endpoint modules are attached as service capabilities mature."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router as streaming_router
from .enhance import router as enhance_router
from .upload import router as upload_router
from .auth import router as auth_router
from .stream_ab import ABStreamService
from .cache import RequestRateLimiter
from .config import Settings
from .repository import Repository
from .jobs import JobsRepository
from .service import StreamingService
from .store import build_signer, build_store


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an ASGI app with an explicitly initialized persistent repository."""

    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.data_dir.mkdir(parents=True, exist_ok=True)
        repository = Repository(resolved_settings.database_path)
        await repository.initialize()
        jobs_repository = JobsRepository(resolved_settings.data_dir / "jobs.db")
        await jobs_repository.initialize()
        media_store = build_store(resolved_settings)
        url_signer = build_signer(resolved_settings)
        app.state.settings = resolved_settings
        app.state.repository = repository
        app.state.jobs_repository = jobs_repository
        app.state.media_store = media_store
        app.state.url_signer = url_signer
        app.state.streaming_service = StreamingService(resolved_settings, repository)
        app.state.ab_stream = ABStreamService(media_store, url_signer)
        # Re-ingest previously-ready uploads so published episodes stay playable across
        # restarts (the A/B variant state lives in memory; the mastered files persist).
        for job in await jobs_repository.get_ready_jobs():
            if not job.asset_id or not job.mastered_key_wav:
                continue
            try:
                mastered = media_store.get(job.mastered_key_wav)
                await app.state.ab_stream.ingest_asset(job.asset_id, job.owner_user_id, mastered, 48000)
            except Exception:
                pass
        app.state.request_limiter = RequestRateLimiter(resolved_settings.request_limit_per_minute)
        yield
        await app.state.streaming_service.close()
        await repository.close()

    app = FastAPI(
        title="Session Watermarked HLS Audio Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.environment != "production" else None,
        redoc_url=None,
    )

    # CORS: allow the Next.js frontend (any localhost dev port) to call the API.
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        started = time.perf_counter()
        if request.url.path != "/healthz":
            source = request.headers.get("Authorization") or (request.client.host if request.client else "unknown")
            permitted, retry_after = await request.app.state.request_limiter.allow(source)
            if not permitted:
                await request.app.state.repository.audit(
                    "http_error", "rate_limited", details={"method": request.method, "path": request.url.path, "status": 429}
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "request rate limit exceeded", "request_id": request_id},
                    headers={"Retry-After": str(retry_after), "X-Request-ID": request_id, "Cache-Control": "no-store"},
                )
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(status_code=500, content={"detail": "internal server error", "request_id": request_id})
        if response.status_code >= 400:
            try:
                await request.app.state.repository.audit(
                    "http_error", "failure", latency_ms=(time.perf_counter() - started) * 1000,
                    details={"method": request.method, "path": request.url.path, "status": response.status_code},
                )
            except Exception:
                pass
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "session-watermarked-hls"}

    app.include_router(streaming_router)
    app.include_router(enhance_router)
    app.include_router(upload_router)
    from .stream import router as stream_ab_router
    app.include_router(stream_ab_router)
    app.include_router(auth_router)
    from .episodes import router as episodes_router
    app.include_router(episodes_router)
    return app


app = create_app()
