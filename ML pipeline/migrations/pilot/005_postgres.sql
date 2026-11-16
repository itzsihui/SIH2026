-- Reviewed-evidence simulation lifecycle/entitlement v5. No payment execution.
CREATE TABLE engine_terms (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT UNIQUE NOT NULL REFERENCES pilot_periods(id),
 version_id TEXT NOT NULL REFERENCES pilot_product_versions(id), start TEXT NOT NULL, "end" TEXT NOT NULL,
 contract TEXT NOT NULL, contract_sha256 TEXT NOT NULL, accepted_at TEXT NOT NULL,
 UNIQUE(policy_id,start), CHECK("end">=start));
INSERT INTO engine_terms SELECT 'SIM-TERM-' || r.id,p.id,r.id,p.version_id,CAST(p.start AS TEXT),CAST(p."end" AS TEXT),p.contract,p.contract_sha256,CAST(p.accepted_at AS TEXT)
 FROM pilot_policies p JOIN pilot_periods r ON r.policy_id=p.id;
CREATE TABLE engine_lifecycle_events (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, policy_id TEXT NOT NULL REFERENCES pilot_policies(id),
 term_id TEXT NOT NULL REFERENCES engine_terms(id), action TEXT NOT NULL CHECK(action IN ('activate_simulation','cancel_simulation','record_expiry')),
 effective_on TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES auth_principals(id), reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
 UNIQUE(term_id,action));
CREATE TABLE engine_period_modes (period_id TEXT PRIMARY KEY REFERENCES pilot_periods(id), mode TEXT NOT NULL CHECK(mode IN ('synthetic_demo','reviewed_evidence')));
INSERT INTO engine_period_modes SELECT DISTINCT period_id,'synthetic_demo' FROM pilot_decisions;
CREATE TABLE engine_decisions (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 period_id TEXT NOT NULL REFERENCES pilot_periods(id), day TEXT NOT NULL, peril TEXT NOT NULL CHECK(peril IN ('rain','haze')),
 context_sha256 TEXT NOT NULL, effect TEXT NOT NULL CHECK(effect IN ('accepted','review_required','review_pending')),
 payload TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(term_id,day,peril,context_sha256,effect));
CREATE TABLE engine_cap_entries (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 decision_id TEXT NOT NULL REFERENCES engine_decisions(id), day TEXT NOT NULL, peril TEXT NOT NULL CHECK(peril IN ('rain','haze')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents>0), currency TEXT NOT NULL CHECK(currency='SGD'), idempotency_key TEXT UNIQUE NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE engine_entitlement_entries (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), period_id TEXT NOT NULL REFERENCES pilot_periods(id),
 decision_id TEXT NOT NULL REFERENCES engine_decisions(id), day TEXT NOT NULL, peril TEXT NOT NULL CHECK(peril IN ('rain','haze')),
 amount_cents INTEGER NOT NULL CHECK(amount_cents<>0), currency TEXT NOT NULL CHECK(currency='SGD'), idempotency_key TEXT UNIQUE NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE engine_replay_plans (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), term_id TEXT NOT NULL REFERENCES engine_terms(id),
 through_day TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(term_id,fingerprint));
CREATE TABLE engine_replay_reviews (
 id TEXT PRIMARY KEY, plan_id TEXT UNIQUE NOT NULL REFERENCES engine_replay_plans(id), actor_id TEXT NOT NULL REFERENCES auth_principals(id),
 source_ref TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE INDEX engine_events_order ON engine_decisions(period_id,day,peril,sequence);
CREATE TRIGGER engine_terms_no_change BEFORE UPDATE OR DELETE ON engine_terms FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_lifecycle_events_no_change BEFORE UPDATE OR DELETE ON engine_lifecycle_events FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_period_modes_no_change BEFORE UPDATE OR DELETE ON engine_period_modes FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_decisions_no_change BEFORE UPDATE OR DELETE ON engine_decisions FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_cap_entries_no_change BEFORE UPDATE OR DELETE ON engine_cap_entries FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_entitlement_entries_no_change BEFORE UPDATE OR DELETE ON engine_entitlement_entries FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_replay_plans_no_change BEFORE UPDATE OR DELETE ON engine_replay_plans FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER engine_replay_reviews_no_change BEFORE UPDATE OR DELETE ON engine_replay_reviews FOR EACH ROW EXECUTE FUNCTION weather_append_only();
