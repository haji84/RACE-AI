"""Synthetic checks only, never actual-race evidence."""
from itertools import permutations
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import keirin_dt_r1_future_settle as settle
from scripts import keirin_dt_r1_future_shadow as shadow

DAY = '2026-11-28'
RACES = ['202611282401', '202611282402', '202611282403']


def forecast(rid):
    triples = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 3)]
    exactas = [dict(cars=list(t), probability=1/6) for t in permutations((1,2,3), 2)]
    return dict(race_id=rid, day=DAY, status='READY', model_sha256=shadow.MODEL_SHA,
                input_sha256='a'*64, riders=[{'car': car} for car in (1, 2, 3)],
                trifectas=triples, exactas=exactas)


class FutureSettlementTests(unittest.TestCase):
    def entries(self):
        return [dict(slot_sha256=shadow.slot(DAY, rid),
                     state=shadow.READY if i < 2 else 'HOLD',
                     reason=None if i < 2 else 'SAVED_ORIGINAL_MISSING',
                     clocks=dict(seal_started_at=DAY + 'T01:00:00Z', cutoff_at=DAY + 'T01:30:00Z'))
                for i,rid in enumerate(RACES)]

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
            [shadow.slot(DAY,rid) for rid in RACES[:2]], {}, load_forecast, result)
        self.assertEqual(events, ['forecast','forecast','result','result','result'])
        self.assertEqual(report['registered_races'], 3)
        self.assertEqual(report['owner_originals_replayed'], 1)
        self.assertEqual(report['metrics']['evaluable'], 3)
        self.assertEqual(report['metrics']['predicted_evaluable'], 1)
        self.assertEqual(report['metrics']['trifecta']['1']['hits'], 1)
        self.assertAlmostEqual(report['metrics']['trifecta']['1']['all_target_rate'], 1/3)
        self.assertEqual(report['metrics']['trifecta']['1']['predicted_rate'], 1)
        self.assertEqual(report['forecast_holds'], {
            'SAVED_ORIGINAL_MISSING': 1, 'FORECAST_REPLAY_UNVERIFIED': 1})
        self.assertNotIn('proper_scores', report['metrics'])
        self.assertEqual(report['pdca'], {
            'fixed_trifecta_points': 4, 'placing_checked': 1, 'flow_checked': 0,
            'grade_counts': {'E': 1}})

    def late_slots(self):
        return {shadow.slot(DAY, rid): 'SERVER_READBACK_AFTER_T15' for rid in RACES[:2]}

    def test_late_reader_and_missing_original_are_distinct_registered_holds(self):
        report = settle._score_registered(RACES, DAY, self.entries(), [], self.late_slots(),
            lambda e,r: self.fail('late forecast opened'),
            lambda r: dict(race_id=r, day=DAY, result_status='MISSING_SAVED_RESULT'))
        self.assertEqual(report['registered_races'], 3)
        self.assertEqual(report['forecast_holds'], {
            'SERVER_READBACK_AFTER_T15': 2, 'SAVED_ORIGINAL_MISSING': 1})
        self.assertEqual(sum(report['forecast_holds'].values()), report['registered_races'])

    def test_nowhere_to_replay_is_distinct_from_missing_official_result(self):
        store = SimpleNamespace(day=DAY, index=dict(originals={RACES[0]: {}}, results={}))
        self.assertEqual(settle._result_row(store, RACES[0], b'', None, None)['result_status'],
                         'MISSING_SAVED_RESULT')
        self.assertEqual(settle._result_row(store, RACES[1], b'', None, None)['result_status'],
                         'NO_SAVED_OFFICIAL_ORIGINAL')

    def test_unverified_latest_revision_never_falls_back(self):
        original = {'original': 1}
        old = {'revision': 1, 'observed_at': DAY + 'T02:00:00Z'}
        latest = {'revision': 2, 'observed_at': DAY + 'T03:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [old, latest]}))
        seen = []

        def replay(saved_store, saved_original, meta, private):
            seen.append(meta)
            raise ValueError('untrusted revision detail')

        with patch.object(settle.records, '_replay_saved_result', side_effect=replay):
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_status'], 'RESULT_REPLAY_UNVERIFIED')
        self.assertEqual(row['result_hold_reason'], 'OFFICIAL_RESULT_REPLAY_FAILED')
        self.assertEqual(seen, [latest])
        self.assertNotIn('top3', row)

    def test_result_replay_reuses_existing_safe_failure_classification(self):
        original = {'original': 1}
        latest = {'observed_at': DAY + 'T03:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [latest]}))
        with patch.object(settle.records, '_replay_saved_result',
                          side_effect=ValueError('OFFICIAL_SP_RECORD_SAVED_RESULT_NOT_REPRODUCIBLE')):
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_hold_reason'], 'SAVED_SCORE_REPLAY_HELD')

    def test_out_of_order_result_revisions_are_held_before_opening_any_result(self):
        original = {'original': 1}
        newer = {'observed_at': DAY + 'T03:00:00Z'}
        older = {'observed_at': DAY + 'T02:00:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(
            originals={RACES[0]: original}, results={RACES[0]: [newer, older]}))
        with patch.object(settle.records, '_replay_saved_result',
                          side_effect=AssertionError('Unordered revisions must not be opened')) as replay:
            row = settle._result_row(store, RACES[0], b'', original, None)
        self.assertEqual(row['result_status'], 'RESULT_REPLAY_UNVERIFIED')
        self.assertEqual(row['result_hold_reason'], 'RESULT_REVISION_ORDER_UNVERIFIED')
        replay.assert_not_called()

    def test_pending_result_does_not_become_miss(self):
        report = settle._score_registered(RACES, DAY, self.entries(), [], self.late_slots(),
            lambda e,r: self.fail('late forecast opened'),
            lambda r: dict(race_id=r,day=DAY,result_status='MISSING_SAVED_RESULT'))
        self.assertEqual(report['metrics']['evaluable'], 0)
        self.assertIsNone(report['metrics']['trifecta']['1']['all_target_rate'])

    def test_duplicate_or_held_slot_cannot_be_admitted(self):
        one = shadow.slot(DAY,RACES[0])
        for eligible in ([one,one],[shadow.slot(DAY,RACES[2])],['f'*64]):
            with self.subTest(eligible=eligible), self.assertRaisesRegex(ValueError, 'REGISTRY_SLOT_MISMATCH'):
                settle._score_registered(RACES,DAY,self.entries(),eligible,{},
                    lambda e,r:self.fail('invalid forecast opened'),
                    lambda r:self.fail('invalid result opened'))

    def test_wrong_result_identity_stops_scoring(self):
        with self.assertRaisesRegex(ValueError, 'RESULT_IDENTITY'):
            settle._score_registered(RACES,DAY,self.entries(),[],self.late_slots(),
                lambda e,r:self.fail('unexpected forecast'),
                lambda r:dict(race_id='different',day=DAY,result_status='MISSING_SAVED_RESULT'))


if __name__ == '__main__':
    unittest.main()
