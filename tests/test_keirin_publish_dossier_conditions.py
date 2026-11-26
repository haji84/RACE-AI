from datetime import datetime, timezone
import json
import unittest

from race_ai import keirin_dossier_conditions as conditions
from scripts import keirin_publish_dossier_conditions as publisher
from tests.test_keirin_daily_rider_update import PublicStore


class PublishConditionsTests(unittest.TestCase):
    def setUp(self):
        self.day = '2026-11-27'
        self.past = '2026-11-26'
        self.at = datetime(2026, 11, 27, 1, tzinfo=timezone.utc)
        rid = '202611272501'
        self.rows = {rid:dict(race_id=rid, meeting_grade='F2', round_stage='FINAL',
            round_label='A級決勝', list_sha256='a' * 64, source_at=self.at.isoformat())}
        self.registry = dict(registered_race_ids=[rid], calendar_source_sha256='b' * 64)
        self.store = PublicStore()

    def publish(self, active, past, *, rows=None):
        return publisher.publish_day(self.store, self.day, registry=self.registry,
            race_conditions=self.rows if rows is None else rows, all_past_days={self.past, self.day},
            updated_results={result['day']: result for result in (past, active)}, published_at=self.at)

    def test_current_results_are_retained_and_excluded_from_current_day_features(self):
        reg = '014005'
        active = conditions.result_slice(self.day, 'c' * 64, [(reg, 'F2', 'FINAL', 1)])
        past = conditions.result_slice(self.past, 'd' * 64, [(reg, 'F2', 'FINAL', 7)])
        result = self.publish(active, past)
        self.assertEqual(result['packet']['history']['end_day'], self.past)
        cells = result['packet']['riders'][0]['cells']
        self.assertEqual(cells[-1]['wins'], 0)
        recent = json.loads(self.store.read_previous(result['commit'], publisher.result_path(self.day)))
        self.assertEqual(recent['riders'][0]['cells'][-1]['wins'], 1)
        self.assertIsNone(self.publish(active, past))
        with self.assertRaisesRegex(ValueError, 'PROJECTION_REGRESSED'):
            self.publish(active, past, rows={})

    def test_latest_source_revision_replaces_slice_instead_of_appending(self):
        reg = '014005'
        active = conditions.result_slice(self.day, 'c' * 64, [(reg, 'F2', 'FINAL', 1)])
        past = conditions.result_slice(self.past, 'd' * 64, [(reg, 'F2', 'FINAL', 7)])
        former = self.publish(active, past)
        updated = conditions.result_slice(self.past, 'e' * 64, [(reg, 'F2', 'FINAL', 1)])
        self.at = self.at.replace(minute=3)
        current = self.publish(active, updated)
        self.assertEqual(current['packet']['riders'][0]['cells'][-1]['wins'], 1)
        self.assertEqual(current['packet']['history']['numeric_finishes'], 1)
        self.assertNotEqual(current['commit'], former['commit'])
