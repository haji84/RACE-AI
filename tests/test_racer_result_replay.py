"""Replay uses retained evidence only; no source or root-state mutation."""
from contextlib import redirect_stdout
import io,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import racer_intraday_refresh as R
from scripts import boat_private_original_vault as V


class ReplayCLITests(unittest.TestCase):
    def invoke(self,args,*,authorize=None):
        report=dict(status='RETAINED_RESULTS_REPLAYED',source_requests=0,changed_races=2,
                    original_observations_preserved=True,originals_changed=False)
        output=io.StringIO()
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(output),\
             patch.object(V,'_environment',side_effect=authorize or (lambda repo:Path(repo))) as guard,\
             patch.object(R,'replay_retained_results',return_value=report) as replay,\
             patch.object(R,'refresh',side_effect=AssertionError('source refresh forbidden')) as refresh,\
             patch.object(R,'OfficialClient',side_effect=AssertionError('source client forbidden')) as source:
            code=R.main(['--repo',folder,'--private-dir',folder+'/unused',*args])
            created=Path(folder+'/unused').exists()
        return code,output.getvalue(),guard,replay,refresh,source,created

    def test_replay_is_explicit_actions_only_and_never_routes_through_refresh(self):
        code,output,guard,replay,refresh,source,created=self.invoke(['--replay-retained-results'])
        self.assertEqual(code,0);guard.assert_called_once();replay.assert_called_once()
        refresh.assert_not_called();source.assert_not_called();self.assertFalse(created)
        self.assertEqual(json.loads(output)['source_requests'],0)

    def test_context_failure_stops_before_any_replay_or_source(self):
        code,output,guard,replay,refresh,source,created=self.invoke(['--replay-retained-results'],authorize=ValueError('ACTIONS_OWNER_CONTEXT_REQUIRED'))
        self.assertEqual(code,1);replay.assert_not_called();refresh.assert_not_called();source.assert_not_called()
        self.assertFalse(created);self.assertNotIn('#saved=',output)

    def test_replay_cannot_be_combined_with_collection_initialization_or_publication(self):
        for flag in ('--initialize','--daily-reconcile','--sync-results','--verify-public'):
            with self.subTest(flag=flag):
                code,_,guard,replay,refresh,source,created=self.invoke(['--replay-retained-results',flag])
                self.assertEqual(code,1);guard.assert_not_called();replay.assert_not_called()
                refresh.assert_not_called();source.assert_not_called();self.assertFalse(created)


if __name__=='__main__':unittest.main()
