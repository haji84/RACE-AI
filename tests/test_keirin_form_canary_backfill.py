"""Fixed-race next-day settlement guards; no real provider or archive I/O."""
from datetime import datetime
import unittest
from unittest.mock import patch

from scripts import keirin_official_form_canary as canary


class BackfillPreflight(unittest.TestCase):
    def test_current_day_marker_stops_before_any_provider_request(self):
        now = datetime.fromisoformat('2026-11-20T15:05:00+00:00')
        marker = dict(schema=canary.provider_stop.SCHEMA, day_jst='2026-11-21',
            code=canary.provider_stop.DENIED, observed_at='2026-11-20T15:01:00+00:00')

        def read(*, repo, day):
            if day < '2026-11-21':
                raise canary.provider_stop.ProviderStopError('STOP_MARKER_FUTURE_DATE_UNTRUSTED')
            return marker

        calls = []
        with patch.object(canary.provider_stop, 'read_for_observed_day', side_effect=read):
            with self.assertRaisesRegex(ValueError, 'CANARY_PERSISTENT_PROVIDER_STOP'):
                canary.collect_final_result(repo='/synthetic', private_root='/unused',
                    frozen_card={}, clock=lambda: now, request=lambda *args: calls.append(args))
        self.assertEqual(calls, [])

    def test_old_denial_stays_blocked_on_the_next_observation_day(self):
        now = datetime.fromisoformat('2026-11-21T12:00:00+09:00')
        marker = dict(schema=canary.provider_stop.SCHEMA, day_jst='2026-11-20',
            code=canary.provider_stop.DENIED, observed_at='2026-11-20T09:00:00+00:00')
        reads = []

        def read(*, repo, day):
            reads.append(day)
            return marker

        calls = []
        with patch.object(canary.provider_stop, 'read_for_observed_day', side_effect=read):
            with self.assertRaisesRegex(canary.CanaryError, 'CANARY_PERSISTENT_PROVIDER_STOP'):
                canary.collect_final_result(repo='/synthetic', private_root='/unused',
                    frozen_card={}, clock=lambda: now, request=lambda *args: calls.append(args))
        self.assertEqual(reads, ['2026-11-21'])
        self.assertEqual(calls, [])

    def test_naive_observation_clock_fails_before_archive_or_provider_io(self):
        reads, calls = [], []

        def read(*, repo, day):
            reads.append(day)
            return {'code': canary.provider_stop.DENIED}

        with patch.object(canary.provider_stop, 'read_for_observed_day', side_effect=read):
            with self.assertRaisesRegex(canary.CanaryError, 'CANARY_PROVIDER_CLOCK_INVALID'):
                canary.collect_final_result(repo='/synthetic', private_root='/unused',
                    frozen_card={}, clock=lambda: datetime(2026, 11, 21, 2),
                    request=lambda *args: calls.append(args))
        self.assertEqual(reads, [])
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
