"""Execute the existing fit step with inert tools; no source or owner key."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/forecast-audit-ui.yml'
FIT = 'Fit the explicit eight-race native research cohort from authenticated private originals'
UPLOAD = 'Keep the encrypted native research fit and count-only status'


def steps():
    job = WORKFLOW.read_text().split('  boat_pdca_production_readback:', 1)[1].split('\n  official_result_recovery_issuer:', 1)[0]
    return {part.split('\n', 1)[0]: part for part in re.split(r'^      - name: ', job, flags=re.MULTILINE)[1:]}


def script(step):
    return '\n'.join(line[10:] for line in step.split('        run: |\n', 1)[1].splitlines())


class NativeFutureSkipRefitWorkflowTests(unittest.TestCase):
    def execute_fit(self, subject, *, full=True, fail=False):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            tools = folder / 'tools'
            tools.mkdir()
            log = folder / 'calls.jsonl'
            output = folder / 'output'
            git = tools / 'git'
            git.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_SUBJECT"\n')
            git.chmod(0o700)
            python = tools / 'python'
            python.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                              'with open(os.environ["FIXTURE_LOG"],"a") as f:f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                              'sys.exit(17 if os.environ["FIXTURE_FAIL"]=="true" else 0)\n')
            python.chmod(0o700)
            manifest = folder / 'audit/state/all-existing-model-native-ci-input.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text('{}')
            if full:
                (manifest.parent / 'all-existing-model-full-native-ci-input.json').write_text('{}')
            env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'],
                       RUNNER_TEMP=str(folder / 'private temp'), GITHUB_OUTPUT=str(output),
                       FIXTURE_SUBJECT=subject, FIXTURE_LOG=str(log), FIXTURE_FAIL=str(fail).lower())
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script(steps()[FIT])],
                                    cwd=folder, env=env, capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            values = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return result, calls, values, str(folder / 'private temp')

    def upload_requested(self, values, *, manifest=True, success=True):
        upload = steps()[UPLOAD]
        self.assertIn("steps.native_research_fit.outputs.fit_executed == 'true'", upload)
        self.assertIn("hashFiles('audit/state/all-existing-model-native-ci-input.json') != ''", upload)
        return success and manifest and values.get('fit_executed') == 'true'

    def test_exact_native_compare_skips_refit_and_nonexistent_candidate_upload(self):
        result, calls, values, _ = self.execute_fit('native-p1-compare: actual pinned thirty')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertEqual(values, {})
        self.assertFalse(self.upload_requested(values))

    def test_default_source_freeze_and_order_fit_keep_existing_fit_and_upload(self):
        for subject in ('routine CI', 'official-native-freeze: source',
                        'official-source-freeze: packet', 'official-order-only-fit: thirty',
                        'native-p1-compare', 'prefix native-p1-compare: wrong',
                        'native-p1-compare-other: wrong'):
            with self.subTest(subject=subject):
                result, calls, values, runner = self.execute_fit(subject)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [['-m', 'scripts.all_existing_model_learning_ci', '--input',
                    'audit/state/all-existing-model-full-native-ci-input.json', '--restored-dir',
                    runner+'/boat-production-readback', '--out-dir', runner+'/all-native-learning']])
                self.assertTrue(self.upload_requested(values))

    def test_original_plan_fallback_and_fit_failure_remain_fail_closed(self):
        result, calls, values, _ = self.execute_fit('routine CI', full=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0][3], 'audit/state/all-existing-model-native-ci-input.json')
        self.assertTrue(self.upload_requested(values))
        result, calls, values, _ = self.execute_fit('routine CI', fail=True)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(len(calls), 1)
        self.assertEqual(values, {})
        self.assertFalse(self.upload_requested(values, success=False))
        self.assertFalse(self.upload_requested({}, manifest=False))

    def test_compare_keeps_candidate_admission_and_both_actual_receipts(self):
        items = steps()
        self.assertIn('id: native_research_fit', items[FIT])
        self.assertIn('id: native_model_candidate', items[UPLOAD])
        for name in ('Require owner key before pinned ciphertext GET and private restore',
                     'Connect frozen venue observations to existing shadow fitter or explicit HOLD',
                     'Keep owner-encrypted learning candidate and count-only status',
                     'Compare the explicitly pinned future native cohort',
                     'Independently save the encrypted native future comparison',
                     'Keep the encrypted original-source provenance for the thirty-cell path',
                     'Verify the actual native future comparison receipt'):
            self.assertNotIn('native_research_fit.outputs', items[name])
            if 'Compare the explicitly' not in name:
                self.assertNotIn('native-p1-compare:*', items[name])
        compare = items['Compare the explicitly pinned future native cohort']
        self.assertIn('python -m scripts.all_existing_model_native_future --manifest', compare)
        receipt = items['Verify the actual native future comparison receipt']
        self.assertIn('--readback-artifact', receipt)
        self.assertIn('--readback-origin-artifact', receipt)
        self.assertNotIn('continue-on-error:', receipt)


if __name__ == '__main__':
    unittest.main()
