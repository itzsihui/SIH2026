CREATE FUNCTION weather_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append-only weather evidence'; END $$;
-- Weather ingestion v3: raw provenance and provisional revisions only; no settlement.
CREATE TABLE weather_runs (
 sequence BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('rain','psi')), query_day TEXT,
 status TEXT NOT NULL CHECK(status IN ('running','complete','paused','failed','quarantined')),
 next_token TEXT, pages INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_code TEXT);
CREATE TABLE weather_fetches (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES weather_runs(id), endpoint TEXT NOT NULL,
 request_token TEXT, fetched_at TEXT NOT NULL, http_status INTEGER, raw_base64 TEXT NOT NULL,
 raw_sha256 TEXT NOT NULL, body_complete INTEGER NOT NULL CHECK(body_complete IN (0,1)),
 outcome TEXT NOT NULL CHECK(outcome IN ('accepted','quarantined','transport_error','superseded')),
 error_code TEXT, parser_version TEXT NOT NULL);
CREATE TABLE weather_station_versions (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, station TEXT NOT NULL, metadata TEXT NOT NULL,
 metadata_sha256 TEXT NOT NULL, first_observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
 fetch_id TEXT NOT NULL REFERENCES weather_fetches(id), UNIQUE(source,station,metadata_sha256));
CREATE TABLE weather_station_presence (
 fetch_id TEXT NOT NULL REFERENCES weather_fetches(id), station_version_id TEXT NOT NULL REFERENCES weather_station_versions(id),
 reading_count INTEGER NOT NULL CHECK(reading_count>=0), PRIMARY KEY(fetch_id,station_version_id));
CREATE TABLE weather_observation_provenance (
 fetch_id TEXT NOT NULL REFERENCES weather_fetches(id), observation_id TEXT NOT NULL REFERENCES pilot_observations(id),
 station_version_id TEXT NOT NULL REFERENCES weather_station_versions(id), source_updated_at TEXT,
 classification TEXT NOT NULL CHECK(classification IN ('new','equal_duplicate','conflicting_revision','late')),
 PRIMARY KEY(fetch_id,observation_id));
CREATE TABLE weather_alerts (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES weather_runs(id), fetch_id TEXT REFERENCES weather_fetches(id),
 code TEXT NOT NULL, details TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE weather_transport_gate (id TEXT PRIMARY KEY, next_allowed DOUBLE PRECISION NOT NULL);
INSERT INTO weather_transport_gate VALUES ('datagov_realtime',0);
CREATE INDEX weather_observation_lookup ON pilot_observations(source,station,metric,observed_at);
CREATE INDEX weather_fetch_run ON weather_fetches(run_id);
CREATE TRIGGER weather_fetches_no_change BEFORE UPDATE OR DELETE ON weather_fetches FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER weather_station_versions_no_change BEFORE UPDATE OR DELETE ON weather_station_versions FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER weather_station_presence_no_change BEFORE UPDATE OR DELETE ON weather_station_presence FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER weather_observation_provenance_no_change BEFORE UPDATE OR DELETE ON weather_observation_provenance FOR EACH ROW EXECUTE FUNCTION weather_append_only();
CREATE TRIGGER weather_alerts_no_change BEFORE UPDATE OR DELETE ON weather_alerts FOR EACH ROW EXECUTE FUNCTION weather_append_only();
