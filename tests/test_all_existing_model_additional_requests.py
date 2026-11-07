"""Invented source capsules exercise additional native cells without HTTP."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_inputs as inputs
from race_ai.boat_all_model_inputs import build_native_inputs
from race_ai.existing_model_dispatch import GROUPS
from tests.test_boat_all_model_inputs import official_inputs, ASOF


def additional_batch():
    program, before = official_inputs(lanes=tuple(range(1, 7)))
    native = build_native_inputs(program, before, as_of=ASOF)['native_inputs']
    return [dict(cell_key='boat/'+mid, native_payload=deepcopy(native[group]))
            for group, mids in GROUPS if group in ('shared', 'boat_full') for mid in mids]


class AdditionalNativeInputTests(unittest.TestCase):
    def validate(self, requests, **kwargs):
        self.assertTrue(hasattr(inputs, 'validate_additional_requests'),
                        'future native cells need validated additional request admission')
        return inputs.validate_additional_requests(requests, **kwargs)

    def test_six_additional_cells_keep_native_source_clocks_and_do_not_relax_legacy_reader(self):
        requests = additional_batch(); before = deepcopy(requests)
        actual = self.validate(requests + deepcopy(requests))
        self.assertEqual(len(actual), 6)
        self.assertEqual(actual, before)
        self.assertEqual(requests, before)
        with self.assertRaises(ValueError): inputs.current_requests(requests)
        actual[0]['native_payload']['snapshot']['entrants'][0]['features']['ability_rating'] = 0
        self.assertEqual(requests, before)

    def test_unmanifested_or_tampered_derivations_and_direct_source_clocks_fail(self):
        original = additional_batch()[0]
        for kind in ('manifest', 'members', 'future_direct', 'rights', 'provider', 'hash', 'missing_hash', 'missing_capture'):
            bad = deepcopy(original); payload = bad['native_payload']
            if kind == 'manifest': payload['source_evidence'].pop()
            elif kind == 'members': payload['source_evidence'][-1]['source_members'][0]['source_sha256'] = 'f'*64
            else:
                # Exercise a payload with direct references and no URN shortcut.
                source = deepcopy(payload['source_evidence'][0])
                payload['source_evidence'] = [source]
                for entrant in payload['snapshot']['entrants']:
                    entrant['source_ref'] = source['source_ref']
                if kind == 'future_direct': source['captured_at'] = '2030-01-15T09:11:00+09:00'
                elif kind == 'rights': source['source_rights_ref'] = 'UNREVIEWED'
                elif kind == 'provider': source['source_ref'] = 'https://example.test/not-authorized'
                elif kind == 'missing_hash': source.pop('source_sha256')
                elif kind == 'missing_capture': source.pop('captured_at')
                else: source['source_sha256'] = 'invalid'
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.validate([bad])

    def test_foreign_stage_scope_cell_and_conflicting_native_inputs_fail(self):
        original = additional_batch()[0]
        for kind in ('stage', 'scope', 'cell', 'sport'):
            bad = deepcopy(original)
            if kind == 'stage': bad['native_payload']['stage'] = 'P0'
            elif kind == 'scope':
                bad['native_payload']['scope'] = bad['native_payload']['snapshot']['scope'] = 'SYNTHETIC_ONLY'
            elif kind == 'sport': bad['cell_key'] = 'horse/boat-comprehensive-v1'
            else: bad['cell_key'] = 'boat/unknown-native-model'
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.validate([bad])
        bad = deepcopy(original)
        bad['native_payload']['snapshot']['entrants'][0]['features']['ability_rating'] = 1
        with self.assertRaises(ValueError): self.validate([original, bad])

    def test_unfitted_pdca_still_requires_native_facts_and_earlier_result_prerequisites(self):
        payload = additional_batch()[0]['native_payload']; snapshot = payload['snapshot']
        request = dict(cell_key='boat/boat-pdca-lane-shadow-v1', native_payload=dict(
            scope='OPERATOR_SUPPLIED_RESEARCH', source_evidence=deepcopy(payload['source_evidence']), rows=[],
            facts=dict(schema='INVALID', race_id='20300115-17-01', cutoff_at=snapshot['sales_cutoff_at'],
                captured_at=ASOF, source_sha256='b'*64, program_sha256='a'*64,
                racers=[dict(lane=e['lane'], registration_no=e['participant_id']) for e in snapshot['entrants']])))
        with self.assertRaises(ValueError): self.validate([request])

    def test_tactical_venue_must_match_current_native_race(self):
        from race_ai.boat_history_store import HistoryStore
        from tests.test_boat_history_store import archives, DAY
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/'history.sqlite')
            try:
                raw, proofs = archives(); store.ingest_day(DAY, raw['B'], raw['K'], proofs['B'], proofs['K'])
                program, before = official_inputs()
                native = build_native_inputs(program, before, as_of=ASOF,
                    history_context=dict(history_store=store, history_identity_verified=True))['native_inputs']['boat_tactical']
            finally: store.close()
        request = dict(cell_key='boat/boat-course-entry-method-scenarios-v0.1-UNTRAINED', native_payload=native)
        self.assertEqual(len(self.validate([request], now=datetime.fromisoformat(ASOF))), 1)
        future = deepcopy(request)
        future['native_payload']['histories'][0]['as_of'] = '2030-01-15T09:10:01+09:00'
        with self.assertRaises(ValueError): self.validate([future], now=datetime.fromisoformat(ASOF))
        request['native_payload']['venue']['venue_code'] = '18'
        with self.assertRaises(ValueError): self.validate([request], now=datetime.fromisoformat(ASOF))

    def test_direct_proofs_cannot_disagree_at_the_same_url_rights_and_capture(self):
        request = additional_batch()[0]; payload = request['native_payload']
        source = deepcopy(payload['source_evidence'][0]); payload['source_evidence'] = [source]
        for entrant in payload['snapshot']['entrants']: entrant['source_ref'] = source['source_ref']
        for kind in ('hash', 'publication'):
            bad = deepcopy(request); duplicate = deepcopy(source)
            if kind == 'hash': duplicate['source_sha256'] = 'e'*64
            else: duplicate['published_at'] = '2030-01-15T08:45:00+09:00'
            bad['native_payload']['source_evidence'].append(duplicate)
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.validate([bad])


class AdditionalCurrentRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_all_existing_model_runtime import CurrentAllModelRuntimeTests as Fixture, CURRENT
        from tests.test_boat_venue_research import personal_data, refs, NOW
        from race_ai.all_existing_model_derivation import derive_records
        from race_ai.all_existing_model_learning import fit, records_from_observed
        from race_ai.boat_observed_pairwise_models import predict_pair
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from race_ai.four_sport_learning import LEARNED_ID, fit_training_only
        from race_ai.observed_weight_learning import seal
        cls.Fixture = Fixture; Fixture.setUpClass(); cls.addClassCleanup(Fixture.doClassCleanups)
        rows, observations = personal_data(8)
        sid = 'official-venue-grid-'+Fixture.pointer['dataset_sha256'][:16]
        url = ('https://raw.githubusercontent.com/haji84/RACE-AI/'+Fixture.pointer['source_commit']+'/'+
               Fixture.pointer['dataset_path'])
        for row in rows:
            snapshot = row['learning_snapshot']
            for source in snapshot['sources']:
                if source['source_id'].startswith('official-venue-grid-'):
                    source.update(source_id=sid, source_url=url, source_sha256=Fixture.pointer['dataset_sha256'])
            for entrant in snapshot['participants']:
                for name in ('course_mean_finish', 'course_mean_st'):
                    if name in entrant['features']: entrant['features'][name]['source_id'] = sid
            admitted = {(s['source_url'], s['source_rights_ref']) for s in snapshot['sources']}
            suite = predict_pair(snapshot, allow_source=lambda u,r,p:(u,r) in admitted and p == 'analysis')
            model = suite['models'][row['model_id']]
            row.update(learning_snapshot_sha256=digest(snapshot), model_sha256=model['prediction_sha256'],
                       original_json_sha256=digest(suite), top8=model['ordered_top8'],
                       ranked=[r['combination'] for r in model['candidates']])
        originals = records_from_observed(rows, observations)
        derived = derive_records(originals, now=NOW, include_groups=('shared', 'shared_learned', 'boat_full'))
        admitted = set(refs(rows, observations))
        cls.training = fit(originals+derived, now=NOW,
            allow_source=lambda u,r,p:(u,r) in admitted and p == 'analysis',
            allow_training=lambda u,r,p:(u,r) in admitted and p == 'model_training')
        cls.training['venue_dataset_sha256'] = Fixture.pointer['dataset_sha256']; seal(cls.training, 'training_sha256')
        cls.ranker_id = LEARNED_ID
        native_rows = []
        for record in [r for r in derived if r['model_id'] == LEARNED_ID][:6]:
            snapshot = deepcopy(record['native_payload']['snapshot'])
            result = {key:deepcopy(record['result'][key]) for key in ('race_id', 'status', 'ordered_top3',
                'published_at', 'captured_at', 'source_sha256', 'source_ref', 'source_rights_ref')}
            result['race_id'] = snapshot['race']['race_id']
            native_rows.append(dict(snapshot=snapshot, result=result))
        cls.baseline_ranker = fit_training_only(native_rows, sport='boat',
            train_end_at=native_rows[-1]['result']['captured_at'], epochs=1,
            now=lambda:NOW-timedelta(seconds=1),
            allow_source=lambda u,r,p:(u,r) in admitted and p == 'analysis',
            allow_result=lambda u,r,p:(u,r) in admitted and p == 'result_evaluation')
        candidate = Fixture.grid_fixture.root/'additional-nine-cell-candidate'
        seal_candidate(dict(training=cls.training, excluded=[], summary=dict(state='FITTED_SHADOW_ONLY',
                       fitted_model_count=9, plaintext_published=False)), candidate)
        body = io.BytesIO()
        with zipfile.ZipFile(body, 'w') as archive:
            for name in ('learning.enc', 'learning.json', 'summary.json'):
                archive.writestr(name, (candidate/name).read_bytes())
        raw = body.getvalue()
        receipt = dict(id=701, name='all-existing-model-learning-100-1', expired=False,
            digest='sha256:'+hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw),
            created_at=(NOW+timedelta(seconds=2)).isoformat(), expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=100, repository_id=1416489937, head_repository_id=1416489937, head_sha='b'*40))
        cls.context = context_from_encrypted_artifact(raw, 701, now=CURRENT, _fetch=lambda _:deepcopy(receipt))

    def setUp(self):
        from tests.test_all_existing_model_runtime import CURRENT
        self.fixture = self.Fixture('test_full_grid_enrichment_native_pair_ciphertext_readback_precedes_raw_removal')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.runtime['context'] = deepcopy(self.context)
        self.now = CURRENT
        base = self.fixture.requests[0]['native_payload']['source']
        extra = next(r['native_payload']['extra'] for r in self.fixture.requests if 'extra' in r['native_payload'])
        proof = self.fixture.requests[0]['native_payload']['source_evidence']
        by_lane = {r['lane']: r for r in extra['participants']}
        program = dict(race_id=base['race_id'], closed_at=base['cutoff_at'], source_url=proof[0]['source_ref'],
            source_sha256=proof[0]['source_sha256'], captured_at=proof[0]['captured_at'],
            boats=[dict(lane=r['lane'], racer_registration_id=r['racer_id'], entry_status='listed',
                        national_win_rate=r['national_win_rate'], motor_top2_rate=r['motor_two_place_rate_percent'],
                        local_win_rate=by_lane[r['lane']]['local_win_rate'], average_st=by_lane[r['lane']]['average_st'])
                   for r in base['boats']])
        before = dict(race_id=base['race_id'], closed_at=base['cutoff_at'], source_url=proof[1]['source_ref'],
            source_sha256=proof[1]['source_sha256'], captured_at=proof[1]['captured_at'],
            data=dict(boats=[dict(lane=r['lane'], racer_registration_id=r['racer_id'],
                                 display_time=r['exhibition_time_seconds'], preview_st=by_lane[r['lane']]['exhibition_st'],
                                 preview_st_status=by_lane[r['lane']]['exhibition_st_status']) for r in base['boats']]))
        native = build_native_inputs(program, before, as_of=(CURRENT-timedelta(seconds=1)).isoformat(),
                                     fitted_model=self.baseline_ranker)['native_inputs']
        self.additional = [dict(cell_key='boat/'+mid, native_payload=deepcopy(native[group]))
                           for group, mids in GROUPS if group in native for mid in mids]

    def generate(self, requests=None):
        from race_ai.all_existing_model_runtime import generate_current_pairs
        return generate_current_pairs(self.fixture.runtime, self.fixture.pending, self.fixture.output,
            now=self.now, additional_requests=self.additional if requests is None else requests)

    def test_all_nine_fitted_cells_are_paired_and_original_five_are_never_replaced(self):
        from race_ai.boat_venue_learning import read_candidate
        from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
        before = deepcopy((self.additional, self.fixture.requests, self.fixture.runtime))
        summary = self.generate()
        self.assertEqual((summary['forecast_partition_count'], summary['captured_native_input_count']), (9, 12))
        self.assertEqual(summary['native_request_count'], 12)
        self.assertTrue(summary['pending_removed']); self.assertEqual(list(self.fixture.pending.iterdir()), [])
        captured = {}; forecasts = set()
        for folder in self.fixture.output.iterdir():
            if not folder.is_dir(): continue
            payload = read_candidate(folder); forecasts.add(payload['cell_key'])
            for capsule in payload.get('captured_native_inputs', []): captured[capsule['cell_key']] = capsule['native_payload']
        self.assertEqual(len(forecasts), 9)
        for request in self.fixture.requests:
            native = captured[request['cell_key']]
            if request['cell_key'] in {'boat/'+mid for mid in OBSERVED}:
                self.assertEqual(native['original_native_payload'], request['native_payload'])
            else: self.assertEqual(native, request['native_payload'])
        original_cells = {request['cell_key'] for request in self.fixture.requests}
        for request in self.additional:
            if request['cell_key'] not in original_cells:
                self.assertEqual(captured[request['cell_key']], request['native_payload'])
        self.assertEqual((self.additional, self.fixture.requests, self.fixture.runtime), before)

    def test_missing_ranker_baseline_and_mismatched_roster_cutoff_preserve_pending(self):
        for kind in ('ranker', 'roster', 'cutoff', 'future'):
            requests = deepcopy(self.additional)
            if kind == 'ranker':
                next(r for r in requests if r['cell_key'] == 'boat/'+self.ranker_id)['native_payload'].pop('learned_model')
            else:
                snapshot = next(r for r in requests if r['cell_key'] == 'boat/boat-comprehensive-v1')['native_payload']['snapshot']
                if kind == 'roster': snapshot['entrants'][0]['participant_id'] = '9999'
                elif kind == 'cutoff': snapshot['sales_cutoff_at'] = (self.now+timedelta(minutes=20)).isoformat()
                else: snapshot['as_of'] = (self.now+timedelta(seconds=1)).isoformat()
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.generate(requests)
            self.fixture.assert_pending(); self.assertFalse(self.fixture.output.exists())

    def test_missing_extra_in_independent_readback_preserves_original_pending(self):
        from race_ai import all_existing_model_runtime as runtime
        real = runtime.make_private_pairs
        def omit_one(context, requests, output, **kwargs):
            requests = [r for r in requests if r['cell_key'] != 'boat/boat-comprehensive-v1']
            summary = real(context, requests, output, **kwargs)
            summary['captured_native_input_count'] += 1
            (Path(output)/'summary.json').write_text(json.dumps(summary), encoding='utf-8')
            return summary
        with patch.object(runtime, 'make_private_pairs', side_effect=omit_one):
            with self.assertRaisesRegex(ValueError, 'CAPTURED_INPUTS_INCOMPLETE'): self.generate()
        self.fixture.assert_pending()

    def test_explicit_empty_additions_keep_the_original_five_input_path(self):
        summary = self.generate(())
        self.assertEqual((summary['forecast_partition_count'], summary['captured_native_input_count']), (2, 5))
        self.assertEqual(summary['native_request_count'], 5)
        self.assertTrue(summary['pending_removed'])


if __name__ == '__main__': unittest.main()
