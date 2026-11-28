"""Synthetic checks only, never actual-race evidence."""
from itertools import permutations
import unittest
from scripts import keirin_dt_r1_future_settle as settle
from scripts import keirin_dt_r1_future_shadow as shadow

DAY = '2026-11-28'
RACES = ['202611282401', '202611282402', '202611282403']


def forecast(rid):
    triples = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 3)]
    exactas = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 2)]
    return dict(race_id=rid, day=DAY, status='READY', model_sha256=shadow.MODEL_SHA,
                input_sha256='a'*64, trifectas=triples, exactas=exactas)


class FutureSettlementTests(unittest.TestCase):
    def entries(self):
        return [dict(slot_sha256=shadow.slot(DAY, rid),
                     state=shadow.READY if i < 2 else 'HOLD') for i,rid in enumerate(RACES)]

    def test_originals_before_results_and_holds_remain_in_denominator(self):
        events = []
        def load_forecast(entry, rid):
            events.append('forecast')
            if rid == RACES[1]:
                raise ValueError('replay mismatch')
            return forecast(rid)
        def result(rid):
            events.append('result')
            return dict(race_id=rid, day=DAY, top3=[1,2,3], result_status='VERIFIED_NORMAL')
        report = settle._score_registered(RACES, DAY, self.entries(),
            [shadow.slot(DAY,rid) for rid in RACES[:2]], load_forecast, result)
        self.assertEqual(events, ['forecast','forecast','result','result','result'])
        self.assertEqual(report['registered_races'], 3)
        self.assertEqual(report['owner_originals_replayed'], 1)
        self.assertEqual(report['metrics']['evaluable'], 3)
        self.assertEqual(report['metrics']['predicted_evaluable'], 1)
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 1)
        self.assertAlmostEqual(report['metrics']['trifecta']['1']['all_target_rate'], 1/3)
        self.assertEqual(report['metrics']['trifecta']['1']['predicted_rate'], 1)

    def test_pending_result_does_not_become_miss(self):
        report = settle._score_registered(RACES, DAY, self.entries(), [],
            lambda e,r: self.fail('late forecast opened'),
            lambda r: dict(race_id=r,day=DAY,result_status='MISSING_SAVED_RESULT'))
        self.assertEqual(report['metrics']['evaluable'], 0)
        self.assertIsNone(report['metrics']['trifecta']['1']['all_target_rate'])

    def test_duplicate_or_held_slot_cannot_be_admitted(self):
        one = shadow.slot(DAY,RACES[0])
        for eligible in ([one,one],[shadow.slot(DAY,RACES[2])],['f'*64]):
            with self.subTest(eligible=eligible), self.assertRaisesRegex(ValueError, 'REGISTRY_SLOT_MISMATCH'):
                settle._score_registered(RACES,DAY,self.entries(),eligible,
                    lambda e,r:self.fail('invalid forecast opened'),
                    lambda r:self.fail('invalid result opened'))

    def test_wrong_result_identity_stops_scoring(self):
        with self.assertRaisesRegex(ValueError, 'RESULT_IDENTITY'):
            settle._score_registered(RACES,DAY,self.entries(),[],
                lambda e,r:self.fail('unexpected forecast'),
                lambda r:dict(race_id='different',day=DAY,result_status='MISSING_SAVED_RESULT'))


if __name__ == '__main__':
    unittest.main()
