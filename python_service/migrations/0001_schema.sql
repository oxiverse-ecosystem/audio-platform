-- Postgres schema for the audio streaming service (P1 multi-replica backend).
-- Apply with:  psql "$AUDIO_DATABASE_URL" -f migrations/0001_schema.sql
-- This is the SQLite DDL translated to Postgres: SERIAL/BIGSERIAL keys, TIMESTAMPTZ where
-- useful, ON CONFLICT upserts, and to_char(to_timestamp(...),'YYYY-MM') for period math
-- (replaces SQLite strftime). Foreign keys are kept to protect referential integrity.

CREATE TABLE IF NOT EXISTS assets (
    asset_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    sample_rate INTEGER NOT NULL,
    channels INTEGER NOT NULL,
    segment_samples INTEGER NOT NULL,
    segment_count INTEGER NOT NULL,
    duration_samples BIGINT NOT NULL,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS entitlements (
    asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (asset_id, user_id)
);

CREATE TABLE IF NOT EXISTS stream_sessions (
    session_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES assets(asset_id),
    user_id TEXT NOT NULL,
    watermark_id BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','revoked','expired'))
);
CREATE INDEX IF NOT EXISTS stream_sessions_user_active ON stream_sessions(user_id, status, expires_at);

CREATE TABLE IF NOT EXISTS watermark_mappings (
    asset_id TEXT NOT NULL,
    watermark_id BIGINT NOT NULL,
    session_id TEXT NOT NULL UNIQUE REFERENCES stream_sessions(session_id),
    user_audit_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY(asset_id, watermark_id)
);

CREATE TABLE IF NOT EXISTS encryption_key_metadata (
    session_id TEXT PRIMARY KEY REFERENCES stream_sessions(session_id) ON DELETE CASCADE,
    key_purpose TEXT NOT NULL,
    derivation_version TEXT NOT NULL,
    key_reference TEXT NOT NULL UNIQUE,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    rotation_status TEXT NOT NULL CHECK (rotation_status IN ('active','retired'))
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    session_id TEXT,
    asset_id TEXT,
    user_audit_hash TEXT,
    outcome TEXT NOT NULL,
    latency_ms DOUBLE PRECISION,
    details_json TEXT NOT NULL,
    created_at BIGINT NOT NULL
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
    duration_samples BIGINT NOT NULL,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS variant_sessions (
    session_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES variant_assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    watermark_id BIGINT NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','revoked','expired'))
);
CREATE INDEX IF NOT EXISTS variant_sessions_user_active ON variant_sessions(user_id, status, expires_at);

CREATE TABLE IF NOT EXISTS variant_entitlements (
    asset_id TEXT NOT NULL REFERENCES variant_assets(asset_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (asset_id, user_id)
);

CREATE TABLE IF NOT EXISTS variant_watermark_mappings (
    asset_id TEXT NOT NULL,
    watermark_id BIGINT NOT NULL,
    session_id TEXT NOT NULL UNIQUE REFERENCES variant_sessions(session_id) ON DELETE CASCADE,
    user_audit_hash TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    PRIMARY KEY(asset_id, watermark_id)
);

-- P2: plans, subscriptions, metering, payouts
CREATE TABLE IF NOT EXISTS billing_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    plan_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('platform','creator')),
    price_paise INTEGER NOT NULL CHECK (price_paise >= 0),
    included_seconds INTEGER CHECK (included_seconds IS NULL OR included_seconds >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS creators (
    creator_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    plan_code TEXT REFERENCES plans(plan_code),
    payout_reference TEXT,
    created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    plan_code TEXT NOT NULL,
    creator_id TEXT REFERENCES creators(creator_id),
    price_paise INTEGER NOT NULL CHECK (price_paise >= 0),
    period_start BIGINT NOT NULL,
    period_end BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active','cancelled','expired'))
);
CREATE INDEX IF NOT EXISTS subscriptions_user_active ON subscriptions(user_id, status, period_end);
CREATE INDEX IF NOT EXISTS subscriptions_creator ON subscriptions(creator_id, status);

CREATE TABLE IF NOT EXISTS asset_creators (
    asset_id TEXT PRIMARY KEY,
    creator_id TEXT NOT NULL REFERENCES creators(creator_id) ON DELETE CASCADE
);

-- Idempotent grant ledger: one row per (session, sequence). The FOR UPDATE lock on the
-- listener's usage_periods row (see PostgresRepository.record_grants) makes the quota check
-- and debit atomic across replicas.
CREATE TABLE IF NOT EXISTS segment_grants (
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    seconds INTEGER NOT NULL,
    granted_at BIGINT NOT NULL,
    PRIMARY KEY (session_id, sequence)
);

CREATE TABLE IF NOT EXISTS usage_periods (
    user_id TEXT NOT NULL,
    period_key TEXT NOT NULL,
    consumed_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (user_id, period_key)
);

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
    computed_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS payout_lines (
    period_key TEXT NOT NULL REFERENCES payout_runs(period_key) ON DELETE CASCADE,
    creator_id TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('pool','creator_subscription')),
    amount_paise INTEGER NOT NULL,
    unique_listeners INTEGER NOT NULL DEFAULT 0,
    listened_seconds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (period_key, creator_id, source)
);
