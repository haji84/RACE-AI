"""Verify the public allowlist with fictional roster and dossier source inputs."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
import unittest
from copy import deepcopy
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
        serialized = json.dumps(result)
        for private in ['private-source-text', 'private-race-record', 'missing_finish_count', 'captured_at']:
            self.assertNotIn(private, serialized)

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
