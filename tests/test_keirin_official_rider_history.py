"""Fixture-only coverage for dated aggregates of authenticated official finish rows."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_rider_history as history
from race_ai import keirin_official_run_history as cipher
from tests import test_keirin_official_nationwide_records as record_fixtures
from tests.test_keirin_official_run_history import git


DAY = '2026-11-25'
RACE = '202611252601'
CUTOFF = '2026-11-25T05:00:00Z'
NOW = datetime(2026, 11, 25, 15, tzinfo=timezone.utc)
SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1'


def metadata(kind, digest, observed_at, race=RACE):
    row = dict(kind=kind, evidence_sha256=digest * 64, cipher_sha256=digest * 64,
               producer_run_id='1234', producer_commit='c' * 40, observed_at=observed_at)
    if kind != 'registry':
        row['race_id'] = race
    if kind == 'original':
        row.update(cutoff_at=CUTOFF, baseline_cipher_sha256='a' * 64)
    if kind == 'result':
        row['monetary_complete'] = False
    return row


class RiderDayTests(unittest.TestCase):
    def setUp(self):
        self.original_meta = metadata('original', '1', '2026-11-25T04:00:00Z')
        self.first = metadata('result', '2', '2026-11-25T06:02:00Z')
        self.second = metadata('result', '3', '2026-11-25T07:02:00Z')
        self.index = dict(records._empty(DAY), originals={RACE: self.original_meta},
                          results={RACE: [self.first]})
        self.store = SimpleNamespace(head='b'*40, index_commit='b'*40, index=self.index, day=DAY)
        starters = [dict(car=car, registration_id=f'{14000+car:06d}') for car in (1, 3, 4, 6, 7)]
        self.original = dict(race_id=RACE, day_jst=DAY, baseline=dict(published_cutoff_at=CUTOFF),
                             snapshot=dict(riders=[dict(car=r['car'], athlete_id=r['registration_id'])
                                                   for r in starters]))
        self.final = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1', race_id=RACE,
                          status='FINAL_NORMAL', refund_status='NONE', starters=starters,
                          finishes=[dict(**row, status=status, place=place) for row, (status, place) in
                                    zip(starters, [('FINISHED', 1), ('FINISHED', 2), ('FALL_FINISHED', 2),
                                                   ('FINISHED', 4), ('DISQUALIFIED', None)])],
                          official_cutoff_at=CUTOFF, source_sha256='d'*64,
                          source_updated_at='2026-11-25T06:00:00Z', observed_at='2026-11-25T06:01:00Z')
        self.answers = {self.first['evidence_sha256']: self.final}

    def project(self, now=NOW):
        def replay(store, original_meta, result_meta, key):
            final = self.answers[result_meta['evidence_sha256']]
            if isinstance(final, Exception):
                raise final
            return self.original, {'official_result': final}, {}
        with patch.object(records, '_replay_saved_result', side_effect=replay):
            return history.project_rider_day(self.store, b'synthetic', now=now)

    def correction(self):
        corrected = deepcopy(self.final)
        corrected.update(source_updated_at='2026-11-25T07:00:00Z',
                         observed_at='2026-11-25T07:01:00Z', source_sha256='e'*64)
        corrected['finishes'][0]['place'] = 2
        corrected['finishes'][1]['place'] = 1
        self.index['results'][RACE].append(self.second)
        self.answers[self.second['evidence_sha256']] = corrected
        return corrected

    def test_full_field_counts_tied_places_and_omits_nonfinishers(self):
        # Another original has no result. It must neither inflate coverage nor prevent this day.
        race = '202611252602'
        self.index['originals'][race] = metadata('original', '9', '2026-11-25T04:00:00Z', race)
        self.assertEqual(self.project(), {
            'schema': SCHEMA, 'day': DAY, 'source_sha256': history.archive_signature(self.store),
            'archive_races': 1, 'verified_races': 1,
            'riders': [
                {'registration': '014001', 'finish_counts': [1, 0, 0, 0, 0, 0, 0, 0, 0]},
                {'registration': '014003', 'finish_counts': [0, 1, 0, 0, 0, 0, 0, 0, 0]},
                {'registration': '014004', 'finish_counts': [0, 1, 0, 0, 0, 0, 0, 0, 0]},
                {'registration': '014006', 'finish_counts': [0, 0, 0, 1, 0, 0, 0, 0, 0]},
            ],
        })

    def test_changed_official_finish_replaces_the_previous_revision(self):
        self.correction()
        rows = self.project()['riders']
        self.assertEqual([row['finish_counts'][:2] for row in rows], [[0, 1], [1, 0], [0, 1], [0, 0]])

    def test_signature_tracks_finishes_and_relevant_originals_only(self):
        before = history.archive_signature(self.store)
        self.index['registry'] = metadata('registry', '5', '2026-11-25T10:00:00Z')
        race = '202611252602'
        self.index['originals'][race] = metadata('original', '9', '2026-11-25T04:00:00Z', race)
        self.assertEqual(history.archive_signature(self.store), before)
        self.original_meta['producer_commit'] = 'c'*39 + 'd'
        changed_original = history.archive_signature(self.store)
        self.assertNotEqual(changed_original, before)
        self.correction()
        self.assertNotEqual(history.archive_signature(self.store), changed_original)

    def test_invalid_old_or_current_revision_holds_the_whole_day(self):
        corrected = self.correction()
        self.answers[self.first['evidence_sha256']] = ValueError('fixture private marker')
        with self.assertRaises(ValueError) as error:
            self.project()
        self.assertNotIn('fixture private marker', str(error.exception))
        self.answers[self.first['evidence_sha256']] = self.final
        corrected['source_updated_at'] = self.final['source_updated_at']
        with self.assertRaises(ValueError):
            self.project()

    def test_rejects_incomplete_invalid_or_unbound_finish_groups(self):
        mutations = {
            'missing finisher': lambda row: row['finishes'].pop(3),
            'fourth place missing': lambda row: row['finishes'][3].update(place=5),
            'registration mismatch': lambda row: row['finishes'][3].update(registration_id='099999'),
            'unknown finish status': lambda row: row['finishes'][3].update(status='UNKNOWN'),
            'unbound cutoff': lambda row: row.update(official_cutoff_at='2026-11-25T05:01:00Z'),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                changed = deepcopy(self.final)
                mutate(changed)
                self.answers[self.first['evidence_sha256']] = changed
                with self.assertRaises(ValueError):
                    self.project()

    def test_future_archive_result_requires_holding_instead_of_rolling_back(self):
        self.correction()
        with self.assertRaises(ValueError):
            self.project(now='2026-11-25T07:01:59Z')
        self.store.index_commit = None
        with self.assertRaises(ValueError):
            self.project()

    def test_different_empty_days_have_different_signatures(self):
        self.index['results'] = {}
        current = self.project()
        self.assertEqual((current['archive_races'], current['verified_races'], current['riders']), (0, 0, []))
        self.store.day = '2026-11-24'
        self.store.index = records._empty(self.store.day)
        self.assertNotEqual(self.project()['source_sha256'], current['source_sha256'])

    def test_saved_original_and_full_final_html_are_replayed(self):
        fixture = record_fixtures.NationwideRecordTests()
        fixture.setUpClass()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
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
                                    index=dict(records._empty(day), originals={rid: original_meta},
                                               results={rid: [result_meta]}),
                                    read=lambda meta, key: saved if meta['kind'] == 'result' else payload)
            with patch.object(records, 'archived_original', return_value=(base, adjusted)):
                project = history.project_rider_day
                now = '2030-01-15T05:00:00Z'
                view = project(store, fixture.private, now=now)
                expected = {r['athlete_id']: r['car'] for r in original['snapshot']['riders']}
                self.assertEqual({r['registration']: r['finish_counts'].index(1)+1 for r in view['riders']}, expected)
                saved['scored']['official_result']['finishes'][-1]['place'] = 1
                with self.assertRaises(ValueError):
                    project(store, fixture.private, now=now)


class PinnedArchiveTests(unittest.TestCase):
    def test_one_shallow_read_pins_independent_days_and_rejects_unrelated_commits(self):
        with TemporaryDirectory() as folder:
            source, reader = (Path(folder) / name for name in ('source', 'reader'))
            for path in (source, reader):
                path.mkdir()
                git(path, 'init', '-q')
                git(path, 'config', 'user.name', 'Fixture')
                git(path, 'config', 'user.email', 'fixture@example.invalid')
            git(source, 'config', 'uploadpack.allowFilter', 'true')
            unrelated_blob = source / 'unrelated'
            unrelated_blob.write_bytes(b'fixture unrelated archive blob')
            git(source, 'add', '--', unrelated_blob.name)
            git(source, 'commit', '-qm', 'fixture base')
            unrelated_sha = git(source, 'rev-parse', 'HEAD:unrelated')
            for day in (DAY, '2026-11-24'):
                index = source / records.ROOT / day / 'index.json'
                index.parent.mkdir(parents=True)
                index.write_bytes(cipher._canonical(records._empty(day)))
            git(source, 'add', '--', records.ROOT)
            git(source, 'commit', '-qm', 'fixture dated indices')
            git(source, 'branch', archive.BRANCH)
            git(reader, 'commit', '--allow-empty', '-qm', 'unrelated local commit')
            foreign = git(reader, 'rev-parse', 'HEAD')
            git(reader, 'remote', 'add', 'origin', source.as_uri())
            git(reader, 'config', 'remote.origin.promisor', 'true')
            git(reader, 'config', 'remote.origin.partialclonefilter', 'blob:none')
            head = records.fetch_partial_head(reader, synthetic_local=True)
            self.assertEqual(head, git(source, 'rev-parse', 'HEAD'))
            self.assertEqual(git(reader, 'rev-list', '--count', head), '1')
            self.assertEqual(records.discover_days_at(reader, head, synthetic_local=True), [DAY, '2026-11-24'])
            for day in (DAY, '2026-11-24'):
                store = records.RecordStore(reader, day, index_commit=head, synthetic_local=True)
                self.assertEqual((store.refresh()['day_jst'], store.head), (day, head))
                with self.assertRaisesRegex(ValueError, 'PINNED_INDEX_READ_ONLY'):
                    store.append(kind='result', payload={}, public_pem=b'', observed_at=NOW)
            self.assertIn('?' + unrelated_sha, git(reader, 'rev-list', '--objects', '--missing=print', head))
            with self.assertRaises(ValueError):
                records.RecordStore(reader, DAY, index_commit=foreign, synthetic_local=True)
            with self.assertRaises(ValueError):
                records.discover_days_at(reader, foreign, synthetic_local=True)
