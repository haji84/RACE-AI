"""Synthetic boundary tests, not evidence of live source admission."""
from copy import deepcopy
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.chatgpt_dt_r1.data import input_digest
from research.chatgpt_dt_r1.features import FeatureBuilder
from research.chatgpt_dt_r1.policy import digest

try:
    admission = importlib.import_module('research.chatgpt_dt_r1.admission')
except ModuleNotFoundError:
    admission = None


DAY = '2030-01-15'
RID = '203001159801'
CUTOFF = '2030-01-15T15:00:00+09:00'
CAPTURED = '2030-01-15T13:00:00+09:00'
VERIFIED = '2030-01-15T04:05:00+00:00'
COMMIT = 'a' * 40


def metadata(kind, race_id=None):
    row = dict(kind=kind, evidence_sha256={'registry': 'b', 'original': 'c', 'result': 'd'}[kind] * 64,
               cipher_sha256='e' * 64, observed_at=CAPTURED,
               producer_run_id='12345', producer_commit='f' * 40)
    if race_id is not None:
        row['race_id'] = race_id
    if kind == 'original':
        row.update(cutoff_at=CUTOFF, baseline_cipher_sha256='1' * 64)
    if kind == 'result':
        row.update(monetary_complete=False, observed_at='2030-01-15T06:15:00Z')
    return row


def source_fixture():
    proof = dict(schema='RACE_AI_KEIRIN_GITHUB_SERVER_ORIGIN_EVIDENCE_V1',
                 state='GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED', race_id=RID,
                 cipher_sha256='1' * 64, official_cutoff_at=CUTOFF,
                 latest_server_evidence_at=VERIFIED, minimum_margin_seconds=65,
                 producer_run_id=12345, producer_commit='f' * 40,
                 producer_job_id=100, producer_artifact_id=200, producer_archive_sha256='2' * 64,
                 readback_run_id=12345, readback_commit='f' * 40,
                 readback_job_id=101, readback_artifact_id=201, readback_archive_sha256='3' * 64,
                 RSA_decryption_verified=False, official_result_verified=False)
    proof['evidence_sha256'] = digest(proof)
    snapshot = dict(race_id=RID, as_of=CAPTURED, published_cutoff_at=CUTOFF,
                    competition='A1_A2', round_stage='A級予選',
                    cutoff_source=dict(url='https://keirin.jp/sp/race', bytes_sha256='4' * 64,
                                       captured_at=CAPTURED),
                    source_pages=[dict(kind='RACECARD', url='https://keirin.jp/sp/race',
                                       bytes_sha256='4' * 64, captured_at=CAPTURED)],
                    line_groups=[[1, 2], [3]], riders=[
                        dict(car=i, athlete_id=f'{100000+i}', competition_points=80.0+i,
                             recent_form_score=.1*i, h_count=i, b_count=i+1,
                             style=('NIGE', 'SASHI', 'ALLROUND')[i-1]) for i in (1, 2, 3)])
    original = dict(race_id=RID, day_jst=DAY, producer_run_id='12345', producer_commit='f' * 40,
                    snapshot=snapshot, baseline_cipher_sha256='1' * 64,
                    baseline_sealed_at=CAPTURED, baseline={'PRIVATE_MODEL_SENTINEL': True},
                    origin_receipts=dict(baseline_origin=proof, condition_origin=None))
    ids = [RID, '203001159802', '203001159803']
    registry = dict(event_day=DAY, registered_race_ids=ids, races=[
        dict(race_id=rid, venue_code=98, race_no=i, official_cutoff_at=None,
             list_source_sha256='5' * 64) for i, rid in enumerate(ids, 1)],
        calendar_source_sha256='6' * 64, list_source_sha256=['5' * 64],
        day_inventory_complete=True, missing_venues=[], disappeared_race_ids=[])
    loaded = dict(day_jst=DAY, registry=registry, records=[original], observed_at=CAPTURED,
                  states=[dict(race_id=rid,
                               state='A_B_AUTHENTICATED_PRE_CUTOFF' if rid == RID else 'WAITING_SOURCE_CAPTURE',
                               condition_state='NO_CONDITIONED_ORIGINAL') for rid in ids],
                  starter_rows=[dict(race_id=RID, source_at=CAPTURED, riders=[
                      dict(number=i, registration=f'{100000+i}', name='SYNTHETIC_NAME_PRIVATE')
                      for i in (1, 2, 3)])])
    return dict(archive_commit=COMMIT, admission=loaded,
                index=dict(registry=metadata('registry'), originals={RID: metadata('original', RID)}, results={}))


