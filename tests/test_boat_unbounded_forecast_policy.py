"""Future-only BOAT owner: no arbitrary request/time/round budget, with safe handoff.

Synthetic offline fixtures; no official source requests or original mutation.
A source wait, missing checkpoint, unknown counters or active prepared round must
never be converted into permission for another request.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from race_ai import repeated_cycle as cycle
from race_ai.source_retry_policy import SourceWait

JST = timezone(timedelta(hours=9))
DAY = '2030-04-01'
START = datetime(2030, 4, 1, 8, 0, tzinfo=JST)


class UnlimitedEligibleForecastWorkTests(unittest.TestCase):
    def test_budgets_are_not_fixed_releases_or_silently_reset(self):
        self.assertIsNone(cycle.SOURCE_LIMIT)
        self.assertIsNone(cycle.ROUND_SOURCE_LIMIT)
        self.assertIsNone(cycle.MAX_ROUNDS)
        self.assertIsNone(cycle.MAX_SECONDS)
        self.assertGreaterEqual(cycle.POLL_SECONDS, 60)

    def test_310_authenticated_get_charges_and_25_rounds_can_continue(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'session.json'
            state = cycle.start(path, day=DAY, run_id=101, now=START)
            self.assertIsNone(state['stop_at'])
            self.assertIsNone(state['source_limit'])
            self.assertIsNone(state['max_rounds'])
            self.assertTrue(cycle.prepare(path, 1, now=START)['active'])
            guard = cycle.SourceGuard(path, clock=lambda: START)
            for _ in range(310):
                guard.charge('forecast')
            self.assertEqual(cycle.load(path)['lifetime_requests'], 310)
            cycle.complete(path, 1, now=START, forecast_artifact=1001, result_artifact=2001)
            for number in range(2, 27):
                current = START + timedelta(seconds=181*(number-1))
                self.assertTrue(cycle.prepare(path, number, now=current)['active'])
                cycle.complete(path, number, now=current,
                               forecast_artifact=1000+number, result_artifact=2000+number)
            final = cycle.load(path)
            self.assertEqual(final['completed_round'], 26)
            self.assertEqual(final['requests_used'], 310)
            self.assertEqual(final['lifetime_requests'], 310)
            self.assertIsNone(final['halted_reason'])

    def test_completed_worker_handoffs_without_reset_or_forecast_regeneration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.json'
            cycle.start(path, day=DAY, run_id=17, now=START)
            self.assertTrue(cycle.prepare(path, 1, now=START)['active'])
            guard = cycle.SourceGuard(path, clock=lambda:START)
            for _ in range(280):guard.charge('forecast')
            cycle.complete(path, 1, now=START, forecast_artifact=21, result_artifact=22)
            outcome = cycle.finish_worker(path, now=START+timedelta(minutes=4))
            self.assertEqual(outcome['reason'], 'WORKER_HANDOFF')
            self.assertEqual(outcome['lifetime_requests'], 280)
            self.assertEqual(cycle.load(path)['halted_reason'], 'WORKER_HANDOFF')
            next_path = Path(folder)/'successor.json'
            inherited = dict(day_jst=DAY,lifetime_requests=outcome['lifetime_requests'],
                             day_start_lifetime_requests=0,lifetime_completed_rounds=1,
                             previous_stop_reason='WORKER_HANDOFF')
            later = START + timedelta(minutes=5)
            continued = cycle.start(next_path, day=DAY, run_id=18, now=later,
                                    source_control=inherited)
            self.assertEqual(continued['lifetime_requests'], 280)
            self.assertTrue(cycle.prepare(next_path, 1, now=later)['active'])
            cycle.SourceGuard(next_path, clock=lambda:later).charge('forecast')
            self.assertEqual(cycle.load(next_path)['lifetime_requests'], 281)

    def test_handoff_rejects_prepared_round_and_retains_file_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'session.json'
            cycle.start(path,day=DAY,run_id=23,now=START)
            cycle.prepare(path,1,now=START)
            original=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'UNCOMMITTED'):
                cycle.finish_worker(path,now=START+timedelta(minutes=1))
            self.assertEqual(path.read_bytes(),original)

    def test_http_429_and_403_do_not_clear_under_unlimited_policy(self):
        for status in (403,429):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'session.json'
                cycle.start(path,day=DAY,run_id=45+status,now=START)
                cycle.prepare(path,1,now=START)
                clock=lambda:START
                guard=cycle.SourceGuard(path,clock=clock)
                guard.http_failure(status,{'Retry-After':'180'})
                with self.assertRaises(SourceWait):
                    guard.charge('forecast')
                self.assertEqual(cycle.load(path)['requests_used'],0)
                with self.assertRaisesRegex(ValueError, 'WORKER_HANDOFF_UNCOMMITTED_ROUND'):
                    cycle.finish_worker(path,now=START+timedelta(seconds=1))
                # A pending round stays pending; a 403/429 is never converted to success.
                self.assertIsNotNone(cycle.load(path)['source_wait'])


if __name__=='__main__':
    unittest.main()
