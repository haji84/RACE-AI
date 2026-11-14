-- Future one-race licensed feed pilot only. DO NOT apply to live D1 until
-- reviewed against existing schema/backups and explicitly accepted for pilot.
-- Keeps provider failures and readback receipts without storing third-party
-- full market data in public Git. No cron is created by this SQL file.
CREATE TABLE IF NOT EXISTS odds_auto_source_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 race_id TEXT NOT NULL,
 attempt_at TEXT NOT NULL,
 finished_at TEXT,
 status TEXT NOT NULL,
 source_published_at TEXT,
 server_received_at TEXT,
 snapshot_sha256 TEXT,
 quoted_count INTEGER CHECK(quoted_count BETWEEN 0 AND 120),
 changed_count INTEGER CHECK(changed_count BETWEEN 0 AND 120),
 http_status INTEGER,
 blocked_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_odds_auto_source_attempts_race_time
 ON odds_auto_source_attempts(race_id,attempt_at);
