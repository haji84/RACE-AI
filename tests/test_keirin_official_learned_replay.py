from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_official_learned_replay as replay


class OfficialLearnedReplayTests(unittest.TestCase):
    cards = ('202611273101', '202611273102')
    cutoff = '2026-11-27T21:00:00+09:00'
    started = core.when('2026-11-28T01:00:00+09:00')

    def setUp(self):
        metas = {rid: {'race_id': rid, 'cutoff_at': self.cutoff, 'evidence_sha256': 'a' * 64}
                 for rid in self.cards}
        self.store = SimpleNamespace(day='2026-11-27', head='a' * 40, index={
            'originals': metas, 'results': {rid: [{'race_id': rid}] for rid in self.cards}})
        self.events = []

    def invoke(self, freeze):
        def prepare(store, meta, private, **kwargs):
            self.events.append(('original', meta['race_id']))
            return dict(race_id=meta['race_id']), {'cars': [1, 2, 3, 4, 5],
                'official_A': [(1, 2, 3), (2, 3, 1)], 'official_B': [(3, 1, 2)], 'cutoff_at': self.cutoff}

        def predict(candidate, inputs):
            self.events.append(('predict', None))
            return [[{'order': (2, 3, 1), 'probability': .7},
                     {'order': (1, 2, 3), 'probability': .3}] for _ in inputs]

        def settle(store, meta, result, private, forecast):
            self.events.append(('result', meta['race_id']))
            return {(1, 2, 3): 2000, (2, 3, 1): 1000}, True

        with patch.object(replay, '_prepare', side_effect=prepare), \
                patch.object(replay, '_predict', side_effect=predict), \
                patch.object(replay, '_settle', side_effect=settle):
            return replay.run(self.store, None, (object(), {'temperature': 1.0}),
                              clock=lambda: self.started, freeze=freeze)

    def test_official_tickets_stay_in_saved_order_and_all_predictions_precede_results(self):
        def freeze(stage, payload):
            self.events.append(('freeze', stage))
            self.assertEqual(payload['predictions'][self.cards[0]]['official_B'], [(3, 1, 2)])
            return {'sealed_sha256': 'b' * 64}

        report = self.invoke(freeze)
        self.assertEqual(self.events, [('original', rid) for rid in self.cards] +
                         [('predict', None), ('freeze', 'forecasts')] + [('result', rid) for rid in self.cards])
        top1 = report['metrics']['trifecta_top1']
        self.assertEqual(top1['races'], 2)
        self.assertEqual({arm: item['hits'] for arm, item in top1['arms'].items()},
                         {'official_A': 2, 'official_B': 0, 'learned': 2})
        self.assertEqual(report['metrics']['trifecta_top2']['races'], 0)
        self.assertEqual(report['metrics']['trifecta_top2']['shorter_saved_ranking'], 2)

    def test_failed_encrypted_readback_leaves_results_unopened(self):
        def fail(stage, payload):
            raise OSError('fixture refuses write')

        with self.assertRaises(OSError):
            self.invoke(fail)
        self.assertTrue(all(operation != 'result' for operation, _ in self.events))
