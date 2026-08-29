# Oxiverse Audio — backend (secure_audio_streaming_mvp_source)

A privacy-first, CDN-cacheable A/B variant-watermarked audio streaming backend with server-
authoritative playback metering and pool-only creator payouts. See `docs/` for the architecture
decisions; this file is the run/operate guide.

## Layout

- `python_service/audio_streaming/` — FastAPI app, variant streaming, billing/metering, Postgres +
  Redis adapters, observability.
- `python_service/migrations/0001_schema.sql` — Postgres DDL (idempotent; re-runnable).
- `python_service/tests/` — unit + integration tests (ffmpeg-based codec tests included).
- `cloudflare_worker/` — edge signed-URL gate matching the origin signer.
- `frontend/` — React + Vite + HLS.js test console (catalog, metered player, usage, admin).
- `docker-compose.yml` / `Dockerfile` — multi-replica deployment (api + postgres + redis).
- `.github/workflows/ci.yml` — test + docker build on push/PR.

## Local dev (SQLite, zero dependencies)

```bash
cd python_service
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# 32+ char secrets are required; the dev defaults are fine for local only
uvicorn audio_streaming.app:app --port 8000 --reload
```

The app seeds plans (`free` = 10h, `listener_50` = ₹499/50h) on first boot and serves:
- `GET  /v1/assets` — catalog
- `POST /v1/dev-login` — issue a test identity (listener|admin); **disabled in production**
- `GET  /v1/usage` — current listener's consumed/included seconds
- `GET  /v1/plans` (admin), `PUT /v1/plans/{code}` — edit price/hours live (no deploy)
- `POST /v1/creators`, `POST /v1/payouts/compute?period=YYYY-MM`
- `GET  /metrics` — Prometheus exposition

To ingest an asset (admin): `POST /v1/variant-assets` (multipart, `asset_id`, `title`, `upload`).
The dev-only `GET /v1/cdn/{object_key}?exp=&sig=` stands in for Cloudflare locally.

## Production (Postgres + Redis + Cloudflare)

```bash
cp .env.example .env   # fill 32+ char secrets
docker compose up --build
```

- `AUDIO_DATABASE_URL` switches the repository to Postgres (asyncpg, `SELECT ... FOR UPDATE`
  metering so concurrent replicas cannot double-grant).
- `AUDIO_REDIS_URL` switches the rate limiter to a cluster-wide Redis sliding window.
- `AUDIO_CDN_BASE_URL` points the manifests at Cloudflare R2 (signed URLs); deploy
  `cloudflare_worker/` to enforce the same signature at the edge.

## Frontend test console

```bash
cd frontend
npm install && npm run dev   # proxies /v1 to :8000
```

Log in with a user id (role listener or admin), browse the catalog, press **Play (metered)** to
stream via the windowed manifest, and watch the usage bar advance. As an admin you can edit plans
live and compute a payout period.

## Test matrix

- P0 — A/B variant watermarking, 48 kHz stereo, CDN cacheable (codec e2e + forensic recovery).
- P2 — plans as DB rows, idempotent windowed metering (retry = no double charge), 402 on quota,
  pool-only payouts bounded by net revenue.
- P4 — JSON logging, `/metrics`, Postgres + Redis adapters, hardened Docker, CI.

`pytest` runs the whole suite; the codec tests need `ffmpeg` on PATH.
