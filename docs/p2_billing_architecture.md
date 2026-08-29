# P2 — Plans, Metering, and Payouts

Implements the `X / Y / Z` market model from the research report as **runtime-editable
database rows** (never code constants), meters playback **server-authoritatively** on the
CDN checkpoint, and computes creator payouts from **revenue-share pools only** (no fixed
per-play rate, so payout is bounded by construction).

## Why pricing lives in the database

The research numbers (X=15h free, Y=₹199–499 creator tiers, Z=50h @ ₹499) are starting
hypotheses, not truth. We expect to revise them several times before launch and A/B test
variants. Hardcoding them would make every price change a deploy. Instead:

- `plans` table: every plan (free, platform, creator) is a row with `price_paise`,
  `included_seconds` (NULL = unlimited), `active`. Editing a price is `PUT /v1/plans/{code}`.
- `billing_config` table: pool share, creator flow-through rate, GST/PSP bps — all editable.
- `seed_billing()` only inserts rows where absent (`ON CONFLICT DO NOTHING`), so a runtime
  edit is never clobbered by a restart.

## Metering model

**Charge on grant, not on client heartbeat.** The client never reports position; the server
does. Signed CDN URLs expire (300s), so the player must return to `/playlist.m3u8?position=N`
to fetch more. Each request meters a ~5-minute sliding **window** starting at `N`:

1. Resolve the listener's allowance: a creator subscription to the asset's creator → uncapped;
   else their highest active platform plan; else the free default.
2. `BillingService.authorize_playback` calls `repository.record_grants`, which is atomic:
   it de-dupes by `(session_id, sequence)` so a retried request bills **nothing** new, checks
   the remaining allowance under the same lock it debits (no interleaving race), and refuses
   to over-grant.
3. On exhaustion it raises `QuotaExceeded` → HTTP 402, so the client can show an upgrade.

This is honest: we debit only the audio we actually hand out. Billing per full episode up front
would over-charge listeners who abandon after 2 minutes.

## Idempotency

The `segment_grants` ledger is keyed `(session_id, sequence)`. A network retry or a seek-back
to an already-granted window finds the row present and grants 0 new seconds. Verified by
`test_retried_window_does_not_double_bill`.

## Payout model

Two bounded streams, both derived from **net** revenue (gross minus 18% GST and ~2.36% PSP,
because Indian consumer pricing is gross-inclusive):

1. **Pool (platform plans):** `payout_pool_bps` (default 55%) of net platform revenue, split
   across creators by `unique_listeners × sqrt(listened_seconds)` with largest-remainder
   rounding so the total equals the pool exactly.
2. **Creator subscriptions:** flow through at `creator_flowthrough_bps` (default 88%).

There is deliberately **no fixed per-play payout**. A fixed rate × heavy listening can exceed
that listener's subscription (the original report's ₹2/play figure loses money on a 300h/month
user). The pool share of net revenue can never exceed net revenue.

## Honest limitations (this is P2, not production)

- SQLite + in-process lock → **single replica only**. Horizontal scale needs Postgres + Redis
  (P1) with the same repository interface.
- Accounts are self-issued HMAC identities; no real IdP. Subscriptions are created via admin
  endpoints here, not a checkout flow. P3 wires Razorpay/UPI and real auth.
- Payouts are computed, not disbursed. `POST /v1/payouts/compute` writes `payout_runs` /
  `payout_lines`; actual bank/UPI transfer is out of scope.
- No proration, no refunds, no multi-currency. The schema leaves room (per-creator payout
  reference, period keys) but the machinery is future work.
