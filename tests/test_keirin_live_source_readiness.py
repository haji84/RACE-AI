"""No-provider unit tests for user-approved existing personal collector fallback."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch
import tempfile

from scripts.keirin_live_source_readiness import (
    assess, KEY, REQUIRED, PROVIDER_KEYS, PROFILE, main as run_guard
)


class PilotReadinessTest(TestCase):
    def test_no_key_holds_even_with_existing_owner_scope(self):
        r = assess({"RACE_AI_OWNER_AUTO_SOURCE_PROFILE": PROFILE})
        self.assertFalse(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(r["status"], "HOLD_NO_PRIVATE_AES_KEY")
        self.assertEqual(r["missing_config_names"], [KEY])
        self.assertEqual(r["provider_requests_by_readiness"], 0)

    def test_old_api_only_guard_is_not_mandatory_for_approved_owner(self):
        r = assess({KEY:"opaque-secret", "RACE_AI_OWNER_AUTO_SOURCE_PROFILE": PROFILE})
        self.assertTrue(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(r["source_mode"], "EXISTING_OWNER_PUBLIC_PAGE_RESEARCH")
        self.assertEqual(r["status"], "OWNER_APPROVED_PUBLIC_RESEARCH_CANDIDATE_COLLECTION_ONLY")
        self.assertEqual(r["missing_config_names"], [])
        self.assertEqual(r["optional_provider_config_unset_count"], 4)
        self.assertFalse(r["source_rights_verified"])
        self.assertFalse(r["complete_model_inputs_verified"])
        self.assertFalse(r["real_race_15min_proven"])
        self.assertFalse(r["official_result_authenticated"])

    def test_no_profile_and_no_provider_stays_offline(self):
        r = assess({KEY:"test"})
        self.assertEqual(r["status"], "HOLD_NO_ENABLED_OWNER_OR_PROVIDER_SOURCE")
        self.assertFalse(r["eligible_to_attempt_existing_owner_admission"])

    def test_wrong_owner_profile_does_not_authorize_provider_requests(self):
        r = assess({KEY:"test", "RACE_AI_OWNER_AUTO_SOURCE_PROFILE":"invented"})
        self.assertEqual(r["source_mode"], "NONE")
        self.assertFalse(r["eligible_to_attempt_existing_owner_admission"])

    def test_partial_provider_bundle_fail_closed_even_with_owner_profile(self):
        r = assess({KEY:"test", "RACE_AI_OWNER_AUTO_SOURCE_PROFILE":PROFILE,
                    PROVIDER_KEYS[0]:"url"})
        self.assertEqual(r["status"], "HOLD_PARTIAL_PROVIDER_CONFIG")
        self.assertFalse(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(len(r["missing_config_names"]), 3)

    def test_full_provider_bundle_does_not_claim_license(self):
        e = {k:"opaque" for k in REQUIRED}
        r = assess(e)
        self.assertTrue(r["eligible_to_attempt_existing_owner_admission"])
        self.assertEqual(r["source_mode"], "EXISTING_PROVIDER_JSON_EXPORT")
        self.assertEqual(r["status"], "PROVIDER_CONFIG_PRESENT_INDEPENDENT_ADMISSION_REQUIRED")
        self.assertFalse(r["source_rights_verified"])
        self.assertFalse(r["real_race_15min_proven"])

    def test_cli_only_writes_boolean_and_never_private_values(self):
        with tempfile.TemporaryDirectory() as t:
            output = Path(t, "output")
            output.write_text("", encoding="utf8")
            environ={KEY:"test-secret-key", "RACE_AI_OWNER_AUTO_SOURCE_PROFILE":PROFILE,
                     "GITHUB_OUTPUT":str(output)}
            text = io.StringIO()
            with patch.dict(os.environ, environ, clear=True), redirect_stdout(text):
                self.assertEqual(run_guard(), 0)
            self.assertEqual(output.read_text(encoding="utf8"),"eligible=true\n")
            self.assertTrue(json.loads(text.getvalue())["eligible_to_attempt_existing_owner_admission"])
            self.assertNotIn("test-secret-key",text.getvalue())
            self.assertNotIn("test-secret-key",output.read_text())
            with patch.dict(os.environ,{"GITHUB_OUTPUT":str(output)},clear=True),redirect_stdout(text):
                self.assertEqual(run_guard(), 0)
            self.assertEqual(output.read_text(), "eligible=true\neligible=false\n")

    def test_uses_preexisting_producer_and_owned_profile_without_new_scraper(self):
        root=Path(__file__).resolve().parents[1]
        flow=(root/".github/workflows/keirin-pr71-owner-autonomous.yml").read_text()
        cloud=(root/"scripts/keirin_cloud_pr71_state.py").read_text()
        owner=(root/"scripts/keirin_cloud_owner_inputs.py").read_text()
        self.assertIn("RACE_AI_OWNER_AUTO_SOURCE_PROFILE: owner-approved-winticket-keirinjp-20261109",flow)
        self.assertIn("needs: config_readiness",flow)
        self.assertIn("needs.config_readiness.outputs.eligible == 'true'",flow)
        self.assertIn("collect_owner_inputs(inbox,owner_auto_confirmed=True)",cloud)
        self.assertIn("if missing_source_configuration(e):",cloud)
        self.assertIn("'provider_machine_rights_independently_verified':False",owner)
        self.assertIn("'actual_four_model_forecast_saved':False",owner)
        # Main push runs only the secret-presence check, never the model cycle.
        guard=flow.split("\\n  config_readiness:\\n",1)[1].split("\\n  # Production secrets",1)[0]
        prod=flow.split("\\n  github-hosted-pr71-cycle:\\n",1)[1].split("\\n  independent-cloud-readback:\\n",1)[0]
        self.assertIn("github.event_name == 'push'",guard)
        self.assertNotIn("github.event_name == 'push'",prod)
        self.assertIn("independent-cloud-readback:",flow)
        self.assertIn("cron: '3,33 * * * *'",flow)
        self.assertIn("cron: '8,13,18,23,28,38,43,48,53,58 * * * *'",flow)


if __name__=="__main__":
    main()
