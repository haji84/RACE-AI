from datetime import datetime, timedelta, timezone
import unittest

from scripts.keirin_mac_acceptance_audit import delivery_days, workflow_observation


class MacAcceptanceAuditTest(unittest.TestCase):
    def setUp(self):
        self.begin = datetime(2026, 11, 26, 0, tzinfo=timezone.utc)
        self.end = self.begin + timedelta(days=1)

    def test_delivery_uses_latest_registration_and_retains_prior_frozen_originals(self):
        race = '202611267301'
        other = '202611267302'
        outside = '202611267303'
        day = '2026-11-26'
        before = (self.begin - timedelta(minutes=10)).isoformat()
        after = (self.end + timedelta(minutes=10)).isoformat()
        index = {'entries': [
            dict(kind='nationwide', days=[day], created_at=before, registered_race_ids=[race, other],
                 original_revisions={race: {'baseline': 'a'}}),
            dict(kind='nationwide', days=[day], created_at=self.begin.isoformat(), registered_race_ids=[race, other, outside],
                 original_revisions={other: {'baseline': 'b'}}),
            dict(kind='result', days=[day], created_at=self.begin.isoformat(), result_revisions={race: 'c', outside: 'd'}),
            dict(kind='result', days=[day], created_at=self.begin.isoformat(), result_revisions={race: 'e'}),
            dict(kind='result', days=[day], created_at=after, result_revisions={other: 'f'}),
        ]}
        yesterday, today = delivery_days(index, self.begin, self.end)
        self.assertEqual(yesterday, dict(day_jst=day, registered=3, original_count=2, original_missing=1,
                                         result_revision_count=2, originals_with_result_revision=1))
        self.assertEqual(today['day_jst'], '2026-11-27')
        self.assertIsNone(today['registered'])

    def test_workflow_start_and_completion_counts_are_distinct(self):
        name = 'keirin-nationwide-ab-auto.yml'
        def row(run_id, at, event, status, conclusion):
            return dict(id=run_id, run_attempt=1, run_started_at=at.isoformat(), event=event, status=status,
                        conclusion=conclusion, path='.github/workflows/' + name, head_branch='main',
                        head_sha='a' * 40, repository={'id': 1416489937}, head_repository={'id': 1416489937},
                        updated_at=(at + timedelta(minutes=2)).isoformat())
        rows = [
            row(1, self.begin - timedelta(seconds=1), 'schedule', 'completed', 'success'),
            row(2, self.begin, 'schedule', 'completed', 'success'),
            row(3, self.begin + timedelta(hours=1), 'workflow_dispatch', 'in_progress', None),
            row(4, self.end - timedelta(minutes=1), 'schedule', 'completed', 'success'),
        ]
        result = workflow_observation(name, rows, self.begin, self.end)
        self.assertEqual(result['schedule']['starts'], 2)
        self.assertEqual(result['schedule']['concluded_success'], 1)
        self.assertEqual(result['workflow_dispatch']['completion_unconfirmed_in_window'], 1)
        self.assertEqual([row['id'] for row in result['schedule']['runs']], [2, 4])
        self.assertEqual(result['all_start_intervals']['max_start_gap_seconds'], 82740)
