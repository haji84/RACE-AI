"""Fictional HTML only; tests do not fetch any website."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from race_ai.operator_export_intake import IntakeError
from race_ai.boat_official_web_adapter import transform_official_screen, main

URL = "https://www.boatrace.jp/owpc/pc/race/racelist?hd=20300115&jcd=16&rno=2"
CAPTURED = "2030-01-15T08:00:00+09:00"
HTML = """<html><body><table><tr><th>レース</th><td><a href="?rno=1">1R</a></td><td>2R</td><td>3R</td></tr>
<tr><th>締切予定時刻</th><td>10:58</td><td>11:25</td><td>11:52</td></tr></table>
<table><tr><th>オッズ</th><td>99.9</td></tr><tr><td>結果</td><td>1-2-3</td></tr></table>
</body></html>"""

def audit(html=HTML, url=URL):
    return transform_official_screen(html.encode("utf-8"),source_url=url,
                                     captured_at=CAPTURED,rights_ref="UNVERIFIED")

class OfficialScreenAdapterTests(unittest.TestCase):
    def test_read_screen_schedule_and_preserve_missing_without_result_leak(self):
        obj = audit()
        self.assertEqual(len(obj["records"]), 3)
        self.assertEqual(obj["event_date_jst"], "2030-01-15")
        self.assertEqual(obj["records"][1]["sales_cutoff_at"],"2030-01-15T11:25:00+09:00")
        self.assertEqual(obj["records"][1]["race_id"], "boat:2030-01-15:boatrace-jcd-16:2")
        self.assertFalse(obj["records"][1]["cutoff_verified"])
        self.assertEqual(obj["screen_capture_audit"]["schedule_kind"],
                         "ANNOUNCED_CUTOFF_NOT_VERIFIED")
        self.assertTrue(all(x["prediction"] is None and x["result"] is None for x in obj["records"]))
        self.assertNotIn("99.9", json.dumps(obj))
        self.assertNotIn("1-2-3", json.dumps(obj))
        self.assertFalse(obj["screen_capture_audit"]["automatic_site_collection_authorized"])

    def test_fake_host_and_query_ambiguities_rejected(self):
        for url in (
            URL.replace("www.boatrace.jp","www.boatrace.jp.evil.test"),
            URL.replace("https:", "http:"),
            URL+"&odds=2",
            URL.replace("jcd=16", "jcd=99"),
            URL.replace("rno=2", "rno=13"),
            URL.replace("hd=20300115", "hd=20300230"),
            URL.replace("rno=2", "rno=2&rno=2"),
        ):
            with self.subTest(url=url), self.assertRaises(IntakeError):
                audit(url=url)

    def test_wrong_page_missing_race_and_ambiguous_time_table(self):
        with self.assertRaisesRegex(IntakeError, "absent"):
            audit(url=URL.replace("rno=2","rno=4"))
        with self.assertRaisesRegex(IntakeError, "ambiguous"):
            audit(HTML.replace("</body>", '<table><tr><td>レース</td><td>1R</td></tr><tr><td>締切予定時刻</td><td>13:00</td></tr></table></body>'))
        with self.assertRaisesRegex(IntakeError, "table absent"):
            audit("<table><tr><th>出走表</th><td>1R</td></tr></table>")

    def test_bad_mismatched_and_incomplete_time(self):
        for bad in ("11:99", "不明"):
            with self.subTest(value=bad), self.assertRaisesRegex(IntakeError,"time"):
                audit(HTML.replace("11:25",bad))
        with self.assertRaisesRegex(IntakeError, "length mismatch"):
            audit(HTML.replace("<td>11:52</td>", ""))

    def test_no_web_request_and_exclusive_local_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            inp=Path(directory)/"saved.html";out=Path(directory)/"audit.json"
            inp.write_text(HTML,encoding="utf-8")
            argv=["--html",str(inp),"--output",str(out),
                  "--source-url",URL,"--captured-at",CAPTURED,
                  "--source-rights-ref","UNVERIFIED"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv),0)
            first=out.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv),2)
            self.assertEqual(out.read_bytes(),first)
            self.assertEqual(json.loads(first)["dataset_status"],"AUDIT_ONLY")

if __name__=="__main__":
    unittest.main()
