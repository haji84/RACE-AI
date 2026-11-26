"""Contract tests for equal-budget metrics based on authenticated daily replays."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from race_ai import keirin_official_paired_measurement as measurement

DAY = '2026-11-27'
RACES = [f'2026112731{number:02d}' for number in range(1, 6)]
PICKS = [[1, 2, 3], [2, 1, 3], [1, 3, 2], [2, 3, 1],
         [3, 1, 2], [3, 2, 1], [4, 1, 2], [4, 2, 1]]


def replay(race_id, *, late=False, money=True, adjusted=True):
    cutoff = DAY + 'T01:45:00Z'
    evidence = DAY + ('T01:31:00Z' if late else 'T01:30:00Z')
    baseline = dict(A={'ranked_tickets': PICKS}, B={'ranked_tickets': PICKS[1:]})
    conditioned = dict(A_research={'ranked_tickets': PICKS[1:]+PICKS[:1]},
                       B_research={'ranked_tickets': PICKS})
    original = dict(race_id=race_id, baseline=baseline, conditioned=conditioned if adjusted else None,
                    baseline_sealed_at=DAY+'T01:20:00Z', conditioned_sealed_at=DAY+'T01:21:00Z',
                    snapshot=dict(riders=[dict(car=i) for i in range(1, 6)], competition='CHALLENGE',
                                  round_stage='A級チャレンジ準決勝', line_groups=[[1, 2], [3, 4], [5]]))
    official = dict(race_id=race_id, official_cutoff_at=cutoff, status='FINAL_NORMAL', refund_status='NONE',
                    winning_triples=[PICKS[0]], payouts_100yen=[dict(triple=PICKS[0], yen=800)])
    origins = dict(baseline_origin={'latest_server_evidence_at': evidence},
                   condition_origin={'latest_server_evidence_at': evidence} if adjusted else None)
    scored = dict(official_result=official, origin_receipts=origins, monetary_comparison_eligible=money)
    return original, scored, {}


class OfficialPairedMeasurementTests(TestCase):
    def score(self, **options):
        store = SimpleNamespace(day=DAY, head='a'*40, index=dict(registry={'identity':'registry'},
            originals={rid:{'race_id':rid} for rid in RACES[:4]},
            results={rid:[{'evidence_sha256':'a'*64}, {'evidence_sha256':'b'*64}] for rid in RACES[:3]}))
        store.read = lambda meta, key: meta
        def replay_latest(store_, original_meta, result_meta, key):
            self.assertEqual(result_meta['evidence_sha256'], 'b'*64)
            rid = original_meta['race_id']
            if rid == RACES[2]:
                raise ValueError('invented evidence hold')
            return replay(rid, late=rid == RACES[1], money=rid == RACES[1], adjusted=rid == RACES[0])
        with patch.object(measurement.records, 'replay_registry', return_value={
            'event_day': DAY, 'registered_race_ids': RACES
        }), patch.object(measurement.records, '_replay_saved_result', side_effect=replay_latest):
            return measurement.measure_day(store, b'mock key', **options)

    def test_measures_official_daily_denominator_and_never_scores_held_originals(self):
        report = self.score()
        self.assertEqual(report['coverage'], dict(official_registered_races=5, archived_baseline_races=4,
            archived_result_races=3, official_order_replay_verified_races=2, official_payout_verified_races=1,
            official_result_replay_held_races=1, archived_baseline_without_result=1, registered_without_original=1,
            cancelled_or_refunded_result_replays=0))
        self.assertEqual(report['result_replay_holds'], {'ARCHIVE_REPLAY_VALIDATION_HELD': 1})
        scope = report['comparisons']['baseline_A_vs_baseline_B']
        cutoff_scores = scope['all_pre_cutoff']
        self.assertEqual(cutoff_scores['trifecta_top4']['paired_races'], 2)
        self.assertEqual(cutoff_scores['trifecta_top4']['virtual_returns']['paired_races'], 1)
        self.assertEqual(cutoff_scores['trifecta_top4']['virtual_returns']['published']['payout_yen'], 800)
        self.assertEqual(cutoff_scores['trifecta_top4']['virtual_returns']['trial']['payout_yen'], 0)
        self.assertEqual(cutoff_scores['trifecta_top8']['paired_races'], 0)
        self.assertEqual(scope['official_t15']['trifecta_top4']['paired_races'], 1)
        self.assertEqual(scope['official_t15']['trifecta_top4']['virtual_returns']['paired_races'], 0)
        self.assertEqual(scope['subgroups_t15']['round_stage']['A級チャレンジ準決勝']['paired_races'], 1)
        self.assertEqual(scope['subgroups_t15']['competition']['CHALLENGE']['paired_races'], 1)
        self.assertEqual(scope['subgroups_t15']['largest_line_size']['2']['paired_races'], 1)

    def test_conditioned_comparison_does_not_infer_probabilities_or_unavailable_market(self):
        report = self.score()
        arm = report['comparisons']['baseline_A_vs_conditioned_A']['official_t15']
        self.assertEqual(arm['trifecta_top4']['paired_races'], 1)
        self.assertEqual(arm['trifecta_top4']['lost'], 1)
        self.assertEqual(arm['trifecta_top4']['trial']['calibration']['state'], 'NO_PAIRED_PROBABILITIES')
        self.assertNotIn('exacta_top2', arm)
        self.assertEqual(report['adoption_status'], 'HOLD_OFFICIAL_PROSPECTIVE_PRODUCT_EVALUATION_INCOMPLETE')
        for rid in RACES:
            self.assertNotIn(rid, str(report))

    def test_no_day_registration_is_an_explicit_hold(self):
        store = SimpleNamespace(day=DAY, head='a'*40, index=dict(registry=None, originals={}, results={}))
        report = measurement.measure_day(store, b'mock key')
        self.assertEqual(report['state'], 'HOLD_OFFICIAL_CALENDAR_UNAVAILABLE')
        self.assertIsNone(report['coverage']['official_registered_races'])

    def test_no_condition_attestation_cannot_promote_a_baseline_result(self):
        calls = []
        def admit(store, original_meta, result_meta, key):
            calls.append(original_meta['race_id'])
            return None
        report = self.score(admit_condition_pair=admit)
        self.assertEqual(calls,RACES[:2])
        condition = report['meeting_condition_trial']
        self.assertEqual(condition['coverage']['no_admitted_condition_pair'], 2)
        self.assertEqual(condition['eligible_paired_races'], 0)
        self.assertEqual(report['coverage']['official_order_replay_verified_races'], 2)
