"""Offline checks for prompt publication and the no-retry provider boundary."""
import json
import unittest

from race_ai import keirin_result_observer as observer


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def packet(value=None, *, denied=False, done=False, fingerprint=None):
    result = {'snapshot': value, 'provider_denied': denied, 'done': done}
    if fingerprint is not None:
        result['fingerprint'] = fingerprint
    return result


class ResultObserverTests(unittest.TestCase):
    def run_case(self, packets, *, stop_check=lambda: False, publisher=None,
                 clock=None, **bounds):
        clock = clock or Clock()
        events = []
        source = iter(packets)

        def tick():
            events.append(('tick', clock.now))
            return next(source)

        def publish(snapshot):
            events.append(('publish', clock.now, snapshot))
            if publisher:
                publisher(snapshot)

        result = observer.run_observer(
            tick=tick, publish=publish, stop_check=stop_check,
            monotonic=clock.monotonic, sleep=clock.sleep, **bounds)
        return result, events, clock

    def test_each_result_publishes_before_next_tick_without_waiting_for_batch(self):
        result, events, _ = self.run_case([
            packet({'race': 'synthetic-1', 'revision': 1}),
            packet({'race': 'synthetic-2', 'revision': 1}, done=True),
        ])
        self.assertEqual([e[0] for e in events], ['tick', 'publish', 'tick', 'publish'])
        self.assertEqual(events[0][1], events[1][1])
        self.assertEqual(events[2][1], events[3][1])
        self.assertEqual(result['published_snapshots'], 2)
        self.assertEqual(result['state'], 'RESULT_OBSERVER_COMPLETE')

    def test_latched_start_never_calls_provider_or_publisher(self):
        result, events, clock = self.run_case([], stop_check=lambda: True)
        self.assertEqual(events, [])
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        self.assertTrue(result['provider_denied'])
        self.assertTrue(result['no_provider_tick'])

    def test_latch_is_checked_before_every_provider_capable_tick(self):
        decisions = iter([False, True])
        result, events, _ = self.run_case(
            [packet({'race': 'synthetic-1'})], stop_check=lambda: next(decisions))
        self.assertEqual([e[0] for e in events], ['tick', 'publish'])
        self.assertEqual(result['ticks'], 1)
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_PROVIDER_STOP')

    def test_valid_result_survives_same_tick_optional_source_denial(self):
        result, events, clock = self.run_case([
            packet({'order_status': 'confirmed', 'payout_status': 'pending'}, denied=True),
        ])
        self.assertEqual([e[0] for e in events], ['tick', 'publish'])
        self.assertEqual(result['published_snapshots'], 1)
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_PROVIDER_STOP')
        self.assertEqual(clock.sleeps, [])

    def test_same_result_is_deduplicated_but_changed_revision_publishes(self):
        first = {'race': 'synthetic-1', 'revision': 1}
        second = {'race': 'synthetic-1', 'revision': 2}
        result, events, _ = self.run_case([
            packet(first), packet(dict(first)), packet(second), packet(first, done=True),
        ])
        self.assertEqual([e[2]['revision'] for e in events if e[0] == 'publish'], [1, 2, 1])
        self.assertEqual(result['published_snapshots'], 3)

    def test_explicit_content_identity_excludes_capture_time_only_when_producer_supplies_it(self):
        result, events, _ = self.run_case([
            packet({'revision': 1, 'observed_at': 'synthetic-time-1'}, fingerprint='a' * 64),
            packet({'revision': 1, 'observed_at': 'synthetic-time-2'}, fingerprint='a' * 64),
            packet({'revision': 2, 'observed_at': 'synthetic-time-3'}, fingerprint='b' * 64, done=True),
        ])
        self.assertEqual(result['published_snapshots'], 2)
        self.assertEqual([e[2]['revision'] for e in events if e[0] == 'publish'], [1, 2])

    def test_empty_pending_ticks_do_not_publish_or_manufacture_a_score(self):
        result, events, _ = self.run_case([packet(), packet({}), packet(done=True)])
        self.assertEqual([e[0] for e in events], ['tick', 'tick', 'tick'])
        self.assertEqual(result['published_snapshots'], 0)
        self.assertNotIn('hit', result)
        self.assertNotIn('score', result)

    def test_tick_error_stops_without_exposing_exception_or_retrying(self):
        clock = Clock()
        calls = []

        def broken():
            calls.append('tick')
            raise RuntimeError('SECRET_HTTP_TOKEN_AND_PRIVATE_RESULT')

        result = observer.run_observer(
            tick=broken, publish=lambda _: calls.append('publish'), stop_check=lambda: False,
            monotonic=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(calls, ['tick'])
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_TICK_FAILED')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(clock.sleeps, [])

    def test_publication_failure_is_not_counted_or_retried(self):
        def broken(_):
            raise OSError('SECRET_STORAGE_CONTEXT')

        result, events, clock = self.run_case([packet({'revision': 1})], publisher=broken)
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_PUBLICATION_FAILED')
        self.assertEqual(result['published_snapshots'], 0)
        self.assertEqual([e[0] for e in events], ['tick', 'publish'])
        self.assertEqual(clock.sleeps, [])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_stop_check_error_fails_closed(self):
        def broken():
            raise RuntimeError('SECRET_GIT_STATE')

        result, events, _ = self.run_case([], stop_check=broken)
        self.assertEqual(events, [])
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_STOP_CHECK_FAILED')
        self.assertTrue(result['no_provider_tick'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_non_boolean_stop_check_cannot_grant_access(self):
        result, events, _ = self.run_case([], stop_check=lambda: None)
        self.assertEqual(events, [])
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_STOP_CHECK_INVALID')

    def test_tick_limit_does_not_sleep_after_last_tick(self):
        result, events, clock = self.run_case([packet(), packet()], max_ticks=2)
        self.assertEqual(result['state'], 'RESULT_OBSERVER_TICK_LIMIT')
        self.assertEqual(result['ticks'], 2)
        self.assertEqual(clock.sleeps, [60])

    def test_deadline_prevents_another_tick_and_bounds_sleep(self):
        result, events, clock = self.run_case(
            [packet(), packet()], duration_seconds=61, interval_seconds=60)
        self.assertEqual(result['state'], 'RESULT_OBSERVER_WINDOW_ENDED')
        self.assertEqual(result['ticks'], 2)
        self.assertEqual(clock.sleeps, [60, 1])
        self.assertLessEqual(clock.now, 61)

    def test_long_intervals_sleep_in_responsive_chunks(self):
        result, events, clock = self.run_case(
            [packet(), packet(done=True)], interval_seconds=180, duration_seconds=200)
        self.assertEqual(clock.sleeps, [60, 60, 60])
        self.assertEqual(result['state'], 'RESULT_OBSERVER_COMPLETE')

    def test_elapsed_time_in_stop_check_prevents_post_deadline_provider_call(self):
        clock = Clock()

        def stop_check():
            clock.now = 100
            return False

        result, events, _ = self.run_case([], clock=clock, stop_check=stop_check, duration_seconds=60)
        self.assertEqual(events, [])
        self.assertEqual(result['state'], 'RESULT_OBSERVER_WINDOW_ENDED')

    def test_monotonic_clock_rollback_stops(self):
        clock = Clock()
        readings = iter([100.0, 99.0])
        calls = []
        result = observer.run_observer(
            tick=lambda: calls.append('tick'), publish=lambda _: calls.append('publish'),
            stop_check=lambda: False, monotonic=lambda: next(readings), sleep=clock.sleep)
        self.assertEqual(calls, [])
        self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_CLOCK_INVALID')

    def test_invalid_payloads_stop_without_echoing_private_data(self):
        invalid = [
            {'snapshot': {'private': 'SECRET'}, 'provider_denied': 'false', 'done': False},
            packet({'revision': 1}, fingerprint='SECRET_BAD_SHA'),
            packet(['SECRET_NOT_A_SNAPSHOT']),
            packet({'revision': float('nan')}),
        ]
        for value in invalid:
            with self.subTest(value=repr(value)):
                result, events, clock = self.run_case([value])
                self.assertEqual(result['state'], 'HOLD_RESULT_OBSERVER_TICK_INVALID')
                self.assertEqual([e[0] for e in events], ['tick'])
                self.assertEqual(clock.sleeps, [])
                self.assertNotIn('SECRET', json.dumps(result))

    def test_invalid_bounds_rejected_before_any_callback(self):
        for values in ({'interval_seconds': 0}, {'interval_seconds': 59},
                       {'duration_seconds': 0}, {'duration_seconds': 21601},
                       {'max_ticks': 0}, {'max_ticks': True}, {'max_ticks': 10000}):
            with self.subTest(values=values), self.assertRaisesRegex(
                    observer.ObserverError, 'OBSERVER_INVALID_BOUNDS'):
                self.run_case([], **values)


if __name__ == '__main__':
    unittest.main()
