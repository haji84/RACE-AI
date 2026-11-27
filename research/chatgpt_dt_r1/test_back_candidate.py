"""Synthetic candidate integrity, future-input and encrypted-retention contracts."""
import copy
import importlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from research.chatgpt_dt_r1.back_phase_study import prepare, scenario_row, VERSION
from research.chatgpt_dt_r1.model import RankModel, digest
from research.chatgpt_dt_r1.pipeline import DEFAULT_SPLITS, write_private_json
from research.chatgpt_dt_r1.test_agari import records


class BackCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from race_ai import keirin_official_run_history as codec
        cls.codec=codec
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.secret=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        cls.owner_pin=sha256(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('research.chatgpt_dt_r1.back_candidate'),
                             'A strict persisted B-candidate interface is required')
        self.api=importlib.import_module('research.chatgpt_dt_r1.back_candidate')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        pin=patch.object(self.codec.storage,'PINNED_OWNER_SPKI_SHA256',self.owner_pin)
        pin.start();self.addCleanup(pin.stop)
        self.history,self.record=records()
        self.history.update(available_at='2026-07-02T00:00:00Z',result_at='2026-07-02T00:00:00Z')
        self.record.update(race_id='PRIVATE_TARGET',day='2026-12-01',cohort='prospective',
            available_at='2026-12-01T07:00:00Z',cutoff_at='2026-12-01T09:00:00Z',
            source_attestation_sha256='a'*64,pre_cutoff_authenticated=True)
        self.at='2026-12-01T08:00:00Z'
        row=prepare([self.history,self.record])[-1]
        self.leader={'schema':VERSION,'feature_names':list(row['feature_names']),
            'mean':[0.]*len(row['feature_names']),'scale':[1.]*len(row['feature_names']),
            'weights':[0.]*len(row['feature_names']),'before':'2026-07-01','training_n':30,
            'converged':True,'training_fingerprint':'b'*64}
        meta={'fit_before_day':'2026-07-01','training_first_day':'2026-06-01',
            'training_last_day':'2026-06-30','training_races':30,'feature_digest_required':True,
            'created_at':'2026-11-27T12:00:00Z','cohort':'retrospective_archived_inputs_no_pre_cutoff_attestation'}
        direct=RankModel.zero(row['feature_names']);direct.fit_meta=dict(meta)
        conditional=RankModel.zero(scenario_row(row,1)['feature_names']);conditional.fit_meta=dict(meta)
        self.candidate=self.api.freeze_candidate(self.leader,conditional,direct,
            source_dataset_sha256='c'*64,splits=DEFAULT_SPLITS,created_at='2026-11-27T13:00:00Z')
        self.study=self.root/'study';self.study.mkdir(mode=0o700)
        self.path=self.study/'back_candidate.json'
        write_private_json(self.path,self.candidate)
        self.pin=sha256(self.path.read_bytes()).hexdigest()
        self.report={'artifact_sha256':self.candidate['artifact_sha256'],'production_promoted':False,
                     'private_marker':'PRIVATE_SOURCE_NEVER_PUBLIC'}
        write_private_json(self.study/'aggregate.json',self.report)

    def rewrite(self, candidate):
        candidate['artifact_sha256']=digest({k:v for k,v in candidate.items() if k!='artifact_sha256'})
        self.path.write_text(json.dumps(candidate,allow_nan=False))
        return sha256(self.path.read_bytes()).hexdigest()

    def test_external_byte_pin_and_internal_component_hashes_are_both_enforced(self):
        loaded=self.api.load_candidate(self.path,expected_sha256=self.pin)
        self.assertEqual(loaded,self.candidate)
        changed=copy.deepcopy(self.candidate);changed['leader']['weights'][0]=1.
        new_pin=self.rewrite(changed)
        with self.assertRaisesRegex(ValueError,'SHA_MISMATCH'):
            self.api.load_candidate(self.path,expected_sha256=self.pin)
        self.assertEqual(self.api.load_candidate(self.path,expected_sha256=new_pin)['leader']['weights'][0],1.)
        changed['conditional']['weights'][0][0]=2.
        with self.assertRaisesRegex(ValueError,'ARTIFACT_HASH_MISMATCH'):
            self.api.load_candidate(self.path,expected_sha256=self.rewrite(changed))

    def test_rehashed_invalid_shapes_schema_source_code_and_dates_are_rejected(self):
        changes=[
            (lambda x:x['leader'].update(scale=[1.]),'LEADER_ARRAY'),
            (lambda x:x['leader']['scale'].__setitem__(0,'1'),'LEADER_ARRAY'),
            (lambda x:x['leader']['weights'].__setitem__(0,True),'LEADER_ARRAY'),
            (lambda x:x['leader'].update(before='2026-08-01'),'TRAINING_BINDING'),
            (lambda x:x.update(production_promoted=True),'RESEARCH_ONLY'),
            (lambda x:x.update(created_at='2026-11-26T00:00:00Z'),'FREEZE_BEFORE_FIT'),
            (lambda x:x['source_code_sha256'].update({'back_phase_study.py':'0'*64}),'SOURCE_CODE'),
            (lambda x:x.update(unregistered_private_field='not allowed'),'FIELDS'),
        ]
        for change,reason in changes:
            with self.subTest(reason=reason):
                changed=copy.deepcopy(self.candidate);change(changed)
                with self.assertRaisesRegex(ValueError,reason):
                    self.api.load_candidate(self.path,expected_sha256=self.rewrite(changed))

    def test_rank_arrays_reject_numeric_strings_even_when_hashes_are_recomputed(self):
        candidate=copy.deepcopy(self.candidate);raw=candidate['conditional']
        raw['weights'][0][0]='1.0'
        raw['model_sha256']=digest({k:v for k,v in raw.items() if k!='model_sha256'})
        with self.assertRaisesRegex(ValueError,'RANK_ARRAY'):
            self.api.load_candidate(self.path,expected_sha256=self.rewrite(candidate))

    def test_nonuniform_full_rank_probabilities_agree_with_joint_order_mass(self):
        candidate=copy.deepcopy(self.candidate)
        conditional=candidate['conditional']
        index=conditional['feature_names'].index('scenario_B_self')
        conditional['weights'][0][index]=1.7
        conditional['weights'][1][conditional['feature_names'].index('scenario_B_same_line')]=.6
        conditional['model_sha256']=digest({k:v for k,v in conditional.items() if k!='model_sha256'})
        candidate['leader']['weights'][candidate['leader']['feature_names'].index('points_relative')]=2.
        self.pin=self.rewrite(candidate)
        output=self.predict(full=True)
        self.assertGreater(max(t['probability'] for t in output['trifectas']),1/6)
        for rider in output['riders']:
            for rank in range(3):
                joint=sum(t['probability'] for t in output['trifectas'] if t['cars'][rank]==rider['car'])
                self.assertAlmostEqual(rider['rank_probabilities'][rank],joint)

    def test_new_study_freezes_loadable_candidate_and_does_not_score_viewed_test_by_default(self):
        from research.chatgpt_dt_r1 import back_phase_study as study
        synthetic=[]
        for i in range(30):
            row=copy.deepcopy(self.record)
            row.update(race_id='fit-'+str(i),day='2026-06-15',cohort='retrospective',
                result_status='COMPLETE',top3=[1,2,3],finish=[1,2,3],
                result_rows=[{'car':1,'rank':1,'sb_mark':'B'},{'car':2,'rank':2},{'car':3,'rank':3}])
            synthetic.append(row)
        tune=copy.deepcopy(synthetic[0]);tune.update(race_id='tune',day='2026-07-15');synthetic.append(tune)
        # Keep a real, valid test row: an empty period could conceal scoring.
        final=copy.deepcopy(tune);final.update(race_id='viewed-test',day='2026-10-15')
        synthetic.append(final)
        directory=self.root/'next-study'
        real_score=study.score
        def guard(rows,*models):
            self.assertTrue(all(r['day']<'2026-10-01' for r in rows),'Viewed test labels must not reach the scorer by default')
            return real_score(rows,*models)
        # Replace archive I/O; wrap the real scorer to detect a forbidden call.
        with patch.object(study,'load_archives',return_value=(synthetic,{'dataset_sha256':'c'*64,'unique_races':32})):
            with patch.object(study,'score',side_effect=guard),redirect_stdout(io.StringIO()):
                report=study.study([],directory)
        self.assertFalse(report['test_evaluated'])
        self.assertIsNone(report.get('test'))
        saved=directory/'back_candidate.json';pin=sha256(saved.read_bytes()).hexdigest()
        self.assertEqual(self.api.load_candidate(saved,expected_sha256=pin)['artifact_sha256'],report['artifact_sha256'])

    def predict(self, **kwargs):
        return self.api.forecast_candidate(self.path,expected_sha256=self.pin,
            record=kwargs.pop('record',self.record),history=kwargs.pop('history',[self.history]),
            prediction_at=kwargs.pop('prediction_at',self.at),**kwargs)

    def test_prospective_prediction_uses_all_scenarios_and_consistent_full_marginals(self):
        forecast=self.predict(full=True)
        self.assertEqual(forecast['status'],'READY')
        self.assertEqual(forecast['model_sha256'],self.candidate['artifact_sha256'])
        self.assertFalse(forecast['production_promoted'])
        self.assertFalse(forecast['independent_source_attestation'])
        self.assertEqual(forecast['confidence']['label'],'HOLD')
        self.assertAlmostEqual(forecast['trifectas'][0]['probability'],1/6)
        self.assertAlmostEqual(sum(forecast['back_leader'].values()),1.)
        ranks=np.asarray([r['rank_probabilities'] for r in forecast['riders']])
        np.testing.assert_allclose(ranks.sum(0),[1.,1.,1.])
        np.testing.assert_allclose(ranks.sum(1),[1.,1.,1.])
        np.testing.assert_allclose(ranks[:,0],[1/3]*3)
        changed=copy.deepcopy(self.record)
        changed.update(top3=[3,2,1],finish=[3,2,1],result_status='COMPLETE',result_rows=[
            {'car':3,'rank':1,'sb_mark':'B'},{'car':2,'rank':2},{'car':1,'rank':3}])
        other=self.predict(record=changed,full=True)
        self.assertEqual(forecast,other)

    def test_prospective_clock_source_history_and_model_age_guards(self):
        with self.assertRaisesRegex(ValueError,'15_MINUTES'):
            self.predict(prediction_at='2026-12-01T08:46:00Z')
        missing=copy.deepcopy(self.record);missing.pop('source_attestation_sha256')
        with self.assertRaisesRegex(ValueError,'AUTHENTICATED_SOURCE'):
            self.predict(record=missing)
        history=copy.deepcopy(self.history);history['result_at']='2026-12-01T08:01:00Z'
        with self.assertRaisesRegex(ValueError,'HISTORY_RESULT_AFTER'):
            self.predict(history=[history])
        same_day=copy.deepcopy(self.history);same_day['day']=self.record['day']
        with self.assertRaisesRegex(ValueError,'HISTORY_MUST_PRECEDE'):
            self.predict(history=[same_day])
        future=copy.deepcopy(self.candidate);future['created_at']='2026-12-02T00:00:00Z'
        self.pin=self.rewrite(future)
        with self.assertRaisesRegex(ValueError,'MODEL_FROM_FUTURE'):
            self.predict()

    def test_retrospective_clock_cannot_be_relabelled_as_prospective(self):
        retrospective=copy.deepcopy(self.record);retrospective['cohort']='retrospective'
        with self.assertRaisesRegex(ValueError,'RETROSPECTIVE_CLOCK'):
            self.predict(record=retrospective)
        output=self.predict(record=retrospective,prediction_at=None)
        self.assertEqual(output['cohort'],'retrospective')
        self.assertIsNone(output['prediction_at'])

    def test_unsupported_roster_returns_private_hold_without_a_distribution(self):
        target=copy.deepcopy(self.record);target['field_supported']=False
        output=self.predict(record=target)
        self.assertEqual(output['status'],'HOLD')
        self.assertEqual(output['reason'],'HOLD_UNSUPPORTED_ROSTER')
        self.assertNotIn('trifectas',output)

    def export(self, name='bundle'):
        dest=self.root/name
        receipt=self.api.export_candidate(self.study,dest,self.public,
            expected_candidate_sha256=self.pin,now='2026-11-27T14:00:00Z')
        return dest,receipt

    def test_encrypted_roundtrip_preserves_exact_private_files_and_predictions(self):
        dest,receipt=self.export()
        self.assertEqual({p.name for p in dest.iterdir()},{'manifest.json','candidate.sealed.json'})
        for path in dest.iterdir():self.assertNotIn(b'PRIVATE_',path.read_bytes())
        restored=self.root/'restored'
        self.api.restore_candidate(dest,restored,expected_manifest_sha256=receipt['manifest_sha256'],
                                   owner_private_pem=self.secret)
        for path in self.study.iterdir():
            self.assertEqual(path.read_bytes(),(restored/path.name).read_bytes())
            self.assertEqual((restored/path.name).stat().st_mode & 0o777,0o600)
        self.assertEqual(self.predict(),self.api.forecast_candidate(restored/'back_candidate.json',
            expected_sha256=self.pin,record=self.record,history=[self.history],prediction_at=self.at))
        self.assertFalse(receipt['owner_decryption_verified'])

    def test_encrypted_external_pin_cipher_tamper_and_unexpected_files_stop_restore(self):
        dest,receipt=self.export();restored=self.root/'restored'
        with self.assertRaisesRegex(ValueError,'MANIFEST_SHA'):
            self.api.restore_candidate(dest,restored,expected_manifest_sha256='0'*64,owner_private_pem=self.secret)
        sealed=dest/'candidate.sealed.json';original=sealed.read_bytes();sealed.write_bytes(original+b'x')
        with self.assertRaisesRegex(ValueError,'CIPHER_SHA'):
            self.api.restore_candidate(dest,restored,expected_manifest_sha256=receipt['manifest_sha256'],owner_private_pem=self.secret)
        self.assertFalse(restored.exists());sealed.write_bytes(original)
        (dest/'unregistered.json').write_text('PRIVATE_EXTRA')
        with self.assertRaisesRegex(ValueError,'FILE_SET'):
            self.api.verify_candidate_bundle(dest,expected_manifest_sha256=receipt['manifest_sha256'])

    def test_unexpected_private_file_and_existing_destination_are_never_overwritten(self):
        raw=self.study/'source.db';raw.write_bytes(b'PRIVATE_SOURCE')
        with self.assertRaisesRegex(ValueError,'FILE_SET'):
            self.export()
        self.assertFalse((self.root/'bundle').exists());raw.unlink()
        dest,receipt=self.export();restored=self.root/'restored';restored.mkdir()
        sentinel=restored/'keep';sentinel.write_text('original')
        with self.assertRaisesRegex(ValueError,'NO_REPLACE'):
            self.api.restore_candidate(dest,restored,expected_manifest_sha256=receipt['manifest_sha256'],owner_private_pem=self.secret)
        self.assertEqual(sentinel.read_text(),'original')

    def test_wrong_owner_key_never_creates_plaintext_restore_destination(self):
        dest,receipt=self.export();restored=self.root/'restored'
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=3072).private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        with self.assertRaisesRegex(ValueError,'PRIVATE_PIN_MISMATCH'):
            self.api.restore_candidate(dest,restored,expected_manifest_sha256=receipt['manifest_sha256'],owner_private_pem=wrong)
        self.assertFalse(restored.exists())

    def test_history_cli_accepts_large_archival_records_with_a_separate_bounded_limit(self):
        record=self.root/'record.json';record.write_text(json.dumps(self.record))
        historical=copy.deepcopy(self.history)
        historical['source_document']='PRIVATE_HISTORY_'*(140*1024)
        history=self.root/'large-history.json';history.write_text(json.dumps([historical]))
        self.assertGreater(history.stat().st_size,2*1024*1024)
        output=self.root/'forecast.json';stdout=io.StringIO()
        args=['forecast','--candidate',str(self.path),'--candidate-sha256',self.pin,
              '--record',str(record),'--history',str(history),'--at',self.at,'--output',str(output)]
        try:
            with redirect_stdout(stdout):self.api.main(args)
        except ValueError as error:
            self.fail(f'Valid archival history over 2 MiB must use the separate history limit: {error}')
        self.assertEqual(json.loads(output.read_text())['status'],'READY')
        self.assertNotIn('PRIVATE_HISTORY_',stdout.getvalue())
        self.assertNotIn('PRIVATE_HISTORY_',output.read_text())
        rejected=self.root/'rejected.json';args[-1]=str(rejected)
        with patch.object(self.api,'MAX_HISTORY_BYTES',1024):
            with self.assertRaisesRegex(ValueError,'FILE_SIZE'):
                self.api.main(args)
        self.assertFalse(rejected.exists())

    def test_public_cli_prints_only_receipt_and_create_only_private_prediction(self):
        record=self.root/'record.json';record.write_text(json.dumps(self.record))
        history=self.root/'history.json';history.write_text(json.dumps([self.history]))
        output=self.root/'forecast.json';stdout=io.StringIO()
        args=['forecast','--candidate',str(self.path),'--candidate-sha256',self.pin,
              '--record',str(record),'--history',str(history),'--at',self.at,'--output',str(output)]
        with redirect_stdout(stdout):self.api.main(args)
        self.assertEqual(json.loads(output.read_text())['status'],'READY')
        self.assertNotIn('PRIVATE_',stdout.getvalue())
        original=output.read_bytes()
        with self.assertRaises(FileExistsError):self.api.main(args)
        self.assertEqual(output.read_bytes(),original)


if __name__=='__main__':unittest.main()
