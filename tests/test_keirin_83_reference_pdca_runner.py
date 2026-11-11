"""Private runner with fictional race results; no actual provider collection."""
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import io
import json
import tempfile
import unittest

from scripts.keirin_83_reference_pdca import main
from tests.test_keirin_83_reference_pdca_bridge import (
    sample,settlement
)


class Private83ReferenceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.manifest=self.root/"owner-original.json"
        self.results=self.root/"owner-observed.json"
        self.output=self.root/"version-001-report.json"
        self.source=sample()
        self.manifest.write_text(json.dumps(self.source,
            sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
        rid=next(r["race_id"] for r in self.source["rows"]
                 if r["venue"]=="武雄")
        self.results.write_text(json.dumps(
            [settlement(rid,(1,2,3),18700)],
            sort_keys=True,ensure_ascii=False),encoding="utf-8")
        self.expected=sha256(self.manifest.read_bytes()).hexdigest()

    def execute(self):
        stdout=io.StringIO()
        with redirect_stdout(stdout),patch(
            "scripts.keirin_83_reference_pdca.ORIGINAL_SHA256",
            self.expected):
            state=main(["--manifest",str(self.manifest),
                        "--results",str(self.results),
                        "--output",str(self.output)])
        return state,stdout.getvalue()

    def test_store_one_private_version_read_back_without_public_riders(self):
        code,log=self.execute()
        self.assertEqual(code,0)
        self.assertEqual(json.loads(log)["reference_hits"],1)
        self.assertEqual(json.loads(log)["four_pr71_models_scored"],0)
        self.assertTrue(self.output.is_file())
        private=json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(private["reference_evaluable_published_results"],1)
        self.assertEqual(private["reference_mansha_captured"],1)
        self.assertIsNone(private["formal_Hit8"])
        self.assertNotIn("example.invalid",log)
        self.assertNotIn("synthetic",log)
        self.assertEqual(self.output.stat().st_mode&0o077,0)

    def test_same_report_path_refuses_rewrite(self):
        code,_=self.execute()
        self.assertEqual(code,0)
        original=self.output.read_bytes()
        code,log=self.execute()
        self.assertEqual(code,2)
        self.assertEqual(self.output.read_bytes(),original)
        self.assertEqual(json.loads(log)["state"],
                         "REFERENCE_83R_PDCA_HOLD_OR_INVALID")

    def test_modified_reference_source_rejected_no_output(self):
        self.manifest.write_text(
            self.manifest.read_text(encoding="utf-8")+"\n",
            encoding="utf-8")
        code,log=self.execute()
        self.assertEqual(code,2)
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(log)["state"],
                         "REFERENCE_83R_PDCA_HOLD_OR_INVALID")

    def test_bad_result_duplicates_fail_closed(self):
        self.results.write_text(
            '{"observation":1,"observation":2}',
            encoding="utf-8")
        code,log=self.execute()
        self.assertEqual(code,2)
        self.assertFalse(self.output.exists())
        self.assertNotIn("observation",log)


if __name__=="__main__":
    unittest.main()