class SyntheticAdmissionFacade:
    """Explicitly injected trusted-test code, never a production evidence file."""
    def __init__(self):
        self.source = source_fixture()
        self.calls = 0
        self.fail = False
        self.result = dict(archive_commit=COMMIT, original_meta=metadata('original', RID),
                           result_meta=metadata('result', RID), revision=1,
                           source_sha256='7' * 64, source_observed_at='2030-01-15T06:10:00Z',
                           result_roster=[1, 2, 3],
                           updates=dict(races=[dict(race_id=RID, authority='official', order_status='confirmed',
                               observed_at='2030-01-15T06:15:00Z', winning_triples=['1-2-3'])]))

    def load_day(self, day):
        self.calls += 1
        if self.fail:
            raise ValueError('PRIVATE_EXCEPTION_MUST_NOT_ESCAPE')
        return deepcopy(self.source)

    def replay_result(self, day, race_id, *, revision=None):
        if self.fail:
            raise ValueError('PRIVATE_EXCEPTION_MUST_NOT_ESCAPE')
        return deepcopy(self.result)


def simple_binding(row):
    return {k: row[k] for k in ('race_id', 'day', 'input_sha256', 'cohort', 'cutoff_at')} | {
        'starters': [r['car'] for r in row['riders']]}


def runtime_binding(row):
    featured = FeatureBuilder().transform(row)
    as_of = '2030-01-15T04:10:00Z'
    history_sha = digest([])
    return simple_binding(row) | dict(field_size=len(row['riders']), **{'class': row['race_class']},
        venue=row['venue_code'], feature_model_id='synthetic-dt-r1',
        feature_input_sha256=featured['feature_input_sha256'],
        feature_schema_sha256=digest(list(featured['feature_names'])),
        history_snapshot_sha256=history_sha,
        dataset_snapshot_sha256=digest(dict(target_input_sha256=row['input_sha256'],
            declared_dataset_sha256=row.get('dataset_sha256'), source_sha256=row.get('source_sha256'),
            history_snapshot_sha256=history_sha)),
        context_snapshot_sha256=digest(dict(venue_records=None, timing_records=[], weather_observation=None,
            as_of=as_of, allow_current_geometry_assumption=False)), context_as_of=as_of,
        context_evidence=None, history_evidence_sha256=digest(featured['history_evidence']))


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(admission, 'official admission adapter missing')
        self.facade = SyntheticAdmissionFacade()
        self.adapter = admission.OfficialAdmissionAdapter(self.facade)

    def test_all_registered_races_and_unknown_fields_survive_without_private_models(self):
        day = self.adapter.load_day(DAY)
        self.assertEqual(len(day['records']), 3)
        self.assertEqual(day['audit']['admitted_races'], 1)
        self.assertEqual(day['audit']['held_races'], 2)
        row = day['records'][0]
        self.assertEqual(row['race_class'], 'A12')
        self.assertEqual(row['source_available_at'], CAPTURED)
        self.assertEqual(row['cutoff_at'], CUTOFF)
        self.assertIsNone(row['riders'][0]['age'])
        self.assertIsNone(row['riders'][0]['top2_rate'])
        self.assertEqual(row['riders'][0]['official_registration_id'], '100001')
        self.assertEqual(row['riders'][0]['win_rate'], .1)
        self.assertFalse(row['publication_time_authenticated'])
        self.assertEqual(row['source_attestation_sha256'], row['source_proof']['origin_receipt_sha256'])
        self.assertEqual(row['input_sha256'], input_digest(row))
        self.assertIsNone(day['records'][1]['cutoff_at'])
        self.assertEqual(day['records'][1]['source_admission_status'], 'HOLD')
        text = json.dumps(day)
        self.assertNotIn('SYNTHETIC_NAME_PRIVATE', text)
        self.assertNotIn('PRIVATE_MODEL_SENTINEL', text)

    def test_athlete_id_without_card_registration_is_not_an_official_identity(self):
        self.facade.source['admission']['starter_rows'] = []
        row = self.adapter.load_day(DAY)['records'][0]
        for rider in row['riders']:
            self.assertIsNone(rider['official_registration_id'])
            self.assertFalse(rider['identity_usable'])
            self.assertEqual(rider['identity_status'], 'UNRESOLVED_RACE_SCOPED')
        self.assertEqual(len({r['identity_key'] for r in row['riders']}), 3)

    def test_l1_and_contested_or_incomplete_lines_never_become_cooperating_singletons(self):
        snapshot = self.facade.source['admission']['records'][0]['snapshot']
        snapshot['competition'] = 'GIRLS'
        row = self.adapter.load_day(DAY)['records'][0]
        self.assertEqual(row['race_class'], 'L1')
        self.assertFalse(row['lines_known'])
        self.assertFalse(row['lines_applicable'])
        self.assertEqual(row['line_groups'], [])
        snapshot.update(competition='A1_A2', line_status='CONTESTED')
        self.assertFalse(self.adapter.load_day(DAY)['records'][0]['lines_known'])
        snapshot.pop('line_status'); snapshot['line_groups'] = [[1, 2]]
        row = self.adapter.load_day(DAY)['records'][0]
        self.assertFalse(row['lines_known'])
        self.assertEqual(row['line_groups'], [])
        self.assertEqual(row['published_line_groups'], [[1, 2]])

    def test_verifier_replays_origin_and_rejects_changed_payload_or_self_assertions(self):
        row = self.adapter.load_day(DAY)['records'][0]
        binding = simple_binding(row)
        checked = self.adapter.source_verifier(binding)
        self.assertTrue(checked['verified'] and checked['independent'])
        self.assertEqual(checked['payload_sha256'], digest(binding))
        self.assertGreaterEqual(self.facade.calls, 2)
        for changed in (dict(binding, input_sha256='0'*64), dict(binding, starters=[1, 2, 4]),
                        dict(binding, starters=[True, 2, 3]),
                        dict(binding, cutoff_at='2030-01-15T16:00:00+09:00'), dict(binding, verified=True)):
            with self.assertRaises(ValueError):
                self.adapter.source_verifier(changed)
        self.facade.fail = True
        with self.assertRaisesRegex(ValueError, '^OFFICIAL_ADMISSION_') as caught:
            self.adapter.source_verifier(binding)
        self.assertNotIn('PRIVATE_EXCEPTION', str(caught.exception))
        with self.assertRaises(ValueError):
            admission.OfficialAdmissionAdapter(lambda _: True)

    def test_full_runtime_binding_checks_numeric_features_and_empty_context(self):
        row = self.adapter.load_day(DAY)['records'][0]
        binding = runtime_binding(row)
        self.assertTrue(self.adapter.source_verifier(binding)['verified'])
        for key in ('feature_input_sha256', 'history_snapshot_sha256', 'dataset_snapshot_sha256',
                    'context_snapshot_sha256', 'history_evidence_sha256', 'feature_schema_sha256'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.adapter.source_verifier(dict(binding, **{key: '0'*64}))
        with self.assertRaises(ValueError):
            self.adapter.source_verifier(dict(binding, context_evidence={'verified': True}))
        early = runtime_binding(row); early['context_as_of'] = '2030-01-15T03:00:00Z'
        with self.assertRaises(ValueError):
            self.adapter.source_verifier(early)

    def test_invalid_proof_or_missing_registry_cannot_bless_inputs(self):
        original = self.facade.source['admission']['records'][0]
        original['origin_receipts']['baseline_origin']['cipher_sha256'] = '0'*64
        out = self.adapter.load_day(DAY)
        self.assertEqual(len(out['records']), 3)
        self.assertEqual(out['audit']['admitted_races'], 0)
        with self.assertRaises(ValueError):
            self.adapter.source_verifier(simple_binding(out['records'][0]))
        self.facade.source['admission']['registry'] = None
        with self.assertRaises(ValueError):
            self.adapter.load_day(DAY)

    def test_authenticated_support_rebuilds_all_224_features_and_refuses_unverified_history(self):
        from dataclasses import asdict
        from research.chatgpt_dt_r1.context import augment_features
        from research.chatgpt_dt_r1.features import build_features
        from research.chatgpt_dt_r1.venues import VenueStore
        row = self.adapter.load_day(DAY)['records'][0]
        history = deepcopy(row)
        history.update(race_id='203001149801', day='2030-01-14',
                       cutoff_at='2030-01-14T15:00:00+09:00', published_cutoff_at='2030-01-14T15:00:00+09:00',
                       available_at='2030-01-14T04:00:00Z', result_at='2030-01-14T06:10:00Z',
                       top3=[1, 2, 3], result_rows=[dict(car=i, rank=i, incident=False) for i in (1, 2, 3)])
        history['input_sha256'] = input_digest(history)
        store = VenueStore.from_records([dict(venue_code='98', name='Synthetic',
            source_url='https://example.test/synthetic-venue', source_sha256='8'*64,
            retrieved_at='2030-01-01T00:00:00Z', circumference_m=400., straight_m=60., cant_deg=30.,
            geometry_scope='dated', effective_from='2020-01-01')])
        timing = dict(observation_id='synthetic-timing', race_id=history['race_id'],
            rider_id=row['riders'][0]['identity_key'], venue_id='98',
            event_at='2030-01-14T06:05:00Z', event_day='2030-01-14',
            timings={'agari_half_seconds': 12.}, identity_confidence=1.,
            uncertainties={'agari_half_seconds': .05}, provenance=dict(kind='official_record',
                source_url='https://example.test/synthetic-timing', source_sha256='9'*64,
                retrieved_at='2030-01-14T06:10:00Z', available_at='2030-01-14T06:10:00Z'))
        as_of = '2030-01-15T04:10:00Z'
        support_calls = []
        def verify(support):
            support_calls.append(deepcopy(support))
            return dict(verified=True, independent=True, verifier='SYNTHETIC_TEST_ONLY',
                receipt_sha256='a'*64, payload_sha256=digest(support), source_receipt_sha256s=['b'*64])
        adapter = admission.OfficialAdmissionAdapter(self.facade, history_records=[history], venue_store=store,
            timing_records=[timing], context_as_of=as_of, support_verifier=verify)
        featured = augment_features([build_features([history, row])[-1]], venue_store=store,
            timing_records=[timing], as_of=as_of)[0]
        self.assertEqual(len(featured['feature_names']), 224)
        self.assertGreater(featured['features'][0, featured['feature_names'].index('history_entries_log')], 0)
        self.assertAlmostEqual(featured['features'][0,
            featured['feature_names'].index('history_observed_agari_half_seconds_mean')], .6)
        binding = runtime_binding(row)
        history_sha = digest([history])
        binding.update(feature_input_sha256=featured['feature_input_sha256'],
            feature_schema_sha256=digest(list(featured['feature_names'])), history_snapshot_sha256=history_sha,
            dataset_snapshot_sha256=digest(dict(target_input_sha256=row['input_sha256'],
                declared_dataset_sha256=None, source_sha256=row['source_sha256'], history_snapshot_sha256=history_sha)),
            context_snapshot_sha256=digest(dict(venue_records=[asdict(r) for r in store.records],
                timing_records=[timing], weather_observation=None, as_of=as_of, allow_current_geometry_assumption=False)),
            context_evidence=featured['context_evidence'], history_evidence_sha256=digest(featured['history_evidence']))
        self.assertTrue(adapter.source_verifier(binding)['verified'])
        self.assertEqual(support_calls[0]['history_records'], [history])
        self.assertEqual(support_calls[0]['timing_records'], [timing])
        for bad_verifier in (None, lambda _: True, lambda payload: dict(verified=True, independent=True,
                verifier='SELF_HASH_ONLY', receipt_sha256=digest(payload), payload_sha256=digest(payload))):
            adapter.support_verifier = bad_verifier
            with self.assertRaises(ValueError):
                adapter.source_verifier(binding)
        adapter.support_verifier = verify
        adapter.history_records[0]['result_at'] = '2030-01-16T00:00:00Z'
        with self.assertRaises(ValueError):
            adapter.source_verifier(binding)

    def test_agari_schema_and_weather_reconstructed_under_independent_support_receipt(self):
        from research.chatgpt_dt_r1.context import augment_features
        from research.chatgpt_dt_r1.agari import augment_agari
        from research.chatgpt_dt_r1.features import build_features
        as_of = '2030-01-15T04:10:00Z'
        weather = dict(kind='forecast', source_sha256='c'*64, issued_at='2030-01-15T03:00:00Z',
                       available_at='2030-01-15T03:01:00Z', wind_speed_m_s=5.)
        calls = []
        def verify(support):
            calls.append(deepcopy(support))
            return dict(verified=True, independent=True, verifier='SYNTHETIC_TEST_ONLY',
                receipt_sha256='a'*64, payload_sha256=digest(support), source_receipt_sha256s=['b'*64])
        adapter = admission.OfficialAdmissionAdapter(self.facade, context_as_of=as_of,
            weather_records={RID:weather}, support_verifier=verify)
        row = adapter.load_day(DAY)['records'][0]
        featured = augment_agari(augment_features(build_features([row]), as_of=as_of))[0]
        self.assertEqual(featured['context_evidence']['weather_source'], 'c'*64)
        binding = runtime_binding(row)
        binding.update(feature_input_sha256=featured['feature_input_sha256'],
            feature_schema_sha256=digest(list(featured['feature_names'])),
            context_snapshot_sha256=digest(dict(venue_records=None, timing_records=[],
                weather_observation=weather, as_of=as_of, allow_current_geometry_assumption=False)),
            context_evidence=featured['context_evidence'], history_evidence_sha256=digest(featured['history_evidence']))
        self.assertTrue(adapter.source_verifier(binding)['verified'])
        self.assertEqual(calls[0]['weather_observation'],weather)
        adapter.weather_records[RID]['wind_speed_m_s']=20.
        with self.assertRaises(ValueError):
            adapter.source_verifier(binding)

    def test_results_only_come_from_replay_and_do_not_change_input_binding(self):
        before = self.adapter.load_day(DAY)['records'][0]
        after = self.adapter.load_day(DAY, include_results=True)['records'][0]
        self.assertEqual(before['input_sha256'], after['input_sha256'])
        self.assertEqual(after['top3'], [1, 2, 3])
        self.assertEqual([r['rank'] for r in after['result_rows']], [1, 2, 3])
        self.assertTrue(all(r['incident'] is None for r in after['result_rows']))
        self.assertEqual(after['result_at'], '2030-01-15T06:15:00Z')
        outcome = dict(race_id=RID, day=DAY, top3=[1, 2, 3], status='settled',
                       result_at=after['result_at'], field_size=3, **{'class': 'A12'}, venue='98')
        receipt = self.adapter.result_verifier(outcome)
        self.assertEqual(receipt['payload_sha256'], digest(outcome))
        self.assertEqual(receipt['authority'], 'official')
        self.assertEqual(receipt['source_sha256'], after['result_source_sha256'])
        for changed in (dict(outcome, top3=[1, 3, 2]), dict(outcome, top3=[True, 2, 3]), dict(outcome, status='cancelled'),
                        dict(outcome, result_at=CAPTURED), dict(outcome, revision=2)):
            with self.assertRaises(ValueError):
                self.adapter.result_verifier(changed)
        self.facade.result['updates']['races'][0]['winning_triples'] = ['1-2-3', '2-1-3']
        tied = self.adapter.load_day(DAY, include_results=True)['records'][0]
        self.assertIsNone(tied['top3'])
        self.assertEqual(tied['result_status'], 'DEAD_HEAT')
        self.assertTrue(self.adapter.result_verifier(dict(outcome, status='dead_heat', top3=None))['verified'])

    def test_pinned_facade_never_fetches_or_constructs_a_default_credential_client(self):
        from race_ai import keirin_official_nationwide_records as existing
        from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
        client = GitHubEvidenceClient(token='', open_request=lambda *a, **k: self.fail('NETWORK'))
        client._cache['/actions/runs/12345'] = b'{"id":12345}'
        with patch.dict(os.environ, {'GIT_NO_LAZY_FETCH': '1'}):
            facade = admission.PinnedOfficialArchive(repo='/synthetic', owner_private_pem=b'SYNTHETIC_NOT_A_KEY',
                        index_commit=COMMIT, origin_client=client)
            self.assertEqual(facade.origin_client.json('/actions/runs/12345'), {'id': 12345})
            with self.assertRaisesRegex(ValueError, 'CACHE_MISS'):
                facade.origin_client.json('/actions/runs/99999')
            class Store:
                head = COMMIT
                index = source_fixture()['index']
            with patch.object(existing, 'load_admitted_day', return_value=self.facade.source['admission']) as load:
                with patch.object(existing, 'RecordStore', return_value=Store()):
                    envelope = facade.load_day(DAY)
            self.assertEqual(envelope['archive_commit'], COMMIT)
            self.assertEqual(load.call_args.kwargs['index_commit'], COMMIT)
            self.assertTrue(load.call_args.kwargs['include_starters'])
            self.assertIs(load.call_args.kwargs['origin_client'], facade.origin_client)
            result_meta = metadata('result', RID)
            Store.index = deepcopy(Store.index)
            Store.index['results'] = {RID: [result_meta]}
            Store.read = lambda self, meta, key: {'scored': {'official_result': {
                'source_sha256': '7'*64, 'observed_at': '2030-01-15T06:10:00Z',
                'starters': [dict(car=i, registration_id=f'{100000+i}') for i in (1, 2, 3)]}}}
            with patch.object(existing, 'RecordStore', return_value=Store()):
                with patch.object(existing, 'replay_saved_result', return_value=self.facade.result['updates']) as replay:
                    result = facade.replay_result(DAY, RID)
            self.assertEqual(result['revision'], 1)
            self.assertEqual(result['source_sha256'], '7'*64)
            self.assertEqual(result['result_roster'], [1, 2, 3])
            self.assertEqual(replay.call_args.args[1], Store.index['originals'][RID])
            self.assertEqual(replay.call_args.args[2], result_meta)
        with patch.dict(os.environ, {'GIT_NO_LAZY_FETCH': '0'}):
            with self.assertRaises(ValueError):
                admission.PinnedOfficialArchive(repo='/synthetic', owner_private_pem=b'NO_KEY',
                    index_commit=COMMIT, origin_client=client)

    def five_car_result(self):
        snapshot = self.facade.source['admission']['records'][0]['snapshot']
        projection = self.facade.source['admission']['starter_rows'][0]['riders']
        for car in (4, 5):
            snapshot['riders'].append(dict(snapshot['riders'][0], car=car, athlete_id=f'{100000+car}'))
            projection.append(dict(number=car, registration=f'{100000+car}', name='SYNTHETIC_NAME_PRIVATE'))
        snapshot['line_groups'] = [[1, 2], [3, 4, 5]]
        self.facade.result['result_roster'] = [1, 2, 3, 4, 5]
        return self.adapter.load_day(DAY, include_results=True)['records'][0]

    def test_calendar_result_end_to_end_keeps_original_unknown_input_and_separate_final_roster(self):
        from research.chatgpt_dt_r1.runtime import ResearchLedger
        row = self.five_car_result()
        self.assertEqual(row['result_roster'], [1, 2, 3, 4, 5])
        self.assertEqual(row['result_field_size'], 5)
        full_source = deepcopy(self.facade.source)
        self.facade.source['admission'].update(records=[], starter_rows=[])
        self.facade.source['index']['originals'] = {}
        held = self.adapter.load_day(DAY)['records'][0]
        calendar = simple_binding(held)
        self.facade.source = full_source
        for result_roster, field_size, race_class in ((None, None, 'UNKNOWN'), ([5, 4, 3, 2, 1], 5, 'A12')):
            with self.subTest(roster=result_roster), tempfile.TemporaryDirectory() as folder:
                ledger = ResearchLedger.initialize(Path(folder) / 'ledger.sqlite',
                    participant_ids=['existing-integrated', 'codex-new', 'dt-r1'],
                    now=lambda: '2030-01-15T06:20:00Z')
                try:
                    self.assertEqual(ledger.register_race(calendar, source_verifier=self.adapter.source_verifier)['status'], 'HOLD')
                    outcome = dict(race_id=RID, day=DAY, top3=[1, 2, 3], status='settled',
                        result_at=row['result_at'], result_roster=result_roster, field_size=field_size,
                        **{'class': race_class}, venue='98')
                    event = ledger.append_result(outcome, result_verifier=self.adapter.result_verifier)
                    saved = ledger.latest_results()[0]
                    self.assertTrue(saved['input_roster_unknown'])
                    self.assertEqual(saved['result_roster'], result_roster)
                    self.assertEqual(saved['field_size'], field_size)
                    self.assertEqual(ledger.registry(), [calendar])
                    self.assertEqual(ledger.registry()[0]['starters'], [])
                    self.assertIsNone(ledger.registry()[0]['cutoff_at'])
                    self.assertEqual(ledger.events('race_admission'), [])
                    self.assertEqual(ledger.coverage()['missing_forecasts'], 3)
                    self.assertEqual(event['body']['receipt']['authority'], 'official')
                    self.assertEqual(event['body']['receipt']['source_sha256'], row['result_source_sha256'])
                finally:
                    ledger.close()

    def test_calendar_result_rejects_invented_full_roster_size_or_missing_original(self):
        row = self.five_car_result()
        outcome = dict(race_id=RID, day=DAY, top3=[1, 2, 3], status='settled', result_at=row['result_at'],
                       input_roster_unknown=True, result_roster=[1, 2, 3, 4, 5], field_size=5,
                       **{'class': 'A12'}, venue='98')
        self.assertTrue(self.adapter.result_verifier(outcome)['verified'])
        for changed in (dict(outcome, result_roster=[1, 2, 3]), dict(outcome, result_roster=[1, 2, 3, 4, 6]),
                        dict(outcome, result_roster=[True, 2, 3, 4, 5]), dict(outcome, field_size=3),
                        dict(outcome, input_roster_unknown='true'), dict(outcome, **{'class': 'S'}),
                        dict(outcome, input_roster_unknown=False, field_size=None)):
            with self.subTest(changed=sorted(changed)), self.assertRaises(ValueError):
                self.adapter.result_verifier(changed)
        self.facade.source['admission'].update(records=[], starter_rows=[])
        self.facade.source['index']['originals'] = {}
        with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_ADMITTED'):
            self.adapter.result_verifier(outcome)

    def test_real_runtime_interface_keeps_unadmitted_calendar_denominator(self):
        from research.chatgpt_dt_r1.model import RankModel
        from research.chatgpt_dt_r1.pipeline import forecast_row
        from research.chatgpt_dt_r1.policy import fixed_selection
        from research.chatgpt_dt_r1.runtime import ResearchLedger, run_shadow_cycle
        rows = self.adapter.load_day(DAY)['records']
        at = '2030-01-15T04:10:00Z'
        feature_row = FeatureBuilder().transform(rows[0])
        model = RankModel.zero(feature_row['feature_names'])
        model.fit_meta.update(created_at='2030-01-01T00:00:00Z', training_last_day='2029-12-31')
        forecast = forecast_row(model, feature_row, prediction_at=at)
        self.assertEqual(forecast['status'], 'READY')
        model_id = forecast['model_id']
        pin = dict(model_sha256=forecast['model_sha256'], policy_sha256=fixed_selection(forecast, 1)['policy_sha256'])
        def synthetic_readback(payload):
            return dict(verified=True, independent=True, verifier='SYNTHETIC_READBACK_ONLY',
                        receipt_sha256='f'*64, payload_sha256=digest(payload))
        with tempfile.TemporaryDirectory() as folder:
            ledger = ResearchLedger.initialize(Path(folder) / 'ledger.sqlite',
                participant_ids=['existing-integrated', 'codex-new', model_id],
                pins={model_id: pin}, now=lambda: at)
            try:
                result = run_shadow_cycle(ledger, rows, model,
                    source_verifier=self.adapter.source_verifier, result_verifier=self.adapter.result_verifier,
                    readback_verifier=synthetic_readback)
                self.assertEqual(result['coverage']['scheduled_races'], 3)
                self.assertEqual(result['coverage']['verified_forecasts'], 1)
                self.assertEqual(result['coverage']['missing_forecasts'], 8)
                self.assertIsNone(result['comparison']['verdict']['winner'])
            finally:
                ledger.close()


if __name__ == '__main__':
    unittest.main()
