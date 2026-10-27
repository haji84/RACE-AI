-- Read-only full trifecta odds snapshots for a protected staging Worker.
-- Create manually only after explicit deployment and rights review.
-- Separate from immutable AI forecast and result tables. NO auto-betting.
CREATE TABLE IF NOT EXISTS odds_latest (
 race_id TEXT PRIMARY KEY,
 payload_json TEXT NOT NULL,
 received_at TEXT NOT NULL,
 sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_odds_latest_received ON odds_latest(received_at);

-- Separate hard stop for the first race pilot. Budget is counted by UTC day,
-- not reset on every cron invocation.  This limits RACE-AI ingestion attempts,
-- not shared-account traffic from other Cloudflare applications.
CREATE TABLE IF NOT EXISTS odds_ingest_quota (
 utc_day TEXT PRIMARY KEY,
 attempts_used INTEGER NOT NULL CHECK (attempts_used >= 0)
);

-- Only the one-race owner-only pilot: append-only, hash-only measurement log.
-- This is NOT a public official odds feed, sales cutoff freeze or AI forecast.
CREATE TABLE IF NOT EXISTS odds_pilot_measurements (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 race_id TEXT NOT NULL,
 source_url TEXT NOT NULL,
 source_published_at TEXT,
 scrape_started_at TEXT NOT NULL,
 scrape_completed_at TEXT NOT NULL,
 received_at TEXT NOT NULL,
 snapshot_sha256 TEXT NOT NULL,
 ticket_count INTEGER NOT NULL CHECK(ticket_count = 120),
 quoted_count INTEGER NOT NULL CHECK(quoted_count BETWEEN 0 AND 120),
 method TEXT NOT NULL CHECK(method = 'ONE_SHOT_CLOUDFLARE_BROWSER_RUN')
);

-- Per-race low-volume test cap for manually probed official odds.
-- In the 2026-10-24 芦屋6R experiment the first count was recorded after
-- the original successful source call; the second source call used an
-- atomic UPDATE...RETURNING. No scheduled crawler was enabled.
CREATE TABLE IF NOT EXISTS odds_pilot_race_quota (
 utc_day TEXT NOT NULL,
 race_id TEXT NOT NULL,
 attempts_used INTEGER NOT NULL CHECK (attempts_used BETWEEN 0 AND 3),
 PRIMARY KEY (utc_day, race_id)
);
