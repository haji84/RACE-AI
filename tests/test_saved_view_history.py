"""Fictional originals: bounded encrypted dates retain their complete inventory."""
from copy import deepcopy
import importlib
from pathlib import Path
import tempfile
import unittest

from race_ai import saved_view_feed as F
from race_ai.boat_history_store import wire
from race_ai.boat_pdca_projection import project_pdca
from race_ai.boat_pdca_state import PdcaState, sha
from tests.test_boat_pdca_github_handoff import invented_research_state


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.H = importlib.import_module('race_ai.saved_view_history')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path, _ = invented_research_state(Path(self.tmp.name))
        state = PdcaState(path)
        try:
            self.seed = project_pdca(state)
        finally:
            state.close()
        self.anchor = F.originals_sha(self.seed)
        self.seed['forecast_base_sha256'] = self.anchor
        self.seed['records'][0]['saved_prediction_evidence'] = {'separate': 'actual-source-binding'}
        self.key = b'h' * 32
        self.view_id = 'a' * 64
        self.files = {}

    def add_day(self, view, day):
        out = deepcopy(view)
        row = deepcopy(self.seed['records'][0])
        row = __import__('json').loads(__import__('json').dumps(row).replace('2026-11-06', day).replace('20261106', day.replace('-', '')))
        out['records'].append(row)
        out['event_date_jst'] = None
        return out

    def store_days(self, view, commit='b' * 40, **options):
        built = self.H.encrypt_day_chunks(view, self.key, view_id=self.view_id, **options)
        for path, body in built['files'].items():
            self.files[(commit, path)] = body
        return self.H.bind_history_locators(built['days'], commit)

    def reader(self, locator):
        return self.files[(locator['commit'], 'views/' + locator['cipher_sha256'] + '.json')]

    def load_day(self, descriptor):
        return self.H.decrypt_day_chunks(descriptor, self.reader, self.key, view_id=self.view_id, forecast_sha256=self.anchor)

    def index(self, days, month='2026-11', previous=None):
        return self.H.build_history(days, current_month=month, previous_catalog=previous, forecast_sha256=self.anchor)

    def store_catalog(self, index, commit='c' * 40):
        built = self.H.encrypt_catalog(index, self.key, view_id=self.view_id)
        for path, body in built['files'].items():
            self.files[(commit, path)] = body
        return self.H.bind_history_locators(built['locator'], commit)

    def load_catalog(self, locator):
        return self.H.decrypt_catalog(self.reader(locator), self.key, view_id=self.view_id)

    def test_dates_restore_complete_native_predictions_and_separate_evidence(self):
        source = self.add_day(self.seed, '2026-11-07')
        before = deepcopy(source)
        days = self.store_days(source)
        self.assertEqual(set(days), {'2026-11-06', '2026-11-07'})
        union = {}
        for day, descriptor in days.items():
            restored = self.load_day(descriptor)
            self.assertEqual({row['event_date_jst'] for row in restored['records']}, {day})
            union.update(F.forecast_inventory(restored))
            self.assertEqual(restored['records'][0]['saved_prediction_evidence'], source['records'][0]['saved_prediction_evidence'])
        self.assertEqual(union, F.forecast_inventory(source))
        self.assertEqual(source, before)

    def test_chunk_bound_splits_only_between_complete_race_records(self):
        source = deepcopy(self.seed)
        for number in range(2, 9):
            row = deepcopy(source['records'][0]);row['race_id'] = '20261106-22-' + str(number).zfill(2);row['race_no'] = number
            source['records'].append(row)
        one = len(wire(dict(source, records=[source['records'][0]])).encode())
        days = self.store_days(source, chunk_plain_limit=one + 100)
        self.assertGreater(len(days['2026-11-06']['chunks']), 1)
        self.assertEqual(F.forecast_inventory(self.load_day(days['2026-11-06'])), F.forecast_inventory(source))
        self.assertTrue(all(len(body) <= self.H.MAX_CHUNK_WIRE for body in self.files.values()))

    def test_router_and_catalog_authenticate_same_view_id_key_and_legacy_anchor(self):
        index = self.index(self.store_days(self.seed))
        raw = self.H.encrypt_history_router(index, self.key, view_id=self.view_id, source_sha='d' * 64, generation=3, previous='e' * 64)
        header, decoded = self.H.decrypt_history_router(raw, self.key, view_id=self.view_id)
        self.assertEqual(header['schema'], self.H.HISTORY_FEED)
        self.assertEqual(header['forecast_sha256'], self.anchor)
        self.assertEqual(decoded, index)
        for body, key, ident in ((raw + b' ', self.key, self.view_id), (raw, b'x' * 32, self.view_id), (raw, self.key, 'f' * 64)):
            with self.assertRaises(ValueError):
                self.H.decrypt_history_router(body, key, view_id=ident)
        locator = self.store_catalog(index)
        self.assertEqual(self.load_catalog(locator), index)

    def test_missing_corrupt_or_reordered_day_chunks_fail_closed(self):
        descriptor = self.store_days(self.seed)['2026-11-06']
        original = self.reader(descriptor['chunks'][0])
        for reader in (lambda locator: b'', lambda locator: original + b' ', lambda locator: original[:-10]):
            with self.assertRaises(ValueError):
                self.H.decrypt_day_chunks(descriptor, reader, self.key, view_id=self.view_id, forecast_sha256=self.anchor)
        bad = deepcopy(descriptor);bad['forecast_inventory_sha256'] = 'f' * 64
        with self.assertRaises(ValueError):
            self.load_day(bad)

    def test_transition_checks_each_old_forecast_across_archives_and_current_day(self):
        source = self.add_day(self.seed, '2026-11-07')
        index = self.index(self.store_days(source))
        self.H.validate_history_transition(source, index, load_day=self.load_day, load_catalog=self.load_catalog)
        changed = deepcopy(source);changed['records'][0]['comparison_predictions'].pop()
        incomplete = self.index(self.store_days(changed, commit='d' * 40))
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_REMOVED_OR_CHANGED'):
            self.H.validate_history_transition(source, incomplete, load_day=self.load_day, load_catalog=self.load_catalog)
        missing = deepcopy(index);del missing['days']['2026-11-06']
        with self.assertRaises(ValueError):
            self.H.validate_history_transition(source, missing, load_day=self.load_day, load_catalog=self.load_catalog)

    def test_month_rollover_pins_old_catalog_and_bounds_new_router(self):
        november = self.index(self.store_days(self.seed))
        archived = self.store_catalog(november)
        december_view = self.add_day(self.seed, '2026-12-01');december_view['records'] = december_view['records'][1:];december_view['event_date_jst'] = '2026-12-01'
        december = self.index(self.store_days(december_view, commit='d' * 40), month='2026-12', previous=archived)
        self.H.validate_history_transition(november, december, load_day=self.load_day, load_catalog=self.load_catalog)
        self.assertEqual(set(december['days']), {'2026-12-01'})
        self.assertLess(len(wire(december).encode()), self.H.MAX_INDEX_PLAIN)
        erased = deepcopy(december);erased['previous_catalog'] = None
        with self.assertRaises(ValueError):
            self.H.validate_history_transition(november, erased, load_day=self.load_day, load_catalog=self.load_catalog)
        bad_archive = deepcopy(november);bad_archive['days'] = {}
        with self.assertRaises(ValueError):
            self.H.build_history({}, current_month='2026-11', forecast_sha256=self.anchor)

    def test_caps_are_daily_and_do_not_increase_existing_monolithic_limits(self):
        for count in (289,):
            view = deepcopy(self.seed)
            view['records'] = [dict(deepcopy(view['records'][0]), race_id='20261106-' + str(i).zfill(5)) for i in range(count)]
            with self.assertRaisesRegex(ValueError, 'DAY_RACE_BOUND'):
                self.store_days(view)
        with self.assertRaises(ValueError):
            self.store_days(self.seed, chunk_plain_limit=self.H.MAX_CHUNK_PLAIN + 1)
        self.assertEqual(self.H.MAX_DAY_PLAIN, 64 * 1024 * 1024)

    def test_december_can_revise_november_results_without_removing_any_november_original(self):
        november = self.index(self.store_days(self.seed))
        old_catalog = self.store_catalog(november)
        dec_view = self.add_day(self.seed, '2026-12-01');dec_view['records'] = dec_view['records'][1:]
        december_days = self.store_days(dec_view, commit='d' * 40)
        before = self.index(december_days, month='2026-12', previous=old_catalog)
        correction = deepcopy(self.seed);correction['records'][0]['result_revisions'] = [{'revision_no': 2, 'status': 'pending'}]
        corrected_november = self.index(self.store_days(correction, commit='e' * 40))
        corrected_catalog = self.store_catalog(corrected_november, commit='f' * 40)
        after = self.index(december_days, month='2026-12', previous=corrected_catalog)
        self.H.validate_history_transition(before, after, load_day=self.load_day, load_catalog=self.load_catalog)
        correction['records'][0]['comparison_predictions'].pop()
        incomplete = self.index(self.store_days(correction, commit='1' * 40))
        bad = self.index(december_days, month='2026-12', previous=self.store_catalog(incomplete, commit='2' * 40))
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_REMOVED_OR_CHANGED'):
            self.H.validate_history_transition(before, bad, load_day=self.load_day, load_catalog=self.load_catalog)

    def test_legacy_v3_multi_date_migration_preserves_its_whole_original_anchor(self):
        legacy = self.add_day(self.seed, '2026-11-07');legacy.pop('forecast_base_sha256')
        anchor = F.originals_sha(legacy)
        self.anchor = anchor
        current = self.index(self.store_days(legacy))
        self.H.validate_history_transition(legacy, current, load_day=self.load_day, load_catalog=self.load_catalog)

    def test_date_partitioning_has_no_global_five_thousand_race_union(self):
        view = dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1', event_date_jst=None,
                    dataset_status='SYNTHETIC_ONLY', forecast_base_sha256=self.anchor, records=[])
        for day_no in range(1, 21):
            day = '2030-04-' + str(day_no).zfill(2)
            for number in range(260):
                view['records'].append(dict(race_id=day.replace('-', '') + '-%02d-%02d' % (1 + number // 12, 1 + number % 12),
                    event_date_jst=day, prediction=dict(model_id='fictional-retained-model', stage='P0'), comparison_predictions=[]))
        days = self.store_days(view)
        self.assertEqual(len(days), 20)
        self.assertEqual(sum(descriptor['races'] for descriptor in days.values()), 5200)
        self.assertEqual(sum(descriptor['forecasts'] for descriptor in days.values()), 5200)
        for descriptor in days.values():
            self.assertEqual(len(self.load_day(descriptor)['records']), 260)

    def test_per_race_forecast_limit_matches_the_existing_browser(self):
        source = deepcopy(self.seed)
        source['records'][0]['comparison_predictions'] = [deepcopy(source['records'][0]['prediction']) for _ in range(128)]
        with self.assertRaisesRegex(ValueError, 'PER_RACE_FORECAST_BOUND'):
            self.store_days(source)


if __name__ == '__main__':
    unittest.main()
