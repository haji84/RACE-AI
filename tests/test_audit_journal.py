import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from race_ai.core import SourceError
from race_ai.audit_journal import append_report,journal_report

def report(day,digest="a"*64,venues=13,races=156):
    return dict(day_jst=day,source_kind="OFFICIAL_B",
       archive_sha256=digest,verified_at=day+"T07:27:00+09:00",
       venues=venues,races=races,assigned_boat_rows=races*6,
       status="OFFICIAL_B_MOTOR_COLUMNS_STRUCTURAL_CHECK_ONLY")

class MetadataJournalTests(unittest.TestCase):
    def test_reopen_sqlite_and_two_dates_and_duplicate(self):
        with tempfile.TemporaryDirectory() as t:
            filename=Path(t)/"evidence.sqlite"
            with sqlite3.connect(filename) as db:
                append_report(db,report("2026-10-13","a"*64,11,132))
                append_report(db,report("2026-10-14","b"*64,13,156))
            with sqlite3.connect(filename) as db:
                append_report(db,report("2026-10-14","b"*64,13,156))
                summary=journal_report(db)
                self.assertEqual(summary["stored_days"],2)
                self.assertEqual(len(summary["rows"]),2)
                self.assertEqual(summary["actual_scheduled_job_days_verified"],0)

    def test_same_hash_conflicting_metadata_rejected(self):
        with sqlite3.connect(":memory:") as db:
            append_report(db,report("2026-10-14"))
            with self.assertRaises(SourceError):
                append_report(db,report("2026-10-14",races=12))

    def test_invalid_count_rejected(self):
        with sqlite3.connect(":memory:") as db:
            q=report("2026-10-14")
            q["assigned_boat_rows"]=0
            with self.assertRaises(SourceError):
                append_report(db,q)

    def test_fake_success_status_rejected(self):
        with sqlite3.connect(":memory:") as db:
            q=report("2026-10-14")
            q["status"]="ALL_VENUES_DAILY_SUCCESS"
            with self.assertRaises(SourceError):
                append_report(db,q)

if __name__=="__main__":
    unittest.main()
