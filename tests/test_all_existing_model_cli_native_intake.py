"""Invented operator records with real encryption/receipt/native-intake calls.

The authenticated-journal reader and external metadata transport return
invented rows; archive admission, decryption, replay and decision MAC stay real.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai.all_existing_model_learning import fit,records_from_observed
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.all_existing_model_research import issue_decision,verify_decision
from scripts import all_existing_model_learning as cli
from tests import test_all_existing_model_pairs as fixtures
from tests.test_boat_venue_research import personal_data,SOURCE,CONTENT,B_RIGHTS
from tests.test_boat_venue_learning import POINTER
from tests.test_frozen_day_cycle import observation


class AllExistingModelCliNativeIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows,cls.observations=personal_data(8)
        cls.records=records_from_observed(cls.rows,cls.observations)
        cls.training=fit(cls.records,now=fixtures.NOW,
                         allow_source=lambda *_:True,allow_training=lambda *_:True)

    def setUp(self):
        fixture=fixtures.AllExistingModelPrivatePairsTests(methodName='runTest')
        fixture.records=self.records;fixture.training=self.training
        fixture.cell=next(iter(self.training['models']));fixture.setUp()
        self.addCleanup(fixture.doCleanups);self.fixture=fixture;self.root=fixture.root
        requests=fixture.extra_native_requests()
        for request in requests:
            payload=request['native_payload'];payload['scope']='OPERATOR_SUPPLIED_RESEARCH'
            base=payload.get('source',payload.get('base_source'))
            hashes=[base['program_source_sha256'],base['beforeinfo_source_sha256']]
            if 'extra' in payload:hashes.append(payload['extra']['source_sha256'])
            payload['source_evidence']=[dict(source_ref='https://www.boatrace.jp/fictional/native/'+str(i),
                source_rights_ref=B_RIGHTS,source_sha256=sha) for i,sha in enumerate(hashes)]
        requests.extend(dict(cell_key='boat/'+mid,native_payload=fixture.native())
                        for mid in self.training['registered_model_ids'] if 'boat/'+mid in self.training['models'])
        self.requests=deepcopy(requests)
        make_private_pairs(fixture.context,requests,self.root/'pairs',now=fixtures.FORECAST_NOW,
                           allow_source=lambda *_:True)
        self.raw,_=fixture.archive();self.metadata=fixture.metadata(self.raw)
        self.actual_metadata=deepcopy(self.metadata);self.metadata_requests=[]
        def external_metadata(url):
            self.assertEqual(url,cli.BASE+'/actions/artifacts/800')
            self.metadata_requests.append(url)
            return deepcopy(self.actual_metadata)
        transport=patch.object(cli,'_github_json',side_effect=external_metadata)
        transport.start();self.addCleanup(transport.stop)
        self.archive=self.root/'archive';self.archive.mkdir(mode=0o700)
        for name,raw in (('archive.zip',self.raw),('metadata.json',json.dumps(self.metadata).encode())):
            path=self.archive/name;path.write_bytes(raw);path.chmod(0o600)
        self.dataset=self.root/'dataset.json';self.dataset.write_text(json.dumps(POINTER));self.dataset.chmod(0o600)
        self.now=fixtures.FORECAST_NOW+timedelta(hours=1)
        pair=fixture.payload()['pair'];normalized=pair['baseline_normalized']
        future=observation(dict(race_id='20300401-24-12',cutoff_at=pair['race_cutoff_at'],
            top8=[normalized['top'][0]],roster=normalized['roster']))
        future.update(captured_at=(fixtures.FORECAST_NOW+timedelta(minutes=21)).isoformat(),
            source_url='https://www.boatrace.jp/owpc/pc/race/raceresult?hd=20300401&jcd=24&rno=12')
        self.future=future

    def verified(self,observations=None):
        return deepcopy((self.rows,self.observations+[self.future] if observations is None else observations,SOURCE,CONTENT))

    def load(self,paths=(),observations=None):
        with patch.object(cli,'load_verified_intake',return_value=self.verified(observations)) as authenticated:
            result=cli.load_intake(self.root/'restored','unused-state-pointer',self.dataset,
                                   now=self.now,native_archive_dirs=paths)
        self.assertIs(authenticated.call_args.kwargs['authenticate_owner_cipher'],True)
        return result

    def arguments(self,command,path):
        return [command,'--restored-dir',str(self.root/'restored'),'--state-input','unused-state-pointer',
            '--dataset-input',str(self.dataset),'--native-archive-dir',str(self.archive),
            '--owner-research-record',str(path),'--out-dir',str(self.root/'fit')]

    def test_optional_actual_archive_adds_five_native_rows_keeps_sixteen_originals_and_exact_refs(self):
        original,binding,intake=self.load()
        records,new_binding,new_intake=self.load([self.archive])
        self.assertEqual(len(original),16);self.assertEqual(len(records),21)
        self.assertEqual(records[:16],original)
        self.assertEqual(binding['intake_sha256'],digest(original))
        self.assertEqual(new_binding['intake_sha256'],digest(records))
        self.assertNotEqual(binding['intake_sha256'],new_binding['intake_sha256'])
        self.assertNotIn('native_archive_intakes',intake)
        self.assertEqual(new_intake['native_archive_count'],1)
        self.assertEqual(new_intake['native_admitted_records'],5)
        self.assertEqual({row['input_receipt']['artifact_id'] for row in records[16:]},{800})
        refs=set(map(tuple,new_binding['source_refs']))
        self.assertTrue(set(map(tuple,binding['source_refs'])).issubset(refs))
        self.assertIn(('https://www.boatrace.jp/fictional/native/0',B_RIGHTS),refs)
        for row in records[16:]:
            self.assertEqual(row['result_observation'],self.future)
            self.assertIsNone(row['result']['published_at'])
        twice,twice_binding,twice_intake=self.load([self.archive,self.archive])
        self.assertEqual(twice,records);self.assertEqual(twice_binding,new_binding)
        self.assertEqual(twice_intake['native_archive_count'],1)
        self.assertEqual(len(self.metadata_requests),3)

    def test_old_scope_never_auto_reissues_but_explicit_new_scope_binds_actual_archive(self):
        _,binding,_=self.load();record_path=self.root/'owner.json'
        old=issue_decision(**binding,now=self.now,expires_at=self.now+timedelta(days=1))
        record_path.write_text(json.dumps(old));record_path.chmod(0o600)
        with patch.object(cli,'load_verified_intake',return_value=self.verified()),patch.object(
                cli,'fit',side_effect=AssertionError('changed scope must stop before fitting')) as fitter:
            out=io.StringIO()
            with redirect_stdout(out):code=cli.main(self.arguments('fit',record_path),now=self.now)
        self.assertEqual(code,2);fitter.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())['reason'],'ALL_MODEL_OWNER_RESEARCH_SCOPE_CHANGED')
        self.assertEqual(json.loads(record_path.read_text()),old)
        new_path=self.root/'new-owner.json'
        with patch.object(cli,'load_verified_intake',return_value=self.verified()):
            out=io.StringIO()
            with redirect_stdout(out):code=cli.main(self.arguments('issue-decision',new_path),now=self.now)
        self.assertEqual(code,0)
        _,new_binding,_=self.load([self.archive])
        verified=verify_decision(json.loads(new_path.read_text()),**new_binding,now=self.now)
        self.assertEqual(json.loads(out.getvalue())['decision_sha256'],verified)
        self.assertFalse((self.root/'fit').exists())
        self.assertNotIn('participants',out.getvalue());self.assertNotIn('native_payload',out.getvalue())

    def test_bad_digest_repo_head_or_private_file_permissions_stop_before_join(self):
        variants=[dict(self.metadata,digest='sha256:'+'0'*64),
                  dict(self.metadata,workflow_run=dict(self.metadata['workflow_run'],repository_id=1)),
                  dict(self.metadata,workflow_run=dict(self.metadata['workflow_run'],head_sha='not-head'))]
        for value in variants:
            with self.subTest(value=value):
                (self.archive/'metadata.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):self.load([self.archive])
        (self.archive/'metadata.json').write_text(json.dumps(self.metadata))
        (self.archive/'archive.zip').chmod(0o644)
        with self.assertRaisesRegex(ValueError,'PRIVATE_FILES_REQUIRED'):self.load([self.archive])
        (self.archive/'archive.zip').chmod(0o600)
        other=self.root/'alias';other.symlink_to(self.archive,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'PRIVATE_DIRECTORY_REQUIRED'):self.load([other])

    def test_explicit_native_scope_fit_encrypts_real_native_records_without_claiming_bootstrap_fit(self):
        from race_ai.boat_venue_learning import read_candidate
        record_path=self.root/'new-owner.json'
        outputs=[]
        with patch.object(cli,'load_verified_intake',return_value=self.verified()):
            for command in ('issue-decision','fit'):
                output=io.StringIO()
                with redirect_stdout(output):code=cli.main(self.arguments(command,record_path),now=self.now)
                self.assertEqual(code,0,output.getvalue());outputs.append(json.loads(output.getvalue()))
        self.assertEqual(outputs[1]['native_archive_count'],1)
        self.assertEqual(outputs[1]['native_admitted_records'],5)
        self.assertTrue(outputs[1]['encrypted_readback_verified'])
        training=read_candidate(self.root/'fit')['training']
        self.assertEqual(len(training['models']),2)
        self.assertEqual({m['unique_races'] for m in training['models'].values()},{9})
        nonobserved={k:v for k,v in training['model_states'].items()
                     if k not in training['models'] and v['unique_races']}
        self.assertEqual(len(nonobserved),3)
        self.assertEqual({v['unique_races'] for v in nonobserved.values()},{1})
        self.assertEqual({v['state'] for v in nonobserved.values()},{'INSUFFICIENT_VERIFIED_RACES'})
        self.assertFalse(outputs[1]['production_promoted'])

    def test_only_authenticated_journal_labels_are_joined_and_conflicting_aliases_stop(self):
        without=self.load([self.archive],self.observations)
        self.assertEqual(len(without[0]),16)
        self.assertEqual(without[2]['native_archive_intakes'][0]['missing_result_native_input_count'],5)
        duplicate=deepcopy(self.future);duplicate['race_id']='boat:2030-04-01:boatrace-jcd-24:12'
        records,_,_=self.load([self.archive],self.observations+[self.future,duplicate])
        self.assertEqual(len(records),21)
        duplicate['data']['results'][0]['racer_registration_id']='9999'
        with self.assertRaisesRegex(ValueError,'CONFLICTING_RESULT'):
            self.load([self.archive],self.observations+[self.future,duplicate])

    def test_local_pre_cutoff_clock_cannot_override_actual_late_server_metadata(self):
        self.actual_metadata['created_at']=(fixtures.FORECAST_NOW+timedelta(minutes=21)).isoformat()
        with self.assertRaisesRegex(ValueError,'ACTUAL_METADATA_MISMATCH'):
            self.load([self.archive])
        self.assertEqual(len(self.metadata_requests),1)

    def test_equal_time_frozen_native_conflict_is_rejected(self):
        records,_,_=self.load([self.archive]);old=records[-1];changed=deepcopy(old)
        changed['input_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'CONFLICTING_RECORD'):
            cli._merge_native_records(records,[changed])

    def test_frozen_native_only_archive_bootstraps_unfitted_cells_without_pair_or_fake_prediction(self):
        selected=[request for request in self.requests if request['cell_key'] not in self.training['models']]
        output=self.root/'input-only'
        make_private_pairs(self.fixture.context,selected,output,now=fixtures.FORECAST_NOW,
                           allow_source=lambda *_:True)
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w',zipfile.ZIP_DEFLATED) as archive:
            for folder in sorted(path for path in output.iterdir() if path.is_dir()):
                for name in ('learning.json','learning.enc','summary.json'):
                    archive.writestr(folder.name+'/'+name,(folder/name).read_bytes())
        raw=body.getvalue();metadata=self.fixture.metadata(raw)
        self.actual_metadata=deepcopy(metadata)
        source=self.root/'input-only-archive';source.mkdir(mode=0o700)
        for name,value in (('archive.zip',raw),('metadata.json',json.dumps(metadata).encode())):
            path=source/name;path.write_bytes(value);path.chmod(0o600)
        records,_,intake=self.load([source])
        self.assertEqual(len(records),19);self.assertEqual(intake['native_admitted_records'],3)
        for record in records[16:]:
            self.assertNotIn('pair_sha256',record['input_partitions'][0])
            self.assertEqual(len(record['input_partitions'][0]['native_inputs_record_sha256']),64)
            self.assertIsNone(record['input_partitions'][0]['carrier_cell_key'])


if __name__=='__main__':unittest.main()
