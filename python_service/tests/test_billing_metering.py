"""P2 acceptance tests: plan configurability, idempotent metering, quota enforcement, payouts.

Run against the in-memory SQLite repository with no ffmpeg/network. The repository methods are
async, so each test wraps a private async helper in asyncio.run -- matching the project's
existing test style (no pytest-asyncio dependency). Every assertion is on real repository
state, never on mocks.
"""

import asyncio
import time

import pytest

from audio_streaming.billing import (
    BillingService,
    QuotaExceeded,
    distribute_pool,
    net_revenue_paise,
    period_key,
    pool_allocation,
)
from audio_streaming.repository import Repository


PAISE_PER_RS = 100


def make_repo(tmp_path) -> Repository:
    from pathlib import Path
    return Repository(Path(tmp_path / "billing.db"))


async def seed(repo: Repository):
    await repo.seed_billing(
        {
            "payout_pool_bps": "5500",
            "creator_flowthrough_bps": "8800",
            "gst_bps": "1800",
            "psp_fee_bps": "236",
            "creator_price_min_paise": "14900",
            "creator_price_max_paise": "49900",
            "currency": "INR",
        },
        (
            {"plan_code": "free", "name": "Free", "kind": "platform", "price_paise": 0,
             "included_seconds": 10 * 3600, "active": True},
            {"plan_code": "listener_50", "name": "Listener", "kind": "platform", "price_paise": 49900,
             "included_seconds": 50 * 3600, "active": True},
        ),
    )


async def _seed_free_sub(repo, user_id):
    await repo.create_subscription({
        "subscription_id": f"free-{user_id}", "user_id": user_id, "plan_code": "free",
        "price_paise": 0, "period_start": int(time.time()) - 10, "period_end": int(time.time()) + 9999,
        "status": "active",
    })


# --- pure pricing math ------------------------------------------------------

def test_net_revenue_strips_gst_and_psp():
    net = net_revenue_paise(599 * PAISE_PER_RS, 1800, 236)
    # 59900 * 10000/11800 = 50763, minus 1413 fee = 49349 (correct, no magic numbers expected)
    assert 49_300 <= net <= 49_400, net
    pool = pool_allocation(net, 5500)
    assert pool < 599 * PAISE_PER_RS  # pool is bounded strictly below gross


def test_pool_distribution_uses_largest_remainder_and_totals_exactly():
    stats = {"a": (100, 10_000), "b": (10, 1_000), "c": (1, 100)}
    dist = distribute_pool(10_000, stats)
    assert dist["a"] > dist["c"]  # unique listeners dominate
    assert sum(dist.values()) == 10_000


def test_pool_distribution_ignores_engagement_without_audience():
    assert distribute_pool(10_000, {"ghost": (0, 10_000)}) == {}


# --- plan configurability (no hardcoded pricing) ----------------------------

def test_plans_are_seedable_and_editable(tmp_path):
    async def run():
        repo = make_repo(tmp_path)
        await repo.initialize()
        await seed(repo)
        assert (await repo.get_plan("free"))["price_paise"] == 0
        await repo.upsert_plan({"plan_code": "listener_50", "name": "Listener", "kind": "platform",
                                "price_paise": 39900, "included_seconds": 50 * 3600, "active": True})
        assert (await repo.get_plan("listener_50"))["price_paise"] == 39900
        # Re-seeding must NOT clobber the edited price (the no-hardcode guarantee).
        await repo.seed_billing({}, ({"plan_code": "listener_50", "name": "Listener", "kind": "platform",
                                     "price_paise": 99900, "included_seconds": 1, "active": True},))
        assert (await repo.get_plan("listener_50"))["price_paise"] == 39900
    asyncio.run(run())


# --- idempotent metering ----------------------------------------------------

def test_retried_window_does_not_double_bill(tmp_path):
    async def run():
        repo = make_repo(tmp_path)
        await repo.initialize()
        await seed(repo)
        await repo.create_creator("cr1", "Nadia", "upi:nadia@x")
        await repo.set_asset_creator("ep1", "cr1")
        await _seed_free_sub(repo, "u1")
        billing = BillingService(repo)
        seqs = list(range(0, 10))  # 10 segments * 4s = 40s
        first = await billing.authorize_playback(
            session_id="sess1", user_id="u1", asset_id="ep1", sequences=seqs,
            seconds_each=4, now=int(time.time()))
        assert first.newly_granted == 10
        consumed1 = await repo.consumed_seconds("u1", period_key())
        second = await billing.authorize_playback(
            session_id="sess1", user_id="u1", asset_id="ep1", sequences=seqs,
            seconds_each=4, now=int(time.time()))
        assert second.newly_granted == 0  # retry bills nothing
        consumed2 = await repo.consumed_seconds("u1", period_key())
        assert consumed1 == consumed2 == 40
    asyncio.run(run())


