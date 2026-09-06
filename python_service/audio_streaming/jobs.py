"""Job + metering persistence for the Phase 1 upload/enhance pipeline.

Lives in its own SQLite file (separate from the streaming schema) so the ingestion
feature never disturbs the watermarked-streaming tables. Stores job lifecycle, the
studio-quality output object keys, the processing report, and a track-only usage
ledger (per D1: metering is recorded during the 25-user free trial but not enforced
until pricing lands).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    creator_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('queued','processing','ready','failed')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    asset_id TEXT,
    raw_path TEXT,
    mastered_key_wav TEXT,
    mastered_key_mp3 TEXT,
    report_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner_user_id, status);
CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    asset_id TEXT,
    seconds REAL NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_user ON usage_ledger(user_id, created_at);
"""


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    owner_user_id: str
    creator_id: str | None
    title: str
    status: str
    created_at: int
    updated_at: int
    asset_id: str | None
    raw_path: str | None
    mastered_key_wav: str | None
    mastered_key_mp3: str | None
    report: dict[str, Any] | None
    error: str | None


class JobsRepository:
    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()

    async def _execute(self, sql: str, params: tuple) -> None:
        async with self._lock:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            try:
                conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()

    async def _fetch_one(self, sql: str, params: tuple):
        async with self._lock:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                return conn.execute(sql, params).fetchone()
            finally:
                conn.close()

    async def create_job(
        self, job_id: str, owner_user_id: str, creator_id: str | None, title: str,
        raw_path: str, asset_id: str, now: int,
    ) -> None:
        await self._execute(
            """INSERT INTO jobs(job_id,owner_user_id,creator_id,title,status,created_at,updated_at,asset_id,raw_path)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (job_id, owner_user_id, creator_id, title, "queued", now, now, asset_id, raw_path),
        )

    async def update_status(
        self, job_id: str, status: str, *, mastered_key_wav: str | None = None,
        mastered_key_mp3: str | None = None, report: dict | None = None, error: str | None = None,
    ) -> None:
        now = int(time.time())
        await self._execute(
            """UPDATE jobs SET status=?, updated_at=?, mastered_key_wav=?, mastered_key_mp3=?,
                  report_json=?, error=? WHERE job_id=?""",
            (status, now, mastered_key_wav, mastered_key_mp3,
             json.dumps(report, sort_keys=True) if report is not None else None, error, job_id),
        )

    async def get_job(self, job_id: str) -> JobRecord | None:
        row = await self._fetch_one("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        return self._record_from_row(row) if row else None

    async def get_job_by_asset(self, asset_id: str) -> JobRecord | None:
        row = await self._fetch_one(
            "SELECT * FROM jobs WHERE asset_id=? ORDER BY created_at DESC LIMIT 1", (asset_id,),
        )
        return self._record_from_row(row) if row else None

    async def get_ready_jobs(self) -> list[JobRecord]:
        async with self._lock:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute("SELECT * FROM jobs WHERE status='ready'").fetchall()
                return [self._record_from_row(r) for r in rows]
            finally:
                conn.close()

    async def record_usage(self, user_id: str, asset_id: str, seconds: float) -> None:
        await self._execute(
            "INSERT INTO usage_ledger(user_id,asset_id,seconds,created_at) VALUES(?,?,?,?)",
            (user_id, asset_id, float(seconds), int(time.time())),
        )

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> JobRecord:
        report = json.loads(row["report_json"]) if row["report_json"] else None
        return JobRecord(
            job_id=row["job_id"], owner_user_id=row["owner_user_id"], creator_id=row["creator_id"],
            title=row["title"], status=row["status"], created_at=row["created_at"],
            updated_at=row["updated_at"], asset_id=row["asset_id"], raw_path=row["raw_path"],
            mastered_key_wav=row["mastered_key_wav"], mastered_key_mp3=row["mastered_key_mp3"],
            report=report, error=row["error"],
        )
