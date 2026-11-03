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


-- One venue/day official cutoff list and bounded provider traffic.
CREATE TABLE IF NOT EXISTS boat_race_schedule (
 race_id TEXT PRIMARY KEY,
 date_jst TEXT NOT NULL,
 venue TEXT NOT NULL,
 race_no INTEGER NOT NULL CHECK(race_no BETWEEN 1 AND 12),
 cutoff_at TEXT NOT NULL,
 UNIQUE(date_jst,venue,race_no)
);
CREATE TABLE IF NOT EXISTS boat_source_budget (
 day_jst TEXT NOT NULL,
 venue TEXT NOT NULL,
 attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 120),
 blocked_until TEXT,
 PRIMARY KEY(day_jst,venue)
);
CREATE TRIGGER IF NOT EXISTS boat_race_schedule_no_update BEFORE UPDATE ON boat_race_schedule
 BEGIN SELECT RAISE(ABORT,'SCHEDULE_REVISION_REQUIRES_NEW_VERSION'); END;
CREATE TRIGGER IF NOT EXISTS boat_race_schedule_no_delete BEFORE DELETE ON boat_race_schedule
 BEGIN SELECT RAISE(ABORT,'SCHEDULE_NOT_DELETABLE'); END;

-- Prospective challenger trained ONLY on earlier append-only official outcomes.
-- Research model never replaces the frozen primary race prediction.
CREATE TABLE IF NOT EXISTS boat_exhibition_shadow_freezes (
 race_id TEXT PRIMARY KEY,
 model_id TEXT NOT NULL,
 primary_sha256 TEXT NOT NULL CHECK(length(primary_sha256)=64),
 cutoff_at TEXT NOT NULL,
 body_json TEXT NOT NULL CHECK(length(body_json)<=120000),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 db_stored_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS boat_exhibition_shadow_outcomes (
 race_id TEXT NOT NULL,
 result_sha256 TEXT NOT NULL CHECK(length(result_sha256)=64),
 report_json TEXT NOT NULL CHECK(length(report_json)<=5000),
 report_sha256 TEXT NOT NULL CHECK(length(report_sha256)=64),
 db_saved_at TEXT NOT NULL,
 PRIMARY KEY(race_id,result_sha256)
);
CREATE INDEX IF NOT EXISTS boat_outcomes_history_asof
 ON boat_exhibition_outcomes(db_saved_at,race_id);
CREATE TRIGGER IF NOT EXISTS boat_exhibition_shadow_freezes_no_update BEFORE UPDATE
 ON boat_exhibition_shadow_freezes BEGIN SELECT RAISE(ABORT,'SHADOW_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_shadow_freezes_no_delete BEFORE DELETE
 ON boat_exhibition_shadow_freezes BEGIN SELECT RAISE(ABORT,'SHADOW_NOT_DELETABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_shadow_outcomes_no_update BEFORE UPDATE
 ON boat_exhibition_shadow_outcomes BEGIN SELECT RAISE(ABORT,'SHADOW_SCORE_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS boat_exhibition_shadow_outcomes_no_delete BEFORE DELETE
 ON boat_exhibition_shadow_outcomes BEGIN SELECT RAISE(ABORT,'SHADOW_SCORE_NOT_DELETABLE'); END;
