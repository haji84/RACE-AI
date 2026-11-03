"""Offline tests for bounded hourly personal result-page monitor."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_personal_monitor import (
    JST, MonitorError, _manifest, select_one, run_once
)


class MonitorTests(unittest.TestCase):
    def manifest(self, *, day="2026-11-03", rows="3601@0845 3602@0905 3603@0926"):
        temp=tempfile.TemporaryDirectory()
        path=Path(temp.name)/"manifest.json"
        path.write_text(json.dumps({
            "schema":"RACE_AI_KEIRIN_PERSONAL_HOURLY_MANIFEST_V1",
            "event_date_jst":day,
            "origin":"test time labels; not verified official cutoff",
            "query_limit_per_run":1,
            "cutoff_rows":rows
        }),encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return path

    def test_read_actual_76_race_roster(self):
        day, rows = _manifest("config/keirin_personal_20261103_manifest.json")
        self.assertEqual(day,"2026-11-03")
        self.assertEqual(len(rows),76)
        self.assertEqual(len({x[1] for x in rows}),76)

    def test_one_selected_by_cutoff_and_short_window(self):
        at=datetime.fromisoformat("2026-11-03T09:47:00+09:00")
        out=select_one(self.manifest(),at=at)
        self.assertEqual(out["state"],"ONE_RACE_SELECTED")
        self.assertEqual(out["race_id"],"202611033603")
        self.assertFalse(out["cutoff_is_officially_verified"])

    def test_day_mismatch_does_zero_gets(self):
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-04T09:47:00+09:00"),
             allow_get=True,fetch=lambda *a,**k:self.fail("GET not allowed"))
        self.assertEqual(out["state"],"NO_CURRENT_DAY_MANIFEST")
        self.assertEqual(out["get_attempts"],0)

    def test_before_result_window_never_fetches(self):
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-03T08:50:00+09:00"),
             allow_get=True,fetch=lambda *a,**k:self.fail("GET before eligible"))
        self.assertEqual(out["state"],"NO_RECENTLY_FINISHED_RACE")
        self.assertEqual(out["get_attempts"],0)

    def test_dry_run_can_choose_but_makes_no_get(self):
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-03T09:47:00+09:00"),
             allow_get=False,fetch=lambda *a,**k:self.fail("DRYRUN GET"))
        self.assertEqual(out["state"],"DRY_RUN_ONE_RACE_READY")
        self.assertEqual(out["get_attempts"],0)

    def test_live_tries_one_get_only_and_does_not_publish_result(self):
        count=[]
        def fake(ymd,venue,no,*,acknowledgement,route):
            count.append((ymd,venue,no,route))
            return {"schema":"RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1",
                    "page_date_marker":True,"page_race_marker":True,
                    "candidate_result":{"state":"ONE_UNVERIFIED_PROVIDER_CANDIDATE",
                        "triple":[6,1,5],"payout_100yen":11480},
                    "source_sha256":"a"*64}
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-03T09:47:00+09:00"),
             allow_get=True,fetch=fake)
        self.assertEqual(count,[("20261103",36,3,"legacy")])
        self.assertEqual(out["get_attempts"],1)
        self.assertTrue(out["candidate_visible"])
        self.assertFalse(out["confirmed_official_result"])
        self.assertFalse(out["next_forecast_saved"])
        self.assertNotIn("winning_triple",str(out))
        self.assertNotIn("payout",str(out))

    def test_provider_http_error_refuses_to_retry(self):
        from race_ai.keirin_mobile_one_shot import MobileProbeError
        attempted=[]
        def boom(*args,**kwargs):
            attempted.append(True)
            raise MobileProbeError("PROVIDER_HTTP_429")
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-03T09:47:00+09:00"),
             allow_get=True,fetch=boom)
        self.assertEqual(len(attempted),1)
        self.assertEqual(out["state"],"PROVIDER_ONE_GET_FAILED_NO_RETRY")
        self.assertFalse(out["confirmed_official_result"])

    def test_reject_duplicate_or_bad_race_number(self):
        for bad in ["3601@0845 3601@0905","3613@0845","0031@0845","3601@2460"]:
            with self.subTest(bad=bad):
                with self.assertRaises(MonitorError):
                    _manifest(self.manifest(rows=bad))

    def test_one_hour_window_does_not_choose_same_race_next_hour(self):
        manifest=self.manifest(rows="3601@0845 3602@0905")
        first=select_one(manifest,
             at=datetime.fromisoformat("2026-11-03T09:13:00+09:00"))
        later=select_one(manifest,
             at=datetime.fromisoformat("2026-11-03T10:13:00+09:00"))
        self.assertEqual(first["race_id"],"202611033601")
        self.assertEqual(later["race_id"],"202611033602")

    def test_public_log_never_calls_forecast(self):
        out=run_once(self.manifest(),
             now=datetime.fromisoformat("2026-11-03T09:47:00+09:00"),
             allow_get=False)
        self.assertNotIn("top8",str(out))
        self.assertNotIn("prediction",str(out))


if __name__ == "__main__":
    unittest.main()
