"""Day identities from already owner-saved non-Rakuten material only."""
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_non_rakuten_day import (
    SCHEMA, OwnerDayRosterError, read_saved_day_roster
)

DAY = "2030-01-15"


def saved_roster():
    return {
        "schema": SCHEMA, "event_date_jst": DAY,
        "source_url": "https://www.keirin.jp/pc/raceschedule",
        "source_sha256": "a" * 64,
        "captured_at": "2030-01-14T20:00:00+09:00",
        "races": [
            {"race_id": f"2030011536{n:02}", "venue_code": 36, "race_no": n}
            for n in range(1, 4)
        ] + [
            {"race_id": f"2030011563{n:02}", "venue_code": 63, "race_no": n}
            for n in range(1, 3)
        ],
    }


class SavedRosterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "owner-roster.json"

    def read(self, doc):
        self.path.write_text(json.dumps(doc), encoding="utf-8")
        return read_saved_day_roster(str(self.path), DAY)

    def test_non_rakuten_races_are_visible_but_unconfirmed(self):
        rows = self.read(saved_roster())
        self.assertEqual(rows["race_count"], 5)
        self.assertEqual(rows["venue_count"], 2)
        self.assertEqual(rows["venue_race_counts"], {"36": 3, "63": 2})
        self.assertFalse(rows["complete_national_coverage_verified"])
        self.assertFalse(rows["official_cutoffs_verified"])
        self.assertFalse(rows["source_use_rights_verified"])
        self.assertTrue(rows["provenance_self_reported"])

    def test_original_rakuten_origin_rejected(self):
        doc = saved_roster()
        doc["source_url"] = "https://keirin.kdreams.jp/kaisai/2030/01/15/"
        with self.assertRaisesRegex(OwnerDayRosterError, "NON_RAKUTEN"):
            self.read(doc)

    def test_wrong_day_duplicate_and_race_number_rejected(self):
        for mutation in ("wrong_day", "duplicate", "wrong_race_no"):
            with self.subTest(mutation=mutation):
                doc = saved_roster()
                if mutation == "wrong_day":
                    doc["event_date_jst"] = "2030-01-14"
                elif mutation == "duplicate":
                    doc["races"].append(doc["races"][0].copy())
                else:
                    doc["races"][0]["race_id"] = "203001153612"
                with self.assertRaises(OwnerDayRosterError):
                    self.read(doc)

    def test_broken_venue_sequence_rejected(self):
        doc = saved_roster()
        doc["races"] = [r for r in doc["races"]
                        if r["race_id"] != "203001153602"]
        with self.assertRaisesRegex(OwnerDayRosterError, "GAPPED"):
            self.read(doc)


if __name__ == "__main__":
    unittest.main()
