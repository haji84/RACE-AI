"""Synthetic checks only, never actual-race evidence."""
from itertools import permutations
from pathlib import Path
from tempfile import TemporaryDirectory
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

    def test_official_precutoff_cancellation_is_neutral_but_early_finish_is_held(self):
        rid = RACES[0]
        original = {'cutoff_at': DAY + 'T03:00:00Z'}
        revision = {'observed_at': DAY + 'T02:55:00Z'}
        store = SimpleNamespace(day=DAY, index=dict(originals={rid: original}, results={rid: [revision]}))
        final = dict(race_id=rid, official_cutoff_at=original['cutoff_at'],
                     observed_at=DAY + 'T02:50:00Z')
        for status, refund, expected in (
            ('CANCELLED', 'FULL', 'OFFICIAL_CANCELLED'),
            ('FINAL_NORMAL', 'NONE', 'RESULT_REPLAY_UNVERIFIED'),
        ):
            with self.subTest(status=status), patch.object(settle.records, '_replay_saved_result',
                    return_value=(None, {'official_result': dict(final, status=status, refund_status=refund)}, None)):
                row = settle._result_row(store, rid, b'', original, settle.clock(DAY + 'T02:59:00Z'))
            self.assertEqual(row['result_status'], expected)
            self.assertNotIn('top3', row)

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

    def test_archived_day_combines_first_slots_and_keeps_latest_registered_denominator(self):
        legacy_rid, later_rid, hold_rid = RACES
        added_rid = '202611282404'
        legacy_slot, later_slot, hold_slot = [shadow.slot(DAY, rid) for rid in RACES]
        registry_meta = dict(cipher_sha256='a'*64, evidence_sha256='b'*64)
        def store(head, race_ids, original_ids, *, complete=True):
            return SimpleNamespace(day=DAY, head=head,
                index=dict(registry=registry_meta, originals={rid: {'source': rid} for rid in original_ids}),
                read=lambda *_: dict(event_day=DAY, registered_race_ids=race_ids,
                                     day_inventory_complete=complete, missing_venues=[] if complete else ['98']))
        old = store(settle.PARENT, RACES, RACES[:1])
        later = store('c'*40, RACES, RACES[:2])
        current = store('d'*40, [*RACES, added_rid], RACES, complete=False)
        def batch(source, ready):
            entries = [dict(entry, state=shadow.READY if entry['slot_sha256'] in ready else 'HOLD')
                       for entry in self.entries()]
            return dict(summary=dict(source_archive_commit=source.head, day_jst=DAY, reader_run_id=source.head),
                        registry=registry_meta, entries=entries)
        old_manifest = batch(old, [legacy_slot])
        old_manifest['entries'][0]['cipher'] = {'file': 'first.sealed.json'}
        later_manifest = batch(later, [later_slot])
        additional = {later_slot: dict(entry=later_manifest['entries'][1], manifest=later_manifest,
                                       cipher_path='verified/later.sealed.json')}
        events = []
        def forecast_replay(entry, raw, manifest, source, rid, *args, history_sources, history_controls):
            events.append(('forecast', rid, source.head))
            self.assertEqual(raw, b'first' if rid == legacy_rid else b'later')
            self.assertEqual(history_sources, {})
            if rid == later_rid:
                history_controls[rid] = forecast(rid)
            return forecast(rid)
        def result_replay(source, rid, key, original_meta, now):
            events.append(('result', rid, source.head))
            self.assertEqual(original_meta, current.index['originals'].get(rid) if rid in RACES[:2] else None)
            return dict(race_id=rid, day=DAY, result_status='VERIFIED_NORMAL', top3=[1,2,3])
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'first.sealed.json').write_bytes(b'first')
            legacy = (dict(manifest=old_manifest, directory=directory),
                      dict(eligible_slots=[legacy_slot], held_slots={hold_slot: 'SERVER_READBACK_AFTER_T15'}))
            with (
                patch.object(settle.batch_retention, 'read_retained_forecasts', return_value=additional),
                patch.object(settle.records, 'replay_registry', side_effect=lambda payload: payload),
                patch.object(settle.records, 'RecordStore', side_effect=lambda _, __, *, index_commit:
                             {old.head: old, later.head: later}[index_commit]),
                patch.object(settle.archive, 'read_blob_bytes', return_value=b'later'),
                patch.object(settle, '_forecast_from_original', side_effect=forecast_replay),
                patch.object(settle, '_result_row', side_effect=result_replay),
            ):
                report = settle._score_archived_day(None, current, b'', None, None, None, lambda: None, legacy)
                additional[legacy_slot] = additional[later_slot]
                with self.assertRaisesRegex(ValueError, 'DUPLICATE_FIRST_SLOT'):
                    settle._score_archived_day(None, current, b'', None, None, None, lambda: None, legacy)
        self.assertEqual(events[:2], [('forecast', legacy_rid, old.head), ('forecast', later_rid, later.head)])
        self.assertEqual(events[2:], [('result', rid, current.head) for rid in [*RACES, added_rid]])
        self.assertEqual(report['registered_races'], 4)
        self.assertEqual(report['owner_originals_replayed'], 2)
        self.assertEqual(report['metrics']['predicted_evaluable'], 2)
        paired = report['metrics']['paired_history']
        self.assertEqual((paired['registered_day'], paired['retained_pairs']), (4, 1))
        self.assertEqual(paired['official_history']['predicted_evaluable'], 1)
        self.assertEqual(paired['no_history']['predicted_evaluable'], 1)
        self.assertNotIn('proper_scores', paired['no_history'])
        self.assertFalse(report['day_inventory_complete'])
        self.assertEqual(report['missing_venues'], 1)
        self.assertEqual(report['timed_originals'], {'legacy': 1, 'additional': 1})
        self.assertEqual(report['forecast_holds'], {'SERVER_READBACK_AFTER_T15': 1, 'SAVED_ORIGINAL_MISSING': 1})


if __name__ == '__main__':
    unittest.main()
