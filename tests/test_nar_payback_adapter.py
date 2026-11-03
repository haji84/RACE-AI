"""Fictional paybacks only; no real provider fetch, stored results or bets."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from race_ai.nar_payback_adapter import IntakeError, parse_payback, main

CAP = "2030-01-01T22:00:00+09:00"

def make_line(venue="架空場", day="20300101", no="1", combo=(2,1,4), pay="1500"):
    row = [""] * 54
    row[:4] = [venue, day, no, "架空レース"]
    if combo is not None:
        row[49:52] = list(map(str, combo))
        row[52] = pay
    return ",".join(row) + "\n"

class NarPaybackTests(unittest.TestCase):
    def test_one_race_produces_unverified_candidate_not_a_settlement(self):
        doc = parse_payback(make_line().encode("cp932"), CAP, "UNVERIFIED")
        self.assertEqual(len(doc["records"]), 1)
        self.assertEqual(doc["records"][0]["trifecta_payouts"][0],
                         {"combination":[2,1,4],"yen_per_100":1500})
        self.assertFalse(doc["forecast_comparison_allowed"])
        self.assertEqual(doc["records"][0]["refund_status"],"UNKNOWN")

    def test_same_race_dead_heat_multiple_distinct_payout_lines(self):
        csv = make_line(combo=(2,1,4),pay="1500") + make_line(combo=(2,4,1),pay="2800")
        a = parse_payback(csv.encode("cp932"),CAP,"UNVERIFIED")
        self.assertEqual(len(a["records"]),1)
        self.assertEqual(len(a["records"][0]["trifecta_payouts"]),2)

    def test_absent_payout_does_not_mean_canceled_or_refunded(self):
        item = parse_payback(make_line(combo=None).encode("cp932"),CAP,"UNVERIFIED")
        self.assertEqual(item["records"][0]["trifecta_payouts"],[])
        self.assertEqual(item["records"][0]["result_finality"],"UNVERIFIED")
        self.assertEqual(item["records"][0]["refund_status"],"UNKNOWN")

    def test_reject_changed_schema_and_untrusted_values(self):
        with self.assertRaisesRegex(IntakeError,"layout"):
            parse_payback("架空場,20300101,1,2,3\n".encode("cp932"),CAP,"UNVERIFIED")
        with self.assertRaisesRegex(IntakeError,"yen payout"):
            parse_payback(make_line(combo=(1,2,3),pay="").encode("cp932"),CAP,"UNVERIFIED")
        with self.assertRaisesRegex(IntakeError,"duplicate trifecta"):
            parse_payback((make_line()+make_line()).encode("cp932"),CAP,"UNVERIFIED")
        with self.assertRaisesRegex(IntakeError,"mixed event dates"):
            parse_payback((make_line()+make_line(day="20300102")).encode("cp932"),CAP,"UNVERIFIED")

    def test_zip_selects_payback_not_odds_and_exclusive_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            archive,output = path/"sample.zip",path/"output.json"
            with ZipFile(archive,"w") as f:
                f.writestr("20300101_payback.csv",make_line().encode("cp932"))
                f.writestr("20300101_odds.csv",b"DO NOT PARSE ODDS")
            args=["--input",str(archive),"--output",str(output),
                  "--captured-at",CAP,"--source-rights-ref","UNVERIFIED"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0)
            obj=json.loads(output.read_text())
            self.assertFalse(obj["official_finality_independently_verified"])
            previous=output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),2)
            self.assertEqual(output.read_bytes(),previous)

if __name__=="__main__":
    unittest.main()
