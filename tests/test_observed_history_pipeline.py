"""Offline parent-receipt flow into future inputs; no provider calls."""
from datetime import datetime,timezone
import hashlib,io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from race_ai import cycle_recovery as recovery
from scripts import github_existing_cycle as runner
from tests.test_frozen_day_cycle import sample,observation
from race_ai.frozen_day_cycle import read_p0

NOW=datetime(2030,4,1,3,tzinfo=timezone.utc)

def history_archive():
    _,p0,meta=sample();_,rows=read_p0(p0,meta,expected_day='2030-04-01')
    obs=observation(rows[0]);stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('official-result-observations.json',json.dumps([obs]))
    raw=stream.getvalue()
    receipt=dict(id=8,name='race-existing-cycle-2',expired=False,created_at='2030-04-01T02:15:00Z',
                 digest='sha256:'+hashlib.sha256(raw).hexdigest(),workflow_run=dict(id=2,head_repository_id=1416489937))
    return raw,receipt,obs,p0,meta

class ObservedHistoryPipelineTests(unittest.TestCase):
    def test_recovery_retains_history_before_any_fitted_model_exists(self):
        raw,receipt,obs,p0,p0meta=history_archive()
        run=dict(id=2,created_at='2030-04-01T00:00:00Z',head_branch=recovery.BRANCH,event='push',status='completed')
        def get(path):
            if path.startswith('actions/workflows/'):return json.dumps({'workflow_runs':[run]}).encode()
            if path.startswith('actions/runs/2/artifacts'):return json.dumps(dict(total_count=2,artifacts=[receipt,p0meta])).encode()
            if path=='actions/artifacts/8':return json.dumps(receipt).encode()
            if path=='actions/artifacts/8/zip':return raw
            if path=='actions/artifacts/1':return json.dumps(p0meta).encode()
            if path=='actions/artifacts/1/zip':return p0
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            restored=recovery.recover(get,'2030-04-01',current_run=3,out=Path(tmp),clock=lambda:NOW)
        self.assertIsNone(restored['learning_context'])
        self.assertEqual(restored['history_context']['observations'],[obs])
        self.assertEqual(restored['history_context']['receipt']['id'],8)
        self.assertEqual(restored['history_context']['verified_at'],NOW.isoformat())
        self.assertIn('8',restored['history_proofs'])
        self.assertEqual(restored['history_proofs']['8']['digest'],receipt['digest'])

    def test_forecast_supplies_history_without_extra_fetch_or_old_input_replay(self):
        from scripts import boat_nationwide_ab_pilot as pilot
        context={'sentinel':'already-authenticated-parent-context'}
        state=dict(index_entries=[],learning_context=None,history_context=context,schedule_cache=None)
        def run(**kwargs):
            self.assertEqual(pilot.OBSERVED_HISTORY_CONTEXT,context)
            return {'observed_pairwise_p1_bundles':[]}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);index=folder/'index.json';index.write_text('{"entries":[]}')
            (folder/'cycle_recovery_output').mkdir()
            with patch.object(runner,'ROOT',folder),patch.object(runner,'load_state',return_value=state), \
                 patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',folder), \
                 patch.object(pilot,'OBSERVED_HISTORY_CONTEXT',None,create=True), \
                 patch.object(pilot,'run',side_effect=run), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('unexpected source GET')):
                runner.forecast('2030-04-01')
                self.assertEqual(json.loads((folder/'national.json').read_text())['learned_pairwise_shadows'],[])

    def test_document_history_evidence_requires_independent_parent_membership(self):
        document={'observed_pairwise_p1_bundles':[{'history_evidence':{'id':'untrusted-embedded-copy'}}]}
        with patch('race_ai.observed_result_history.validate_history_proofs',side_effect=ValueError('parent mismatch')):
            with self.assertRaisesRegex(ValueError,'parent mismatch'):
                recovery.validate_document_history(document,{})
        recovery.validate_document_history({'observed_pairwise_p1_bundles':[{'suite':{}}]}, {})
