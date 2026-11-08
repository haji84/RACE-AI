"""Unit proof of a source-free AES Git stage; authentic provider results are NOT used."""
import unittest
from datetime import timedelta
from race_ai import model_pdca_history as H,saved_view_feed as F
from race_ai.racer_intraday import IntradayState
from race_ai.racer_result_bridge import SavedResultBridge
from race_ai.racer_intraday_handoff import load_intraday
from tests.test_racer_result_bridge import BridgeTests,saved_view
from tests.test_racer_intraday_handoff import FixtureGit
from tests.test_racer_daily import NOW
from scripts import racer_intraday_refresh as R
from race_ai.boat_pdca_github_handoff import TRANSFER_REF

class StageTests(unittest.TestCase):
    def test_staged_old_aes_score_is_restored_independently_with_no_source_GET(self):
        fixture=BridgeTests('test_confirmed_result_reaches_saved_forecast_without_intake_and_quiet_replay_is_identical')
        fixture.setUp()
        try:
            from tests.test_retained_model_pdca_audit import HistoricalModelPdcaAudit
            view=HistoricalModelPdcaAudit().capture(saved_view())
            fixture.seed(view)
            writer=FixtureGit(fixture.repo,ref=TRANSFER_REF)
            rootsha=writer.commit({'state/other-unrelated.bin':b'UNCHANGED'},None)
            writer.push(rootsha,None)
            key=bytes(range(32));now=NOW+timedelta(days=1)
            initial=load_intraday(fixture.repo,initialize=True,key=key,transport=writer,now=now)
            from race_ai.racer_intraday_handoff import save_intraday
            save_intraday(initial,catalogue_sha256='a'*64,key=key,now=now)
            bridge=SavedResultBridge(fixture.repo,now=now+timedelta(minutes=2),transport=fixture.git,bootstrap=fixture.boot)
            result=R.stage_existing_pdca_without_source(fixture.repo,now=now+timedelta(minutes=2),
                intraday_transport=writer,bridge=bridge,key=key)
            self.assertEqual(result['status'],'STAGED_NEEDS_INDEPENDENT_READBACK')
            self.assertEqual(result['source_provider_requests'],0)
            self.assertEqual(result['formally_scored_forecasts'],1)
            from scripts.verify_all_history_pdca_readback import verify_snapshot
            restored=load_intraday(fixture.repo,key=key,transport=FixtureGit(fixture.repo,ref=TRANSFER_REF),now=now+timedelta(minutes=3))
            newBridge=SavedResultBridge(fixture.repo,now=now+timedelta(minutes=3),transport=fixture.git,bootstrap=fixture.boot)
            proof=verify_snapshot(restored['state'],newBridge,now=now+timedelta(minutes=3))
            self.assertEqual(proof['formally_scored_forecasts'],1)
            self.assertGreaterEqual(proof['independent_day_readbacks'],1)
            self.assertEqual(writer.read(result['generation'] and writer.head(),'state/other-unrelated.bin',100),b'UNCHANGED')
        finally:fixture.doCleanups()

if __name__=='__main__': unittest.main()
