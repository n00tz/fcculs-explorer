-- FCC ULS Explorer — application-level tables (not FCC-sourced data)
-- These are net-new tables for change tracking, identity grouping,
-- and the alerting/notification feature set. FCC-sourced record tables
-- (amateur licenses, towers, etc.) are defined in a separate migration
-- once field layouts are verified (see docs/fcc-data-reference.md).

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Generic change log driving the alerting feature. One row per changed
-- field per ingestion run.
CREATE TABLE IF NOT EXISTS change_events (
    id              BIGSERIAL PRIMARY KEY,
    subject_type    TEXT NOT NULL,       -- 'amateur_license' | 'tower'
    subject_key     TEXT NOT NULL,       -- callsign or ASR registration number
    uls_system_id   TEXT,                -- unique_system_identifier, when applicable
    field_name      TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    source_file     TEXT NOT NULL,       -- e.g. l_am_mon.zip, r_tower_wed.zip
    effective_date  DATE NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_change_events_subject ON change_events (subject_type, subject_key, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_change_events_uls_id ON change_events (uls_system_id);

-- Passwordless auth
CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS magic_link_tokens (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Notification delivery targets
CREATE TABLE IF NOT EXISTS notification_channels (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_type TEXT NOT NULL,          -- 'smtp' | 'email_to_sms' | 'webhook' | 'ntfy' | 'discord' | 'telegram' | 'matrix'
    label       TEXT,
    config      JSONB NOT NULL,          -- e.g. {"email": "..."} or {"url": "..."}
    is_verified BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- User watches on a callsign or ULS ID
CREATE TABLE IF NOT EXISTS watches (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_type    TEXT NOT NULL,       -- 'callsign' | 'uls_id' | 'asr_registration_number'
    subject_value   TEXT NOT NULL,
    channel_id      BIGINT NOT NULL REFERENCES notification_channels(id) ON DELETE CASCADE,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, subject_type, subject_value, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_watches_subject ON watches (subject_type, subject_value) WHERE is_active;

-- Outbound notification queue/audit trail (RQ jobs reference this row)
CREATE TABLE IF NOT EXISTS notification_deliveries (
    id              BIGSERIAL PRIMARY KEY,
    watch_id        BIGINT NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    change_event_id BIGINT NOT NULL REFERENCES change_events(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | sent | failed
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);