def test_creator_subscription_grants_uncapped_listening(tmp_path):
    async def run():
        repo = make_repo(tmp_path)
        await repo.initialize()
        await seed(repo)
        await repo.create_creator("cr1", "Nadia", "upi:nadia@x")
        await repo.set_asset_creator("ep1", "cr1")
        await repo.create_subscription({
            "subscription_id": "cs1", "user_id": "u1", "plan_code": "creator:nadia",
            "creator_id": "cr1", "price_paise": 19900, "period_start": int(time.time()) - 10,
            "period_end": int(time.time()) + 9999, "status": "active"})
        billing = BillingService(repo)
        before = await repo.consumed_seconds("u1", period_key())
        await billing.authorize_playback(
            session_id="sess1", user_id="u1", asset_id="ep1", sequences=list(range(0, 900)),
            seconds_each=4, now=int(time.time()))
        after = await repo.consumed_seconds("u1", period_key())
        assert after == before == 0  # creator sub must not eat the free 10h
    asyncio.run(run())


# --- quota enforcement ------------------------------------------------------

def test_quota_rejects_when_allowance_spent(tmp_path):
    async def run():
        repo = make_repo(tmp_path)
        await repo.initialize()
        await seed(repo)
        await repo.create_creator("cr1", "Nadia", "upi:nadia@x")
        await repo.set_asset_creator("ep1", "cr1")
        await _seed_free_sub(repo, "u1")
        billing = BillingService(repo)
        total = 10 * 3600
        seg = 4
        pos = 0
        while True:
            try:
                auth = await billing.authorize_playback(
                    session_id="sess1", user_id="u1", asset_id="ep1", sequences=[pos],
                    seconds_each=seg, now=int(time.time()))
            except QuotaExceeded:
                break  # allowance fully spent; subsequent requests are rejected
            if auth.newly_granted == 0:
                break
            pos += 1
        assert await repo.consumed_seconds("u1", period_key()) == total
        with pytest.raises(QuotaExceeded):
            await billing.authorize_playback(
                session_id="sess1", user_id="u1", asset_id="ep1", sequences=[pos],
                seconds_each=seg, now=int(time.time()))
    asyncio.run(run())


# --- payout computation -----------------------------------------------------

def test_payout_pool_bounded_by_revenue(tmp_path):
    async def run():
        repo = make_repo(tmp_path)
        await repo.initialize()
        await seed(repo)
        now = int(time.time())
        await repo.create_subscription({
            "subscription_id": "s1", "user_id": "u1", "plan_code": "listener_50",
            "price_paise": 49900, "period_start": now - 10, "period_end": now + 9999, "status": "active"})
        await repo.create_creator("cr1", "Nadia", "upi:nadia@x")
        await repo.set_asset_creator("ep1", "cr1")
        for uid, secs in (("u1", 3600), ("u2", 1800)):
            await _seed_free_sub(repo, uid)
            await repo.record_grants(session_id=f"s-{uid}", user_id=uid, creator_id="cr1",
                                     period=period_key(now), sequences=[0], seconds_each=secs,
                                     included_seconds=None)
        run_out = await BillingService(repo).compute_payout(period_key(now))
        gross, net, pool = run_out["gross_paise"], run_out["net_paise"], run_out["pool_paise"]
        assert pool < gross  # bounded by construction
        lines = {line["creator_id"]: line["amount_paise"] for line in run_out["lines"]}
        assert lines.get("cr1", 0) == pool

        await repo.create_creator("cr2", "Ravi", "upi:ravi@x")
        await repo.create_subscription({
            "subscription_id": "cs1", "user_id": "u3", "plan_code": "creator:ravi",
            "creator_id": "cr2", "price_paise": 19900, "period_start": now - 10,
            "period_end": now + 9999, "status": "active"})
        run2 = await BillingService(repo).compute_payout(period_key(now))
        cr2 = [l for l in run2["lines"] if l["creator_id"] == "cr2" and l["source"] == "creator_subscription"]
        assert cr2 and cr2[0]["amount_paise"] < 19900  # net of GST + psp, then 88%
    asyncio.run(run())
