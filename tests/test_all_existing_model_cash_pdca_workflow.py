"""Execute the explicit workflow shell with local command fixtures only."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/forecast-audit-ui.yml'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
MANIFEST = 'audit/state/all-existing-model-cash-pdca-input.json'
MODULE = 'scripts.all_existing_model_cash_pdca'


def steps(text):
    job = text.split('  boat_pdca_production_readback:', 1)[1].split('\n  viewer_contract:', 1)[0]
    return [part for part in re.split(r'^      - name: ', job, flags=re.MULTILINE)[1:]]


def by_id(items, ident):
    return next((item for item in items if re.search(r'^        id: ' + re.escape(ident) + r'$', item, re.MULTILINE)), None)


def run_script(step):
    block = step.split('        run: ', 1)[1]
    if block.startswith('|\n'):
        return '\n'.join(line[10:] for line in block[2:].splitlines())
    return block.splitlines()[0]


class CashPDCAPipelineTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.steps = steps(self.text)

    def hook(self):
        item = by_id(self.steps, 'cash_native_pdca')
        self.assertIsNotNone(item, 'the explicit cash-native-pdca workflow hook is absent')
        return item

    def execute(self, script, subject, *, ready=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); commands = root / 'commands'; commands.mkdir()
            output = root / 'github-output'; log = root / 'calls.jsonl'
            git = commands / 'git'
            git.write_text('#!/bin/sh\n[ "$1 $2 $3" = "log -1 --format=%s" ] || exit 91\nprintf "%s\\n" "$FIXTURE_SUBJECT"\n')
            git.chmod(0o700)
            python = commands / 'python'
            python.write_text('#!' + sys.executable + '\n' +
                'import json,os,sys\nmask=os.umask(0);os.umask(mask)\n' +
                'with open(os.environ["FIXTURE_LOG"],"a") as stream:stream.write(json.dumps({"args":sys.argv[1:],"mask":mask})+"\\n")\n' +
                'with open(os.environ["GITHUB_OUTPUT"],"a") as stream:stream.write("ready="+os.environ["FIXTURE_READY"]+"\\nartifact_name=all-existing-model-cash-pdca-42-900012\\n")\n' +
                'print(json.dumps({"ready":os.environ["FIXTURE_READY"]=="true","source_requests":0}))\n')
            python.chmod(0o700)
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
                FIXTURE_SUBJECT=subject, FIXTURE_LOG=str(log), FIXTURE_READY=str(ready).lower(),
                GITHUB_OUTPUT=str(output), RUNNER_TEMP=str(root / 'private runner temp'),
                RACE_AI_STATE_KEY='PUBLIC_SYNTHETIC_FIXTURE_ONLY')
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], env=env,
                capture_output=True, text=True, check=False, timeout=10, cwd=root)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            values = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return result, calls, values, env['RUNNER_TEMP']

    def test_explicit_prefix_executes_exact_cli_and_preserves_private_path_with_spaces(self):
        item = self.hook()
        result, calls, values, temporary = self.execute(run_script(item), 'cash-native-pdca: score retained originals')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [dict(args=['-m', MODULE, '--input', MANIFEST, '--out-dir',
            temporary + '/cash-native-pdca'], mask=0o077)])
        self.assertEqual(values['requested'], 'true'); self.assertEqual(values['ready'], 'true')
        self.assertEqual(values['artifact_name'], 'all-existing-model-cash-pdca-42-900012')
        self.assertNotIn('PUBLIC_SYNTHETIC_FIXTURE_ONLY', result.stdout + result.stderr)

    def test_routine_and_other_explicit_commands_do_not_invoke_cash_scoring(self):
        script = run_script(self.hook())
        for subject in ('routine CI', 'cash-native-pdca', 'order-only-pdca: score', 'future-native: freeze',
                        'prefix cash-native-pdca: not an explicit request'):
            with self.subTest(subject=subject):
                result, calls, output, _ = self.execute(script, subject)
                self.assertEqual(result.returncode, 0); self.assertEqual(calls, []); self.assertEqual(output, {})

    def test_trusted_pr71_key_scope_and_manifest_are_required_by_existing_job(self):
        item = self.hook()
        job = self.text.split('  boat_pdca_production_readback:', 1)[1].split('    steps:', 1)[0]
        for clause in ("github.event_name == 'pull_request'", "github.repository == 'haji84/RACE-AI'",
                       'github.event.pull_request.number == 71', 'github.event.pull_request.head.repo.full_name == github.repository'):
            self.assertIn(clause, job)
        self.assertIn("if: hashFiles('" + MANIFEST + "') != ''", item)
        for line in ('GH_TOKEN: ${{ github.token }}', 'GITHUB_SHA: ${{ github.event.pull_request.head.sha }}',
                     'RACE_AI_STATE_KEY: ${{ secrets.RACE_AI_STATE_KEY }}', 'shell: bash'):
            self.assertIn(line, item)
        self.assertNotIn('continue-on-error:', item)

    def test_only_ready_cipher_root_uploads_and_actual_receipt_is_replayed(self):
        generate = self.hook(); upload = by_id(self.steps, 'cash_native_pdca_upload')
        self.assertIsNotNone(upload)
        self.assertIn("if: steps.cash_native_pdca.outputs.ready == 'true'", upload)
        self.assertIn('uses: ' + UPLOAD, upload)
        self.assertIn('name: ${{ steps.cash_native_pdca.outputs.artifact_name }}', upload)
        self.assertIn('path: ${{ runner.temp }}/cash-native-pdca/\n', upload)
        self.assertNotIn('overwrite:', upload); self.assertNotIn('env:', upload)
        self.assertIn('retention-days: 7', upload); self.assertIn('if-no-files-found: error', upload)
        readback = next((step for step in self.steps if MODULE in step and '--readback-artifact' in step), None)
        self.assertIsNotNone(readback)
        self.assertLess(self.steps.index(generate), self.steps.index(upload)); self.assertLess(self.steps.index(upload), self.steps.index(readback))
        self.assertIn("if: steps.cash_native_pdca_upload.outputs.artifact-id != ''", readback)
        for line in ('GH_TOKEN: ${{ github.token }}', 'GITHUB_SHA: ${{ github.event.pull_request.head.sha }}',
                     'RACE_AI_STATE_KEY: ${{ secrets.RACE_AI_STATE_KEY }}'):
            self.assertIn(line, readback)
        script = run_script(readback).replace('${{ steps.cash_native_pdca_upload.outputs.artifact-id }}', '9001')
        result, calls, _, temporary = self.execute(script, 'routine CI')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0]['args'], ['-m', MODULE, '--input', MANIFEST, '--out-dir',
            temporary + '/cash-native-pdca', '--readback-artifact', '9001'])

    def test_hold_stays_false_and_status_upload_is_count_only_sibling_without_key(self):
        result, calls, output, _ = self.execute(run_script(self.hook()), 'cash-native-pdca: held', ready=False)
        self.assertEqual(result.returncode, 0); self.assertEqual(len(calls), 1); self.assertEqual(output['ready'], 'false')
        status = next((step for step in self.steps if 'path: ${{ runner.temp }}/cash-native-pdca.status.json' in step), None)
        self.assertIsNotNone(status)
        self.assertIn("if: always() && steps.cash_native_pdca.outputs.requested == 'true'", status)
        self.assertIn('uses: ' + UPLOAD, status)
        self.assertNotIn('env:', status); self.assertNotIn('overwrite:', status)
        self.assertNotIn('cash-native-pdca.summary.json', status)
        self.assertNotIn('cash-native-pdca.generation.json', status)
        self.assertEqual(len([step for step in self.steps if 'cash-native-pdca' in step]), 4)


if __name__ == '__main__': unittest.main()
