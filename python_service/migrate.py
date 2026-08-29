"""Idempotent Postgres migration runner for the audio service.

Run once at container start (or locally) against ``AUDIO_DATABASE_URL``. The schema file
(``migrations/0001_schema.sql``) uses ``IF NOT EXISTS`` / ``ON CONFLICT DO NOTHING`` so re-runs
are safe. Uses asyncpg (an app dependency), not psycopg, to avoid an extra runtime package.
"""

import os
import sys

import asyncpg

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "migrations", "0001_schema.sql")


async def main() -> None:
    dsn = os.environ.get("AUDIO_DATABASE_URL")
    if not dsn:
        print("AUDIO_DATABASE_URL not set; skipping migration.", file=sys.stderr)
        return

    # asyncpg wants an async-aware dsn; the postgresql:// form works as-is.
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        sql = fh.read()

    conn = await asyncpg.connect(dsn)
    try:
        # Run the whole schema in one transaction. Idempotent DDL tolerates re-runs.
        await conn.execute(sql)
        print("schema applied (idempotent)")
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
