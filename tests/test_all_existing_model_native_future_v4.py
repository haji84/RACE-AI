"""Authored nineteen-cell research fits and fresh baseline inputs; no live data."""
import base64
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai import all_existing_model_research as research
from race_ai import all_existing_model_future_baseline as baseline
from race_ai.all_existing_model_learning import fit,verify_training,_sources
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_venue_learning import seal_candidate
from race_ai.four_sport_learning import LEARNED_ID
from scripts import all_existing_model_native_future as future
from scripts import all_existing_model_learning as learning
from tests import test_all_existing_model_native_future as boat
from tests.test_all_existing_model_native_future_v3 import KEY,NOW,metadata
from tests.test_all_existing_model_common_eight_per_sport import common_records,FIXTURE_NOW
from tests.test_nonboat_sparse_contracts import sparse_snapshot
from tests.test_all_existing_model_matrix import _shift_dates
from tests.test_all_existing_model_learning import observed_records
from tests.test_boat_venue_research import SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER


def ordinary_rows():
    rows=[deepcopy(row) for row in common_records() if row['sport'] in ('boat','horse')]
    for row in rows:
        result=row['result']
        for key in ('schema','evaluation_scope','published_payout_yen','payout_unit_verified','reason'):
            result.pop(key,None)
        result.update(status='settled',payout_per_100_yen=1230)
        row.pop('result_observation',None)
        if row['sport']=='horse':
            day=row['as_of'][:10];snapshot=_shift_dates(sparse_snapshot('horse',slots=(1,2,3)),
                (future.future.stamp(row['as_of']).date()-future.future.stamp('2030-01-15T09:10:00+09:00').date()).days)
            snapshot['race'].update(race_id=row['race_id'],event_date_jst=day,as_of=row['as_of'],sales_cutoff_at=row['cutoff_at'])
            ref='https://www.jra.go.jp/fixture/source/'+day
            for participant in snapshot['participants']:
                for feature in participant['features'].values():feature.update(source_ref=ref,
                    source_rights_ref='OWNER_PERSONAL_OFFICIAL_HORSE_FACTUAL_ANALYSIS_20261107')
            row['native_payload']=dict(snapshot=snapshot,stage='P0');row['stage']='P0'
            result['roster']={str(p['number']):p['identity'] for p in snapshot['participants']}
            row['input_sha256']=digest(row['native_payload'])
    return rows


def owner_fit(rows,clock):
    trained=fit(rows,now=clock,allow_source=lambda *_:True,allow_training=lambda *_:True)
    binding=dict(source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,
        source_refs=sorted(set().union(*(learning._record_source_refs(row) for row in rows))),
        intake_sha256=learning._intake_identity(rows),registry_sha256=trained['registry_sha256'])
    with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()):
        owner=research.issue_decision(**binding,now=clock,expires_at=NOW+timedelta(days=30))
    trained.update(training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=digest(owner),
        owner_bound_intake_sha256=binding['intake_sha256'],source_content_sha256=CONTENT,
        venue_dataset_sha256=POINTER['dataset_sha256'])
    trained['training_sha256']=digest({key:value for key,value in trained.items() if key!='training_sha256'})
    verify_training(trained);return trained,owner


@lru_cache(maxsize=1)
def fitted():
    rows=ordinary_rows();trained,owner=owner_fit(rows,FIXTURE_NOW)
    old_rows=[row for row in rows if row['model_id']==LEARNED_ID]
    old,old_owner=owner_fit(old_rows,FIXTURE_NOW-timedelta(days=1))
    records=json.loads(json.dumps(observed_records()).replace('2030-04-01','2030-01-01').replace('20300401','20300101'))
    for row in records:row['input_sha256']=digest(row['native_payload'])
    carrier=fit(records,now=FIXTURE_NOW-timedelta(days=2))
    return trained,owner,old,old_owner,carrier


