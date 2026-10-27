"""SQLite integration contract for the disabled, one-race odds source pilot.
The test never connects to Cloudflare or an upstream race provider.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLAIM_SQL = (
    "INSERT INTO odds_auto_source_attempts(race_id,attempt_at,status) "
    "SELECT ?,?,'CLAIMED' WHERE NOT EXISTS ("
    "SELECT 1 FROM odds_auto_source_attempts WHERE race_id=? "
    "AND (julianday(attempt_at)>julianday(?) - 60.0/86400.0 "
    "OR (blocked_until IS NOT NULL AND julianday(blocked_until)>julianday(?)))) "
    "RETURNING id"
)


class SqliteAutoOddsSourceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript((ROOT / "workers/odds_schema.sql").read_text())
        self.db.executescript((ROOT / "workers/odds_auto_source_schema.sql").read_text())

    def tearDown(self):
        self.db.close()

    def claim(self, timestamp, race="20300115-01-01"):
        return self.db.execute(
            CLAIM_SQL, (race, timestamp, race, timestamp, timestamp)
        ).fetchone()

    def test_persistent_60_second_lease_and_race_isolation(self):
        self.assertIsNotNone(self.claim("2030-01-15T00:50:00.000Z"))
        self.assertIsNone(self.claim("2030-01-15T00:50:59.000Z"))
        self.assertIsNotNone(self.claim("2030-01-15T00:51:01.000Z"))
        self.assertIsNotNone(self.claim("2030-01-15T00:50:59.000Z", race="20300115-01-02"))
        count = self.db.execute("SELECT count(*) FROM odds_auto_source_attempts").fetchone()[0]
        self.assertEqual(count, 3)

    def test_rate_limit_backoff_is_durable_across_restarts(self):
        claimed = self.claim("2030-01-15T00:50:00.000Z")
        self.db.execute(
            "UPDATE odds_auto_source_attempts SET status=?, blocked_until=? WHERE id=?",
            ("PROVIDER_DENIED_OR_RATE_LIMITED", "2030-01-15T01:30:00.000Z", claimed[0]),
        )
        self.assertIsNone(self.claim("2030-01-15T01:05:00.000Z"))
        self.assertIsNotNone(self.claim("2030-01-15T01:30:01.000Z"))

    def test_account_level_attempt_budget_is_atomic(self):
        sql = (
            "INSERT INTO odds_ingest_quota(utc_day,attempts_used) VALUES (?,1) "
            "ON CONFLICT(utc_day) DO UPDATE SET attempts_used=attempts_used+1 "
            "WHERE attempts_used < ? RETURNING attempts_used"
        )
        vals = [self.db.execute(sql, ("2030-01-15", 3)).fetchone() for _ in range(4)]
        self.assertEqual([x[0] if x else None for x in vals], [1, 2, 3, None])
        self.assertEqual(
            self.db.execute(
                "SELECT attempts_used FROM odds_ingest_quota WHERE utc_day=?",
                ("2030-01-15",),
            ).fetchone()[0], 3,
        )


if __name__ == "__main__":
    unittest.main()
