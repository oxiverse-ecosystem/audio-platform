"""Plans, subscriptions, entitlement resolution, listening meter, and payout computation.

Design rules this module exists to honour
----------------------------------------
1. **Nothing about pricing is a constant.** Plans, prices, included hours, the payout pool
   share and the creator flow-through rate all live in database rows and are editable at
   runtime. X, Y and Z will be revised repeatedly before launch; changing one must be a row
   update, never a deploy.
2. **Metering is server-authoritative.** The meter never trusts a client-reported position.
   Because signed CDN URLs expire, the player is forced to return to the origin for more
   segments -- that refresh is the natural, unavoidable checkpoint. We debit the audio we
   actually hand out.
3. **Grants are idempotent.** A network retry or a player re-requesting a manifest must not
   bill twice, so each (session, sequence) grant is recorded once and only newly granted
   segments are debited.
4. **Payouts are bounded by revenue, never by a fixed per-play rate.** A fixed rate multiplied
   by an engaged listener's hours can exceed that listener's subscription -- the platform then
   loses money on its best users. The pool is a share of net revenue, so it cannot.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone


class BillingError(ValueError):
    """Raised for an invalid plan, subscription, or quota condition."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.status_code = status_code


class QuotaExceeded(BillingError):
    """Raised when a listener has consumed their plan's included hours for the period."""

    def __init__(self, detail: str = "listening quota exhausted for this period"):
        super().__init__(detail, status_code=402)


# --- configuration defaults -------------------------------------------------
# These are SEED VALUES for a fresh database only. They are written as rows on first
# initialization and are editable at runtime; the code always reads the rows, never these.
SEED_CONFIG: dict[str, str] = {
    "payout_pool_bps": "5500",             # 55% of net platform-plan revenue to creators
    "creator_flowthrough_bps": "8800",     # creators keep 88% of their own subscriptions
    "gst_bps": "1800",                     # 18% GST, prices are gross-inclusive
    "psp_fee_bps": "236",                  # ~2% + GST on the fee
    "creator_price_min_paise": "14900",    # Rs 149 floor for a creator tier
    "creator_price_max_paise": "49900",    # Rs 499 ceiling for a creator tier
    "currency": "INR",
}

SEED_PLANS: tuple[dict[str, object], ...] = (
    {
        "plan_code": "free",
        "name": "Free",
        "kind": "platform",
        "price_paise": 0,
        "included_seconds": 10 * 3600,     # X = 10 h / month
        "active": True,
    },
    {
        "plan_code": "listener_50",
        "name": "Listener",
        "kind": "platform",
        "price_paise": 49900,              # Z = Rs 499 / month
        "included_seconds": 50 * 3600,     # 50 h / month
        "active": True,
    },
)


@dataclass(frozen=True)
class Plan:
    plan_code: str
    name: str
    kind: str
    price_paise: int
    included_seconds: int | None  # None means unlimited
    active: bool


@dataclass(frozen=True)
class Subscription:
    subscription_id: str
    user_id: str
    plan_code: str
    creator_id: str | None
    price_paise: int
    period_start: int
    period_end: int
    status: str


@dataclass(frozen=True)
class UsageSnapshot:
    """What a listener has consumed and what remains, for one billing period."""

    user_id: str
    period_key: str
    plan_code: str
    included_seconds: int | None
    consumed_seconds: int

    @property
    def unlimited(self) -> bool:
        return self.included_seconds is None

    @property
    def remaining_seconds(self) -> int | None:
        if self.included_seconds is None:
            return None
        return max(0, self.included_seconds - self.consumed_seconds)

    @property
    def exhausted(self) -> bool:
        return self.remaining_seconds == 0


def period_key(moment: int | None = None) -> str:
    """Calendar-month billing period in UTC, e.g. ``2026-08``."""

    stamp = datetime.fromtimestamp(moment if moment is not None else int(time.time()), tz=timezone.utc)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def net_revenue_paise(gross_paise: int, gst_bps: int, psp_fee_bps: int) -> int:
    """Revenue actually available to the platform after tax and payment processing.

    Indian consumer pricing is quoted gross-inclusive, so GST is carved out of the displayed
    price rather than added to it. Payout math must run on this figure, not on the sticker
    price, or the pool silently overpays.
    """

    if gross_paise < 0:
        raise BillingError("gross revenue must not be negative")
    base = round(gross_paise * 10_000 / (10_000 + gst_bps))
    fee = round(gross_paise * psp_fee_bps / 10_000)
    return max(0, base - fee)


def pool_allocation(net_paise: int, pool_bps: int) -> int:
    """The creator pool for a period: a share of net revenue, so it can never exceed it."""

    if not 0 <= pool_bps <= 10_000:
        raise BillingError("payout pool share must be between 0 and 10000 bps")
    return round(net_paise * pool_bps / 10_000)


