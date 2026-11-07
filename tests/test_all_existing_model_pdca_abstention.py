"""Real native seller normalization shapes on invented races; no external I/O."""
from copy import deepcopy
from datetime import date, datetime
import unittest

from race_ai import all_existing_model_registry as registry
from race_ai.actions_contract import digest
from race_ai.all_existing_model_pdca import _aggregate, _score
from research.seller_shadow_v1 import model as seller
from tests.test_existing_special_parameter_adapters import SELLER, SELLER_AT, seller_payload


class NativeSellerAbstentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = seller_payload(count=6)
        for race, key in enumerate(cls.payload['cards'], 1):
            cls.payload['cards'][key]['艇1_全国勝率'] = str(5.7+.1*race)
            cls.payload['waku'][key]['艇1_枠番別勝率'] = str(8.8-.1*race)
        arguments = (cls.payload['cards'], cls.payload['waku'], date(2030, 1, 15),
                     datetime.fromisoformat(SELLER_AT))
        cls.baseline = seller.generate(*arguments)
        cls.learned = seller.generate(*arguments, parameters={'score_national_weight': 0, 'score_gap_weight': 0})
        filtered = deepcopy(cls.payload)
        for card in filtered['cards'].values():
            card['艇1_級別'] = 'B2'
        cls.filtered = seller.generate(filtered['cards'], filtered['waku'],
                                      date(2030, 1, 15), datetime.fromisoformat(SELLER_AT))

    def normalized(self, prediction, number):
        payload = dict(self.payload, race_id=f'2030011518{number:02d}', as_of=SELLER_AT,
                       cutoff_at='2030-01-15T14:00:00+09:00', scope='SYNTHETIC_ONLY')
        source = dict(source_ref='synthetic://seller-abstention-program', source_rights_ref='fictional-program',
                      source_sha256=digest(payload['cards']), captured_at=SELLER_AT)
        payload['source_evidence'] = [source]
        payload['registered_roster'] = dict(schema=registry.ROSTER_SCHEMA, sport='boat',
            race_id=payload['race_id'], as_of=SELLER_AT,
            roster={'1':'4101', '2':'4102', '3':'4103', '4':'4104', '5':'4105', '6':'4106'},
            native_input_sha256=digest({key:payload[key] for key in ('cards','waku','day')}), **source)
        return registry.normalize(SELLER, 'boat', payload, prediction)

    def observation(self, normalized=None):
        winner = normalized['top'][0] if normalized and normalized['top'] else [1, 2, 3]
        return dict(status='settled', ordered_top3=winner, payout_per_100_yen=1200, refund_numbers=[])

    def assert_zero_abstention(self, arm, status):
        self.assertEqual(arm['selection_status'], status)
        self.assertEqual(arm['ticket_count'], 0)
        self.assertEqual(arm['stake_yen'], 0)
        self.assertEqual(arm['payout_yen'], 0)
        self.assertEqual(arm['refund_yen'], 0)
        self.assertEqual(arm['net_yen'], 0)
        self.assertIsNone(arm['log_loss'])
        self.assertFalse(arm['hit'])

    def test_both_native_rank_limit_arms_have_zero_stakes_and_no_loss(self):
        abstained = self.normalized(self.baseline, 1)
        self.assertEqual(abstained['selection_status'], 'RANK_LIMIT')
        self.assertEqual(abstained['plans'], {})
        result = _score(dict(baseline_normalized=abstained, learned_normalized=deepcopy(abstained)),
                        self.observation())
        self.assertFalse(result['paired']); self.assertEqual(result['state'], 'NATIVE_ABSTENTION_UNPAIRED')
        for score in [result]+list(result['native_plan_variants'].values()):
            self.assert_zero_abstention(score['baseline'], 'RANK_LIMIT')
            self.assert_zero_abstention(score['learned'], 'RANK_LIMIT')

    def test_both_native_filtered_arms_are_abstentions(self):
        abstained = self.normalized(self.filtered, 1)
        self.assertEqual(abstained['selection_status'], 'FILTERED')
        self.assertEqual(abstained['plans'], {})
        result = _score(dict(baseline_normalized=abstained, learned_normalized=deepcopy(abstained)),
                        self.observation())
        self.assertFalse(result['paired'])
        for score in [result]+list(result['native_plan_variants'].values()):
            self.assert_zero_abstention(score['baseline'], 'FILTERED')
            self.assert_zero_abstention(score['learned'], 'FILTERED')

    def test_one_selected_arm_preserves_native_three_and_five_plan_units(self):
        for baseline, learned, abstained_arm, selected_arm in (
                (self.normalized(self.baseline, 1), self.normalized(self.learned, 1), 'baseline', 'learned'),
                (self.normalized(self.baseline, 6), self.normalized(self.learned, 6), 'learned', 'baseline')):
            with self.subTest(abstained_arm=abstained_arm):
                selected = baseline if selected_arm == 'baseline' else learned
                before = deepcopy((baseline, learned))
                result = _score(dict(baseline_normalized=baseline, learned_normalized=learned),
                                self.observation(selected))
                self.assertFalse(result['paired']); self.assertTrue(result['selection_plan_changed'])
                self.assertEqual(result['primary_native_plan'], 'five')
                for name, count in (('three', 3), ('five', 5)):
                    variant = result['native_plan_variants'][name]
                    self.assertFalse(variant['paired'])
                    self.assert_zero_abstention(variant[abstained_arm], 'RANK_LIMIT')
                    self.assertEqual(variant[selected_arm]['ticket_count'], count)
                    self.assertEqual(variant[selected_arm]['stake_yen'], sum(selected['plans'][name]['stakes']))
                    self.assertIsNone(variant[selected_arm]['log_loss'])
                self.assertEqual((baseline, learned), before)

    def test_filtered_and_selected_arms_remain_unpaired_in_aggregate(self):
        abstained = self.normalized(self.filtered, 2); selected = self.normalized(self.baseline, 2)
        result = _score(dict(baseline_normalized=abstained, learned_normalized=selected),
                        self.observation(selected))
        self.assert_zero_abstention(result['baseline'], 'FILTERED')
        board = _aggregate([dict(cell_key='boat/'+SELLER, forecast_record_sha256='f'*64, score=result)])['boat/'+SELLER]
        self.assertEqual(board['paired_forecasts'], 0)
        for variant in board['native_plan_variants'].values():
            self.assertEqual(variant['paired_forecasts'], 0)
            for arm in ('baseline', 'learned'):
                self.assertEqual(variant[arm]['forecasts'], 0)
                self.assertIsNone(variant[arm]['roi'])
                self.assertIsNone(variant[arm]['mean_log_loss'])

    def test_empty_variants_cannot_mask_a_nonempty_primary_plan(self):
        selected = self.normalized(self.baseline, 2); malformed = dict(selected, plans={})
        with self.assertRaisesRegex(ValueError, 'NATIVE_ABSTENTION_PLAN_INVALID'):
            _score(dict(baseline_normalized=malformed, learned_normalized=selected), self.observation(selected))


if __name__ == '__main__':
    unittest.main()
