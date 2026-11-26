"""Verify the public allowlist with fictional roster and dossier source inputs."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
import unittest
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256

from race_ai import keirin_official_public_source as official
from scripts import keirin_public_rider_projection as projection
from tests import test_keirin_official_public_source as official_fixture
from tests import test_keirin_rider_dossier_readback as dossier_fixture


class PublicRiderProjectionTests(unittest.TestCase):
    def schedule(self, data=None):
        day = official_fixture.DAY
        return official.fetch_day_schedule(
            day, fetcher=official_fixture.transport(data or official_fixture.fixtures()),
            clock=lambda: official_fixture.NOW,
        )

    def test_starters_are_bound_to_raw_official_number_and_car(self):
        data = official_fixture.fixtures()
        rows = data['JSJ017']['rInfo'][0]['sInfo']
        rows.pop(2)
        rows[0]['private_payload'] = 'private-original-only'
        result = projection.project_starters(self.schedule(data), published_at=official_fixture.NOW)
        self.assertEqual(result['schema'], 'RACE_AI_KEIRIN_PUBLIC_STARTERS_V1')
        self.assertEqual(result['day'], official_fixture.DAY)
        first = result['races'][0]
        self.assertEqual(first['race_id'], official_fixture.RACE)
        self.assertEqual(first['source_at'], official_fixture.NOW.isoformat())
        self.assertEqual([rider['number'] for rider in first['riders']], [1, 2, 4, 5, 6, 7])
        self.assertEqual(first['riders'][0], {
            'number': 1, 'registration': '999001', 'name': '架空選手1',
            'region': '架空', 'style': '両',
        })
        serialized = json.dumps(result)
        for private in ['private-original-only', 'encp', 'raw_bytes', 'event_token', 'official_cutoff_at']:
            self.assertNotIn(private, serialized)

    def test_starter_projection_rejects_unbound_snapshots_and_incomplete_names(self):
        wrong_car = self.schedule()
        wrong_car['races'][0]['starters'][0]['registration_id'] = '111111'
        with self.assertRaises(ValueError):
            projection.project_starters(wrong_car, published_at=official_fixture.NOW)
        data = official_fixture.fixtures()
        data['JSJ017']['rInfo'][0]['sInfo'][0]['senName'] = ''
        with self.assertRaises(ValueError):
            projection.project_starters(self.schedule(data), published_at=official_fixture.NOW)

    def directory_sources(self):
        fixture = dossier_fixture.DossierRecoveryTests()
        fixture.setUp()
        fixture.reg['riders'][0].update(
            name='架空選手', class_='A1', prefecture_or_country='架空県',
            source_note='private-source-text', captured_at=dossier_fixture.AT,
        )
        person = fixture.reg['riders'][0]
        person['class'] = person.pop('class_')
        fixture.doc['dossiers'][0]['name'] = person['name']
        fixture.doc['dossiers'][0]['finish_history']['recent_races'] = [{'race_id': 'private-race-record'}]
        missing = dict(person, registration='012346', name='未観測選手')
        fixture.reg['riders'].append(missing)
        second = deepcopy(fixture.doc['dossiers'][0])
        second['registration'], second['name'] = missing['registration'], missing['name']
        second['finish_history']['registration'] = missing['registration']
        second['finish_history']['periods']['all'].update(
            observed_count=0, first_observed_day=None, latest_observed_day=None,
            finish_counts=dict.fromkeys(map(str, range(1, 10)), 0),
        )
        fixture.doc['dossiers'].append(second)
        fixture.metrics['registered_riders'] = 2
        fixture.prepare()
        fixture.receipt['git_readback_at'] = dossier_fixture.AT
        fixture.receipt['archive_commit'] = 'a' * 40
        return fixture.originals, fixture.receipt

    def test_directory_preserves_verified_coverage_and_publishes_only_aggregates(self):
        files, receipt = self.directory_sources()
        result = projection.project_directory(files, receipt, now=dossier_fixture.NOW)
        self.assertEqual(result['schema'], 'RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1')
        self.assertEqual(result['as_of'], dossier_fixture.DAY)
        self.assertEqual(result['history_start_day'], dossier_fixture.START)
        self.assertEqual(result['history_end_day'], dossier_fixture.END)
        first, empty = result['riders']
        self.assertEqual(first['registration'], '012345')
        self.assertEqual(first['name'], '架空選手')
        self.assertEqual(first['grade'], 'A1')
        self.assertEqual(first['history']['observed_count'], 1)
        self.assertEqual(first['history']['finish_counts']['1'], 1)
        self.assertEqual(empty['history']['observed_count'], 0)
        self.assertIsNone(empty['history']['latest_observed_day'])
        self.assertNotIn('history_windows', first)
        self.assertNotIn('history_windows', empty)
        serialized = json.dumps(result)
        for private in ['private-source-text', 'private-race-record', 'missing_finish_count', 'captured_at']:
            self.assertNotIn(private, serialized)

    def directory_window_sources(self, mutate=None):
        files, receipt = self.directory_sources()
        data = json.loads(files[dossier_fixture.NATIONAL])
        first, empty = [row['finish_history']['periods'] for row in data['dossiers']]

        def window(start, places, first, last):
            return dict(start_day_inclusive=start, observed_count=len(places), missing_finish_count=None,
                        finish_counts={str(rank): places.count(rank) for rank in range(1, 10)},
                        first_observed_day=first, latest_observed_day=last,
                        finish_rates={'private-window-rate': 0.5}, archive_note='private-window-field')

        first.update({
            'all': window(None, [1, 1, 1, 2, 2, 3], dossier_fixture.START, dossier_fixture.END),
            '1_month': window('2098-12-03', [1, 2], '2098-12-03', dossier_fixture.END),
            '4_months': window('2098-09-03', [1, 1, 2], '2098-10-01', dossier_fixture.END),
            '1_year': window('2098-01-03', [1, 1, 1, 2, 3], '2098-01-03', dossier_fixture.END),
            '3_years': window('2096-01-03', [1, 1, 1, 2, 2, 3], dossier_fixture.START, dossier_fixture.END),
        })
        for name in ('1_month', '4_months', '1_year'):
            empty[name] = window(first[name]['start_day_inclusive'], [], None, None)
        if mutate:
            mutate(first)
        raw = dossier_fixture.raw(data)
        files[dossier_fixture.NATIONAL] = raw
        receipt['files'][dossier_fixture.NATIONAL] = dict(bytes=len(raw), sha256=sha256(raw).hexdigest())
        receipt['numeric_finish_records'] = 6
        return files, receipt

    def test_directory_windows_export_only_verified_aggregate_fields(self):
        files, receipt = self.directory_window_sources()
        document = projection.project_directory(files, receipt, now=dossier_fixture.NOW + timedelta(days=32))
        first, empty = document['riders']
        expected = {'1_month', '4_months', '1_year'}
        self.assertEqual(document['schema'], 'RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1')
        self.assertEqual(set(first['history_windows']), expected)
        self.assertEqual(set(empty['history_windows']), expected)
        self.assertEqual(set(first['history_windows']['4_months']),
                         {'start_day_inclusive', 'observed_count', 'finish_counts',
                          'first_observed_day', 'latest_observed_day'})
        self.assertEqual(first['history_windows']['4_months']['start_day_inclusive'], '2098-09-03')
        self.assertEqual(first['history_windows']['4_months']['observed_count'], 3)
        self.assertEqual(first['history_windows']['4_months']['finish_counts']['1'], 2)
        self.assertEqual(first['history_windows']['4_months']['first_observed_day'], '2098-10-01')
        self.assertEqual(first['history_windows']['4_months']['latest_observed_day'], dossier_fixture.END)
        self.assertEqual(empty['history_windows']['1_month']['observed_count'], 0)
        self.assertIsNone(empty['history_windows']['1_month']['first_observed_day'])
        encoded = json.dumps(document)
        for detail in ('3_years', 'finish_rates', 'private-window-field', 'missing_finish_count'):
            self.assertNotIn(detail, encoded)

    def test_directory_windows_reject_malformed_coverage_counts_and_dates(self):
        def assign(name, **fields):
            return lambda periods: periods[name].update(fields)

        for mutate in (
            lambda periods: periods.pop('4_months'),
            assign('1_month', start_day_inclusive='2098-12-02'),
            assign('1_month', first_observed_day='2098-12-02'),
            assign('1_month', latest_observed_day=dossier_fixture.DAY),
            assign('1_month', latest_observed_day='2098-12-30'),
            assign('1_month', observed_count=True),
            assign('1_month', observed_count=2.0),
            assign('1_month', observed_count=-1),
            assign('1_month', observed_count=3),
            lambda periods: periods['1_month']['finish_counts'].update({'9': -1}),
            lambda periods: periods['1_month']['finish_counts'].update({'1': True}),
            lambda periods: periods['1_month']['finish_counts'].update({'10': 0}),
            assign('1_month', observed_count=0, finish_counts=dict.fromkeys(map(str, range(1, 10)), 0)),
            # Totals nest while a rank is absent from the immediately larger window.
            lambda periods: periods['1_month']['finish_counts'].update({'2': 0, '3': 1}),
            # Totals nest while a rank exceeds the verified all-history bucket.
            lambda periods: periods['1_year']['finish_counts'].update({'1': 2, '9': 1}),
        ):
            with self.subTest(mutation=mutate):
                files, receipt = self.directory_window_sources(mutate)
                with self.assertRaises(ValueError):
                    projection.project_directory(files, receipt, now=dossier_fixture.NOW)

    def test_calendar_months_clamp_to_the_last_day_of_the_target_month(self):
        self.assertEqual(projection._history_month_start(date(2024, 3, 31), 1), date(2024, 2, 29))
        self.assertEqual(projection._history_month_start(date(2024, 2, 29), 12), date(2023, 2, 28))
        self.assertEqual(projection._history_month_start(date(2026, 1, 31), 4), date(2025, 9, 30))

    def test_directory_rejects_file_mutation_or_altered_coverage_even_with_same_ids(self):
        files, receipt = self.directory_sources()
        files[dossier_fixture.REGISTRY] += b' '
        with self.assertRaises(ValueError):
            projection.project_directory(files, receipt, now=dossier_fixture.NOW)
        files, receipt = self.directory_sources()
        receipt['numeric_finish_records'] = 2
        with self.assertRaises(ValueError):
            projection.project_directory(files, receipt, now=dossier_fixture.NOW)

    def test_public_artifact_contains_only_the_directory_and_its_checked_receipt(self):
        files, archive = self.directory_sources()
        document = projection.project_directory(files, archive, now=dossier_fixture.NOW)
        proof = projection.directory_receipt(document, archive)
        with TemporaryDirectory(dir=Path(gettempdir()).resolve()) as temporary:
            output = Path(temporary) / 'projection'
            projection._write_directory(output, document, proof)
            self.assertEqual({p.name for p in output.iterdir()}, {projection.DIRECTORY_FILE, projection.RECEIPT_FILE})
            public_bytes = (output / projection.DIRECTORY_FILE).read_bytes()
            self.assertEqual(proof['projection_sha256'], sha256(public_bytes).hexdigest())
            self.assertEqual(proof['projection_bytes'], len(public_bytes))
            self.assertEqual(proof['registered_riders'], 2)
            self.assertEqual(proof['riders_with_numeric_history'], 1)
            self.assertEqual(proof['numeric_finish_records'], 1)
            with self.assertRaises(ValueError):
                projection._write_directory(output, document, proof)
            self.assertEqual((output / projection.DIRECTORY_FILE).read_bytes(), public_bytes)
