import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts.keirin_rider_profile_history import HistoryBook, Ride


class RiderHistorySupplementTests(unittest.TestCase):
    def setUp(self):
        self.clock = datetime(2026, 11, 25, 15, tzinfo=timezone.utc)
        self.registry_sha = 'a' * 64
        self.archive_shas = ['b' * 64, 'c' * 64]
        self.registry = {'complete': True, 'retrieval_completed_at': '2026-11-25T14:37:56+00:00', 'riders': [
            {'registration': f'{12000 + car:06}', 'name': f'試験選手{car}',
             'cohort': 100 + car, 'prefecture_or_country': '福岡'}
            for car in range(1, 6)]}
        self.roster = {'date': '2026-11-25', 'races': [{
            'race_id': '202611252601', 'cutoff': '2026-11-25T12:00:00+09:00',
            'riders': [{'number': car, 'name': f'試験選手{car}'} for car in range(1, 6)]}]}
        self.raw = json.dumps(self.roster, ensure_ascii=False).encode()
        self.identities = {'schema': 'KEIRIN_SAVED_ROSTER_IDENTITIES_V1',
            'generated_at': '2026-11-25T14:00:00+00:00', 'registry_sha256': self.registry_sha,
            'source_roster_sha256': None, 'holds': [], 'races': [{
                'race_id': '202611252601', 'source_url': 'https://keirin.kdreams.jp/seibuen/racedetail/2620261125010001/',
                'source_sha256': 'd' * 64, 'captured_at': '2026-11-25T13:50:00+00:00',
                'riders': [{'car': car, 'name': f'試験選手{car}', 'registration': f'{12000 + car:06}',
                            'cohort': 100 + car, 'prefecture': '福岡'} for car in range(1, 6)]}]}
        self.book = HistoryBook([
            Ride('202611202601', '012001', 1, None, 'LEAD', 'A'),
            Ride('202611242601', '012001', 3, None, 'SECOND', 'A'),
            Ride('202611252601', '012001', 2, None, 'LEAD', 'A'),
            Ride('202611262601', '012001', 1, None, 'LEAD', 'A')])

    def build(self, **kwargs):
        from scripts.keirin_rider_history_supplement import build_supplement
        return build_supplement(self.raw, self.identities, self.registry, self.book,
                                registry_sha256=self.registry_sha,
                                archive_sha256s=self.archive_shas, clock=self.clock, **kwargs)

    def test_existing_history_and_roster_are_preserved_with_actual_source_hash(self):
        original = copy.deepcopy(self.identities)
        doc, summary = self.build()
        self.assertEqual(doc['source_roster_sha256'], sha256(self.raw).hexdigest())
        self.assertFalse(doc['predictive_model_changed'])
        self.assertEqual(doc['knowledge_as_of'], self.clock.isoformat())
        history = doc['races'][0]['riders'][0]['history']
        self.assertEqual(history, self.book.finish_history('012001', race_id='202611252601'))
        self.assertEqual(history['periods']['all']['observed_count'], 2)
        self.assertEqual(self.identities, original)
        self.assertEqual(summary['attached_races'], 1)
        self.assertEqual(summary['attached_riders'], 5)
        self.assertNotIn('riders', summary)

    def test_empty_history_stays_unknown_and_never_becomes_a_zero_ability(self):
        doc, _ = self.build()
        row = doc['races'][0]['riders'][1]['history']['periods']['all']
        self.assertEqual(row['observed_count'], 0)
        self.assertIsNone(row['finish_rates'])
        self.assertIsNone(row['missing_finish_count'])

    def test_actual_saved_roster_can_derive_its_day_without_adding_a_date_member(self):
        del self.roster['date']
        self.raw = json.dumps(self.roster, ensure_ascii=False).encode()
        doc, _ = self.build()
        self.assertEqual(doc['source_roster_sha256'], sha256(self.raw).hexdigest())
        self.assertEqual(len(doc['races']), 1)

    def test_missing_identity_holds_one_whole_race_without_erasing_others(self):
        self.identities['races'][0]['riders'].pop()
        doc, summary = self.build()
        self.assertEqual(doc['races'], [])
        self.assertEqual(summary['held_races'], 1)
        self.assertEqual(summary['holds_by_reason'], {'ROSTER_IDENTITY_MISMATCH': 1})

    def test_name_or_cohort_conflict_cannot_attach_a_different_person(self):
        for field, value in [('name', '別の選手'), ('cohort', 999)]:
            with self.subTest(field=field):
                before = self.identities['races'][0]['riders'][0][field]
                self.identities['races'][0]['riders'][0][field] = value
                doc, summary = self.build()
                self.assertEqual(doc['races'], [])
                self.assertEqual(summary['held_races'], 1)
                self.identities['races'][0]['riders'][0][field] = before

    def test_registry_and_explicit_roster_hashes_must_match(self):
        self.identities['registry_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'REGISTRY_SHA_MISMATCH'):
            self.build()
        self.identities['registry_sha256'] = self.registry_sha
        self.identities['source_roster_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'ROSTER_SHA_MISMATCH'):
            self.build()

    def test_incomplete_registry_or_future_capture_is_not_admitted(self):
        self.registry['complete'] = False
        with self.assertRaisesRegex(ValueError, 'REGISTRY_INCOMPLETE'):
            self.build()
        self.registry['complete'] = True
        self.identities['races'][0]['captured_at'] = '2026-11-25T15:00:00.000001+00:00'
        doc, summary = self.build()
        self.assertEqual(doc['races'], [])
        self.assertEqual(summary['holds_by_reason'], {'IDENTITY_CAPTURE_TIME_INVALID': 1})

    def test_duplicate_source_race_is_rejected(self):
        self.identities['races'].append(copy.deepcopy(self.identities['races'][0]))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_IDENTITY_RACE'):
            self.build()

    def test_registry_captured_after_build_cannot_claim_earlier_knowledge(self):
        self.registry['retrieval_completed_at'] = '2026-11-25T15:00:00.000001+00:00'
        with self.assertRaisesRegex(ValueError, 'REGISTRY_CAPTURE_AFTER_BUILD'):
            self.build()

    def test_plaintext_cannot_be_written_inside_a_local_public_checkout(self):
        from scripts.keirin_rider_history_supplement import write_supplement
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.git').mkdir()
            output = root / 'private' / 'rider_histories.json'
            with self.assertRaisesRegex(ValueError, 'CANNOT_ENTER_CHECKOUT'):
                write_supplement(output, {})
            self.assertFalse(output.exists())

    def test_known_roster_registration_conflict_holds_the_race(self):
        self.roster['races'][0]['riders'][0]['registration'] = '099999'
        self.raw = json.dumps(self.roster, ensure_ascii=False).encode()
        doc, summary = self.build()
        self.assertEqual(doc['races'], [])
        self.assertEqual(summary['held_races'], 1)


if __name__ == '__main__':
    unittest.main()
