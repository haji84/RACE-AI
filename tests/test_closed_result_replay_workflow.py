"""Closed-result replay uses retained data without weakening the forecast route."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from tests.test_five_gate_saved_view_workflow import admits, REF, SUBJECT, RETENTION_SUBJECT


ROOT = Path(__file__).resolve().parents[1]
RECONCILE = 'saved-view: forecasts-first reconcile-closed verified saved results'
VERIFY_CURRENT = 'saved-view: forecasts-first verify-current saved site only'
ORDINARY = 'saved-view: forecasts-first current forecast display'
CANONICAL = 'refs/heads/feat/four-sport-forecast-audit-view-20261022'
INITIALIZE = 'Initialize encrypted display feed'
OWNER = 'Verify the actual private owner site without the local workspace'


class ClosedResultReplayWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text(),
                                  Loader=yaml.BaseLoader)
        self.steps = self.workflow['jobs']['saved_view_publication']['steps']

    def step(self, name):
        return next(step for step in self.steps if step.get('name') == name)

    def shell(self, name, *, subject=RECONCILE, ref=REF, overrides=None, missing=()):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); binary = folder/'bin'; binary.mkdir(); log = folder/'calls'
            (binary/'git').write_text('#!/bin/sh\nprintf "%s\\n" "$SUBJECT"\n')
            for tool in ('python', 'node'):
                (binary/tool).write_text('#!'+sys.executable+'\n'
                    'import json,os,sys\n'
                    'tool=os.path.basename(sys.argv[0])\n'
                    'with open(os.environ["LOG"],"a") as stream:stream.write(json.dumps(dict(tool=tool,args=sys.argv[1:]))+"\\n")\n'
                    'if tool=="node" and any(k in os.environ for k in ("RACE_AI_STATE_KEY","GH_TOKEN","GITHUB_TOKEN")):raise SystemExit(99)\n'
                    'if sys.argv[1:2]==["-c"]:print("2026-11-07")\n'
                    'module=sys.argv[2] if tool=="python" and sys.argv[1:2]==["-m"] else tool\n'
                    'raise SystemExit(2 if os.environ.get("FAIL_MODULE")==module else 0)\n')
            for file in binary.iterdir(): file.chmod(0o700)
            env = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], LOG=str(log),
                SUBJECT=subject, GITHUB_REF=ref, GITHUB_EVENT_NAME='push', GITHUB_ACTOR_ID='173585154',
                GITHUB_REPOSITORY_ID='1416489937', FORECAST_DISPLAY_RUN_ID='42411771346',
                FORECAST_DISPLAY_DAY='2026-11-08', RUNNER_TEMP=temporary,
                RACE_AI_STATE_KEY='PUBLIC_TEST_SENTINEL', GH_TOKEN='PUBLIC_TEST_TOKEN', GITHUB_TOKEN='PUBLIC_TEST_TOKEN')
            env.update(overrides or {})
            for key in missing: env.pop(key, None)
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', self.step(name)['run']],
                                    env=env, capture_output=True, text=True, timeout=10)
            calls = [json.loads(line.replace(temporary, '<TEMP>')) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_reconcile_uses_only_fixed_vault_config_and_preserves_four_old_initialization_modes(self):
        cases = [(RECONCILE, REF, ['-m', 'scripts.boat_saved_view_feed', '--replay-vault-config',
                    'audit/state/boat-closed-result-replay-input.json', '--day', '2026-11-08']),
                 (ORDINARY, REF, ['-m', 'scripts.boat_saved_view_feed', '--forecasts-only',
                    '--hydrate-originals', '--day', '2026-11-08', '--recover-model-run', '42411771346']),
                 (VERIFY_CURRENT, REF, None),
                 (SUBJECT, REF, None), (RETENTION_SUBJECT, REF, None),
                 ('saved-view: publish', CANONICAL, ['-m', 'scripts.boat_saved_view_feed', '--seed-only'])]
        for subject, ref, expected in cases:
            with self.subTest(subject=subject, ref=ref):
                result, calls = self.shell(INITIALIZE, subject=subject, ref=ref)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [] if expected is None else [dict(tool='python', args=expected)])

    def test_verify_current_readiness_is_count_only_and_requires_the_existing_guards(self):
        result, calls = self.shell(INITIALIZE, subject=VERIFY_CURRENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(result.stdout),
            dict(status='CURRENT_SAVED_SITE_VERIFICATION_READY', official_source_requests=0))
        for changes in ({'GITHUB_ACTOR_ID':'1'}, {'GITHUB_REPOSITORY_ID':'1'},
                        {'GITHUB_EVENT_NAME':'workflow_dispatch'}, {'SUBJECT':'saved-view: unknown'}, {'SUBJECT':''}):
            with self.subTest(changes=changes):
                result, calls = self.shell(INITIALIZE, subject=VERIFY_CURRENT, overrides=changes)
                self.assertEqual(result.returncode, 2); self.assertEqual(calls, [])
        for key in ('GITHUB_ACTOR_ID', 'GITHUB_REPOSITORY_ID', 'GITHUB_EVENT_NAME'):
            with self.subTest(missing=key):
                result, calls = self.shell(INITIALIZE, subject=VERIFY_CURRENT, missing=(key,))
                self.assertEqual(result.returncode, 2); self.assertEqual(calls, [])

    def test_missing_or_wrong_owner_event_repository_and_unknown_subject_stop_before_the_adapter(self):
        for changes in ({'GITHUB_ACTOR_ID':'1'}, {'GITHUB_REPOSITORY_ID':'1'},
                        {'GITHUB_EVENT_NAME':'workflow_dispatch'}, {'SUBJECT':'saved-view: unknown'}, {'SUBJECT':''}):
            with self.subTest(changes=changes):
                result, calls = self.shell(INITIALIZE, overrides=changes)
                self.assertEqual(result.returncode, 2); self.assertEqual(calls, [])
        for key in ('GITHUB_ACTOR_ID', 'GITHUB_REPOSITORY_ID', 'GITHUB_EVENT_NAME'):
            with self.subTest(missing=key):
                result, calls = self.shell(INITIALIZE, missing=(key,))
                self.assertEqual(result.returncode, 2); self.assertEqual(calls, [])
        for ref in (CANONICAL, 'refs/heads/unrelated', ''):
            with self.subTest(other_ref=ref):
                result, calls = self.shell(INITIALIZE, ref=ref)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [dict(tool='python', args=['-m','scripts.boat_saved_view_feed','--seed-only'])])

    def test_reconcile_skips_writers_results_and_models_and_keeps_the_existing_browser_timeout(self):
        allowed = {'Exact reviewed display publisher', 'Pinned official parser for retained result bytes',
            'Install pinned encrypted display dependencies', INITIALIZE, 'Install the existing pinned browser checker',
            OWNER, 'Require verified site display and unchanged frozen settlement'}
        for subject in (RECONCILE, VERIFY_CURRENT):
            with self.subTest(subject=subject):
                active = {step['name'] for step in self.steps if 'if' not in step or admits(step['if'], subject=subject)}
                self.assertEqual(active, allowed)
                self.assertEqual(admits(self.step(OWNER)['timeout-minutes'], subject=subject), 4)

    def test_current_result_day_and_four_old_verification_modes_keep_their_distinct_clocks(self):
        cases = [(RECONCILE, REF, ['--day','2026-11-08'], 2),
                 (VERIFY_CURRENT, REF, ['--day','2026-11-08'], 2),
                 (ORDINARY, REF, ['--require-future'], 2),
                 (SUBJECT, REF, ['--day','2026-11-07'], 4),
                 (RETENTION_SUBJECT, REF, None, 1),
                 ('saved-view: publish', CANONICAL, ['--day','2026-11-07'], 2)]
        for subject, ref, dates, count in cases:
            with self.subTest(subject=subject, ref=ref):
                result, calls = self.shell(OWNER, subject=subject, ref=ref)
                self.assertEqual(result.returncode, 0, result.stderr)
                operations = [call for call in calls if call['args'][:1] != ['-c']]
                self.assertEqual(len(operations), count)
                contexts = [call['args'] for call in operations if call['args'][:2] == ['-m','scripts.boat_saved_site_context']]
                self.assertEqual(contexts, [] if dates is None else [['-m','scripts.boat_saved_site_context', *dates,
                    '--output','<TEMP>/boat-saved-site-context.json']])
                if subject in (RECONCILE, VERIFY_CURRENT):
                    self.assertEqual(operations[-1]['tool'], 'node')
                    self.assertEqual(operations[-1]['args'][-2:], ['--compact-results','--check-current-day'])

    def test_source_job_stays_excluded_for_every_subject_on_the_owned_ref(self):
        expression = self.workflow['jobs']['official_national']['if']
        for subject in (RECONCILE, VERIFY_CURRENT, ORDINARY, SUBJECT, RETENTION_SUBJECT, 'chore: unrelated', ''):
            with self.subTest(subject=subject): self.assertFalse(admits(expression, subject=subject))

    def test_adapter_and_browser_holds_propagate_to_the_existing_final_gate(self):
        result, _ = self.shell(INITIALIZE, overrides={'FAIL_MODULE':'scripts.boat_saved_view_feed'})
        self.assertEqual(result.returncode, 2)
        for subject in (RECONCILE, VERIFY_CURRENT):
            result, _ = self.shell(OWNER, subject=subject, overrides={'FAIL_MODULE':'node'})
            self.assertEqual(result.returncode, 2)
        for outcome in ('failure', 'skipped', 'cancelled', ''):
            result, calls = self.shell('Require verified site display and unchanged frozen settlement',
                                      overrides={'SITE_CHECK_OUTCOME':outcome})
            self.assertEqual(result.returncode, 2); self.assertEqual(calls, [])


if __name__ == '__main__': unittest.main()
