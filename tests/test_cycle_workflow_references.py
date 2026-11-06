"""Guard the real composite round, not the obsolete inline workflow layout."""
import re
import os
import subprocess
import tempfile
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/boat-nationwide-ab-one-shot.yml'
ROUND = ROOT / '.github/actions/existing-model-round/action.yml'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'


class WorkflowReferencesTest(unittest.TestCase):
    def test_viewer_checks_out_both_real_pinned_dependencies(self):
        text = (ROOT / '.github/workflows/forecast-audit-ui.yml').read_text().split('  viewer_contract:', 1)[1]
        for ref, path in [
            ('761247bee0209e37b1af6b8885e92cad3e9260a5', 'pr64-reference'),
            ('7a432e5acc4d3495a0e82bd79726929e2f8085fe', 'pr72-reference'),
        ]:
            self.assertIn(ref, text)
            self.assertIn('path: ' + path, text)
        self.assertLess(text.index('path: pr72-reference'), text.index('python -m unittest discover'))

    def assert_round_contract(self, text):
        self.assertIn('using: composite', text)
        steps = re.split(r'^    - name: ', text, flags=re.MULTILINE)[1:]
        self.assertEqual(len(steps), 9)
        prepare, discovery, p0freeze, forecast, freeze, audit, result, complete, display = steps
        self.assertIn('id: ready', prepare)
        self.assertIn('github_existing_cycle.py repeat-prepare', prepare)
        self.assertIn('github_existing_cycle.py supplement --round', discovery)
        self.assertIn('id: discovery', discovery)
        self.assertIn('id: discovery_freeze', p0freeze)
        self.assertIn("steps.discovery.outputs.supplement_ready == 'true'", p0freeze)
        self.assertIn('path: p0_supplement_output/cycle-${{ inputs.round }}/forecasts.json', p0freeze)
        self.assertIn('steps.ready.outputs.p0_name', p0freeze)
        self.assertIn('uses: ' + UPLOAD, p0freeze)
        self.assertIn('if-no-files-found: error', p0freeze)
        self.assertNotIn('overwrite: true', p0freeze)
        self.assertIn('github_existing_cycle.py forecast', forecast)
        for step in steps[1:-1]:
            self.assertIn("if: steps.ready.outputs.active == 'true'", step)
            self.assertNotIn('continue-on-error:', step)
        for step, ident, path, name in [
            (freeze, 'freeze', 'boat_nationwide_output/national.json', 'forecast_name'),
            (result, 'result', 'existing_cycle_output/', 'result_name'),
        ]:
            self.assertIn('id: ' + ident, step)
            self.assertIn('uses: ' + UPLOAD, step)
            self.assertIn('path: ' + path, step)
            self.assertIn('steps.ready.outputs.' + name, step)
            self.assertIn('if-no-files-found: error', step)
            self.assertNotIn('overwrite: true', step)
        self.assertIn('github_existing_cycle.py audit', audit)
        self.assertIn('P0_SUPPLEMENT_ARTIFACT: ${{ steps.discovery_freeze.outputs.artifact-id }}', audit)
        self.assertIn('supplement_args+=(--p0-supplement "$P0_SUPPLEMENT_ARTIFACT")', audit)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", audit)
        self.assertIn('github_existing_cycle.py repeat-complete', complete)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", complete)
        self.assertIn("--result-artifact '${{ steps.result.outputs.artifact-id }}'", complete)
        self.assertIn('continue-on-error: true',display)
        self.assertIn('scripts.boat_saved_view_feed --result-artifact',display)
        self.assertIn('RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}',display)
        self.assertIn("if: steps.ready.outputs.active == 'true'",display)

    def test_existing_cycle_create_only_first_p0_then_reuses_original(self):
        text = WORKFLOW.read_text()
        # The existing first-receipt bootstrap now creates its metadata index;
        # recurring rounds additionally publish display-only ciphertext. Source
        # accounting starts before the missing-only supplement, not after it.
        self.assertRegex(text,r'permissions:\n  contents: write[^\n]*\n  actions: read\n')
        self.assertIn('actions: read', text)
        self.assertIn('persist-credentials: false', text)
        for marker in ('id: first_p0', 'first_p0_bootstrap.py preflight',
                       'first_p0_bootstrap.py capture', 'id: first_upload',
                       'first_p0_bootstrap.py finalize --artifact-id'):
            self.assertIn(marker, text)
        self.assertIn("if: steps.first_p0.outputs.capture != 'true'", text)
        self.assertLess(text.index('first_p0_bootstrap.py preflight'), text.index('first_p0_bootstrap.py capture'))
        self.assertLess(text.index('first_p0_bootstrap.py capture'), text.index('id: first_upload'))
        self.assertIn('first_p0_bootstrap.py capture-wait', text)
        self.assertNotIn('id: p0supplement', text)
        self.assertNotIn('run: python scripts/existing_day_program.py', text)
        self.assertIn('cancel-in-progress: false', text)
        finalize = next(step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                        if 'run: python scripts/first_p0_bootstrap.py finalize' in step)
        self.assertIn("if: steps.first_p0.outputs.capture == 'true'", finalize)
        self.assertIn('steps.first_upload.outputs.artifact-id', finalize)
        self.assertLess(text.index('id: first_upload'), text.index('first_p0_bootstrap.py finalize'))
        self.assertLess(text.index('first_p0_bootstrap.py finalize'), text.index('github_existing_cycle.py restore'))
        self.assertLess(text.index('github_existing_cycle.py restore'), text.index('github_existing_cycle.py repeat-start'))
        self.assertIn('RACE_AI_FIRST_P0_CAPTURED: ${{ steps.first_p0.outputs.capture }}', text)
        self.assertNotIn('github_existing_cycle.py supplement', text)
        workers = [step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                   if 'uses: ./.github/actions/existing-model-round' in step]
        self.assertEqual(len(workers), 24)
        for worker in workers:
            self.assertIn("if: steps.repeat_start.outputs.session_ready == 'true'", worker)
        self.assertIn('timeout-minutes: 360', text)
        self.assertIn('RACE_AI_EVENT_DAY=', text)
        self.assertIn('RACE_AI_WORKER_HANDOFF_AT=', text)
        self.assertIn('datetime.now(timezone.utc)', text)
        self.assertLess(text.index('python -m unittest'), text.index('RACE_AI_EVENT_DAY='))
        self.assertLess(text.index('RACE_AI_EVENT_DAY='), text.index('first_p0_bootstrap.py preflight'))
        self.assertIn('timedelta(minutes=330)', text)
        for name in ('Save first P0 separately', 'Read back original ZIP'):
            step = next(step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                        if step.startswith(name))
            self.assertIn("steps.first_capture.outputs.capture_complete == 'true'", step)
        self.assertIn("if: steps.restore.conclusion == 'success'", text)
        for command in ('git push', 'gh api --method PUT', 'first_p0_bootstrap.py finalize'):
            self.assertNotIn(command, ROUND.read_text())
        self.assert_round_contract(ROUND.read_text())

    def test_result_before_forecast_freeze_is_rejected(self):
        text = ROUND.read_text()
        parts = re.split(r'(?=^    - name: )', text, flags=re.MULTILINE)
        parts[5], parts[6] = parts[6], parts[5]
        with self.assertRaises(AssertionError):
            self.assert_round_contract(''.join(parts))

    def test_missing_or_wrong_receipt_and_overwrite_are_rejected(self):
        text = ROUND.read_text()
        for old, new in [
            ('id: freeze', 'id: wrong'),
            ('steps.freeze.outputs.artifact-id', 'steps.result.outputs.artifact-id'),
            ('if-no-files-found: error', 'if-no-files-found: warn'),
            ('retention-days: 7', 'retention-days: 7\n        overwrite: true'),
            ("if: steps.ready.outputs.active == 'true'", 'continue-on-error: true'),
        ]:
            with self.subTest(mutation=old), self.assertRaises(AssertionError):
                self.assert_round_contract(text.replace(old, new, 1))

    def test_optional_discovery_receipt_is_omitted_when_no_new_original_exists(self):
        audit = next(step for step in re.split(r'^    - name: ', ROUND.read_text(), flags=re.MULTILINE)
                     if 'github_existing_cycle.py audit' in step)
        script = audit.split('      run: |\n', 1)[1]
        script = '\n'.join(line[8:] for line in script.splitlines())
        script = script.replace('${{ inputs.round }}', '1').replace('${{ steps.freeze.outputs.artifact-id }}', '123')
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'python'
            executable.write_text("#!/bin/bash\n/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\"\n")
            executable.chmod(0o700)
            for receipt in ('', '456'):
                env = dict(os.environ, PATH=folder + os.pathsep + os.environ['PATH'], P0_SUPPLEMENT_ARTIFACT=receipt)
                result = subprocess.run(['bash', '-e', '-c', script], env=env, check=True,
                                        text=True, capture_output=True)
                args = json.loads(result.stdout)
                expected = ['scripts/github_existing_cycle.py', 'audit', '--round', '1', '--p1-artifact', '123']
                self.assertEqual(args, expected + (['--p0-supplement', receipt] if receipt else []))
