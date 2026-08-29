"""Small SQLite repository; production can replace it with a managed relational database."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .models import AssetRecord, SessionRecord, VariantAssetRecord
from .security import stable_hash


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    segment_samples INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    duration_samples INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entitlements (
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (asset_id, user_id)
);
CREATE TABLE IF NOT EXISTS stream_sessions (
    session_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    user_id TEXT NOT NULL,
    watermark_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','revoked','expired'))
);
CREATE INDEX IF NOT EXISTS stream_sessions_user_active ON stream_sessions(user_id, status, expires_at);
CREATE TABLE IF NOT EXISTS watermark_mappings (
    asset_id TEXT NOT NULL,
    watermark_id INTEGER NOT NULL,
    session_id TEXT NOT NULL UNIQUE REFERENCES stream_sessions(session_id),
    user_audit_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(asset_id, watermark_id)
);
CREATE TABLE IF NOT EXISTS encryption_key_metadata (
    session_id TEXT PRIMARY KEY REFERENCES stream_sessions(session_id) ON DELETE CASCADE,
    key_purpose TEXT NOT NULL,
    derivation_version TEXT NOT NULL,
    key_reference TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    rotation_status TEXT NOT NULL CHECK(rotation_status IN ('active','retired'))
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    session_id TEXT,
    asset_id TEXT,
    user_audit_hash TEXT,
    outcome TEXT NOT NULL,
    latency_ms REAL,
    details_json TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_created_at ON audit_events(created_at);
CREATE TABLE IF NOT EXISTS variant_assets (
    asset_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    segment_samples INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    duration_samples INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS variant_sessions (
    session_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES variant_assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    watermark_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','revoked','expired'))
);
CREATE INDEX IF NOT EXISTS variant_sessions_user_active ON variant_sessions(user_id, status, expires_at);
CREATE TABLE IF NOT EXISTS variant_entitlements (
    asset_id TEXT NOT NULL REFERENCES variant_assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (asset_id, user_id)
);
CREATE TABLE IF NOT EXISTS variant_watermark_mappings (
    asset_id TEXT NOT NULL,
    watermark_id INTEGER NOT NULL,
    session_id TEXT NOT NULL UNIQUE REFERENCES variant_sessions(session_id) ON DELETE CASCADE,
    user_audit_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(asset_id, watermark_id)
);
-- --- P2: plans, subscriptions, metering, payouts -------------------------------
-- Every pricing number lives in these rows, never in code, so X/Y/Z can be revised
-- and A/B tested without a deploy.
CREATE TABLE IF NOT EXISTS billing_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    plan_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('platform','creator')),
    price_paise INTEGER NOT NULL CHECK(price_paise >= 0),
    -- NULL means unlimited listening.
    included_seconds INTEGER CHECK(included_seconds IS NULL OR included_seconds >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS creators (
    creator_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    plan_code TEXT REFERENCES plans(plan_code),
    payout_reference TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    -- creator subscriptions use a 'creator:<id>' code that intentionally does not exist in
    -- the platform plans table; hence no FK here.
    plan_code TEXT NOT NULL,
    creator_id TEXT REFERENCES creators(creator_id),
    price_paise INTEGER NOT NULL CHECK(price_paise >= 0),
    period_start INTEGER NOT NULL,
    period_end INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','cancelled','expired'))
);
CREATE INDEX IF NOT EXISTS subscriptions_user_active ON subscriptions(user_id, status, period_end);
CREATE INDEX IF NOT EXISTS subscriptions_creator ON subscriptions(creator_id, status);
-- Assets belong to a creator so listening can be attributed for payouts.
CREATE TABLE IF NOT EXISTS asset_creators (
    asset_id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL REFERENCES creators(creator_id) ON DELETE CASCADE
);
-- Idempotent grant ledger: one row per (session, sequence). A retried request finds the
-- row already present and is therefore not billed twice.
CREATE TABLE IF NOT EXISTS segment_grants (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    seconds INTEGER NOT NULL,
    granted_at INTEGER NOT NULL,
    PRIMARY KEY (session_id, sequence)
);
CREATE TABLE IF NOT EXISTS usage_periods (
    user_id TEXT NOT NULL,
    period_key TEXT NOT NULL,
    consumed_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, period_key)
);
-- Per-creator listening within a period, for pool distribution.
CREATE TABLE IF NOT EXISTS creator_usage (
    creator_id TEXT NOT NULL,
    period_key TEXT NOT NULL,
    user_id TEXT NOT NULL,
    seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (creator_id, period_key, user_id)
);
CREATE TABLE IF NOT EXISTS payout_runs (
    period_key TEXT PRIMARY KEY,
    gross_paise INTEGER NOT NULL,
    net_paise INTEGER NOT NULL,
    pool_paise INTEGER NOT NULL,
    computed_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS payout_lines (
    period_key TEXT NOT NULL REFERENCES payout_runs(period_key) ON DELETE CASCADE,
    creator_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('pool','creator_subscription')),
    amount_paise INTEGER NOT NULL,
    unique_listeners INTEGER NOT NULL DEFAULT 0,
    listened_seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (period_key, creator_id, source)
);
"""


