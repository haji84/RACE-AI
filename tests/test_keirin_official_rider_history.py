"""Project synthetic replay outputs; the official records suite tests the real source replay."""
from copy import deepcopy
from datetime import datetime, timezone
from importlib import import_module, util
import json
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_official_nationwide_records as records

DAY = '2026-11-25'
RACE = '202611252601'
TARGET = '202611262601'
DAY_CUTOFF = '2026-11-25T05:00:00Z'
TARGET_CUTOFF = '2026-11-26T05:00:00Z'
NOW = datetime(2026, 11, 25, 15, tzinfo=timezone.utc)


def metadata(kind, digest, observed_at):
    meta = dict(kind=kind, race_id=RACE, cipher_sha256=digest * 64,
                evidence_sha256=digest * 64, producer_run_id='1234',
                producer_commit='c' * 40, observed_at=observed_at)
    if kind == 'original':
        meta.update(cutoff_at=DAY_CUTOFF, baseline_cipher_sha256='a' * 64)
    else:
        meta['monetary_complete'] = False
    return meta


class OfficialRiderHistoryTests(unittest.TestCase):
    def setUp(self):
        path = 'race_ai.keirin_official_rider_history'
        self.assertIsNotNone(util.find_spec(path), 'official result-to-history projection is missing')
        self.module = import_module(path)
        self.original_meta = metadata('original', '1', '2026-11-25T04:00:00Z')
        self.first = metadata('result', '2', '2026-11-25T06:02:00Z')
        self.second = metadata('result', '3', '2026-11-25T07:02:00Z')
        self.index = dict(schema=records.INDEX_SCHEMA, day_jst=DAY, registry=None,
                          originals={RACE:self.original_meta}, results={RACE:[self.first]})
        self.store = SimpleNamespace(head='b'*40, index_commit='b'*40, index=self.index, day=DAY)
        starters = [dict(car=i, registration_id=f'{14000+i:06d}') for i in range(1, 6)]
        self.original = dict(race_id=RACE, day_jst=DAY,
                             baseline=dict(published_cutoff_at=DAY_CUTOFF),
                             snapshot=dict(riders=[dict(car=r['car'], athlete_id=r['registration_id'])
                                                   for r in starters]))
        self.final = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1', race_id=RACE,
                          status='FINAL_NORMAL', refund_status='NONE', starters=starters,
                          finishes=[dict(**row, status=state, place=place)
                                    for row, (state, place) in zip(starters, [
                                        ('FINISHED', 1), ('FINISHED', 2), ('FALL_FINISHED', 2),
                                        ('FALL_DNF', None), ('DISQUALIFIED', None)])],
                          official_cutoff_at=DAY_CUTOFF, source_sha256='d'*64,
                          source_updated_at='2026-11-25T06:00:00Z', observed_at='2026-11-25T06:01:00Z')
        self.answers = {self.first['evidence_sha256']:self.final}
        self.seen = []

    def project(self, **options):
        def replay(store, original_meta, result_meta, pem):
            self.assertIs(store, self.store)
            self.assertEqual(original_meta, self.original_meta)
            self.seen.append(result_meta['evidence_sha256'])
            result = self.answers[result_meta['evidence_sha256']]
            if isinstance(result, Exception):
                raise result
            return self.original, {'official_result':result}, {}
        args = dict(target_race_id=TARGET, target_cutoff_at=TARGET_CUTOFF,
                    knowledge_as_of=NOW, clock=lambda: NOW)
        with patch.object(records, '_replay_saved_result', side_effect=replay):
            return self.module.project_day(self.store, b'synthetic', **(args | options))

    def correction(self):
        corrected = deepcopy(self.final)
        corrected.update(source_updated_at='2026-11-25T07:00:00Z',
                         observed_at='2026-11-25T07:01:00Z', source_sha256='e'*64)
        corrected['finishes'][0]['place'], corrected['finishes'][1]['place'] = 2, 1
        self.index['results'][RACE].append(self.second)
        self.answers[self.second['evidence_sha256']] = corrected
        return corrected

    def test_ties_exceptional_status_unknowns_and_safe_receipt(self):
        view = self.project()
        self.assertEqual(view.receipt['numeric_finishes'], 3)
        self.assertEqual(view.receipt['non_numeric_finishes'], 2)
        self.assertEqual(view.receipt['tied_races'], 1)
        self.assertEqual(view.finish_history('014003')['periods']['all']['finish_counts'][2], 1)
        self.assertEqual(view.finish_history('014004')['periods']['all']['observed_count'], 0)
        self.assertIsNone(view.finish_history('014004')['periods']['all']['missing_finish_count'])
        self.assertEqual(view.private_races[RACE]['finishes'][-2]['status'], 'FALL_DNF')
        summary = json.dumps(view.receipt)
        for private_value in [RACE, TARGET, '014003', 'FALL_DNF', self.final['source_sha256']]:
            self.assertNotIn(private_value, summary)
        self.assertNotIn('014003', repr(view))

    def test_correction_replaces_one_start_and_preserves_revision_provenance(self):
        self.correction()
        view = self.project()
        stats = view.finish_history('014001')['periods']['all']
        self.assertEqual((stats['observed_count'], stats['finish_counts'][2]), (1, 1))
        self.assertEqual([row['evidence_sha256'] for row in view.private_races[RACE]['revisions']],
                         [self.first['evidence_sha256'], self.second['evidence_sha256']])

    def test_future_revision_never_supplants_eligible_earlier_source(self):
        self.correction()
        view = self.project(knowledge_as_of='2026-11-25T07:01:59Z')
        self.assertEqual(self.seen, [self.first['evidence_sha256']])
        self.assertEqual(view.finish_history('014001')['periods']['all']['finish_counts'][1], 1)
        self.assertNotIn(self.second['evidence_sha256'], repr(view.private_races))
        self.assertEqual(self.project(knowledge_as_of='2026-11-25T05:59:00Z').receipt['admitted_races'], 0)

    def test_duplicate_replay_or_payout_revision_is_one_start(self):
        self.index['results'][RACE] += [deepcopy(self.first), self.second]
        self.answers[self.second['evidence_sha256']] = self.final
        view = self.project()
        self.assertEqual(view.finish_history('014001')['periods']['all']['observed_count'], 1)
        self.assertEqual(len(view.private_races[RACE]['revisions']), 2)

    def test_invalid_eligible_correction_holds_race_and_preserves_other_starts(self):
        corrected = self.correction()
        valid = deepcopy(corrected)
        for failure in [ValueError('PRIVATE_MARKER'), dict(valid, source_updated_at=self.final['source_updated_at']),
                        dict(valid, observed_at='2026-11-25T08:00:00Z')]:
            with self.subTest(failure=type(failure).__name__):
                self.answers[self.second['evidence_sha256']] = failure
                view = self.project()
                self.assertEqual(view.receipt['held_races'], 1)
                self.assertEqual(view.finish_history('014001')['periods']['all']['observed_count'], 0)
                self.assertNotIn('PRIVATE_MARKER', json.dumps(view.receipt))

    def test_roster_cutoff_and_status_binding(self):
        for mutate in [lambda f:f['starters'][0].update(registration_id='099999'),
                       lambda f:f['finishes'][0].update(car=2),
                       lambda f:f['finishes'][0].update(status='UNKNOWN'),
                       lambda f:f.update(race_id=TARGET),
                       lambda f:f.update(official_cutoff_at='2026-11-25T06:30:00Z')]:
            with self.subTest(mutation=mutate):
                result = deepcopy(self.final)
                mutate(result)
                self.answers[self.first['evidence_sha256']] = result
                self.assertEqual(self.project().receipt['held_races'], 1)

    def test_rejects_unpinned_store_same_day_forecast_and_future_knowledge(self):
        for options in [dict(target_race_id=RACE, target_cutoff_at=DAY_CUTOFF),
                        dict(target_cutoff_at='2026-11-24T10:00:00Z'),
                        dict(knowledge_as_of='2026-11-26T05:00:00Z'),
                        dict(clock=lambda: datetime(2026, 11, 25, 13, tzinfo=timezone.utc))]:
            with self.assertRaises(ValueError):
                self.project(**options)
        self.store.index_commit = None
        with self.assertRaises(ValueError):
            self.project()

    def test_archive_revision_cannot_precede_its_original_and_replay_clock_cannot_regress(self):
        self.original_meta['observed_at'] = '2026-11-25T06:03:00Z'
        self.assertEqual(self.project().receipt['held_races'], 1)
        self.original_meta['observed_at'] = '2026-11-25T04:00:00Z'
        times = iter([NOW, datetime(2026, 11, 25, 14, tzinfo=timezone.utc)])
        with self.assertRaises(ValueError):
            self.project(knowledge_as_of='2026-11-25T08:00:00Z', clock=lambda: next(times))

    def test_original_receipt_and_replayed_cutoff_must_match_exactly(self):
        self.original_meta['cutoff_at'] = '2026-11-25T05:00:00.000001Z'
        self.assertEqual(self.project().receipt['held_races'], 1)

    def test_future_archived_original_is_excluded_from_as_of_coverage(self):
        extra_id = '202611252602'
        self.index['originals'][extra_id] = dict(self.original_meta, race_id=extra_id,
                                                observed_at='2026-11-25T14:00:00Z')
        result = self.project(knowledge_as_of='2026-11-25T13:00:00Z')
        self.assertEqual(result.receipt['originals_by_as_of'], 1)
        self.assertEqual(result.receipt['no_result_by_as_of'], 0)

    def test_bad_lower_rank_gap_is_held_even_when_podium_is_valid(self):
        for row in self.final['finishes']:
            row.update(status='FINISHED', place=row['car'])
        self.final['finishes'][3]['place'] = 5
        self.assertEqual(self.project().receipt['held_races'], 1)

    def test_later_replay_is_descriptive_and_never_claims_forecast_authentication(self):
        report = self.project(clock=lambda: datetime(2026, 11, 27, tzinfo=timezone.utc)).receipt
        self.assertFalse(report['replayed_before_target_cutoff'])
        self.assertFalse(report['forecast_original_authenticated'])
        self.assertFalse(report['historical_as_of_authenticated'])

    def test_dossier_queries_same_histories_without_claiming_a_forecast_deadline(self):
        project = getattr(self.module, 'project_day_for_dossier', None)
        self.assertIsNotNone(project, 'A day-only dossier entry point is required')
        race_history = self.project()
        with patch.object(records, '_replay_saved_result',
                          return_value=(self.original, {'official_result': self.final}, {})):
            view = project(self.store, b'synthetic', target_day='2026-11-26', knowledge_as_of=NOW, clock=lambda: NOW)
        self.assertEqual(view.finish_history('014001'), race_history.finish_history('014001'))
        self.assertEqual(view.receipt['target_scope'], 'DAY_LEVEL_DOSSIER_NO_FORECAST_DEADLINE')
        self.assertNotIn('replayed_before_target_cutoff', view.receipt)
        self.assertNotIn('202611260101', json.dumps(view.receipt))
        self.assertFalse(view.receipt['forecast_original_authenticated'])

    def test_dossier_as_of_uses_exclusive_end_of_jst_day_to_microsecond(self):
        project = getattr(self.module, 'project_day_for_dossier', None)
        self.assertIsNotNone(project, 'A day-only dossier entry point is required')
        args = dict(target_day='2026-11-26', clock=lambda: datetime(2026, 11, 27, tzinfo=timezone.utc))
        self.index['results'].clear()
        view = project(self.store, b'synthetic', knowledge_as_of='2026-11-26T14:59:59.999999Z', **args)
        self.assertEqual(view.receipt['knowledge_as_of'], '2026-11-26T14:59:59.999999+00:00')
        with self.assertRaises(ValueError):
            project(self.store, b'synthetic', knowledge_as_of='2026-11-26T15:00:00Z', **args)

    def test_existing_crypto_witnesses_and_official_page_reparse_feed_history(self):
        from tests.test_keirin_official_nationwide_records import NationwideRecordTests

        fixture = NationwideRecordTests()
        fixture.setUpClass()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with TemporaryDirectory() as folder:
            original, payload, base, adjusted, packets, capture = fixture.comparison_fixture(folder)
            scored = records.compare_result(original=original, payload=payload, raw_baseline=base,
                                            raw_conditioned=adjusted, packets=packets, final_capture=capture)
            rid, day = original['race_id'], original['day_jst']
            original_meta = dict(self.original_meta, race_id=rid,
                                 cutoff_at=original['baseline']['published_cutoff_at'],
                                 observed_at=original['baseline_sealed_at'])
            result_meta = dict(self.first, race_id=rid, monetary_complete=True,
                               observed_at='2030-01-15T04:10:00Z')
            saved = dict(schema=records.RESULT_SCHEMA, race_id=rid, scored=scored, final_capture=capture,
                         original_evidence_sha256=original_meta['evidence_sha256'], origin_packets=packets)
            store = SimpleNamespace(day=day, head='a'*40, index_commit='a'*40,
                                    index=dict(schema=records.INDEX_SCHEMA, registry=None, day_jst=day,
                                               originals={rid:original_meta}, results={rid:[result_meta]}),
                                    read=lambda meta, _: saved if meta['kind'] == 'result' else payload)
            def verify():
                return self.module.project_day(store, fixture.private, target_race_id='203001169801',
                                               target_cutoff_at='2030-01-16T03:00:00Z',
                                               knowledge_as_of='2030-01-15T05:00:00Z',
                                               clock=lambda: datetime(2030, 1, 15, 6, tzinfo=timezone.utc))
            with patch.object(records, 'archived_original', return_value=(base, adjusted)):
                view = verify()
                finishes = scored['official_result']['finishes']
                self.assertEqual(view.receipt['numeric_finishes'], len(finishes))
                registration = finishes[0]['registration_id']
                self.assertEqual(view.finish_history(registration)['periods']['all']['observed_count'], 1)
                saved['scored']['official_result']['finishes'][0]['place'] = 5
                self.assertEqual(verify().receipt['held_races'], 1)


if __name__ == '__main__':
    unittest.main()
