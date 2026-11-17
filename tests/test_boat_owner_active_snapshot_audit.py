"""Invented encrypted receipts; no live API, inference during audit or source GET."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
OWNER=ROOT/'owner-source'
sys.path.insert(0,str(OWNER))
import race_ai,tests,scripts
for folder in ('pr64-reference','pr72-reference'):
    race_ai.__path__.append(str(OWNER/folder/'race_ai'))
tests.__path__.append(str(OWNER/'tests'))
scripts.__path__.append(str(ROOT/'scripts'))
from race_ai.actions_contract import digest
from race_ai.boat_private_original_archive import seal_original_zip
from tests.test_boat_private_original_vault import packed
from tests.test_frozen_day_cycle import sample
from tests.private_cycle_ui_fixture import _artifacts
from tests import test_boat_all_model_recovery as M

HEAD='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
KEY=bytes(range(32))
NOW=datetime(2030,4,1,9,5,tzinfo=timezone.utc)
DAY='2030-04-01'
path=ROOT/'scripts/boat_owner_active_snapshot_audit.py'
if path.exists():
    spec=importlib.util.spec_from_file_location('main_active_snapshot',path)
    active=importlib.util.module_from_spec(spec);spec.loader.exec_module(active)
else:active=None


class ActiveSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        M.ModelRecoveryTests.setUpClass()

    def setUp(self):
        self.env=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        self.env.start();self.addCleanup(self.env.stop)
        self.run=dict(id=99,head_sha=HEAD,head_branch='production/boat-p0-p1-20261111',
            event='workflow_dispatch',workflow_id=405276784,status='in_progress',conclusion=None,
            run_attempt=1,created_at='2030-04-01T01:30:00Z',updated_at='2030-04-01T09:03:00Z',
            repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))
        self.job=dict(id=777,run_id=99,run_attempt=1,head_sha=HEAD,status='in_progress',
            name='Existing frozen P0, exhibition P1, separate official results and PDCA',
            steps=[dict(name='Deadline-ordered five-model round 01',status='completed',conclusion='success',
                started_at='2030-04-01T01:40:00Z',completed_at='2030-04-01T09:02:00Z'),
                dict(name='Deadline-ordered five-model round 02',status='in_progress',conclusion=None,
                started_at='2030-04-01T09:02:00Z',completed_at=None)])
        self.raws={};self.metas={};self.calls=[];self.extra={}
        doc,_,_=sample();doc.update(code_sha=HEAD,source_sha256='a'*64)
        self.add(100,'boat-p0-existing-99','P0',packed({'forecasts.json':json.dumps(doc)}),'2030-04-01T01:43:00Z')
        p1raw,_=_artifacts()[0][1]
        self.add(101,'boat-national-cutoff-99','P1',p1raw,'2030-04-01T01:43:01Z')
        self.state=dict(day_jst=DAY,run_id=99,requests_used=20,completed_round=0,prepared_round=1,
            lifetime_requests_base=88,lifetime_requests=108,lifetime_completed_rounds_base=7,
            lifetime_completed_rounds=7,day_start_lifetime_requests=88,source_wait=None,halted_reason=None)
        self.report=dict(day_jst=DAY,run_id='99',code_sha=HEAD,round_no=1,
            first_forecast_artifacts=[self.metas[101]],bounded_repeat_session=self.state,
            updated_at='2030-04-01T09:01:00Z',private='PRIVATE_FORECAST_SENTINEL')
        self.result()
        payload=deepcopy(M.ModelRecoveryTests.payload)
        payload.update(run_id='99',source_code_commit=HEAD)
        payload['runtime_provenance']['source_code_commit']=HEAD
        from race_ai import boat_all_model_store as store,boat_all_model_cycle as engine
        raw=M.zipped(store.seal_forecasts(payload,run_id='99',round_no=1,key=KEY))
        self.add(103,'boat-all-model-forecasts-99-r1',None,raw,'2030-04-01T09:00:20Z')
        receipt=dict(repository_id='1416489937',repository='haji84/RACE-AI',run_id='99',head_sha=HEAD,
            artifact_id=103,created_at=self.metas[103]['created_at'],payload_sha256=digest(payload),independently_verified=True)
        self.view=engine.project_round(payload,receipt)
        self.cutoffs={r['race_id']:datetime.fromisoformat(r['cutoff_at'].replace('Z','+00:00')) for r in self.view['records']}

    def add(self,ident,name,kind,raw,at):
        if kind:raw=packed({'private-original.enc':seal_original_zip(raw,run_id=99,head_sha=HEAD,kind=kind,key=KEY)})
        self.raws[ident]=raw
        self.metas[ident]=dict(id=ident,name=name,expired=False,digest='sha256:'+sha256(raw).hexdigest(),
            size_in_bytes=len(raw),created_at=at,expires_at='2030-04-08T09:00:00Z',
            workflow_run=dict(id=99,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))

    def result(self,nested=None):
        self.report['report_sha256']=digest({k:v for k,v in self.report.items() if k!='report_sha256'})
        self.add(102,'race-existing-cycle-99','RESULT',packed({
            'status.json':json.dumps(self.report),'official-result-observations.json':'[]',
            'current-p1-original.zip':self.raws[101] if nested is None else nested}), '2030-04-01T09:01:01Z')

    def get(self,route):
        self.calls.append(route)
        if route in self.extra:return self.extra[route]
        if route=='actions/runs/99':return json.dumps(self.run).encode()
        if route=='actions/runs/99/jobs?per_page=100':return json.dumps(dict(total_count=1,jobs=[self.job])).encode()
        if route=='actions/runs/99/artifacts?per_page=100':return json.dumps(dict(total_count=len(self.metas),artifacts=list(self.metas.values()))).encode()
        if route.startswith('actions/artifacts/'):
            ident=int(route.split('/')[2]);return self.raws[ident] if route.endswith('/zip') else json.dumps(self.metas[ident]).encode()
        raise AssertionError('unexpected external route')

    def audit(self,get=None):
        self.assertIsNotNone(active,'active completed-receipt audit is missing')
        # Official B verification has separate raw-vault tests. This fixture
        # keeps every AES/ZIP/projection reader real and isolates that dependency.
        from scripts import boat_exact_all_model_zip_readback as exact
        with patch.object(exact,'_official_cutoffs',return_value=self.cutoffs),\
             patch.object(active,'_saved_view',return_value=self.view):
            return active.audit_active_snapshot(Path('unused'),99,now=NOW,get=get or self.get)

    def test_completed_receipts_are_independently_decrypted_with_precomplete_counters(self):
        before=deepcopy((self.raws,self.metas,self.state,self.view))
        out=self.audit()
        self.assertEqual(out['completed_rounds_audited'],[1])
        self.assertEqual(out['raw_aes_archives_verified'],4)
        self.assertEqual(out['round_evidence'][0]['sealed_precompletion_counters'],self.state)
        for key in ('full_day_coverage','successor_dispatch_allowed','latest_live_counters_audited'):
            self.assertIs(out[key],False)
        self.assertEqual(out['official_source_requests'],0)
        self.assertNotIn('PRIVATE_',json.dumps(out));self.assertNotIn('ordered_top8',json.dumps(out))
        self.assertEqual((self.raws,self.metas,self.state,self.view),before)

    def test_missing_duplicate_corrupt_expired_head_key_and_nested_receipts_refuse(self):
        for case in ('missing','duplicate','corrupt','expired','expires','head','metahead','key',
                     'nested','reference','counter','day','job','late','allmodelduplicate','allmodellate'):
            with self.subTest(case=case):
                saved=deepcopy((self.raws,self.metas,self.report,self.run,self.job))
                if case=='missing':self.metas.pop(102)
                elif case=='duplicate':self.metas[999]=dict(self.metas[101],id=999)
                elif case=='corrupt':self.raws[103]+=b'changed'
                elif case=='expired':self.metas[101]['expired']=True
                elif case=='expires':self.metas[101]['expires_at']='2030-04-01T09:04:00Z'
                elif case=='head':self.run['head_sha']='f'*40
                elif case=='metahead':self.metas[103]['workflow_run']['head_sha']='f'*40
                elif case=='nested':self.result(nested=b'changed')
                elif case=='reference':self.report['first_forecast_artifacts']=[dict(self.metas[101],id=999)];self.result()
                elif case=='counter':self.state['lifetime_requests']=999;self.result()
                elif case=='day':self.report['day_jst']='2030-04-02';self.result()
                elif case=='job':self.job['run_id']=1
                elif case=='late':self.metas[102]['created_at']='2030-04-01T09:04:00Z'
                elif case=='allmodelduplicate':self.metas[999]=dict(self.metas[103],id=999)
                elif case=='allmodellate':self.metas[103]['created_at']='2030-04-01T09:04:00Z'
                with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(b'x'*32 if case=='key' else KEY).decode()):
                    with self.assertRaises(ValueError):self.audit()
                self.raws,self.metas,self.report,self.run,self.job=saved
                self.state=self.report['bounded_repeat_session']

    def test_later_inventory_growth_is_excluded_not_reinterpreted_as_a_full_day(self):
        def growing(route):
            raw=self.get(route)
            if route.endswith('artifacts?per_page=100'):
                self.metas[104]=dict(self.metas[103],id=104,name='boat-all-model-forecasts-99-r2')
            return raw
        out=self.audit(growing)
        self.assertEqual(out['completed_rounds_audited'],[1])
        self.assertEqual(out['raw_aes_archives_verified'],4)
        self.assertNotIn('actions/artifacts/104/zip',self.calls)

    def test_p0_supplements_and_initial_model_archive_are_not_silently_skipped(self):
        from race_ai import boat_all_model_store as store
        document,_,_=sample();document.update(code_sha=HEAD,source_sha256='a'*64)
        self.add(104,'boat-p0-existing-99-cycle-01','P0',packed({'forecasts.json':json.dumps(document)}),
                 '2030-04-01T01:43:02Z')
        payload=deepcopy(M.ModelRecoveryTests.empty_payload)
        payload.update(stage='P0',run_id='99',source_code_commit=HEAD,generated_at='2030-04-01T01:39:00Z',
            as_of='2030-04-01T01:39:00Z',dispatch_reports=[],native_input_capsules=[],current_inputs=[],
            baseline=None,summary=dict(contexts=0,generated_forecasts=0,reused_baseline_forecasts=0))
        payload['runtime_provenance']['source_code_commit']=HEAD
        self.add(105,'boat-all-model-forecasts-99-r0',None,
            M.zipped(store.seal_forecasts(payload,run_id='99',round_no=0,key=KEY)), '2030-04-01T01:39:01Z')
        out=self.audit()
        self.assertEqual(out['p0_supplements_verified'],1)
        self.assertEqual(out['raw_aes_archives_verified'],6)
        self.assertEqual(out['all_model_zip_readback']['active_completed_round_scope'],[0,1])
        for ident in (104,105):self.assertIn(f'actions/artifacts/{ident}/zip',self.calls)

    def test_growth_during_pagination_fails_closed(self):
        def growing(route):
            if route.endswith('artifacts?per_page=100'):
                rows=list(self.metas.values())+[dict(id=i,name=f'irrelevant-{i}') for i in range(1000,1096)]
                return json.dumps(dict(total_count=101,artifacts=rows)).encode()
            if route.endswith('artifacts?per_page=100&page=2'):
                return json.dumps(dict(total_count=102,artifacts=[dict(id=2000,name='new')])).encode()
            return self.get(route)
        with self.assertRaises(ValueError):self.audit(growing)

    def test_inherited_p0_is_resolved_from_exact_registry_without_relabeling_active_run(self):
        from race_ai.boat_private_original_archive import open_original_zip
        with open_original_zip(self.raws[100],self.metas[100],expected_kind='P0',key=KEY) as z:
            doc=json.loads(z.read('forecasts.json'))
        prior='c123b8538006b3189181195bbc91d8f28d216ba5';doc['code_sha']=prior
        raw=packed({'private-original.enc':seal_original_zip(packed({'forecasts.json':json.dumps(doc)}),
            run_id=88,head_sha=prior,kind='P0',key=KEY)})
        meta=deepcopy(self.metas.pop(100));meta.update(id=200,name='boat-p0-existing-88',
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),created_at='2030-04-01T01:29:00Z')
        meta['created_at']='2030-04-01T01:43:00Z'
        self.run['created_at']='2030-04-01T01:43:00Z'
        self.job['steps'][0]['started_at']='2030-04-01T01:43:00Z'
        meta['workflow_run'].update(id=88,head_sha=prior)
        origin=dict(self.run,id=88,head_sha=prior,status='completed',conclusion='failure',
                    created_at='2030-04-01T01:00:00Z',updated_at='2030-04-01T01:43:00Z')
        receipt=dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1',day_jst=DAY,no_regeneration=True,
            run_id=88,artifact_id=200,zip_sha256=sha256(raw).hexdigest(),server_created_at=meta['created_at'])
        body=json.dumps(receipt).encode();commit='d'*40;path=f'docs/evidence/{DAY}/p0-first-receipt.json'
        self.extra.update({'git/ref/heads/feat/four-sport-forecast-audit-view-20261022':json.dumps(dict(object=dict(sha=commit))).encode(),
            f'contents/{path}?ref={commit}':json.dumps(dict(type='file',path=path,encoding='base64',
                content=base64.b64encode(body).decode(),size=len(body),sha=__import__('hashlib').sha1(f'blob {len(body)}\0'.encode()+body).hexdigest())).encode(),
            'actions/runs/88':json.dumps(origin).encode(),
            'actions/runs/88/artifacts?per_page=100':json.dumps(dict(total_count=1,artifacts=[meta])).encode(),
            'actions/artifacts/200':json.dumps(meta).encode(),'actions/artifacts/200/zip':raw})
        out=self.audit()
        self.assertEqual(out['p0_origin_run_id'],88)
        self.assertEqual(self.run['status'],'in_progress')
        registry=f'contents/{path}?ref={commit}';value=json.loads(self.extra[registry]);value['sha']='f'*40
        self.extra[registry]=json.dumps(value).encode()
        with self.assertRaises(ValueError):self.audit()

    def test_default_exact_reader_refuses_an_active_run_without_inventory_scope(self):
        from scripts import boat_exact_all_model_zip_readback as exact
        with self.assertRaises(ValueError):
            exact.audit(get=self.get,repo='unused',run_id=99,day=DAY,expected_models=['boat-model-A'],
                        original_view=self.view,now=NOW,owner_key=KEY)

    def test_workflow_uses_current_push_target_and_keeps_completed_defaults(self):
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertNotIn("|| '43818666068'",text)
        self.assertIn("|| '44019591352'",text)
        self.assertIn('audit_active_snapshot',text)
        self.assertEqual(text.count("|| '44019591352'"),3)
        self.assertEqual(text.count("if: success() && steps.original_audit.outputs.active_snapshot != 'true'"),2)
        self.assertNotIn('gh workflow run',text.split('\n  authenticated_original_matrix:\n',1)[1])
        self.assertNotIn('workflow_dispatch:',text.split('permissions:',1)[0])
        import ast,textwrap
        for tag in ('PY','PY_ALL_MODEL','PY_EXACT'):
            marker="python - <<'"+tag+"'\n"
            block=text.split(marker)[-1].split('\n          '+tag,1)[0]
            ast.parse(textwrap.dedent(block))
        from scripts import boat_owner_evidence_audit as ordinary
        self.assertIn("run.get('status')=='completed'",__import__('inspect').getsource(ordinary.inspect_run))

    def test_explicit_exact_scope_cannot_change_its_run_jobs_inventory_or_clock(self):
        from race_ai.actions_contract import digest
        reads=active._Reads(self.get)
        job,rounds=active._jobs(reads,self.run,NOW)
        listing=list(self.metas.values())
        scope=dict(schema=active.SCHEMA,run=self.run,job=job,rounds=rounds,inventory=listing,
                   inventory_sha256=digest(listing),captured_at=NOW.isoformat())
        for field,value in (('rounds',[2]),('inventory_sha256','f'*64),('captured_at','2030-04-01T09:06:00Z'),
                            ('job',dict(job,run_id=999)),('run',dict(self.run,head_sha='f'*40))):
            changed=deepcopy(scope);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                active.validate_active_scope(changed,self.run,listing,NOW,reads)

if __name__=='__main__':unittest.main()