def distribute_pool(
    pool_paise: int,
    creator_stats: dict[str, tuple[int, int]],
) -> dict[str, int]:
    """Split the pool across creators, weighting unique listeners above raw seconds.

    ``creator_stats`` maps creator_id -> (unique_listeners, listened_seconds).

    Weighting by unique listeners rather than by volume alone is deliberate: a pure
    seconds-share model pays the loudest few and starves niche creators, which is the known
    failure of pro-rata streaming payouts. Reach is the multiplier; time is the base.
    The largest-remainder method is used so the distributed total equals the pool exactly --
    a rounding drift would silently create or destroy money.
    """

    if pool_paise <= 0 or not creator_stats:
        return {}
    weights: dict[str, float] = {}
    for creator_id, (unique_listeners, seconds) in creator_stats.items():
        if unique_listeners <= 0 or seconds <= 0:
            continue
        weights[creator_id] = float(unique_listeners) * float(seconds) ** 0.5
    total = sum(weights.values())
    if total <= 0:
        return {}
    exact = {creator_id: pool_paise * weight / total for creator_id, weight in weights.items()}
    floors = {creator_id: int(value) for creator_id, value in exact.items()}
    remainder = pool_paise - sum(floors.values())
    for creator_id in sorted(exact, key=lambda key: exact[key] - floors[key], reverse=True):
        if remainder <= 0:
            break
        floors[creator_id] += 1
        remainder -= 1
    return {creator_id: amount for creator_id, amount in floors.items() if amount > 0}


def creator_subscription_split(price_paise: int, flowthrough_bps: int, gst_bps: int, psp_fee_bps: int) -> tuple[int, int]:
    """Split one creator subscription into (creator_earnings, platform_cut), both on net."""

    net = net_revenue_paise(price_paise, gst_bps, psp_fee_bps)
    creator = round(net * flowthrough_bps / 10_000)
    return creator, net - creator


@dataclass(frozen=True)
class PlaybackAuthorization:
    plan_code: str
    included_seconds: int | None
    consumed_seconds: int
    newly_granted: int


class BillingService:
    """Resolves plans, meters playback, and computes payouts against the repository.

    The repository is injected (no import from this module) so billing logic stays testable
    in isolation and the storage backend can be swapped without touching pricing rules.
    """

    def __init__(self, repository):
        self.repository = repository

    async def resolve_allowance(self, user_id: str, asset_id: str, now: int) -> tuple[str, int | None]:
        """Return ``(plan_code, included_seconds)`` for a playback request.

        A creator subscription to the asset's creator grants uncapped listening to that
        creator's catalogue, independent of the listener's platform plan. Otherwise the
        listener's highest platform plan (or the free default) sets the monthly allowance.
        """

        creator_id = await self.repository.get_asset_creator(asset_id)
        if creator_id is not None and await self.repository.has_creator_subscription(user_id, creator_id, now):
            return f"creator:{creator_id}", None
        sub = await self.repository.active_platform_subscription(user_id, now)
        if sub is not None:
            return sub["plan_code"], sub.get("included_seconds")
        free = await self.repository.get_plan("free")
        if free is None:
            raise BillingError("no 'free' plan configured")
        return free["plan_code"], free.get("included_seconds")

    async def authorize_playback(
        self,
        *,
        session_id: str,
        user_id: str,
        asset_id: str,
        sequences: list[int],
        seconds_each: int,
        now: int,
    ) -> PlaybackAuthorization:
        """Meter a window of segments. Raises QuotaExceeded when nothing can be granted."""

        period = period_key(now)
        plan_code, included = await self.resolve_allowance(user_id, asset_id, now)
        newly, consumed = await self.repository.record_grants(
            session_id=session_id,
            user_id=user_id,
            creator_id=await self.repository.get_asset_creator(asset_id),
            period=period,
            sequences=sequences,
            seconds_each=seconds_each,
            included_seconds=included,
        )
        # Rejected entirely because the allowance is spent.
        if newly == 0 and included is not None and consumed >= included:
            raise QuotaExceeded(
                f"listening quota for plan '{plan_code}' exhausted this period "
                f"({consumed} of {included} seconds used)"
            )
        return PlaybackAuthorization(plan_code, included, consumed, newly)

    async def compute_payout(self, period: str) -> dict[str, object]:
        """Compute and persist creator payouts for a monthly period.

        Platform-plan revenue feeds the revenue-share pool (bounded by construction); creator
        subscription revenue flows through at the configured rate. No fixed per-play rate
        exists, so total payout can never exceed net revenue.
        """

        config = await self.repository.get_config()
        gst_bps = int(config["gst_bps"])
        psp_fee_bps = int(config["psp_fee_bps"])
        pool_bps = int(config["payout_pool_bps"])
        flowthrough_bps = int(config["creator_flowthrough_bps"])

        gross_platform = await self.repository.platform_revenue_paise(period)
        net = net_revenue_paise(gross_platform, gst_bps, psp_fee_bps)
        pool = pool_allocation(net, pool_bps)
        stats = await self.repository.creator_period_stats(period)
        pool_lines = distribute_pool(pool, stats)
        creator_subs = await self.repository.creator_subscription_revenue(period)

        lines: list[dict[str, object]] = []
        for creator_id, amount in pool_lines.items():
            unique, seconds = stats[creator_id]
            lines.append({
                "creator_id": creator_id,
                "source": "pool",
                "amount_paise": amount,
                "unique_listeners": unique,
                "listened_seconds": seconds,
            })
        for creator_id, gross in creator_subs.items():
            creator_amount, _ = creator_subscription_split(gross, flowthrough_bps, gst_bps, psp_fee_bps)
            lines.append({
                "creator_id": creator_id,
                "source": "creator_subscription",
                "amount_paise": creator_amount,
                "unique_listeners": 0,
                "listened_seconds": 0,
            })
        await self.repository.save_payout_run(period, gross_platform, net, pool, lines)
        return await self.repository.get_payout_run(period)
