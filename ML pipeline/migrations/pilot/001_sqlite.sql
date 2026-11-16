-- Canonical simulation ledger v1. No real insurance issuance or payment rail.
CREATE TABLE IF NOT EXISTS pilot_schema_migrations (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL);
CREATE TABLE pilot_merchants (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, external_ref TEXT NOT NULL, identity_status TEXT NOT NULL CHECK(identity_status='unverified_simulation'), UNIQUE(namespace,external_ref));
CREATE TABLE pilot_operators (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, external_ref TEXT NOT NULL, identity_status TEXT NOT NULL CHECK(identity_status='unverified_simulation'), UNIQUE(namespace,external_ref));
CREATE TABLE pilot_operator_merchants (operator_id TEXT REFERENCES pilot_operators(id), merchant_id TEXT REFERENCES pilot_merchants(id), PRIMARY KEY(operator_id,merchant_id));
CREATE TABLE pilot_centres (id TEXT PRIMARY KEY, namespace TEXT NOT NULL, external_ref TEXT NOT NULL, UNIQUE(namespace,external_ref));
CREATE TABLE pilot_stalls (id TEXT PRIMARY KEY, centre_id TEXT NOT NULL REFERENCES pilot_centres(id), namespace TEXT NOT NULL, external_ref TEXT NOT NULL, UNIQUE(namespace,external_ref));
CREATE TABLE pilot_product_versions (id TEXT PRIMARY KEY, contract TEXT NOT NULL, contract_sha256 TEXT NOT NULL, lifecycle TEXT NOT NULL CHECK(lifecycle='simulation'));
CREATE TABLE pilot_policies (
 id TEXT PRIMARY KEY, stall_id TEXT UNIQUE NOT NULL,
 merchant_id TEXT NOT NULL REFERENCES pilot_merchants(id), operator_id TEXT NOT NULL REFERENCES pilot_operators(id),
 stall_entity_id TEXT NOT NULL REFERENCES pilot_stalls(id), version_id TEXT NOT NULL REFERENCES pilot_product_versions(id),
 start TEXT NOT NULL, "end" TEXT NOT NULL, contract TEXT NOT NULL, contract_sha256 TEXT NOT NULL,
 accepted_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status='enrolled_simulation'), CHECK("end">=start), FOREIGN KEY(operator_id,merchant_id) REFERENCES pilot_operator_merchants(operator_id,merchant_id));
CREATE TABLE pilot_periods (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), version_id TEXT NOT NULL REFERENCES pilot_product_versions(id),
 start TEXT NOT NULL, "end" TEXT NOT NULL, currency TEXT NOT NULL CHECK(currency='SGD'),
 combined_cap_cents INTEGER NOT NULL CHECK(combined_cap_cents>=0), UNIQUE(policy_id,start), UNIQUE(id,policy_id), CHECK("end">=start));
CREATE TABLE pilot_evidence (
 id TEXT PRIMARY KEY, event_date TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
CREATE TABLE pilot_decisions (
 policy_id TEXT NOT NULL REFERENCES pilot_policies(id), day TEXT NOT NULL,
 peril TEXT NOT NULL CHECK(peril IN ('rain','haze')), response TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>=0), amount NUMERIC GENERATED ALWAYS AS (amount_cents / 100.0) STORED, currency TEXT NOT NULL CHECK(currency='SGD'),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), decision_id TEXT UNIQUE NOT NULL,
 FOREIGN KEY(period_id,policy_id) REFERENCES pilot_periods(id,policy_id), PRIMARY KEY(policy_id,day,peril));