class Repository:
    """Async-serialized SQLite access suitable for a single-process MVP."""

    def __init__(self, path: Path):
        self._path = path
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            self._connection = sqlite3.connect(self._path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
            self._connection.executescript(SCHEMA)
            self._connection.commit()

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("repository has not been initialized")
        return self._connection

    async def save_asset(self, asset: AssetRecord) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO assets(asset_id,title,source_path,source_sha256,sample_rate,channels,segment_samples,segment_count,duration_samples,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (asset.asset_id, asset.title, asset.source_path, asset.source_sha256, asset.sample_rate, asset.channels,
                 asset.segment_samples, asset.segment_count, asset.duration_samples, asset.created_at),
            )
            self._db().commit()

    async def get_asset(self, asset_id: str) -> AssetRecord | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        return self._asset_from_row(row) if row else None

    async def set_entitlement(self, asset_id: str, user_id: str, allowed: bool) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO entitlements(asset_id,user_id,allowed,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(asset_id,user_id) DO UPDATE SET allowed=excluded.allowed, updated_at=excluded.updated_at""",
                (asset_id, user_id, int(allowed), int(time.time())),
            )
            self._db().commit()

    async def has_entitlement(self, asset_id: str, user_id: str) -> bool:
        async with self._lock:
            row = self._db().execute(
                "SELECT allowed FROM entitlements WHERE asset_id=? AND user_id=?", (asset_id, user_id)
            ).fetchone()
        return bool(row and row["allowed"])

    async def active_session_count(self, user_id: str, now: int) -> int:
        async with self._lock:
            row = self._db().execute(
                "SELECT COUNT(*) AS count FROM stream_sessions WHERE user_id=? AND status='active' AND expires_at>?",
                (user_id, now),
            ).fetchone()
        return int(row["count"])

    async def create_session(
        self,
        session: SessionRecord,
        *,
        key_purpose: str,
        derivation_version: str,
        key_reference: str,
    ) -> None:
        async with self._lock:
            db = self._db()
            db.execute(
                "INSERT INTO stream_sessions(session_id,asset_id,user_id,watermark_id,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?)",
                (session.session_id, session.asset_id, session.user_id, session.watermark_id, session.created_at,
                 session.expires_at, session.status),
            )
            db.execute(
                "INSERT INTO watermark_mappings(asset_id,watermark_id,session_id,user_audit_hash,created_at) VALUES(?,?,?,?,?)",
                (session.asset_id, session.watermark_id, session.session_id, stable_hash(session.user_id), session.created_at),
            )
            db.execute(
                """INSERT INTO encryption_key_metadata(session_id,key_purpose,derivation_version,key_reference,created_at,expires_at,rotation_status)
                VALUES(?,?,?,?,?,?,?)""",
                (session.session_id, key_purpose, derivation_version, key_reference, session.created_at, session.expires_at, "active"),
            )
            db.commit()

    async def get_session(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM stream_sessions WHERE session_id=?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    async def revoke_session(self, session_id: str) -> None:
        async with self._lock:
            self._db().execute("UPDATE stream_sessions SET status='revoked' WHERE session_id=?", (session_id,))
            self._db().commit()

    async def attribution_lookup(self, asset_id: str, watermark_id: int) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute(
                "SELECT session_id,user_audit_hash,created_at FROM watermark_mappings WHERE asset_id=? AND watermark_id=?",
                (asset_id, watermark_id),
            ).fetchone()
        return dict(row) if row else None

    async def encryption_key_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Return versioned operational metadata only; no raw or encrypted AES key is stored."""

        async with self._lock:
            row = self._db().execute(
                """SELECT key_purpose,derivation_version,key_reference,created_at,expires_at,rotation_status
                FROM encryption_key_metadata WHERE session_id=?""",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    async def audit(
        self,
        event_type: str,
        outcome: str,
        *,
        session_id: str | None = None,
        asset_id: str | None = None,
        user_id: str | None = None,
        latency_ms: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_details = details or {}
        async with self._lock:
            self._db().execute(
                """INSERT INTO audit_events(event_type,session_id,asset_id,user_audit_hash,outcome,latency_ms,details_json,created_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                (event_type, session_id, asset_id, stable_hash(user_id) if user_id else None, outcome, latency_ms,
                 json.dumps(safe_details, sort_keys=True), int(time.time())),
            )
            self._db().commit()

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(**dict(row))

    # --- variant (CDN A/B) streaming path -------------------------------------

    async def save_variant_asset(self, asset: VariantAssetRecord) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO variant_assets(asset_id,title,source_sha256,sample_rate,channels,segment_samples,
                segment_count,duration_samples,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (asset.asset_id, asset.title, asset.source_sha256, asset.sample_rate, asset.channels,
                 asset.segment_samples, asset.segment_count, asset.duration_samples, asset.created_at),
            )
            self._db().commit()

    async def get_variant_asset(self, asset_id: str) -> VariantAssetRecord | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM variant_assets WHERE asset_id=?", (asset_id,)).fetchone()
        return VariantAssetRecord(**dict(row)) if row else None

    async def set_variant_entitlement(self, asset_id: str, user_id: str, allowed: bool) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO variant_entitlements(asset_id,user_id,allowed,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(asset_id,user_id) DO UPDATE SET allowed=excluded.allowed, updated_at=excluded.updated_at""",
                (asset_id, user_id, int(allowed), int(time.time())),
            )
            self._db().commit()

    async def has_variant_entitlement(self, asset_id: str, user_id: str) -> bool:
        async with self._lock:
            row = self._db().execute(
                "SELECT allowed FROM variant_entitlements WHERE asset_id=? AND user_id=?", (asset_id, user_id)
            ).fetchone()
        return bool(row and row["allowed"])

    async def active_variant_session_count(self, user_id: str, now: int) -> int:
        async with self._lock:
            row = self._db().execute(
                "SELECT COUNT(*) AS count FROM variant_sessions WHERE user_id=? AND status='active' AND expires_at>?",
                (user_id, now),
            ).fetchone()
        return int(row["count"])

    async def create_variant_session(self, session: SessionRecord) -> None:
        async with self._lock:
            db = self._db()
            db.execute(
                """INSERT INTO variant_sessions(session_id,asset_id,user_id,watermark_id,created_at,expires_at,status)
                VALUES(?,?,?,?,?,?,?)""",
                (session.session_id, session.asset_id, session.user_id, session.watermark_id, session.created_at,
                 session.expires_at, session.status),
            )
            db.execute(
                """INSERT INTO variant_watermark_mappings(asset_id,watermark_id,session_id,user_audit_hash,created_at)
                VALUES(?,?,?,?,?)""",
                (session.asset_id, session.watermark_id, session.session_id, stable_hash(session.user_id),
                 session.created_at),
            )
            db.commit()

    async def get_variant_session(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM variant_sessions WHERE session_id=?", (session_id,)).fetchone()
        return self._session_from_row(row) if row else None

    async def revoke_variant_session(self, session_id: str) -> None:
        async with self._lock:
            self._db().execute("UPDATE variant_sessions SET status='revoked' WHERE session_id=?", (session_id,))
            self._db().commit()

    async def variant_attribution_lookup(self, asset_id: str, watermark_id: int) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute(
                """SELECT session_id,user_audit_hash,created_at FROM variant_watermark_mappings
                WHERE asset_id=? AND watermark_id=?""",
                (asset_id, watermark_id),
            ).fetchone()
        return dict(row) if row else None


    # --- P2: billing, metering, payouts ---------------------------------------

    async def seed_billing(self, config: dict[str, str], plans: tuple[dict[str, Any], ...]) -> None:
        """Insert seed config/plans only where absent, so runtime edits are never overwritten."""

        now = int(time.time())
        async with self._lock:
            db = self._db()
            for key, value in config.items():
                db.execute(
                    "INSERT INTO billing_config(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO NOTHING",
                    (key, value, now),
                )
            for plan in plans:
                db.execute(
                    """INSERT INTO plans(plan_code,name,kind,price_paise,included_seconds,active,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(plan_code) DO NOTHING""",
                    (plan["plan_code"], plan["name"], plan["kind"], plan["price_paise"],
                     plan["included_seconds"], int(plan["active"]), now, now),
                )
            db.commit()

    async def get_config(self) -> dict[str, str]:
        async with self._lock:
            rows = self._db().execute("SELECT key,value FROM billing_config").fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def set_config(self, key: str, value: str) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO billing_config(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value, int(time.time())),
            )
            self._db().commit()

    async def upsert_plan(self, plan: dict[str, Any]) -> None:
        """Create or re-price a plan. This is how X/Y/Z change -- a row update, not a deploy."""

        now = int(time.time())
        async with self._lock:
            self._db().execute(
                """INSERT INTO plans(plan_code,name,kind,price_paise,included_seconds,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(plan_code) DO UPDATE SET
                    name=excluded.name, kind=excluded.kind, price_paise=excluded.price_paise,
                    included_seconds=excluded.included_seconds, active=excluded.active,
                    updated_at=excluded.updated_at""",
                (plan["plan_code"], plan["name"], plan["kind"], plan["price_paise"],
                 plan["included_seconds"], int(plan["active"]), now, now),
            )
            self._db().commit()

    async def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM plans WHERE plan_code=?", (plan_code,)).fetchone()
        return dict(row) if row else None

    async def list_plans(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM plans" + (" WHERE active=1" if active_only else "") + " ORDER BY price_paise"
        async with self._lock:
            rows = self._db().execute(query).fetchall()
        return [dict(row) for row in rows]

    async def create_creator(self, creator_id: str, display_name: str, payout_reference: str | None) -> None:
        async with self._lock:
            self._db().execute(
                "INSERT INTO creators(creator_id,display_name,payout_reference,created_at) VALUES(?,?,?,?)",
                (creator_id, display_name, payout_reference, int(time.time())),
            )
            self._db().commit()

    async def set_asset_creator(self, asset_id: str, creator_id: str) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO asset_creators(asset_id,creator_id) VALUES(?,?)
                ON CONFLICT(asset_id) DO UPDATE SET creator_id=excluded.creator_id""",
                (asset_id, creator_id),
            )
            self._db().commit()

    async def get_asset_creator(self, asset_id: str) -> str | None:
        async with self._lock:
            row = self._db().execute("SELECT creator_id FROM asset_creators WHERE asset_id=?", (asset_id,)).fetchone()
        return row["creator_id"] if row else None

    async def create_subscription(self, subscription: dict[str, Any]) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO subscriptions(subscription_id,user_id,plan_code,creator_id,price_paise,
                period_start,period_end,status) VALUES(?,?,?,?,?,?,?,?)""",
                (subscription["subscription_id"], subscription["user_id"], subscription["plan_code"],
                 subscription.get("creator_id"), subscription["price_paise"], subscription["period_start"],
                 subscription["period_end"], subscription["status"]),
            )
            self._db().commit()

    async def active_platform_subscription(self, user_id: str, now: int) -> dict[str, Any] | None:
        """The listener's current platform plan, highest included allowance winning."""

        async with self._lock:
            row = self._db().execute(
                """SELECT s.*, p.included_seconds, p.kind FROM subscriptions s
                JOIN plans p ON p.plan_code = s.plan_code
                WHERE s.user_id=? AND s.status='active' AND s.period_end > ? AND p.kind='platform'
                ORDER BY (p.included_seconds IS NULL) DESC, p.included_seconds DESC LIMIT 1""",
                (user_id, now),
            ).fetchone()
        return dict(row) if row else None

    async def has_creator_subscription(self, user_id: str, creator_id: str, now: int) -> bool:
        async with self._lock:
            row = self._db().execute(
                """SELECT 1 FROM subscriptions WHERE user_id=? AND creator_id=? AND status='active'
                AND period_end > ? LIMIT 1""",
                (user_id, creator_id, now),
            ).fetchone()
        return row is not None

    async def cancel_subscription(self, subscription_id: str) -> None:
        async with self._lock:
            self._db().execute("UPDATE subscriptions SET status='cancelled' WHERE subscription_id=?", (subscription_id,))
            self._db().commit()

    async def consumed_seconds(self, user_id: str, period: str) -> int:
        async with self._lock:
            row = self._db().execute(
                "SELECT consumed_seconds FROM usage_periods WHERE user_id=? AND period_key=?", (user_id, period)
            ).fetchone()
        return int(row["consumed_seconds"]) if row else 0

    async def record_grants(
        self,
        *,
        session_id: str,
        user_id: str,
        creator_id: str | None,
        period: str,
        sequences: list[int],
        seconds_each: int,
        included_seconds: int | None,
    ) -> tuple[int, int]:
        """Debit only sequences not already granted; refuse to exceed the plan allowance.

        Returns ``(newly_granted_count, consumed_seconds_after)``. The whole operation runs
        under one lock and one transaction so a concurrent request cannot interleave between
        the quota check and the debit -- otherwise two parallel manifest requests could both
        pass a check that only one of them should.
        """

        now = int(time.time())
        async with self._lock:
            db = self._db()
            existing = {
                int(row["sequence"])
                for row in db.execute(
                    f"SELECT sequence FROM segment_grants WHERE session_id=? AND sequence IN "
                    f"({','.join('?' * len(sequences))})",
                    (session_id, *sequences),
                ).fetchall()
            } if sequences else set()
            fresh = [sequence for sequence in sequences if sequence not in existing]
            row = db.execute(
                "SELECT consumed_seconds FROM usage_periods WHERE user_id=? AND period_key=?", (user_id, period)
            ).fetchone()
            consumed = int(row["consumed_seconds"]) if row else 0
            if included_seconds is not None:
                affordable = max(0, (included_seconds - consumed) // seconds_each) if seconds_each else 0
                fresh = fresh[:affordable]
            if not fresh:
                return 0, consumed
            debit = len(fresh) * seconds_each
            db.executemany(
                "INSERT OR IGNORE INTO segment_grants(session_id,sequence,seconds,granted_at) VALUES(?,?,?,?)",
                [(session_id, sequence, seconds_each, now) for sequence in fresh],
            )
            # A creator subscription grants uncapped listening to that creator's catalogue, so it
            # must not draw down the listener's platform (free/paid) monthly allowance. We still
            # record creator engagement even when uncapped, because that drives the payout pool.
            if included_seconds is not None:
                db.execute(
                    """INSERT INTO usage_periods(user_id,period_key,consumed_seconds,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(user_id,period_key) DO UPDATE SET
                        consumed_seconds = usage_periods.consumed_seconds + excluded.consumed_seconds,
                        updated_at = excluded.updated_at""",
                    (user_id, period, debit, now),
                )
            if creator_id is not None:
                db.execute(
                    """INSERT INTO creator_usage(creator_id,period_key,user_id,seconds) VALUES(?,?,?,?)
                    ON CONFLICT(creator_id,period_key,user_id) DO UPDATE SET
                        seconds = creator_usage.seconds + excluded.seconds""",
                    (creator_id, period, user_id, debit),
                )
            db.commit()
            return len(fresh), consumed + (debit if included_seconds is not None else 0)

    async def creator_period_stats(self, period: str) -> dict[str, tuple[int, int]]:
        """creator_id -> (unique_listeners, listened_seconds) for a period."""

        async with self._lock:
            rows = self._db().execute(
                """SELECT creator_id, COUNT(DISTINCT user_id) AS listeners, SUM(seconds) AS seconds
                FROM creator_usage WHERE period_key=? GROUP BY creator_id""",
                (period,),
            ).fetchall()
        return {row["creator_id"]: (int(row["listeners"]), int(row["seconds"] or 0)) for row in rows}

    async def platform_revenue_paise(self, period: str) -> int:
        """Gross revenue from platform plans whose period overlaps the given month."""

        async with self._lock:
            row = self._db().execute(
                """SELECT COALESCE(SUM(s.price_paise),0) AS gross FROM subscriptions s
                JOIN plans p ON p.plan_code=s.plan_code
                WHERE p.kind='platform' AND s.status='active'
                AND strftime('%Y-%m', s.period_start, 'unixepoch')=?""",
                (period,),
            ).fetchone()
        return int(row["gross"])

    async def creator_subscription_revenue(self, period: str) -> dict[str, int]:
        async with self._lock:
            rows = self._db().execute(
                """SELECT creator_id, COALESCE(SUM(price_paise),0) AS gross FROM subscriptions
                WHERE creator_id IS NOT NULL AND status='active'
                AND strftime('%Y-%m', period_start, 'unixepoch')=? GROUP BY creator_id""",
                (period,),
            ).fetchall()
        return {row["creator_id"]: int(row["gross"]) for row in rows}

    async def save_payout_run(
        self, period: str, gross: int, net: int, pool: int, lines: list[dict[str, Any]]
    ) -> None:
        async with self._lock:
            db = self._db()
            db.execute(
                """INSERT INTO payout_runs(period_key,gross_paise,net_paise,pool_paise,computed_at)
                VALUES(?,?,?,?,?) ON CONFLICT(period_key) DO UPDATE SET
                    gross_paise=excluded.gross_paise, net_paise=excluded.net_paise,
                    pool_paise=excluded.pool_paise, computed_at=excluded.computed_at""",
                (period, gross, net, pool, int(time.time())),
            )
            db.execute("DELETE FROM payout_lines WHERE period_key=?", (period,))
            db.executemany(
                """INSERT INTO payout_lines(period_key,creator_id,source,amount_paise,unique_listeners,listened_seconds)
                VALUES(?,?,?,?,?,?)""",
                [(period, line["creator_id"], line["source"], line["amount_paise"],
                  line.get("unique_listeners", 0), line.get("listened_seconds", 0)) for line in lines],
            )
            db.commit()

    async def get_payout_run(self, period: str) -> dict[str, Any] | None:
        async with self._lock:
            run = self._db().execute("SELECT * FROM payout_runs WHERE period_key=?", (period,)).fetchone()
            if run is None:
                return None
            lines = self._db().execute(
                "SELECT * FROM payout_lines WHERE period_key=? ORDER BY amount_paise DESC", (period,)
            ).fetchall()
        return {**dict(run), "lines": [dict(line) for line in lines]}

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        values = dict(row)
        return SessionRecord(**values)
