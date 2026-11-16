-- DayCover+ 3.0 Production PostgreSQL & PostGIS Schema
-- Ground Truth V1.0 Specification (11 Nov 2026)
-- MAS FEAT Compliant Parametric Climate Microinsurance

-- Enable PostGIS and UUID extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. STALLS & HAWKER CENTRES (Spatial with PostGIS)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stalls (
    id VARCHAR(32) PRIMARY KEY,
    centre_name VARCHAR(255) NOT NULL,
    stall_number VARCHAR(32),
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Point, 4326),
    assigned_gauge_id VARCHAR(32) NOT NULL,
    psi_region VARCHAR(32) NOT NULL,
    plan VARCHAR(32) NOT NULL DEFAULT 'haze+rain',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stalls_geom ON stalls USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_stalls_gauge ON stalls (assigned_gauge_id);
CREATE INDEX IF NOT EXISTS idx_stalls_region ON stalls (psi_region);

-- -----------------------------------------------------------------------------
-- 2. POLICIES (Enforcing Annual Caps & Flat Subscriptions)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS policies (
    id VARCHAR(64) PRIMARY KEY,
    stall_id VARCHAR(32) NOT NULL REFERENCES stalls(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, EXPIRED, SUSPENDED
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    weekly_premium_sgd NUMERIC(6, 2) NOT NULL DEFAULT 2.00,
    annual_rain_events_paid INT NOT NULL DEFAULT 0,
    annual_haze_days_paid INT NOT NULL DEFAULT 0,
    annual_haze_paid_sgd NUMERIC(8, 2) NOT NULL DEFAULT 0.00,
    max_rain_events INT NOT NULL DEFAULT 1,
    max_haze_days INT NOT NULL DEFAULT 5,
    max_haze_amount_sgd NUMERIC(8, 2) NOT NULL DEFAULT 150.00,
    funding_mode VARCHAR(32) NOT NULL DEFAULT 'SUBSCRIPTION', -- SUBSCRIPTION, SPONSORED_ESG
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policies_stall ON policies (stall_id);
CREATE INDEX IF NOT EXISTS idx_policies_status ON policies (status);

-- -----------------------------------------------------------------------------
-- 3. READINGS (Append-Only Immutable Sovereign Telemetry Feed)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings (
    id BIGSERIAL PRIMARY KEY,
    station_id VARCHAR(32) NOT NULL,
    metric VARCHAR(32) NOT NULL, -- rainfall_daily_mm, psi_24hr, wbgt_c, rainfall_hourly_mm
    observed_at TIMESTAMPTZ NOT NULL,
    value NUMERIC(10, 3) NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    source VARCHAR(64) NOT NULL DEFAULT 'NEA_SINGAPORE',
    payload_hash VARCHAR(64) NOT NULL, -- Cryptographic SHA-256 hash for tamper proofing
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_station_metric_time UNIQUE (station_id, metric, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_readings_lookup ON readings (station_id, metric, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_readings_metric ON readings (metric, observed_at DESC);

-- -----------------------------------------------------------------------------
-- 4. CENTRE CLOSURES (Scheduled NEA Spring Cleaning Washdowns)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS centre_closures (
    id BIGSERIAL PRIMARY KEY,
    centre_name VARCHAR(255) NOT NULL,
    closure_date DATE NOT NULL,
    closure_type VARCHAR(32) NOT NULL, -- q1, q2, q3, q4, r_and_r, maintenance
    description TEXT,
    CONSTRAINT uq_centre_closure UNIQUE (centre_name, closure_date)
);

CREATE INDEX IF NOT EXISTS idx_closures_lookup ON centre_closures (centre_name, closure_date);

-- -----------------------------------------------------------------------------
-- 5. TRIGGER EVENTS (Deterministic Engine Decision Ledger)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trigger_events (
    id VARCHAR(64) PRIMARY KEY,
    event_date DATE NOT NULL,
    stall_id VARCHAR(32) NOT NULL REFERENCES stalls(id),
    peril VARCHAR(32) NOT NULL, -- rain, haze, rain_80_cmp, rain_short_storm, heat
    status VARCHAR(32) NOT NULL, -- paid, capped, excluded, shadow, pending
    amount NUMERIC(8, 2) NOT NULL DEFAULT 0.00,
    reason TEXT NOT NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    rule_version VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trigger_events_stall_date ON trigger_events (stall_id, event_date);
CREATE INDEX IF NOT EXISTS idx_trigger_events_status ON trigger_events (status);

-- -----------------------------------------------------------------------------
-- 6. PAYOUTS (Instant PayNow FAST Settlement & RFC 4122 Receipts)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payouts (
    id VARCHAR(64) PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL REFERENCES trigger_events(id),
    stall_id VARCHAR(32) NOT NULL REFERENCES stalls(id),
    amount NUMERIC(8, 2) NOT NULL,
    payment_rail VARCHAR(32) NOT NULL DEFAULT 'PAYNOW_FAST',
    idempotency_key VARCHAR(64) NOT NULL UNIQUE,
    reference_number VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'SETTLED', -- SETTLED, PENDING, FAILED
    disbursed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payouts_stall ON payouts (stall_id);
CREATE INDEX IF NOT EXISTS idx_payouts_reference ON payouts (reference_number);

-- -----------------------------------------------------------------------------
-- 7. AUDIT LOG (Immutable Event Sourcing for MAS FEAT Compliance)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_time ON audit_log (timestamp DESC);
