"""Fresh call events bind invented legacy predictions without rewriting them."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_saved_prediction_evidence as evidence
from race_ai.actions_contract import digest
from race_ai.saved_view_feed import forecast_inventory
from tests.test_boat_native_coverage_evidence import NOW,predictions
from tests.test_boat_saved_prediction_evidence import repack
from tests import test_boat_collector_model_completion as collector
RID=collector.RID


class NativeGenerationEventTests(unittest.TestCase):
    def setUp(self):
        from importlib import util
        self.assertIsNotNone(util.find_spec('race_ai.boat_native_generation_event'),
                             'fresh native call start/completion evidence is missing')
        from race_ai import boat_native_generation_event
        self.events=boat_native_generation_event

    def fresh(self):
        from tests.test_boat_saved_prediction_evidence import original_view
        view,doc,raw,meta=original_view('P1')
        base_sha=doc['paired_forecasts'][0]['source_sha256']
        bindings=dict(source_snapshot_sha256=base_sha,program_source_sha256='a'*64,beforeinfo_source_sha256='b'*64)
        models=[doc['additional_official_feature_shadows'][0],*doc['observed_pairwise_p1_bundles'][0]['suite']['models'].values()]
        doc['native_generation_events']=[self.events.record_generation_event(model,race_id='20300401-24-12',
            computation_started_at='2030-04-01T08:10:01+00:00',
            computation_completed_at='2030-04-01T08:10:02+00:00',**bindings) for model in models]
        raw,meta=repack(doc,meta,'national.json')
        # The containing document has a new byte hash; every native body is exact.
        for p in predictions(view['records'][0]):p['original_json_sha256']=hashlib.sha256(json.dumps(doc,ensure_ascii=False).encode()).hexdigest()
        schedule=[dict(race_id='20300401-24-12',cutoff_at='2030-04-01T17:30:00+09:00',
                       schedule_captured_at='2030-04-01T00:00:00+00:00',source_sha256='c'*64)]
        return view,doc,raw,meta,schedule

    def test_fresh_events_make_only_the_five_original_families_qualified_and_keep_body_hashes(self):
        view,doc,raw,meta,schedule=self.fresh();before=deepcopy(view)
        from race_ai.boat_private_original_archive import seal_original_zip
        key=bytes(range(32))
        cipher=seal_original_zip(raw,run_id=meta['workflow_run']['id'],head_sha='a'*40,kind='P1',key=key)
        wrapped=io.BytesIO()
        with zipfile.ZipFile(wrapped,'w') as z:z.writestr('private-original.enc',cipher)
        raw=wrapped.getvalue();meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
        out,counts=evidence.hydrate_prediction_evidence(view,[(raw,meta)],key=key,official_schedule=schedule,now=NOW)
        qualified=[evidence.native_coverage_evidence(out['records'][0],p,now=NOW)
                   for p in predictions(out['records'][0])]
        self.assertEqual(sum(p['status']=='QUALIFIED_PRE_CUTOFF' for p in qualified),5)
        self.assertEqual(sum(p.get('computation_completed_at') is not None for p in qualified),3)
        self.assertEqual(counts['native_pre_cutoff_qualified'],5)
        self.assertEqual(forecast_inventory(out),forecast_inventory(before))
        self.assertEqual(view,before)
        self.assertTrue(all(p['generated_at'] is None for p in predictions(out['records'][0])))

    def test_event_absence_never_repairs_asof_generated_claim_in_an_existing_view(self):
        view,_,raw,meta=__import__('tests.test_boat_saved_prediction_evidence',fromlist=['original_view']).original_view('P1')
        for p in predictions(view['records'][0]):
            p.update(generated_at=p['as_of'],eligible_pre_cutoff=True,external_receipt_verified=True)
        before=deepcopy(view)
        schedule=[dict(race_id='20300401-24-12',cutoff_at='2030-04-01T17:30:00+09:00',
                       schedule_captured_at='2030-04-01T00:00:00+00:00',source_sha256='c'*64)]
        out,counts=evidence.hydrate_prediction_evidence(view,[(raw,meta)],official_schedule=schedule,now=NOW)
        self.assertEqual(counts['native_pre_cutoff_qualified'],2)
        self.assertEqual(counts['native_pre_cutoff_held'],5)
        self.assertEqual(forecast_inventory(out),forecast_inventory(before))

    def test_duplicate_tamper_foreign_source_future_and_late_events_are_rejected(self):
        for change in ('duplicate','hash','model','source','extra_source','future','late','reverse'):
            with self.subTest(change=change):
                view,doc,_,meta,schedule=self.fresh()
                event=doc['native_generation_events'][0]
                if change=='duplicate':doc['native_generation_events'].append(deepcopy(event))
                elif change=='hash':event['prediction_sha256']='0'*64
                elif change=='model':event['model_id']='other-native-model'
                elif change=='source':event['source_snapshot_sha256']='0'*64
                elif change=='extra_source':
                    model=doc['additional_official_feature_shadows'][0]
                    old_hash=model['bundle_sha256'];model['extra_source_sha256']='0'*64
                    model['bundle_sha256']=digest({k:v for k,v in model.items() if k!='bundle_sha256'})
                    event['prediction_sha256']=model['bundle_sha256']
                    for p in predictions(view['records'][0]):
                        if p['prediction_sha256']==old_hash:
                            p['prediction_sha256']=model['bundle_sha256'];p['model_sha256']=model['bundle_sha256']
                elif change=='future':event['computation_completed_at']='2030-04-01T08:12:01+00:00'
                elif change=='late':event['computation_completed_at']='2030-04-01T08:30:00+00:00'
                else:event['computation_started_at']='2030-04-01T08:10:03+00:00'
                event['event_sha256']=digest({k:v for k,v in event.items() if k!='event_sha256'})
                raw,meta=repack(doc,meta,'national.json')
                for p in predictions(view['records'][0]):p['original_json_sha256']=hashlib.sha256(json.dumps(doc,ensure_ascii=False).encode()).hexdigest()
                with self.assertRaises(ValueError):evidence.hydrate_prediction_evidence(view,[(raw,meta)],official_schedule=schedule,now=NOW)

    def test_producer_records_three_fresh_events_and_does_not_regenerate_saved_families(self):
        result,requests,_=collector.CollectorCompletionTests().collect({},frozen=False)
        self.assertEqual(len(result['native_generation_events']),3)
        self.assertEqual(len(requests),3)
        saved,requests,_=collector.CollectorCompletionTests().collect({RID:sorted(collector.BASELINES)},forbid_models=True)
        self.assertFalse(saved.get('native_generation_events'))
        self.assertEqual(len(requests),2)

    def test_clocks_bracket_each_actual_model_call_before_optional_io(self):
        from scripts import boat_nationwide_ab_pilot as pilot
        import os
        calls=[];tick=0;raw_program,raw_preview=collector.raw_sources()
        def timestamp():
            nonlocal tick
            tick+=1;at=(collector.NOW+timedelta(microseconds=tick)).isoformat()
            calls.append(('clock',at));return at
        def get(url,**_kw):
            calls.append(('get',url))
            if '/racelist?' in url:raw=raw_program
            elif '/beforeinfo?' in url:raw=raw_preview
            else:raise pilot.SourceError('OPTIONAL_FIXTURE_UNAVAILABLE')
            return raw,collector.NOW,hashlib.sha256(raw).hexdigest()
        original_c=pilot.build_live_feature_shadow;original_o=pilot.build_observed_p1
        def clite(*args,**kwargs):
            calls.append(('clite_start',None));out=original_c(*args,**kwargs)
            calls.append(('clite_return',None));return out
        def observed(*args,**kwargs):
            calls.append(('observed_start',None));out=original_o(*args,**kwargs)
            calls.append(('observed_return',None));return out
        with patch.object(pilot,'get',side_effect=get),patch.object(pilot,'_clock',return_value=collector.NOW), \
             patch.object(pilot,'observed_timestamp',side_effect=timestamp),patch.object(pilot,'MODEL_INPUT_SINK',None), \
             patch.object(pilot,'NATIVE_INPUT_SINK',None),patch.object(pilot,'OBSERVED_HISTORY_CONTEXT',None), \
             patch.object(pilot,'collect_pitreport',return_value=None),patch.object(pilot,'collect_entry_history',return_value=None), \
             patch.object(pilot,'build_live_feature_shadow',side_effect=clite),patch.object(pilot,'build_observed_p1',side_effect=observed), \
             patch.dict(os.environ,{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}):
            status,pair,c,_,o=pilot.make_pair(collector.DAY,dict(race_id=RID,cutoff_at='2030-04-01T20:30:00+09:00'))
        events=status['native_generation_events'];self.assertEqual(len(events),3)
        for prefix,event in (('clite',events[0]),('observed',events[1])):
            start=calls.index((prefix+'_start',None));end=calls.index((prefix+'_return',None))
            self.assertEqual(calls[start-1],('clock',event['computation_started_at']))
            self.assertEqual(calls[end+1],('clock',event['computation_completed_at']))
        self.assertEqual(events[0]['prediction_sha256'],c['bundle_sha256'])
        self.assertEqual({e['prediction_sha256'] for e in events[1:]},
                         {m['prediction_sha256'] for m in o['suite']['models'].values()})
        self.assertTrue(all(e['source_snapshot_sha256']==pair['source_sha256'] for e in events))

    def test_old_saved_view_survives_real_cipher_recovery_cache_and_native_hold_evidence(self):
        from tests import test_boat_all_model_recovery as cases
        from tests import test_boat_all_model_cycle as models
        from race_ai import boat_all_model_cycle as engine
        from race_ai.boat_private_original_archive import seal_original_zip
        cases.ModelRecoveryTests.setUpClass();recovery=cases.ModelRecoveryTests();recovery.setUp()
        fixture=models.AllModelCycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        ctx=models.source_context();baseline=models.native_baseline(ctx)
        prior=models.receipt(baseline,artifact=99,saved='2030-04-01T18:00:02+09:00')
        payload=engine.forecast_round([ctx],fixture.runtime(),now=models.NOW,
            baseline_document=baseline,baseline_receipt=prior)
        from race_ai.boat_ab_shadow import MODEL_IDS as AB
        for slot in payload['dispatch_reports'][0]['slots']:
            if slot['status']=='ORIGINAL_REUSED':
                slot.pop('original_input_as_of',None)
                if slot['model_id'] not in AB:slot['dispatch_generated_at']=models.ASOF
        old=engine.project_round(payload,models.receipt(payload,artifact=101,saved='2030-04-01T09:00:20Z'))
        for p in predictions(old['records'][0]):
            if p['dispatch_status']=='ORIGINAL_REUSED':
                p.pop('native_clock_provenance',None)
                p.update(generated_at=p['as_of'],eligible_pre_cutoff=True)
                p['missing_reasons']=[r for r in p['missing_reasons'] if r not in
                    ('GENERATED_AT_NOT_SAVED','NATIVE_GENERATION_CLOCK_MISSING')]
        before=deepcopy(old);inventory=forecast_inventory(old)
        second=json.loads(json.dumps(ctx).replace('20300401-12-12','20300401-13-12').replace('jcd=12','jcd=13'))
        second['program']['venue']='13'
        next_payload=engine.forecast_round([second],fixture.runtime(),now=models.NOW)
        first=recovery.artifact(101,1,payload=payload);later=recovery.artifact(102,2,payload=next_payload)
        output,counts=recovery.recover(old,recovery.transport(first,later),day=cases.DAY)
        self.assertEqual(old,before)
        self.assertTrue(all(forecast_inventory(output)[key]==value for key,value in inventory.items()))
        self.assertEqual(counts['status'],'SAVED_MODEL_RECOVERY_COMPLETE')
        self.assertEqual(counts['archives_verified'],2)
        self.assertGreater(counts['appended_forecasts'],0)
        self.assertEqual(len(output['records']),2)
        new_row=next(r for r in output['records'] if r['race_id']!=ctx['program']['race_id'])
        self.assertTrue(any(p['eligible_pre_cutoff'] for p in predictions(new_row)))
        again,repeated=recovery.recover(output,recovery.transport(first,later),day=cases.DAY)
        self.assertEqual(again,output);self.assertEqual(repeated['archives_verified'],0)
        # The historical true flag remains in its exact original body. Only
        # the separately authenticated native sidecar decides formal coverage.
        body=cases.wire(baseline)
        clear=io.BytesIO()
        with zipfile.ZipFile(clear,'w') as z:z.writestr('national.json',body)
        cipher=seal_original_zip(clear.getvalue(),run_id=42,head_sha=models.HEAD,kind='P1',key=cases.KEY)
        native_zip=io.BytesIO()
        with zipfile.ZipFile(native_zip,'w') as z:z.writestr('private-original.enc',cipher)
        raw=native_zip.getvalue()
        meta=dict(id=99,name='boat-national-cutoff-42',expired=False,created_at=prior['created_at'],
            digest='sha256:'+hashlib.sha256(raw).hexdigest(),workflow_run=dict(id=42,
                repository_id=1416489937,head_repository_id=1416489937,head_sha=models.HEAD))
        ledger=[dict(race_id=ctx['program']['race_id'],cutoff_at=ctx['program']['closed_at'],
                     schedule_captured_at='2030-04-01T08:00:00+09:00',source_sha256='c'*64)]
        hydrated,_=evidence.hydrate_prediction_evidence(output,[(raw,meta)],key=cases.KEY,
            official_schedule=ledger,now=cases.CLOCK)
        self.assertEqual(forecast_inventory(hydrated),forecast_inventory(output))
        original_row=next(r for r in hydrated['records'] if r['race_id']==ctx['program']['race_id'])
        legacy=[p for p in predictions(original_row) if p['dispatch_status']=='ORIGINAL_REUSED' and p['model_id'] not in AB]
        self.assertEqual(len(legacy),3)
        self.assertTrue(all(p['eligible_pre_cutoff'] is True for p in legacy))
        self.assertTrue(all(evidence.native_coverage_evidence(original_row,p,now=cases.CLOCK)['status']=='HOLD'
                            for p in legacy))
        ab=[p for p in predictions(original_row) if p['dispatch_status']=='ORIGINAL_REUSED' and p['model_id'] in AB]
        self.assertEqual(len(ab),2)
        self.assertTrue(all(evidence.native_coverage_evidence(original_row,p,now=cases.CLOCK)['status']=='QUALIFIED_PRE_CUTOFF'
                            for p in ab))


if __name__=='__main__':unittest.main()
