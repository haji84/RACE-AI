"""Name aliases come from exact invented official B and TERM source bytes."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import base64
import importlib
import json
import tempfile
import unittest

from race_ai import boat_saved_model_view as M
from race_ai.actions_contract import digest
from race_ai.boat_racer_database import RacerDatabase
from race_ai.boat_racer_term import term_info
from race_ai.saved_view_feed import forecast_inventory
from tests.test_boat_entry_observations import uncompressed_lzh
from tests.test_boat_racer_term import record
from tests.test_program_race_isolation import fixture
from tests.test_boat_saved_model_view import view, prediction

try: A = importlib.import_module('race_ai.boat_name_aliases')
except ModuleNotFoundError: A = None

DAY = '2030-04-01'
CLOCK = datetime(2030, 4, 1, 8, tzinfo=timezone.utc)
URL = 'https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh'


class NameAliasTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(A, 'source-backed official name bridge is missing')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'racers.sqlite'
        self.sources('選手名字', '選手名字郎')

    def sources(self, short, full):
        raw = fixture().replace(b'18BBGN', b'01BBGN').replace(b'18BEND', b'01BEND')
        raw = raw.replace('選手名字'.encode('cp932'), short.encode('cp932'))
        self.raw_b = uncompressed_lzh(raw, 'B300401.TXT')
        self.manifest = dict(schema='RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1', b_sources=[dict(day=DAY,
            raw_b_base64=base64.b64encode(self.raw_b).decode(), source_url=URL,
            source_sha256=sha256(self.raw_b).hexdigest(), captured_at='2030-04-01T00:00:00Z')])
        records = []
        for n in range(1, 7):
            raw = record(str(4000+n)); raw = raw[:4]+full.encode('cp932').ljust(16, b' ')+raw[20:]
            records.append(raw)
        self.term_raw = uncompressed_lzh(b'\n'.join(records), 'fan2604.txt')
        db = RacerDatabase(clock=lambda: CLOCK)
        db.import_term(self.term_raw, term='2026-2', source_url=term_info('2026-2')['source_url'],
                       captured_at='2026-11-06T00:00:00Z')
        self.path.write_bytes(db.serialize()); self.path.chmod(0o600); db.db.close()
        self.short, self.full = short, full

    def facts(self):
        return A.build_name_aliases(self.manifest, self.path, now=CLOCK)

    def views(self):
        base = view(); extra = view(prediction(stage='P1'))
        for doc in (base, extra):
            for person in doc['records'][0]['participants']:
                person['registration_no'] = str(4000+person['number'])
        for person in base['records'][0]['participants']:
            person.update(name=self.short, name_source=dict(kind='SAME_RACE_PROGRAM',
                registration_no=person['registration_no'], race_id='20300401-01-01',
                source_url=URL, source_sha256=sha256(self.raw_b).hexdigest()))
        for person in extra['records'][0]['participants']: person['name'] = self.full
        return base, extra

    def test_exact_sources_generate_scoped_pairs_without_prefix_heuristic(self):
        for short, full in [('選手名字', '選手名字郎'), ('大豆生蒼', '大豆生田 蒼')]:
            self.sources(short, full); facts = self.facts()
            self.assertEqual(len(facts), 72)
            f = facts[0]
            self.assertEqual((f['short_name'], f['full_name']), (short, full))
            self.assertEqual((f['race_id'], f['event_date_jst'], f['number'], f['registration_no']),
                             ('20300401-01-01', DAY, 1, '4001'))
            self.assertEqual(f['b_source']['source_sha256'], sha256(self.raw_b).hexdigest())
            self.assertEqual(f['full_source']['source_sha256'], sha256(self.term_raw).hexdigest())
            self.assertEqual(f['fact_sha256'], digest({k:v for k,v in f.items() if k != 'fact_sha256'}))

    def test_aliases_survive_append_without_names_and_upgrade_display_with_full_source(self):
        base, extra = self.views(); original = deepcopy((base, extra))
        attached = A.attach_name_aliases(base, self.facts())
        self.assertEqual((base, extra), original)
        self.assertEqual(forecast_inventory(attached), forecast_inventory(base))
        merged = M.merge_saved_views(attached, [extra]); row = merged['records'][0]
        self.assertEqual(row['participants'][0]['name'], self.full)
        self.assertEqual(row['participants'][0]['name_source']['kind'], 'VERIFIED_RACER_REGISTRY')
        self.assertEqual(row['participants'][0]['name_source']['source_sha256'], sha256(self.term_raw).hexdigest())
        self.assertNotEqual(row['participants'][0]['name_source']['source_url'], URL)
        self.assertTrue(any(s['participants'] == base['records'][0]['participants'] for s in row['saved_participant_rosters']))
        self.assertEqual(row['prediction'], base['records'][0]['prediction'])
        self.assertEqual(row['comparison_predictions'], [extra['records'][0]['prediction']])
        replay = json.loads(json.dumps(merged, ensure_ascii=False))
        self.assertEqual(M.merge_saved_views(replay, [extra]), merged)
        self.assertEqual(A.attach_name_aliases(merged, self.facts()), merged)

    def test_missing_alias_or_full_name_outside_exact_pair_still_holds(self):
        base, extra = self.views()
        with self.assertRaises(M.SavedModelViewError): M.merge_saved_views(base, [extra])
        attached = A.attach_name_aliases(base, self.facts())
        extra['records'][0]['participants'][0]['name'] = '別人名字郎'
        with self.assertRaises(ValueError): M.merge_saved_views(attached, [extra])

    def test_pre_upgrade_B_display_is_preserved_when_older_saved_snapshot_had_no_name(self):
        base, extra = self.views()
        old_snapshot = deepcopy(base['records'][0]['participants'])
        for person in old_snapshot: person['name'] = None; person.pop('name_source', None)
        base['records'][0]['saved_participant_rosters'] = [dict(participants=old_snapshot)]
        merged = M.merge_saved_views(A.attach_name_aliases(base, self.facts()), [extra])
        snapshots = merged['records'][0]['saved_participant_rosters']
        self.assertTrue(any(s['participants'] == base['records'][0]['participants'] for s in snapshots))
        self.assertEqual(M.merge_saved_views(merged, [extra]), merged)

    def test_alias_rejects_changed_source_scope_registration_or_lane(self):
        for field, value in [('race_id', '20300401-01-02'), ('event_date_jst', '2030-04-02'),
                             ('number', 2), ('registration_no', '4999')]:
            base, extra = self.views(); attached = A.attach_name_aliases(base, self.facts())
            f = attached['records'][0]['official_name_aliases'][0]; f[field] = value
            f['fact_sha256'] = digest({k:v for k,v in f.items() if k != 'fact_sha256'})
            with self.assertRaises(ValueError): M.merge_saved_views(attached, [extra])
        base, extra = self.views(); attached = A.attach_name_aliases(base, self.facts())
        extra['records'][0]['participants'][0]['name_source'] = dict(kind='SAME_RACE_PROGRAM',
            registration_no='4001', race_id='20300401-01-01', source_sha256='9'*64, source_url=URL)
        extra['records'][0]['participants'][0]['name'] = self.short
        with self.assertRaises(ValueError): M.merge_saved_views(attached, [extra])

    def test_raw_source_hash_body_day_registry_documents_and_urls_are_verified(self):
        for change in ('hash', 'url', 'day', 'base64'):
            manifest = deepcopy(self.manifest); source = manifest['b_sources'][0]
            source.update({'hash':dict(source_sha256='0'*64), 'url':dict(source_url='https://example.test/b.lzh'),
                           'day':dict(day='2030-04-02'), 'base64':dict(raw_b_base64='not base64')}[change])
            with self.assertRaises(ValueError): A.build_name_aliases(manifest, self.path, now=CLOCK)
        import sqlite3
        db = sqlite3.connect(self.path); db.execute('DROP TRIGGER immutable_racers_update')
        pid, body = db.execute('SELECT racer_id,document FROM racers LIMIT 1').fetchone()
        doc = json.loads(body); doc['name'] = '偽造 全名'
        db.execute('UPDATE racers SET document=? WHERE racer_id=?', (json.dumps(doc), pid)); db.commit(); db.close()
        with self.assertRaises(ValueError): self.facts()

    def test_fact_tampering_is_rejected_and_no_alias_does_not_rewrite_view(self):
        base, _ = self.views()
        self.assertIs(A.attach_name_aliases(base, []), base)
        facts = self.facts(); facts[0]['full_name'] = '別人名字郎'
        with self.assertRaises(ValueError): A.attach_name_aliases(base, facts)

    def test_rehashed_full_source_tamper_cannot_bypass_source_admission_or_replay(self):
        base, extra = self.views(); facts = self.facts()
        f = facts[0]; f['full_source']['source_sha256'] = '9'*64
        f['fact_sha256'] = digest({k:v for k,v in f.items() if k != 'fact_sha256'})
        with self.assertRaises(ValueError): A.attach_name_aliases(base, facts)
        merged = M.merge_saved_views(A.attach_name_aliases(base, self.facts()), [extra])
        f = merged['records'][0]['official_name_aliases'][0]
        f['full_source']['source_sha256'] = '9'*64
        f['fact_sha256'] = digest({k:v for k,v in f.items() if k != 'fact_sha256'})
        with self.assertRaises(ValueError): M.merge_saved_views(merged, [extra])

    def test_explicit_name_mapping_cannot_hide_different_letters_outside_pair(self):
        base, extra = self.views(); attached = A.attach_name_aliases(base, self.facts())
        for names in (dict(races={'20300401-01-01':{'4001':dict(name='別人名字郎', number=1)}}),
                      dict(registry={'4001':dict(name='別人名字郎', verified=True, source_sha256='8'*64)})):
            with self.assertRaises(ValueError): M.merge_saved_views(attached, [extra], names=names)

    def test_unknown_B_capture_clock_stays_null_and_does_not_change_forecast_clocks(self):
        self.manifest['b_sources'][0]['captured_at'] = None
        facts = self.facts(); self.assertIsNone(facts[0]['b_source']['captured_at'])
        base, extra = self.views()
        merged = M.merge_saved_views(A.attach_name_aliases(base, facts), [extra])
        self.assertEqual(merged['records'][0]['prediction'], base['records'][0]['prediction'])

    def test_explicit_withdrawal_uses_complete_bound_roster_without_restoring_active_lane(self):
        base, extra = self.views(); removed = extra['records'][0]['participants'].pop()
        extra['records'][0].update(roster_status='OFFICIAL_ACTIVE', withdrawn_lanes=[6],
            withdrawn_participants=[dict(removed, active=False, withdrawn=True)])
        facts = self.facts(); before = deepcopy(extra)
        attached = A.attach_name_aliases(extra, facts)
        self.assertEqual(extra, before)
        self.assertEqual(len(attached['records'][0]['official_name_aliases']), 6)
        for previous in (None, A.attach_name_aliases(base, facts)):
            merged = M.merge_saved_views(attached) if previous is None else M.merge_saved_views(previous, [attached])
            row = merged['records'][0]
            self.assertEqual([p['number'] for p in row['participants']], [1,2,3,4,5])
            self.assertEqual(row['withdrawn_lanes'], [6])
            self.assertEqual(row['withdrawn_participants'][0]['registration_no'], '4006')
            self.assertEqual(row['withdrawn_participants'][0]['name'], self.full)
            self.assertEqual(M.merge_saved_views(merged, [attached]), merged)

    def test_unbound_withdrawn_identity_never_guesses_an_alias_or_blocks_active_roster(self):
        base, extra = self.views(); extra['records'][0]['participants'].pop()
        extra['records'][0].update(roster_status='OFFICIAL_ACTIVE', withdrawn_lanes=[6],
            withdrawn_participants=[dict(number=6, registration_no=None, name=None, active=False)])
        attached = A.attach_name_aliases(extra, self.facts())
        self.assertEqual(len(attached['records'][0]['official_name_aliases']), 5)
        merged = M.merge_saved_views(A.attach_name_aliases(base, self.facts()), [attached])
        self.assertEqual([p['number'] for p in merged['records'][0]['participants']], [1,2,3,4,5])
        self.assertEqual(merged['records'][0]['withdrawn_participants'][0]['registration_no'], '4006')


class ProgramNameAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai import boat_all_model_cycle as E
        from tests import test_boat_all_model_cycle as F
        test = F.AllModelCycleTests(); test.setUp()
        try: cls.payload = E.forecast_round([F.source_context()], test.runtime(), now=F.NOW)
        finally: test.doCleanups()
        cls.receipt = F.receipt(cls.payload)
        cls.clock = datetime.fromisoformat('2030-04-01T18:01:00+09:00')
        raw = fixture().replace(b'18BBGN', b'12BBGN').replace(b'18BEND', b'12BEND')
        b = uncompressed_lzh(raw, 'B300401.TXT')
        cls.manifest = dict(schema=A.MANIFEST, b_sources=[dict(day=DAY,
            raw_b_base64=base64.b64encode(b).decode(), source_url=URL,
            source_sha256=sha256(b).hexdigest(), captured_at=None)])

    def test_missing_term_uses_exact_authenticated_program_and_correct_full_source(self):
        from unittest.mock import patch
        from race_ai import boat_all_model_cycle as E
        view = E.project_round(self.payload, self.receipt)
        base = deepcopy(view); source = self.manifest['b_sources'][0]
        for p in base['records'][0]['participants']:
            p.update(name='選手名字', name_source=dict(kind='SAME_RACE_PROGRAM',
                registration_no=p['registration_no'], race_id=base['records'][0]['race_id'],
                source_url=source['source_url'], source_sha256=source['source_sha256']))
        with patch.object(E, 'dispatch', side_effect=AssertionError('alias factory reran a model')):
            facts = A.build_program_name_aliases(self.manifest, self.payload, self.receipt, now=self.clock)
        self.assertEqual(len(facts), 5)
        self.assertEqual(facts[0]['full_source']['kind'], 'SAME_RACE_PROGRAM')
        self.assertEqual(facts[0]['full_source']['native_payload_sha256'], digest(self.payload))
        self.assertIsNotNone(facts[0]['full_source']['native_capsule_sha256'])
        original = deepcopy(base)
        merged = M.merge_saved_views(A.attach_name_aliases(base, facts), [view])
        self.assertEqual(base, original)
        person = merged['records'][0]['participants'][0]
        self.assertEqual(person['name'], '選手 1')
        self.assertEqual(person['name_source']['kind'], 'SAME_RACE_PROGRAM')
        self.assertEqual(person['name_source']['source_sha256'], self.payload['current_inputs'][0]['program']['source_sha256'])
        self.assertEqual(forecast_inventory(merged), forecast_inventory(base))
        self.assertEqual(M.merge_saved_views(json.loads(json.dumps(merged)), [view]), merged)

    def test_mutated_name_registration_day_source_or_capsule_cannot_gain_alias(self):
        for change in ('name', 'registration', 'day', 'hash', 'capsule'):
            payload = deepcopy(self.payload); receipt = deepcopy(self.receipt)
            program = payload['current_inputs'][0]['program']
            if change == 'name': program['boats'][0]['name'] = '偽造 全名'
            elif change == 'registration': program['boats'][0]['racer_registration_id'] = '4999'
            elif change == 'day': program['race_id'] = program['race_id'].replace('20300401', '20300402')
            elif change == 'hash': program['source_sha256'] = '9'*64
            else: payload['native_input_capsules'][0]['capsule_sha256'] = '9'*64
            receipt['payload_sha256'] = digest(payload)
            with self.subTest(change=change), self.assertRaises(ValueError):
                A.build_program_name_aliases(self.manifest, payload, receipt, now=self.clock)
        receipt = deepcopy(self.receipt); receipt['payload_sha256'] = '9'*64
        with self.assertRaises(ValueError): A.build_program_name_aliases(self.manifest, self.payload, receipt, now=self.clock)

    def test_legacy_native_program_does_not_gain_an_invented_capsule_receipt(self):
        payload = deepcopy(self.payload); payload.pop('native_input_capsules')
        receipt = dict(self.receipt, payload_sha256=digest(payload))
        facts = A.build_program_name_aliases(self.manifest, payload, receipt, now=self.clock)
        self.assertEqual(len(facts), 5)
        self.assertIsNone(facts[0]['full_source']['native_capsule_sha256'])

    def test_genuine_saved_p0_is_verified_and_leaves_program_name_batch_empty(self):
        from race_ai import boat_all_model_cycle as E
        from tests import test_boat_all_model_cycle as F
        from tests.test_boat_saved_p0_seller_sources import original_p0, NOW
        test = F.AllModelCycleTests(); test.setUp()
        try:
            _, document, original_receipt = original_p0()
            payload = E.forecast_saved_p0(document, original_receipt, test.runtime(), now=NOW)
            receipt = F.receipt(payload, saved=NOW.isoformat())
            batch = A.build_program_name_aliases(self.manifest, payload, receipt, now=self.clock)
        finally: test.doCleanups()
        self.assertEqual(batch, [])

    def test_whole_second_receipt_precision_matches_native_projection_without_clock_rewrite(self):
        from race_ai import boat_all_model_cycle as E
        from race_ai.boat_active_exhibition import parse_active_beforeinfo
        from tests import test_boat_all_model_cycle as F
        from tests.test_boat_active_exhibition import program, main_table, start_table
        from tests.test_boat_observation_context import frame, url
        card = program(withdrawn=(6,))
        captured = '2030-04-01T18:00:00.100000+09:00'
        card['captured_at'] = card['source']['captured_at'] = captured
        for person in card['boats']: person['captured_at'] = captured
        before = parse_active_beforeinfo(frame(main_table(missing=(6,))+start_table(lanes=(1,2,3,4,5))),
            program=card, source_url=url(), captured_at='2030-04-01T18:00:00.200000+09:00')
        context = dict(program=card, beforeinfo=before, as_of='2030-04-01T18:00:00.300000+09:00')
        test = F.AllModelCycleTests(); test.setUp()
        try:
            payload = E.forecast_round([context], test.runtime(),
                now=datetime.fromisoformat('2030-04-01T18:00:00.400000+09:00'))
        finally: test.doCleanups()
        receipt = F.receipt(payload, saved='2030-04-01T18:00:00+09:00')
        projected = E.project_round(payload, receipt)
        inputs = deepcopy((payload, receipt))
        facts = A.build_program_name_aliases(self.manifest, payload, receipt, now=self.clock)
        self.assertEqual(len(facts), 5)
        self.assertEqual(facts[0]['full_source']['captured_at'], captured)
        self.assertEqual(facts[0]['full_source']['created_at'], receipt['created_at'])
        self.assertEqual((payload, receipt), inputs)
        self.assertEqual(E.project_round(payload, receipt), projected)
        invalid = deepcopy(facts[0])
        invalid['full_source']['captured_at'] = '2030-04-01T18:00:01+09:00'
        invalid['fact_sha256'] = digest({k:v for k,v in invalid.items() if k != 'fact_sha256'})
        with self.assertRaisesRegex(ValueError, 'PROGRAM_RECEIPT_CLOCK_INVALID'): A.validate_fact(invalid)


if __name__ == '__main__': unittest.main()
