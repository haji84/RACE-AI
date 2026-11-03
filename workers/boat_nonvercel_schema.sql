-- Separate private pilot D1 namespace; no existing odds tables are mutated.
-- Apply only after verifying Cloudflare account plan and deployment approval.
CREATE TABLE IF NOT EXISTS boat_exhibition_freezes (
 race_id TEXT PRIMARY KEY,
 model_id TEXT NOT NULL,
 source_sha256 TEXT NOT NULL CHECK(length(source_sha256)=64),
 cutoff_at TEXT NOT NULL,
 body_json TEXT NOT NULL CHECK(length(body_json)<=120000),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 db_stored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS boat_exhibition_outcomes (
 race_id TEXT NOT NULL,
 result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64),
 report_json TEXT NOT NULL CHECK(length(report_json)<=5000),
 report_sha256 TEXT NOT NULL CHECK(length(report_sha256)=64),
 db_saved_at TEXT NOT NULL,
 PRIMARY KEY(race_id,result_sha256)
);
CREATE TRIGGER IF NOT EXISTS boat_exhibition_freezes_no_update BEFORE UPDATE
 ON boat_exhibition_freezes BEGIN SELECT RAISE(ABORT,'FORECAST_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_freezes_no_delete BEFORE DELETE
 ON boat_exhibition_freezes BEGIN SELECT RAISE(ABORT,'FORECAST_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_outcomes_no_update BEFORE UPDATE
 ON boat_exhibition_outcomes BEGIN SELECT RAISE(ABORT,'RESULT_REVISION_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_outcomes_no_delete BEFORE DELETE
 ON boat_exhibition_outcomes BEGIN SELECT RAISE(ABORT,'RESULT_REVISION_IMMUTABLE'); END;
