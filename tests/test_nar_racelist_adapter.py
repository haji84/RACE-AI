"""All NAR inputs below fictional; local only, no HTTP."""
import contextlib,io,json
from pathlib import Path
import tempfile
import unittest
import zipfile
from race_ai.nar_racelist_adapter import parse_racelist,main,IntakeError

CSV="競馬場,競走年月日,レース番号,発走時刻,レース名\n架空競馬場,20300101,1,1140,架空１Ｒ\n架空競馬場,20300101,2,1210,架空２Ｒ\n"
CAP="2030-01-01T07:00:00+09:00"

class NarAdapterTests(unittest.TestCase):
    def test_schedule_not_misread_as_sales_cutoff(self):
        x=parse_racelist(CSV.encode("utf-8"),CAP,"UNVERIFIED")
        self.assertEqual(x["event_date_jst"],"2030-01-01")
        self.assertEqual(len(x["races"]),2)
        self.assertTrue(all(r["sales_cutoff_at"] is None for r in x["races"]))

    def test_official_positioned_headerless_csv(self):
        # The public layout defines field positions without promising headers.
        no_header="架空競馬場,20300101,1,1140,重賞\n架空競馬場,20300101,2,1210,普通\n"
        out=parse_racelist(no_header.encode("cp932"),CAP,"UNVERIFIED")
        self.assertEqual([row["race_no"] for row in out["races"]],[1,2])
        self.assertTrue(all(row["sales_cutoff_at"] is None for row in out["races"]))

    def test_reject_wrong_header_market_input(self):
        with self.assertRaisesRegex(IntakeError,"header"):
            parse_racelist("競馬場,競走年月日,人気,オッズ\n架空,20300101,1,2\n".encode("utf-8"),CAP,"UNVERIFIED")

    def test_zip_selects_only_racelist_not_odds(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);src=p/"sample.zip";out=p/"out.json"
            with zipfile.ZipFile(src,"w") as zip:
                zip.writestr("20300101_racelist.csv",CSV.encode("cp932"))
                zip.writestr("20300101_odds.csv",b"DO-NOT-READ")
            args=["--input",str(src),"--output",str(out),"--captured-at",CAP,
                  "--source-rights-ref","UNVERIFIED"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0)
            data=json.loads(out.read_text())
            self.assertEqual(len(data["records"]),2)
            self.assertFalse(data["intake_meta"]["permission_independently_verified"])
            self.assertTrue(all(r["prediction"] is None for r in data["records"]))
            original=out.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),2)
            self.assertEqual(out.read_bytes(),original)

    def test_duplicate_id_rejected_by_shared_intake(self):
        from race_ai.operator_export_intake import transform
        x=parse_racelist((CSV+"架空競馬場,20300101,1,1140,duplicate\n").encode("utf-8"),CAP,"UNVERIFIED")
        with self.assertRaisesRegex(IntakeError,"duplicate"):
            transform(x,"0"*64)

if __name__=="__main__":
    unittest.main()
