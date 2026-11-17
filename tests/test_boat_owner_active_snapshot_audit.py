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

    def audit(self,get=None,*,missing_program=False,**scope_options):
        self.assertIsNotNone(active,'active completed-receipt audit is missing')
        # Official B verification has separate raw-vault tests. This fixture
        # keeps every AES/ZIP/projection reader real and isolates that dependency.
        from scripts import boat_exact_all_model_zip_readback as exact
        from race_ai import boat_program_source as program
        cutoff_patch=(patch.object(program,'load_program_source',return_value=None) if missing_program else
                      patch.object(exact,'_official_cutoffs',return_value=self.cutoffs))
        with cutoff_patch,\
             patch.object(active,'_saved_view',return_value=self.view):
            return active.audit_active_snapshot(Path('unused'),99,now=NOW,get=get or self.get,**scope_options)

    def test_absent_program_keeps_default_refusal_but_active_raw_aes_is_explicitly_unqualified(self):
        out=self.audit(missing_program=True)
        proof=out['all_model_zip_readback']
        self.assertEqual(out['raw_aes_archives_verified'],4)
        self.assertFalse(out['official_cutoff_qualification'])
        self.assertEqual(out['cutoff_qualification_blocker'],'OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE')
        self.assertEqual(proof['status'],'AES_ZIP_REPLAY_VERIFIED_OFFICIAL_PROGRAM_UNAVAILABLE')
        self.assertEqual(proof['aes_originals_independently_decrypted'],1)
        self.assertEqual(proof['original_content_projection_verified'],1)
        self.assertGreater(proof['original_predictions_matched_saved_AES_view'],0)
        self.assertEqual(proof['physical_pre_cutoff_distinct_model_slots'],0)
        self.assertEqual(proof['official_schedule_crosschecked_pre_cutoff_model_slots'],0)
        self.assertIsNone(proof['authentic_official_P0_schedule_races'])
        self.assertIsNone(proof['scheduled_view_model_slot_upper_bound'])
        self.assertEqual(proof['unqualified_original_reasons']['OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE'],
                         proof['p1_forecast_rows_reopened'])
        from scripts import boat_exact_all_model_zip_readback as exact
        from race_ai import boat_program_source as program
        self.run.update(status='completed',conclusion='success')
        with patch.object(program,'load_program_source',return_value=None):
            with self.assertRaisesRegex(ValueError,'^BOAT_EXACT_ZIP_READBACK_OFFICIAL_PROGRAM_UNAVAILABLE$'):
                exact.audit(get=self.get,repo='unused',run_id=99,day=DAY,expected_models=['boat-model-A'],
                            original_view=self.view,now=NOW,owner_key=KEY)

    def test_absent_program_never_converts_key_hash_source_day_late_nested_or_refusal_to_success(self):
        from race_ai import boat_program_source as program
        for case in ('key','hash','source','day','late','nested','program_corrupt','spoofed_absence','denial'):
            before=deepcopy((self.raws,self.metas,self.report,self.run))
            with self.subTest(case=case):
                if case=='hash':self.raws[103]+=b'changed'
                elif case=='source':self.metas[103]['workflow_run']['head_sha']='f'*40
                elif case=='day':self.report['day_jst']='2030-04-02';self.result()
                elif case=='late':self.metas[103]['created_at']='2030-04-01T09:04:00Z'
                elif case=='nested':self.result(nested=b'changed')
                def get(path):
                    if case=='denial' and path=='actions/artifacts/103/zip':
                        raise ValueError('GITHUB_API_READ_HTTP_403_HALT')
                    return self.get(path)
                with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(b'x'*32 if case=='key' else KEY).decode()):
                    if case in ('program_corrupt','spoofed_absence'):
                        code=('BOAT_EXACT_ZIP_READBACK_OFFICIAL_PROGRAM_UNAVAILABLE' if case=='spoofed_absence'
                              else 'PROGRAM_SOURCE_CATALOG_AUTHENTICATION_FAILED')
                        with patch.object(program,'load_program_source',side_effect=ValueError(code)),\
                             patch.object(active,'_saved_view',return_value=self.view),self.assertRaises(ValueError):
                            active.audit_active_snapshot(Path('unused'),99,now=NOW,get=get)
                    else:
                        with self.assertRaises(ValueError):self.audit(get,missing_program=True)
                self.raws,self.metas,self.report,self.run=before;self.state=self.report['bounded_repeat_session']

    def test_failure_diagnostic_emits_only_static_public_code_location(self):
        from scripts import boat_exact_all_model_zip_readback as exact
        try:exact._owner_head('private-owner-token-sentinel')
        except ValueError as error:report=active.failure_diagnostic(error)
        self.assertIn('scripts/boat_exact_all_model_zip_readback.py:',report['failure_at'])
        self.assertEqual(report['failure_function'],'_owner_head')
        self.assertNotIn('sentinel',json.dumps(report))
        self.assertEqual(active.failure_diagnostic(RuntimeError('private-exception-sentinel')), {})

    def test_unqualified_scan_still_rejects_projection_day_head_and_receipt_changes(self):
        from collections import Counter
        from scripts import boat_exact_all_model_zip_readback as exact
        models={p['model_id'] for row in self.view['records']
                for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None}
        for field,value in (('event_date_jst','2030-04-02'),('source_code_commit','f'*40),
                            ('external_receipt_verified',False),('server_saved_at','2030-04-01T09:01:00Z')):
            view=deepcopy(self.view)
            if field=='event_date_jst':view['records'][0][field]=value
            else:
                row=view['records'][0];prediction=next(p for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                                                      if p is not None and p.get('artifact_id')==103)
                prediction[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                exact._scan_unqualified_originals(view,day=DAY,artifact_id=103,
                    physical_saved_at=self.metas[103]['created_at'],expected=models,
                    source_original_index=Counter(),expected_owner_sha=HEAD)

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

    def test_default_eff_still_refuses_a_missing_completed_round_model_archive(self):
        self.metas.pop(103)
        with self.assertRaises(ValueError):self.audit(missing_program=True)

    def test_workflow_uses_current_push_target_and_keeps_completed_defaults(self):
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        self.assertNotIn("|| '43818666068'",text)
        self.assertIn('audit_active_snapshot',text)
        self.assertEqual(text.count('OWNER_AUDIT_RUN_ID: ${{ steps.audit_target.outputs.run_id }}'),3)
        self.assertEqual(active.select_audit_target('push',dict(ref='refs/heads/main',repository={'full_name':'haji84/RACE-AI'}))['run_id'],44019591352)
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

M2_HEAD='86b029ae5bddd5d4956497d8b32b2c92b8eec521'


class M2SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): ActiveSnapshotTests.setUpClass()

    def setUp(self):
        source=patch.object(sys.modules[__name__],'HEAD',M2_HEAD);source.start();self.addCleanup(source.stop)
        self.f=ActiveSnapshotTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def audit(self,**kwargs):
        return self.f.audit(expected_owner_sha=M2_HEAD,**kwargs)

    def mixed_baseline(self):
        """Prepare genuine existing native outputs before the read-only audit."""
        from race_ai import boat_all_model_cycle as engine,boat_all_model_store as store
        native=M.model_fixture;fixture=native.AllModelCycleTests();fixture.setUp()
        try:
            context=native.source_context();document=native.native_baseline(context)
            proof=native.receipt(document,artifact=201,saved='2030-04-01T09:00:01Z')
            proof['run_id']='88'
            payload=engine.forecast_round([context],fixture.runtime(),now=native.NOW,
                baseline_document=document,baseline_receipt=proof)
        finally:fixture.doCleanups()
        old=active.OWNER_SHA
        payload.update(run_id='99',source_code_commit=M2_HEAD)
        payload['runtime_provenance']['source_code_commit']=M2_HEAD
        payload['baseline']['receipt']['head_sha']=old
        raw=packed({'private-original.enc':seal_original_zip(packed({'national.json':json.dumps(document)}),
            run_id=88,head_sha=old,kind='P1',key=KEY)})
        meta=dict(self.f.metas[101],id=201,name='boat-national-cutoff-88',created_at='2030-04-01T09:00:01Z',
                  digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
        meta['workflow_run']=dict(meta['workflow_run'],id=88,head_sha=old)
        origin=dict(self.f.run,id=88,head_sha=old,status='completed',conclusion='success',
                    created_at='2030-04-01T01:00:00Z',updated_at='2030-04-01T09:00:02Z')
        self.f.extra.update({'actions/runs/88':json.dumps(origin).encode(),
            'actions/runs/88/artifacts?per_page=100':json.dumps(dict(total_count=1,artifacts=[meta])).encode(),
            'actions/artifacts/201':json.dumps(meta).encode(),'actions/artifacts/201/zip':raw})
        self.mixed_payload=payload;self.native_document=document;self.prior_meta=meta
        self.seal_mixed()
        receipt=dict(repository_id='1416489937',repository='haji84/RACE-AI',run_id='99',head_sha=M2_HEAD,
            artifact_id=103,created_at=self.f.metas[103]['created_at'],payload_sha256=digest(payload),independently_verified=True)
        self.f.view=engine.project_round(payload,receipt)
        self.f.cutoffs={r['race_id']:datetime.fromisoformat(r['cutoff_at'].replace('Z','+00:00')) for r in self.f.view['records']}
        self.assertGreater(payload['summary']['reused_baseline_forecasts'],0)

    def seal_mixed(self):
        from race_ai import boat_all_model_store as store
        self.f.add(103,'boat-all-model-forecasts-99-r1',None,
            M.zipped(store.seal_forecasts(self.mixed_payload,run_id='99',round_no=1,key=KEY)),
            '2030-04-01T09:00:20Z')

    def two_native_rounds(self,*,initial_model=True):
        """A completed second native round does not attest ALL_MODEL issuance."""
        from race_ai.repeated_cycle import artifact_name
        document=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[],
            additional_official_feature_shadows=[],observed_pairwise_p1_bundles=[],candidate_attempts=[],
            all_model_collection=dict(state='PREPARED_RUNTIME_ADMITTED'))
        self.f.add(104,artifact_name('boat-national-cutoff',99,2),'P1',packed({'national.json':json.dumps(document)}),
                   '2030-04-01T09:02:10Z')
        state=dict(self.f.state,requests_used=21,lifetime_requests=109,completed_round=1,prepared_round=2,
                   lifetime_completed_rounds=8)
        report=dict(self.f.report,round_no=2,first_forecast_artifacts=[self.f.metas[104]],
                    bounded_repeat_session=state,updated_at='2030-04-01T09:03:10Z')
        report['report_sha256']=digest({k:v for k,v in report.items() if k!='report_sha256'})
        self.f.add(105,artifact_name('race-existing-cycle',99,2),'RESULT',packed({'status.json':json.dumps(report),
            'official-result-observations.json':'[]','current-p1-original.zip':self.f.raws[104]}),'2030-04-01T09:03:20Z')
        self.f.job['steps'][1].update(status='completed',conclusion='success',completed_at='2030-04-01T09:04:00Z')
        self.f.run['updated_at']='2030-04-01T09:04:30Z'
        if initial_model:
            from race_ai import boat_all_model_store as store
            payload=deepcopy(M.ModelRecoveryTests.empty_payload)
            payload.update(stage='P0',run_id='99',source_code_commit=M2_HEAD,generated_at='2030-04-01T01:39:00Z',
                as_of='2030-04-01T01:39:00Z',dispatch_reports=[],native_input_capsules=[],current_inputs=[],
                baseline=None,summary=dict(contexts=0,generated_forecasts=0,reused_baseline_forecasts=0))
            payload['runtime_provenance']['source_code_commit']=M2_HEAD
            self.f.add(106,'boat-all-model-forecasts-99-r0',None,
                M.zipped(store.seal_forecasts(payload,run_id='99',round_no=0,key=KEY)),'2030-04-01T01:39:01Z')

    def test_two_native_rounds_with_only_r0_r1_models_authenticate_all_receipts_and_hold_unknown_r2(self):
        self.two_native_rounds();before=deepcopy((self.f.raws,self.f.metas,self.f.report,self.f.run,self.f.job,self.f.view))
        for missing_program in (False,True):
            out=self.audit(missing_program=missing_program);proof=out['all_model_zip_readback']
            self.assertEqual(out['completed_rounds_audited'],[1,2])
            self.assertEqual(proof['active_completed_round_scope'],[0,1])
            self.assertEqual(proof['missing_all_model_rounds'],[2])
            self.assertEqual(proof['excluded_all_model_rounds'],[])
            self.assertEqual(proof['status'],'HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
            self.assertEqual(proof['cutoff_qualification_blocker'],
                'OFFICIAL_PROGRAM_SOURCE_UNAVAILABLE' if missing_program else 'ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
            self.assertEqual(proof['official_program_source_authenticated'],not missing_program)
            unknown=next(row for row in proof['all_model_round_coverage'] if row['round']==2)
            self.assertEqual(unknown['state'],'ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
            self.assertIsNone(unknown['generated_forecasts'])
            self.assertEqual(proof['actual_listed_archives'],2)
            self.assertEqual(out['raw_aes_archives_verified'],7)
            self.assertEqual(out['status'],'HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
            for field in ('physical_pre_cutoff_distinct_model_slots','official_schedule_crosschecked_pre_cutoff_model_slots'):
                self.assertEqual(proof[field],0)
            for field in ('full_day_coverage','successor_dispatch_allowed','latest_live_counters_audited','official_cutoff_qualification'):
                self.assertIs(out[field],False)
            for ident in (104,105):self.assertIn(f'actions/artifacts/{ident}/zip',self.f.calls)
            self.assertNotIn('PRIVATE_',json.dumps(out));self.assertNotIn('ordered_top8',json.dumps(out))
        self.assertEqual((self.f.raws,self.f.metas,self.f.report,self.f.run,self.f.job,self.f.view),before)

    def test_missing_model_scope_cannot_shorten_native_prefix_hide_present_archives_or_forge_exclusions(self):
        self.two_native_rounds()
        from race_ai.actions_contract import digest
        listing=list(self.f.metas.values());reads=active._Reads(self.f.get)
        scope=dict(schema=active.SCHEMA,run=self.f.run,job=self.f.job,rounds=[1,2],inventory=listing,
            inventory_sha256=digest(listing),captured_at=NOW.isoformat(),expected_owner_sha=M2_HEAD,
            allow_completed_receipts=False,final_control=None,
            all_model_archive_scope=dict(present_rounds=[0,1],missing_rounds=[2],excluded_rounds=[]))
        self.assertEqual(active.validate_active_scope(scope,self.f.run,listing,NOW,reads,expected_owner_sha=M2_HEAD),[0,1])
        for field,value in (('present_rounds',[0]),('present_rounds',[False,True]),('missing_rounds',[]),('excluded_rounds',[1])):
            changed=deepcopy(scope);changed['all_model_archive_scope'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                active.validate_active_scope(changed,self.f.run,listing,NOW,reads,expected_owner_sha=M2_HEAD)
        changed=dict(scope,rounds=[1])
        with self.assertRaises(ValueError):active.validate_active_scope(changed,self.f.run,listing,NOW,reads,expected_owner_sha=M2_HEAD)

    def test_present_model_and_every_selected_native_receipt_stay_mandatory_despite_other_model_gap(self):
        self.two_native_rounds()
        for case in ('all_missing_transport','all_corrupt','all_expired','all_key','p1_missing','result_missing','nested_corrupt'):
            before=deepcopy((self.f.raws,self.f.metas));get=self.f.get
            if case=='all_missing_transport':
                def get(path):
                    if path=='actions/artifacts/103/zip':raise ValueError('GITHUB_API_READ_HTTP_404_HALT')
                    return self.f.get(path)
            elif case=='all_corrupt':self.f.raws[103]+=b'changed'
            elif case=='all_expired':self.f.metas[103]['expired']=True
            elif case=='all_key':
                from race_ai import boat_all_model_store as store
                with __import__('zipfile').ZipFile(__import__('io').BytesIO(self.f.raws[103])) as z:
                    payload=store.open_forecasts(z.read('forecasts.enc'),key=KEY)
                self.f.add(103,'boat-all-model-forecasts-99-r1',None,M.zipped(store.seal_forecasts(payload,run_id='99',
                    round_no=1,key=bytes(reversed(range(32))))),'2030-04-01T09:00:20Z')
            elif case=='p1_missing':self.f.metas.pop(104)
            elif case=='result_missing':self.f.metas.pop(105)
            else:self.f.raws[105]+=b'changed'
            with self.subTest(case=case),self.assertRaises(ValueError):self.audit(get=get,missing_program=True)
            self.f.raws,self.f.metas=before

    def test_zero_present_model_archives_are_unknown_not_zero_generation_or_a_reader_success(self):
        self.two_native_rounds(initial_model=False);self.f.metas.pop(103)
        out=self.audit(missing_program=True);proof=out['all_model_zip_readback']
        self.assertEqual(out['completed_rounds_audited'],[1,2]);self.assertEqual(proof['missing_all_model_rounds'],[1,2])
        self.assertEqual(proof['actual_listed_archives'],0);self.assertEqual(out['raw_aes_archives_verified'],5)
        self.assertEqual(proof['status'],'HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')
        self.assertTrue(all(row['generated_forecasts'] is None for row in proof['all_model_round_coverage']))

    def test_native_round_without_its_model_archive_is_not_counted_twice_when_later_packet_reuses_it(self):
        # The readback protocol permits an authenticated prior-native receipt.
        # Generation normally passes its current P1; this tests the accounting
        # boundary for a supported older receipt, without assuming live usage.
        from race_ai import boat_all_model_cycle as engine,boat_all_model_store as store
        self.mixed_baseline();self.two_native_rounds()
        self.f.add(101,'boat-national-cutoff-99','P1',packed({'national.json':json.dumps(self.native_document)}),
                   '2030-04-01T09:00:01Z')
        self.f.report['first_forecast_artifacts']=[self.f.metas[101]];self.f.result()
        self.mixed_payload['baseline']['receipt'].update(run_id='99',head_sha=M2_HEAD,artifact_id=101)
        self.f.add(103,'boat-all-model-forecasts-99-r2',None,
            M.zipped(store.seal_forecasts(self.mixed_payload,run_id='99',round_no=2,key=KEY)),
            '2030-04-01T09:03:30Z')
        receipt=dict(repository_id='1416489937',repository='haji84/RACE-AI',run_id='99',head_sha=M2_HEAD,
            artifact_id=103,created_at=self.f.metas[103]['created_at'],payload_sha256=digest(self.mixed_payload),independently_verified=True)
        self.f.view=engine.project_round(self.mixed_payload,receipt)
        out=self.audit(missing_program=True);proof=out['all_model_zip_readback']
        self.assertEqual(out['completed_rounds_audited'],[1,2]);self.assertEqual(proof['missing_all_model_rounds'],[1])
        self.assertEqual(proof['additional_native_p1_archives_verified'],0)
        self.assertEqual(out['raw_aes_archives_verified'],7)

    def test_crypto_old_eff_baseline_is_verified_but_never_counted_as_new_m2_output(self):
        self.mixed_baseline();before=deepcopy((self.f.raws,self.f.extra,self.mixed_payload,self.f.view))
        out=self.audit(missing_program=True);proof=out['all_model_zip_readback']
        self.assertEqual(proof['referenced_existing_baseline_p1_rows_not_recounted'],
                         self.mixed_payload['summary']['reused_baseline_forecasts'])
        self.assertEqual(proof['p1_forecast_rows_reopened'],self.mixed_payload['summary']['generated_forecasts'])
        self.assertEqual(proof['additional_native_p1_archives_verified'],1)
        self.assertEqual(out['raw_aes_archives_verified'],5)
        self.assertIn('actions/artifacts/201/zip',self.f.calls)
        self.assertEqual(proof['physical_pre_cutoff_distinct_model_slots'],0)
        self.assertEqual(proof['official_schedule_crosschecked_pre_cutoff_model_slots'],0)
        self.assertEqual((self.f.raws,self.f.extra,self.mixed_payload,self.f.view),before)

    def test_crypto_old_baseline_wrong_key_hash_head_id_run_clock_day_and_class_source_refuse(self):
        self.mixed_baseline()
        for case in ('key','hash','head','id','run','clock','document','day','class_source','native_context','unknown_slot','status'):
            before=deepcopy((self.f.raws,self.f.metas,self.f.extra,self.mixed_payload))
            if case=='key':
                raw=packed({'private-original.enc':seal_original_zip(packed({'national.json':json.dumps(self.native_document)}),
                    run_id=88,head_sha=active.OWNER_SHA,kind='P1',key=bytes(reversed(range(32))))})
                meta=dict(self.prior_meta,digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
                self.f.extra['actions/artifacts/201/zip']=raw
                self.f.extra['actions/artifacts/201']=json.dumps(meta).encode()
                self.f.extra['actions/runs/88/artifacts?per_page=100']=json.dumps(dict(total_count=1,artifacts=[meta])).encode()
            elif case=='hash':self.f.extra['actions/artifacts/201/zip']+=b'changed'
            elif case=='head':self.mixed_payload['baseline']['receipt']['head_sha']='f'*40
            elif case=='id':
                self.mixed_payload['baseline']['receipt']['artifact_id']=999
                self.f.extra['actions/artifacts/999']=json.dumps(dict(self.prior_meta,id=999)).encode()
            elif case=='run':self.mixed_payload['baseline']['receipt']['run_id']='87'
            elif case=='clock':self.mixed_payload['baseline']['receipt']['created_at']='2030-04-01T09:00:02Z'
            elif case=='document':self.mixed_payload['baseline']['document_sha256']='f'*64
            elif case=='day':
                origin=json.loads(self.f.extra['actions/runs/88']);origin['created_at']='2030-04-02T01:00:00Z'
                self.f.extra['actions/runs/88']=json.dumps(origin).encode()
            elif case=='class_source':self.mixed_payload['runtime_provenance']['source_code_commit']=active.OWNER_SHA
            elif case=='status':
                origin=json.loads(self.f.extra['actions/runs/88']);origin.update(status='completed',conclusion='cancelled')
                self.f.extra['actions/runs/88']=json.dumps(origin).encode()
            else:
                report=self.mixed_payload['dispatch_reports'][0]
                slot=next(slot for slot in report['slots'] if slot['status']=='ORIGINAL_REUSED')
                original=next(item for item in report['retained_originals'] if
                    all(item.get(k)==slot.get(k) for k in ('race_id','model_id','model_version')))
                for item in (slot,original):
                    if case=='native_context':item['native_context']['unknown']='FORGED'
                    else:item['unknown']='FORGED'
            self.seal_mixed()
            with self.subTest(case=case),self.assertRaises(ValueError):self.audit(missing_program=True)
            self.f.raws,self.f.metas,self.f.extra,self.mixed_payload=before

    def test_authenticated_reference_cannot_exempt_a_changed_body_or_current_output_source(self):
        from collections import Counter
        from scripts import boat_exact_all_model_zip_readback as exact
        from race_ai import boat_all_model_recovery as recovery
        self.mixed_baseline()
        verified,_=exact._verified_reused_baseline(self.f.get,recovery._MetadataReader(self.f.get),
            self.mixed_payload,self.f.view,self.f.run,saved_at=self.f.metas[103]['created_at'],now=NOW,key=KEY,day=DAY)
        models={p['model_id'] for row in self.f.view['records'] for p in
                [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None}
        for case in ('own_source','reference_body','reference_receipt'):
            projection=deepcopy(self.f.view)
            for row in projection['records']:
                predictions=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]
                p=next(p for p in predictions if (p['artifact_id']==103)==(case=='own_source'))
                if case=='own_source':p['source_code_commit']=active.OWNER_SHA
                elif case=='reference_body':p['unknown']='FORGED'
                else:p['receipt_run_id']='87'
                break
            for qualified in (False,True):
                kwargs=dict(projection=projection,day=DAY,artifact_id=103,physical_saved_at=self.f.metas[103]['created_at'],
                    expected=models,source_original_index=Counter(),expected_owner_sha=M2_HEAD,verified_reused_predictions=verified)
                if qualified:kwargs.update(clock=NOW,official_cutoffs=self.f.cutoffs)
                with self.subTest(case=case,qualified=qualified),self.assertRaises(ValueError):
                    (exact._scan if qualified else exact._scan_unqualified_originals)(**kwargs)

    def test_current_selected_native_p1_reference_is_authenticated_without_double_counting_archive(self):
        from race_ai import boat_all_model_cycle as engine
        self.mixed_baseline()
        self.f.add(101,'boat-national-cutoff-99','P1',packed({'national.json':json.dumps(self.native_document)}),
                   '2030-04-01T09:00:01Z')
        self.f.report['first_forecast_artifacts']=[self.f.metas[101]];self.f.result()
        self.mixed_payload['baseline']['receipt'].update(run_id='99',head_sha=M2_HEAD,artifact_id=101)
        self.seal_mixed()
        receipt=dict(repository_id='1416489937',repository='haji84/RACE-AI',run_id='99',head_sha=M2_HEAD,
            artifact_id=103,created_at=self.f.metas[103]['created_at'],payload_sha256=digest(self.mixed_payload),independently_verified=True)
        self.f.view=engine.project_round(self.mixed_payload,receipt)
        out=self.audit(missing_program=True)
        self.assertEqual(out['raw_aes_archives_verified'],4)
        self.assertEqual(out['all_model_zip_readback']['referenced_native_p1_archives_independently_verified'],1)
        self.assertEqual(out['all_model_zip_readback']['additional_native_p1_archives_verified'],0)

    def complete(self,*,completed_round=1,prepared_round=None):
        from race_ai import boat_source_control as control
        state=deepcopy(self.f.state)
        state.update(schema='RACE_AI_CONTINUOUS_REPEAT_V2',completed_round=completed_round,
            prepared_round=prepared_round,lifetime_completed_rounds=7+completed_round)
        state['session_sha256']=digest(state)
        cipher=seal_original_zip(packed({'repeat-session.json':json.dumps(state)}),
                                 run_id=99,head_sha=M2_HEAD,kind='CONTINUITY',key=KEY)
        self.summary=control.build_summary(cipher,run_id=99,head_sha=M2_HEAD,key=KEY)
        self.f.add(110,'race-cycle-continuity-99',None,packed({'private-original.enc':cipher}),
                   '2030-04-01T09:03:00Z')
        self.f.add(111,'race-source-control-99',None,packed({'source-control.json':json.dumps(self.summary)}),
                   '2030-04-01T09:03:01Z')
        self.f.run.update(status='completed',conclusion='success',updated_at='2030-04-01T09:04:00Z')
        self.f.job.update(status='completed',conclusion='success')
        self.f.job['steps']=self.f.job['steps'][:1]+[
            dict(name=f'Deadline-ordered five-model round {number:02}',status='completed',conclusion='success',
                 started_at='2030-04-01T09:02:01Z',completed_at='2030-04-01T09:02:02Z') for number in range(2,25)]

    def test_explicit_m2_authenticates_own_aes_and_keeps_missing_cutoffs_unqualified(self):
        out=self.audit(missing_program=True)
        self.assertEqual(out['owner_source_commit'],M2_HEAD)
        self.assertEqual(out['completed_rounds_audited'],[1])
        self.assertEqual(out['raw_aes_archives_verified'],4)
        self.assertFalse(out['official_cutoff_qualification'])
        self.assertIsNone(out['all_model_zip_readback']['authentic_official_P0_schedule_races'])
        self.assertEqual(out['round_evidence'][0]['sealed_precompletion_counters'],self.f.state)
        self.assertGreater(out['all_model_zip_readback']['original_predictions_matched_saved_AES_view'],0)
        for field in ('full_day_coverage','successor_dispatch_allowed','latest_live_counters_audited'):
            self.assertIs(out[field],False)

    def test_m2_requires_explicit_source_and_refuses_arbitrary_or_dynamic_source(self):
        with self.assertRaises(ValueError):self.f.audit()
        for source in (HEAD[:39]+'f', 'production/boat-p0-p1-20261111', 'refs/heads/main', None):
            with self.subTest(source=source),self.assertRaises(ValueError):
                self.f.audit(expected_owner_sha=source)
        self.f.run['head_sha']='f'*40
        with self.assertRaises(ValueError):self.audit()

    def test_m2_key_receipt_nested_counter_and_cipher_mismatches_stay_fatal(self):
        for case in ('key','receipt','nested','counter','cipher','report_source','job_source'):
            before=deepcopy((self.f.raws,self.f.metas,self.f.report,self.f.job))
            if case=='receipt':self.f.metas[103]['workflow_run']['head_sha']='f'*40
            elif case=='nested':self.f.result(nested=b'changed')
            elif case=='counter':self.f.state['lifetime_requests']+=1;self.f.result()
            elif case=='cipher':self.f.raws[103]+=b'changed'
            elif case=='report_source':self.f.report['code_sha']='f'*40;self.f.result()
            elif case=='job_source':self.f.job['head_sha']='f'*40
            with self.subTest(case=case),patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(b'x'*32 if case=='key' else KEY).decode()),self.assertRaises(ValueError):
                self.audit(missing_program=True)
            self.f.raws,self.f.metas,self.f.report,self.f.job=before
            self.f.state=self.f.report['bounded_repeat_session']

    def test_m2_inherits_exact_old_p0_registry_without_reissuing_it(self):
        original=self.f.audit
        self.f.audit=lambda *args,**kwargs: original(*args,expected_owner_sha=M2_HEAD,**kwargs)
        self.f.test_inherited_p0_is_resolved_from_exact_registry_without_relabeling_active_run()

    def test_completed_m2_uses_authenticated_final_round_not_twenty_four_success_labels(self):
        self.complete()
        out=self.audit(missing_program=True,allow_completed_receipts=True)
        self.assertEqual(out['completed_rounds_audited'],[1])
        self.assertEqual(out['owner_status_at_snapshot'],'completed')
        self.assertEqual(out['status'],'COMPLETED_OWNER_RECEIPTS_AES_VERIFIED_PARTIAL_SCOPE')
        self.assertEqual(out['final_control']['completed_round'],1)
        self.assertTrue(out['final_control_aes_authenticated'])
        self.assertEqual(out['successful_round_steps_excluded'],list(range(2,25)))
        self.assertEqual(out['raw_aes_archives_verified'],5)
        for field in ('full_day_coverage','successor_dispatch_allowed','latest_live_counters_audited','official_cutoff_qualification'):
            self.assertIs(out[field],False)
        with self.assertRaises(ValueError):self.audit(missing_program=True)

    def test_completed_m2_selected_prefix_and_final_public_control_are_mandatory(self):
        for case in ('missing_selected','missing_control','wrong_control_source','tamper_public','tamper_cipher','expired_control','counter','missing_step'):
            before=deepcopy((self.f.raws,self.f.metas,self.f.run,self.f.job,self.f.report))
            self.complete(completed_round=2 if case=='missing_selected' else 1)
            if case=='missing_control':self.f.metas.pop(110)
            elif case=='wrong_control_source':self.f.metas[110]['workflow_run']['head_sha']='f'*40
            elif case=='tamper_public':
                self.summary['control']['lifetime_requests']+=1
                self.f.add(111,'race-source-control-99',None,packed({'source-control.json':json.dumps(self.summary)}),'2030-04-01T09:03:01Z')
            elif case=='tamper_cipher':self.f.raws[110]+=b'changed'
            elif case=='expired_control':self.f.metas[110]['expired']=True
            elif case=='counter':self.f.state['requests_used']+=1;self.f.state['lifetime_requests']+=1;self.f.result()
            elif case=='missing_step':self.f.job['steps']=self.f.job['steps'][1:]
            with self.subTest(case=case),self.assertRaises(ValueError):
                self.audit(missing_program=True,allow_completed_receipts=True)
            self.f.raws,self.f.metas,self.f.run,self.f.job,self.f.report=before
            self.f.state=self.f.report['bounded_repeat_session']

    def test_completed_partial_scope_cannot_enter_default_exact_or_old_owner_scope(self):
        self.complete()
        from scripts import boat_exact_all_model_zip_readback as exact
        with self.assertRaises(ValueError):
            exact.audit(get=self.f.get,repo='unused',run_id=99,day=DAY,expected_models=['boat-model-A'],
                        original_view=self.f.view,now=NOW,owner_key=KEY)
        with self.assertRaises(ValueError):self.f.audit(allow_completed_receipts=True)
        # Official-B availability cannot bypass the M2 final-control scope.
        with patch.object(exact,'_official_cutoffs',return_value=self.f.cutoffs) as cutoffs:
            with self.assertRaises(ValueError):
                exact.audit(get=self.f.get,repo='unused',run_id=99,day=DAY,expected_models=['boat-model-A'],
                            original_view=self.f.view,now=NOW,owner_key=KEY,expected_owner_sha=M2_HEAD)
            cutoffs.assert_not_called()

    def test_completed_scope_excludes_extra_unfinished_archives_and_keeps_missing_model_unknown(self):
        self.complete()
        self.f.metas[104]=dict(self.f.metas[103],id=104,name='boat-all-model-forecasts-99-r2')
        self.f.raws[104]=b'corrupt unfinished extra is never selected'
        out=self.audit(missing_program=True,allow_completed_receipts=True)
        self.assertEqual(out['all_model_zip_readback']['actual_listed_archives'],1)
        self.assertEqual(out['all_model_zip_readback']['excluded_all_model_rounds'],[2])
        self.assertNotIn('actions/artifacts/104/zip',self.f.calls)
        self.f.metas.pop(103)
        held=self.audit(missing_program=True,allow_completed_receipts=True)
        self.assertEqual(held['missing_all_model_rounds'],[1])
        self.assertEqual(held['status'],'HOLD_ALL_MODEL_ARCHIVE_ABSENT_UNEXPLAINED')

    def test_snapshot_run_and_final_job_status_must_be_truthful(self):
        for status,conclusion in (('queued',None),('in_progress','failure'),('completed',None),('completed','cancelled')):
            before=deepcopy(self.f.run);self.f.run.update(status=status,conclusion=conclusion)
            with self.subTest(status=status,conclusion=conclusion),self.assertRaises(ValueError):self.audit()
            self.f.run=before
        self.complete();self.f.job['status']='in_progress'
        with self.assertRaises(ValueError):self.audit(missing_program=True,allow_completed_receipts=True)


class M2TargetSelectionTests(unittest.TestCase):
    def event(self,source=M2_HEAD):
        return dict(repository={'full_name':'haji84/RACE-AI'},workflow_run=dict(id=123,head_sha=source,
            head_branch=active.BRANCH,event='workflow_dispatch',status='completed',conclusion='success',
            head_repository={'full_name':'haji84/RACE-AI'}))

    def test_actual_completion_event_and_explicit_main_target_are_source_fixed(self):
        out=active.select_audit_target('workflow_run',self.event())
        self.assertEqual(out,dict(run_id=123,expected_owner_sha=M2_HEAD,allow_completed_receipts=True))
        push=dict(ref='refs/heads/main',repository={'full_name':'haji84/RACE-AI'})
        target=dict(schema='RACE_AI_M2_READONLY_AUDIT_TARGET_V1',run_id=456,source_commit=M2_HEAD)
        self.assertEqual(active.select_audit_target('push',push,main_target=target),
                         dict(run_id=456,expected_owner_sha=M2_HEAD,allow_completed_receipts=True))
        old=active.select_audit_target('push',push)
        self.assertEqual(old,dict(run_id=44019591352,expected_owner_sha=active.OWNER_SHA,allow_completed_receipts=False))
        callback=active.select_audit_target('workflow_run',self.event(active.OWNER_SHA))
        self.assertEqual(callback['run_id'],123);self.assertFalse(callback['allow_completed_receipts'])

    def test_untrusted_event_dynamic_head_or_config_never_selects_an_owner(self):
        push=dict(ref='refs/heads/main',repository={'full_name':'haji84/RACE-AI'})
        target=dict(schema='RACE_AI_M2_READONLY_AUDIT_TARGET_V1',run_id=456,source_commit=M2_HEAD)
        for change in (dict(source_commit='f'*40),dict(source_commit='production/boat-p0-p1-20261111'),
                       dict(run_id=True),dict(run_id=0),dict(source_commit=active.OWNER_SHA),dict(extra='unknown')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                active.select_audit_target('push',push,main_target=dict(target,**change))
        for field,value in (('head_sha','f'*40),('head_branch','main'),('event','push'),('id',True),
                            ('status','in_progress'),('conclusion','cancelled'),
                            ('head_repository',{'full_name':'attacker/fork'})):
            event=self.event();event['workflow_run'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):active.select_audit_target('workflow_run',event)
        with self.assertRaises(ValueError):active.select_audit_target('pull_request',self.event())
        with self.assertRaises(ValueError):active.select_audit_target('push',dict(push,ref='refs/heads/other'))

    def test_workflow_keeps_eff_historical_reader_then_checks_exact_selected_parser_pins(self):
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        live=text.split('\n  authenticated_original_matrix:\n',1)[1]
        self.assertLess(live.index('PY_CHECKPOINT'),live.index('id: audit_target'))
        self.assertLess(live.index('id: audit_target'),live.index('ref: ${{ steps.audit_target.outputs.expected_owner_sha }}'))
        self.assertIn('clean: false',live)
        self.assertIn("audit/state/boat-m2-independent-audit-target.json",live)
        self.assertIn("subprocess.check_output(['git','-C',str(target.parent),'rev-parse','HEAD']",live)
        self.assertIn('allow_completed_receipts=',live)
        self.assertIn(M2_HEAD,live)


if __name__=='__main__':unittest.main()
