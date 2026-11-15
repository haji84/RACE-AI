"""Lost-round recovery from invented API bytes and genuine sealed model outputs."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_all_model_cycle as engine, boat_all_model_store as store
from race_ai.actions_contract import digest
from race_ai.saved_view_feed import forecast_inventory
from tests import test_boat_all_model_cycle as model_fixture
from tests.test_boat_all_model_cycle import HEAD, NOW, receipt, source_context

try:
    recovery=importlib.import_module('race_ai.boat_all_model_recovery')
except ModuleNotFoundError:
    recovery=None

KEY=bytes(range(32))
DAY='2030-04-01'
CLOCK=NOW+timedelta(minutes=1)


def wire(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def zipped(cipher,*,member='forecasts.enc'):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member,cipher)
    return out.getvalue()


def api_run(run=42):
    return dict(id=run,workflow_id=405276784,head_branch='feat/four-sport-forecast-audit-view-20261022',
        head_sha=HEAD,status='in_progress',created_at='2030-04-01T08:50:00Z',updated_at='2030-04-01T09:00:00Z',
        repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
        head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))


class ActualResponses:
    def __init__(self,rows,bodies,*,archived=False):
        self.calls=[];self.rows=deepcopy(rows);self.bodies=dict(bodies);self.archived=archived;self.restored=set()
        self.bodies['actions/runs/42']=wire(api_run())
        for page in range(1,max(1,(len(rows)+99)//100)+1):
            endpoint='actions/runs/42/artifacts?per_page=100'+('' if page==1 else f'&page={page}')
            self.bodies[endpoint]=wire(dict(total_count=len(rows),artifacts=rows[(page-1)*100:page*100]))

    def __call__(self,endpoint):
        self.calls.append(endpoint)
        raw=self.bodies[endpoint]
        if isinstance(raw,Exception):raise raw
        if endpoint.startswith('actions/artifacts/') and not endpoint.endswith('/zip'):
            self.restored.add(int(endpoint.rsplit('/',1)[1]))
        return raw

    def is_archived(self,ident):
        return self.archived and ident in self.restored


class ModelRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=model_fixture.AllModelCycleTests();fixture.setUp()
        try:
            runtime=fixture.runtime()
            cls.payload=engine.forecast_round([source_context()],runtime,now=NOW)
            cls.empty_payload=engine.forecast_round([source_context()],runtime,now=NOW.replace(hour=21))
        finally:fixture.doCleanups()

    def setUp(self):
        self.assertIsNotNone(recovery,'saved model artifact recovery is missing')

    def artifact(self,ident,round_no,*,payload=None,saved='2030-04-01T09:00:20Z',header_round=None,member='forecasts.enc'):
        value=deepcopy(self.payload if payload is None else payload)
        cipher=store.seal_forecasts(value,run_id='42',round_no=round_no if header_round is None else header_round,key=KEY)
        raw=zipped(cipher,member=member)
        meta=dict(id=ident,name=f'boat-all-model-forecasts-42-r{round_no}',expired=False,
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),created_at=saved,
            expires_at='2030-04-08T09:00:20Z',
            workflow_run=dict(id=42,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD))
        return value,raw,meta

    def transport(self,*artifacts,archived=False):
        rows=[];bodies={}
        for _,raw,meta in artifacts:
            ident=meta['id'];rows.append(deepcopy(meta))
            bodies[f'actions/artifacts/{ident}']=wire(meta);bodies[f'actions/artifacts/{ident}/zip']=raw
        return ActualResponses(rows,bodies,archived=archived)

    def base(self,*,known=None):
        output=engine.project_round(self.payload,receipt(self.payload,artifact=known or 102,saved='2030-04-01T09:00:20Z'))
        if known is None:
            for row in output['records']:row.update(prediction=None,comparison_predictions=[])
        return output

    def recover(self,view,get,**kwargs):
        with patch.object(recovery,'_now',return_value=kwargs.pop('now',CLOCK)):
            return recovery.recover_saved_models(view,get,run_ids=kwargs.pop('run_ids',[42]),key=kwargs.pop('key',KEY),**kwargs)

    def unrepresentable_payload(self):
        payload=deepcopy(self.payload);payload.pop('native_input_capsules')
        slot=next(slot for report in payload['dispatch_reports'] for slot in report['slots']
            if slot.get('prediction') and isinstance(slot['prediction'].get('candidates'),list)
            and isinstance(slot['prediction']['candidates'][0],dict))
        prediction=slot['prediction'];prediction['candidates'][0]['unsupported_fixture_attribute']=True
        seal=next(name for name in ('prediction_sha256','model_sha256','bundle_sha256','prediction_hash') if name in prediction)
        prediction[seal]=digest({name:value for name,value in prediction.items() if name!=seal})
        slot.update(prediction_sha256=prediction[seal],output_sha256=digest(prediction))
        return payload

    def nearly_full_history_row(self):
        from race_ai import saved_view_history as history
        from race_ai.saved_view_feed import forecast_anchor
        base=self.base(known=102);row=base['records'][0]
        small=deepcopy(row);small.update(race_id='20300401-01-02',race_no=2,prediction=None,comparison_predictions=[])
        base['records'].append(small);row['review_padding']=''
        head={name:value for name,value in base.items() if name!='records'}
        head.update(event_date_jst=DAY,forecast_base_sha256=forecast_anchor(base))
        row['review_padding']='x'*(history.MAX_CHUNK_PLAIN-128-len(wire(dict(head,records=[])))-len(wire(row)))
        return base

    def test_lost_first_round_is_recovered_when_only_second_round_reached_the_view(self):
        first=self.artifact(101,1);second=self.artifact(102,2)
        base=self.base(known=102);before=deepcopy(base);old=forecast_inventory(base)
        get=self.transport(first,second)
        result,counts=self.recover(base,get)
        self.assertEqual(base,before)
        self.assertEqual(counts['archives_verified'],2);self.assertEqual(counts['already_projected_artifacts'],0)
        self.assertGreater(counts['appended_p1_forecasts'],0)
        self.assertTrue(all(forecast_inventory(result).get(k)==v for k,v in old.items()))
        restored=[p for row in result['records'] for p in [row['prediction'],*row['comparison_predictions']] if p and p.get('artifact_id')==101]
        self.assertTrue(restored)
        self.assertTrue(all(p['persisted_at']=='2030-04-01T09:00:20Z' and p['receipt_run_id']=='42' for p in restored))
        self.assertIn('actions/artifacts/102',get.calls)
        replay=self.transport(first,second)
        again,repeated=self.recover(result,replay)
        self.assertEqual(again,result);self.assertEqual(repeated['archives_verified'],0)
        self.assertEqual(repeated['appended_forecasts'],0)
        self.assertFalse(any(endpoint.startswith('actions/artifacts/') for endpoint in replay.calls))

    def test_late_saved_forecasts_stay_ineligible_and_results_remain_pending(self):
        item=self.artifact(101,1,saved='2030-04-01T12:00:20Z')
        result,counts=self.recover(self.base(),self.transport(item),now=NOW.replace(hour=22))
        predictions=[p for row in result['records'] for p in [row['prediction'],*row['comparison_predictions']] if p]
        self.assertTrue(predictions);self.assertTrue(all(p['eligible_pre_cutoff'] is False for p in predictions))
        self.assertTrue(all(row['result'] is None for row in result['records']))
        self.assertEqual(counts['appended_eligible_pre_cutoff_forecasts'],0)

    def test_active_run_clocks_are_checked_after_the_response_is_acquired(self):
        item=self.artifact(101,1,saved=(CLOCK+timedelta(seconds=2)).isoformat())
        get=self.transport(item);run=api_run();run['updated_at']=(CLOCK+timedelta(seconds=1)).isoformat()
        get.bodies['actions/runs/42']=wire(run);observed=[CLOCK]
        def current(endpoint):
            raw=get(endpoint);observed[0]+=timedelta(seconds=3);return raw
        with patch.object(recovery,'_now',side_effect=lambda:observed[0]):
            try:result,counts=recovery.recover_saved_models(self.base(),current,run_ids=[42],key=KEY)
            except ValueError as exc:self.fail('legitimate concurrent run update was treated as future: '+str(exc))
        self.assertGreater(counts['appended_p1_forecasts'],0)

    def test_empty_real_artifact_is_verified_without_claiming_or_skipping_a_prediction(self):
        item=self.artifact(101,1,payload=self.empty_payload,saved='2030-04-01T12:00:20Z')
        result,counts=self.recover(self.base(),self.transport(item),now=NOW.replace(hour=22))
        self.assertEqual(counts['archives_verified'],1);self.assertEqual(counts['empty_prediction_archives'],1)
        self.assertEqual(counts['appended_p1_forecasts'],0)
        _,again=self.recover(result,self.transport(item),now=NOW.replace(hour=22))
        self.assertEqual(again['archives_verified'],0);self.assertEqual(again['coverage_reused_artifacts'],1)
        self.assertEqual(again['already_projected_artifacts'],0)

    def test_archived_receipt_after_expiry_requires_an_explicit_post_restore_capability(self):
        item=self.artifact(101,1);old=deepcopy(item[2]);old['expired']=True
        get=self.transport(item,archived=True)
        get.bodies['actions/runs/42/artifacts?per_page=100']=wire(dict(total_count=1,artifacts=[old]))
        result,counts=self.recover(self.base(),get,now=NOW.replace(year=2031))
        self.assertGreater(counts['appended_forecasts'],0);self.assertEqual(counts['archived_artifacts'],1)
        self.assertIs(json.loads(get.bodies['actions/artifacts/101'])['expired'],False)
        self.assertIs(json.loads(get.bodies['actions/runs/42/artifacts?per_page=100'])['artifacts'][0]['expired'],True)
        class Proxy:
            def __init__(self,target):self.target=target
            def __call__(self,path):return self.target(path)
            def __getattr__(self,name):return lambda *_:True
        with self.assertRaises(ValueError):self.recover(self.base(),Proxy(self.transport(item)),now=NOW.replace(year=2031))

    def test_complete_second_page_is_enumerated_without_availability_inventory_hydration(self):
        item=self.artifact(101,1);get=self.transport(item)
        rows=[dict(id=1000+i,name='unrelated-public-source') for i in range(100)]+[item[2]]
        get=ActualResponses(rows,get.bodies)
        get.archived_artifact_pages=lambda _:self.fail('availability inventory hydrated unrelated ZIPs')
        _,counts=self.recover(self.base(),get)
        self.assertEqual(counts['archives_verified'],1)
        self.assertIn('actions/runs/42/artifacts?per_page=100&page=2',get.calls)

    def test_count_and_zip_byte_budgets_defer_before_metadata_can_hydrate_a_zip(self):
        first=self.artifact(101,1);second=self.artifact(102,2)
        for options in ({'max_artifacts':1},{'byte_limit':len(first[1])}):
            get=self.transport(first,second)
            context=patch.object(recovery,'MAX_TOTAL_ZIP_BYTES',options['byte_limit']) if 'byte_limit' in options else patch.object(recovery,'MAX_TOTAL_ZIP_BYTES',64*1024*1024)
            with context:
                _,counts=self.recover(self.base(),get,**{k:v for k,v in options.items() if k!='byte_limit'})
            self.assertEqual(counts['archives_verified'],1);self.assertEqual(counts['deferred_artifacts'],1)
            self.assertNotIn('actions/artifacts/102',get.calls);self.assertNotIn('actions/artifacts/102/zip',get.calls)

    def test_day_filter_is_applied_after_authenticating_the_whole_payload(self):
        item=self.artifact(101,1);base=self.base()
        result,counts=self.recover(base,self.transport(item),day='2030-04-02')
        self.assertEqual(result,base);self.assertEqual(counts['archives_verified'],1)
        self.assertEqual(counts['out_of_scope_records'],1);self.assertEqual(counts['appended_forecasts'],0)
        bad=deepcopy(self.payload);bad['native_input_capsules'][0]['capsule_sha256']='f'*64
        with self.assertRaises(ValueError):self.recover(base,self.transport(self.artifact(101,1,payload=bad)),day='2030-04-02')

    def test_hash_header_round_payload_head_and_run_provenance_mismatches_stop_atomically(self):
        for kind in ('digest','listed_size','head','run','round','member','payload_head'):
            item=self.artifact(101,1,header_round=2 if kind=='round' else None,member='wrong.enc' if kind=='member' else 'forecasts.enc')
            if kind=='payload_head':
                value=deepcopy(self.payload);value['source_code_commit']='b'*40;item=self.artifact(101,1,payload=value)
            get=self.transport(item);base=self.base();before=deepcopy(base)
            if kind=='digest':
                meta=deepcopy(item[2]);meta['digest']='sha256:'+'f'*64;get.bodies['actions/artifacts/101']=wire(meta)
            if kind=='listed_size':
                row=deepcopy(item[2]);row['size_in_bytes']+=1
                get.bodies['actions/runs/42/artifacts?per_page=100']=wire(dict(total_count=1,artifacts=[row]))
            if kind in ('head','run'):
                info=api_run();info['head_sha' if kind=='head' else 'workflow_id']='b'*40 if kind=='head' else 1
                get.bodies['actions/runs/42']=wire(info)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.recover(base,get)
            self.assertEqual(base,before)

    def test_403_is_not_retried_and_does_not_replace_any_existing_original(self):
        get=self.transport(self.artifact(101,1));get.bodies['actions/artifacts/101']=RuntimeError('GITHUB_API_READ_HTTP_403_HALT')
        base=self.base(known=102);before=deepcopy(base)
        with self.assertRaisesRegex(RuntimeError,'HTTP_403'):self.recover(base,get)
        self.assertEqual(get.calls.count('actions/artifacts/101'),1)
        self.assertNotIn('actions/artifacts/101/zip',get.calls);self.assertEqual(base,before)

    def test_a_physically_verified_same_original_with_conflicting_output_is_rejected(self):
        item=self.artifact(101,1);base=engine.project_round(item[0],receipt(item[0],artifact=101,saved=item[2]['created_at']))
        p=base['records'][0]['prediction']
        p['ordered_top8']=list(reversed(p['ordered_top8']));before=deepcopy(base)
        with self.assertRaises(ValueError):self.recover(base,self.transport(item))
        self.assertEqual(base,before)

    def test_one_existing_prediction_is_not_proof_that_its_whole_archive_was_imported(self):
        item=self.artifact(101,1)
        full=engine.project_round(item[0],receipt(item[0],artifact=101,saved=item[2]['created_at']))
        base=deepcopy(full);base['records'][0]['comparison_predictions']=[]
        first=deepcopy(base['records'][0]['prediction'])
        result,counts=self.recover(base,self.transport(item))
        self.assertEqual(forecast_inventory(result),forecast_inventory(full))
        self.assertEqual(result['records'][0]['prediction'],first)
        self.assertEqual(counts['appended_forecasts'],len(forecast_inventory(full))-1)
        self.assertEqual(counts['archives_verified'],1)

    def test_missing_covered_prediction_is_restored_instead_of_reported_complete(self):
        item=self.artifact(101,1);full,_=self.recover(self.base(),self.transport(item))
        expected=forecast_inventory(full);damaged=deepcopy(full);row=damaged['records'][0]
        row['prediction']=row['comparison_predictions'].pop(0)
        get=self.transport(item);result,counts=self.recover(damaged,get)
        self.assertEqual(forecast_inventory(result),expected)
        self.assertEqual(counts['archives_verified'],1);self.assertEqual(counts['appended_forecasts'],1)
        self.assertIn('actions/artifacts/101/zip',get.calls)

    def test_corrupt_attestation_or_changed_covered_original_holds_before_transport(self):
        item=self.artifact(101,1);complete,_=self.recover(self.base(),self.transport(item))
        self.assertTrue(any('saved_model_archive_evidence' in row for row in complete['records']),
                        'verified archive has no authenticated coverage')
        for kind in ('mac','day','output','extra'):
            broken=deepcopy(complete)
            anchor=next(row for row in broken['records'] if 'saved_model_archive_evidence' in row)
            evidence=anchor['saved_model_archive_evidence']['101']
            if kind=='mac':evidence['mac']='f'*64
            elif kind=='day':evidence['state']['day']='2030-04-02'
            elif kind=='output':anchor['prediction']['ordered_top8'].reverse()
            else:anchor['comparison_predictions'].append(dict(deepcopy(anchor['prediction']),variant='UNKNOWN_VARIANT'))
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.recover(broken,lambda _:self.fail('corrupt coverage used a transport fallback'))

    def test_verified_empty_prefix_does_not_starve_artifacts_after_the_first128(self):
        artifacts=[self.artifact(1000+i,i,payload=self.empty_payload,saved='2030-04-01T12:00:20Z') for i in range(129)]
        first,counts=self.recover(self.base(),self.transport(*artifacts),now=NOW.replace(hour=22))
        self.assertEqual(counts['archives_verified'],128);self.assertEqual(counts['deferred_artifacts'],1)
        get=self.transport(*artifacts)
        result,again=self.recover(first,get,now=NOW.replace(hour=22))
        self.assertEqual(again['archives_verified'],1);self.assertEqual(again['coverage_reused_artifacts'],128)
        self.assertEqual(again['deferred_artifacts'],0);self.assertEqual(again['appended_forecasts'],0)
        self.assertNotIn('actions/artifacts/1000',get.calls)
        self.assertIn('actions/artifacts/1128/zip',get.calls)
        self.assertTrue(any('saved_model_archive_evidence' in row for row in result['records']))

    def test_unrepresentable_saved_forecast_is_pending_rather_than_an_empty_complete_scope(self):
        item=self.artifact(101,1,payload=self.unrepresentable_payload())
        result,counts=self.recover(self.base(),self.transport(item))
        self.assertEqual(counts['deferred_artifacts'],1)
        self.assertTrue(any(slot['projection_status']=='UNREPRESENTABLE' for row in result['records'] for slot in row['dispatch_slots']))
        self.assertFalse(any('saved_model_archive_evidence' in row for row in result['records']))
        _,again=self.recover(result,self.transport(item))
        self.assertEqual(again['archives_verified'],1)

    def test_coverage_is_day_scoped_and_does_not_suppress_a_later_day_import(self):
        fixture=model_fixture.AllModelCycleTests();fixture.setUp()
        try:
            ctx=json.loads(wire(source_context()).decode().replace('2030-04-01','2030-04-02').replace('20300401','20300402'))
            payload=engine.forecast_round([ctx],fixture.runtime(),now=NOW+timedelta(days=1))
        finally:fixture.doCleanups()
        mixed=deepcopy(self.payload);mixed.pop('native_input_capsules')
        mixed.update(generated_at=payload['generated_at'],as_of=payload['as_of'])
        for name in ('current_inputs','dispatch_reports','model_readiness','skipped_contexts'):
            mixed[name]+=deepcopy(payload[name])
        mixed['summary']={name:mixed['summary'][name]+payload['summary'][name] for name in mixed['summary']}
        item=self.artifact(101,1,payload=mixed,saved='2030-04-02T09:00:20Z')
        base=self.base();tomorrow=deepcopy(base['records'][0])
        tomorrow.update(race_id='20300402-01-01',event_date_jst='2030-04-02',
                        cutoff_at=tomorrow['cutoff_at'].replace('2030-04-01','2030-04-02'))
        base['records'].append(tomorrow);base['event_date_jst']=None
        one,counts=self.recover(base,self.transport(item),day=DAY,now=NOW+timedelta(days=2))
        self.assertGreater(counts['appended_forecasts'],0)
        self.assertFalse(any(row.get('saved_model_archive_evidence') for row in one['records'] if row['event_date_jst']=='2030-04-02'))
        get=self.transport(item)
        both,again=self.recover(one,get,day='2030-04-02',now=NOW+timedelta(days=2))
        self.assertGreater(again['appended_forecasts'],0);self.assertIn('actions/artifacts/101/zip',get.calls)
        self.assertTrue(all(not row.get('prediction') or row['prediction']['cutoff_at'].startswith(row['event_date_jst']) for row in both['records']))
        replay=self.transport(item)
        _,done=self.recover(both,replay,day='2030-04-02',now=NOW+timedelta(days=2))
        self.assertEqual(done['archives_verified'],0)
        self.assertFalse(any(endpoint.startswith('actions/artifacts/') for endpoint in replay.calls))

    def test_view_bound_defers_an_append_without_raising_or_discarding_originals(self):
        base=self.base();get=self.transport(self.artifact(101,1))
        with patch.object(recovery,'MAX_VIEW_BYTES',len(wire(base))+1):
            result,counts=self.recover(base,get)
        self.assertEqual(result,base);self.assertEqual(counts['deferred_artifacts'],1)

    def test_per_race_original_capacity_defers_without_raising_the_existing_limit(self):
        base=self.base(known=102);row=base['records'][0];original=row['prediction']
        variants=[dict(deepcopy(original),artifact_id=1000+i) for i in range(128)]
        row.update(prediction=variants[0],comparison_predictions=variants[1:])
        try:result,counts=self.recover(base,self.transport(self.artifact(101,1)))
        except ValueError as exc:self.fail('existing per-race limit was not deferred: '+str(exc))
        self.assertEqual(result,base);self.assertEqual(counts['deferred_artifacts'],1)

    def test_attestation_row_and_history_chunk_bounds_defer_before_publishing_growth(self):
        from race_ai import saved_view_history as history
        first=self.artifact(101,1,payload=self.empty_payload,saved='2030-04-01T12:00:20Z')
        second=self.artifact(102,2,payload=self.empty_payload,saved='2030-04-01T12:00:20Z')
        complete,_=self.recover(self.base(),self.transport(first),now=NOW.replace(hour=22))
        self.assertTrue(any('saved_model_archive_evidence' in row for row in complete['records']))
        row=next(row for row in complete['records'] if 'saved_model_archive_evidence' in row)
        evidence_bytes=len(wire(row['saved_model_archive_evidence']))
        overhead=len(wire(dict(complete,records=[])))
        for target,name,limit in ((recovery,'MAX_ROW_EVIDENCE_BYTES',evidence_bytes),
                                  (history,'MAX_CHUNK_PLAIN',overhead+len(wire(row))+1)):
            with self.subTest(bound=name),patch.object(target,name,limit):
                result,counts=self.recover(complete,self.transport(first,second),now=NOW.replace(hour=22))
            self.assertEqual(result,complete);self.assertEqual(counts['deferred_artifacts'],1)

    def test_enlarged_row_defers_even_when_a_small_sibling_can_host_coverage(self):
        from race_ai import saved_view_history as history
        base=self.nearly_full_history_row();before=deepcopy(base);inventory=forecast_inventory(base)
        history.encrypt_day_chunks(base,KEY,view_id='a'*64)
        result,counts=self.recover(base,self.transport(self.artifact(101,1)))
        self.assertEqual(counts['status'],'SAVED_MODEL_RECOVERY_DEFERRED')
        self.assertEqual(counts['appended_forecasts'],0);self.assertEqual(counts['deferred_artifacts'],1)
        self.assertEqual(result,before);self.assertEqual(base,before)
        self.assertEqual(forecast_inventory(result),inventory)
        history.encrypt_day_chunks(result,KEY,view_id='a'*64)

    def test_unrepresentable_partial_merge_defers_all_growth_if_a_day_row_would_overflow(self):
        from race_ai import saved_view_history as history
        base=self.nearly_full_history_row();before=deepcopy(base);inventory=forecast_inventory(base)
        history.encrypt_day_chunks(base,KEY,view_id='a'*64)
        item=self.artifact(101,1,payload=self.unrepresentable_payload())
        result,counts=self.recover(base,self.transport(item))
        self.assertEqual(counts['status'],'SAVED_MODEL_RECOVERY_DEFERRED')
        self.assertEqual(counts['appended_forecasts'],0)
        self.assertEqual(result,before);self.assertEqual(base,before)
        self.assertEqual(forecast_inventory(result),inventory)
        history.encrypt_day_chunks(result,KEY,view_id='a'*64)

    def test_invalid_scope_or_missing_owner_key_stops_before_any_transport(self):
        for options in ({'run_ids':list(range(1,18))},{'run_ids':[True]},{'max_artifacts':129},{'key':b'bad'}):
            with self.subTest(options=tuple(options)),self.assertRaises(ValueError):
                self.recover(self.base(),lambda _:self.fail('invalid request used transport'),**options)


if __name__=='__main__':unittest.main()
