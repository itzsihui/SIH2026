-- Settlement v7: local mock outbox, immutable authority and confirmed outcomes only.
CREATE TABLE settlement_recipients (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES pilot_merchants(id), owner_id TEXT NOT NULL REFERENCES auth_principals(id),
 reference_sha256 TEXT NOT NULL, wallet_id TEXT UNIQUE NOT NULL, namespace TEXT NOT NULL CHECK(namespace='local_mock_only'),
 created_at TEXT NOT NULL, UNIQUE(merchant_id,reference_sha256));
CREATE TABLE settlement_recipient_reviews (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, recipient_id TEXT NOT NULL REFERENCES settlement_recipients(id),
 actor_id TEXT NOT NULL REFERENCES auth_principals(id), decision TEXT NOT NULL CHECK(decision IN ('approved','revoked')),
 source_ref TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE settlement_outbox (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), day TEXT NOT NULL, peril TEXT NOT NULL CHECK(peril IN ('rain','haze')),
 decision_id TEXT UNIQUE NOT NULL REFERENCES engine_decisions(id), snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO settlement_outbox SELECT DISTINCT 'SIM-OUTBOX-' || d.id,d.policy_id,d.term_id,d.period_id,d.day,d.peril,d.id,d.payload,d.recorded_at
 FROM engine_decisions d JOIN engine_entitlement_entries e ON e.decision_id=d.id;
CREATE TABLE settlement_instructions (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), outbox_id TEXT NOT NULL REFERENCES settlement_outbox(id),
 decision_id TEXT NOT NULL REFERENCES engine_decisions(id), recipient_id TEXT NOT NULL REFERENCES settlement_recipients(id),
 recipient_review_id TEXT NOT NULL REFERENCES settlement_recipient_reviews(id), day TEXT NOT NULL, peril TEXT NOT NULL,
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0), currency TEXT NOT NULL CHECK(currency='SGD'),
 provider_ref TEXT UNIQUE NOT NULL, idempotency_key TEXT NOT NULL, scenario TEXT NOT NULL,
 authority TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES auth_principals(id), created_at TEXT NOT NULL, UNIQUE(policy_id,idempotency_key));
CREATE TABLE settlement_instruction_events (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, instruction_id TEXT NOT NULL REFERENCES settlement_instructions(id),
 state TEXT NOT NULL CHECK(state IN ('queued','submitted','uncertain','canceled_unsent')), reason TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE settlement_dispatch_attempts (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, instruction_id TEXT NOT NULL REFERENCES settlement_instructions(id),
 attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3), actor_id TEXT NOT NULL REFERENCES auth_principals(id),
 recorded_at TEXT NOT NULL, UNIQUE(instruction_id,attempt_number));
CREATE TABLE settlement_provider_events (
 id TEXT PRIMARY KEY, instruction_id TEXT NOT NULL REFERENCES settlement_instructions(id), event_id TEXT NOT NULL,
 provider_sequence INTEGER NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('applied','stale','quarantined')), reason TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE UNIQUE INDEX settlement_valid_event_id ON settlement_provider_events(event_id) WHERE disposition IN ('applied','stale');
CREATE TABLE settlement_cash_entries (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), instruction_id TEXT NOT NULL REFERENCES settlement_instructions(id),
 receipt_id TEXT NOT NULL REFERENCES settlement_provider_events(id), day TEXT NOT NULL, peril TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('mock_confirmed','mock_reversal')), amount_cents INTEGER NOT NULL,
 currency TEXT NOT NULL CHECK(currency='SGD'), idempotency_key TEXT UNIQUE NOT NULL, recorded_at TEXT NOT NULL,
 CHECK((kind='mock_confirmed' AND amount_cents>0) OR (kind='mock_reversal' AND amount_cents<0)));
CREATE TABLE settlement_mock_wallet_entries (
 id TEXT PRIMARY KEY, wallet_id TEXT NOT NULL REFERENCES settlement_recipients(wallet_id),
 cash_entry_id TEXT UNIQUE NOT NULL REFERENCES settlement_cash_entries(id), amount_cents INTEGER NOT NULL CHECK(amount_cents<>0),
 currency TEXT NOT NULL CHECK(currency='SGD'), recorded_at TEXT NOT NULL);
CREATE TABLE settlement_mock_key (id TEXT PRIMARY KEY, secret TEXT NOT NULL);
CREATE TABLE settlement_mock_jobs (
 instruction_id TEXT PRIMARY KEY REFERENCES settlement_instructions(id), provider_ref TEXT UNIQUE NOT NULL,
 recipient_id TEXT NOT NULL, recipient_review_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
 scenario TEXT NOT NULL, provider_sequence INTEGER NOT NULL, gross_cents INTEGER NOT NULL,
 reversed_cents INTEGER NOT NULL, status TEXT NOT NULL, polls INTEGER NOT NULL DEFAULT 0);
CREATE TRIGGER settlement_recipients_no_change BEFORE UPDATE OR DELETE ON settlement_recipients FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_recipient_reviews_no_change BEFORE UPDATE OR DELETE ON settlement_recipient_reviews FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_outbox_no_change BEFORE UPDATE OR DELETE ON settlement_outbox FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_instructions_no_change BEFORE UPDATE OR DELETE ON settlement_instructions FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_instruction_events_no_change BEFORE UPDATE OR DELETE ON settlement_instruction_events FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_dispatch_attempts_no_change BEFORE UPDATE OR DELETE ON settlement_dispatch_attempts FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_provider_events_no_change BEFORE UPDATE OR DELETE ON settlement_provider_events FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_cash_entries_no_change BEFORE UPDATE OR DELETE ON settlement_cash_entries FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER settlement_mock_wallet_entries_no_change BEFORE UPDATE OR DELETE ON settlement_mock_wallet_entries FOR EACH ROW EXECUTE FUNCTION weather_append_only();
