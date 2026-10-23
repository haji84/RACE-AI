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
