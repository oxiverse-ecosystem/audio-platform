# Audio Platform — Product Model, Architecture Plan & Self-Skill

> Owner: Likhith Sai (Oxiverse). This document is both a planning artifact AND a
> self-skill for the Hermes agent working on this repo. It captures the product
> idea, the researched Cloudflare delivery architecture, the scaling verdict, and
> the gaps between the current MVP and the target design.
>
> Status: PLAN ONLY. Nothing here is implemented yet. Research + architecture
> decisions only.

---

## 1. The Product Idea (verbatim understanding)

Founders (like Likhith) waste time scrolling Instagram *while* their real build is
running / deploying / waiting. That dead time could be used to share *what they are
deciding, how they think, lessons* — founder-to-founder knowledge.

The blocker: making "reels" or video takes record → re-record → edit cycles that
eat the very time we are trying to reclaim, so the share never happens and we fall
back to scrolling.

The product:
- A founder shares **audio only** (fast to record, no video edit loop).
- The **platform auto-processes the audio into studio-quality** output — noise
  reduction, leveling, EQ, loudness normalization — via **algorithms + minimal AI**
  (pure DSP, no LLM needed for the audio chain).
- Listeners stream the cleaned audio.
- A **forensic watermark** is embedded per-listener so that if a listener leaks the
  audio, the leak can be traced back to *which listener/session* — deterring and
  attributing pirates.

### Business / monetization model (as specified)
- **Free tier**: listen free for `X` hours / month (X TBD).
- **Paid platform tier**: `Y` price gives **50 listening hours** / month.
- **Creator purchase pack**: a listener who trusts/likes a specific creator can buy
  a pack **priced by the creator** (creator sets the range) → **unlimited recordings
  from that creator**.
- **Creator earnings**: creators earn from packs + platform rev-share. This is a
  revenue event, so the forensic watermark (attribution) is what makes the
  creator-pack model safe to offer (unlimited from one creator = high leak risk
  without tracing).

This is a defensible v1: free discovery → paid platform → creator-aligned packs,
with watermarking as the trust backbone.

---

## 2. Architecture Plan (the researched "how")

### 2.1 The one decision that dominates everything: A/B VARIANT watermarking

**Never personalize bytes on the hot path.** If each listener receives unique bytes,
the CDN caches *nothing* (every request is a MISS) and the origin pays *one codec
pass per listener per segment* — concurrency caps in the low double digits no matter
how good the code is. This is exactly what the current MVP does (stateful
overlap-add watermark per session). On Cloudflare CDN with "many listeners" this
**will not scale**.

**Use A/B variant watermarking (Netflix/Sky/NAGRA pattern):**
1. At **ingest (once per asset)**: encode every HLS segment **twice** — variant `0`
   and variant `1` — differing only by the sign of a keyed spread-spectrum carrier.
   Paths: `assets/<asset_id>/v0/<seq>.ts` and `.../v1/<seq>.ts`.
2. Both variants are **immutable and identical for all users** → fully CDN-cacheable,
   `Cache-Control: public, max-age=31536000, immutable`.
3. **Per listener, generate only a manifest.** The listener's 32-bit attribution id
   expands to a codeword (magic + id + CRC); the manifest picks, segment by segment,
   whichever variant carries their next codeword bit. Personalization = *choice of
   files*, not bytes.
4. **Forensics**: correlate a recovered segment against the carrier for that position;
   the sign gives the bit. Bits vote into codeword slots; require **CRC to validate**
   before returning an id (so a false attribution needs a CRC collision, not just
   noise).

Trade: **2x storage**, zero origin CPU at playback, ~100% cache hit rate. On R2
(no egress fees) storage is the cheapest resource — take the trade.

### 2.2 Storage & delivery on Cloudflare

```
Creator upload ──▶ R2 (source master, encrypted at rest)
        │
        ▼
Ingest worker (queued, NOT inline):
  auto-enhance (DSP) ──▶ normalize 48k/2ch ──▶ HLS segment
  ├─ encode variant 0 (carrier +) ──▶ encrypt AES-128 (per-asset key) ──▶ R2 v0/
  └─ encode variant 1 (carrier -) ──▶ encrypt AES-128 (per-asset key) ──▶ R2 v1/
        │
        ▼
Cloudflare Worker (edge, in front of R2):
  - validate signed URL: HMAC-SHA256(object_key + expires), constant-time,
    object-key regex allowlist
  - cache key = object key ONLY (never the signed query string)
  - return immutable cache headers
        │
        ▼
Listener client (HLS.js):
  GET /manifest?sig=...  ──▶ server builds per-listener manifest
  (v0/v1 per segment by codeword) + short-TTL signed segment URLs + AES key URL
```

