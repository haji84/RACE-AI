"""Retention must run on real producers before their temporary runner ends."""
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class VaultWorkflowTests(unittest.TestCase):
    def test_each_native_producer_retains_exact_github_originals(self):
        workflow=(ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text()
        rounds=(ROOT/'.github/actions/existing-model-round/action.yml').read_text()
        for artifact in ('steps.first_upload.outputs.artifact-id','steps.new_day_models_freeze.outputs.artifact-id',
                         'steps.checkpoint_upload.outputs.artifact-id','steps.source_control_upload.outputs.artifact-id'):
            self.assertTrue(any('boat_private_original_vault capture' in line and artifact in line for line in workflow.splitlines()))
        for artifact in ('steps.freeze.outputs.artifact-id','steps.all_models_freeze.outputs.artifact-id','steps.result.outputs.artifact-id'):
            self.assertTrue(any('boat_private_original_vault capture' in line and artifact in line for line in rounds.splitlines()))
        self.assertIn('boat_private_original_vault retain-captures',rounds)
        self.assertLess(rounds.index('boat_private_original_vault retain-captures'),rounds.index('github_existing_cycle.py repeat-complete'))
        self.assertIn('boat_saved_view_feed --result-artifact',rounds)
        self.assertIn('--hydrate-originals',rounds)
        # Every forecast upload must precede slow durable Git retention.
        self.assertLess(rounds.index('name: Verify private research ciphertext'),rounds.index('boat_private_original_vault capture'))
        self.assertNotIn('RACE_AI_STATE_KEY:',workflow.split('Test originals, pending results',1)[1].split('Install pinned encrypted display',1)[0])
        final=workflow.split('name: Preserve exact raw result responses',1)[1].split('      - name:',1)[0]
        self.assertIn('if: always()',final)
        self.assertIn('boat_private_original_vault retain-captures',final)
        self.assertLess(workflow.index('boat_original_maintenance backfill'),workflow.index('name: Automatically match saved results'))
        source=workflow.split('  official_national:',1)[1]
        # The seller's unchanged 07:00 gate needs genuine P0 execution before
        # waiting for the first exhibition window around 08:20.
        self.assertLess(source.index('boat_all_model_cycle bootstrap-current'),source.index('github_existing_cycle.py wait-for-window'))


if __name__=='__main__':unittest.main()
