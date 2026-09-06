"""Small SQLite repository; production can replace it with a managed relational database."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .models import AssetRecord, SessionRecord
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
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    is_creator INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS email_verifications (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE INDEX IF NOT EXISTS email_verifications_user ON email_verifications(user_id, used_at);
CREATE TABLE IF NOT EXISTS password_resets (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE INDEX IF NOT EXISTS password_resets_user ON password_resets(user_id, used_at);
CREATE TABLE IF NOT EXISTS episodes (
    episode_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL UNIQUE,
    creator_id TEXT NOT NULL REFERENCES users(user_id),
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL DEFAULT 'Founder Stories',
    visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','pack','private')),
    status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','processing','ready','published')),
    publish_on_ready INTEGER NOT NULL DEFAULT 0,
    waveform_peaks TEXT,
    duration_seconds REAL NOT NULL DEFAULT 0,
    play_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS episodes_created ON episodes(created_at DESC);
CREATE INDEX IF NOT EXISTS episodes_category ON episodes(category, created_at DESC);
CREATE INDEX IF NOT EXISTS episodes_creator ON episodes(creator_id, created_at DESC);
CREATE TABLE IF NOT EXISTS episode_plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(episode_id) ON DELETE CASCADE,
    creator_id TEXT NOT NULL REFERENCES users(user_id),
    played_at INTEGER NOT NULL,
    duration_listened_seconds REAL NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS episode_plays_creator_date ON episode_plays(creator_id, played_at);
CREATE INDEX IF NOT EXISTS episode_plays_episode ON episode_plays(episode_id, played_at);
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

            # Automatic schema migration for existing sqlite db files
            cols = {row["name"] for row in self._connection.execute("PRAGMA table_info(episodes)").fetchall()}
            if "status" not in cols:
                self._connection.execute("ALTER TABLE episodes ADD COLUMN status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','processing','ready','published'))")
            if "publish_on_ready" not in cols:
                self._connection.execute("ALTER TABLE episodes ADD COLUMN publish_on_ready INTEGER NOT NULL DEFAULT 0")
            if "waveform_peaks" not in cols:
                self._connection.execute("ALTER TABLE episodes ADD COLUMN waveform_peaks TEXT")

            # Create index after columns are ensured
            self._connection.execute("CREATE INDEX IF NOT EXISTS episodes_status ON episodes(status, created_at DESC)")
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

    # --- auth (dev): users + email verification ---
    async def create_user(
        self, user_id: str, email: str, display_name: str, password_hash: str, is_creator: bool, now: int
    ) -> None:
        async with self._lock:
            self._db().execute(
                """INSERT INTO users(user_id,email,display_name,password_hash,email_verified,is_creator,created_at)
                VALUES(?,?,?,?,0,?,?)""",
                (user_id, email, display_name, password_hash, int(bool(is_creator)), now),
            )
            self._db().commit()

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    async def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    async def set_email_verified(self, user_id: str, now: int) -> None:
        async with self._lock:
            self._db().execute("UPDATE users SET email_verified=1 WHERE user_id=?", (user_id,))
            self._db().commit()

    async def create_verification(self, token: str, user_id: str, created_at: int, expires_at: int) -> None:
        async with self._lock:
            self._db().execute(
                "INSERT INTO email_verifications(token,user_id,created_at,expires_at,used_at) VALUES(?,?,?,?,NULL)",
                (token, user_id, created_at, expires_at),
            )
            self._db().commit()

    async def get_verification(self, token: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM email_verifications WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

    async def mark_verification_used(self, token: str, now: int) -> None:
        async with self._lock:
            self._db().execute("UPDATE email_verifications SET used_at=? WHERE token=?", (now, token))
            self._db().commit()

    # --- episodes (discovery, drafts & async) ---
    @staticmethod
    def _episode_from_row(row: sqlite3.Row | dict) -> dict[str, Any]:
        d = dict(row)
        if "waveform_peaks" in d and isinstance(d["waveform_peaks"], str):
            try:
                d["waveform_peaks"] = json.loads(d["waveform_peaks"])
            except Exception:
                d["waveform_peaks"] = None
        elif "waveform_peaks" not in d:
            d["waveform_peaks"] = None
        if "status" not in d:
            d["status"] = "published"
        if "publish_on_ready" not in d:
            d["publish_on_ready"] = 0
        return d

    async def create_episode(
        self, episode_id: str, asset_id: str, creator_id: str, title: str,
        description: str | None, category: str, visibility: str, duration_seconds: float, now: int,
        status: str = "published", publish_on_ready: int = 0, waveform_peaks: list[float] | None = None,
    ) -> None:
        peaks_json = json.dumps(waveform_peaks) if waveform_peaks is not None else None
        async with self._lock:
            self._db().execute(
                """INSERT INTO episodes(episode_id,asset_id,creator_id,title,description,category,visibility,duration_seconds,play_count,created_at,status,publish_on_ready,waveform_peaks)
                   VALUES(?,?,?,?,?,?,?,?,0,?,?,?,?)""",
                (episode_id, asset_id, creator_id, title, description, category, visibility, duration_seconds, now, status, publish_on_ready, peaks_json),
            )
            self._db().commit()

    async def update_episode_status(
        self, episode_id: str, status: str, *,
        duration_seconds: float | None = None, waveform_peaks: list[float] | None = None,
    ) -> None:
        sql = "UPDATE episodes SET status=?"
        params: list[Any] = [status]
        if duration_seconds is not None:
            sql += ", duration_seconds=?"
            params.append(duration_seconds)
        if waveform_peaks is not None:
            sql += ", waveform_peaks=?"
            params.append(json.dumps(waveform_peaks))
        sql += " WHERE episode_id=?"
        params.append(episode_id)
        async with self._lock:
            self._db().execute(sql, tuple(params))
            self._db().commit()

    async def update_episode_publish_on_ready(self, episode_id: str, publish_on_ready: int) -> None:
        async with self._lock:
            self._db().execute("UPDATE episodes SET publish_on_ready=? WHERE episode_id=?", (publish_on_ready, episode_id))
            self._db().commit()

    async def get_episodes(self, *, category: str | None = None, creator_id: str | None = None,
                           search: str | None = None, visibility: str = "public",
                           status: str | None = "published",
                           limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT * FROM episodes WHERE visibility=?"
        params: list = [visibility]
        if status:
            sql += " AND status=?"
            params.append(status)
        if category:
            sql += " AND category=?"
            params.append(category)
        if creator_id:
            sql += " AND creator_id=?"
            params.append(creator_id)
        if search:
            sql += " AND (title LIKE ? OR description LIKE ?)"
            params.extend((f"%{search}%", f"%{search}%"))
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        async with self._lock:
            rows = self._db().execute(sql, tuple(params)).fetchall()
        return [self._episode_from_row(r) for r in rows]

    async def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
        return self._episode_from_row(row) if row else None

    async def get_episode_by_asset(self, asset_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute(
                "SELECT * FROM episodes WHERE asset_id=? ORDER BY created_at DESC LIMIT 1", (asset_id,)
            ).fetchone()
        return self._episode_from_row(row) if row else None

    async def increment_play_count(self, episode_id: str) -> None:
        async with self._lock:
            self._db().execute("UPDATE episodes SET play_count=play_count+1 WHERE episode_id=?", (episode_id,))
            self._db().commit()

    async def record_play(
        self, episode_id: str, creator_id: str, played_at: int,
        duration_listened_seconds: float = 0, completed: bool = False,
    ) -> None:
        async with self._lock:
            db = self._db()
            db.execute(
                """INSERT INTO episode_plays(episode_id,creator_id,played_at,duration_listened_seconds,completed)
                   VALUES(?,?,?,?,?)""",
                (episode_id, creator_id, played_at, duration_listened_seconds, int(bool(completed))),
            )
            db.execute("UPDATE episodes SET play_count=play_count+1 WHERE episode_id=?", (episode_id,))
            db.commit()

    async def get_categories(self, visibility: str = "public") -> list[str]:
        async with self._lock:
            rows = self._db().execute(
                "SELECT DISTINCT category FROM episodes WHERE visibility=? AND status='published' ORDER BY category", (visibility,)
            ).fetchall()
        return [r["category"] for r in rows]

    # --- analytics (creator dashboard) ---
    async def get_creator_stats(self, creator_id: str) -> dict[str, Any]:
        async with self._lock:
            db = self._db()
            episodes = db.execute("SELECT episode_id, play_count FROM episodes WHERE creator_id=? AND status='published'", (creator_id,)).fetchall()
            total_episodes = len(episodes)
            total_plays = sum(r["play_count"] for r in episodes)
            total_seconds = db.execute(
                "SELECT COALESCE(SUM(duration_seconds), 0) AS s FROM episodes WHERE creator_id=?", (creator_id,)
            ).fetchone()["s"]
            return {
                "total_episodes": total_episodes,
                "total_plays": total_plays,
                "total_duration_seconds": total_seconds,
                "total_earnings": 0.0,
                "pack_subscribers": 0,
            }

    async def get_creator_episodes(self, creator_id: str, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT * FROM episodes WHERE creator_id=?"
        params: list = [creator_id]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        async with self._lock:
            rows = self._db().execute(sql, tuple(params)).fetchall()
        return [self._episode_from_row(r) for r in rows]

    async def get_creator_drafts(self, creator_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        async with self._lock:
            rows = self._db().execute(
                "SELECT * FROM episodes WHERE creator_id=? AND status != 'published' ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (creator_id, limit, offset),
            ).fetchall()
        return [self._episode_from_row(r) for r in rows]

    async def get_creator_timeseries(self, creator_id: str, days: int = 30) -> dict[str, Any]:
        """Aggregate daily plays and listener retention over the specified time window."""
        now = int(time.time())
        day_seconds = 86400
        start_of_today = (now // day_seconds) * day_seconds
        start_ts = start_of_today - (days - 1) * day_seconds

        async with self._lock:
            db = self._db()
            rows = db.execute(
                """SELECT played_at, duration_listened_seconds, completed
                   FROM episode_plays
                   WHERE creator_id=? AND played_at >= ?
                   ORDER BY played_at ASC""",
                (creator_id, start_ts),
            ).fetchall()

        daily_counts: dict[int, dict[str, Any]] = {}
        for d in range(days):
            day_ts = start_ts + d * day_seconds
            date_str = time.strftime("%Y-%m-%d", time.gmtime(day_ts))
            daily_counts[day_ts] = {
                "date": date_str,
                "timestamp": day_ts,
                "plays": 0,
                "completed_plays": 0,
                "total_duration": 0.0,
            }

        total_plays = 0
        total_completed = 0
        total_duration_all = 0.0

        for r in rows:
            p_ts = r["played_at"]
            day_bucket = (p_ts // day_seconds) * day_seconds
            if day_bucket in daily_counts:
                daily_counts[day_bucket]["plays"] += 1
                if r["completed"]:
                    daily_counts[day_bucket]["completed_plays"] += 1
                daily_counts[day_bucket]["total_duration"] += r["duration_listened_seconds"]
            total_plays += 1
            if r["completed"]:
                total_completed += 1
            total_duration_all += r["duration_listened_seconds"]

        points = []
        for day_ts in sorted(daily_counts.keys()):
            item = daily_counts[day_ts]
            p = item["plays"]
            comp = item["completed_plays"]
            points.append({
                "date": item["date"],
                "timestamp": item["timestamp"],
                "plays": p,
                "completed_plays": comp,
                "completion_rate": round((comp / p) * 100, 1) if p > 0 else 0.0,
                "avg_duration_seconds": round(item["total_duration"] / p, 1) if p > 0 else 0.0,
            })

        overall_retention = round((total_completed / total_plays) * 100, 1) if total_plays > 0 else 0.0
        avg_listen = round(total_duration_all / total_plays, 1) if total_plays > 0 else 0.0

        return {
            "days": days,
            "total_plays": total_plays,
            "overall_retention_rate": overall_retention,
            "avg_listen_seconds": avg_listen,
            "points": points,
        }

    # --- password resets ---
    async def create_password_reset(self, token: str, user_id: str, created_at: int, expires_at: int) -> None:
        async with self._lock:
            self._db().execute(
                "INSERT INTO password_resets(token,user_id,created_at,expires_at,used_at) VALUES(?,?,?,?,NULL)",
                (token, user_id, created_at, expires_at),
            )
            self._db().commit()

    async def get_password_reset(self, token: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._db().execute("SELECT * FROM password_resets WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

    async def mark_password_reset_used(self, token: str, now: int) -> None:
        async with self._lock:
            self._db().execute("UPDATE password_resets SET used_at=? WHERE token=?", (now, token))
            self._db().commit()

    async def update_password(self, user_id: str, password_hash: str) -> None:
        async with self._lock:
            self._db().execute("UPDATE users SET password_hash=? WHERE user_id=?", (password_hash, user_id))
            self._db().commit()

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> AssetRecord:
        return AssetRecord(**dict(row))

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SessionRecord:
        values = dict(row)
        return SessionRecord(**values)
