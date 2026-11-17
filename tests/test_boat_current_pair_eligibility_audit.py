"""Invented native pairs and RESULT journals with real AES; no live reads."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT/'owner-source'
sys.path.insert(0, str(OWNER))
import race_ai, scripts, tests
for folder in ('pr64-reference', 'pr72-reference'):
    race_ai.__path__.append(str(OWNER/folder/'race_ai'))
scripts.__path__.append(str(ROOT/'scripts'))
tests.__path__.append(str(OWNER/'tests'))

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import base64
import importlib.util
import io
import json
import os
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.boat_venue_learning import read_candidate, seal_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_private_original_archive import seal_original_zip
from tests import test_all_existing_model_pairs as pair_fixture
from tests.test_all_existing_model_learning import observed_records
from tests.test_observed_weight_learning import NOW as TRAIN_NOW
from tests.test_frozen_day_cycle import observation
from scripts import boat_owner_active_snapshot_audit as active

SOURCE = active.M2_OWNER_SHA
RETENTION_SOURCE = 'bb49215034b779ea1493b35dd91e5c3ebfc04032'
KEY = bytes(range(32))
FORECAST_NOW = pair_fixture.FORECAST_NOW
NOW = datetime(2030, 4, 1, 9, 5, tzinfo=timezone.utc)
MODULE = ROOT/'scripts/boat_current_pair_eligibility_audit.py'
if MODULE.exists():
    spec = importlib.util.spec_from_file_location('main_current_pair_counts', MODULE)
    audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
else:
    audit = None


def packed(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return stream.getvalue()


class CurrentPairEligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai.all_existing_model_learning import fit
        records = observed_records(synthetic=False); mid = records[0]['model_id']
        cls.records = [row for row in records if row['model_id'] == mid]
        cls.training = fit(cls.records, now=TRAIN_NOW, allow_source=lambda *_:True, allow_training=lambda *_:True)
        cls.cell = next(iter(cls.training['models']))

    def setUp(self):
        self.assertIsNotNone(audit, 'current-day native pair counts audit is missing')
        setting = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        setting.start(); self.addCleanup(setting.stop)
        temporary = tempfile.TemporaryDirectory(prefix='authored-current-pair-counts-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.raws = {}; self.metas = {}; self.calls = []; self.extra = {}
        self.run = dict(id=99, head_sha=SOURCE, head_branch=active.BRANCH, event='workflow_dispatch',
            workflow_id=405276784, status='in_progress', conclusion=None, run_attempt=1,
            created_at='2030-04-01T07:59:00Z', updated_at='2030-04-01T09:03:00Z',
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
        self.job = dict(id=777, run_id=99, run_attempt=1, head_sha=SOURCE, status='in_progress',
            name=active.JOB, steps=[
                dict(name='Deadline-ordered five-model round 01', status='completed', conclusion='success',
                     started_at='2030-04-01T08:09:00Z', completed_at='2030-04-01T08:12:00Z'),
                dict(name='Deadline-ordered five-model round 02', status='completed', conclusion='success',
                     started_at='2030-04-01T08:12:01Z', completed_at='2030-04-01T08:40:00Z'),
                dict(name='Deadline-ordered five-model round 03', status='in_progress', conclusion=None,
                     started_at='2030-04-01T08:40:01Z', completed_at=None)])
        self.set_training(self.training)
        self.pairs(1)
        self.pending = self.result_observation(pending=True)
        self.settled = self.result_observation()
        self.results(1, [self.pending])
        self.results(2, [self.pending, self.settled])
        self.metas[999] = dict(self.metas[800], id=999, name='boat-venue-research-pdca-99-1',
                               size_in_bytes=295723352, digest='sha256:'+'d'*64)

    def set_training(self, training):
        self.training = training
        self.training_build = getattr(self, 'training_build', 0)+1
        folder = self.root/f'training-{self.training_build}'
        seal_candidate(dict(training=deepcopy(training), excluded=[], summary=dict(
            state=training['state'], fitted_model_count=len(training['models']),
            production_promoted=False, actual_purchases=False, plaintext_published=False)), folder)
        raw = packed({name: (folder/name).read_bytes() for name in ('learning.json', 'learning.enc', 'summary.json')})
        self.add(700, 'all-existing-model-learning-99-1', raw, '2030-04-01T08:00:02Z')
        self.context = context_from_encrypted_artifact(raw, 700, now=FORECAST_NOW,
            _fetch=lambda _:deepcopy(self.metas[700]))

    def add(self, ident, name, raw, saved):
        self.raws[ident] = raw
        self.metas[ident] = dict(id=ident, name=name, expired=False, size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(), created_at=saved, expires_at='2030-04-08T09:00:00Z',
            workflow_run=dict(id=99, head_sha=SOURCE, repository_id=1416489937, head_repository_id=1416489937))

    def pairs(self, number, *, input_only=False, both_models=False):
        seed = pair_fixture.AllExistingModelPrivatePairsTests('runTest'); seed.records = self.records
        generated = FORECAST_NOW if number == 1 else FORECAST_NOW+timedelta(minutes=3)
        native = seed.native(1)
        native['snapshot']['as_of'] = (generated-timedelta(seconds=1)).isoformat()
        for source in native['snapshot']['sources']:
            source['captured_at'] = native['snapshot']['as_of']
            if source['published_at'] is not None: source['published_at'] = native['snapshot']['as_of']
        from race_ai.boat_observed_pairwise_models import MODEL_IDS
        if both_models:
            requests = [dict(cell_key=cell, native_payload=deepcopy(native)) for cell in self.training['models']]
        else:
            missing = next(('boat/'+mid for mid in MODEL_IDS if 'boat/'+mid not in self.training['models']), None)
            requests = [dict(cell_key=missing if input_only else self.cell, native_payload=native)]
        for item in requests:
            item['native_payload']['scope'] = 'OPERATOR_SUPPLIED_RESEARCH'
            if 'scope' in item['native_payload'].get('snapshot', {}):
                item['native_payload']['snapshot']['scope'] = 'OPERATOR_SUPPLIED_RESEARCH'
        self.pair_build = getattr(self, 'pair_build', 0)+1
        folder = self.root/f'pairs-{number}-{input_only}-{self.pair_build}'
        make_private_pairs(self.context, requests, folder, now=generated, allow_source=lambda *_:True)
        self.pair_folder = folder
        children = [path for path in folder.iterdir() if path.is_dir()]
        self.payload = read_candidate(children[0])
        raw = packed({path.name+'/'+name:(path/name).read_bytes() for path in children
                      for name in ('learning.json', 'learning.enc', 'summary.json')})
        self.add(799+number, f'all-existing-model-pairs-99-{number}', raw,
                 (generated+timedelta(seconds=3)).isoformat())

    def result_observation(self, *, pending=False):
        pair = self.payload['pair']
        row = dict(race_id='20300401-24-01', cutoff_at=pair['cutoff_at'],
                   roster=pair['baseline_normalized']['roster'], top8=pair['baseline_normalized']['top'])
        result = observation(row)
        result.update(source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=24&hd=20300401',
            captured_at='2030-04-01T08:31:00Z', kind='raceresult', information_phase='official_result')
        if pending:
            result.update(status='PENDING', body_identity_verified=False, data=None,
                          captured_at='2030-04-01T08:10:30Z')
        return result

    def results(self, number, journal, *, mutate_report=None):
        updated = '2030-04-01T08:11:00Z' if number == 1 else '2030-04-01T08:37:00Z'
        report = dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1', day_jst='2030-04-01',
            run_id='99', code_sha=SOURCE, round_no=number, updated_at=updated, result_observation_versions=len(journal),
            actual_purchases=False, private='PRIVATE_RESULT_SENTINEL')
        if mutate_report is not None: mutate_report(report)
        report['report_sha256'] = digest(report)
        plain = packed({'official-result-observations.json':json.dumps(journal), 'status.json':json.dumps(report)})
        raw = packed({'private-original.enc':seal_original_zip(plain, run_id=99, head_sha=SOURCE, kind='RESULT', key=KEY)})
        name = 'race-existing-cycle-99' if number == 1 else f'race-existing-cycle-99-cycle-{number:02}'
        self.add(899+number, name, raw, (datetime.fromisoformat(updated.replace('Z','+00:00'))+timedelta(seconds=1)).isoformat())

    def get(self, route):
        self.calls.append(route)
        if route in self.extra: return self.extra[route]
        if route == 'actions/runs/99': return json.dumps(self.run).encode()
        if route == 'actions/runs/99/jobs?per_page=100': return json.dumps(dict(total_count=1, jobs=[self.job])).encode()
        if route == 'actions/runs/99/artifacts?per_page=100':
            return json.dumps(dict(total_count=len(self.metas), artifacts=list(self.metas.values()))).encode()
        if route.startswith('actions/artifacts/'):
            ident = int(route.split('/')[2])
            if route.endswith('/zip'):
                if ident == 999: raise AssertionError('large PDCA must not be downloaded')
                return self.raws[ident]
            return json.dumps(self.metas[ident]).encode()
        raise AssertionError('unexpected external route')

    def audit(self, **options):
        return audit.audit_current_pairs(get=self.get, run_id=99, now=NOW, expected_owner_sha=SOURCE, **options)

    def rewrite_pair(self, mutate):
        payload = deepcopy(self.payload); mutate(payload)
        folder = self.root/'rewritten-pair'; seal_candidate(payload, folder)
        partition = next(path.name for path in self.pair_folder.iterdir() if path.is_dir())
        raw = packed({partition+'/'+name:(folder/name).read_bytes() for name in ('learning.json', 'learning.enc', 'summary.json')})
        self.add(800, 'all-existing-model-pairs-99-1', raw, self.metas[800]['created_at'])

    def test_real_crypto_counts_are_flat_private_and_still_unqualified(self):
        with patch('race_ai.all_existing_model_pdca._score', side_effect=AssertionError('counts must not score')):
            result = self.audit()
        self.assertTrue(result['current_pair_authenticated'])
        self.assertEqual(result['current_pair_forecast_record_count'], 1)
        self.assertEqual(result['current_pair_input_only_record_count'], 0)
        self.assertEqual(result['current_pair_distinct_race_count'], 1)
        self.assertEqual(result['current_pair_result_unique_revision_count'], 2)
        self.assertEqual(result['current_pair_result_duplicate_revision_count'], 1)
        self.assertEqual(result['current_pair_producer_journal_settled_join_count'], 1)
        self.assertEqual(result['current_pair_qualifying_g8_count'], 0)
        self.assertIsNone(result['current_pair_qualifying_g8_denominator'])
        for field in ('official_raw_verified', 'official_cutoff_verified', 'minimum_cohort'):
            self.assertIsNone(result['current_pair_'+field])
        for field in ('accuracy_improvement_proven', 'promotion_allowed', 'full_day_coverage'):
            self.assertIs(result['current_pair_'+field], False)
        self.assertTrue(all(type(value) in (str, int, bool, type(None)) for value in result.values()))
        public = json.dumps(result)
        for private in ('PRIVATE_RESULT_SENTINEL', 'https://', '20300401-24-01', 'roster', 'ordered_top3', 'weights', 'payout', 'roi'):
            self.assertNotIn(private, public)

    def test_input_only_never_generates_forecasts_or_opens_result_bodies(self):
        self.pairs(1, input_only=True)
        original = self.get
        def get(route):
            if route in ('actions/artifacts/900/zip', 'actions/artifacts/901/zip'):
                raise AssertionError('input-only cannot need result decryption')
            return original(route)
        with patch('race_ai.all_existing_model_registry.predict', side_effect=AssertionError('retroforecast')):
            result = audit.audit_current_pairs(get=get, run_id=99, now=NOW, expected_owner_sha=SOURCE)
        self.assertEqual(result['current_pair_forecast_record_count'], 0)
        self.assertEqual(result['current_pair_input_only_record_count'], 1)
        self.assertEqual(result['current_pair_result_archive_count'], 0)
        self.assertEqual(result['current_pair_distinct_race_count'], 0)

    def test_repeat_pair_records_do_not_inflate_first_versions_or_race_counts(self):
        self.pairs(2)
        result = self.audit()
        self.assertEqual(result['current_pair_forecast_record_count'], 2)
        self.assertEqual(result['current_pair_first_forecast_record_count'], 1)
        self.assertEqual(result['current_pair_repeat_forecast_record_count'], 1)
        self.assertEqual(result['current_pair_distinct_race_count'], 1)
        self.assertEqual(result['current_pair_training_archive_count'], 1)

    def test_latest_pending_correction_does_not_fall_back_to_an_older_settlement(self):
        later = deepcopy(self.pending); later['captured_at'] = '2030-04-01T08:36:00Z'
        self.results(2, [self.pending, self.settled, later])
        result = self.audit()
        self.assertEqual(result['current_pair_producer_journal_settled_join_count'], 0)
        self.assertEqual(result['current_pair_producer_journal_pending_join_count'], 1)
        self.assertEqual(result['current_pair_result_unique_revision_count'], 3)

    def test_selected_bytes_metadata_keys_and_source_mutations_fail_closed(self):
        cases = ('cipher', 'metadata', 'source', 'late', 'expired', 'wrong_key', 'missing_training', 'wrong_job')
        for case in cases:
            before = deepcopy((self.raws, self.metas, self.job))
            if case == 'cipher': self.raws[800] += b'changed'
            elif case == 'metadata': self.extra['actions/artifacts/800'] = json.dumps(dict(self.metas[800], digest='sha256:'+'f'*64)).encode()
            elif case == 'source': self.metas[800]['workflow_run']['head_sha'] = 'f'*40
            elif case == 'late': self.metas[800]['created_at'] = self.payload['pair']['cutoff_at']
            elif case == 'expired': self.metas[800]['expired'] = True
            elif case == 'missing_training': del self.metas[700]
            elif case == 'wrong_job': self.job['head_sha'] = 'f'*40
            with self.subTest(case=case), patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(b'x'*32 if case=='wrong_key' else KEY).decode()), self.assertRaisesRegex(ValueError, '^CURRENT_PAIR_AUDIT_REJECTED$'):
                self.audit()
            self.raws, self.metas, self.job = before; self.extra = {}

    def test_embedded_training_receipt_is_not_an_external_metadata_receipt(self):
        self.rewrite_pair(lambda payload:payload['training_receipt'].update(digest='sha256:'+'f'*64))
        with self.assertRaisesRegex(ValueError, 'CURRENT_PAIR_AUDIT_'):
            self.audit()

    def test_duplicate_inventory_and_conflicting_result_capture_are_fatal(self):
        listing = list(self.metas.values())
        self.extra['actions/runs/99/artifacts?per_page=100'] = json.dumps(dict(total_count=len(listing)+1, artifacts=listing+[listing[0]])).encode()
        with self.assertRaises(ValueError): self.audit()
        self.extra = {}
        conflict = deepcopy(self.settled); conflict['source_sha256'] = 'c'*64
        self.results(2, [self.pending, self.settled, conflict])
        with self.assertRaises(ValueError): self.audit()

    def test_later_uncompleted_pairs_are_excluded_without_reading_their_bodies(self):
        self.metas[802] = dict(self.metas[800], id=802, name='all-existing-model-pairs-99-3')
        result = self.audit()
        self.assertEqual(result['current_pair_excluded_archive_count'], 1)
        self.assertNotIn('actions/artifacts/802/zip', self.calls)

    def test_oversized_selected_archives_are_rejected_before_zip_download(self):
        for ident in (800, 700):
            original = self.metas[ident]['size_in_bytes']
            self.metas[ident]['size_in_bytes'] = 295723352
            self.calls.clear()
            with self.subTest(ident=ident), self.assertRaises(ValueError): self.audit()
            self.assertNotIn(f'actions/artifacts/{ident}/zip', self.calls)
            self.metas[ident]['size_in_bytes'] = original

    def test_absent_or_only_uncompleted_pair_archives_keep_counts_unknown(self):
        del self.metas[800]
        for later in (False, True):
            if later:
                self.metas[802] = dict(self.metas[700], id=802, name='all-existing-model-pairs-99-3')
            self.calls.clear(); result = self.audit()
            self.assertFalse(result['current_pair_authenticated'])
            self.assertEqual(result['current_pair_archive_count'], 0)
            self.assertIsNone(result['current_pair_forecast_record_count'])
            self.assertIsNone(result['current_pair_input_only_record_count'])
            self.assertIsNone(result['current_pair_result_archive_count'])
            self.assertEqual(result['current_pair_qualifying_g8_count'], 0)
            self.assertFalse(any(route.endswith('/zip') for route in self.calls))

    def test_more_model_rows_do_not_inflate_the_number_of_races(self):
        from race_ai.all_existing_model_learning import fit
        self.set_training(fit(observed_records(synthetic=False), now=TRAIN_NOW,
            allow_source=lambda *_:True, allow_training=lambda *_:True))
        self.pairs(1, both_models=True)
        result = self.audit()
        self.assertEqual(result['current_pair_forecast_record_count'], 2)
        self.assertEqual(result['current_pair_first_forecast_record_count'], 2)
        self.assertEqual(result['current_pair_distinct_race_count'], 1)
        self.assertEqual(result['current_pair_producer_journal_joined_race_count'], 1)

    def test_resealed_complete_training_body_must_equal_the_actual_training_artifact(self):
        from race_ai.observed_weight_learning import seal
        def mutate(payload):
            training = payload['training']; training['unbound_extra_field'] = 'DIFFERENT_FROZEN_BODY'
            seal(training, 'training_sha256')
            payload['pair']['training_sha256'] = training['training_sha256']
            seal(payload['pair'], 'pair_sha256')
            payload['summary']['training_sha256'] = training['training_sha256']
        self.rewrite_pair(mutate)
        from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
        # This is internally consistent ciphertext, so a claimed training SHA
        # alone would accept it. The separately fetched full body must differ.
        _verified_private_pairs_artifact(self.raws[800], self.metas[800], now=NOW,
                                        expected_run_id=99, expected_head_sha=SOURCE)
        with self.assertRaises(ValueError): self.audit()

    def test_result_round_day_old_report_and_missing_selected_result_are_fatal(self):
        before = deepcopy((self.raws, self.metas))
        for field, value in (('round_no', True), ('day_jst', '2030-04-02'),
                             ('updated_at', '2030-04-01T08:00:00Z')):
            self.results(2, [], mutate_report=lambda report:report.update({field:value}))
            with self.subTest(field=field), self.assertRaises(ValueError): self.audit()
            self.raws, self.metas = deepcopy(before)
        del self.metas[901]
        with self.assertRaises(ValueError): self.audit()

    def test_api_bool_ids_and_unapproved_sources_are_not_trusted_flags(self):
        for options in (dict(run_id=True), dict(expected_owner_sha=True), dict(expected_owner_sha='f'*40)):
            arguments = dict(get=self.get, run_id=99, now=NOW, expected_owner_sha=SOURCE); arguments.update(options)
            with self.subTest(options=options), self.assertRaises(ValueError): audit.audit_current_pairs(**arguments)


class RetentionCurrentPairEligibilityTests(CurrentPairEligibilityTests):
    """The same authored crypto/refusal contracts at the new literal source."""
    def setUp(self):
        source=patch.object(sys.modules[__name__],'SOURCE',RETENTION_SOURCE)
        source.start();self.addCleanup(source.stop)
        super().setUp()


class CurrentPairWorkflowTests(unittest.TestCase):
    def test_failure_keeps_core_proof_active_path_and_emits_only_static_unknown_counts(self):
        text = (ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertTrue('# CURRENT_PAIR_COUNTS_BEGIN' in text, 'current pair failure isolation is missing')
        block = text.split('# CURRENT_PAIR_COUNTS_BEGIN\n', 1)[1].split('# CURRENT_PAIR_COUNTS_END', 1)[0]
        core = dict(status='ACTIVE_COMPLETED_RECEIPTS_AES_VERIFIED_PARTIAL_SCOPE', raw_aes_archives_verified=38,
                    full_day_coverage=False, successor_dispatch_allowed=False)
        def rejected(*args): raise ValueError('PRIVATE_EXCEPTION_SENTINEL source token')
        for loader in (rejected, lambda *args:SimpleNamespace(audit_current_pairs=lambda **kwargs:rejected())):
            namespace = dict(report=deepcopy(core), reads=object(), ident=99, snapshot_clock=NOW, owner=SOURCE,
                             active_snapshot=True, from_exact_file=loader)
            exec(textwrap.dedent(block), namespace)
            result = namespace['report']
            self.assertTrue(namespace['active_snapshot'])
            self.assertTrue(all(result[key] == value for key, value in core.items()))
            self.assertFalse(result['current_pair_authenticated'])
            self.assertIsNone(result['current_pair_forecast_record_count'])
            self.assertIsNone(result['current_pair_input_only_record_count'])
            self.assertEqual(result['current_pair_qualifying_g8_count'], 0)
            self.assertNotIn('PRIVATE_EXCEPTION_SENTINEL', json.dumps(result))
        self.assertIn("output.write('active_snapshot='+('true' if active_snapshot else 'false')", text)



ATOMIC_SOURCE='a74f1e940e7fc0852e63938f8138bdb58bd93163'


class AtomicCurrentPairEligibilityTests(CurrentPairEligibilityTests):
    """Run the unchanged genuine AES/refusal cases at the protected atomic source."""
    def setUp(self):
        source=patch.object(sys.modules[__name__],'SOURCE',ATOMIC_SOURCE)
        source.start();self.addCleanup(source.stop)
        super().setUp()


if __name__ == '__main__':
    unittest.main()
