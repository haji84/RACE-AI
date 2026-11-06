"""Synthetic orchestration checks around the independently tested crypto path."""
from copy import deepcopy
from pathlib import Path
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tests.test_all_existing_model_inputs import acquired_pair
from race_ai.all_existing_model_inputs import current_requests, read_private_pending_requests


class AllModelCycleConnectionTests(unittest.TestCase):
    def baseline(self, *, fail_sink=False):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);repo=root/'repo';repo.mkdir()
        (repo/'cycle_recovery_output').mkdir();(repo/'boat_nationwide_output').mkdir()
        (repo/'audit/state').mkdir(parents=True)
        (repo/'audit/state/all-existing-model-owner-research.json').write_text('{}')
        index=repo/'index.json';index.write_text('{"entries":[]}')
        captured=[];acquired_pair(captured.append)
        expected=current_requests(captured)
        original={'observed_pairwise_p1_bundles':[], 'fixture':'unchanged',
                  'learned_pairwise_shadows':[], 'learning_failures':[],
                  'all_model_collection':{'state':'ADDITIONAL_FAMILIES_UNAVAILABLE','reason':'ALL_MODEL_RUNTIME_UNAVAILABLE_OR_REJECTED'}}
        old_sink=lambda value:None
        def primary(**kwargs):
            self.assertIsNot(pilot.NATIVE_INPUT_SINK,old_sink)
            self.assertFalse((repo/'boat_nationwide_output/national.json').exists())
            pilot.NATIVE_INPUT_SINK(deepcopy(captured[0]))
            return deepcopy(original)
        original_writer=__import__('race_ai.all_existing_model_inputs',fromlist=['write_private_pending_requests']).write_private_pending_requests
        def write_after_baseline(requests,folder):
            self.assertEqual(json.loads((repo/'boat_nationwide_output/national.json').read_text()),original)
            if fail_sink:raise ValueError('private failure')
            return original_writer(requests,folder)
        with patch.object(runner,'ROOT',repo),patch.object(runner,'load_state',return_value={'index_entries':[]}), \
             patch.object(pilot,'FROZEN_INDEX',index),patch.object(pilot,'OUTPUT',repo/'boat_nationwide_output'), \
             patch.object(pilot,'NATIVE_INPUT_SINK',old_sink),patch.object(pilot,'run',side_effect=primary), \
             patch.dict(os.environ,RUNNER_TEMP=str(root)), \
             patch('race_ai.all_existing_model_inputs.write_private_pending_requests',side_effect=write_after_baseline):
            runner.forecast('2030-04-01',round_no=2)
            self.assertIs(pilot.NATIVE_INPUT_SINK,old_sink)
        self.assertEqual(json.loads((repo/'boat_nationwide_output/national.json').read_text()),original)
        return root,expected

    def test_exact_native_inputs_written_privately_only_after_baseline(self):
        root,expected=self.baseline()
        pending=root/'all-existing-model-inputs/cycle-2'
        self.assertEqual(read_private_pending_requests(pending),expected)
        self.assertEqual((pending/'pending.json').stat().st_mode&0o777,0o600)

    def test_optional_private_handoff_failure_preserves_baseline(self):
        root,_=self.baseline(fail_sink=True)
        self.assertFalse((root/'all-existing-model-inputs/cycle-2').exists())

    def test_upload_uses_atomic_cipher_directory_without_root_summary(self):
        from scripts import github_existing_cycle as runner
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);preload=root/'preload';preload.mkdir(mode=0o700)
            runtime={'preload_folder':preload,'output_folder':root/'upload/cycle-2'}
            output=root/'github-output';output.touch()
            def generate(_runtime,_pending,staging,**kwargs):
                staging.mkdir(mode=0o700);child=staging/('a'*64);child.mkdir(mode=0o700)
                for name in ('learning.enc','learning.json','summary.json'):(child/name).write_bytes(b'cipher-fixture')
                (staging/'summary.json').write_text('{}')
                return dict(state='ENCRYPTED_PRIVATE_NATIVE_PAIRS_LOCAL_ONLY',partition_count=1,
                    pending_removed=True,encrypted_readback_verified=True)
            with patch.dict(os.environ,RUNNER_TEMP=str(root),GITHUB_OUTPUT=str(output)), \
                 patch('race_ai.all_existing_model_runtime.generate_current_pairs',side_effect=generate):
                summary=runner._all_model_research_generate(runtime,2)
            self.assertTrue(summary['encrypted_readback_verified'])
            self.assertEqual({p.name for p in runtime['output_folder'].iterdir()},{'a'*64})
            self.assertEqual(output.read_text(),'all_model_pairs=true\n')
            self.assertFalse(preload.exists())

    def test_partial_cipher_is_quarantined_and_never_uploaded(self):
        from scripts import github_existing_cycle as runner
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);preload=root/'preload';preload.mkdir(mode=0o700)
            runtime={'preload_folder':preload,'output_folder':root/'upload/cycle-2'}
            def reject(_runtime,_pending,staging,**kwargs):
                staging.mkdir(mode=0o700);(staging/'learning.enc').write_bytes(b'partial')
                raise ValueError('/private/sensitive')
            with patch.dict(os.environ,RUNNER_TEMP=str(root)), \
                 patch('race_ai.all_existing_model_runtime.generate_current_pairs',side_effect=reject):
                summary=runner._all_model_research_generate(runtime,2)
            self.assertEqual(summary['state'],'HOLD_PRIVATE_NATIVE_INPUTS')
            self.assertNotIn('/private',json.dumps(summary))
            self.assertFalse(runtime['output_folder'].exists())
            self.assertEqual(len(list((root/'boat-venue-research-quarantine').glob('*/cipher/learning.enc'))),1)


if __name__=='__main__':unittest.main()
