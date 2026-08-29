# A/B Variant Watermarked Streaming (P0 architecture)

This document describes the production streaming path and why it replaced the original
per-session just-in-time watermarking MVP.

## Why the original design could not ship

The MVP embedded a per-listener watermark at request time (`/v1/streams/...`). That makes every
delivered byte unique per session, which has two fatal consequences at scale:

1. **The CDN caches nothing.** Cloudflare becomes a pass-through proxy. All bandwidth is origin
   bandwidth.
2. **The origin pays a codec pass per listener per segment.** Load grows linearly with concurrent
   listeners. With a bounded worker pool the service correctly sheds load with `503`s -- which is
   honest, but it means concurrency is capped in the low double digits.

The legacy endpoints still exist and still pass their tests, but they are not the production path.

## The A/B variant design

At **ingest** each segment is encoded twice, differing only in the sign of a keyed spread-spectrum
carrier:

- `assets/<asset_id>/v0/<seq>.ts` -- carries codeword bit `0`
- `assets/<asset_id>/v1/<seq>.ts` -- carries codeword bit `1`

Both objects are immutable, identical for every listener, and therefore cacheable forever.

At **playback** the origin does no media work at all. A listener's session owns a 32-bit
attribution id, expanded to a 64-bit codeword (`0xA55A` magic + id + CRC-16). Their manifest
selects, segment by segment, whichever variant carries their next codeword bit. Personalization is
the *choice of files*, not the bytes.

```
creator upload
  -> ffmpeg decode to 48 kHz stereo
  -> segment (4 s, aligned to watermark hops)
  -> embed variant 0 and variant 1
  -> AAC 128k in MPEG-TS
  -> AES-128-CBC (per-asset key)
  -> R2 bucket
                        listener plays
                          -> origin issues signed manifest  (microseconds, no codec)
                          -> Cloudflare serves segments from cache
                          -> player fetches AES key from origin (short TTL)
```

### Cost profile

| | per-session JIT | A/B variants |
|---|---|---|
| Origin CPU per listener | 1 codec pass per segment | zero |
| CDN cache hit rate | 0% | ~100% |
| Storage | 1x | 2x |
| Concurrency ceiling | worker pool size | CDN capacity |

Storage is the only thing that got worse, and on R2 (zero egress fees) that is the cheapest
resource in the system.

## Forensic attribution

`POST /v1/variant-attribution/verify` accepts recovered segments as float32 PCM. For each one the
detector correlates against the keyed carrier for that position; the sign of the correlation gives
the bit. Bits vote into codeword slots weighted by confidence, then the CRC must validate exactly
before an id is returned -- so a false attribution requires a CRC collision, not merely a noisy
recovery.

### Two non-obvious properties this required

**Keyed bit permutation.** In natural order the 16-bit constant magic header would occupy the first
16 segments, so any capture shorter than that would be byte-identical for every listener and carry
no attribution at all. `bit_slot_permutation()` derives a per-asset keyed permutation, spreading id
and CRC bits across the whole programme.

**Codec-delay alignment search.** Time-domain spread-spectrum correlation is alignment-sensitive.
AAC introduces a **1024-sample encoder delay**, and a real capture can start anywhere. Measured on
a 48 kHz stereo fixture: correlation of an aligned block scored `0.0203`; the same block at offset
zero after an AAC round trip scored `0.0008` -- a ~25x collapse with an unreliable sign. `detect_bit`
therefore searches leading offsets and keeps the strongest-magnitude alignment. This is why
`search_offsets` exists and why it defaults to `True`.

## Encryption and access control

- **Segment encryption** is AES-128-CBC with a key derived per *asset*, not per session. A
  per-session key would make ciphertext unique and defeat caching. The IV is derived per
  `(asset, sequence, variant)`.
- **Per-listener secrecy** comes from the signed manifest plus a short-TTL key endpoint that
  requires a session-bound capability token.
