-- Local identity/access boundary v2. No official identity verification.
CREATE TABLE auth_principals (
 id TEXT PRIMARY KEY, alias TEXT UNIQUE NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','operator','reviewer','service')),
 password_hash TEXT, active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE auth_credentials (
 id TEXT PRIMARY KEY, principal_id TEXT NOT NULL REFERENCES auth_principals(id), token_hash TEXT UNIQUE NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('session','service')), scopes TEXT NOT NULL, family_id TEXT NOT NULL,
 created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, absolute_expires_at BIGINT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)), CHECK(expires_at<=absolute_expires_at));
CREATE TABLE auth_grants (
 principal_id TEXT NOT NULL REFERENCES auth_principals(id), merchant_id TEXT NOT NULL REFERENCES pilot_merchants(id),
 active INTEGER NOT NULL CHECK(active IN (0,1)), PRIMARY KEY(principal_id,merchant_id));
CREATE TABLE auth_onboarding (
 stall_id TEXT PRIMARY KEY, merchant_id TEXT UNIQUE NOT NULL REFERENCES pilot_merchants(id),
 operator_id TEXT NOT NULL REFERENCES pilot_operators(id), stall_entity_id TEXT UNIQUE NOT NULL REFERENCES pilot_stalls(id),
 owner_id TEXT NOT NULL REFERENCES auth_principals(id), centre_ref TEXT NOT NULL, latitude DOUBLE PRECISION NOT NULL,
 longitude DOUBLE PRECISION NOT NULL, gauge TEXT NOT NULL, psi_region TEXT NOT NULL,
 external_namespace TEXT NOT NULL CHECK(external_namespace IN ('manual_local','wallet_sandbox')),
 external_ref_hash TEXT NOT NULL, licence_ref_hash TEXT UNIQUE NOT NULL, evidence_sha256 TEXT NOT NULL,
 accepted_version TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending_review','eligible_simulation','rejected','revoked')),
 created_at BIGINT NOT NULL, UNIQUE(external_namespace,external_ref_hash));
CREATE TABLE auth_consent_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id TEXT NOT NULL REFERENCES pilot_merchants(id), principal_id TEXT NOT NULL REFERENCES auth_principals(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('income_baseline','weather_impact_research','transaction_retention')),
 action TEXT NOT NULL CHECK(action IN ('grant','revoke')), scope TEXT NOT NULL CHECK(scope IN ('transactions:read','transactions:retain')),
 expires_at BIGINT NOT NULL, retention_days INTEGER NOT NULL CHECK(retention_days BETWEEN 0 AND 90), recorded_at BIGINT NOT NULL);
CREATE INDEX auth_consent_latest ON auth_consent_events(merchant_id,purpose,sequence);
CREATE TABLE auth_login_limits (key_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start BIGINT NOT NULL);
CREATE TRIGGER auth_consent_no_update BEFORE UPDATE ON auth_consent_events BEGIN SELECT RAISE(ABORT,'append-only consent history'); END;
CREATE TRIGGER auth_consent_no_delete BEFORE DELETE ON auth_consent_events BEGIN SELECT RAISE(ABORT,'append-only consent history'); END;
