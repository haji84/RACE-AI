"""Deterministic source-free startup waiting; invented saved P0 schedule only."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import repeated_cycle
from race_ai.boat_observed_pairwise_models import predict_pair
from scripts import github_existing_cycle as cycle
from scripts import first_p0_bootstrap as bootstrap
from tests.test_frozen_day_cycle import sample
from tests.test_boat_observed_pairwise_models import fixture

DAY = '2030-04-01'


class Clock:
    def __init__(self, now, *, jump=None):
        self.current = now
        self.sleeps = []
        self.jump = jump

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current = self.jump if self.jump is not None else self.current+timedelta(seconds=seconds)


class StartupWaitTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(cycle, 'wait_for_window'), 'source-free startup wait command is missing')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.document, raw, self.receipt = sample()
        early = fixture(research=True)
        early['as_of'] = '2030-04-01T04:10:00+09:00'
        early['sources'][0].update(published_at='2030-04-01T03:00:00+09:00',
                                   captured_at='2030-04-01T04:00:00+09:00')
        self.document['predictions'] = [predict_pair(early, allow_source=lambda *_: True)]
        self.body = json.dumps(self.document, sort_keys=True, separators=(',', ':')).encode()
        archived = io.BytesIO()
        with zipfile.ZipFile(archived, 'w') as source:
            source.writestr('forecasts.json', self.body)
        self.receipt.update(created_at='2030-04-01T04:11:00+09:00',
                            digest='sha256:'+sha256(archived.getvalue()).hexdigest())
        self.output = self.root/'step-output.txt'
        self.output.write_text('')
        self.write_restored()

    def write_restored(self, *, document=None):
        if document is not None:
            self.document = document
            self.body = (json.dumps(document, ensure_ascii=False, indent=2)+'\n').encode()
        folder = self.root/'boat_all_day_output'
        folder.mkdir(exist_ok=True)
        (folder/'forecasts.json').write_bytes(self.body)
        (folder/'first-receipt.json').write_text(json.dumps(self.receipt))
        evidence = self.root/'docs/evidence'/DAY
        evidence.mkdir(parents=True, exist_ok=True)
        index = dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1', day_jst=DAY,
                     artifact_id=self.receipt['id'], run_id=self.receipt['workflow_run']['id'],
                     server_created_at=self.receipt['created_at'], zip_sha256=self.receipt['digest'][7:],
                     json_sha256=sha256(self.body).hexdigest())
        (evidence/'p0-first-receipt.json').write_text(json.dumps(index))

    def execute(self, now, *, day=DAY, deadline=None, jump=None):
        clock = Clock(now, jump=jump)
        deadline = deadline or now+timedelta(minutes=330)
        env = dict(RACE_AI_EVENT_DAY=day, RACE_AI_WORKER_HANDOFF_AT=deadline.isoformat(),GITHUB_RUN_ID='42',
                   GITHUB_OUTPUT=str(self.output))
        printed = io.StringIO()
        with patch.object(cycle, 'ROOT', self.root), patch.object(bootstrap, 'ROOT', self.root), \
             patch.dict(os.environ, env, clear=True), \
             patch.object(cycle, 'gh', side_effect=AssertionError('startup wait cannot read GitHub')), \
             patch.object(bootstrap, 'gh', side_effect=AssertionError('startup control cannot read GitHub')), \
             patch.object(cycle, 'original', side_effect=AssertionError('startup wait cannot fetch originals')), \
             patch.object(cycle.request, 'urlopen', side_effect=AssertionError('startup wait cannot read sources')), \
             patch.object(repeated_cycle, 'start', side_effect=AssertionError('startup wait cannot start a session')), \
             redirect_stdout(printed):
            result = cycle.wait_for_window(day, clock=clock.now, sleeper=clock.sleep)
        return result, clock, [json.loads(line) for line in printed.getvalue().splitlines()]

    def existing_control(self, **changes):
        inherited = dict(lifetime_requests=701, lifetime_completed_rounds=29,
                         previous_halted_reason='SOURCE_HTTP_403_NO_RETRY',
                         source_wait=dict(state='AUTHORIZATION_WAIT', reason='SOURCE_AUTHORIZATION_REQUIRED',
                                          retry_at=None, http_status=403, attempts=2),
                         receipt=dict(id=7, digest='sha256:'+'b'*64))
        with patch.object(bootstrap, 'ROOT', self.root):
            control = bootstrap.bootstrap_control(DAY, 42, inherited=inherited)
            control.update(requests_used=2, lifetime_requests=703, **changes)
            bootstrap._save_control(control)
        path = self.root/'cycle_recovery_output/bootstrap-source-control.json'
        return path, json.loads(path.read_text())

    def test_early_worker_reaches_first_t15_without_spending_65_minute_session(self):
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        opening = cutoff-timedelta(minutes=15)
        now = opening-timedelta(hours=4)
        unchanged = {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result, clock, output = self.execute(now)
        self.assertTrue(result['window_ready'])
        self.assertEqual(result['state'], 'SOURCE_WINDOW_READY')
        self.assertEqual(clock.current, opening)
        self.assertGreater(sum(clock.sleeps), 3900)
        self.assertTrue(all(seconds == 30 for seconds in clock.sleeps))
        self.assertEqual(len(output), len(clock.sleeps)+1)
        self.assertTrue(all(row['source_requests'] == 0 and row['source_session_started'] is False for row in output))
        self.assertFalse((self.root/'cycle_recovery_output/repeat-session.json').exists())
        for path, body in unchanged.items():
            if path != self.output:
                self.assertEqual(path.read_bytes(), body)
        self.assertIn('window_ready=true\n', self.output.read_text())
        self.assertEqual((repeated_cycle.SOURCE_LIMIT, repeated_cycle.ROUND_SOURCE_LIMIT,
                          repeated_cycle.MAX_ROUNDS, repeated_cycle.MAX_SECONDS, repeated_cycle.POLL_SECONDS),
                         (240, 45, 24, 3900, 180))

    def test_open_window_returns_immediately_and_jst_day_is_used(self):
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        now = (cutoff-timedelta(minutes=14)).astimezone(timezone.utc)
        result, clock, _ = self.execute(now)
        self.assertTrue(result['window_ready'])
        self.assertEqual(clock.sleeps, [])

    def test_empty_or_finished_schedule_returns_immediately_without_source_session(self):
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, clock, _ = self.execute(cutoff)
        self.assertFalse(result['window_ready'])
        self.assertEqual(result['state'], 'NO_FUTURE_WINDOW')
        self.assertEqual(clock.sleeps, [])
        self.assertFalse((self.root/'cycle_recovery_output/bootstrap-source-control.json').exists())
        empty = deepcopy(self.document); empty.update(schedule=[], predictions=[], race_count=0, model_forecast_count=0)
        self.write_restored(document=empty)
        result, clock, _ = self.execute(cutoff-timedelta(hours=2))
        self.assertFalse(result['window_ready'])
        self.assertEqual(clock.sleeps, [])

    def restored_result_work(self, *, confirmed=False, corrupt=False):
        race = self.document['schedule'][0]
        observation = dict(race_id=race['race_id'], captured_at=race['cutoff_at'],
                           data=dict(confirmed=confirmed, status='settled' if confirmed else 'pending'))
        state = dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1', complete=True, day_jst=DAY,
                     rows=[dict(race_id=race['race_id'],cutoff_at=race['cutoff_at'],stage='P0')],
                     observations=[observation], source_control=dict(lifetime_requests=701))
        state['state_sha256'] = sha256(json.dumps(state,sort_keys=True,separators=(',',':'),
                                                  ensure_ascii=False).encode()).hexdigest()
        if corrupt:
            state['state_sha256'] = '0'*64
        path = self.root/'cycle_recovery_output'/'continuity.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(state))
        return path

    def test_after_last_forecast_pending_results_keep_existing_source_gate_ready(self):
        path = self.restored_result_work()
        before = path.read_bytes()
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, clock, _ = self.execute(cutoff+timedelta(minutes=5))
        self.assertTrue(result['window_ready'])
        self.assertEqual(result['work_scope'], 'PENDING_RESULTS')
        self.assertEqual(result['pending_result_races'], 1)
        self.assertEqual(result['source_requests'], 0)
        self.assertFalse(result['source_session_started'])
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(path.read_bytes(), before)

    def test_confirmed_results_do_not_open_an_extra_after_hours_session(self):
        self.restored_result_work(confirmed=True)
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, _, _ = self.execute(cutoff+timedelta(hours=7))
        self.assertFalse(result['window_ready'])
        self.assertEqual(result['state'], 'NO_FUTURE_WINDOW')

    def test_corrupt_result_work_stops_before_source_readiness(self):
        self.restored_result_work(corrupt=True)
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        with self.assertRaisesRegex(ValueError, 'recovered state hash mismatch'):
            self.execute(cutoff+timedelta(minutes=5))

    def test_unreachable_window_waits_to_pinned_handoff_without_opening_sources(self):
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        now = cutoff-timedelta(hours=6)
        result, clock, _ = self.execute(now)
        self.assertFalse(result['window_ready'])
        self.assertEqual(result['state'], 'WORKER_HANDOFF')
        self.assertEqual(clock.current, now+timedelta(minutes=330))
        self.assertEqual(sum(clock.sleeps), 330*60)
        self.assertTrue(all(seconds == 30 for seconds in clock.sleeps))
        result, clock, _ = self.execute(cutoff-timedelta(minutes=14), deadline=cutoff-timedelta(minutes=15))
        self.assertEqual(result['state'], 'WORKER_HANDOFF')
        self.assertEqual(clock.sleeps, [])

    def test_no_future_window_seals_day_handoff_without_changing_inherited_control(self):
        path, before = self.existing_control()
        native = (self.root/'boat_all_day_output/forecasts.json').read_bytes()
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, clock, _ = self.execute(cutoff)
        self.assertEqual(result['state'], 'NO_FUTURE_WINDOW')
        after = json.loads(path.read_text())
        self.assertEqual(after['control_reason'], 'DAY_HANDOFF')
        self.assertNotEqual(after['source_control_sha256'], before['source_control_sha256'])
        self.assertEqual({key:value for key,value in after.items() if key not in ('control_reason','source_control_sha256')},
                         {key:value for key,value in before.items() if key not in ('control_reason','source_control_sha256')})
        with patch.object(bootstrap, 'ROOT', self.root):
            bootstrap.bootstrap_control(DAY, 42)  # Reverify the exact new seal.
        self.assertEqual(after['source_wait']['http_status'], 403)
        self.assertEqual(after['previous_halted_reason'], 'SOURCE_HTTP_403_NO_RETRY')
        self.assertEqual((self.root/'boat_all_day_output/forecasts.json').read_bytes(), native)
        self.assertFalse((self.root/'cycle_recovery_output/repeat-session.json').exists())
        original = path.read_bytes()
        self.execute(cutoff)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(clock.sleeps, [])

    def test_day_or_worker_handoff_is_sealed_but_hard_control_reason_stays_latched(self):
        path, before = self.existing_control()
        now = datetime.fromisoformat('2030-04-01T08:00:00+09:00')
        result, _, _ = self.execute(now, jump=datetime.fromisoformat('2030-04-02T00:00:00+09:00'))
        self.assertEqual(result['state'], 'DAY_HANDOFF')
        self.assertEqual(json.loads(path.read_text())['control_reason'], 'DAY_HANDOFF')
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, _, _ = self.execute(cutoff-timedelta(minutes=14), deadline=cutoff-timedelta(minutes=15))
        self.assertEqual(result['state'], 'WORKER_HANDOFF')
        self.assertEqual(json.loads(path.read_text())['control_reason'], 'WORKER_HANDOFF')
        with patch.object(bootstrap, 'ROOT', self.root):
            control = bootstrap.bootstrap_control(DAY, 42)
            control['control_reason'] = 'SOURCE_HTTP_403_NO_RETRY'
            bootstrap._save_control(control)
        original = path.read_bytes()
        self.execute(cutoff)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(json.loads(path.read_text())['source_wait'], before['source_wait'])

    def test_open_window_leaves_existing_control_bytes_unchanged(self):
        path, _ = self.existing_control(control_reason='DAY_HANDOFF')
        original = path.read_bytes()
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        result, _, _ = self.execute(cutoff-timedelta(minutes=14))
        self.assertTrue(result['window_ready'])
        self.assertEqual(path.read_bytes(), original)

    def test_future_or_old_event_day_and_mid_wait_day_change_handoff(self):
        now = datetime.fromisoformat('2030-04-01T08:00:00+09:00')
        for day in ('2030-03-31', '2030-04-02'):
            with self.subTest(day=day):
                result, clock, _ = self.execute(now, day=day)
                self.assertEqual(result['state'], 'DAY_HANDOFF')
                self.assertFalse(result['window_ready'])
                self.assertEqual(clock.sleeps, [])
        result, clock, _ = self.execute(now, jump=datetime.fromisoformat('2030-04-02T00:00:00+09:00'))
        self.assertEqual(result['state'], 'DAY_HANDOFF')
        self.assertEqual(clock.sleeps, [30])

    def test_changed_original_bytes_or_receipt_cannot_supply_wait_targets(self):
        now = datetime.fromisoformat('2030-04-01T08:00:00+09:00')
        (self.root/'boat_all_day_output/forecasts.json').write_bytes(self.body+b' ')
        with self.assertRaises(ValueError):
            self.execute(now)
        self.write_restored()
        metadata = deepcopy(self.receipt); metadata['digest'] = 'sha256:'+'0'*64
        (self.root/'boat_all_day_output/first-receipt.json').write_text(json.dumps(metadata))
        with self.assertRaises(ValueError):
            self.execute(now)

    def test_handoff_pin_and_preexisting_source_session_are_fail_closed(self):
        now = datetime.fromisoformat('2030-04-01T08:00:00+09:00')
        with self.assertRaises(ValueError):
            self.execute(now, deadline=now+timedelta(minutes=330, seconds=1))
        session = self.root/'cycle_recovery_output/repeat-session.json'
        session.parent.mkdir(); session.write_bytes(b'original-session-bytes')
        with self.assertRaises(ValueError):
            self.execute(now)
        self.assertEqual(session.read_bytes(), b'original-session-bytes')

    def test_closed_races_are_ignored_and_short_final_sleep_reaches_exact_t15(self):
        cutoff = datetime.fromisoformat(self.document['schedule'][0]['cutoff_at'])
        later = deepcopy(self.document)
        later['schedule'].append(dict(race_id='20300401-01-02', cutoff_at=(cutoff+timedelta(hours=1)).isoformat()))
        self.write_restored(document=later)
        opening = cutoff+timedelta(hours=1)-timedelta(minutes=15)
        result, clock, _ = self.execute(opening-timedelta(seconds=60.5))
        self.assertTrue(result['window_ready'])
        self.assertEqual(clock.sleeps, [30., 30., .5])
        self.assertEqual(clock.current, opening)

    def test_conflicting_authenticated_cutoff_and_future_receipt_are_rejected(self):
        invalid = deepcopy(self.document)
        invalid['schedule'][0]['cutoff_at'] = '2030-04-01T11:00:00+09:00'
        self.write_restored(document=invalid)
        with self.assertRaisesRegex(ValueError, 'SOURCE_WINDOW_RESTORED_CUTOFF_REJECTED'):
            self.execute(datetime.fromisoformat('2030-04-01T08:00:00+09:00'))
        self.write_restored()
        with self.assertRaisesRegex(ValueError, 'SOURCE_WINDOW_RESTORED_P0_CLOCK_REJECTED'):
            self.execute(datetime.fromisoformat('2030-04-01T03:00:00+09:00'))

    def test_cli_routes_wait_before_event_day_rejects_a_future_pin(self):
        with patch.object(cycle, 'wait_for_window') as wait, \
             patch.object(cycle, 'event_day', side_effect=AssertionError('wait owns day handoff')), \
             patch.object(cycle.sys, 'argv', ['github_existing_cycle.py', 'wait-for-window']):
            cycle.main()
        wait.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
