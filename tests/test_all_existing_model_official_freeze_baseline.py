"""A new official-cache freeze binds an authored prior native baseline only."""
from copy import deepcopy
from datetime import date,timedelta
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from race_ai import all_existing_model_future_baseline as baseline
from race_ai import all_existing_model_research as research
from race_ai.boat_venue_learning import seal_candidate
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.all_existing_model_learning import _sources
from race_ai.four_sport_learning import LEARNED_ID
from scripts import all_existing_model_official_freeze as freeze
from tests import test_all_existing_model_native_future as boat
from tests import test_all_existing_model_official_freeze as old_freeze
from tests.test_all_existing_model_native_future_v4 import ordinary_rows,owner_fit
from tests.test_all_existing_model_matrix import _shift_dates
from tests import test_jra_official_sparse_adapter as jra
from tests.test_boat_venue_research import SOURCE,CONTENT,B_RIGHTS
from tests.test_boat_venue_learning import POINTER


class OfficialBaselineFreezeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=old_freeze.OfficialFreezeTests('test_manifest_requires_exact_pins_and_current_execution_day')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.manifest=self.fixture.manifest
    def test_v3_exact_baseline_manifest_and_new_weekend_rule_do_not_change_old_versions(self):
        value=dict(self.manifest,schema=freeze.V3_SCHEMA,excluded_native_artifacts=[],
            horse_baseline_artifact=dict(id=690,digest='sha256:'+'c'*64,run_id=39,head_sha='b'*40),
            carrier_artifact=dict(id=700,digest='sha256:'+'d'*64,run_id=42,head_sha='a'*40))
        path=self.root/'v3.json';path.write_text(json.dumps(value))
        self.assertEqual(freeze.load_manifest(path,now=jra.NOW),value)
        self.assertEqual(freeze._rule_id(value),'JRA_2026_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS')
        self.assertEqual(freeze._rule_id(dict(value,execution_day='2026-11-08')),
            'JRA_2026_SUNDAY_ALL_RACES_START_MINUS_60_SECONDS')
        self.assertEqual(freeze._rule_id(dict(self.manifest,execution_day='2026-11-08')),
            'JRA_2026_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS')
        with self.assertRaises(ValueError):freeze._rule_id(dict(value,execution_day='2026-11-09'))
        old=dict(value,schema=freeze.V2_SCHEMA);path.write_text(json.dumps(old))
        with self.assertRaises(ValueError):freeze.load_manifest(path,now=jra.NOW)
    def setup_baseline(self):
        manifest,env,carrier,carrier_meta=self.fixture._fixture()
        training=deepcopy(carrier['training']);created=freeze.future.stamp(training['created_at'])
        owner=research.issue_decision(source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,
            source_refs=[('https://www.boatrace.jp/fixture/card',B_RIGHTS)],
            intake_sha256=training['source_intake_sha256'],registry_sha256=training['registry_sha256'],
            now=created,expires_at=jra.NOW+timedelta(days=7))
        training.update(training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=freeze.digest(owner),
            source_content_sha256=CONTENT,venue_dataset_sha256=POINTER['dataset_sha256'])
        training['training_sha256']=freeze.digest({k:v for k,v in training.items() if k!='training_sha256'})
        folder=self.root/'bound-carrier';seal_candidate(dict(training=training,owner_research_record=owner,excluded=[],
            summary=dict(state='FITTED_SHADOW_ONLY',actual_purchases=False,production_promoted=False)),folder)
        carrier_raw=boat.zipped(folder);carrier_meta=dict(carrier_meta,size_in_bytes=len(carrier_raw),
            digest='sha256:'+sha256(carrier_raw).hexdigest(),name='all-existing-model-learning-38-1',
            created_at=(created+timedelta(seconds=2)).isoformat(),
            workflow_run=dict(id=38,head_sha='e'*40,repository_id=1416489937,head_repository_id=1416489937))
        shift=(date(2026,10,20)-date(2030,1,15)).days
        rows=[_shift_dates(row,shift) for row in ordinary_rows() if row['sport']=='horse' and row['model_id']==LEARNED_ID]
        def restore_rights(value):
            if type(value) is dict:
                if 'source_rights_ref' in value:value['source_rights_ref']=freeze.capture.official_rights_ref('horse')
                for child in value.values():restore_rights(child)
            elif type(value) is list:
                for child in value:restore_rights(child)
        for row in rows:
            restore_rights(row)
            row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['snapshot']['scope']=row['scope']
            row['input_sha256']=freeze.digest(row['native_payload'])
        trained,owner=owner_fit(rows,jra.NOW-timedelta(days=1))
        folder=self.root/'baseline';seal_candidate(dict(training=trained,owner_research_record=owner,excluded=[],
            summary=dict(state='FITTED_SHADOW_ONLY',actual_purchases=False,production_promoted=False)),folder)
        raw=boat.zipped(folder);actual=dict(carrier_meta,id=690,name='all-existing-model-learning-39-1',
            size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(jra.NOW-timedelta(days=1)+timedelta(seconds=2)).isoformat(),
            workflow_run=dict(id=39,head_sha='b'*40,repository_id=1416489937,head_repository_id=1416489937))
        pin=dict(id=690,digest=actual['digest'],run_id=39,head_sha='b'*40)
        carrier_pin=dict(id=700,digest=carrier_meta['digest'],run_id=38,head_sha='e'*40)
        manifest=dict(manifest,schema=freeze.V3_SCHEMA,excluded_native_artifacts=[],horse_baseline_artifact=pin,
            carrier_artifact=carrier_pin)
        self.mapping={'actions/artifacts/690':actual,'actions/artifacts/690/zip':raw,
            'actions/artifacts/700':carrier_meta,'actions/artifacts/700/zip':carrier_raw};self.now=jra.NOW
        for mocked in (patch.object(freeze,'ROOT',self.root/'repo'),
                patch.object(freeze,'utc_now',side_effect=lambda:self.now),
                patch.object(freeze.future,'candidate',return_value=carrier),
                patch.object(freeze.future,'metadata',side_effect=lambda ident:self.mapping['actions/artifacts/'+str(ident)]),
                patch.object(freeze.future,'gh',side_effect=lambda route:self.mapping[route])):
            mocked.start();self.addCleanup(mocked.stop)
        return manifest,env,actual
    def test_new_five_input_capsules_keep_four_defaults_and_bind_baseline_before_actual_readback(self):
        manifest,env,_=self.setup_baseline();output=self.root/'output'
        result=freeze.generate(700,output,env,manifest)
        self.assertTrue(result['ready'],result);self.assertEqual(result['forecast_partition_count'],0)
        self.assertEqual(result['baseline_attached_native_input_count'],1)
        records=freeze.local_records(output);caps=records[0]['captured_native_inputs']
        ranker=next(c for c in caps if c['cell_key']=='horse/'+LEARNED_ID)
        self.assertIn('learned_model',ranker['native_payload'])
        original=deepcopy(ranker['native_payload']);original.pop('learned_model');original.pop('baseline_attachment')
        for capsule in caps:
            if capsule is not ranker:self.assertEqual(capsule['native_payload'],original)
        status=dict(result,schema=freeze.STATUS,workflow_run_id=42,expected_head_sha='a'*40)
        path=output.with_name('output.status.json');freeze.save(path,freeze.future.wire(status))
        raw=self.fixture._archive(output);actual=dict(self.mapping['actions/artifacts/690'],id=801,
            name='all-existing-model-pairs-42-900002',size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(jra.NOW+timedelta(seconds=1)).isoformat(),
            workflow_run=dict(id=42,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
        self.mapping['actions/artifacts/801']=actual;self.mapping['actions/artifacts/801/zip']=raw
        self.now=jra.NOW+timedelta(seconds=5);admitted=freeze.readback(801,output,env,manifest=manifest)
        self.assertTrue(admitted['baseline_receipt_verified']);self.assertTrue(admitted['independent_pre_cutoff_receipt_verified'])
        self.assertTrue(admitted['original_source_native_replay_verified'])
        self.assertEqual(admitted['horse_baseline_artifact'],manifest['horse_baseline_artifact'])
        status.pop('future_baseline_schema');freeze.save(path,freeze.future.wire(status),replace=True)
        with self.assertRaisesRegex(ValueError,'BASELINE_SCHEMA_BINDING'):freeze.readback(801,output,env)
    def test_bad_attach_callback_cannot_change_raw_facts_even_with_self_consistent_proof(self):
        manifest,env,_=self.setup_baseline();output=self.root/'bad-callback';real=baseline.attach
        def altered(payload,*args,**kwargs):
            changed=deepcopy(payload);feature=next(iter(changed['snapshot']['participants'][0]['features'].values()))
            feature['value']-=0.001
            return real(changed,*args,**kwargs)
        with patch.object(baseline,'attach',side_effect=altered):result=freeze.generate(700,output,env,manifest)
        self.assertFalse(result['ready']);self.assertFalse(output.exists())
    def test_readback_rederives_raw_facts_instead_of_trusting_resealed_native_proof(self):
        manifest,env,_=self.setup_baseline();original=self.root/'original'
        result=freeze.generate(700,original,env,manifest);record=freeze.local_records(original)[0]
        context=freeze._load_carrier(manifest['carrier_artifact']);old=freeze._load_horse_baseline(manifest['horse_baseline_artifact'])
        requests=[]
        for capsule in record['captured_native_inputs']:
            payload=deepcopy(capsule['native_payload']);proof=payload.pop('baseline_attachment',None);payload.pop('learned_model',None)
            feature=next(iter(payload['snapshot']['participants'][0]['features'].values()));feature['value']-=0.001
            if proof is not None:payload=baseline.attach(payload,old,sport='horse',source_metadata=proof['source_metadata'],
                now=freeze.future.stamp(proof['attached_at']))
            requests.append(dict(cell_key=capsule['cell_key'],native_payload=payload))
        tampered=self.root/'tampered';refs=set().union(*(_sources(r['native_payload']) for r in requests))
        make_private_pairs(context,requests,tampered,now=freeze.future.stamp(record['generated_at']),
            allow_source=lambda ref,rights,purpose:purpose=='analysis' and (ref,rights) in refs)
        (tampered/'summary.json').unlink();records=freeze.local_records(tampered)
        status=dict(result,schema=freeze.STATUS,workflow_run_id=42,expected_head_sha='a'*40,
            record_sha256=sorted(freeze.digest(r) for r in records))
        freeze.save(tampered.with_name('tampered.status.json'),freeze.future.wire(status))
        with self.assertRaisesRegex(ValueError,'RAW_SOURCE_NATIVE_BINDING'):
            freeze.readback(801,tampered,env,manifest=manifest)
    def test_old_card_capture_before_baseline_receipt_is_hold_and_no_native_is_reissued(self):
        manifest,env,actual=self.setup_baseline();output=self.root/'held'
        actual['created_at']=(jra.NOW-timedelta(seconds=30)).isoformat()
        result=freeze.generate(700,output,env,manifest)
        self.assertFalse(result['ready']);self.assertFalse(output.exists())
        self.assertEqual(result['forecast_partition_count'] if 'forecast_partition_count' in result else 0,0)


if __name__=='__main__':unittest.main()
