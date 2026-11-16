"""Independent matrix scope uses actual reopened AES originals, never view flags."""
from copy import deepcopy
from datetime import timedelta
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
OWNER=Path(os.environ.get('RACE_AI_TEST_OWNER_SOURCE',ROOT/'owner-source'))
if str(OWNER) not in sys.path:sys.path.insert(0,str(OWNER))
import race_ai
for folder in (OWNER/'race_ai',OWNER/'pr64-reference/race_ai',OWNER/'pr72-reference/race_ai'):
    if str(folder) not in race_ai.__path__:race_ai.__path__.append(str(folder))
import tests
if str(OWNER/'tests') not in tests.__path__:tests.__path__.append(str(OWNER/'tests'))
import scripts
if str(OWNER/'scripts') not in scripts.__path__:scripts.__path__.append(str(OWNER/'scripts'))
from scripts import boat_owner_evidence_audit as audit
from scripts import boat_owner_national_p1_matrix as matrix
from tests import test_boat_all_model_recovery as fixture
from race_ai.actions_contract import digest
from race_ai.saved_view_feed import forecast_inventory


class MatrixReadbackScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ModelRecoveryTests.setUpClass()

    def setUp(self):
        self.assertTrue(callable(getattr(audit,'reopen_matrix_view',None)),
                        'whole-view matrix needs a fresh all-lineage AES reader')
        self.assertTrue(callable(getattr(audit,'matrix_readback_scope',None)))
        self.assertTrue(callable(getattr(matrix,'vault_complete',None)))
        self.case=fixture.ModelRecoveryTests();self.case.setUp()

    def example(self,*,two_owners=False):
        from race_ai import boat_all_model_store as store,boat_all_model_cycle as engine
        first=self.case.artifact(101,1)
        view=engine.project_round(first[0],fixture.receipt(first[0],artifact=101,saved=first[2]['created_at']))
        get=self.case.transport(first)
        if two_owners:
            second=deepcopy(self.case.payload);second['run_id']='43'
            # Separate issuance for the same race is enough to exercise owner
            # lineage. Preserve the genuine model outputs and source inputs.
            raw=fixture.zipped(store.seal_forecasts(second,run_id='43',round_no=1,key=fixture.KEY))
            meta=deepcopy(first[2]);meta.update(id=102,name='boat-all-model-forecasts-43-r1',
                digest='sha256:'+fixture.sha256(raw).hexdigest(),size_in_bytes=len(raw))
            meta['workflow_run']['id']=43
            second_receipt=dict(fixture.receipt(second,artifact=102,saved=meta['created_at']),run_id='43')
            other=engine.project_round(second,second_receipt)
            from race_ai.boat_saved_view_intake import append_views
            view=append_views(view,[other])
            get.bodies['actions/runs/43']=fixture.wire(fixture.api_run(43))
            get.bodies['actions/runs/43/artifacts?per_page=100']=fixture.wire(dict(total_count=1,artifacts=[meta]))
            get.bodies['actions/artifacts/102']=fixture.wire(meta)
            get.bodies['actions/artifacts/102/zip']=raw
        mid=next(p['model_id'] for row in view['records']
                 for p in [row['prediction'],*row['comparison_predictions']]
                 if p['eligible_pre_cutoff'] is True)
        return view,get,mid

    def reopen(self,view,get):
        with patch.object(fixture.recovery,'_now',return_value=fixture.CLOCK):
            return audit.reopen_matrix_view(view,get,selected_owner=42,day=fixture.DAY,
                                            now=fixture.CLOCK,key=fixture.KEY)

    def coverage(self,view,mid,scope=None):
        # This scope fixture has one applicable catalog model. Other model
        # fixtures retain their independent input HOLDs and are not a 14/14 proof.
        subset=deepcopy(view)
        for row in subset['records']:
            keep=[p for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                  if p is not None and p['model_id']==mid]
            row.update(prediction=keep[0] if keep else None,comparison_predictions=keep[1:])
        return matrix.saved_view_coverage(subset,day=fixture.DAY,model_ids=[mid],
            scheduled_races=1,now=fixture.CLOCK,independent_scope=scope)

    def test_self_reported_other_owner_and_zero_reopened_never_prove_the_whole_view(self):
        view,_,mid=self.example(two_owners=True)
        counts=self.coverage(view,mid)
        self.assertEqual(counts['missing_p1_model_slots'],0)
        self.assertFalse(counts['independently_authenticated_source_zip_claim'])
        self.assertGreater(counts['independent_scope']['unreopened_qualified_originals'],0)
        self.assertFalse(matrix.vault_complete(counts,dict(status='SAVED_MODEL_RECOVERY_COMPLETE',
            deferred_artifacts=0,deferred_runs=0),dict(status='AUTHENTICATED_NATIVE_COVERAGE'),
            dict(source_owner_conclusion='success',observed_source_control={'prepared_round':None})))

    def test_workflow_completion_and_readback_flags_use_the_counted_original_scope(self):
        import ast,textwrap
        text=(ROOT/'.github/workflows/boat-owner-national-p1-matrix.yml').read_text()
        stage=text.split("python - <<'PY_ALL_MODEL'\n",1)[1].split('\n          PY_ALL_MODEL',1)[0]
        code=ast.parse(textwrap.dedent(stage))
        expression=next(n.value for n in ast.walk(code) if isinstance(n,ast.Assign)
                        and any(isinstance(t,ast.Name) and t.id=='complete' for t in n.targets))
        environment=dict(mod=matrix,counts=dict(status='SAVED_MODEL_RECOVERY_COMPLETE',archives_verified=0,
            deferred_artifacts=0,deferred_runs=0,unrepresented_scoped_forecasts=0),
            after=dict(missing_p1_model_slots=0,cutoff_conflicts=0,unsupported_or_extra_models=0,
                independently_authenticated_source_zip_claim=False,
                independent_scope={'whole_counted_scope_reopened':False}),
            native_counts=dict(status='AUTHENTICATED_NATIVE_COVERAGE'),
            baseline=dict(source_owner_conclusion='success',observed_source_control={'prepared_round':None}))
        self.assertFalse(eval(compile(ast.Expression(expression),'<workflow>','eval'),environment))
        output=next(n.value for n in ast.walk(code) if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=='out' for t in n.targets))
        readback=next(k.value for k in output.keywords if k.arg=='independent_readback')
        self.assertFalse(eval(compile(ast.Expression(readback),'<workflow>','eval'),environment))
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
            n.func.attr=='reopen_matrix_view' for n in ast.walk(code)))

    def test_every_owner_original_is_reopened_and_only_then_full_is_possible(self):
        view,get,mid=self.example(two_owners=True);before=deepcopy(view)
        output,recovery,readback=self.reopen(view,get)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        counts=self.coverage(output,mid,scope)
        self.assertEqual(scope['run_ids'],[42,43])
        self.assertEqual(scope['all_model_archives_reopened'],2)
        self.assertTrue(counts['independently_authenticated_source_zip_claim'])
        self.assertEqual(counts['independent_scope']['unreopened_qualified_originals'],0)
        self.assertTrue(matrix.vault_complete(counts,recovery,dict(status='AUTHENTICATED_NATIVE_COVERAGE'),
            dict(source_owner_conclusion='success',observed_source_control={'prepared_round':None})))
        self.assertEqual(view,before);self.assertEqual(forecast_inventory(output),forecast_inventory(view))
        self.assertTrue(all(f'actions/artifacts/{ident}/zip' in get.calls for ident in (101,102)))

    def test_selected_owner_scope_cannot_authenticate_another_owners_carried_original(self):
        view,get,mid=self.example(two_owners=True);own=deepcopy(view)
        for row in own['records']:
            keep=[p for p in [row['prediction'],*row['comparison_predictions']] if p['artifact_id']==101]
            row.update(prediction=keep[0],comparison_predictions=keep[1:])
        output,_,readback=self.reopen(own,get)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        self.assertEqual(scope['run_ids'],[42])
        counts=self.coverage(view,mid,scope)
        self.assertEqual(counts['missing_p1_model_slots'],0)
        self.assertFalse(counts['independently_authenticated_source_zip_claim'])
        self.assertEqual(counts['independent_scope']['unreopened_qualified_originals'],1)

    def test_retained_mac_cache_is_cleared_only_on_the_audit_copy_and_reopened(self):
        view,get,mid=self.example()
        with patch.object(fixture.recovery,'_now',return_value=fixture.CLOCK):
            cached,_=fixture.recovery.recover_saved_models(view,get,run_ids=[42],day=fixture.DAY,key=fixture.KEY)
        before=deepcopy(cached);get.calls=[]
        output,counts,readback=self.reopen(cached,get)
        self.assertEqual(counts['archives_verified'],1)
        self.assertEqual(counts['coverage_reused_artifacts'],0)
        self.assertIn('actions/artifacts/101/zip',get.calls)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        self.assertTrue(self.coverage(output,mid,scope)['independently_authenticated_source_zip_claim'])
        self.assertEqual(cached,before)
        self.assertEqual(forecast_inventory(output),forecast_inventory(cached))

    def test_readback_completion_clock_can_follow_the_audit_start_without_backdating(self):
        view,get,mid=self.example();finished=fixture.CLOCK+timedelta(seconds=5)
        with patch.object(fixture.recovery,'_now',return_value=finished):
            output,_,readback=audit.reopen_matrix_view(view,get,selected_owner=42,
                day=fixture.DAY,now=fixture.CLOCK,key=fixture.KEY)
        scope=audit.matrix_readback_scope(output,readback,now=finished)
        self.assertEqual(scope['checked_at'],finished.isoformat())
        self.assertTrue(matrix.saved_view_coverage(output,day=fixture.DAY,
            model_ids=sorted({p['model_id'] for r in output['records']
                for p in [r['prediction'],*r['comparison_predictions']]}),scheduled_races=1,
            now=finished,independent_scope=scope)['independently_authenticated_source_zip_claim'])

    def test_duplicate_hash_run_and_clock_conflicts_hold(self):
        for change in ('duplicate','zip','run','head','clock','artifact_before_run','saved_clock'):
            with self.subTest(change=change):
                view,get,_=self.example()
                if change=='duplicate':
                    row=deepcopy(get.rows[0])
                    get.bodies['actions/runs/42/artifacts?per_page=100']=fixture.wire(dict(total_count=2,artifacts=[row,row]))
                elif change=='zip':get.bodies['actions/artifacts/101/zip']+=b'tampered'
                elif change=='run':
                    value=fixture.api_run();value['repository']['id']=1
                    get.bodies['actions/runs/42']=fixture.wire(value)
                elif change=='head':
                    value=deepcopy(get.rows[0]);value['workflow_run']['head_sha']='b'*40
                    get.bodies['actions/artifacts/101']=fixture.wire(value)
                elif change=='clock':
                    value=fixture.api_run();value['updated_at']=(fixture.CLOCK+timedelta(seconds=1)).isoformat()
                    get.bodies['actions/runs/42']=fixture.wire(value)
                elif change=='artifact_before_run':
                    value=fixture.api_run();value['created_at']='2030-04-01T09:00:21Z'
                    value['updated_at']='2030-04-01T09:00:21Z'
                    get.bodies['actions/runs/42']=fixture.wire(value)
                else:
                    for row in view['records']:
                        for p in [row['prediction'],*row['comparison_predictions']]:
                            p['server_saved_at']='2030-04-01T08:59:00Z'
                with self.assertRaises(ValueError):
                    output,_,readback=self.reopen(view,get)
                    audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)

    def test_scope_cannot_be_reused_for_a_changed_prediction_or_without_its_readback_count(self):
        view,get,mid=self.example();output,_,readback=self.reopen(view,get)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        changed=deepcopy(output);changed['records'][0]['prediction']['scope_note']='changed body'
        self.assertFalse(self.coverage(changed,mid,scope)['independently_authenticated_source_zip_claim'])
        stale=deepcopy(scope);stale['archives_reopened']=0
        self.assertFalse(self.coverage(output,mid,stale)['independently_authenticated_source_zip_claim'])

    def test_conflicting_duplicate_identity_cannot_hide_behind_the_last_matching_body(self):
        view,get,mid=self.example();output,_,readback=self.reopen(view,get)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        changed=deepcopy(output);row=changed['records'][0]
        original=deepcopy(next(p for p in [row['prediction'],*row['comparison_predictions']] if p['model_id']==mid))
        row.update(prediction=dict(original,scope_note='conflicting same identity'),comparison_predictions=[original])
        self.assertFalse(self.coverage(changed,mid,scope)['independently_authenticated_source_zip_claim'])

    def test_scope_artifact_hash_owner_and_clock_contradictions_hold(self):
        view,get,mid=self.example();output,_,readback=self.reopen(view,get)
        scope=audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)
        for field,value in (('zip_sha256','bad'),('run_id',999),
                            ('created_at',(fixture.CLOCK+timedelta(seconds=1)).isoformat())):
            with self.subTest(field=field):
                changed=deepcopy(scope);changed['artifacts'][101][field]=value
                changed['scope_sha256']=digest({k:v for k,v in changed.items() if k!='scope_sha256'})
                self.assertFalse(self.coverage(output,mid,changed)['independently_authenticated_source_zip_claim'])

    def test_all_model_view_body_cannot_supply_its_own_unverified_fields(self):
        for field,value in (('input_sha256','f'*64),('output_sha256','f'*64),('source_sha256','f'*64),
                            ('scope_note','unverified'),('odds_independent',False),('missing_reasons',[])):
            with self.subTest(field=field):
                view,get,mid=self.example()
                target=next(p for row in view['records'] for p in [row['prediction'],*row['comparison_predictions']]
                            if p['model_id']==mid)
                if field=='missing_reasons':value=['UNVERIFIED_FIELD']
                target[field]=value
                with self.assertRaises(ValueError):
                    output,_,readback=self.reopen(view,get)
                    audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)

    def native_example(self):
        import io,zipfile
        from race_ai.boat_private_original_archive import seal_original_zip
        from race_ai import boat_saved_prediction_evidence as native
        from tests.test_boat_saved_prediction_evidence import original_view
        view,_,raw,meta=original_view('P1')
        cipher=seal_original_zip(raw,run_id=99,head_sha=fixture.HEAD,kind='P1',key=fixture.KEY)
        wrapper=io.BytesIO()
        with zipfile.ZipFile(wrapper,'w') as z:z.writestr('private-original.enc',cipher)
        raw=wrapper.getvalue()
        meta.update(size_in_bytes=len(raw),digest='sha256:'+fixture.sha256(raw).hexdigest(),
                    expires_at='2030-04-08T09:00:20Z')
        get=fixture.ActualResponses([],{})
        run=fixture.api_run(99);run.update(created_at='2030-04-01T08:00:00Z',updated_at='2030-04-01T08:12:00Z')
        get.bodies.update({'actions/runs/99':fixture.wire(run),
            'actions/runs/99/artifacts?per_page=100':fixture.wire(dict(total_count=1,artifacts=[meta])),
            'actions/artifacts/123':fixture.wire(meta),'actions/artifacts/123/zip':raw})
        return view,get

    def test_native_view_body_cannot_supply_its_own_unverified_fields(self):
        for field,value in (('input_sha256','f'*64),('output_sha256','f'*64),('source_sha256','f'*64),
                            ('scope_note','unverified'),('ordered_candidates',[])):
            with self.subTest(field=field):
                view,get=self.native_example();view['records'][0]['prediction'][field]=value
                with self.assertRaises(ValueError):
                    output,_,readback=self.reopen(view,get)
                    audit.matrix_readback_scope(output,readback,now=fixture.CLOCK)

    def test_genuine_enriched_native_projection_and_row_sidecars_remain_accepted(self):
        import base64,json
        from race_ai.frozen_day_cycle import read_p1
        from race_ai.boat_saved_view_intake import project_native_state
        from race_ai.boat_saved_prediction_evidence import _read_archive
        view,get=self.native_example();raw=get.bodies['actions/artifacts/123/zip']
        meta=json.loads(get.bodies['actions/artifacts/123'])
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(fixture.KEY).decode()}):
            document,rows=read_p1(raw,meta)
        _,_,wrapper=_read_archive(raw,meta,fixture.KEY)
        state=dict(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',day_jst=fixture.DAY,
            rows=rows,receipts=[meta],observations=[],complete=False)
        state['state_sha256']=digest(state)
        enriched=project_native_state(state,documents=[wrapper]);before=forecast_inventory(enriched)
        enriched['records'][0]['result']={'status':'pending'}
        enriched['records'][0]['saved_prediction_evidence']={}
        output,_,readback=self.reopen(enriched,get)
        self.assertEqual(forecast_inventory(output),before)
        self.assertEqual(forecast_inventory(enriched),before)
        self.assertEqual(len(readback['native_originals']),1)

    def test_native_original_is_separately_reopened_and_legacy_clock_hold_survives(self):
        from race_ai import boat_saved_prediction_evidence as native
        view,get=self.native_example();before=deepcopy(view)
        replayed,counts,readback=self.reopen(view,get)
        self.assertEqual(counts['archives_verified'],0)
        self.assertIn('actions/artifacts/123/zip',get.calls)
        self.assertEqual(len(readback['native_originals']),1)
        if not callable(getattr(native,'native_coverage_evidence',None)):
            scope=audit.matrix_readback_scope(replayed,readback,now=fixture.CLOCK)
            self.assertEqual(scope['inventory'],{})
        else:
            schedule=[dict(race_id=view['records'][0]['race_id'],cutoff_at=view['records'][0]['cutoff_at'],
                schedule_captured_at='2030-04-01T00:00:00Z',source_sha256='c'*64)]
            hydrated,counts=native.hydrate_prediction_evidence(replayed,readback['native_originals'],
                key=fixture.KEY,official_schedule=schedule,now=fixture.CLOCK)
            scope=audit.matrix_readback_scope(hydrated,readback,now=fixture.CLOCK)
            self.assertEqual(scope['native_archives_reopened'],1)
            self.assertEqual(counts['native_pre_cutoff_qualified'],2)
            self.assertEqual(counts['native_pre_cutoff_held'],5)
            mid=hydrated['records'][0]['prediction']['model_id']
            self.assertTrue(self.coverage(hydrated,mid,scope)['independently_authenticated_source_zip_claim'])
        self.assertEqual(view,before)
        self.assertEqual(forecast_inventory(replayed),forecast_inventory(view))


if __name__=='__main__':unittest.main()
