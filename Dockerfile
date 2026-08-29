# ---- build stage ----
FROM python:3.11-slim AS build
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY python_service/requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# ---- runtime stage ----
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
# Runtime deps for ffmpeg-based ingest (already present on host during dev; required in container).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user; never as root.
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY python_service /app/python_service

# Data dir is mounted/augmented at runtime; give the unprivileged user ownership.
RUN chown -R appuser:appuser /app && mkdir -p /app/runtime-data && chown -R appuser:appuser /app/runtime-data
USER appuser

ENV AUDIO_ENV=production \
    AUDIO_DATA_DIR=/app/runtime-data \
    AUDIO_DATABASE_PATH=/app/runtime-data/streaming.db \
    PYTHONPATH=/app/python_service

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["python", "-m", "uvicorn", "audio_streaming.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