CREATE TABLE pilot_decision_revisions (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 decision_id TEXT NOT NULL REFERENCES pilot_decisions(decision_id), evidence_id TEXT NOT NULL REFERENCES pilot_evidence(id),
 response TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE pilot_instructions (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 decision_id TEXT UNIQUE NOT NULL REFERENCES pilot_decisions(decision_id), amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
 currency TEXT NOT NULL CHECK(currency='SGD'), mode TEXT NOT NULL CHECK(mode='simulation_only'),
 status TEXT NOT NULL CHECK(status='simulated_confirmed'), idempotency_key TEXT UNIQUE NOT NULL, FOREIGN KEY(period_id,policy_id) REFERENCES pilot_periods(id,policy_id));
CREATE TABLE pilot_settlement_attempts (
 id TEXT PRIMARY KEY, instruction_id TEXT NOT NULL REFERENCES pilot_instructions(id),
 status TEXT NOT NULL CHECK(status='simulated_confirmed'), provider TEXT NOT NULL CHECK(provider='simulation'),
 reference TEXT UNIQUE NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE pilot_financial_entries (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 decision_id TEXT NOT NULL REFERENCES pilot_decisions(decision_id),
 peril TEXT NOT NULL CHECK(peril IN ('rain','haze')),
 kind TEXT NOT NULL CHECK(kind IN ('allocation','simulated_settlement','compensation')),
 amount_cents INTEGER NOT NULL, currency TEXT NOT NULL CHECK(currency='SGD'),
 reverses_entry_id TEXT UNIQUE REFERENCES pilot_financial_entries(id), idempotency_key TEXT UNIQUE NOT NULL,
 reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
 FOREIGN KEY(period_id,policy_id) REFERENCES pilot_periods(id,policy_id),
 CHECK((kind='allocation' AND amount_cents>0 AND reverses_entry_id IS NULL) OR
       (kind='simulated_settlement' AND amount_cents<0 AND reverses_entry_id IS NULL) OR
       (kind='compensation' AND amount_cents>0 AND reverses_entry_id IS NOT NULL)));
CREATE UNIQUE INDEX pilot_one_posting_kind ON pilot_financial_entries(decision_id,kind) WHERE kind IN ('allocation','simulated_settlement');
CREATE INDEX pilot_allocations_period ON pilot_financial_entries(period_id,kind);
CREATE TABLE pilot_billing_entries (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 kind TEXT NOT NULL CHECK(kind IN ('obligation','collection','credit','refund','compensation')),
 amount_cents INTEGER NOT NULL, currency TEXT NOT NULL CHECK(currency='SGD'), due_on TEXT,
 reverses_entry_id TEXT REFERENCES pilot_billing_entries(id), idempotency_key TEXT UNIQUE NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE pilot_audit (
 id TEXT PRIMARY KEY, policy_id TEXT REFERENCES pilot_policies(id), action TEXT NOT NULL, details TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE pilot_observations (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, station TEXT NOT NULL, metric TEXT NOT NULL, unit TEXT NOT NULL,
 value NUMERIC NOT NULL, observed_at TEXT NOT NULL, quality TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 UNIQUE(source,station,metric,observed_at,payload_sha256));
CREATE TABLE pilot_daily_aggregates (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, station TEXT NOT NULL, metric TEXT NOT NULL, unit TEXT NOT NULL,
 day TEXT NOT NULL, timezone TEXT NOT NULL CHECK(timezone='Asia/Singapore'), value NUMERIC,
 observed_bins INTEGER NOT NULL CHECK(observed_bins>=0), expected_bins INTEGER NOT NULL CHECK(expected_bins>0),
 status TEXT NOT NULL CHECK(status IN ('pending','final','corrected','rejected')), version TEXT NOT NULL,
 CHECK(observed_bins<=expected_bins), UNIQUE(source,station,metric,day,version));
CREATE TABLE pilot_aggregate_inputs (aggregate_id TEXT REFERENCES pilot_daily_aggregates(id), observation_id TEXT REFERENCES pilot_observations(id), PRIMARY KEY(aggregate_id,observation_id));
CREATE TABLE pilot_imports (source_sha256 TEXT PRIMARY KEY, details TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TRIGGER pilot_decision_final BEFORE UPDATE ON pilot_decisions WHEN json_extract(OLD.response,'$.status')<>'PENDING' BEGIN SELECT RAISE(ABORT,'final decision is immutable'); END;
CREATE TRIGGER pilot_product_versions_no_update BEFORE UPDATE ON pilot_product_versions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_product_versions_no_delete BEFORE DELETE ON pilot_product_versions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_evidence_no_update BEFORE UPDATE ON pilot_evidence BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_evidence_no_delete BEFORE DELETE ON pilot_evidence BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_decision_revisions_no_update BEFORE UPDATE ON pilot_decision_revisions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_decision_revisions_no_delete BEFORE DELETE ON pilot_decision_revisions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_instructions_no_update BEFORE UPDATE ON pilot_instructions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_instructions_no_delete BEFORE DELETE ON pilot_instructions BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_settlement_attempts_no_update BEFORE UPDATE ON pilot_settlement_attempts BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_settlement_attempts_no_delete BEFORE DELETE ON pilot_settlement_attempts BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_financial_entries_no_update BEFORE UPDATE ON pilot_financial_entries BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_financial_entries_no_delete BEFORE DELETE ON pilot_financial_entries BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_billing_entries_no_update BEFORE UPDATE ON pilot_billing_entries BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_billing_entries_no_delete BEFORE DELETE ON pilot_billing_entries BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_audit_no_update BEFORE UPDATE ON pilot_audit BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_audit_no_delete BEFORE DELETE ON pilot_audit BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_observations_no_update BEFORE UPDATE ON pilot_observations BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_observations_no_delete BEFORE DELETE ON pilot_observations BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_daily_aggregates_no_update BEFORE UPDATE ON pilot_daily_aggregates BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_daily_aggregates_no_delete BEFORE DELETE ON pilot_daily_aggregates BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_aggregate_inputs_no_update BEFORE UPDATE ON pilot_aggregate_inputs BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_aggregate_inputs_no_delete BEFORE DELETE ON pilot_aggregate_inputs BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_imports_no_update BEFORE UPDATE ON pilot_imports BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
CREATE TRIGGER pilot_imports_no_delete BEFORE DELETE ON pilot_imports BEGIN SELECT RAISE(ABORT,'append-only pilot ledger'); END;
