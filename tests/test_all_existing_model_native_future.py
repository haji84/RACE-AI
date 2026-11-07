"""Saved invented native inputs, real owner codecs, GitHub transport fixtures only."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.all_existing_model_learning import fit
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_all_model_inputs import build_native_inputs
from race_ai.boat_venue_learning import seal_candidate
from race_ai.existing_model_dispatch import GROUPS
from race_ai.four_sport_learning import LEARNED_ID
from scripts import all_existing_model_future_p0 as existing
from tests.test_boat_all_model_inputs import official_inputs

KEY = bytes(range(32))  # Public, deliberately fictional test-only owner key.
NOW = datetime(2030, 1, 15, 0, 10, tzinfo=timezone.utc)
RUN_HEAD = 'b'*40
SOURCE_HEAD = 'c'*40
FITTED_GROUPS = {'shared', 'shared_learned', 'boat_full', 'boat_observed', 'boat_ab', 'boat_clite'}


def zipped(root):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file(): archive.writestr(str(path.relative_to(root)), path.read_bytes())
    return output.getvalue()


def requests(*, day='2030-01-15', number=1, baseline=None, cutoff='10:00:00', capture='09:00:00'):
    program, before = official_inputs(tuple(range(1, 7)))
    def moved(value):
        text = json.dumps(value).replace('2030-01-15', day).replace('20300115', day.replace('-', ''))
        result = json.loads(text)
        result['race_id'] = day.replace('-', '')+'-17-'+f'{number:02d}'
        result['source_url'] = result['source_url'].replace('rno=1', 'rno='+str(number))
        result['closed_at'] = day+'T'+cutoff+'+09:00'
        result['captured_at'] = day+'T'+capture+'+09:00'
        return result
    native = build_native_inputs(moved(program), moved(before), as_of=day+'T09:00:01+09:00',
                                 fitted_model=baseline)['native_inputs']
    if baseline is None: native['shared_learned'] = deepcopy(native['shared'])
    return [dict(cell_key='boat/'+mid, native_payload=deepcopy(native[group]))
            for group, mids in GROUPS if group in FITTED_GROUPS and group in native for mid in mids]


def extra_requests(*, day='2030-01-15'):
    """Existing tactical and PDCA invented native fixtures, independently retained."""
    from tests.test_boat_tactical_scenarios import inputs
    from race_ai.boat_tactical_scenarios import MODEL_ID as TACTICAL
    from tests.test_existing_special_parameter_adapters import pdca_payload
    from tests.test_all_existing_model_matrix import _shift_dates
    source, histories, venue = inputs()
    source.update(race_id='20300115-17-01', captured_at='2030-01-15T09:00:00+09:00',
                  cutoff_at='2030-01-15T10:00:00+09:00')
    for row in source['boats']: row['racer_id'] = str(4000+row['lane'])
    for index, row in enumerate(histories, 1):
        row.update(racer_id=str(4000+index), as_of=source['captured_at'])
        row['source_receipt']['captured_at'] = '2030-01-15T08:59:00+09:00'
    venue.update(venue_code='17', captured_at='2030-01-15T08:59:00+09:00')
    tactical = dict(source=source, histories=histories, venue=venue, scope='OPERATOR_SUPPLIED_RESEARCH')
    tactical['source_evidence'] = [dict(source_ref='synthetic://tactical/'+letter, source_sha256=letter*64,
        source_rights_ref='fixture-native-source', captured_at='2030-01-15T08:59:00+09:00', published_at=None)
        for letter in 'abcd']
    pdca = _shift_dates(pdca_payload(), -292)
    facts = pdca['facts']; facts.update(race_id=source['race_id'], captured_at=source['captured_at'],
        cutoff_at=source['cutoff_at'], source_url='https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=17&hd=20300115')
    for row in facts['racers']: row['registration_no'] = str(4000+row['lane'])
    hashes = {facts['source_sha256'], facts['program_sha256']}
    for prior in pdca['rows']:
        report = json.loads(prior['report_json']); report['race_id'] = report['race_id'].replace('-18-', '-17-')
        prior['report_json'] = json.dumps(report, separators=(',', ':'))
        prior['report_sha256'] = sha256(prior['report_json'].encode()).hexdigest()
        hashes.update((report['source_sha256'], prior['report_sha256']))
    pdca.update(scope='OPERATOR_SUPPLIED_RESEARCH', source_evidence=[
        dict(source_ref='synthetic://pdca/'+value, source_sha256=value, source_rights_ref='fixture-native-source',
             captured_at='2030-01-15T08:59:00+09:00', published_at=None) for value in sorted(hashes)])
    if day != '2030-01-15':
        offset = (datetime.fromisoformat(day)-datetime(2030, 1, 15)).days
        tactical = _shift_dates(tactical, offset); pdca = _shift_dates(pdca, offset)
        facts = pdca['facts']; hashes = {facts['source_sha256'], facts['program_sha256']}
        for prior in pdca['rows']:
            report = json.loads(prior['report_json'])
            prior['report_sha256'] = sha256(prior['report_json'].encode()).hexdigest()
            hashes.update((report['source_sha256'], prior['report_sha256']))
        pdca['source_evidence'] = [dict(source_ref='synthetic://pdca/'+value, source_sha256=value,
            source_rights_ref='fixture-native-source', captured_at=day+'T08:59:00+09:00', published_at=None)
            for value in sorted(hashes)]
    return [dict(cell_key='boat/'+TACTICAL, native_payload=tactical),
            dict(cell_key='boat/boat-pdca-lane-shadow-v1', native_payload=pdca)]


@lru_cache(maxsize=2)
def training(cell_count=12):
    rows = []
    for number in range(1, 9):
        native_requests = requests(day=f'2030-01-{number:02d}')
        if cell_count == 14: native_requests += extra_requests(day=f'2030-01-{number:02d}')
        for request in native_requests:
            key = request['cell_key']; sport, mid = key.split('/', 1); payload = request['native_payload']
            info = registry.identity(mid, sport, payload)
            rows.append(dict(model_id=mid, sport=sport, race_id=info['race_id'], stage=info['stage'], scope=info['scope'],
                as_of=info['as_of'], cutoff_at=info['cutoff_at'], native_payload=payload, input_sha256=digest(payload),
                input_saved_at=(existing.stamp(info['as_of'])+timedelta(seconds=1)).isoformat(),
                result=dict(race_id=info['race_id'], sport=sport, status='settled', ordered_top3=[1, 2, 3] if number%2 else [6, 5, 4],
                    published_at=None, captured_at=f'2030-01-{number:02d}T10:01:00+09:00', source_ref='synthetic://result/'+str(number),
                    source_rights_ref='fixture-result', source_sha256=f'{number:064x}', identity_verified=True,
                    roster=info['roster'], payout_per_100_yen=1230, refund_numbers=[])))
    return fit(rows, now=NOW-timedelta(days=6), allow_source=lambda *_: True, allow_training=lambda *_: True)


class NativeFutureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = training()
        if len(cls.training['models']) != 12: raise AssertionError('fixture did not fit twelve native cells')

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.all_existing_model_native_future'),
                             'saved-native future producer is absent')
        return importlib.import_module('scripts.all_existing_model_native_future')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fictional-native-future-')
        self.addCleanup(temporary.cleanup); self.temp = Path(temporary.name)
        self.outputs = self.temp/'outputs'; self.outputs.touch(mode=0o600)
        self.root = self.temp/'future'; self.now = NOW
        env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_RUN_ID='42', GITHUB_SHA='a'*40, RUNNER_TEMP=str(self.temp), GITHUB_OUTPUT=str(self.outputs),
            RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        for item in (patch.dict(os.environ, env), patch.object(existing, 'utc_now', side_effect=lambda: self.now)):
            item.start(); self.addCleanup(item.stop)
        candidate = self.temp/'candidate'
        seal_candidate(dict(training=deepcopy(self.training), excluded=[], summary=dict(state='FICTIONAL_TWELVE_FITTED')), candidate)
        raw = zipped(candidate)
        self.candidate = self.metadata(200, 'all-existing-model-learning-7-1', raw, saved=NOW-timedelta(minutes=15), run=7)
        self.context = dict(training=deepcopy(self.training), receipt=deepcopy(self.candidate))
        baseline = self.training['models']['boat/'+LEARNED_ID]['native_training']
        self.requests = requests(baseline=baseline)
        source = self.temp/'source'
        make_private_pairs(self.context, self.requests, source, now=NOW-timedelta(minutes=9), allow_source=lambda *_: True)
        (source/'summary.json').unlink()
        source_raw = zipped(source)
        self.source = self.metadata(100, 'all-existing-model-pairs-8-9', source_raw, saved=NOW-timedelta(minutes=8), run=8, head=SOURCE_HEAD)
        self.manifest = dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V1', candidate_artifact_id=200,
            candidate_digest=self.candidate['digest'], source_input_artifact_id=100, source_input_digest=self.source['digest'],
            source_run_id=8, source_head_sha=SOURCE_HEAD)
        self.manifest_path = self.temp/'manifest.json'; self.manifest_path.write_bytes(existing.wire(self.manifest))
        actual_run = dict(id=42, head_sha=RUN_HEAD, repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
                          head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        self.mapping = {'actions/runs/42': existing.wire(actual_run),
            'actions/artifacts/200': existing.wire(self.candidate), 'actions/artifacts/200/zip': raw,
            'actions/artifacts/100': existing.wire(self.source), 'actions/artifacts/100/zip': source_raw}
        self.calls = []
        def github(route):
            self.calls.append(route); return self.mapping[route]
        patcher = patch.object(existing, 'gh', side_effect=github); patcher.start(); self.addCleanup(patcher.stop)

    def metadata(self, ident, name, raw, *, saved, run, head=RUN_HEAD):
        return dict(id=ident, name=name, expired=False, digest='sha256:'+sha256(raw).hexdigest(), size_in_bytes=len(raw),
            created_at=saved.isoformat(), expires_at=(NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=run, repository_id=1416489937, head_repository_id=1416489937, head_sha=head))

    def run_cli(self, *, readback=None):
        cli = self.module(); stream = io.StringIO()
        args = ['--manifest', str(self.manifest_path), '--out-dir', str(self.root)]
        if readback is not None: args.extend(['--readback-artifact', str(readback)])
        with redirect_stdout(stream): code = cli.main(args)
        self.assertEqual(code, 0)
        self.assertNotIn(base64.b64encode(KEY).decode(), stream.getvalue())
        return json.loads(stream.getvalue())

    def source_records(self):
        from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
        return _verified_private_pairs_artifact(self.mapping['actions/artifacts/100/zip'], self.source, now=self.now,
            expected_run_id=8, expected_head_sha=SOURCE_HEAD)[1]

    def test_old_candidate_and_source_runs_produce_exact_twelve_same_input_pairs_then_actual_readback(self):
        before = deepcopy(self.requests)
        result = self.run_cli()
        self.assertTrue(result['ready'], result)
        self.assertEqual(result['forecast_partition_count'], 12)
        self.assertEqual(result['captured_native_input_count'], 12)
        self.assertEqual(result['artifact_name'], 'all-existing-model-pairs-42-900004')
        self.assertEqual(result['expected_head_sha'], RUN_HEAD)
        self.assertFalse(result['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(len(list(self.root.iterdir())), 12)
        records = self.module().local_records(self.root)
        original = {request['cell_key']: request['native_payload'] for request in before}
        self.assertEqual({p['cell_key']:p['native_payload'] for p in records}, original)
        self.assertTrue(all(existing.stamp(p['generated_at']) == NOW for p in records))
        self.assertEqual(self.requests, before)
        self.assertGreater(result['source_age_seconds_min'], 500)
        raw = zipped(self.root)
        self.mapping['actions/artifacts/201/zip'] = raw
        self.mapping['actions/artifacts/201'] = existing.wire(self.metadata(201, result['artifact_name'], raw,
            saved=self.now+timedelta(seconds=3), run=42))
        self.now += timedelta(seconds=4)
        readback = self.run_cli(readback=201)
        self.assertTrue(readback['independent_pre_cutoff_receipt_verified'], readback)
        self.assertEqual(readback['source_audit_sha256'], result['source_audit_sha256'])
        self.assertEqual(readback['manifest_sha256'], digest(self.manifest))
        self.assertEqual(readback['source_input_artifact_id'], 100)
        self.assertTrue(all(route.startswith('actions/') for route in self.calls))
        self.assertIn('ready=true', self.outputs.read_text())

    def test_two_registered_unfitted_capsules_survive_fourteen_input_twelve_forecast_codec(self):
        extras = extra_requests()
        # Exercise the actual existing native predictors as well as retention.
        for request in extras:
            sport, mid = request['cell_key'].split('/', 1)
            registry.predict(mid, sport, request['native_payload'], at=self.now, allow_source=lambda *_: True)
        source = self.temp/'source14'
        make_private_pairs(self.context, self.requests+extras, source, now=NOW-timedelta(minutes=9), allow_source=lambda *_: True)
        (source/'summary.json').unlink(); raw = zipped(source)
        metadata = self.metadata(100, 'all-existing-model-pairs-8-9', raw, saved=NOW-timedelta(minutes=8), run=8, head=SOURCE_HEAD)
        self.mapping['actions/artifacts/100'] = existing.wire(metadata)
        self.mapping['actions/artifacts/100/zip'] = raw
        self.manifest['source_input_digest'] = metadata['digest']; self.manifest_path.write_bytes(existing.wire(self.manifest))
        result = self.run_cli(); self.assertTrue(result['ready'], result)
        self.assertEqual(result['captured_native_input_count'], 14)
        self.assertEqual(result['retained_unfitted_native_input_count'], 2)
        records = self.module().local_records(self.root)
        self.assertEqual(len(records), 12)
        capsules = [c for p in records for c in p.get('captured_native_inputs', [])]
        self.assertEqual({c['cell_key']:c['native_payload'] for c in capsules if c['cell_key'] in {e['cell_key'] for e in extras}},
                         {e['cell_key']:e['native_payload'] for e in extras})
        self.root = self.temp/'future-v2-twelve'
        self.manifest.update(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V2', candidate_cell_count=12)
        self.manifest_path.write_bytes(existing.wire(self.manifest))
        v2 = self.run_cli(); self.assertTrue(v2['ready'], v2)
        self.assertEqual((v2['forecast_partition_count'],v2['captured_native_input_count'],v2['retained_unfitted_native_input_count']), (12,14,2))
        self.assertEqual(v2['candidate_cell_count'], 12)

    def test_earliest_complete_case_selected_and_identical_capsules_deduplicate(self):
        cli = self.module(); records = self.source_records()
        records += deepcopy(records)
        later = requests(number=2, baseline=self.training['models']['boat/'+LEARNED_ID]['native_training'], cutoff='10:30:00')
        capsules = []
        for request in later:
            sport, mid = request['cell_key'].split('/', 1); native = request['native_payload']
            info = registry.identity(mid, sport, native)
            capsules.append(dict(cell_key=request['cell_key'], native_payload=native, input_sha256=digest(native),
                                 captured_as_of=info['as_of'], cutoff_at=info['cutoff_at']))
        records.insert(0, dict(captured_native_inputs=capsules))
        selected = cli.prepare_requests(self.context, records, now=self.now)
        self.assertEqual(selected['source_audit']['race_id'], 'boat:2030-01-15:boatrace-jcd-17:1')
        self.assertEqual(len(selected['requests']), 12)
        selected = cli.prepare_requests(self.context, records, now=NOW+timedelta(minutes=40))
        self.assertEqual(selected['source_audit']['race_id'], 'boat:2030-01-15:boatrace-jcd-17:2')
        self.assertEqual(selected['requests'][0]['native_payload'], sorted(later, key=lambda r:r['cell_key'])[0]['native_payload'])

    def test_ten_minute_margin_holds_without_retimestamping_or_output(self):
        self.now = NOW+timedelta(minutes=40)
        result = self.run_cli()
        self.assertFalse(result['ready']); self.assertIn('HOLD', result['state'])
        self.assertFalse(self.root.exists())
        self.assertEqual(result['source_requests'], 0)

    def test_manifest_pins_actual_digest_run_and_head_and_rejects_unknown_or_bool(self):
        for name, value in [('candidate_digest','sha256:'+'f'*64), ('source_input_digest','sha256:'+'f'*64),
                            ('source_run_id',9), ('source_head_sha','f'*40), ('candidate_artifact_id',True), ('unknown',1)]:
            with self.subTest(name=name):
                changed = deepcopy(self.manifest); changed[name] = value
                self.manifest_path.write_bytes(existing.wire(changed))
                result = self.run_cli()
                self.assertFalse(result['ready']); self.assertFalse(self.root.exists())

    def test_missing_cell_duplicate_conflict_pre_candidate_clock_and_any_training_overlap_reject(self):
        cli = self.module(); records = self.source_records()
        prepared = cli.prepare_requests(self.context, records, now=self.now)
        self.assertEqual(len(prepared['requests']), 12)
        self.assertEqual(records, self.source_records())
        for kind in ('missing', 'duplicate', 'clock', 'training', 'stage', 'future'):
            with self.subTest(kind=kind):
                changed = deepcopy(records); context = deepcopy(self.context)
                carrier = next(p for p in changed if p.get('captured_native_inputs'))
                if kind == 'missing': carrier['captured_native_inputs'].pop()
                elif kind == 'duplicate':
                    duplicate = deepcopy(carrier); duplicate['captured_native_inputs'][0]['input_sha256'] = 'f'*64
                    changed.append(duplicate)
                elif kind == 'clock': context['receipt']['created_at'] = (NOW-timedelta(minutes=1)).isoformat()
                elif kind == 'training': next(iter(context['training']['models'].values()))['validation_race_ids'].append('20300115-17-01')
                elif kind == 'stage':
                    cap = next(c for c in carrier['captured_native_inputs'] if registry.group(c['cell_key'].split('/',1)[1]) == 'shared')
                    cap['native_payload']['stage'] = 'P0'; cap['input_sha256'] = digest(cap['native_payload'])
                elif kind == 'future':
                    cap = carrier['captured_native_inputs'][0]; cap['captured_as_of'] = (NOW+timedelta(minutes=1)).isoformat()
                with self.assertRaises(ValueError): cli.prepare_requests(context, changed, now=self.now)

    def test_source_capture_age_is_separate_from_newer_native_conversion_asof(self):
        records = self.source_records(); carrier = next(p for p in records if p.get('captured_native_inputs'))
        capsule = next(c for c in carrier['captured_native_inputs'] if registry.group(c['cell_key'].split('/',1)[1]) == 'shared')
        feature = next(iter(capsule['native_payload']['snapshot']['participants'][0]['features'].values()))
        feature['captured_at'] = '2030-01-15T08:40:00+09:00'
        capsule['input_sha256'] = digest(capsule['native_payload'])
        audit = self.module().prepare_requests(self.context, records, now=self.now)['source_audit']
        self.assertEqual(audit['source_age_seconds_max'], 1800)
        self.assertLess(audit['native_input_age_seconds_max'], audit['source_age_seconds_max'])
        self.assertEqual(audit['source_age_basis'], 'ACTUAL_SELECTION_TIME_MINUS_RETAINED_SOURCE_CAPTURE')

    def upgrade_fourteen(self):
        """A distinct fitted14 candidate consumes the old12 candidate's14caps."""
        extras = extra_requests(); source = self.temp/'source-all-fourteen'
        make_private_pairs(self.context, self.requests+extras, source, now=NOW-timedelta(minutes=9), allow_source=lambda *_: True)
        (source/'summary.json').unlink(); source_raw = zipped(source)
        self.source = self.metadata(100, 'all-existing-model-pairs-8-9', source_raw, saved=NOW-timedelta(minutes=8), run=8, head=SOURCE_HEAD)
        self.mapping['actions/artifacts/100'] = existing.wire(self.source)
        self.mapping['actions/artifacts/100/zip'] = source_raw
        fitted = training(14); self.assertEqual(len(fitted['models']), 14)
        candidate = self.temp/'candidate-fourteen'
        seal_candidate(dict(training=deepcopy(fitted), excluded=[], summary=dict(state='FICTIONAL_FOURTEEN_FITTED')), candidate)
        raw = zipped(candidate)
        self.candidate = self.metadata(200, 'all-existing-model-learning-7-2', raw, saved=NOW-timedelta(minutes=15), run=7)
        self.mapping['actions/artifacts/200'] = existing.wire(self.candidate)
        self.mapping['actions/artifacts/200/zip'] = raw
        self.context = dict(training=deepcopy(fitted), receipt=deepcopy(self.candidate))
        self.manifest.update(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V2', candidate_cell_count=14,
                             candidate_digest=self.candidate['digest'], source_input_digest=self.source['digest'])
        self.manifest_path.write_bytes(existing.wire(self.manifest))
        return fitted, self.requests+extras

    def test_v2_fourteen_real_native_fits_fourteen_cipher_pairs_and_actual_readback(self):
        fitted, original = self.upgrade_fourteen()
        result = self.run_cli(); self.assertTrue(result['ready'], result)
        self.assertEqual((result['forecast_partition_count'],result['baseline_forecast_count'],result['learned_forecast_count']), (14,14,14))
        self.assertEqual((result['captured_native_input_count'],result['retained_unfitted_native_input_count']), (14,0))
        self.assertEqual(result['candidate_cell_count'], 14)
        self.assertEqual(len(list(self.root.iterdir())), 14)
        records = self.module().local_records(self.root, candidate_cell_count=14)
        self.assertEqual({p['cell_key']:p['native_payload'] for p in records}, {r['cell_key']:r['native_payload'] for r in original})
        self.assertTrue(all(p['training']['training_sha256'] == fitted['training_sha256'] for p in records))
        raw = zipped(self.root)
        self.mapping['actions/artifacts/201/zip'] = raw
        self.mapping['actions/artifacts/201'] = existing.wire(self.metadata(201, result['artifact_name'], raw,
            saved=self.now+timedelta(seconds=3), run=42))
        self.now += timedelta(seconds=4)
        verified = self.run_cli(readback=201)
        self.assertTrue(verified['independent_pre_cutoff_receipt_verified'], verified)
        self.assertEqual((verified['forecast_partition_count'], verified['candidate_cell_count']), (14,14))
        self.assertEqual(verified['manifest_sha256'], digest(self.manifest))
        self.assertEqual(verified['source_audit_sha256'], result['source_audit_sha256'])

    def test_v2_count_is_exact_and_v1_digest_and_twelve_defaults_are_unchanged(self):
        cli = self.module(); original = deepcopy(self.manifest)
        self.assertEqual(cli.validate_manifest(original), original)
        self.assertEqual(digest(cli.validate_manifest(original)), digest(original))
        v2 = dict(original, schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V2', candidate_cell_count=12)
        self.assertEqual(cli.validate_manifest(v2), v2)
        for count in (True, False, 12.0, '14', 0, 9, 13, 15):
            with self.subTest(count=count), self.assertRaises(ValueError):
                cli.validate_manifest(dict(v2, candidate_cell_count=count))
        for changed in (dict(original,candidate_cell_count=12),
                        {k:v for k,v in v2.items() if k!='candidate_cell_count'}):
            with self.assertRaises(ValueError): cli.validate_manifest(changed)
        # A V2count14 cannot silently admit the legacy12 fitted artifact.
        self.manifest = dict(v2, candidate_cell_count=14); self.manifest_path.write_bytes(existing.wire(self.manifest))
        rejected = self.run_cli(); self.assertFalse(rejected['ready']); self.assertFalse(self.root.exists())

    def test_v1_cannot_admit_fourteen_and_v2_fourteen_requires_both_added_cells(self):
        self.upgrade_fourteen()
        self.manifest.pop('candidate_cell_count'); self.manifest['schema']='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V1'
        self.manifest_path.write_bytes(existing.wire(self.manifest))
        rejected = self.run_cli(); self.assertFalse(rejected['ready']); self.assertFalse(self.root.exists())
        records = self.source_records(); carrier = next(p for p in records if p.get('captured_native_inputs'))
        for group in ('boat_tactical','boat_pdca'):
            changed = deepcopy(records); carrier = next(p for p in changed if p.get('captured_native_inputs'))
            carrier['captured_native_inputs'] = [c for c in carrier['captured_native_inputs'] if registry.group(c['cell_key'].split('/',1)[1]) != group]
            with self.subTest(group=group), self.assertRaises(ValueError):
                self.module().prepare_requests(self.context, changed, now=self.now, candidate_cell_count=14)

    def test_actual_upload_must_preserve_ten_minute_margin_not_only_generation(self):
        result = self.run_cli(); self.assertTrue(result['ready'], result)
        raw = zipped(self.root)
        saved = existing.stamp(result['cutoff_at'])-timedelta(minutes=10)+timedelta(seconds=1)
        self.mapping['actions/artifacts/201/zip'] = raw
        self.mapping['actions/artifacts/201'] = existing.wire(self.metadata(201, result['artifact_name'], raw, saved=saved, run=42))
        self.now = saved+timedelta(seconds=1)
        readback = self.run_cli(readback=201)
        self.assertFalse(readback['ready'], readback)
        self.assertFalse(readback['independent_pre_cutoff_receipt_verified'])

    def test_missing_owner_key_stops_before_any_github_request(self):
        self.calls.clear()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''):
            result = self.run_cli()
        self.assertFalse(result['ready']); self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_wrong_uploaded_digest_head_or_late_save_cannot_become_pre_cutoff_proof(self):
        result = self.run_cli(); self.assertTrue(result['ready'], result)
        raw = zipped(self.root)
        self.mapping['actions/artifacts/201/zip'] = raw
        self.now += timedelta(seconds=4)
        for kind in ('digest','head','cutoff'):
            metadata = self.metadata(201, result['artifact_name'], raw, saved=NOW+timedelta(seconds=3), run=42)
            if kind == 'digest': metadata['digest'] = 'sha256:'+'f'*64
            elif kind == 'head': metadata['workflow_run']['head_sha'] = 'f'*40
            else:
                self.now = NOW+timedelta(hours=2)
                metadata['created_at'] = '2030-01-15T10:00:00+09:00'
            self.mapping['actions/artifacts/201'] = existing.wire(metadata)
            with self.subTest(kind=kind): self.assertFalse(self.run_cli(readback=201)['ready'])


if __name__ == '__main__': unittest.main()
