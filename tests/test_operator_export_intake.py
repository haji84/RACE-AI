"""Synthetic-only regressions for the local 5-category (4 sport) intake."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from race_ai.operator_export_intake import IntakeError, parse_file, transform, main
from race_ai.discovery_reconcile import compare_daily

SPORTS=("boat","keirin","autorace","horse_jra","horse_local")
DATE="2030-01-01"

def fixture():
    return {"schema":"RACE_AI_OPERATOR_EXPORT_V1","event_date_jst":DATE,
            "source_ref":"https://example.invalid/fake","source_rights_ref":"UNVERIFIED",
            "captured_at":"2030-01-01T07:00:00+09:00",
            "races":[{"sport":s,"venue":"fake-"+s,"race_no":1,
                       "sales_cutoff_at":"2030-01-01T09:55:00+09:00",
                       "offering_status":"UNKNOWN"} for s in SPORTS]}

class LocalExportTests(unittest.TestCase):
    def test_five_categories_to_existing_offline_audit(self):
        result=transform(fixture(),"0"*64)
        self.assertEqual(len(result["records"]),5)
        self.assertFalse(result["intake_meta"]["permission_independently_verified"])
        self.assertTrue(all(r["prediction"] is None and not r["cutoff_verified"] for r in result["records"]))
        reference={"scope":"MANUAL_REFERENCE_ONLY","event_date_jst":DATE,
                   "venues":[{"sport":s,"venue":"fake-"+s,"race_numbers":[1]} for s in SPORTS]}
        comparison=compare_daily(reference,result)
        self.assertEqual(comparison["comparison_status"],"REFERENCE_MATCH_ONLY")
        self.assertFalse(comparison["complete_official_coverage_verified"])

    def test_pre_prediction_forbidden_fields_fail_closed(self):
        for name in ("odds","popularity","result","forecast","winning_combo","cutoff_verified"):
            obj=fixture();obj["races"][0][name]=True
            with self.subTest(field=name),self.assertRaisesRegex(IntakeError,"unexpected race fields"):
                transform(obj,"0"*64)

    def test_duplicate_and_invalid_cutoffs(self):
        obj=fixture();obj["races"].append(dict(obj["races"][0]))
        with self.assertRaisesRegex(IntakeError,"duplicate race"):
            transform(obj,"0"*64)
        obj=fixture();obj["races"][0]["sales_cutoff_at"]="2030-01-02T10:00:00+09:00"
        with self.assertRaisesRegex(IntakeError,"cutoff date"):
            transform(obj,"0"*64)
        obj=fixture();obj["races"][0]["sales_cutoff_at"]="2030-01-01T09:55:00"
        with self.assertRaisesRegex(IntakeError,"timezone"):
            transform(obj,"0"*64)

    def test_missing_categories_not_assumed_no_meeting(self):
        obj=fixture();obj["races"]=obj["races"][:1]
        self.assertEqual(len(transform(obj,"0"*64)["intake_meta"]["missing_sports_not_proven_no_meeting"]),4)

    def test_exclusive_output_hash_and_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);src=p/"in.json";dst=p/"out.json"
            src.write_text(json.dumps(fixture()),encoding="utf-8")
            _,source_sha=parse_file(src)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--input",str(src),"--output",str(dst)]),0)
            self.assertEqual(json.loads(dst.read_text())["intake_meta"]["source_sha256"],source_sha)
            before=dst.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--input",str(src),"--output",str(dst)]),2)
            self.assertEqual(dst.read_bytes(),before)
            src.write_text('{"schema":"A","schema":"B"}',encoding="utf-8")
            with self.assertRaisesRegex(IntakeError,"duplicate JSON"):
                parse_file(src)

if __name__=="__main__":
    unittest.main()