class NineteenManifestTests(unittest.TestCase):
    def test_explicit_nineteen_profile_requires_distinct_baseline_and_keeps_thirty_strict(self):
        value=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V4',candidate_cell_count=19,
            candidate_artifact_id=200,candidate_digest='sha256:'+'a'*64,
            source_input_artifacts=[dict(id=100,digest='sha256:'+'b'*64,run_id=8,head_sha='c'*40)],
            horse_baseline_artifact=dict(id=190,digest='sha256:'+'d'*64,run_id=6,head_sha='e'*40))
        self.assertEqual(future.validate_manifest(value),value)
        for change in (dict(candidate_cell_count=30),dict(candidate_cell_count=True),
                dict(horse_baseline_artifact=dict(value['horse_baseline_artifact'],id=200))):
            with self.subTest(change=change),self.assertRaises(ValueError):future.validate_manifest(dict(value,**change))
        wrong=dict(value,schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3');wrong.pop('horse_baseline_artifact')
        with self.assertRaises(ValueError):future.validate_manifest(wrong)


class NineteenFutureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.training,cls.owner,cls.old,cls.old_owner,cls.carrier=fitted()
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.temp=Path(temporary.name)
        fixture=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        fixture.start();self.addCleanup(fixture.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden'))
        network.start();self.addCleanup(network.stop)
        self.mapping={};self.now=NOW;self.root=self.temp/'future';self.env=dict(run_id=42,head_sha='d'*40,temp=self.temp)
        for ident,trained,owner,run,saved,head in (
                (200,self.training,self.owner,7,FIXTURE_NOW+timedelta(minutes=1),'a'*40),
                (190,self.old,self.old_owner,6,FIXTURE_NOW-timedelta(days=1)+timedelta(minutes=1),'b'*40)):
            folder=self.temp/str(ident);seal_candidate(dict(training=deepcopy(trained),owner_research_record=deepcopy(owner),
                excluded=[],summary=dict(state='FITTED_SHADOW_ONLY',fitted_model_count=len(trained['models']),
                    actual_purchases=False,production_promoted=False)),folder)
            raw=boat.zipped(folder);actual=metadata(ident,f'all-existing-model-learning-{run}-1',raw,saved=saved,run=run,head=head)
            self.mapping['actions/artifacts/'+str(ident)]=json.dumps(actual).encode()
            self.mapping['actions/artifacts/'+str(ident)+'/zip']=raw
        for mocked in (patch.object(future.future,'utc_now',side_effect=lambda:self.now),
                patch.object(future.future,'metadata',side_effect=lambda ident:json.loads(self.mapping['actions/artifacts/'+str(ident)])),
                patch.object(future.future,'gh',side_effect=lambda route:self.mapping[route])):
            mocked.start();self.addCleanup(mocked.stop)
        old_meta=json.loads(self.mapping['actions/artifacts/190'])
        self.baseline=baseline.load_baseline(dict(id=190,digest=old_meta['digest'],run_id=6,head_sha='b'*40),
            now=NOW,fetch_metadata=future.future.metadata,fetch_zip=lambda ident:self.mapping['actions/artifacts/'+str(ident)+'/zip'])
        self.requests=boat.requests(day='2030-02-02',cutoff='23:59:00')+boat.extra_requests(day='2030-02-02')
        for request in self.requests:
            native=request['native_payload'];native['scope']='SYNTHETIC_ONLY'
            if request['cell_key']=='boat/'+LEARNED_ID:
                native['learned_model']=deepcopy(self.old['models']['boat/'+LEARNED_ID]['native_training'])
            if 'scope' in native.get('snapshot',{}):native['snapshot']['scope']='SYNTHETIC_ONLY'
            info=future.registry.identity(request['cell_key'].split('/',1)[1],'boat',native)
            request['native_payload']=json.loads(json.dumps(native).replace(info['race_cutoff_at'],'2030-02-02T23:59:00+09:00'))
        snapshot=_shift_dates(sparse_snapshot('horse',slots=(1,2,3)),18)
        snapshot['race'].update(as_of=(NOW-timedelta(minutes=4)).isoformat(),sales_cutoff_at='2030-02-02T23:59:00+09:00')
        ref='https://www.jra.go.jp/fixture/fresh-card';rights='OWNER_PERSONAL_OFFICIAL_HORSE_FACTUAL_ANALYSIS_20261107'
        for participant in snapshot['participants']:
            for feature in participant['features'].values():feature.update(source_ref=ref,source_rights_ref=rights,
                captured_at=(NOW-timedelta(minutes=4)).isoformat(),published_at=None)
        native=dict(snapshot=snapshot,stage='P0',source_evidence=[dict(source_ref=ref,source_rights_ref=rights,
            source_sha256='a'*64,captured_at=(NOW-timedelta(minutes=4)).isoformat(),published_at=None)])
        source_meta=dict(status=200,source_url=ref,final_url=ref,source_sha256='a'*64,byte_count=100,
            fetched_at=(NOW-timedelta(minutes=5)).isoformat(),response_received_at=(NOW-timedelta(minutes=4)).isoformat(),headers={})
        for cell in sorted(future.V4_CELLS['horse']):
            payload=(baseline.attach(native,self.baseline,sport='horse',source_metadata=source_meta,
                now=NOW-timedelta(minutes=3)) if cell=='horse/'+LEARNED_ID else deepcopy(native))
            self.requests.append(dict(cell_key=cell,native_payload=payload))
        source=self.temp/'source';context=dict(training=self.carrier,receipt=metadata(90,'all-existing-model-learning-5-1',
            b'fixture',saved=FIXTURE_NOW-timedelta(days=1),run=5))
        make_private_pairs(context,self.requests,source,now=NOW-timedelta(minutes=2),allow_source=lambda *_:True)
        (source/'summary.json').unlink();raw=boat.zipped(source)
        actual=metadata(100,'all-existing-model-pairs-8-1',raw,saved=NOW-timedelta(minutes=1),run=8,head='c'*40)
        self.mapping['actions/artifacts/100']=json.dumps(actual).encode();self.mapping['actions/artifacts/100/zip']=raw
        current=json.loads(self.mapping['actions/artifacts/200'])
        self.manifest=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V4',candidate_cell_count=19,candidate_artifact_id=200,
            candidate_digest=current['digest'],horse_baseline_artifact=dict(id=190,digest=old_meta['digest'],run_id=6,head_sha='b'*40),
            source_input_artifacts=[dict(id=100,digest=actual['digest'],run_id=8,head_sha='c'*40)])
    def test_real_nineteen_fit_fresh_attachment_encrypted_pairs_and_origin_actual_readback(self):
        original=deepcopy(self.requests);result=future.generate(self.manifest,self.root,self.env)
        self.assertTrue(result['ready'],result);self.assertTrue(result['all_nineteen_cells_produced'],result)
        self.assertEqual(result['forecast_counts_by_sport'],dict(boat=14,horse=5))
        self.assertEqual(result['forecast_partition_count'],19);self.assertNotIn('all_thirty_cells_produced',result)
        self.assertTrue(result['ranker_comparisons']['horse']['ranker_parameters_identical'])
        self.assertFalse(result['ranker_comparisons']['horse']['improvement_claimed']);self.assertEqual(self.requests,original)
        for ident,folder,name in ((201,self.root,'all-existing-model-pairs-42-900004'),
                (202,self.root.with_name(self.root.name+'.origin'),'all-native-future-origin-42-900010')):
            raw=boat.zipped(folder);self.mapping['actions/artifacts/'+str(ident)+'/zip']=raw
            self.mapping['actions/artifacts/'+str(ident)]=json.dumps(metadata(ident,name,raw,
                saved=NOW+timedelta(seconds=2),head='d'*40)).encode()
        self.now=NOW+timedelta(seconds=4)
        actual=future.readback(201,self.manifest,self.root,self.env,readback_origin_artifact=202)
        self.assertTrue(actual['complete_independent_receipts_verified']);self.assertEqual(actual['forecast_partition_count'],19)
        self.assertTrue(actual['all_nineteen_cells_produced'])
    def test_missing_attachment_and_native_clocks_hold_horse_without_replacing_input(self):
        context=future.candidate(self.manifest);_,records=future.source_v3(self.manifest)
        originals=deepcopy(records)
        for record in records:
            for capsule in record.get('captured_native_inputs',[]):
                if capsule['cell_key']=='horse/'+LEARNED_ID:
                    capsule['native_payload'].pop('baseline_attachment');capsule['input_sha256']=digest(capsule['native_payload'])
        horse=[dict(generated_at=r['generated_at'],captured_native_inputs=[c for c in r.get('captured_native_inputs',[])
            if c['cell_key'].startswith('horse/')]) for r in records]
        horse=[r for r in horse if r['captured_native_inputs']]
        held=future.prepare_requests_v3(context,horse,now=NOW,profile='V4',baseline_context=self.baseline)
        self.assertEqual(held['forecast_counts_by_sport']['horse'],0)
        self.assertEqual(held['held_sports']['horse']['reason'],'HOLD_NATIVE_BASELINE_ATTACHMENT_INVALID')
        self.assertFalse(held['all_nineteen_cells_produced']);self.assertEqual(originals[0]['generated_at'],records[0]['generated_at'])
        same=deepcopy(self.manifest);same['horse_baseline_artifact']['id']=same['candidate_artifact_id']
        with self.assertRaises(ValueError):future.validate_manifest(same)
    def test_owner_v_two_or_noncommon_sport_cohort_cannot_be_relabelled_nineteen_cash(self):
        with self.assertRaises(ValueError):future._training_v3(self.training,self.owner,require_owner=True)
        bad=deepcopy(self.training);key=next(key for key in bad['models'] if key.startswith('horse/'))
        model=bad['models'][key];model['train_race_ids']=model['train_race_ids'][1:]+model['validation_race_ids'][:1]
        model['model_sha256']=digest({k:v for k,v in model.items() if k!='model_sha256'})
        bad['training_sha256']=digest({k:v for k,v in bad.items() if k!='training_sha256'})
        with self.assertRaises(ValueError):future._training_v4(bad,self.owner,require_owner=True)


if __name__=='__main__':unittest.main()
