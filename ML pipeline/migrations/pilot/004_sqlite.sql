-- Daily evidence v4; local evidence reviews do not issue policies or settle.
CREATE TABLE weather_mapping_reviews (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, station_version_id TEXT NOT NULL REFERENCES weather_station_versions(id),
 valid_from TEXT NOT NULL, valid_until TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','revoked')),
 reviewer_id TEXT NOT NULL REFERENCES auth_principals(id), source_ref TEXT NOT NULL, recorded_at TEXT NOT NULL, CHECK(valid_until>=valid_from));
CREATE TABLE weather_revision_reviews (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, source TEXT NOT NULL, station TEXT NOT NULL, metric TEXT NOT NULL,
 observed_at TEXT NOT NULL, revision_set_sha256 TEXT NOT NULL, selected_observation_id TEXT REFERENCES pilot_observations(id),
 reviewer_id TEXT NOT NULL REFERENCES auth_principals(id), source_ref TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE weather_daily_details (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, aggregate_id TEXT UNIQUE NOT NULL REFERENCES pilot_daily_aggregates(id), kind TEXT NOT NULL CHECK(kind IN ('rain','psi')),
 station TEXT NOT NULL, day TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
 recorded_at TEXT NOT NULL, UNIQUE(kind,station,day,fingerprint));
CREATE TABLE weather_daily_reviews (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, aggregate_id TEXT NOT NULL REFERENCES pilot_daily_aggregates(id),
 result_aggregate_id TEXT NOT NULL REFERENCES pilot_daily_aggregates(id), decision TEXT NOT NULL CHECK(decision IN ('final','rejected')),
 reviewer_id TEXT NOT NULL REFERENCES auth_principals(id), source_ref TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE weather_closure_versions (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, centre_id TEXT NOT NULL REFERENCES pilot_centres(id),
 day TEXT NOT NULL, payload TEXT NOT NULL, closed INTEGER NOT NULL CHECK(closed IN (0,1)), source_ref TEXT NOT NULL, source_sha256 TEXT NOT NULL,
 supersedes_id TEXT REFERENCES weather_closure_versions(id), recorded_at TEXT NOT NULL,
 UNIQUE(centre_id,day,source_sha256));
CREATE TABLE weather_closure_reviews (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, closure_id TEXT NOT NULL REFERENCES weather_closure_versions(id),
 decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')), reviewer_id TEXT NOT NULL REFERENCES auth_principals(id),
 source_ref TEXT NOT NULL, recorded_at TEXT NOT NULL);
CREATE TABLE weather_evidence_selections (
 id TEXT PRIMARY KEY, policy_id TEXT NOT NULL REFERENCES pilot_policies(id), day TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(policy_id,day,fingerprint));
CREATE TRIGGER weather_mapping_reviews_no_update BEFORE UPDATE ON weather_mapping_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_mapping_reviews_no_delete BEFORE DELETE ON weather_mapping_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_revision_reviews_no_update BEFORE UPDATE ON weather_revision_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_revision_reviews_no_delete BEFORE DELETE ON weather_revision_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_daily_details_no_update BEFORE UPDATE ON weather_daily_details BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_daily_details_no_delete BEFORE DELETE ON weather_daily_details BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_daily_reviews_no_update BEFORE UPDATE ON weather_daily_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_daily_reviews_no_delete BEFORE DELETE ON weather_daily_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_closure_versions_no_update BEFORE UPDATE ON weather_closure_versions BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_closure_versions_no_delete BEFORE DELETE ON weather_closure_versions BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_closure_reviews_no_update BEFORE UPDATE ON weather_closure_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_closure_reviews_no_delete BEFORE DELETE ON weather_closure_reviews BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_evidence_selections_no_update BEFORE UPDATE ON weather_evidence_selections BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
CREATE TRIGGER weather_evidence_selections_no_delete BEFORE DELETE ON weather_evidence_selections BEGIN SELECT RAISE(ABORT,'append-only daily evidence'); END;
