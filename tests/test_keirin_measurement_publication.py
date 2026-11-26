from copy import deepcopy
from datetime import datetime, timezone
import json
import unittest

from race_ai import keirin_measurement_publication as publication
from race_ai import keirin_official_condition_scoring as trial
from race_ai import keirin_official_paired_measurement as official
from race_ai import keirin_paired_measurement as paired
from tests.test_keirin_daily_rider_update import PublicStore


DAY = '2026-11-27'
AT = datetime(2026, 11, 27, 14, tzinfo=timezone.utc)
INDEX = 'b' * 64


def report(hits=(False, True)):
    row = paired.MarketObservation(AT.isoformat(), DAY.replace('-', '') + '3101', 4,
                                   hits, (0.10, 0.25), (0, 1000))
    result = trial.summarize_day(DAY, [])
    result['eligible_paired_races'] = 1
    for market in result['markets']:
        result['markets'][market] = paired.summarize_market([row], market)
    return dict(schema=official.SCHEMA, state='OFFICIAL_SP_RESULT_ARCHIVE_MEASURED',
                day_jst=DAY, archive_commit='a' * 40,
                coverage=dict(official_registered_races=1, archived_baseline_races=1,
                              archived_result_races=1, official_order_replay_verified_races=1,
                              official_payout_verified_races=1, official_result_replay_held_races=0,
                              archived_baseline_without_result=0, registered_without_original=0,
                              cancelled_or_refunded_result_replays=0),
                comparisons={name: {'official_t15': {market: paired.summarize_market([row], market)
                                                      for market in official.MARKETS}}
                             for name in official.COMPARISONS},
                meeting_condition_trial=result)


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.store = PublicStore()

    def publish(self, value, *, index=INDEX, at=AT):
        return publication.publish_day(self.store, value, index_sha256=index, checked_at=at)

    def test_persists_day_and_cohort_with_equal_budget_stats(self):
        outcome = self.publish(report())
        head = outcome['commit']
        current = publication.read_day(self.store, head, DAY)
        market = current['official_t15']['baseline_A_vs_baseline_B']['trifecta_top4']
        self.assertEqual(market['trial']['hits'], 1)
        self.assertEqual(market['paired_races'], 1)
        self.assertEqual(market['virtual_returns']['trial']['stake_yen'], 400)
        self.assertEqual(current['index_sha256'], INDEX)
        cumulative = json.loads(self.store.read_previous(head, publication.LATEST))
        self.assertEqual(cumulative['cohort']['primary']['trifecta_top4']['trial_hits'], 1)
        self.assertEqual(self.store.read_previous(head, 'odds/2026-11-23.json'), b'preexisting')

    def test_unchanged_index_and_metrics_do_not_write_unrelated_head(self):
        self.publish(report())
        stale_head = self.store.head()
        same = dict(report(), archive_commit='c' * 40)
        self.publish(same, at=AT.replace(minute=1))
        self.assertEqual(self.store.head(), stale_head)
        self.assertEqual(self.store.published, 1)

    def test_revision_replaces_the_current_day_and_keeps_one_cohort_entry(self):
        first = self.publish(report())['commit']
        revised = self.publish(report((True, False)), index='c' * 64, at=AT.replace(minute=1))
        old = publication.read_day(self.store, first, DAY)
        self.assertEqual(old['meeting_condition_trial']['markets']['trifecta_top4']['trial']['hits'], 1)
        current = json.loads(self.store.read_previous(revised['commit'], publication.LATEST))
        self.assertEqual(current['cohort']['eligible_paired_races'], 1)
        self.assertEqual(current['cohort']['primary']['trifecta_top4']['trial_hits'], 0)

    def test_refuses_free_form_nested_strings_and_backwards_publication(self):
        self.publish(report())
        old = self.store.head()
        malformed = deepcopy(report())
        malformed['meeting_condition_trial']['markets']['exacta_top2']['published']['hits'] = '原本'
        with self.assertRaises(ValueError):
            self.publish(malformed, index='c' * 64)
        with self.assertRaises(ValueError):
            self.publish(report((True, False)), index='c' * 64, at=AT.replace(hour=13))
        self.assertEqual(old, self.store.head())
