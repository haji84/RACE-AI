"""Unit tests for daily discover-only immutable coverage ledger."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_daily_ledger import daily_run, save_once
from race_ai.keirin_discovery import DiscoveryError

DAY="2026-11-03"


class DailyLedgerTests(unittest.TestCase):
    def sample(self,day):
        return {
            "source_url":f"https://keirin.kdreams.jp/kaisai/2026/11/03/",
            "source_sha256":"a"*64,
            "races":[{"race_id":f"2026110336{i:02d}",
                      "venue_code":36,"race_no":i} for i in range(1,8)]
                 + [{"race_id":f"2026110363{i:02d}",
                     "venue_code":63,"race_no":i} for i in range(1,13)],
        }

    def test_all_races_keep_unknown_prediction_and_results(self):
        report=daily_run(today=DAY,collector=self.sample)
        self.assertEqual(report["discovered_count"],19)
        self.assertEqual(len(set(report["race_ids"])),19)
        self.assertEqual(report["private_forecasts_generated"],0)
        self.assertEqual(report["provider_result_final_verified"],0)
        self.assertIsNone(report["official_model_hit8"])
        for row in report["records"]:
            self.assertIsNone(row["official_cutoff_at"])
            self.assertIsNone(row["hit8"])
            self.assertEqual(row["forecast_status"],"NOT_GENERATED_INPUTS_UNVERIFIED")

    def test_failing_source_is_failure_not_empty_race_day(self):
        def blocked(_):
            raise DiscoveryError("source unavailable")
        with self.assertRaises(DiscoveryError):
            daily_run(today=DAY,collector=blocked)

    def test_save_once_permissions_and_readback(self):
        doc=daily_run(today=DAY,collector=self.sample)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"race-ledger.json"
            size=save_once(path,doc)
            self.assertEqual(size,path.stat().st_size)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),doc)
            with self.assertRaisesRegex(ValueError,"IMMUTABLE_OUTPUT_EXISTS"):
                save_once(path,{"attempt":"overwrite"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),doc)

    def test_pre_cutoff_data_never_fabricated(self):
        doc=daily_run(today=DAY,collector=self.sample)
        self.assertTrue(all(r["model_version"] is None for r in doc["records"]))
        self.assertFalse(doc["national_coverage_verified"])


if __name__=="__main__":
    unittest.main()
