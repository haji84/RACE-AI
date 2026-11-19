"""Invented acquisition counts only; never contact a provider or run a model."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import keirin_cloud_owner_inputs as owner


ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / '.github/workflows/keirin-pr71-owner-autonomous.yml'


def observed():
    return dict(state='OFFICIAL_SP_PARTIAL_INPUT_CAPTURED',
        calendar_meetings_observed=3, calendar_venue_headers_observed=2,
        day_venue_count=1, day_race_count=3, race_lists_verified=1,
        details_verified=2, riders_verified=14, future_detail_count=1,
        expired_detail_count=1, http_status_counts={'200': 30},
        navigation_request_count=5, resource_request_count=25,
        unknown_transmitted_status_count=0, blocked_before_send=0,
        provider_denied=False,
        provider_denial_http_status_counts={'HTTP_403': 0, 'HTTP_429': 0, 'UNKNOWN': 0},
        budget_exhausted=False, private_source_files_saved=6,
        source_admission=False, model_input_admission=False,
        new_forecasts=0, winticket_requests=0)


def structural_lines(text):
    output, block = [], None
    for line in text.splitlines():
        if not line.strip():
            continue
        indentation = len(line) - len(line.lstrip())
        if block is not None and indentation > block:
            continue
        block = None
        found = re.fullmatch(r'(\s*)run:\s*(.*)', line)
        if found:
            output.append(found[1] + 'run: <EXISTING_RUN_BODY>')
            if found[2].startswith(('|', '>')):
                block = len(found[1])
        else:
            output.append(line)
    return '\n'.join(output) + '\n'


class OfficialConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Path(self.temp.name)
        self.inbox.chmod(0o700)
        self.calls = []

    def invoke(self, report=None, **changes):
        self.assertIn('official_capture', inspect.signature(owner.collect_owner_inputs).parameters,
                      'OFFICIAL_SOURCE_CONNECTION_MISSING')
        def capture(inbox, **kwargs):
            self.calls.append((inbox, kwargs))
            return observed() if report is None else report
        return owner.collect_owner_inputs(self.inbox, owner_auto_confirmed=True,
            official_capture=capture, clock=lambda: datetime(2030, 1, 15, tzinfo=timezone.utc),
            monotonic=lambda: 0, **changes)

    def test_default_uses_official_counts_without_legacy_or_model_promotion(self):
        result = self.invoke()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result['source_provider'], 'KEIRIN_JP_PUBLIC_SP')
        self.assertEqual(result['source_day_schedule_race_count'], 3)
        self.assertEqual(result['public_page_requests'], 30)
        self.assertEqual(result['official_sp_acquisition']['riders_verified'], 14)
        self.assertEqual(result['new_pre_race_inputs'], 0)
        self.assertIs(result['actual_four_model_forecast_saved'], False)
        self.assertFalse((self.inbox / 'pre').exists())
        self.assertFalse((self.inbox / 'winticket_racecard_partial').exists())

    def test_unknown_private_fields_never_leave_the_mapper(self):
        report = observed()
        report.update(private_rider_name='private invented rider', cookie='private invented cookie',
                      source_url='https://private.invalid/secret')
        result = json.dumps(self.invoke(report))
        self.assertNotIn('private invented', result)
        self.assertNotIn('private.invalid', result)

    def test_invalid_model_or_winticket_claims_are_rejected_without_fallback(self):
        for change in ({'source_admission': True}, {'model_input_admission': True},
                       {'new_forecasts': 1}, {'winticket_requests': 1},
                       {'day_race_count': False}, {'details_verified': -1},
                       {'provider_denied': 'false'}, {'provider_denied': True},
                       {'budget_exhausted': True},
                       {'http_status_counts': {'200': 29, '403': 1}}):
            with self.subTest(change=change):
                result = self.invoke(dict(observed(), **change))
                self.assertTrue(result['source_capture_held'])
                self.assertEqual(result['new_pre_race_inputs'], 0)
                self.assertIsNone(result['public_page_requests'])
                self.assertIsNone(result['official_sp_acquisition']['winticket_requests'])

    def test_provider_denial_remains_visible_and_no_legacy_retry_occurs(self):
        report = observed()
        report.update(state='HOLD_OFFICIAL_SP_DENIED', provider_denied=True,
                      http_status_counts={'200': 29, '403': 1},
                      provider_denial_http_status_counts={'HTTP_403': 1, 'HTTP_429': 0, 'UNKNOWN': 0})
        result = self.invoke(report)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(result['source_capture_held'])
        self.assertTrue(result['provider_denial_stopped_requests'])
        self.assertEqual(result['provider_denial_http_status_counts']['HTTP_403'], 1)

    def test_unknown_and_partial_denominators_are_preserved(self):
        report = observed()
        report.update(state='HOLD_OFFICIAL_SP_BUDGET', day_venue_count=None,
                      day_race_count=None, budget_exhausted=True,
                      http_status_counts={'200': 29}, unknown_transmitted_status_count=1)
        result = self.invoke(report)
        self.assertIsNone(result['source_day_schedule_race_count'])
        self.assertEqual(result['official_sp_acquisition']['details_verified'], 2)
        self.assertEqual(result['official_sp_acquisition']['unknown_transmitted_status_count'], 1)
        self.assertTrue(result['work_budget_exhausted'])

    def test_no_owner_authorization_means_no_official_call(self):
        self.assertIn('official_capture', inspect.signature(owner.collect_owner_inputs).parameters,
                      'OFFICIAL_SOURCE_CONNECTION_MISSING')
        with self.assertRaises(ValueError):
            owner.collect_owner_inputs(self.inbox, owner_auto_confirmed=False,
                official_capture=lambda *a, **k: self.fail('UNEXPECTED_SOURCE_CALL'))

    def test_runtime_error_is_fixed_hold_without_exception_values_or_retry(self):
        self.assertIn('official_capture', inspect.signature(owner.collect_owner_inputs).parameters,
                      'OFFICIAL_SOURCE_CONNECTION_MISSING')
        def unavailable(*args, **kwargs):
            raise RuntimeError('private invented error must never be logged')
        result = owner.collect_owner_inputs(self.inbox, owner_auto_confirmed=True,
                                           official_capture=unavailable)
        self.assertTrue(result['source_capture_held'])
        self.assertNotIn('private invented', json.dumps(result))
        self.assertIsNone(result['public_page_requests'])

    def test_selected_existing_ab_runtime_stops_before_official_capture(self):
        selected = dict(RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED='true',
            RACE_AI_AB_PUBLIC_CAPTURE_ENABLED='true',
            RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true', RACE_AI_AB_SOURCE_S3_PREFIX='')
        with patch.dict('os.environ', selected, clear=True):
            result = self.invoke()
        self.assertEqual(self.calls, [])
        self.assertEqual(result['new_pre_race_inputs'], 0)
        self.assertTrue(result['source_capture_held'])

    def test_existing_model_queue_rejects_before_any_official_capture(self):
        (self.inbox / 'pre').mkdir()
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual(self.calls, [])

    def test_actual_browser_driver_report_reaches_the_existing_owner_cycle(self):
        from race_ai.keirin_official_sp_browser import collect_official_sp
        from tests.test_keirin_official_sp_browser import Browser
        browser = Browser(venues=(98,))
        def capture(inbox, **kwargs):
            return collect_official_sp(inbox, browser_factory=lambda: browser, **kwargs)
        result = owner.collect_owner_inputs(self.inbox, owner_auto_confirmed=True,
            official_capture=capture, clock=lambda: datetime(2030, 1, 15, 2, tzinfo=timezone.utc),
            monotonic=lambda: 0)
        self.assertIs(result['source_capture_held'], False)
        self.assertEqual(result['source_day_schedule_race_count'], 3)
        self.assertEqual(result['official_sp_acquisition']['riders_verified'], 21)
        self.assertEqual(result['public_page_requests'], len(browser.sent))

    def test_actual_driver_denial_is_preserved_by_the_existing_owner_cycle(self):
        from race_ai.keirin_official_sp_browser import collect_official_sp
        from tests.test_keirin_official_sp_browser import Browser
        browser = Browser(venues=(98,)); browser.calendar_status = 403
        def capture(inbox, **kwargs):
            return collect_official_sp(inbox, browser_factory=lambda: browser, **kwargs)
        result = owner.collect_owner_inputs(self.inbox, owner_auto_confirmed=True,
            official_capture=capture, clock=lambda: datetime(2030, 1, 15, 2, tzinfo=timezone.utc),
            monotonic=lambda: 0)
        self.assertTrue(result['source_capture_held'])
        self.assertIs(result['provider_denial_stopped_requests'], True)
        self.assertEqual(result['provider_denial_http_status_counts']['HTTP_403'], 1)
        self.assertEqual(result['public_page_requests'], 1)


class OfficialWorkflowTests(unittest.TestCase):
    def test_workflow_definitions_match_reviewed_structure_outside_run_bodies(self):
        # Includes the reviewed SP module/test path filters; job definitions,
        # permissions, schedules, source pins and conditions stay protected.
        digest = sha256(structural_lines(FLOW.read_text()).encode()).hexdigest()
        self.assertEqual(digest, 'd299faba9e01923fd7f8b2c0563c4001fee7da97c9f78acbfae1f188a75ca255')

    def test_real_consumers_reuse_browser_version_in_existing_run_steps(self):
        content = FLOW.read_text()
        source = content.split('      - name: Main-only owner-approved real source connection', 1)[1].split('\n  manual71-', 1)[0]
        runtime = content.split('\n  github-hosted-pr71-cycle:', 1)[1].split('\n  independent-cloud-readback:', 1)[0]
        for part in (source, runtime):
            self.assertIn('playwright==1.56.0', part)
            self.assertIn('python -m playwright install --with-deps chromium', part)
        self.assertLess(runtime.index('NO_PRIVATE_AES_KEY_HOLD'), runtime.index('playwright==1.56.0'))

    def test_public_preflight_does_not_repeat_the_denied_winticket_probe(self):
        content = FLOW.read_text().split('\n  public-preflight:', 1)[1].split('\n  config_readiness:', 1)[0]
        self.assertNotIn('python -m scripts.keirin_next_published_race_probe', content)
        self.assertIn('HOLD_WINTICKET_SOURCE_UNCHANGED_OFFICIAL_OWNER_PATH_SEPARATE', content)
        self.assertIn('keirin_source_gap_plan.py', content)


class PinnedNamespaceTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv('RACE_AI_PR71_PINNED_SOURCE_ROOT'),
                         'Pinned-source fixture is provided by existing CI')
    def test_new_input_readers_do_not_shadow_pinned_forecast_models(self):
        source = Path(os.environ['RACE_AI_PR71_PINNED_SOURCE_ROOT']).resolve()
        program = '''
import json
from pathlib import Path
import race_ai
from race_ai import keirin_pr71_four_model_rank as models
from race_ai import four_sport_model_suite as suite
from scripts import keirin_cloud_owner_inputs as owner
before = [str(Path(m.__file__).resolve()) for m in (models,suite)]
collector = owner._official_collector()
from race_ai import keirin_official_sp_browser as browser
from race_ai import keirin_official_sp_receipt as receipt
from race_ai import keirin_official_schedule as calendar
after = [str(Path(m.__file__).resolve()) for m in (models,suite)]
print(json.dumps(dict(before=before,after=after,
    readers=[str(Path(m.__file__).resolve()) for m in (browser,receipt,calendar)],
    owner=str(Path(owner.__file__).resolve()),callable=callable(collector))))
'''
        env = {k: v for k, v in os.environ.items() if not k.startswith(('RACE_AI_', 'GITHUB_', 'GH_'))}
        env['PYTHONPATH'] = str(source) + os.pathsep + str(ROOT)
        result = subprocess.run([sys.executable, '-c', program], cwd=source, env=env,
                                capture_output=True, timeout=20)
        self.assertTrue(result.returncode == 0, 'PINNED_NAMESPACE_IMPORT_FAILED')
        data = json.loads(result.stdout)
        self.assertTrue(data['callable'])
        self.assertEqual(data['before'], data['after'])
        self.assertTrue(all(Path(p).is_relative_to(source) for p in data['after']))
        self.assertTrue(all(Path(p).is_relative_to(ROOT) for p in data['readers']))
        self.assertEqual(Path(data['owner']), ROOT / 'scripts/keirin_cloud_owner_inputs.py')


if __name__ == '__main__':
    unittest.main()
