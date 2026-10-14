import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from race_ai.day_snapshot_publisher import publish, validate

JST = ZoneInfo("Asia/Tokyo")


def sample(day):
    return {
        "date_jst": day, "source_url": "https://example.org/approved",
        "source_sha256": "a" * 64,
        "first_observed_at": datetime.now(JST).isoformat(),
        "venues": [{"venue": "18", "races": [{
            "race_id": day.replace("-", "") + "-18-03",
            "boats": [{"lane": i, "racer_registration_id": str(4000 + i),
                       "motor_no": i} for i in range(1, 7)]
        }]}]
    }


class SnapshotPublisherTests(unittest.TestCase):
    def test_approved_snapshot_atomic_publish(self):
        day = datetime.now(JST).date()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, approval, output = root / "source.json", root / "approval.json", root / "web/data/today.json"
            source.write_text(json.dumps(sample(day.isoformat())), encoding="utf-8")
            approval.write_text(json.dumps({"redistribution_authorized": True,
                "source_url": "https://example.org/approved",
                "evidence_reference": "approved-test-fixture", "reviewed_by": "test"}), encoding="utf-8")
            publish(source, approval, output, today=day)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["redistribution_authorized"])
            self.assertEqual(result["races"], 1)
            self.assertEqual(result["complete_six_boat_races"], 1)

    def test_yesterday_rejected_without_overwriting_current(self):
        day = datetime.now(JST).date()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, approval, output = root / "source.json", root / "approval.json", root / "today.json"
            output.write_text("unchanged", encoding="utf-8")
            source.write_text(json.dumps(sample("2026-01-01")), encoding="utf-8")
            approval.write_text(json.dumps({"redistribution_authorized": True,
                "source_url": "https://example.org/approved",
                "evidence_reference": "test", "reviewed_by": "test"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                publish(source, approval, output, today=day)
            self.assertEqual(output.read_text(encoding="utf-8"), "unchanged")

    def test_missing_rights_rejected(self):
        day = datetime.now(JST).date()
        with self.assertRaises(ValueError):
            validate(sample(day.isoformat()), today=day, approval={})

    def test_duplicate_lane_rejected(self):
        day = datetime.now(JST).date()
        value = sample(day.isoformat())
        value["venues"][0]["races"][0]["boats"][1]["lane"] = 1
        with self.assertRaises(ValueError):
            validate(value, today=day, approval={"redistribution_authorized": True,
                "source_url": "https://example.org/approved",
                "evidence_reference": "test", "reviewed_by": "test"})