- **R2**: S3-compatible, **zero egress fees** → the correct home for audio streaming
  at scale (egress is the usual killer cost).
- **Worker**: edge token/signed-URL validation, manifest assembly, cache control.
  Keeps origin load at zero for media bytes.
- **HLS + AES-128-CBC**: per-ASSET key (NOT per-session — per-session key makes
  ciphertext unique and destroys caching). IV per `(asset, sequence, variant)`.
  Per-listener secrecy comes from the **signed manifest + short-TTL key endpoint**
  bound to a session capability; per-listener *attribution* comes from variant
  choices.

### 2.3 Signed + encrypted contract
- Signed URL: `HMAC-SHA256("<object_key>\n<expires_at>")`, base64url, padding
  stripped. Verify identically in Python (origin) AND Cloudflare Worker (WebCrypto) —
  cross-language HMAC is where silent mismatches hide; verify byte-identical output
  before trusting. Constant-time compare both sides. Short TTL 60–120s, refresh at
  50% expiry.
- This is **access control + traceability, NOT DRM**. Watermarking attributes copies
  *after the fact*; it does not prevent copying. Widevine/FairPlay is a later upgrade
  and does not change this architecture. State this plainly to any stakeholder.

### 2.4 Handling many listeners (scaling claim)
- Because personalization = choice of cached variants, CDN hit rate ≈ 100%, origin
  CPU per listener = 0. Concurrency ceiling = Cloudflare CDN capacity, not our code.
- **Verify the scaling claim in any future build**: issue N concurrent manifests and
  assert the per-listener build/encode counter is **0**. Never assert scalability in
  prose only.
- The current MVP's stateful per-session watermark is the opposite of this and must
  be migrated. (See §4.)

### 2.5 Auto-edit pipeline (minimal AI, algorithms)
Pure DSP, runs ONCE at ingest (scaling-friendly, not per-listener):
- `enhancer.py` (exists): high-pass filter, VAD-gated stationary-noise spectral
  attenuation, peak compression, limited make-up gain.
- `mastering.py` (exists): EQ, de-esser, multiband compression, saturation, LUFS
  normalization (-16 LUFS for spoken word), true-peak limiting.
- `pipeline.py` (exists): one-call enhance-then-master.
This is the "studio quality, automated, minimal AI" requirement — already prototyped
in this repo. Keep it DSP-only; no LLM in the audio chain.

### 2.6 Metering / quota enforcement (the tiers)
Currently **unbuilt** — the MVP has no metering ledger, so advertised tiers are
unenforced in code. Required for the model:
- Playback-duration ledger per listener (free X hrs, paid 50 hrs, creator-pack
  unlimited-from-creator-C).
- Enforce at manifest/key generation: if quota exhausted → 402/upgrade.
- Use Postgres (`SELECT ... FOR UPDATE` for concurrent-safe decrement) + Redis for
  hot quota counters. (The existing `multi_replica_fastapi` skill patterns cover
  this drop-in repo + Redis rate-limiter.)
- Cloudflare Worker can do edge token validation, but quota *state* lives in the
  origin DB — Worker passes the session capability, origin decides.

### 2.7 Creator earnings & payment
- Creator sets pack price range; buyer pays; platform rev-share; creator paid out.
- Payment: **Razorpay / UPI** (India-first, matches Oxiverse). Webhooks → entitlement.
- Leak attribution feeds trust: a leaked creator-pack recording → recover codeword →
  attribute listener → revoke access + takedown + (optionally) chargeback/legal.
- This is the P3 phase in the existing MVP (real IdP + Razorpay + payout). Unbuilt.

---

## 3. Research Findings (cited)

- **A/B forensic watermarking is the industry standard** (MovieLabs/ETSI DASH-IF for
  video; Tencent StreamLive, NAGRA, Kinescope for audio/video). Personalization =
  choice of A/B segments at the edge, no per-user encode. ~24 segments → 10M unique
  ids; invisible marks survive re-encoding, cropping, even camera capture.
  (kinescope.com/blog/forensic-watermarking, tencentcloud forensic watermark docs)
- **Spread-spectrum audio watermarking** embeds inaudible markers robust to
  compression/re-encoding; detection needs the original PN sequence. Used in music,
  podcasts, audiobooks, live broadcasts for traitor-tracing. (scoredetect.com)
- **CDN audio specifics**: segments are small (64–192 KB); cache hit ratio matters
  per-request. Best practice 2026: signed URLs with 60–120s TTL + token refresh at
  50%; long TTL + `immutable` for immutable assets; byte-range support for seeking;
  cache key ignores tracking querystrings; HTTP/3+QUIC. Mid-tier origin shield for
  long-tail. (blazingcdn guide, digitalhouse.cloud, webs.page/cdn-selection)
