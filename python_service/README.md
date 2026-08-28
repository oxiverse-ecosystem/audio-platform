# Session-Watermarked HLS Audio Service

This directory contains a **Python FastAPI/ASGI production MVP** for delivering listener-specific HLS-style audio. It prepares an input asset once, creates a unique short-lived stream session for an entitled listener, applies a deterministic keyed 32-bit attribution watermark before segment encryption, and serves AES-128-CBC encrypted MPEG-TS audio segments.

The service treats access control, encryption, and watermark attribution as distinct layers. It never sends the watermark secret to a client and it avoids raw encryption keys in logs. The embedded identifier is an opaque HMAC-derived 32-bit value; the mapping back to a user and session remains in the server database.

> **Scope and honesty.** This is an engineering MVP, not a claim of watermark robustness. Its tests establish access isolation, deterministic controlled-fixture recovery, cryptographic segment/key handling, sample-domain boundary continuity, and bounded-load behavior. They do **not** establish imperceptibility, resistance to codecs, trimming, time-scale modification, acoustic replay, collusion, adversarial removal, or any Pd/Pfa rate. Earlier invalid Pd/Pfa claims are not used here.

## Quick start

Install `ffmpeg` from your operating-system package manager, then create an isolated environment and run the ASGI service. The development defaults are intentionally rejected when `AUDIO_ENV=production`.

```bash
cd python_service
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export AUDIO_ENV=development
uvicorn audio_streaming.app:app --host 127.0.0.1 --port 8000
```

For a production deployment, set the four independent secrets (`AUDIO_AUTH_SECRET`, `AUDIO_CAPABILITY_SECRET`, `AUDIO_WATERMARK_SECRET`, and `AUDIO_SEGMENT_KEY_SECRET`) from a managed secret store. Each must contain at least 32 characters. Do not use the development values.

| Endpoint | Caller | Purpose |
| --- | --- | --- |
| `POST /v1/assets` | Administrator identity | Registers a bounded base64 audio source, normalizes it once to 16 kHz mono PCM, aligns it to watermark/segment boundaries, and optionally grants initial entitlements. |
| `PUT /v1/assets/{asset_id}/entitlements` | Administrator identity | Grants or revokes an asset entitlement for a listener. |
| `POST /v1/stream-sessions` | Entitled listener identity | Creates a session, persists the 32-bit attribution mapping, and issues the short-lived playlist capability. |
| `GET /v1/streams/{session_id}/playlist.m3u8` | Short-lived signed capability; optional matching bearer identity | Returns an HLS manifest with per-session encrypted-segment and key URLs. |
| `GET /v1/streams/{session_id}/segments/{sequence}.ts` | Segment-specific signed capability | Performs bounded personalization, AAC-in-TS encoding, AES-128 encryption, and cache-controlled delivery. |
| `GET /v1/streams/{session_id}/keys/main` | Short-lived signed capability | Returns the 16-byte AES-128 session key without persisting or logging the key. |
| `POST /v1/attribution/verify` | Administrator identity | Maps an extracted 32-bit ID and asset identifier to a stored session and pseudonymous user audit hash. |
| `GET /v1/operations/metrics` | Administrator identity | Returns aggregate cache, request, and latency counters with no secret or raw user identifiers. |
| `POST /v1/enhance` | Any valid bearer identity | **Single enhancement entry point.** Runs the full audio pipeline (spectral noise reduction when the VAD finds a usable floor, then the CPU-only studio-mastering chain) and returns the processed audio plus the combined report. There is no separate enhance or master endpoint; the enhancer and mastering stages are orchestrated internally. |

The reference identity scheme uses a server-HMAC bearer token to make the MVP self-contained and to support automated tests. Replace `issue_identity` with OIDC/JWT verification at the edge or in the application before production. The playlist URL itself is an expiring signed capability because standard HLS clients cannot reliably attach an `Authorization` header for all nested media/key requests. If a bearer identity is supplied, it must match the capability’s session owner.

## Transport, segment encryption, and personalization flow

The HLS playlist declares `EXT-X-KEY:METHOD=AES-128`; each segment is AES-128-CBC encrypted with PKCS#7 padding. The key is derived from a server-only segment-key secret and the session ID, and the IV is deterministically domain-separated by session and sequence. HLS AES-128 is defined as AES-CBC encryption of media segments, with the key URI and optional IV declared through `EXT-X-KEY`. [1]

| Stage | Reused across listeners? | Server-only material | Bound |
| --- | --- | --- | --- |
| Decode, mono fold-down, resample, conservative level normalization, and alignment | Yes; one normalized `.npy` intermediate per asset | None | 20 MiB upload; 30 minute source limit in the MVP |
| Watermark carrier generation and overlap-add embedding | No; it is session-specific | Watermark secret; opaque 32-bit token | 512-sample frames, 256-sample hop, absolute carrier timeline |
| AAC-in-MPEG-TS encode and AES-128 encryption | No; output is session-specific | Segment-key secret and session key | Per-request bounded worker pool and LRU personalized-segment cache |
| Playlist, segment, and key URL capability | No; minted per session/request scope | Capability-signing secret | 120 seconds by default, never beyond session expiry |

