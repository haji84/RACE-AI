"""Existing summaries and immutable history must retain their temporal limits."""
from copy import deepcopy
from datetime import datetime
import unittest

from race_ai.core import SourceError
from race_ai.race_update_merge import merge_race_updates
from tests import test_race_update_merge as merge_fixtures


class RaceUpdateMergeBoundaryTests(unittest.TestCase):
    def test_late_summary_cannot_upgrade_any_prerace_eligibility_flag(self):
        helper = merge_fixtures.RaceUpdateMergeTests()
        late = helper.observation(capture='2026-10-15T09:00:00+09:00',
                                  saved='2026-10-15T09:01:00+09:00')
        original = helper.merge(helper.feed(), [late])
        for eligible, stored_eligible in ((True, False), (False, True), (True, True)):
            summary = deepcopy(original)
            record = summary['venues'][0]['races'][0]['official_updates']['records'][0]
            record.update(eligible_pre_race=eligible, storage_eligible_pre_race=stored_eligible)
            with self.subTest(eligible=eligible, stored_eligible=stored_eligible), self.assertRaises(SourceError):
                helper.merge(summary, [helper.observation('odds3t')])

    def test_existing_duplicate_snapshot_cannot_replace_immutable_save_metadata(self):
        helper = merge_fixtures.RaceUpdateMergeTests()
        feed = helper.merge(helper.feed(), [helper.observation()], summary_only=False)
        records = feed['venues'][0]['races'][0]['official_updates']['records']
        conflicting = deepcopy(records[0])
        conflicting['saved_at'] = '2026-10-15T07:02:00+09:00'
        records.append(conflicting)
        with self.assertRaises(SourceError):
            helper.merge(feed, [helper.observation('odds3t')], summary_only=False)

    def test_untouched_existing_bundle_still_obeys_merge_time_cutoff(self):
        helper = merge_fixtures.RaceUpdateMergeTests()
        late = helper.observation(capture='2026-10-15T09:00:00+09:00',
                                  saved='2026-10-15T09:01:00+09:00')
        feed = helper.merge(helper.feed(), [late], summary_only=False)
        with self.assertRaises(SourceError):
            merge_race_updates(feed, [], now=datetime.fromisoformat('2026-10-15T08:00:00+09:00'),
                               summary_only=False)

    def test_empty_batch_cannot_expand_existing_summary_to_full_history(self):
        helper = merge_fixtures.RaceUpdateMergeTests()
        summary = helper.merge(helper.feed(), [helper.observation()])
        with self.assertRaises(SourceError):
            helper.merge(summary, [], summary_only=False)


if __name__ == '__main__':
    unittest.main()