- **Segment URLs** are signed: `HMAC-SHA256("<key>\n<exp>")`, base64url unpadded. Verified
  identically by `storage.verify_object_url`, the dev `/v1/cdn` endpoint, and the Cloudflare
  Worker. Cross-checked byte-for-byte between Python and WebCrypto.
- **Edge caching keys on the object path only**, never on the signature -- otherwise each
  listener's unique query string would miss the cache and collapse the design back to origin load.

This is not DRM. It is signed-URL access control plus forensic traceability, which is a
defensible v1 for audio. Widevine/FairPlay is a later upgrade and does not change this
architecture.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AUDIO_VARIANT_SAMPLE_RATE` | `48000` | Ingest sample rate |
| `AUDIO_VARIANT_CHANNELS` | `2` | Stereo |
| `AUDIO_VARIANT_BITRATE` | `128k` | AAC bitrate |
| `AUDIO_VARIANT_SEGMENT_SECONDS` | `4.0` | Segment length |
| `AUDIO_VARIANT_FRAME_SAMPLES` | `4096` | Watermark analysis frame |
| `AUDIO_VARIANT_WATERMARK_STRENGTH` | `0.0025` | Carrier amplitude |
| `AUDIO_CDN_BASE_URL` | *(required in prod)* | Public CDN origin |
| `AUDIO_CDN_URL_TTL_SECONDS` | `300` | Signed URL lifetime |
| `AUDIO_OBJECT_STORE_BACKEND` | `local` | `local` or `s3` (R2) |
| `AUDIO_OBJECT_STORE_BUCKET/ENDPOINT/ACCESS_KEY/SECRET_KEY` | | R2 credentials |

When `AUDIO_CDN_BASE_URL` is unset the origin serves segments itself from `/v1/cdn`, enforcing the
same signature contract. That endpoint returns `404` once a real CDN is configured.

## Endpoints

| Method | Path | Role | Notes |
|---|---|---|---|
| `POST` | `/v1/variant-assets` | admin | Multipart ingest; builds and publishes both variants |
| `PUT` | `/v1/variant-assets/{id}/entitlements` | admin | Grant/revoke listener access |
| `POST` | `/v1/variant-streams` | listener | Create a session; returns manifest URL |
| `GET` | `/v1/variant-streams/{sid}/playlist.m3u8` | capability | Personalized manifest, no media work |
| `GET` | `/v1/variant-streams/{sid}/keys/main` | capability | AES-128 content key |
| `DELETE` | `/v1/variant-streams/{sid}` | owner/admin | Revoke a session |
| `POST` | `/v1/variant-attribution/verify` | admin | Forensic recovery from leaked audio |
| `GET` | `/v1/variant-operations/metrics` | admin | Manifest/session counters |

## Deploying the Worker

```bash
cd cloudflare_worker
wrangler r2 bucket create audio-variants
wrangler secret put SIGNING_SECRET   # must equal AUDIO_CAPABILITY_SECRET
wrangler deploy
```

Then point the origin at it: `AUDIO_CDN_BASE_URL=https://<worker-domain>`.

## Verified behaviour

`tests/test_variant_streaming.py` exercises the real chain with ffmpeg -- no mocks:

- ingest publishes exactly `2 x segment_count` objects
- each listener's manifest matches their own codeword and differs between listeners
- signed URLs are `immutable`-cacheable; tampered and expired signatures are refused
- **full playback: manifest -> signed CDN fetch -> AES-128 decrypt -> AAC decode -> codeword
  recovery -> CRC valid -> exact session and user attribution**
- sessions are owner-bound; revocation stops manifest issuance
- 8 concurrent manifests are issued with `segment_builds == 0` (the scaling claim, asserted)

## Known limitations (next phases)

- SQLite + in-process rate limiter/metrics: single replica only. P1 replaces with Postgres + Redis.
- Ingest runs inline on the request's worker pool; a long upload holds a slot. Should move to a
  queue.
- No creator/listener accounts, plans, or listening-hours ledger yet (P2) -- the X/Y/Z pricing model
  has no enforcement in code.
- Identity tokens are self-issued HMAC; production needs a real identity provider.