The carrier uses a sequence-independent absolute sample clock. Therefore, when a client requests or retries segments out of order, each segment is rendered from the same global carrier phase that a continuous stream would have used. This property is tested at the uncompressed PCM boundary. The separate AAC-in-TS encoding operation is deliberately described as HLS-style MVP packaging; a high-scale production pipeline should use pre-warmed, timestamp-continuous media packaging and object storage/CDN delivery rather than repeated local encoding.

## Capacity controls and deployment topology

The process implements a fixed thread pool for CPU-bound DSP/codec work, a second admission semaphore capped at twice the worker count, a byte-bounded LRU for personalized encrypted segments, a per-user active-session cap, and an in-memory request-rate limiter. Cancellation of an HTTP waiter does not release worker admission early, preventing cancellation storms from creating unbounded hidden work.

| Deployment option | Appropriate use | Operational note |
| --- | --- | --- |
| This service in a single container | Development, integration, or bounded VOD MVP | SQLite and local prepared files are process-local. Set a small worker count and treat cache loss as normal. |
| Horizontally scaled API/DSP containers with managed PostgreSQL, object storage, and CDN | Recommended production path | Move prepared PCM and personalized encrypted segments to object storage; use a shared rate limiter, distributed cache, and a job queue. Preserve authorization checks at the origin/CDN boundary. |
| Dedicated media worker fleet plus queue | High bitrate, live, multiple renditions, or many simultaneous first-plays | Split ingest/preparation from session personalization; benchmark codec/DSP costs on target CPU architecture before setting autoscaling. |

The managed project host’s 1 vCPU / 512 MiB autoscaled envelope is appropriate only for a **small demonstration** of this CPU-bound pathway. It is not presented as high-scale media infrastructure. For practical production streaming, use the container image below behind a TLS-only load balancer, a managed secret store, external durable storage/database, observability, and a CDN that does not weaken capability-query validation. Do not deploy plain HTTP: signed capabilities and HLS keys require TLS in transit.

## Secret management and rotation

Keep the identity, capability, watermark, and media-encryption root secrets in separate versioned secret-store entries. Restrict read access to the streaming service runtime identity and audit secret reads. Never place them in source control, client JavaScript, playlists, analytics fields, exception text, or command-line arguments. The database persists only a session-scoped key purpose, derivation version, expiry, rotation state, and an HMAC-derived non-secret key reference; it never persists the AES key itself.

| Rotation event | Required action | Expected effect |
| --- | --- | --- |
| Capability-signing secret rotation | Issue a new secret version, temporarily validate both versions, then retire the old version after the maximum capability TTL. | Invalidates expired capabilities and minimizes disruption to active playback. |
| Segment-key secret rotation | Version the key derivation, keep old versions until all corresponding stream sessions expire, then revoke/retire them. | Existing HLS key URLs can complete only during their bounded session lifetime. |
| Watermark secret rotation | Version carrier/ID derivation and store the derivation version in the attribution mapping before enabling a new secret. | Preserves historical attribution verification. Do **not** rotate without retaining the prior version. |
| Identity-signing key rotation | Delegate to an OIDC provider with JWKS overlap or accept explicit `kid` versions. | Listener authentication remains independently rotatable. |

The current minimal schema supports controlled maintenance rotation by revoking active sessions before a root-secret change. Seamless multi-version rotation is a required next production-hardening step, not something this MVP claims to have implemented.

## Threat model and limitations

The service aims to prevent an unauthenticated caller from obtaining a playlist, encrypted segment, or HLS key; to prevent one entitled user from replaying another user’s active session capability while using their own bearer identity; and to retain a server-side mapping to attribute a successfully extracted valid ID. The capability URL is a bearer credential for its short lifetime, so it may leak through browser history, referrers, screenshots, logs, or proxies if deployment controls are careless. Use Referrer-Policy, redacted structured logging, TLS, short TTLs, and no-store responses.

The 32-bit ID has a finite collision space. The service’s session allocator detects a collision within an asset and retries with a new session ID; final attribution always requires both the known asset ID and the extracted watermark ID. A production forensic system should consider a longer protected payload or store additional protocol metadata if its expected scale approaches meaningful birthday-collision risk.

No watermark can make captured audio impossible to remove or impossible to redistribute. AES protects delivery, not analog capture; signed URLs protect access until shared; and the current carrier has only controlled-fixture recovery evidence. A valid robustness claim requires a locked train/tune/test corpus, explicit quality budget, CRC-gated exact-ID decision, independent negatives, attack-specific confidence intervals, and a separately designed TSM/acoustic-replay channel.

## Tests

Run the full automated suite with:

```bash
cd python_service
PYTHONPATH=. pytest -q
```

The suite verifies authorization isolation, raw key/segment access control, AES decryption correctness, deterministic 32-bit mapping, exact controlled-fixture ID recovery, sample-domain boundary continuity, single-flight cache behavior, and bounded cold-stream back-pressure. In the configured two-worker test profile, a six-request cold burst admits four personalization jobs and returns controlled `503` responses for two excess requests. This is a safety assertion, **not** a throughput benchmark.

## References

[1] [RFC 8216: HTTP Live Streaming](https://datatracker.ietf.org/doc/html/rfc8216)
