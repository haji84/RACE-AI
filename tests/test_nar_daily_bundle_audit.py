"""Synthetic NAR official-layout ZIP integration tests; zero real source material."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from race_ai.operator_export_intake import IntakeError
from race_ai.nar_daily_bundle_audit import audit_daily_zip, main

CAP="2030-01-15T07:00:00+09:00"
NAME="20300115_1894687200_race.zip"
RACES=("架空場,20300115,1,1140,架空1R\n"
       "架空場,20300115,2,1210,架空2R\n")
def payback_row(race,combo=(2,1,4),yen=1800):
    r=[""]*54
    r[:4]=["架空場","20300115",str(race),"架空"]
    r[49:52]=list(map(str,combo))
    r[52]=str(yen)
    return ",".join(r)+"\n"

def zipped(racelist=RACES,payback=None,extra=None):
    mem=io.BytesIO()
    with ZipFile(mem,"w") as z:
        z.writestr("20300115_racelist.csv",racelist.encode("cp932"))
        z.writestr("20300115_horselist.csv",b"ignored runner source")
        if payback is not None:
            z.writestr("20300115_payback.csv",payback.encode("cp932"))
        if extra is not None:
            z.writestr(extra,b"bad")
    return mem.getvalue()

class NarBundleTests(unittest.TestCase):
    def test_prior_to_settlement_ledger_2_races_no_forecasts(self):
        result=audit_daily_zip(zipped(),filename=NAME,captured_at=CAP,rights_ref="UNVERIFIED")
        self.assertEqual(len(result["daily_index"]["records"]),2)
        self.assertIsNone(result["payout_candidates"])
        self.assertFalse(result["forecast_comparison_allowed"])
        self.assertFalse(result["complete_daily_coverage_proven"])
        self.assertTrue(all(r["sales_cutoff_at"] is None and r["prediction"] is None
                            for r in result["daily_index"]["records"]))

    def test_after_result_candidate_keeps_missing_and_no_authentication(self):
        result=audit_daily_zip(zipped(payback=payback_row(1)),filename=NAME,
                               captured_at=CAP,rights_ref="UNVERIFIED")
        self.assertEqual(len(result["payout_candidates"]["records"]),1)
        self.assertEqual(len(result["races_without_payout_candidate"]),1)
        self.assertEqual(result["payout_unlisted_in_race_index"],[])
        self.assertFalse(result["official_result_finality_proven"])
        self.assertFalse(result["model_training_eligible"])

    def test_unlisted_payback_detected_not_silent(self):
        result=audit_daily_zip(zipped(payback=payback_row(3)),filename=NAME,
                               captured_at=CAP,rights_ref="UNVERIFIED")
        self.assertEqual(result["payout_unlisted_in_race_index"],
                         ["horse_local:2030-01-15:架空場:3"])

    def test_zip_reject_odds_path_traversal_and_mixed_day(self):
        for bad in ("20300115_odds.csv","../20300115_payback.csv",
                    "20300116_payback.csv"):
            with self.subTest(bad=bad),self.assertRaisesRegex(IntakeError,"unexpected ZIP"):
                audit_daily_zip(zipped(extra=bad),filename=NAME,captured_at=CAP,
                                rights_ref="UNVERIFIED")

    def test_reject_wrong_archive_date_and_invalid_name(self):
        with self.assertRaisesRegex(IntakeError,"filename"):
            audit_daily_zip(zipped(),filename="unknown.zip",captured_at=CAP,
                            rights_ref="UNVERIFIED")
        with self.assertRaisesRegex(IntakeError,"date mismatch"):
            audit_daily_zip(zipped(),filename="20300116_1894687200_race.zip",
                            captured_at=CAP,rights_ref="UNVERIFIED")

    def test_cli_creates_unverified_output_once(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/NAME
            output=Path(d)/"audit.json"
            file.write_bytes(zipped(payback=payback_row(1)))
            args=["--input",str(file),"--output",str(output),
                  "--captured-at",CAP,"--source-rights-ref","UNVERIFIED"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0)
            saved=json.loads(output.read_text())
            self.assertTrue(saved["source_zip_sha256"])
            original=output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),2)
            self.assertEqual(output.read_bytes(),original)

if __name__=="__main__":
    unittest.main()
