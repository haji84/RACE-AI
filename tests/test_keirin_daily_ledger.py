"""Unit tests for daily discover-only immutable coverage ledger."""
from datetime import datetime
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.keirin_daily_ledger import daily_run, save_once, main
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

    def test_default_cli_cannot_fetch_excluded_source_or_write_roster(self):
        from tests.test_keirin_discovery import doc

        class Response:
            status = 200
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def geturl(self):
                return "https://keirin.kdreams.jp/kaisai/2026/11/03/"

            def read(self, limit):
                return doc()

        class Opener:
            def __init__(self):
                self.requests = []

            def open(self, request, **kwargs):
                self.requests.append(request)
                return Response()

        transport = Opener()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "today_manifest.json"
            stdout = StringIO()
            with patch("race_ai.keirin_discovery.build_opener",
                       return_value=transport), redirect_stdout(stdout):
                code = main(["--day", DAY, "--output", str(output)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout.getvalue())["state"],
                             "DAILY_DISCOVERY_INCOMPLETE")
            self.assertFalse(output.exists())
        self.assertEqual(transport.requests, [])


if __name__=="__main__":
    unittest.main()
