"""No-network operator command checks, all test inputs fictional."""
import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_boat_b_program_bridge import (
    b_handoff, normalized_feed, approved_policy_document, KEY, AT, RACE
)
from race_ai.boat_b_handoff_cli import main


class BCommandTests(unittest.TestCase):
    def _files(self, root):
        files=[Path(root)/x for x in ("b.json","reviewed-policy.json",
                                      "normalized.json","delivery.json")]
        files[0].write_text(json.dumps(b_handoff()),encoding="utf-8")
        files[1].write_text(json.dumps(approved_policy_document()),encoding="utf-8")
        files[2].write_text(json.dumps(normalized_feed()),encoding="utf-8")
        return files

    def test_offline_B_stages_without_inventing_features_or_forecast(self):
        with tempfile.TemporaryDirectory() as td:
            b,p,feature,out=self._files(td)
            args=["--b-handoff",str(b),"--policy",str(p),
                  "--race-id",RACE,"--output",str(out)]
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":KEY.decode()}):
                with contextlib.redirect_stdout(io.StringIO()) as terminal:
                    status=main(args,now=datetime.fromisoformat(AT))
            self.assertEqual(status,0)
            stored=json.loads(out.read_text())
            self.assertFalse(stored["model_eligible"])
            self.assertEqual(stored["status"],"AWAITING_VERIFIED_PRE_RACE_FEATURES")
            self.assertEqual(json.loads(terminal.getvalue())["models_ran"],False)
            self.assertEqual(os.stat(out).st_mode & 0o777,0o600)
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":KEY.decode()}):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args,now=datetime.fromisoformat(AT)),2)
            self.assertEqual(stored,json.loads(out.read_text()))

    def test_offline_B_to_existing_four_models_with_full_features(self):
        with tempfile.TemporaryDirectory() as td:
            b,p,feature,out=self._files(td)
            args=["--b-handoff",str(b),"--policy",str(p),
                  "--feature-feed",str(feature),"--race-id",RACE,
                  "--output",str(out)]
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":KEY.decode()}):
                with contextlib.redirect_stdout(io.StringIO()):
                    rc=main(args,now=datetime.fromisoformat(AT))
            self.assertEqual(rc,0)
            result=json.loads(out.read_text())
            self.assertTrue(result["b_program_reconciled"])
            self.assertEqual(result["research_suite"]["model_count"],4)
            self.assertFalse(result["official_prediction"])
            self.assertIsNone(result["external_receipt"])

    def test_policy_not_present_blocks_no_output(self):
        with tempfile.TemporaryDirectory() as td:
            b,p,feature,out=self._files(td)
            args=["--b-handoff",str(b),"--policy",str(p),
                  "--race-id",RACE,"--output",str(out)]
            with patch.dict(os.environ,{"RACE_AI_SOURCE_REVIEW_KEY":""}):
                with contextlib.redirect_stderr(io.StringIO()) as terminal:
                    status=main(args,now=datetime.fromisoformat(AT))
            self.assertEqual(status,2)
            self.assertIn("B_HANDOFF_BLOCKED",terminal.getvalue())
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
