"""Explicit operator boundary; real owner MAC/AES, delegated fit is a fixture."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_research as research
from race_ai import all_existing_model_registry as registry
from race_ai.boat_all_model_store import open_forecasts
from race_ai.official_order_only_result import EVALUATION_SCOPE
from scripts import all_existing_model_learning_ci as ci
from tests import test_all_existing_model_learning_ci as ci_fixtures
from tests import test_all_existing_model_crypto as owner_fixtures

try:wrapper=importlib.import_module('scripts.all_existing_model_order_only_fit')
except ModuleNotFoundError:wrapper=None

KEY=bytes(range(32))
REQUEST=dict(schema='RACE_AI_OWNER_ORDER_ONLY_FIT_REQUEST_V1',
    owner_instruction_ref='OWNER_INSTRUCTION_20261107_PERSONAL_RESEARCH',
    purpose='EXISTING_ALL_FAMILIES_ORDER_ONLY_SHADOW_FIT',
    cohort_policy='EARLIEST_COMPLETE_EIGHT_RACES_PER_SPORT',cohort_size=8,target_fitted_model_count=30,
    sports=['autorace','boat','horse','keirin'],label_evaluation_scope=EVALUATION_SCOPE,
    provider_permission_confirmed=False,production_promoted=False,actual_purchases=False,
    commercial_use_permitted=False,public_raw_data_permitted=False)


class OrderOnlyFitWrapperTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(wrapper,'explicit order-only operator wrapper is missing')
        fixture=ci_fixtures.ExistingModelLearningCiTests(methodName='runTest');fixture.setUp()
        self.addCleanup(fixture.doCleanups);self.fixture=fixture;self.root=fixture.root
        self.now=ci_fixtures.NOW;self.calls=[];self.payload=None;self.shortage=False;self.result_change={};self.bad_mac=False
        self.output=fixture.runner/'candidate';self.restored=fixture.runner/'restored';self.restored.mkdir(mode=0o700)
        self.request_path=self.root/'audit/state/order-only-fit-request.json';self.request_path.parent.mkdir(parents=True)
        self.request_path.write_text(json.dumps(REQUEST));self.original_request=self.request_path.read_bytes()
        self.old=self.root/'audit/state/original-owner-mac.json';self.old.write_bytes(b'original owner record bytes')
        self.manifest=dict(fixture.manifest,schema=ci.SCHEMA_V4,keep_other_sports=True,
            full_native_boat_cohort=True,allow_order_only=True,
            owner_research_record='audit/state/order-only-fit-request.json')
        self.manifest_path=self.root/'operator-v4.json';self.manifest_path.write_text(json.dumps(self.manifest))
        owner=owner_fixtures.AllModelOwnerDecisionTests(methodName='runTest')
        owner.refs=[('https://www.boatrace.jp/fictional/frozen-input',owner_fixtures.B_RIGHTS)]
        self.binding=owner.arguments(now=self.now,label_evaluation_scope=EVALUATION_SCOPE)
        environment=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),GITHUB_ACTIONS='true',
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='42',
            GITHUB_SHA='a'*40,RUNNER_TEMP=str(fixture.runner))
        environment.start();self.addCleanup(environment.stop)
        for target,value in ((ci,'ROOT'),(wrapper,'ROOT')):
            change=patch.object(target,value,self.root);change.start();self.addCleanup(change.stop)
        context=patch.object(wrapper.future,'environment',return_value=dict(run_id=42,head_sha='a'*40,temp=fixture.runner))
        context.start();self.addCleanup(context.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('actual GET forbidden'))
        network.start();self.addCleanup(network.stop)
        process=patch('subprocess.run',side_effect=AssertionError('actual subprocess/Git forbidden'))
        process.start();self.addCleanup(process.stop);self.process_guard=process

    def fit(self,arguments,*,now):
        self.calls.append(list(arguments));self.assertEqual(now,self.now)
        self.assertIn('--common-eight-per-sport',arguments)
        for flag in ('--allow-order-only','--keep-other-sports','--full-native-boat-cohort'):self.assertIn(flag,arguments)
        owner=Path(arguments[arguments.index('--owner-research-record')+1])
        self.assertTrue(owner.is_relative_to(self.fixture.runner));self.assertNotEqual(owner,self.request_path)
        if arguments[0]=='issue-decision':
            if self.shortage:
                print(json.dumps(dict(state='HOLD_ALL_MODEL_RESEARCH',reason='ALL_MODEL_COMMON_EIGHT_PER_SPORT_REQUIRED')))
                return 2
            decision=research.issue_decision(**self.binding,expires_at=self.now+timedelta(days=90))
            if self.bad_mac:decision['mac']='0'*64
            owner.write_bytes(json.dumps(decision,indent=2).encode());owner.chmod(0o600)
            self.assertEqual(owner.stat().st_mode&0o777,0o600)
            print(json.dumps(dict(state='OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED',decision_sha256=digest(decision))))
            return 0
        self.assertEqual(arguments[0],'fit');decision=json.loads(owner.read_bytes())
        research.verify_decision(decision,**self.binding)
        output=Path(arguments[arguments.index('--out-dir')+1]);output.mkdir(mode=0o700)
        for name in ('learning.enc','learning.json','summary.json'):
            path=output/name;path.write_bytes(b'fixture delegated encrypted fit output');path.chmod(0o600)
        cells={cell['cell_key'] for cell in registry.cells() if registry.group(cell['model_id'])!='seller'}
        training=dict(models={cell:dict(unique_races=8,train_races=6,validation_races=2) for cell in cells},
            common_eight_per_sport=True,required_common_cells=30,record_count=240,
            cohort_counts_by_sport={sport:8 for sport in ('boat','autorace','keirin','horse')},
            common_cohort_sha256='c'*64,label_evaluation_scope=EVALUATION_SCOPE,
            owner_research_decision_sha256=digest(decision),production_promoted=False)
        training.update(self.result_change)
        self.payload=dict(training=training,owner_research_record=decision,
            summary=dict(actual_purchases=False,production_promoted=False))
        print(json.dumps(dict(state='FITTED_SHADOW_ONLY',fitted_model_count=30,
            owner_research_decision_sha256=digest(decision),label_evaluation_scope=EVALUATION_SCOPE,
            production_promoted=False,plaintext_published=False)))
        return 0

    def invoke(self):
        stdout=io.StringIO()
        with patch.object(wrapper.learning,'main',side_effect=self.fit), \
                patch.object(wrapper,'read_candidate',side_effect=lambda _:deepcopy(self.payload)),redirect_stdout(stdout):
            code=wrapper.main(['--input',str(self.manifest_path),'--restored-dir',str(self.restored),
                '--out-dir',str(self.output)],now=self.now,_fetch=self.fixture.fetch)
        return code,json.loads(stdout.getvalue()),stdout.getvalue()

    def test_explicit_request_issues_private_v2_then_fits_and_preserves_complete_encrypted_owner_audit(self):
        code,summary,public=self.invoke()
        self.assertEqual(code,0);self.assertTrue(summary['ready']);self.assertEqual(summary['fitted_model_count'],30)
        self.assertEqual([call[0] for call in self.calls],['issue-decision','fit'])
        owner=Path(self.calls[0][self.calls[0].index('--owner-research-record')+1])
        self.assertEqual(owner,Path(self.calls[1][self.calls[1].index('--owner-research-record')+1]));self.assertFalse(owner.exists())
        backup=self.output.with_name(self.output.name+'.owner-research.enc')
        self.assertEqual(backup.stat().st_mode&0o777,0o600)
        evidence=open_forecasts(backup.read_bytes(),key=KEY)
        self.assertEqual(evidence['owner_fit_request'],REQUEST)
        self.assertEqual(evidence['owner_research_record'],self.payload['owner_research_record'])
        research.verify_decision(evidence['owner_research_record'],**self.binding)
        self.assertEqual(summary['owner_record_cipher_sha256'],sha256(backup.read_bytes()).hexdigest())
        self.assertEqual({path.name for path in self.output.iterdir()},{'learning.enc','learning.json','summary.json'})
        self.assertEqual(self.request_path.read_bytes(),self.original_request)
        self.assertEqual(self.old.read_bytes(),b'original owner record bytes')
        for private in ('"mac"','"decision"','source_refs','native_payload','intake_sha256'):
            self.assertNotIn(private,public)

    def test_shortage_holds_before_owner_record_or_fit_without_rewriting_request(self):
        self.shortage=True;code,summary,_=self.invoke()
        self.assertEqual(code,2);self.assertFalse(summary['ready'])
        self.assertEqual(summary['reason'],'ALL_MODEL_COMMON_EIGHT_PER_SPORT_REQUIRED')
        self.assertEqual([call[0] for call in self.calls],['issue-decision'])
        self.assertFalse(self.output.exists());self.assertFalse(self.output.with_name('candidate.owner-research.enc').exists())
        self.assertEqual(self.request_path.read_bytes(),self.original_request)

    def test_invalid_new_owner_mac_is_not_backed_up_or_passed_to_fit(self):
        self.bad_mac=True;code,summary,_=self.invoke()
        self.assertEqual(code,2);self.assertFalse(summary['ready'])
        self.assertEqual([call[0] for call in self.calls],['issue-decision'])
        self.assertFalse(self.output.with_name('candidate.owner-research.enc').exists())

    def test_wrong_request_or_v3_is_rejected_before_download_or_issuer(self):
        for change in (dict(schema='UNKNOWN'),dict(target_fitted_model_count=31),dict(cohort_size=7),
                       dict(label_evaluation_scope='CASH'),dict(production_promoted=True),dict(extra=1)):
            self.request_path.write_text(json.dumps(dict(REQUEST,**change)))
            code,summary,_=self.invoke()
            with self.subTest(change=change):self.assertEqual(code,2);self.assertFalse(summary['ready'])
        self.request_path.write_bytes(self.original_request)
        v3={k:v for k,v in self.manifest.items() if k!='allow_order_only'};v3['schema']=ci.SCHEMA_V3
        self.manifest_path.write_text(json.dumps(v3));code,_,_=self.invoke();self.assertEqual(code,2)
        self.assertEqual(self.calls,[]);self.assertEqual(self.fixture.calls,[])

    def test_missing_key_or_non_actions_stops_before_any_fetch_and_never_searches_key_files(self):
        for change in (dict(RACE_AI_STATE_KEY=''),dict(GITHUB_ACTIONS='false'),dict(GITHUB_REPOSITORY_ID='1')):
            with patch.dict(os.environ,**change):code,summary,_=self.invoke()
            with self.subTest(change=list(change)):self.assertEqual(code,2);self.assertFalse(summary['ready'])
        self.assertEqual(self.calls,[]);self.assertEqual(self.fixture.calls,[])

    def test_incomplete_candidate_counts_or_chronology_never_becomes_ready(self):
        self.result_change=dict(record_count=239)
        code,summary,_=self.invoke();self.assertEqual(code,2);self.assertFalse(summary['ready'])

    def test_real_common_selection_thirty_native_fits_and_encrypted_candidate_roundtrip(self):
        from tests.test_all_existing_model_common_eight_per_sport import common_records,FIXTURE_NOW
        from race_ai.all_existing_model_learning import verify_training
        from race_ai.boat_venue_learning import read_candidate
        rows=common_records();before=deepcopy(rows);self.now=FIXTURE_NOW
        self.binding.update(now=self.now)
        for metadata in self.fixture.metadata.values():
            metadata.update(created_at=(self.now-timedelta(hours=1)).isoformat(),
                expires_at=(self.now+timedelta(days=7)).isoformat())
        loaded=[]
        def admitted_fixture(restored,state,dataset,**options):
            self.assertTrue(options['common_eight_per_sport']);self.assertTrue(options['allow_order_only'])
            selected,cohort=wrapper.learning._select_common_eight_per_sport(deepcopy(rows),now=options['now'])
            loaded.append(cohort)
            refs=set().union(*(wrapper.learning._record_source_refs(row) for row in selected))
            binding={key:deepcopy(value) for key,value in self.binding.items() if key!='now'}
            binding.update(source_refs=[list(pair) for pair in sorted(refs)],
                intake_sha256=wrapper.learning._intake_identity(selected,result_admissions=[],common_cohort=cohort))
            intake=dict(cohort,observed_unique_races=8,eligible=[{} for _ in range(8)],
                native_archive_count=1,native_admitted_records=240,result_archive_count=1,
                result_archive_admissions=[],kept_other_sport_record_count=128,
                kept_other_sports=['autorace','horse','keirin'],order_only_record_count=128,
                label_evaluation_scope=EVALUATION_SCOPE)
            return selected,binding,intake
        self.process_guard.stop();actual_run=subprocess.run
        def local_node(command,*args,**kwargs):
            self.assertEqual(command[0],'node','only the existing local owner codec readiness may run')
            return actual_run(command,*args,**kwargs)
        stdout=io.StringIO()
        with patch('subprocess.run',side_effect=local_node), \
                patch.object(wrapper.learning,'load_intake',side_effect=admitted_fixture),redirect_stdout(stdout):
            code=wrapper.main(['--input',str(self.manifest_path),'--restored-dir',str(self.restored),
                '--out-dir',str(self.output)],now=self.now,_fetch=self.fixture.fetch)
            payload=read_candidate(self.output) if code==0 else None
        summary=json.loads(stdout.getvalue());self.assertEqual(code,0,summary)
        self.assertTrue(summary['ready']);self.assertEqual(summary['fitted_model_count'],30)
        self.assertEqual(len(loaded),2);self.assertEqual(loaded[0],loaded[1]);self.assertEqual(rows,before)
        training=payload['training'];self.assertTrue(verify_training(training));self.assertEqual(len(training['models']),30)
        self.assertEqual({(model['unique_races'],model['train_races'],model['validation_races'])
                          for model in training['models'].values()},{(8,6,2)})
        self.assertEqual(training['scope'],'SYNTHETIC_ONLY')
        self.assertFalse(payload['summary']['actual_purchases']);self.assertNotIn('actual_purchases',training)
        for field,value in (('common_cohort_sha256','f'*64),('record_count',239)):
            altered=deepcopy(training);altered[field]=value
            altered['training_sha256']=digest({key:child for key,child in altered.items() if key!='training_sha256'})
            with self.subTest(common_contract=field),self.assertRaises(ValueError):verify_training(altered)
        altered=deepcopy(training);model=next(iter(altered['models'].values()));line=model['source_lineage'][0]
        for field in ('actual_native_generated_at','native_generation_receipt_sha256',
                      'native_generation_partitions_sha256','native_generation_evidence'):
            line.pop(field,None)
        model['model_sha256']=digest({key:value for key,value in model.items() if key!='model_sha256'})
        altered['training_sha256']=digest({key:value for key,value in altered.items() if key!='training_sha256'})
        with self.assertRaisesRegex(ValueError,'COMMON_COHORT_ORIGINAL_NATIVE_PROOF'):verify_training(altered)
        backup=self.output.with_name('candidate.owner-research.enc')
        audit=open_forecasts(backup.read_bytes(),key=KEY)
        self.assertEqual(audit['owner_research_record'],payload['owner_research_record'])
        self.assertEqual(digest(audit['owner_research_record']),training['owner_research_decision_sha256'])
        self.assertEqual(self.request_path.read_bytes(),self.original_request)
        self.assertEqual(self.old.read_bytes(),b'original owner record bytes')


if __name__=='__main__':unittest.main()
