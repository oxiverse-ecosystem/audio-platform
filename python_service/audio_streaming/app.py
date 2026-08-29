"""FastAPI app factory; endpoint modules are attached as service capabilities mature."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .api import router as streaming_router
from .enhance import router as enhance_router
from .cache import RequestRateLimiter
from .config import Settings
from .billing import SEED_CONFIG, SEED_PLANS
from .observability import configure_logging, metrics
from .repository import Repository
from .service import StreamingService
from .storage import build_object_store
from .variant_api import router as variant_router
from .variant_service import VariantStreamingService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an ASGI app with an explicitly initialized persistent repository."""

    resolved_settings = settings or Settings.from_env()
    configure_logging(resolved_settings.environment, os.getenv("AUDIO_LOG_LEVEL", "INFO"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.data_dir.mkdir(parents=True, exist_ok=True)
        from .postgres_repository import build_repository
        repository = build_repository(resolved_settings)
        await repository.initialize()
        app.state.settings = resolved_settings
        app.state.repository = repository
        app.state.streaming_service = StreamingService(resolved_settings, repository)
        app.state.object_store = build_object_store(resolved_settings)
        app.state.variant_service = VariantStreamingService(resolved_settings, repository, app.state.object_store)
        # P1: prefer a Redis-backed cluster-wide limiter when configured, else in-memory.
        redis_url = os.getenv("AUDIO_REDIS_URL", "").strip()
        if redis_url:
            try:
                from .redis_limiter import RedisRateLimiter
                app.state.request_limiter = RedisRateLimiter(
                    redis_url, resolved_settings.request_limit_per_minute)
            except Exception:  # noqa: BLE001 - fall back rather than refuse to boot
                logging.warning("redis limiter unavailable; using in-process limiter")
                app.state.request_limiter = RequestRateLimiter(resolved_settings.request_limit_per_minute)
        else:
            app.state.request_limiter = RequestRateLimiter(resolved_settings.request_limit_per_minute)
        # P2: seed pricing/plans only where absent so runtime edits survive restarts.
        await repository.seed_billing(SEED_CONFIG, SEED_PLANS)
        yield
        await app.state.streaming_service.close()
        await repository.close()
        if hasattr(app.state.request_limiter, "close"):
            try:
                await app.state.request_limiter.close()
            except Exception:  # noqa: BLE001
                pass

    app = FastAPI(
        title="Session Watermarked HLS Audio Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.environment != "production" else None,
        redoc_url=None,
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
                metrics.inc("http_requests_total", 1)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "request rate limit exceeded", "request_id": request_id},
                    headers={"Retry-After": str(retry_after), "X-Request-ID": request_id, "Cache-Control": "no-store"},
                )
        try:
            response = await call_next(request)
        except Exception:
            metrics.inc("http_errors_total", 1)
            response = JSONResponse(status_code=500, content={"detail": "internal server error", "request_id": request_id})
        if response.status_code >= 400:
            try:
                await request.app.state.repository.audit(
                    "http_error", "failure", latency_ms=(time.perf_counter() - started) * 1000,
                    details={"method": request.method, "path": request.url.path, "status": response.status_code},
                )
            except Exception:  # noqa: BLE001
                pass
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.2f}"
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz", tags=["operations"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "session-watermarked-hls"}

    @app.get("/metrics", tags=["operations"])
    async def metrics_endpoint() -> Response:
        return Response(metrics.to_prometheus(), media_type="text/plain; version=0.0.4")

    app.include_router(streaming_router)
    app.include_router(variant_router)
    app.include_router(enhance_router)
    return app


app = create_app()
