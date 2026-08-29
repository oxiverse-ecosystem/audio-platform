"""Postgres-backed repository for multi-replica deployment.

This is a drop-in replacement for ``repository.Repository`` (same async method surface) that
targets PostgreSQL via ``asyncpg``. It is selected automatically when ``AUDIO_DATABASE_URL`` is
set; otherwise the app keeps using the zero-dependency SQLite repository.

Key difference from the SQLite version: correctness under concurrency. The SQLite repo leans on
a single-process ``asyncio.Lock`` to make the "check quota, then debit" step atomic. With many
replicas that lock does not exist, so ``record_grants`` instead takes a ``SELECT ... FOR UPDATE``
row lock on the listener's ``usage_periods`` row inside a transaction. Postgres serializes the
two concurrent manifest requests that would otherwise both pass the quota check, so no
double-billing and no over-grant.

Schema: see ``migrations/0001_schema.sql``. It is the SQLite DDL translated to Postgres dialect
(``SERIAL``/``BIGSERIAL``, ``TIMESTAMPTZ`` where useful, ``ON CONFLICT`` upserts, no
``strftime`` -- date math uses ``to_char``/``date_trunc``).
"""

from __future__ import annotations

import os
import time
from typing import Any

from .models import AssetRecord, SessionRecord, VariantAssetRecord
from .security import stable_hash


