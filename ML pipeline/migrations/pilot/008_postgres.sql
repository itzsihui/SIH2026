-- Collection accrual v8: mock transaction-linked premium collection. Append-only; no real money, no claim authority.
CREATE TABLE collection_accrual_entries (
 sequence BIGSERIAL PRIMARY KEY, term_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('accrual','accrual_reversal','confirmation','confirmation_reversal')),
 event_id TEXT NOT NULL, ref_event_id TEXT, week_index INTEGER NOT NULL, cycle_index INTEGER NOT NULL,
 amount_cents BIGINT NOT NULL, txn_amount_cents BIGINT NOT NULL DEFAULT 0, reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
 UNIQUE(term_key,kind,event_id));
CREATE INDEX collection_accrual_term ON collection_accrual_entries(term_key,kind,week_index,cycle_index);
CREATE TABLE collection_ignored_events (
 sequence BIGSERIAL PRIMARY KEY, term_key TEXT NOT NULL, event_sha256 TEXT NOT NULL, reason TEXT NOT NULL, recorded_at TEXT NOT NULL,
 UNIQUE(term_key,event_sha256));
CREATE TRIGGER collection_accrual_entries_no_change BEFORE UPDATE OR DELETE ON collection_accrual_entries FOR EACH ROW EXECUTE FUNCTION weather_append_only();
