"""The only production BOAT backfill is an authenticated, source-free archive replay."""
from pathlib import Path
import unittest

W=Path(__file__).resolve().parents[1]/'.github/workflows/boat-owner-model-original-recovery.yml'
SOURCE='0da3f00b0f5c5115f956658d306ddcb9833ec7af'


class OriginalRecoveryGuardTests(unittest.TestCase):
    def test_only_authenticated_production_owner_run_or_allowlisted_one_shot(self):
        s=W.read_text()
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'",s)
        self.assertIn("github.event.workflow_run.head_sha == '"+SOURCE+"'",s)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository",s)
        self.assertIn("github.event.workflow_run.head_branch == 'production/boat-p0-p1-20261111'",s)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'",s)
        self.assertIn("startsWith(github.event.head_commit.message,",s)
        self.assertIn("'boat-original-recovery: sourcefree-43348227701'",s)
        self.assertIn("group: boat-racer-daily-statistics",s)

    def test_recovery_uses_originals_not_prediction_regeneration_or_provider_get(self):
        s=W.read_text()
        original=s.split('  recover_original:',1)[1].split('  independent_saved_readback:',1)[0]
        self.assertIn("--hydrate-originals --recover-model-run",original)
        self.assertIn('RACE_AI_ORIGINAL_VAULT_ENABLED:',original)
        self.assertIn("SAVED_MODEL_ARCHIVES_REPLAYED",original)
        self.assertIn("ENCRYPTED_VIEW_PUBLISHED",original)
        self.assertIn("new_source_requests=0",original)
        self.assertIn("no_actual_forecast_rewrites=True",original)
        for forbidden in ("www.boatrace.jp","requests.get","httpx.get",
                          "--sync-results","bootstrap-current","generate-forecasts",
                          "gh workflow run","--initialize"):
            self.assertNotIn(forbidden,original)
        self.assertNotIn("continue-on-error: true",original)

    def test_independent_readback_never_claims_national_total_from_p0_sample(self):
        s=W.read_text()
        check=s.split("  independent_saved_readback:",1)[1]
        for marker in ("physical_first_p0_scope=136",
                       "HOLD_NO_NEW_EVENT_DAY_SAVED",
                       "P0_P1_MODEL_COVERAGE_HOLD",
                       "FIRST_P0_SCOPE_BOTH_STAGES_PRESENT_SCHEDULE_SCOPE_UNVERIFIED",
                       "stage_covered_races","original_view_cipher_readback=True"):
            self.assertIn(marker,check)
        self.assertIn("F.current_view(bridge.git,bridge.bootstrap,day=target)",check)
        self.assertIn("cipher==expected",check)
        self.assertNotIn("www.boatrace.jp",check)


if __name__=="__main__":
    unittest.main()