class PostgresRepository:
    """Async PostgreSQL repository implementing the same contract as the SQLite ``Repository``."""

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool: Any = None

    async def initialize(self) -> None:
        import asyncpg  # imported here so the SQLite default path needs no Postgres driver
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # --- assets (legacy path) -------------------------------------------------

    async def save_asset(self, asset: AssetRecord) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO assets(asset_id,title,source_path,source_sha256,sample_rate,channels,
                segment_samples,segment_count,duration_samples,created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT(asset_id) DO UPDATE SET title=EXCLUDED.title""",
                asset.asset_id, asset.title, asset.source_path, asset.source_sha256, asset.sample_rate,
                asset.channels, asset.segment_samples, asset.segment_count, asset.duration_samples,
                asset.created_at,
            )

    async def get_asset(self, asset_id: str) -> AssetRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM assets WHERE asset_id=$1", asset_id)
        return AssetRecord(**dict(row)) if row else None

    async def set_entitlement(self, asset_id: str, user_id: str, allowed: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO entitlements(asset_id,user_id,allowed,updated_at) VALUES($1,$2,$3,$4)
                ON CONFLICT(asset_id,user_id) DO UPDATE SET allowed=EXCLUDED.allowed, updated_at=EXCLUDED.updated_at""",
                asset_id, user_id, bool(allowed), int(time.time()),
            )

    async def has_entitlement(self, asset_id: str, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT allowed FROM entitlements WHERE asset_id=$1 AND user_id=$2", asset_id, user_id)
        return bool(row and row["allowed"])

    async def active_session_count(self, user_id: str, now: int) -> int:
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM stream_sessions WHERE user_id=$1 AND status='active' AND expires_at>$2",
                user_id, now)
        return int(count)

    async def create_session(self, session: SessionRecord, *, key_purpose: str, derivation_version: str,
                            key_reference: str) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO stream_sessions(session_id,asset_id,user_id,watermark_id,created_at,expires_at,status)
                    VALUES($1,$2,$3,$4,$5,$6,$7)""",
                    session.session_id, session.asset_id, session.user_id, session.watermark_id,
                    session.created_at, session.expires_at, session.status)
                await conn.execute(
                    """INSERT INTO watermark_mappings(asset_id,watermark_id,session_id,user_audit_hash,created_at)
                    VALUES($1,$2,$3,$4,$5)""",
                    session.asset_id, session.watermark_id, session.session_id,
                    stable_hash(session.user_id), session.created_at)
                await conn.execute(
                    """INSERT INTO encryption_key_metadata(session_id,key_purpose,derivation_version,key_reference,created_at,expires_at,rotation_status)
                    VALUES($1,$2,$3,$4,$5,$6,'active')""",
                    session.session_id, key_purpose, derivation_version, key_reference,
                    session.created_at, session.expires_at)

    async def get_session(self, session_id: str) -> SessionRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM stream_sessions WHERE session_id=$1", session_id)
        return self._session_from_row(row) if row else None

    async def revoke_session(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE stream_sessions SET status='revoked' WHERE session_id=$1", session_id)

    async def attribution_lookup(self, asset_id: str, watermark_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT session_id,user_audit_hash,created_at FROM watermark_mappings WHERE asset_id=$1 AND watermark_id=$2",
                asset_id, watermark_id)
        return dict(row) if row else None

    async def encryption_key_metadata(self, session_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT key_purpose,derivation_version,key_reference,created_at,expires_at,rotation_status
                FROM encryption_key_metadata WHERE session_id=$1""", session_id)
        return dict(row) if row else None

    async def audit(self, event_type: str, outcome: str, *, session_id: str | None = None,
                    asset_id: str | None = None, user_id: str | None = None, latency_ms: float | None = None,
                    details: dict[str, Any] | None = None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_events(event_type,session_id,asset_id,user_audit_hash,outcome,latency_ms,details_json,created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                event_type, session_id, asset_id, stable_hash(user_id) if user_id else None, outcome,
                latency_ms, __import__("json").dumps(details or {}, sort_keys=True), int(time.time()))

    # --- variant (CDN A/B) streaming path -------------------------------------

    async def save_variant_asset(self, asset: VariantAssetRecord) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO variant_assets(asset_id,title,source_sha256,sample_rate,channels,segment_samples,segment_count,duration_samples,created_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT(asset_id) DO UPDATE SET title=EXCLUDED.title""",
                asset.asset_id, asset.title, asset.source_sha256, asset.sample_rate, asset.channels,
                asset.segment_samples, asset.segment_count, asset.duration_samples, asset.created_at)

    async def get_variant_asset(self, asset_id: str) -> VariantAssetRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM variant_assets WHERE asset_id=$1", asset_id)
        return VariantAssetRecord(**dict(row)) if row else None

    async def list_variant_assets(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT asset_id,title,sample_rate,channels,segment_count,duration_samples,created_at "
                "FROM variant_assets ORDER BY created_at DESC")
        return [dict(row) for row in rows]

    async def set_variant_entitlement(self, asset_id: str, user_id: str, allowed: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO variant_entitlements(asset_id,user_id,allowed,updated_at) VALUES($1,$2,$3,$4)
                ON CONFLICT(asset_id,user_id) DO UPDATE SET allowed=EXCLUDED.allowed, updated_at=EXCLUDED.updated_at""",
                asset_id, user_id, bool(allowed), int(time.time()))

    async def has_variant_entitlement(self, asset_id: str, user_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT allowed FROM variant_entitlements WHERE asset_id=$1 AND user_id=$2", asset_id, user_id)
        return bool(row and row["allowed"])

    async def active_variant_session_count(self, user_id: str, now: int) -> int:
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM variant_sessions WHERE user_id=$1 AND status='active' AND expires_at>$2",
                user_id, now)
        return int(count)

    async def create_variant_session(self, session: SessionRecord) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO variant_sessions(session_id,asset_id,user_id,watermark_id,created_at,expires_at,status)
                    VALUES($1,$2,$3,$4,$5,$6,$7)""",
                    session.session_id, session.asset_id, session.user_id, session.watermark_id,
                    session.created_at, session.expires_at, session.status)
                await conn.execute(
                    """INSERT INTO variant_watermark_mappings(asset_id,watermark_id,session_id,user_audit_hash,created_at)
                    VALUES($1,$2,$3,$4,$5)""",
                    session.asset_id, session.watermark_id, session.session_id,
                    stable_hash(session.user_id), session.created_at)

    async def get_variant_session(self, session_id: str) -> SessionRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM variant_sessions WHERE session_id=$1", session_id)
        return self._session_from_row(row) if row else None

    async def revoke_variant_session(self, session_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE variant_sessions SET status='revoked' WHERE session_id=$1", session_id)

    async def variant_attribution_lookup(self, asset_id: str, watermark_id: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT session_id,user_audit_hash,created_at FROM variant_watermark_mappings WHERE asset_id=$1 AND watermark_id=$2",
                asset_id, watermark_id)
        return dict(row) if row else None

    # --- P2: billing, metering, payouts ---------------------------------------

    async def seed_billing(self, config: dict[str, str], plans: tuple[dict[str, Any], ...]) -> None:
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for key, value in config.items():
                    await conn.execute(
                        """INSERT INTO billing_config(key,value,updated_at) VALUES($1,$2,$3)
                        ON CONFLICT(key) DO NOTHING""", key, value, now)
                for plan in plans:
                    await conn.execute(
                        """INSERT INTO plans(plan_code,name,kind,price_paise,included_seconds,active,created_at,updated_at)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                        ON CONFLICT(plan_code) DO NOTHING""",
                        plan["plan_code"], plan["name"], plan["kind"], plan["price_paise"],
                        plan["included_seconds"], bool(plan["active"]), now, now)

    async def get_config(self) -> dict[str, str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT key,value FROM billing_config")
        return {row["key"]: row["value"] for row in rows}

    async def set_config(self, key: str, value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO billing_config(key,value,updated_at) VALUES($1,$2,$3)
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
                key, value, int(time.time()))

    async def upsert_plan(self, plan: dict[str, Any]) -> None:
        now = int(time.time())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO plans(plan_code,name,kind,price_paise,included_seconds,active,created_at,updated_at)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT(plan_code) DO UPDATE SET
                    name=EXCLUDED.name, kind=EXCLUDED.kind, price_paise=EXCLUDED.price_paise,
                    included_seconds=EXCLUDED.included_seconds, active=EXCLUDED.active, updated_at=EXCLUDED.updated_at""",
                plan["plan_code"], plan["name"], plan["kind"], plan["price_paise"],
                plan["included_seconds"], bool(plan["active"]), now, now)

    async def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM plans WHERE plan_code=$1", plan_code)
        return dict(row) if row else None

    async def list_plans(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM plans" + (" WHERE active=TRUE" if active_only else "") + " ORDER BY price_paise"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [dict(row) for row in rows]

    async def create_creator(self, creator_id: str, display_name: str, payout_reference: str | None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO creators(creator_id,display_name,payout_reference,created_at) VALUES($1,$2,$3,$4)",
                creator_id, display_name, payout_reference, int(time.time()))

    async def set_asset_creator(self, asset_id: str, creator_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO asset_creators(asset_id,creator_id) VALUES($1,$2)
                ON CONFLICT(asset_id) DO UPDATE SET creator_id=EXCLUDED.creator_id""",
                asset_id, creator_id)

    async def get_asset_creator(self, asset_id: str) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT creator_id FROM asset_creators WHERE asset_id=$1", asset_id)
        return row["creator_id"] if row else None

    async def create_subscription(self, subscription: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO subscriptions(subscription_id,user_id,plan_code,creator_id,price_paise,period_start,period_end,status)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8)""",
                subscription["subscription_id"], subscription["user_id"], subscription["plan_code"],
                subscription.get("creator_id"), subscription["price_paise"], subscription["period_start"],
                subscription["period_end"], subscription["status"])

    async def active_platform_subscription(self, user_id: str, now: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT s.*, p.included_seconds, p.kind FROM subscriptions s
                JOIN plans p ON p.plan_code = s.plan_code
                WHERE s.user_id=$1 AND s.status='active' AND s.period_end > $2 AND p.kind='platform'
                ORDER BY (p.included_seconds IS NULL) DESC, p.included_seconds DESC LIMIT 1""",
                user_id, now)
        return dict(row) if row else None

    async def has_creator_subscription(self, user_id: str, creator_id: str, now: int) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT 1 FROM subscriptions WHERE user_id=$1 AND creator_id=$2 AND status='active'
                AND period_end > $3 LIMIT 1""", user_id, creator_id, now)
        return row is not None

    async def cancel_subscription(self, subscription_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id=$1", subscription_id)

    async def consumed_seconds(self, user_id: str, period: str) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT consumed_seconds FROM usage_periods WHERE user_id=$1 AND period_key=$2", user_id, period)
        return int(row["consumed_seconds"]) if row else 0

    async def record_grants(self, *, session_id: str, user_id: str, creator_id: str | None,
                            period: str, sequences: list[int], seconds_each: int,
                            included_seconds: int | None) -> tuple[int, int]:
        """Metered debit under Postgres row lock so concurrent replicas cannot double-grant.

        The listener's ``usage_periods`` row is locked with ``FOR UPDATE`` inside the
        transaction; a second concurrent request blocks until the first commits, then sees the
        updated ``consumed_seconds`` and honours the remaining allowance.
        """

        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Ensure the usage row exists, then lock it.
                await conn.execute(
                    """INSERT INTO usage_periods(user_id,period_key,consumed_seconds,updated_at)
                    VALUES($1,$2,0,$3) ON CONFLICT(user_id,period_key) DO NOTHING""",
                    user_id, period, now)
                consumed_row = await conn.fetchrow(
                    "SELECT consumed_seconds FROM usage_periods WHERE user_id=$1 AND period_key=$2 FOR UPDATE",
                    user_id, period)
                consumed = int(consumed_row["consumed_seconds"])

                existing = set()
                if sequences:
                    placeholders = ",".join(f"${i+3}" for i in range(len(sequences)))
                    rows = await conn.fetch(
                        f"SELECT sequence FROM segment_grants WHERE session_id=$1 AND sequence IN ({placeholders})",
                        session_id, *sequences)
                    existing = {int(r["sequence"]) for r in rows}
                fresh = [s for s in sequences if s not in existing]

                if included_seconds is not None:
                    affordable = max(0, (included_seconds - consumed) // seconds_each) if seconds_each else 0
                    fresh = fresh[:affordable]
                if not fresh:
                    return 0, consumed

                debit = len(fresh) * seconds_each
                await conn.executemany(
                    "INSERT INTO segment_grants(session_id,sequence,seconds,granted_at) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    [(session_id, sequence, seconds_each, now) for sequence in fresh])
                if included_seconds is not None:
                    await conn.execute(
                        """INSERT INTO usage_periods(user_id,period_key,consumed_seconds,updated_at)
                        VALUES($1,$2,$3,$4)
                        ON CONFLICT(user_id,period_key) DO UPDATE SET consumed_seconds = usage_periods.consumed_seconds + EXCLUDED.consumed_seconds""",
                        user_id, period, debit, now)
                if creator_id is not None:
                    await conn.execute(
                        """INSERT INTO creator_usage(creator_id,period_key,user_id,seconds) VALUES($1,$2,$3,$4)
                        ON CONFLICT(creator_id,period_key,user_id) DO UPDATE SET seconds = creator_usage.seconds + EXCLUDED.seconds""",
                        creator_id, period, user_id, debit)
                return len(fresh), consumed + (debit if included_seconds is not None else 0)

    async def creator_period_stats(self, period: str) -> dict[str, tuple[int, int]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT creator_id, COUNT(DISTINCT user_id) AS listeners, COALESCE(SUM(seconds),0) AS seconds
                FROM creator_usage WHERE period_key=$1 GROUP BY creator_id""", period)
        return {row["creator_id"]: (int(row["listeners"]), int(row["seconds"])) for row in rows}

    async def platform_revenue_paise(self, period: str) -> int:
        async with self._pool.acquire() as conn:
            gross = await conn.fetchval(
                """SELECT COALESCE(SUM(s.price_paise),0) FROM subscriptions s
                JOIN plans p ON p.plan_code=s.plan_code
                WHERE p.kind='platform' AND s.status='active' AND to_char(to_timestamp(s.period_start),'YYYY-MM')=$1""",
                period)
        return int(gross)

    async def creator_subscription_revenue(self, period: str) -> dict[str, int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT creator_id, COALESCE(SUM(price_paise),0) AS gross FROM subscriptions
                WHERE creator_id IS NOT NULL AND status='active'
                AND to_char(to_timestamp(period_start),'YYYY-MM')=$1 GROUP BY creator_id""", period)
        return {row["creator_id"]: int(row["gross"]) for row in rows}

    async def save_payout_run(self, period: str, gross: int, net: int, pool: int,
                              lines: list[dict[str, Any]]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO payout_runs(period_key,gross_paise,net_paise,pool_paise,computed_at)
                    VALUES($1,$2,$3,$4,$5)
                    ON CONFLICT(period_key) DO UPDATE SET gross_paise=EXCLUDED.gross_paise, net_paise=EXCLUDED.net_paise,
                        pool_paise=EXCLUDED.pool_paise, computed_at=EXCLUDED.computed_at""",
                    period, gross, net, pool, int(time.time()))
                await conn.execute("DELETE FROM payout_lines WHERE period_key=$1", period)
                if lines:
                    await conn.executemany(
                        """INSERT INTO payout_lines(period_key,creator_id,source,amount_paise,unique_listeners,listened_seconds)
                        VALUES($1,$2,$3,$4,$5,$6)""",
                        [(period, line["creator_id"], line["source"], line["amount_paise"],
                          line.get("unique_listeners", 0), line.get("listened_seconds", 0)) for line in lines])

    async def get_payout_run(self, period: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            run = await conn.fetchrow("SELECT * FROM payout_runs WHERE period_key=$1", period)
            if run is None:
                return None
            lines = await conn.fetch("SELECT * FROM payout_lines WHERE period_key=$1 ORDER BY amount_paise DESC", period)
        return {**dict(run), "lines": [dict(line) for line in lines]}

    @staticmethod
    def _session_from_row(row: dict[str, Any]) -> SessionRecord:
        return SessionRecord(**dict(row))


def build_repository(settings) -> "Repository | object":
    """Return a Postgres repository when configured, else the SQLite repository.

    Postgres deps (asyncpg) are imported lazily so the SQLite default runs with zero extra
    dependencies. Set ``AUDIO_DATABASE_URL`` to a ``postgresql://`` DSN to switch to the
    multi-replica backend; the rest of the code depends only on the shared async method contract.
    """

    dsn = os.getenv("AUDIO_DATABASE_URL", "").strip()
    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        from .postgres_repository import PostgresRepository
        return PostgresRepository(dsn)
    from .repository import Repository
    return Repository(settings.database_path)
