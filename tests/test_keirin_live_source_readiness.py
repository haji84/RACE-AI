"""No-provider regression tests for rapid prospective KEIRIN source admission."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch
import tempfile

from scripts.keirin_live_source_readiness import assess, REQUIRED, main as run_guard


class PilotReadinessTest(TestCase):
    def test_missing_keys_hold_without_provider_access(self):
        r = assess({"RACE_AI_STATE_KEY": "a"})
        self.assertFalse(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(r["status"], "HOLD_MISSING_TRUSTED_SOURCE_CONFIGURATION")
        self.assertEqual(len(r["missing_config_names"]), len(REQUIRED)-1)
        self.assertFalse(r["real_race_15min_proven"])
        self.assertFalse(r["source_rights_verified"])
        self.assertEqual(r["provider_requests_by_readiness"], 0)

    def test_empty_is_not_configured(self):
        r = assess({key:"" for key in REQUIRED})
        self.assertEqual(set(r["missing_config_names"]), set(REQUIRED))

    def test_present_is_not_license_or_real_proof(self):
        r = assess({key:f"private-{i}-opaque" for i,key in enumerate(REQUIRED)})
        self.assertTrue(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(r["status"], "SOURCE_CONFIG_PRESENT_ADMISSION_STILL_REQUIRED")
        self.assertFalse(r["source_rights_verified"])
        self.assertFalse(r["official_result_authenticated"])

    def test_cli_writes_boolean_only_without_leaking_input_secrets(self):
        with tempfile.TemporaryDirectory() as t:
            output = Path(t, "output")
            output.write_text("", encoding="utf8")
            env = {key:f"private-sentinel-{i}" for i,key in enumerate(REQUIRED)}
            env["GITHUB_OUTPUT"] = str(output)
            buffer = io.StringIO()
            with patch.dict(os.environ,env,clear=True), redirect_stdout(buffer):
                self.assertEqual(run_guard(),0)
            self.assertEqual(output.read_text(encoding="utf8"),"eligible=true\n")
            self.assertTrue(json.loads(buffer.getvalue())["eligible_to_attempt_existing_owner_admission"])
            for secret in env.values():
                if secret == str(output):
                    continue
                self.assertNotIn(secret,buffer.getvalue())
                self.assertNotIn(secret,output.read_text())
            with patch.dict(os.environ,{"GITHUB_OUTPUT":str(output)},clear=True),redirect_stdout(buffer):
                self.assertEqual(run_guard(),0)
            self.assertEqual(output.read_text(), "eligible=true\neligible=false\n")

    def test_schedule_is_five_minute_cadence_and_production_gated(self):
        flow = (Path(__file__).resolve().parents[1]/
                ".github/workflows/keirin-pr71-owner-autonomous.yml").read_text()
        regular = "'3,33 * * * *'"
        extra = "'8,13,18,23,28,38,43,48,53,58 * * * *'"
        self.assertIn(regular,flow)
        self.assertIn(extra,flow)
        minutes={3,33,8,13,18,23,28,38,43,48,53,58}
        self.assertEqual(minutes, set(range(3,60,5)))
        self.assertIn("needs: config_readiness",flow)
        self.assertIn("needs.config_readiness.outputs.eligible == 'true'",flow)
        self.assertIn("github.ref == 'refs/heads/main'",flow)
        self.assertIn("github.event.schedule == '3,33 * * * *'",flow)
        self.assertIn("race_ai/live_15min_proof.py",flow)
        self.assertIn("independent-cloud-readback:",flow)


if __name__ == "__main__":
    main()
