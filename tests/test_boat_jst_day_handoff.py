"""Regress the real 2026-11-14/15 JST BOAT worker handoff failure.

Research-only, source-free tests. Never fetch race data, write an owner vault,
reset GET counters, or treat a prepared round/source wait as a clean handoff.
"""
import tempfile
import unittest
import os
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

from race_ai import repeated_cycle as cycle

JST = timezone(timedelta(hours=9))
DAY = '2030-04-01'
NEXT_DAY = '2030-04-02'
START = datetime(2030, 4, 1, 23, 50, tzinfo=JST)
MIDNIGHT = datetime(2030, 4, 2, 0, 1, tzinfo=JST)


class MidnightWorkerHandoffTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'repeat-session.json'

    def _completed_original(self):
        cycle.start(self.path, day=DAY, run_id=20261114, now=START,
                    source_control=dict(day_jst=DAY, lifetime_requests=700,
                                        lifetime_completed_rounds=40,
                                        day_start_lifetime_requests=500))
        self.assertTrue(cycle.prepare(self.path, 1, now=START)['active'])
        guard = cycle.SourceGuard(self.path, clock=lambda: START)
        guard.charge('forecast')
        guard.charge('result')
        cycle.complete(self.path, 1, now=START + timedelta(seconds=15),
                       forecast_artifact=101, result_artifact=102)
        return cycle.load(self.path)

    def test_midnight_finish_preserves_exact_day_counters_and_receipts(self):
        before = self._completed_original()
        self.assertEqual(cycle.prepare(self.path, 2, now=MIDNIGHT)['reason'],
                         'DAY_HANDOFF')
        outcome = cycle.finish_worker(self.path, now=MIDNIGHT)
        after = cycle.load(self.path)
        self.assertEqual(outcome, dict(reason='DAY_HANDOFF', completed_round=1,
                                      lifetime_requests=702))
        self.assertEqual(after['day_jst'], DAY)
        self.assertEqual(after['halted_reason'], 'DAY_HANDOFF')
        for field in ('run_id', 'receipts', 'requests_used', 'requests_by_kind',
                      'lifetime_requests', 'day_start_lifetime_requests',
                      'lifetime_completed_rounds', 'source_control',
                      'source_wait', 'completed_round', 'prepared_round'):
            self.assertEqual(after[field], before[field], field)
        sealed = self.path.read_bytes()
        self.assertEqual(cycle.finish_worker(self.path, now=MIDNIGHT), outcome)
        self.assertEqual(self.path.read_bytes(), sealed)

    def test_new_day_worker_inherits_totals_but_new_day_budget_baseline(self):
        old = self._completed_original()
        cycle.finish_worker(self.path, now=MIDNIGHT)
        successor = Path(self.folder.name) / 'next-day.json'
        prior = dict(day_jst=DAY, lifetime_requests=old['lifetime_requests'],
                     lifetime_completed_rounds=old['lifetime_completed_rounds'],
                     day_start_lifetime_requests=old['day_start_lifetime_requests'],
                     previous_halted_reason='DAY_HANDOFF')
        fresh = cycle.start(successor, day=NEXT_DAY, run_id=20261115,
                            now=MIDNIGHT, source_control=prior)
        self.assertEqual(fresh['lifetime_requests'], 702)
        self.assertEqual(fresh['day_start_lifetime_requests'], 702)
        self.assertEqual(fresh['lifetime_completed_rounds'], 41)
        self.assertTrue(cycle.prepare(successor, 1, now=MIDNIGHT)['active'])
        cycle.SourceGuard(successor, clock=lambda: MIDNIGHT).charge('forecast')
        self.assertEqual(cycle.load(successor)['lifetime_requests'], 703)

    def test_expired_physical_deadline_uses_actual_jst_day_without_extra_work(self):
        from scripts import github_existing_cycle as owner
        from scripts import boat_prospective_forward as forward

        for now, expected in ((START + timedelta(minutes=6), 'WORKER_HANDOFF'),
                              (MIDNIGHT, 'DAY_HANDOFF')):
            with self.subTest(now=now), tempfile.TemporaryDirectory() as root_dir:
                root = Path(root_dir)
                session = root / 'cycle_recovery_output' / 'repeat-session.json'
                output = root / 'github-output.txt'
                cycle.start(session, day=DAY, run_id=71, now=START)
                self.assertTrue(cycle.prepare(session, 1, now=START)['active'])
                cycle.complete(session, 1, now=START + timedelta(seconds=10),
                               forecast_artifact=71, result_artifact=72)

                class FixedDatetime(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

                env = {'RACE_AI_WORKER_HANDOFF_AT': (START + timedelta(minutes=5)).isoformat(),
                       'GITHUB_OUTPUT': str(output)}
                with patch.object(owner, 'ROOT', root), patch.object(owner, 'datetime', FixedDatetime), \
                     patch.object(forward, 'active', return_value=False), patch.dict(os.environ, env):
                    owner.repeat_prepare(DAY, 2)
                after = cycle.load(session)
                self.assertEqual(after['halted_reason'], expected)
                self.assertEqual(after['completed_round'], 1)
                self.assertEqual(after['requests_used'], 0)
                self.assertEqual(after['receipts'][0]['forecast_artifact'], 71)
                self.assertIn('reason=' + expected, output.read_text())

    def test_uncommitted_round_remains_a_hard_failure_after_midnight(self):
        cycle.start(self.path, day=DAY, run_id=2, now=START)
        cycle.prepare(self.path, 1, now=START)
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'WORKER_HANDOFF_UNCOMMITTED_ROUND'):
            cycle.finish_worker(self.path, now=MIDNIGHT)
        self.assertEqual(self.path.read_bytes(), original)

    def test_403_or_429_wait_cannot_be_relabelled_as_a_clean_day_handoff(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.path.unlink(missing_ok=True)
                cycle.start(self.path, day=DAY, run_id=status, now=START)
                previous = cycle.load(self.path)
                previous['source_wait'] = cycle.plan_http_wait(
                    status, {'Retry-After': '900'}, START)
                cycle.write_state(self.path, previous)
                sealed = self.path.read_bytes()
                outcome = cycle.finish_worker(self.path, now=MIDNIGHT)
                self.assertEqual(outcome['reason'], 'SOURCE_WAIT')
                self.assertEqual(outcome['lifetime_requests'], 0)
                self.assertEqual(self.path.read_bytes(), sealed)

    def test_integrity_or_source_halt_is_not_reclassified_as_success(self):
        self._completed_original()
        previous = cycle.load(self.path)
        previous['halted_reason'] = 'ORIGINAL_INTEGRITY_REJECTED'
        cycle.write_state(self.path, previous)
        sealed = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'WORKER_HANDOFF_PREVIOUS_STOP_UNVERIFIED'):
            cycle.finish_worker(self.path, now=MIDNIGHT)
        self.assertEqual(self.path.read_bytes(), sealed)

    def test_tampered_original_is_rejected_without_handoff_write(self):
        self._completed_original()
        raw = self.path.read_text()
        self.path.write_text(raw.replace('"requests_used": 2', '"requests_used": 0'))
        sealed = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'session hash mismatch'):
            cycle.finish_worker(self.path, now=MIDNIGHT)
        self.assertEqual(self.path.read_bytes(), sealed)


if __name__ == '__main__':
    unittest.main()