- **Encrypted HLS + AES-128 + session tokens** is the standard secure-audio delivery
  (Audiorista audiobook model: per-chapter AES-128, expiring session tokens,
  closed-loop app sandbox). Confirmed appropriate v1 for audio.
- **AudioDN** (audiodeliverynetwork.com) is a live service built on Cloudflare
  R2/Workers offering exactly upload + transcoding + signed delivery + playback.
  Reference / build-vs-buy benchmark. Given Oxiverse's build-in-public + privacy-first
  + control ethos, building on R2+Workers ourselves is more aligned, but AudioDN shows
  the target capability is real and shippable.
- **Auto audio cleanup tools** (Auphonic, Adobe Podcast, Descript, iZotope RX,
  Audacity spectral subtraction) confirm the DSP chain we already prototyped
  (noise reduction + leveling + LUFS) is the industry-standard "studio quality"
  automation. Our DSP-only approach is correct and avoids model runtime cost.

---

## 4. Critical Gap: current MVP watermark will NOT scale

The MVP's `docs/research_notes.md` describes **stateful per-session overlap-add
watermarking** (personalize bytes per session, encrypt after). This is the
per-session JIT approach that:
- makes the CDN cache 0% of segments (every listener = unique bytes),
- costs the origin one codec pass per listener per segment,
- caps concurrency in the low double digits.

On Cloudflare CDN with "many listeners" this is the #1 architectural blocker.

**Required migration**: replace the stateful watermark with the A/B variant scheme
(§2.1). Ingest encodes v0/v1 once; delivery is cacheable immutable objects; the
listener gets a manifest, not unique bytes. This is the single highest-priority
architecture change before any scale test.

Note: the `audio-forensic-watermark` Hermes skill references `variant_watermark.py`,
`ingest.py`, `variant_api.py` — these currently exist ONLY as compiled `.pyc` in
`__pycache__`, not as source in this repo. Reconcile before relying on them.

---

## 5. Build phases (roadmap, not yet started)

- **P1 — Ingest + A/B variant encode + R2 store**: encode v0/v1, AES-128 per-asset,
  push to R2, immutable cache headers. (Replaces stateful watermark.)
- **P2 — Cloudflare Worker signed-URL + manifest**: HMAC validation, per-listener
  manifest assembly from codeword, short-TTL key endpoint.
- **P3 — Metering + tiers + payment**: Postgres/Redis quota ledger, Razorpay/UPI,
  creator packs, rev-share payout. (Enforces the business model.)
- **P4 — Forensic recovery service**: upload leaked audio → recover codeword → CRC
  validate → attribute listener → revoke/takedown.
- **P5 — Client app**: HLS.js player, free/paid/pack UX, creator dashboard.

---

## 6. Open questions for Likhith

1. Free-tier `X` and paid `Y` — what numbers? (Drives metering + margin.)
2. Creator pack: "unlimited from that creator" — is it time-bounded (monthly) or
   one-time purchase? Affects entitlement model.
3. Geo: India-first (Razorpay/UPI, data-residency) or global (Stripe)?
4. Build on R2+Workers directly (control, OSS-aligned) vs AudioDN as delivery layer
   (faster, less control)? Recommend R2+Workers given Oxiverse ethos.
5. Do we want the watermark to also survive *analog* capture (phone recording the
   speaker)? A/B SSW survives re-encoding; true analog-hole robustness needs stronger
   carrier — confirm the threat model.

---

## 7. Agent operating notes (for the Hermes agent)

- When asked to "make this production ready" or "handle many listeners", the FIRST
  thing to check is whether watermarking is A/B variant (cacheable) or stateful
  (per-session). If stateful → stop and flag §4 before coding around it.
- Lead with the architectural verdict, not a task list.
- Never assert a scaling property not proven by a concurrent-manifest test (assert
  per-listener encode counter == 0).
- Relevant existing skills: `watermarked-cdn-streaming` (A/B variant reference docs:
  `references/ab_variant_watermarking.md`, `references/multi_replica_fastapi.md`),
  `audio-forensic-watermark` (detector pitfalls: AAC 1024-sample delay, alignment
  search, strength 0.02), `python-audio-dsp` / `python-audio-enhancement` (the
  auto-edit chain already in this repo's enhancer/mastering/pipeline).
- Privacy-by-design: no listener analytics without explicit opt-in; watermark secret
  + AES key never serialized in responses; attribution mapping stored server-side
  only. Aligns with Oxiverse OCL.
