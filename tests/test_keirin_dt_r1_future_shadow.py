"""Synthetic owner-codec tests; no real key, source access or live forecast claim."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_official_run_history as codec
from research.chatgpt_dt_r1.policy import digest
from tests.test_keirin_learned_official_inputs import _original
from tests import test_keirin_official_nationwide_extension as official_fixture
from tests.test_keirin_official_sp_receipt import detail_data, html
from tests.test_keirin_official_form_history import profile


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2030-01-15T02:01:00+00:00')


def nine_rider_original():
    """Nine invented source-bound riders, for the largest supported field."""
    from race_ai import keirin_official_nationwide_extension as ext
    from race_ai import keirin_nationwide_auto_generator as old_model
    args = official_fixture.NationwideExtensionTests().baseline_arguments()
    when = args.pop('now')
    card = args['card_arguments']
    card['list_raw'] = card['list_raw'].replace('Ｌ級ガールズ選抜'.encode(), 'Ｓ級選抜'.encode())
    card['list_sha256'] = sha256(card['list_raw']).hexdigest()
    data = detail_data(9)
    for rider in data['SJ0315']['sensyuTypeInfo']:
        rider.update(kyuhan='S1', heikinTokuten='51.25')
    data['SC0201']['C0201data']['encSelParaR'] = 'C' * 64
    positions = (1, 2, 3, 5, 6, 8, 9, 11, 12)
    data['SJ0314'] = dict(resultCd=0, narabiyoso=dict(lineKeitai='四分戦', lineKeitaiClass='yonbusen',
        errFlg='false', ryoikiFlg='true', kyoHyoji='false', maxAxixY=1, teikyo='架空紙',
        shaban=[dict(shaban=str(car), ichi=str(pos)) for car, pos in enumerate(positions, 1)]))
    scripts = args['prediction_scripts']
    extra = '<button onclick="btnClickOfFrame(\'SJ0321\')">予想情報</button>'
    extra += ''.join('<script src="' + path + '"></script>' for path in (*scripts, ext.LINE_VIEW_PATH))
    raw = html(data).replace(b'var jsonData', b'var displayingSyoriKbn = 1; var jsonData')
    card['detail_raw'] = raw.replace(b'</body>', extra.encode() + b'</body>')
    card['detail_sha256'] = sha256(card['detail_raw']).hexdigest()
    view = '\n'.join(ext._LINE_VIEW_FRAGMENTS).encode()
    card['line_view_source'] = dict(raw_bytes=view, expected_sha256=sha256(view).hexdigest(), observed_at=when)
    marks = json.loads(args['prediction_source']['raw_bytes'])
    for car in (8, 9):
        marks['sensyuTypeInfo'].append(dict(syaban=str(car), sensyuRegistNo=f'99{car:04d}',
            sensyuName=f'架空選手{car}', sensyuComment='架空コメント'))
    raw = json.dumps(marks, ensure_ascii=False).encode()
    args['prediction_source'].update(raw_bytes=raw, expected_sha256=sha256(raw).hexdigest())
    args['profile_sources'] = []
    for car in range(1, 10):
        registration = f'99{car:04d}'
        raw = profile(registration).replace('試験選手'.encode(), f'架空選手{car}'.encode())
        raw = raw.replace(b'2026/11/20', b'2030/01/15').replace(b'51.00', b'51.25')
        raw = raw.replace('Ｌ級１班'.encode(), b'S1')
        args['profile_sources'].append(dict(registration_id=registration, raw_bytes=raw,
            expected_sha256=sha256(raw).hexdigest(), observed_at=when, http_status=200,
            source_url='https://keirin.jp/sp/racerracentrecord?snum=' + registration))
    snapshot = ext.build_baseline_candidate(**args, now=when)['snapshot']
    baseline = old_model.generate_A_B(snapshot, generated_at=when.isoformat())
    payload, original = _original()
    for record in (payload, original):
        record.update(snapshot=snapshot, baseline=baseline)
    payload['baseline_arguments'] = args
    return payload, original


class FutureShadowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.api = importlib.import_module('scripts.keirin_dt_r1_future_shadow')
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / 'safe'
        self.payload, self.original = _original()
        self.rid = self.original['race_id']
        self.day = self.original['day_jst']
        self.ids = [f'2030011598{i:02d}' for i in range(1, 79)]
        self.registry = dict(event_day=self.day, registered_race_ids=self.ids,
                             day_inventory_complete=True)
        self.registry_meta = dict(kind='registry', evidence_sha256='1' * 64,
            cipher_sha256='2' * 64, observed_at=NOW.isoformat(),
            producer_commit='3' * 40, producer_run_id='123')
        self.original_meta = dict(kind='original', race_id=self.rid,
            evidence_sha256='4' * 64, cipher_sha256='5' * 64,
            baseline_cipher_sha256='a' * 64, cutoff_at=self.original['snapshot']['published_cutoff_at'],
            observed_at=NOW.isoformat(), producer_commit='3' * 40, producer_run_id='123')
        self.reads = []
        def read(meta, private):
            self.reads.append(meta['kind'])
            self.assertEqual(private, self.private)
            if meta['kind'] == 'registry':
                return {'registry': self.registry, 'observed_at': NOW.isoformat()}
            if meta['kind'] == 'original':
                return deepcopy(self.payload)
            raise AssertionError('Prediction mode must never read results')
        self.store = SimpleNamespace(day=self.day, head='b' * 40,
            index=dict(registry=self.registry_meta, originals={self.rid: self.original_meta},
                       results={self.rid: [{'kind': 'result'}]}), read=read)
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937', GITHUB_REF='refs/heads/main',
            GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_RUN_ID='456', GITHUB_SHA='c' * 40,
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main',
            GITHUB_JOB='observe-results', RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED='true')
        self.current = NOW
        self.stack = []
        for patched in (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin),
            patch.object(self.api.records, 'replay_registry', return_value=self.registry),
            patch.object(self.api.records, 'admit_original',
                side_effect=lambda *a, **k: (deepcopy(self.original), {'synthetic': True})),
        ):
            self.stack.append(patched.start()); self.addCleanup(patched.stop)
        self.admit = self.stack[-1]

    def produce(self):
        return self.api.produce_day(store=self.store, repo=ROOT, output=self.output,
            owner_public_pem=self.public, owner_private_pem=self.private,
            code_commit='c' * 40, origin_client=object(), clock=lambda: self.current)

    def manifest(self):
        return json.loads((self.output / 'manifest.json').read_bytes())

    def test_registered_denominator_survives_missing_originals_and_results_are_never_read(self):
        report = self.produce()
        self.assertEqual(report['registered_races'], 78)
        self.assertEqual(report['saved_originals'], 1)
        self.assertEqual(report['new_encrypted_forecasts'], 1)
        self.assertEqual(report['locally_saved_before_t15'], 1)
        self.assertEqual(report['held_races'], 77)
        self.assertEqual(report['hold_reasons'], {'SAVED_ORIGINAL_MISSING': 77})
        self.assertEqual(report['formal_three_way_races'], 0)
        self.assertEqual(report['independently_admitted_new_forecasts'], 0)
        self.assertEqual(report['history_races'], 0)
        self.assertEqual(report['confidence'], 'HOLD')
        self.assertFalse(report['production_promoted'])
        self.assertEqual(self.reads, ['registry', 'original'])
        self.assertEqual(self.admit.call_count, 2)
        manifest = self.manifest()
        self.assertEqual(len(manifest['entries']), 78)
        self.api.verify_output(self.output, expected_manifest_sha256=report['manifest_sha256'])
        entry, = [r for r in manifest['entries'] if r.get('cipher')]
        raw = (self.output / entry['cipher']['file']).read_bytes()
        private = codec.decrypt_evidence(raw, self.private)
        self.assertEqual(private['race_id'], self.rid)
        self.assertEqual(private['forecast']['model_sha256'], self.api.MODEL_SHA)
        self.assertEqual(private['forecast']['prediction_at'], NOW.isoformat())
        self.assertNotEqual(private['forecast']['prediction_at'], self.original['baseline']['generated_at'])
        self.assertEqual(private['feature_row']['history_evidence']['official_support']['status'], 'MISSING_HISTORY')
        self.assertEqual(len(private['feature_row']['feature_names']), 462)
        self.assertEqual(private['forecast']['confidence']['label'], 'HOLD')
        self.assertFalse(private['forecast']['forecast_original_independently_read_back'])
        self.assertEqual(private['feature_row']['result_rows'], [])
        shared = private['shared_material']
        self.assertTrue('source_projection' not in shared, 'Raw source must remain in its original archive')
        self.assertEqual(shared['source_projection_sha256'], digest(
            self.api.official_inputs.source_projection(self.payload, self.original)))
        self.assertEqual(shared['source_original_reference'], self.original_meta)
        public = json.dumps(manifest) + json.dumps(report) + raw.decode()
        for hidden in (self.rid, 'baseline_arguments', 'normalized_input', 'trifectas',
                       'official_registration_id', 'rank_probabilities', 'PRIVATE KEY'):
            self.assertNotIn(hidden, public)
        self.assertEqual({p.name for p in self.output.iterdir()}, {'manifest.json', entry['cipher']['file']})

    def test_nine_riders_use_the_same_frozen_schema_and_compact_cipher_source_reference(self):
        self.payload, self.original = nine_rider_original()
        report = self.produce()
        self.assertEqual(report['new_encrypted_forecasts'], 1)
        entry, = [r for r in self.manifest()['entries'] if r['cipher']]
        private = codec.decrypt_evidence((self.output / entry['cipher']['file']).read_bytes(), self.private)
        self.assertEqual(len(private['forecast']['riders']), 9)
        self.assertEqual(len(private['forecast']['trifectas']), 9 * 8 * 7)
        self.assertTrue('raw_bytes' not in json.dumps(private), 'Raw source bytes must not be duplicated')

    def test_late_original_holds_before_admission_and_keeps_all_registered_races(self):
        self.current = datetime.fromisoformat(self.original_meta['cutoff_at']) - timedelta(minutes=14)
        report = self.produce()
        self.assertEqual(report['registered_races'], report['held_races'])
        self.assertEqual(report['new_encrypted_forecasts'], 0)
        self.assertEqual(report['hold_reasons']['PRE_PREDICTION_T15_MARGIN'], 1)
        self.admit.assert_not_called()
        self.assertEqual(self.reads, ['registry'])

    def test_actual_clock_after_save_can_invalidate_an_otherwise_good_forecast(self):
        save = self.api.capture_files._save_once
        def delayed(path, raw):
            save(path, raw)
            if str(path).endswith('.sealed.json'):
                self.current = datetime.fromisoformat(self.original_meta['cutoff_at']) - timedelta(seconds=899)
        with patch.object(self.api.capture_files, '_save_once', side_effect=delayed):
            report = self.produce()
        self.assertEqual(report['new_encrypted_forecasts'], 1)
        self.assertEqual(report['locally_saved_before_t15'], 0)
        self.assertEqual(report['held_races'], 78)
        self.assertEqual(report['hold_reasons']['POST_SAVE_T15_MARGIN'], 1)
        entry, = [r for r in self.manifest()['entries'] if r.get('cipher')]
        self.assertEqual(entry['state'], 'HOLD')
        self.api.verify_output(self.output, expected_manifest_sha256=report['manifest_sha256'])

    def test_model_computation_crossing_margin_holds_before_any_cipher_is_written(self):
        predict = self.api.forecast_row
        def delayed(*args, **kwargs):
            forecast = predict(*args, **kwargs)
            self.current = datetime.fromisoformat(self.original_meta['cutoff_at']) - timedelta(seconds=899)
            return forecast
        with patch.object(self.api, 'forecast_row', side_effect=delayed):
            report = self.produce()
        self.assertEqual(report['new_encrypted_forecasts'], 0)
        self.assertEqual(report['hold_reasons']['POST_GENERATION_T15_MARGIN'], 1)

    def test_failed_independent_admission_never_echoes_private_exception(self):
        self.admit.side_effect = ValueError('PRIVATE_SOURCE_AND_RIDER_SECRET')
        report = self.produce()
        self.assertEqual(report['held_races'], 78)
        self.assertEqual(report['hold_reasons']['SOURCE_ADMISSION_UNVERIFIED'], 1)
        self.assertNotIn('PRIVATE_SOURCE', json.dumps(report) + json.dumps(self.manifest()))

    def test_reverification_rejects_a_changed_fresh_original(self):
        changed = deepcopy(self.original)
        changed['snapshot']['riders'][0]['athlete_id'] = '999998'
        self.admit.side_effect = [(deepcopy(self.original), {}), (changed, {})]
        report = self.produce()
        self.assertEqual(report['new_encrypted_forecasts'], 0)
        self.assertEqual(report['hold_reasons']['INPUT_PROJECTION_UNVERIFIED'], 1)

    def test_create_once_never_overwrites_an_existing_run(self):
        self.produce()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaisesRegex(ValueError, 'OUTPUT_ALREADY_EXISTS'):
            self.produce()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_reader_rejects_extra_plaintext_fields_and_cipher_or_denominator_tampering(self):
        report = self.produce()
        original = (self.output / 'manifest.json').read_bytes()
        for change in ('extra', 'count', 'cipher', 'state', 'scope_bool'):
            manifest = json.loads(original)
            if change == 'extra': manifest['raw_prediction'] = {'private': True}
            elif change == 'count': manifest['summary']['registered_races'] -= 1
            elif change == 'state': manifest['summary']['state'] = 'PRIVATE_INJECTED_SOURCE_TEXT'
            elif change == 'scope_bool': manifest['summary']['result_reads'] = False
            else: next(r for r in manifest['entries'] if r.get('cipher'))['cipher']['sha256'] = '0' * 64
            (self.output / 'manifest.json').write_bytes(codec._canonical(manifest))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.api.verify_output(self.output)
        (self.output / 'manifest.json').write_bytes(original)
        self.api.verify_output(self.output, expected_manifest_sha256=report['manifest_sha256'])

    def test_frozen_model_and_context_pins_are_checked_without_refitting(self):
        trained, venues = self.api.load_frozen(ROOT)
        self.assertEqual(trained.to_dict()['model_sha256'], self.api.MODEL_SHA)
        self.assertEqual(len(trained.feature_names), 462)
        self.assertEqual(len(venues.records), 43)
        with patch.object(self.api, 'MODEL_FILE_SHA', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_OR_CONTEXT_UNVERIFIED'):
                self.api.load_frozen(ROOT)

    def test_changed_inference_source_cannot_silently_run_the_old_model(self):
        clone = self.root / 'pinned-code'
        for relative in (self.api.MODEL_FILE, self.api.VENUE_FILE, *(
                'research/chatgpt_dt_r1/' + name for name in self.api.INFERENCE_SOURCES)):
            path = clone / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, path)
        (clone / 'research/chatgpt_dt_r1/features.py').write_text('changed code\n')
        with self.assertRaisesRegex(ValueError, 'FROZEN_MODEL_OR_CONTEXT_UNVERIFIED'):
            self.api.load_frozen(clone)

    def test_current_day_is_required_even_when_existing_study_guard_allows_history(self):
        self.current = NOW + timedelta(days=1)
        with self.assertRaisesRegex(ValueError, 'ACTUAL_JST_DAY_REQUIRED'):
            self.produce()
        self.assertFalse(self.output.exists())

    def test_registry_cannot_claim_availability_after_the_actual_run_clock(self):
        self.current = NOW - timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, 'REGISTRY_FROM_FUTURE'):
            self.produce()
        self.assertFalse(self.output.exists())

    def test_existing_main_manual_job_guard_runs_before_reads_or_output(self):
        for change in ({'GITHUB_REF': 'refs/heads/research'}, {'GITHUB_EVENT_NAME': 'schedule'},
                       {'GITHUB_JOB': 'contracts'}, {'GITHUB_REPOSITORY': 'fork/RACE-AI'}):
            with self.subTest(change=change), patch.dict(os.environ, {**self.env, **change}, clear=True), \
                    patch.object(self.api, 'produce_day') as produce, \
                    patch.object(self.api.continuation.pipeline, 'check_owner_private_key') as key:
                with self.assertRaises(ValueError):
                    self.api.run_future_shadow(repo=ROOT, private_root=self.root, output=self.output,
                        owner_public_pem=ROOT / 'test-public.pem', owner_private_pem=self.private,
                        day=self.day, clock=lambda: NOW)
                produce.assert_not_called(); key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
