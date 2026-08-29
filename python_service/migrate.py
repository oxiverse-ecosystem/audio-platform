"""Idempotent Postgres migration runner for the audio service.

Run once at container start (or locally) against ``AUDIO_DATABASE_URL``. The schema file
(``migrations/0001_schema.sql``) uses ``IF NOT EXISTS`` throughout, so re-running is a no-op
and safe to call on every boot before the API starts.

Usage:  AUDIO_DATABASE_URL=postgresql://... python python_service/migrate.py
"""

from __future__ import annotations

import os
import pathlib

import asyncpg


async def main() -> None:
    dsn = os.environ.get("AUDIO_DATABASE_URL")
    if not dsn:
        raise SystemExit("AUDIO_DATABASE_URL is not set; nothing to migrate (SQLite needs no migration).")
    here = pathlib.Path(__file__).resolve().parent
    sql = (here / "migrations" / "0001_schema.sql").read_text(encoding="utf-8")
    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            # Execute the whole schema as one script; all statements are IF NOT EXISTS.
            await conn.execute(sql)
        print("migrations applied")
    finally:
        await pool.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
