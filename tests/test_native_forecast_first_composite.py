"""The native round publishes retained forecasts before its result audit."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
EARLY = 'Publish retained forecast originals before result work'


class NativeForecastFirstCompositeTests(unittest.TestCase):
    def setUp(self):
        action = yaml.load((ROOT / '.github/actions/existing-model-round/action.yml').read_text(),
                           Loader=yaml.BaseLoader)
        self.steps = action['runs']['steps']

    def early(self):
        matches = [step for step in self.steps if step.get('name') == EARLY]
        self.assertEqual(len(matches), 1, 'native forecast-first publication is missing or duplicated')
        return matches[0]

    def test_original_retention_and_native_proof_precede_forecast_publication_and_result_audit(self):
        early = self.early()
        positions = {step['name']: index for index, step in enumerate(self.steps)}
        for name in ('Retain exact baseline and supplemental P0 originals beyond artifact expiry',
                     'Retain exact additional model execution beyond artifact expiry',
                     'Retain explicit native carrier originals before the proof barrier',
                     'Require exact prospective native carrier readback'):
            self.assertLess(positions[name], positions[EARLY])
        self.assertLess(positions[EARLY],
                        positions['Read back original and independently check later official results'])
        self.assertEqual(early['if'], "steps.ready.outputs.active == 'true'")
        self.assertEqual(early['env'], {'RACE_AI_STATE_KEY': '${{ inputs.saved-view-key }}'})

    def run_early(self, publisher_exit):
        script = self.early()['run'].replace('${{ github.run_id }}', '42')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = root / 'calls.json'
            python = root / 'python'
            python.write_text('#!' + sys.executable + '\n'
                              'import json,os,sys\n'
                              'with open(os.environ["CALLS"],"w") as stream:json.dump(sys.argv[1:],stream)\n'
                              'raise SystemExit(int(os.environ["PUBLISHER_EXIT"]))\n')
            python.chmod(0o700)
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script],
                env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                         CALLS=str(calls), PUBLISHER_EXIT=str(publisher_exit)),
                capture_output=True, text=True, timeout=10)
            return result, json.loads(calls.read_text())

    def test_early_command_recovers_current_run_forecasts_without_a_result_artifact(self):
        result, calls = self.run_early(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['-m', 'scripts.boat_saved_view_feed', '--forecasts-only',
                                 '--hydrate-originals', '--recover-model-run', '42'])
        self.assertEqual(result.stdout, '')

    def test_display_hold_warns_without_stopping_the_existing_source_round(self):
        result, _ = self.run_early(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
            '::warning::Encrypted forecast display update held; original source collection continues.\n')


if __name__ == '__main__':
    unittest.main()
