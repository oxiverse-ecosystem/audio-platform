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


    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        values = dict(row)
        return SessionRecord(**values)
