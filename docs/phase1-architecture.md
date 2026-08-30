# Audio Platform — Decisions, Threat Model Research & Phase 1 Architecture

Companion to `audio-platform-skill.md` (product/plan overview). This doc locks the
founder's decisions, records the threat-model research (incl. analog capture), and
specifies a **local-first, Cloudflare-migratable** Phase 1 so we can build now
without Cloudflare credits and deploy later with a config flip.

---

## 1. LOCKED DECISIONS (from founder)

| # | Decision | Consequence |
|---| --- | --- |
| D1 | **Pricing deferred.** Launch free for **25 users, 1-year free trial** to recruit founders. Numbers (free X hrs, paid Y=50hrs, pack price) decided after real usage. | Metering + quota ledger must still be BUILT (so it's ready), but enforcement is "track only" during trial. No paywall yet. |
| D2 | **Creator pack = monthly**, creator-sets price range, unlimited recordings from that creator. | Entitlement = `(user, creator, month)` row; revocation at month end / non-renew. |
| D3 | **Build on Cloudflare R2 + Workers** (control, OSS-aligned) — but **develop locally first** (no startup credits yet). | Storage + signing must be swappable behind interfaces so migration = config, not rewrite. |
| D4 | **Maximize the threat model** — watermark should survive as much as possible, **including analog re-recording** (phone recording the speaker). | DSP-only is insufficient for T3; adopt redundancy + ECC now, and a pluggable DL watermark for high-value assets. |
| D5 | **Phase 1 scope** = (a) an **enhance API to studio quality for paid customers**, then (b) an API that **serves encrypted audio with watermark on request**. Local only for now. | See §4. |

Ethos preserved: privacy-by-design (no analytics without opt-in), Oxiverse OCL-aligned,
build-in-public. Auto-edit chain stays **pure DSP, no LLM** (D4's DL watermark is a
*separate* concern from the edit chain — allowed).

---

## 2. THREAT MODEL & WATERMARK RESEARCH (cited)

### 2.1 Threat tiers
- **T1 (digital, easy):** MP3/Opus re-encode, gain/normalize, trimming, filtering.
  → Classical spread-spectrum (SS) survives well.
- **T2 (digital, medium):** heavy compression, time-scale modification (speed/pitch
  shift), cropping. → Needs temporal redundancy + error-correction + transform-domain.
- **T3 (analog hole, hard):** speaker→mic re-recording (phone films/records playback).
  AR preserves *content* but **heavily damages the watermark** — ordinary SS fails
  (DeAR paper, AAAI'23 / arxiv 2212.02339; DeepAWR, ScienceDirect 2025).

### 2.2 What research says works
- **Re-recording-resilient watermarking requires a distortion simulator** modelling
  AR as *environment reverberation + band-pass filtering + Gaussian noise*, embedded
  in an *encoder–distortion-simulator–decoder* (DeAR/DeepAWR). These are **deep-
  learning** watermarks, not pure DSP. (arxiv 2212.02339; ScienceDirect S0031320325000263)
- **Temporal redundancy + time-order-agnostic detection** is the key to surviving
  cuts/desync/degraded copies: AWARE (2026) aggregates temporal evidence into one
  score per bit via a Bitwise Readout Head, decoding reliably under temporal cuts.
  (arxiv 2510.17512)
- **Collusion resistance** (multiple users XOR their differently-watermarked copies)
  needs time-varying patterns / probabilistic fingerprinting / multi-segment ID
  spreading (Lumenci forensic-watermarking review).
- **Zero-watermarking** (Scientific Reports 2026) modifies *no* host samples — uses
  robust audio features as a fingerprint. No quality loss, but fragile to feature-
  changing attacks; useful as a *second opinion* detector, not primary.
- **A/B variant delivery** (our scaling design) keeps SS robustness while avoiding
  per-user encode — spread-spectrum + A/B is the industry streaming pattern
  (Lumenci; Tencent StreamLive; NAGRA).

### 2.3 Adopted watermark strategy (D4 "maximize")
Primary (baseline, pure DSP, runs at ingest once):
- Payload = `magic(16) + user_id(32) + CRC(16)`, then wrapped in **Reed-Solomon**
  (e.g. RS short码) so partial bit loss still recovers the full id via CRC+ECC.
- **Temporal repetition**: repeat the full codeword `N≈12–20x`, interleaved across
  segments → a short leaked clip still carries the id (fixes the "short-clip weak
  spot" noted in kinescope research).
- **Transform-domain embedding** in DWT low-mid coefficients with perceptual masking
  (frequency masking) for imperceptibility (Zenodo 10008718; Springer FFT-FLT 2026).
- **Time-order-agnostic detector** (AWARE-style): aggregate per-bit evidence over the
  whole clip, don't rely on a fragile sync marker.
- Per-asset keyed permutation of codeword→segment (already in skill).
- A/B variant encode at ingest (v0/v1 carrier sign); manifest picks per listener.

High-value slot (creator packs / paid, where analog leak is likely):
- **Pluggable DL embedder** (DeAR/DeepAWR-style) trained with AR distortion simulator,
  swapped in behind the same `WatermarkEngine` interface. Runs once at ingest (not per
  listener), so compute cost is bounded. This is the "maximize threat model" upgrade
  without touching delivery or the edit chain.

Known limitation (state plainly): no watermark makes analog capture *impossible*;
it maximizes traceability + deterrent. Collusion is partially mitigated by A/B +
coded fingerprint; full collusion resistance is a later research step.

---

## 3. LOCAL-FIRST, CLOUDFLARE-MIGRATABLE ARCHITECTURE

Goal: build + test everything locally now; deploy to R2+Workers later with **no
rewrite**. Achieve via two swappable interfaces.

### 3.1 `MediaStore` (storage backend)
```
interface MediaStore:
    put(key: str, data: bytes) -> None
    get(key: str) -> bytes
    signed_url(key: str, expires_s: int) -> str   # for delivery
```
- `LocalFSStore` (now): files under `runtime-data/objects/<key>`; signed_url returns
  `http://host/cdn/<key>?exp=&sig=` (existing MVP `/cdn` pattern).
- `R2Store` (later): boto3/S3-compatible, identical object keys. `signed_url` can be a
  direct R2 pre-signed URL OR routed through the Worker. **Object keys identical**
  (`assets/<asset_id>/v0/<seq>.ts`) so nothing reshapes on migration.
- Optional dev parity: **MinIO** (S3 API locally) so the exact boto3 code runs now.

### 3.2 `URLSigner` (capability/signed-URL)
- HMAC-SHA256(`<object_key>\n<expires_at>`), base64url, padding stripped.
- `LocalSigner` (Python, now) and `WorkerSigner` (Cloudflare Worker, WebCrypto, later).
- **Verify byte-identical output in Python and Node before trusting** (cross-language
  HMAC is where silent mismatches hide).

### 3.3 Ingest pipeline (queued, NOT inline)
```
creator raw upload ─▶ MediaStore.put(source)
        │  (job queue)
        ▼
enhance (DSP: enhancer+mastering) ─▶ mastered PCM ─▶ MediaStore.put(mastered)
        │
        ▼
watermark engine (DSP baseline OR DL slot for high-value)
  ├─ encode variant 0 (carrier +) ─▶ AES-128 (PER-ASSET key) ─▶ MediaStore v0/
  └─ encode variant 1 (carrier -) ─▶ AES-128 (PER-ASSET key) ─▶ MediaStore v1/
        │
        ▼
persist: asset row, per-asset key (server-only), variant manifest template
```

### 3.4 Delivery (per listener, cacheable)
```
GET /v1/streams/{session}/playlist.m3u8
   ├─ auth + entitlement check (quota ledger)
   ├─ derive listener 32-bit id → codeword (magic+id+CRC+RS)
   ├─ build manifest: per segment pick v0/v1 by codeword bit (keyed perm)
   └─ return m3u8 with signed segment URLs + signed AES key URL
        │
        ▼
Client (HLS.js) fetches signed segments ─▶ (local) /cdn route  OR  (CF) Worker+R2
```
- Per-listener secrecy: signed manifest + short-TTL key endpoint bound to session.
- Per-listener attribution: variant choices (A/B), NOT unique bytes → CDN-cacheable.
- This is **access control + traceability, NOT DRM**. State plainly to stakeholders.

### 3.5 Committed-now, deploy-later artifacts
- `wrangler.toml` + `worker.js` (stub, NOT deployed): does HMAC validation + serves
  R2 objects + immutable cache headers. Flip `MediaStore`→R2 + `URLSigner`→Worker to
  go live. No code rewrite.
- Secrets via env in `.env` (gitignored): `AUDIO_*` secrets already defined in README.

---

## 4. PHASE 1 SCOPE (actionable)

### 4.1 Enhance API (for paid customers) — extend existing `POST /v1/enhance`
- Keep pure-DSP pipeline (enhancer + mastering). Add a **"studio preset"** config.
- **Bridge to streaming**: store the mastered result as an asset, return `asset_id`
  (not just base64 audio). This makes enhance the ingestion point for streaming.
- Switch large uploads from base64 (40 MiB cap) to **presigned multipart** (real
  founder audio is minutes long; base64+JSON is wrong for hundreds of MB).
- **Entitlement gating**: require a valid account identity; record per-user usage in
  the quota ledger (track-only during 25-user trial, D1).
- Identity: lightweight account (email or Oxiverse SSO) — needed for the trial cohort.

### 4.2 Encrypted + watermarked serving API (on request)
- Reuse existing session-watermarked HLS scaffolding BUT migrate the watermark to the
  **A/B variant scheme** (§2.3 / skill §2) so it is CDN-ready from day one. The
  current stateful per-session watermark is the scaling trap — do not ship it to
  multi-listener.
- Endpoints (already exist, re-point to A/B + local MediaStore):
  `POST /v1/stream-sessions`, `GET .../playlist.m3u8`, `GET .../segments/{seq}.ts`,
  `GET .../keys/main`, `POST /v1/attribution/verify`.
- Local delivery via `/cdn` route backed by `LocalFSStore`.

### 4.3 Metering (track-only now, enforced later)
- Per-user playback-duration ledger. SQLite now → Postgres + Redis later (see
  `watermarked-cdn-streaming` `references/multi_replica_fastapi.md` for the drop-in
  repo + `SELECT ... FOR UPDATE` pattern).
- During trial: record only; no 402. When pricing lands (D1), flip to enforce.

### 4.4 Attribution service (leak tracing)
- `POST /v1/attribution/verify`: upload leaked audio → recover codeword (time-order-
  agnostic detector) → RS-decode + CRC-validate → map to listener → revoke + takedown.
- This is what makes the creator-pack (unlimited, D2) safe to offer.

---

## 5. VERIFY, DON'T ASSERT
- Concurrent-manifest test: issue N manifests, assert per-listener encode counter == 0
  (proves CDN scaling). Never claim scalability in prose.
- Watermark recovery: needs offset search (AAC 1024-sample delay; aligned corr ~0.02
  vs ~0.0008 at offset 0 = ~25x collapse). Strength ~0.02 survives AAC.
- Fixtures >= 64 segments (or >= N×codeword-len for redundancy) so CRC-valid
  attribution is meaningful, not just the constant header.
- A/B cache proof: assert both `v0/` and `v1/` dirs full, manifests differ per user,
  signed URLs serve `public, max-age=1y, immutable`, tampered/expired → 403.

---

## 6. OPEN ITEMS STILL NEEDED
- D1 pricing numbers (after trial data).
- Identity provider choice for the 25-user trial (email magic-link vs Oxiverse SSO).
- Confirm DL watermark (DeAR/DeepAWR) is in-scope for Phase 1 high-value slot or
  deferred to P4 — founder said "maximize," so flag for build decision when we hit
  creator-pack work.

See `audio-platform-skill.md` for product model, business tiers, and the full A/B
delivery reference. Agent self-skill: `audio-platform` (Hermes).
