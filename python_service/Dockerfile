FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AUDIO_ENV=production \
    AUDIO_DATA_DIR=/var/lib/audio-streaming

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY audio_streaming ./audio_streaming

RUN useradd --system --create-home --uid 10001 streamsvc \
    && mkdir -p /var/lib/audio-streaming \
    && chown -R streamsvc:streamsvc /app /var/lib/audio-streaming
USER streamsvc

EXPOSE 8000
CMD ["uvicorn", "audio_streaming.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]

