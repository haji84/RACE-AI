"""Real-data acceptance reuses the existing source-free display job."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace as N
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
REF = 'refs/heads/codex/forecast-first-display-20261108'
SUBJECT = 'saved-view: forecasts-first five-gates actual acceptance'
RETENTION_SUBJECT = 'saved-view: forecasts-first five-gates retention-only diagnostic'


def admits(expression, *, subject=SUBJECT, actor='173585154', ref=REF,
           browser='success', publication='success'):
    code = expression.removeprefix('${{').removesuffix('}}').strip()
    code = re.sub(r'!(?!=)', ' not ', code).replace('&&', ' and ').replace('||', ' or ')
    github = N(repository='haji84/RACE-AI', repository_id='1416489937', actor_id=actor,
        event_name='push', ref=ref, event=N(head_commit=N(message=subject)))
    good = N(outcome='success', outputs=N(ready='false'))
    steps = N(forecast_only_publication=N(outcome=publication), saved_model_publication=good,
              browser_tooling=N(outcome=browser),
              prospective_policy=good, all_models_bootstrap=good, all_models_bootstrap_freeze=N(outputs={'artifact-id': ''}))
    return eval(code, {'__builtins__': {}}, {'github': github, 'steps': steps,
        'startsWith': lambda value, prefix: value.startswith(prefix), 'always': lambda: True, 'hashFiles': lambda _: ''})


class FiveGateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text(), Loader=yaml.BaseLoader)
        self.steps = self.workflow['jobs']['saved_view_publication']['steps']

    def named(self, name):
        return next(step for step in self.steps if step.get('name') == name)

    def test_owner_only_mode_never_starts_an_official_collector(self):
        self.assertIn(REF.removeprefix('refs/heads/'), self.workflow['on']['push']['branches'])
        display = self.workflow['jobs']['saved_view_publication']['if']
        source = self.workflow['jobs']['official_national']['if']
        self.assertTrue(admits(display)); self.assertFalse(admits(source))
        for values in (dict(actor='1'), dict(subject='chore: unrelated'), dict(subject='saved-view: other')):
            self.assertFalse(admits(display, **values)); self.assertFalse(admits(source, **values))

    def test_same_jobs_permissions_concurrency_and_source_timeout(self):
        self.assertEqual(set(self.workflow['jobs']), {'saved_view_publication', 'official_national'})
        self.assertEqual(self.workflow['permissions'], {'contents': 'write', 'actions': 'read'})
        self.assertEqual(self.workflow['jobs']['saved_view_publication']['timeout-minutes'], '20')
        self.assertEqual(self.workflow['jobs']['official_national']['timeout-minutes'], '360')
        self.assertEqual(self.workflow['concurrency']['cancel-in-progress'], 'false')

    def test_only_existing_retention_readers_browser_and_final_gate_run(self):
        allowed = {'Exact reviewed display publisher', 'Pinned official parser for retained result bytes',
            'Install pinned encrypted display dependencies', 'Initialize encrypted display feed',
            'Retain and independently restore exact saved originals without taking over the active worker',
            'Retain safe completed-worker control for the existing hourly coordinator',
            'Install the existing pinned browser checker', 'Verify the actual private owner site without the local workspace',
            'Require verified site display and unchanged frozen settlement'}
        for step in self.steps:
            if 'if' not in step or admits(step['if']):
                self.assertIn(step.get('name'), allowed)
        retention = self.named('Retain and independently restore exact saved originals without taking over the active worker')
        mirror = self.named('Retain safe completed-worker control for the existing hourly coordinator')
        self.assertTrue(admits(retention['if'])); self.assertTrue(admits(mirror['if']))
        self.assertFalse(admits(retention['if'], subject='saved-view: forecasts-first prior mode'))
        self.assertFalse(admits(mirror['if'], subject='saved-view: forecasts-first prior mode'))
        self.assertIn('--run-id 42444478902', retention['run'])
        self.assertIn('publish --run-id 42444478902', mirror['run'])

    def test_historical_money_and_full_restore_are_explicit_not_future_fallback(self):
        body = self.named('Verify the actual private owner site without the local workspace')['run']
        self.assertIn('--day 2026-11-07', body)
        self.assertIn('--saved-comparison-day 2026-11-07', body)
        self.assertIn('--daily-budgets 10000,5000', body)
        self.assertIn('--required-capture-locator audit/state/boat-retained-aa57-required-capture.json', body)
        self.assertIn('--require-future', body)
        self.assertIn('SITE_CHECK_OUTCOME', self.named('Require verified site display and unchanged frozen settlement')['run'])

    def test_current_closed_aa57_capture_is_distinct_from_ac3_replay_and_active_display(self):
        path = ROOT/'audit/state/boat-retained-aa57-required-capture.json'
        self.assertTrue(path.is_file(), 'selected closed-run capture requirement is missing')
        required = json.loads(path.read_text())
        replay = json.loads((ROOT/'audit/state/boat-closed-result-replay-input.json').read_text())
        self.assertEqual(required, dict(schema='RACE_AI_BOAT_REQUIRED_CAPTURE_V1',
            expected_capture_count=32, locator=dict(schema='RACE_AI_BOAT_PRIVATE_ORIGINAL_LOCATOR_V1',
                status='READY', kind='SOURCE_CAPTURES', artifact_id=None, repository_id='1416489937',
                ref='state/boat-private-originals', source_commit='c8a8b13ec0702b06642937fd5b0ed09f40050159',
                batch_path='state/boat-private-originals/v1/2026-11/batches/1f7bac03a8436875b136c9a9798121787653cea14ed6a3d37170d0b8058df558.json',
                batch_sha256='1f7bac03a8436875b136c9a9798121787653cea14ed6a3d37170d0b8058df558',
                entry_sha256='17b5a79529e6611daa927be1209eede089f14e146c25f0c56dee7bfb46ed702c')))
        self.assertEqual(replay['run_id'], 42439206540)
        self.assertEqual(replay['head_sha'], 'ac3f302f646fdafede90565e6b6f32560ace062f')
        self.assertEqual(replay['expected_capture_count'], 53)
        self.assertEqual(json.loads((ROOT/'audit/state/boat-retained-ac3-required-capture.json').read_text()),
            dict(schema='RACE_AI_BOAT_REQUIRED_CAPTURE_V1', locator=replay['capture_locator'], expected_capture_count=53))
        self.assertNotEqual(required['locator'], replay['capture_locator'])
        self.assertEqual(self.named('Initialize encrypted display feed')['env']['FORECAST_DISPLAY_RUN_ID'],
                         '42450915404')

    def test_verification_does_not_republish_forecasts_and_checks_owner_again(self):
        body = self.named('Initialize encrypted display feed')['run']
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); binary = folder/'bin'; binary.mkdir(); log = folder/'calls'
            for name, text in [('git', 'printf "%s\\n" "$SUBJECT"'), ('python', 'printf "%s\\n" "$*" >> "$LOG"')]:
                file = binary/name; file.write_text('#!/bin/sh\n'+text+'\n'); file.chmod(0o700)
            base = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], LOG=str(log),
                GITHUB_REF=REF, GITHUB_EVENT_NAME='push', GITHUB_ACTOR_ID='173585154',
                GITHUB_REPOSITORY_ID='1416489937', SUBJECT=SUBJECT,
                FORECAST_DISPLAY_RUN_ID='42411771346', FORECAST_DISPLAY_DAY='2026-11-08')
            run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', body], env=base, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse(log.exists(), 'acceptance-only route must not invoke the feed publisher')
            bad = dict(base, GITHUB_ACTOR_ID='1')
            run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', body], env=bad, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2); self.assertFalse(log.exists())

    def test_retention_only_runs_with_skipped_browser_and_skips_all_writers_and_browser_install(self):
        for name in ('Retain and independently restore exact saved originals without taking over the active worker',
                     'Retain safe completed-worker control for the existing hourly coordinator',
                     'Install the existing pinned browser checker'):
            self.assertFalse(admits(self.named(name)['if'], subject=RETENTION_SUBJECT, browser='skipped'))
        owner = self.named('Verify the actual private owner site without the local workspace')
        self.assertTrue(admits(owner['if'], subject=RETENTION_SUBJECT, browser='skipped'))
        self.assertFalse(admits(owner['if'], subject=SUBJECT, browser='skipped'))
        for outcome in ('failure', 'skipped', 'cancelled'):
            self.assertFalse(admits(owner['if'], subject=RETENTION_SUBJECT,
                                    browser='skipped', publication=outcome))

    def test_retention_only_shell_calls_exact_verifier_and_keeps_a_hold_failed(self):
        body = self.named('Verify the actual private owner site without the local workspace')['run']
        gate = self.named('Require verified site display and unchanged frozen settlement')['run']
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); binary = folder/'bin'; binary.mkdir(); log = folder/'calls'
            commands = [('git', 'printf "%s\\n" "$SUBJECT"'),
                ('python', 'printf "%s\\n" "$*" >> "$LOG"\nif [ "$2" = scripts.boat_retained_run_verify ]; then exit "$VERIFY_EXIT"; fi'),
                ('node', 'printf "%s\\n" NODE >> "$LOG"\nexit 99')]
            for name, text in commands:
                file = binary/name; file.write_text('#!/bin/sh\n'+text+'\n'); file.chmod(0o700)
            base = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], LOG=str(log),
                        SUBJECT=RETENTION_SUBJECT, GITHUB_REF=REF, RUNNER_TEMP=temporary)
            for code in (0, 2):
                with self.subTest(verifier_exit=code):
                    if log.exists(): log.unlink()
                    run = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', body],
                        env=dict(base, VERIFY_EXIT=str(code)), capture_output=True, text=True)
                    self.assertEqual(run.returncode, code, run.stderr)
                    self.assertEqual(log.read_text().splitlines(), [
                        '-m scripts.boat_retained_run_verify --run 42444478902 --day 2026-11-08 '
                        '--head aa57a9299340230ccd7764effb51c79edb182b5e '
                        '--required-capture-locator audit/state/boat-retained-aa57-required-capture.json '
                        '--output '+temporary+'/boat-retained-run-verification.json'])
                    final = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', gate],
                        env=dict(base, SITE_CHECK_OUTCOME='success' if code == 0 else 'failure'),
                        capture_output=True, text=True)
                    self.assertEqual(final.returncode, code, final.stderr)


if __name__ == '__main__': unittest.main()
