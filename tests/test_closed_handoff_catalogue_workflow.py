"""The existing handoff step retains its closed catalogue before mirroring."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
NAME = 'Mirror the previous completed worker without exposing its private payload'


class ClosedHandoffCatalogueWorkflowTests(unittest.TestCase):
    def setUp(self):
        workflow = yaml.load((ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text(),
                             Loader=yaml.BaseLoader)
        self.job = workflow['jobs']['official_national']
        self.steps = self.job['steps']
        self.step = next(step for step in self.steps if step.get('name') == NAME)

    def execute(self, *, fail_backfill=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); calls = root/'calls'
            binary = root/'python'
            binary.write_text('#!'+sys.executable+'\n'
                'import json,os,sys\n'
                'with open(os.environ["CALLS"],"a") as output:output.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'raise SystemExit(2 if os.environ["FAIL_BACKFILL"]=="true" and sys.argv[2]=="scripts.boat_original_maintenance" else 0)\n')
            binary.chmod(0o700)
            script = self.step['run'].replace('${{ runner.temp }}', temporary)
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script],
                env=dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'], CALLS=str(calls),
                         FAIL_BACKFILL=str(fail_backfill).lower()),
                capture_output=True, text=True, timeout=10)
            commands = [json.loads(line.replace(temporary, '<TEMP>'))
                        for line in calls.read_text().splitlines()] if calls.exists() else []
            return result, commands

    def test_authenticated_default_discovery_precedes_unchanged_mirror_with_private_outputs(self):
        result, commands = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, [
            ['-m', 'scripts.boat_original_maintenance', 'backfill', '--repo-root', '.',
             '--output', '<TEMP>/boat-original-before-handoff.json'],
            ['-m', 'scripts.boat_source_control_mirror', 'latest-closed', '--repo-root', '.',
             '--output', '<TEMP>/boat-source-control-previous.json']])
        self.assertEqual(result.stdout, '')

    def test_failed_backfill_stops_the_mirror_without_swallowing_the_step_failure(self):
        result, commands = self.execute(fail_backfill=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(commands, [['-m', 'scripts.boat_original_maintenance', 'backfill',
            '--repo-root', '.', '--output', '<TEMP>/boat-original-before-handoff.json']])

    def test_existing_key_token_failure_policy_and_position_precede_fresh_source(self):
        self.assertEqual(self.job['env']['RACE_AI_STATE_KEY'], '${{ secrets.RACE_AI_STATE_KEY }}')
        self.assertEqual(self.step['env'], {'GH_TOKEN': '${{ github.token }}'})
        self.assertEqual(self.step['continue-on-error'], 'true')
        self.assertEqual(set(self.step), {'name', 'continue-on-error', 'env', 'run'})
        index = self.steps.index(self.step)
        self.assertEqual([step['name'] for step in self.steps[index:index+3]], [NAME,
            'Wait without source requests for the authenticated exhibition window',
            'Initialize continuous source session and account for initial B GET'])

    def test_real_backfill_owner_guard_stops_before_view_source_or_report_creation(self):
        from scripts import boat_original_maintenance as maintenance
        attempts = []
        def forbidden(*args, **kwargs):
            attempts.append('unexpected work')
            raise AssertionError('owner guard must precede work')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'boat-original-before-handoff.json'
            report = io.StringIO()
            with patch.dict(os.environ, {'GITHUB_ACTIONS':'true', 'GITHUB_REPOSITORY':'haji84/RACE-AI',
                            'GH_TOKEN':'public-fixture-token-no-real-access'}, clear=True), redirect_stdout(report):
                code = maintenance.main(['backfill', '--repo-root', str(ROOT), '--output', str(output)],
                    view_loader=forbidden, github_get=forbidden)
            self.assertEqual(code, 2)
            self.assertEqual(attempts, [])
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(report.getvalue())['failure_phase'], 'OWNER_CONTEXT')


if __name__ == '__main__': unittest.main()
