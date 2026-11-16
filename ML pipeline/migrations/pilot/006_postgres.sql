-- Billing v6: simulation obligations and deterministic mock reconciliation only.
CREATE TABLE billing_schedules (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT UNIQUE NOT NULL REFERENCES engine_terms(id),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), contract_sha256 TEXT NOT NULL, convention TEXT NOT NULL,
 annual_cents INTEGER NOT NULL CHECK(annual_cents=10400), currency TEXT NOT NULL CHECK(currency='SGD'), created_at TEXT NOT NULL);
CREATE TABLE billing_bills (
 id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES billing_schedules(id), instalment INTEGER NOT NULL CHECK(instalment BETWEEN 1 AND 12),
 due_on TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents IN (866,867)), currency TEXT NOT NULL CHECK(currency='SGD'),
 UNIQUE(schedule_id,instalment));
CREATE TABLE billing_authorizations (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, term_id TEXT NOT NULL REFERENCES engine_terms(id), actor_id TEXT NOT NULL REFERENCES auth_principals(id),
 action TEXT NOT NULL CHECK(action IN ('grant','revoke')), purpose TEXT NOT NULL CHECK(purpose='mock_collections_only'), recorded_at TEXT NOT NULL);
CREATE TABLE billing_attempts (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 bill_id TEXT NOT NULL REFERENCES billing_bills(id), authorization_id TEXT NOT NULL REFERENCES billing_authorizations(id),
 actor_id TEXT NOT NULL REFERENCES auth_principals(id), amount_cents INTEGER NOT NULL CHECK(amount_cents>0), currency TEXT NOT NULL CHECK(currency='SGD'),
 scenario TEXT NOT NULL CHECK(scenario IN ('success','partial','failed','timeout','pending','reversal')),
 provider_ref TEXT UNIQUE NOT NULL, idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(policy_id,idempotency_key));
CREATE TABLE billing_dispatches (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, attempt_id TEXT NOT NULL REFERENCES billing_attempts(id),
 state TEXT NOT NULL CHECK(state IN ('submitting','submitted','uncertain','canceled_unsubmitted')), recorded_at TEXT NOT NULL, UNIQUE(attempt_id,state));
CREATE TABLE billing_provider_events (
 id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES billing_attempts(id), event_id TEXT NOT NULL, provider_sequence INTEGER NOT NULL,
 payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, disposition TEXT NOT NULL CHECK(disposition IN ('applied','stale','quarantined')),
 reason TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE UNIQUE INDEX billing_one_valid_event_id ON billing_provider_events(event_id) WHERE disposition IN ('applied','stale');
CREATE INDEX billing_event_state ON billing_provider_events(attempt_id,provider_sequence);
CREATE TABLE billing_entry_links (
 entry_id TEXT PRIMARY KEY REFERENCES pilot_billing_entries(id), bill_id TEXT NOT NULL REFERENCES billing_bills(id),
 attempt_id TEXT REFERENCES billing_attempts(id), event_receipt_id TEXT REFERENCES billing_provider_events(id));
CREATE TABLE billing_refund_requests (
 id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES billing_attempts(id), actor_id TEXT NOT NULL REFERENCES auth_principals(id),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0), idempotency_key TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(attempt_id,idempotency_key));
-- Local mock state/secret, never a real provider credential and never returned in API/logs.
CREATE TABLE billing_mock_key (id TEXT PRIMARY KEY, secret TEXT NOT NULL);
CREATE TABLE billing_mock_jobs (
 attempt_id TEXT PRIMARY KEY REFERENCES billing_attempts(id), provider_ref TEXT UNIQUE NOT NULL, bill_id TEXT NOT NULL,
 amount_cents INTEGER NOT NULL, scenario TEXT NOT NULL, provider_sequence INTEGER NOT NULL, gross_cents INTEGER NOT NULL,
 refunded_cents INTEGER NOT NULL, reversed_cents INTEGER NOT NULL, status TEXT NOT NULL,
 polls INTEGER NOT NULL DEFAULT 0, refund_request_id TEXT);
CREATE TABLE billing_mock_refunds (request_id TEXT PRIMARY KEY REFERENCES billing_refund_requests(id), payload TEXT NOT NULL);
CREATE TRIGGER billing_schedules_no_change BEFORE UPDATE OR DELETE ON billing_schedules FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_bills_no_change BEFORE UPDATE OR DELETE ON billing_bills FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_authorizations_no_change BEFORE UPDATE OR DELETE ON billing_authorizations FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_attempts_no_change BEFORE UPDATE OR DELETE ON billing_attempts FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_dispatches_no_change BEFORE UPDATE OR DELETE ON billing_dispatches FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_provider_events_no_change BEFORE UPDATE OR DELETE ON billing_provider_events FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_entry_links_no_change BEFORE UPDATE OR DELETE ON billing_entry_links FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_refund_requests_no_change BEFORE UPDATE OR DELETE ON billing_refund_requests FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER billing_mock_refunds_no_change BEFORE UPDATE OR DELETE ON billing_mock_refunds FOR EACH ROW EXECUTE FUNCTION weather_append_only();
