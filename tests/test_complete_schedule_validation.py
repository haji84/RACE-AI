"""Complete-day availability must not lose active venues through missing flags."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

from race_ai.day_snapshot_publisher import validate
from race_ai.official_day_schedule import endpoint, merge_schedule_programs, parse_day_schedule
from tests.test_day_publish import snapshot
from tests.test_official_day_schedule import DAY, fixture


NOW = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)


class CompleteScheduleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'web/api/today.py'
        spec = importlib.util.spec_from_file_location('complete_schedule_today', path)
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)

    def setUp(self):
        schedule = parse_day_schedule(fixture(), day=DAY, source_url=endpoint(DAY),
                                      observed_at='2026-10-15T03:00:00+09:00')
        self.payload = merge_schedule_programs(schedule, snapshot())
        self.payload['redistribution_authorized'] = True
        approvals = [dict(source_url=s['source_url'], redistribution_authorized=True,
                          evidence_reference='synthetic-only', reviewed_by='test')
                     for s in self.payload['sources']]
        self.approval = {**approvals[0], 'source_approvals': approvals[1:]}

    def both_validators_reject(self, payload):
        for consumer in ('api', 'local publisher'):
            with self.subTest(consumer=consumer), self.assertRaises(ValueError):
                if consumer == 'api':
                    self.api.validate_feed(payload, day=DAY, now=NOW)
                else:
                    validate(payload, today=DAY, approval=self.approval, now=NOW)

    def test_valid_complete_schedule_is_accepted_by_both_validators(self):
        self.api.validate_feed(self.payload, day=DAY, now=NOW)
        validate(self.payload, today=DAY, approval=self.approval, now=NOW)

    def test_missing_or_nonboolean_no_event_cannot_hide_active_race_venue(self):
        for value in (None, 0, 'false'):
            payload = deepcopy(self.payload)
            venue = next(v for v in payload['venues'] if v['races'])
            if value is None:
                venue.pop('no_event')
            else:
                venue['no_event'] = value
            payload['active_venues'].remove(venue['venue'])
            with self.subTest(no_event=value):
                self.both_validators_reject(payload)

    def test_missing_schedule_flag_cannot_bypass_active_venue_basis_or_proof(self):
        for field, value in (('schedule_basis', 'NOT_LISTED_IN_COMPLETE_DAY_INDEX'),
                             ('schedule_source_sha256', 'b' * 64)):
            payload = deepcopy(self.payload)
            venue = next(v for v in payload['venues'] if v['races'])
            venue.pop('schedule_verified')
            venue[field] = value
            with self.subTest(field=field):
                self.both_validators_reject(payload)


if __name__ == '__main__':
    unittest.main()
