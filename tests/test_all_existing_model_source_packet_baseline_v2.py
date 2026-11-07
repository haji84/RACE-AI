"""Invented two-sport prospective packets and baseline candidates; no real access."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import io
import json
import re
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_research as research
from race_ai.all_existing_model_learning import fit,verify_training,_sources
from race_ai.boat_venue_learning import seal_candidate
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.official_order_only_result import EVALUATION_SCOPE,LEGACY_OBSERVATION_FIELDS
from tests import test_all_existing_model_source_packet_freeze as fixtures
from tests.test_all_existing_model_common_eight_per_sport import common_records
from tests.test_all_existing_model_matrix import _shift_dates,native_records
from tests.test_boat_venue_research import SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER

api=fixtures.freeze
SCHEMA='RACE_AI_OFFICIAL_SOURCE_PACKET_FREEZE_INPUT_V2'
FIT_AT=datetime(2030,1,14,8,tzinfo=timezone.utc)

def shift_fixture(value,offset,key=''):
    if isinstance(value,dict):return {k:shift_fixture(v,offset,k) for k,v in value.items()}
    if isinstance(value,list):return [shift_fixture(v,offset,key) for v in value]
    if not isinstance(value,str) or 'sha256' in key or 'rights' in key or key in (
        'digest','mac','model_id','model_version','transform_id','schema','carrier_cell_key','instruction_ref'):return value
    if key=='report_json':
        return json.dumps(shift_fixture(json.loads(value),offset),sort_keys=True,separators=(',',':'))
    def day(match):
        try:return (datetime.strptime(match[0],'%Y-%m-%d')+timedelta(days=offset)).strftime('%Y-%m-%d')
        except ValueError:return match[0]
    def compact(match):
        try:return (datetime.strptime(match[0],'%Y%m%d')+timedelta(days=offset)).strftime('%Y%m%d')
        except ValueError:return match[0]
    value=re.sub(r'20\d{2}-\d{2}-\d{2}',day,value)
    return re.sub(r'(?<!\d)20\d{6}(?!\d)',compact,value)


def authorize_fixture(value,sport):
    host={'boat':'www.boatrace.jp','autorace':'autorace.jp','keirin':'keirin.jp','horse':'www.jra.go.jp'}[sport]
    rights='OWNER_PERSONAL_OFFICIAL_HTML_ANALYSIS_20261104' if sport=='boat' else fixtures.capture.official_rights_ref(sport)
    if isinstance(value,dict):
        for key,child in list(value.items()):
            value[key]=rights if key=='source_rights_ref' else authorize_fixture(child,sport)
    elif isinstance(value,list):
        for n,child in enumerate(value):value[n]=authorize_fixture(child,sport)
    elif isinstance(value,str) and (value.startswith('synthetic:') or value.startswith('https://example.test/') or value.startswith('fictional-fixture-provider-') or value=='fictional-weather-source'):
        return 'https://'+host+'/fixture/'+sha256(value.encode()).hexdigest()
    return value


@lru_cache(maxsize=4)
def baseline_training(order=False,carrier=False):
    rows=[]
    for cell in registry.cells():
        if cell['group']=='seller' or cell['sport'] in ('autorace','keirin') and cell['model_id']==LEARNED_ID:continue
        current=native_records(cell['model_id'],cell['sport'])
        offset=(datetime(2030,1,1).date()-datetime.fromisoformat(current[0]['as_of']).date()).days
        rows.extend(shift_fixture(current,offset))
    for sport,case in (('autorace',fixtures.auto_case()),('keirin',fixtures.keirin_case())):
        converted=api.case_inputs(case,now=fixtures.auto.NOW)
        source=next(r['native_payload'] for r in converted['requests'] if r['cell_key']==sport+'/'+LEARNED_ID)
        for n in range(8):
            payload=shift_fixture(deepcopy(source),n-14);info=registry.identity(LEARNED_ID,sport,payload)
            cutoff=datetime.fromisoformat(info['race_cutoff_at']);asof=datetime.fromisoformat(info['as_of'])
            result=dict(sport=sport,race_id=info['race_id'],status='settled',ordered_top3=[1,2,3],roster=info['roster'],
                identity_verified=True,captured_at=(cutoff+timedelta(minutes=1)).isoformat(),published_at=None,
                source_ref='https://'+('autorace.jp' if sport=='autorace' else 'keirin.jp')+'/fixture/result/'+str(n),
                source_rights_ref=fixtures.capture.official_rights_ref(sport),source_sha256=f'{n+1:064x}',
                payout_per_100_yen=1500,refund_numbers=[],closed_at=info['race_cutoff_at'],reason='ORDINARY_SETTLED_RESULT')
            rows.append(dict(model_id=LEARNED_ID,sport=sport,race_id=info['race_id'],stage=info['stage'],scope=info['scope'],
                as_of=info['as_of'],cutoff_at=info['cutoff_at'],native_payload=payload,input_sha256=digest(payload),
                input_saved_at=(asof+timedelta(seconds=1)).isoformat(),result=result))
    for row in rows:
        row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['scope']=row['scope']
        if 'scope' in row['native_payload'].get('snapshot',{}):row['native_payload']['snapshot']['scope']=row['scope']
        payload=row['native_payload']
        if registry.group(row['model_id'])=='boat_observed':
            for source in payload['snapshot']['sources']:
                if source['source_url'].startswith('synthetic:'):
                    source['source_url']='https://example.test/authored-history/'+sha256(source['source_url'].encode()).hexdigest()
        if registry.group(row['model_id'])=='autorace_personal':
            payload['registered_roster']['native_input_sha256']=digest(payload['snapshot'])
        if registry.group(row['model_id'])=='boat_pdca':
            for item in payload['rows']:item['report_sha256']=sha256(item['report_json'].encode()).hexdigest()
        kind=registry.group(row['model_id']);hashes=set();refs=set()
        if kind=='boat_full':
            refs.update(e['source_ref'] for e in payload['snapshot']['entrants'])
            if payload['snapshot'].get('conditions_source') is not None:refs.add(payload['snapshot']['conditions_source'])
        elif kind in ('boat_ab','boat_clite','boat_tactical'):
            source=payload.get('source',payload.get('base_source',{}))
            hashes.update((source.get('program_source_sha256'),source.get('beforeinfo_source_sha256')))
            if kind=='boat_clite':hashes.add(payload['extra']['source_sha256'])
            if kind=='boat_tactical':
                hashes.update(h['source_receipt']['official_source_sha256'] for h in payload['histories'])
                hashes.add(payload['venue']['official_source_sha256'])
        elif kind=='boat_pdca':
            hashes.update((payload['facts']['source_sha256'],payload['facts']['program_sha256']))
            for item in payload['rows']:hashes.update((json.loads(item['report_json'])['source_sha256'],item['report_sha256']))
        evidence=payload.setdefault('source_evidence',[])
        for source_sha in hashes:
            evidence.append(dict(source_ref='synthetic://authored-baseline/'+str(source_sha),source_sha256=source_sha,
                source_rights_ref='AUTHORED_NATIVE_FIXTURE',captured_at=row['as_of']))
        for ref in refs:
            evidence.append(dict(source_ref=ref,source_sha256='a'*64,source_rights_ref='AUTHORED_NATIVE_FIXTURE',captured_at=row['as_of']))
        authorize_fixture(row,row['sport'])
        if kind=='autorace_personal':payload['registered_roster']['native_input_sha256']=digest(payload['snapshot'])
        row['input_sha256']=digest(payload)
        if row['result'].get('status')=='rank_confirmed':
            row['result']={k:v for k,v in row['result'].items() if k in LEGACY_OBSERVATION_FIELDS}
            row['result'].update(status='settled',payout_per_100_yen=1500,reason='ORDINARY_SETTLED_RESULT')
            if 'result_observation' in row:row['result_observation']=deepcopy(row['result'])
    if carrier:rows=[r for r in rows if r['sport']=='boat']
    research._source_refs(set().union(*(_sources(r) for r in rows)))
    training=fit(rows,now=FIT_AT,allow_source=lambda *_:True,allow_training=lambda *_:True,allow_order_only=order)
    assert len(training['models'])==(14 if carrier else 30)
    refs=set().union(*(_sources(r) for r in rows))
    owner=research.issue_decision(source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,
        source_refs=sorted(refs),intake_sha256=training['source_intake_sha256'],registry_sha256=training['registry_sha256'],
        now=FIT_AT,expires_at=FIT_AT+timedelta(hours=1),label_evaluation_scope=EVALUATION_SCOPE if order else None)
    training.update(training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=digest(owner),
        source_content_sha256=CONTENT,venue_dataset_sha256=POINTER['dataset_sha256'])
    training['training_sha256']=digest({k:v for k,v in training.items() if k!='training_sha256'});verify_training(training)
    return training,owner


class SourcePacketBaselineV2Tests(unittest.TestCase):
    def setUp(self):
        self.old=fixtures.SourcePacketFreezeTests('runTest');self.old.setUp();self.addCleanup(self.old.doCleanups)
        self.root=self.old.root;self.repo=self.old.repo;self.env=self.old.env;self.now=fixtures.auto.NOW
        self.pin=dict(id=900,digest='sha256:'+'b'*64,run_id=40,head_sha='c'*40)
        self.carrier_pin=dict(id=700,digest='sha256:'+'d'*64,run_id=39,head_sha='e'*40)
    def manifest(self,cases=None):
        cases=cases or [fixtures.auto_case(),fixtures.keirin_case()]
        manifest,_,_=self.old.sealed(fixtures.packet(cases));manifest.update(schema=SCHEMA,
            maximum_races_per_sport={c['sport']:8 for c in cases},baseline_artifacts={c['sport']:deepcopy(self.pin) for c in cases},carrier_artifact=deepcopy(self.carrier_pin))
        return manifest
    def test_exact_v2_per_sport_pins_and_v1_conversion_golden(self):
        value=self.manifest();path=self.root/'input.json';path.write_text(json.dumps(value))
        self.assertEqual(api.load_manifest(path,now=self.now),value)
        for change in ({'baseline_artifacts':{}},{'baseline_artifacts':{'autorace':self.pin}},
                {'baseline_artifacts':dict(value['baseline_artifacts'],horse=self.pin)},
                {'baseline_artifacts':{s:dict(self.pin,id=True) for s in ('autorace','keirin')}}):
            path.write_text(json.dumps(dict(value,**change)))
            with self.subTest(change=change),self.assertRaises(ValueError):api.load_manifest(path,now=self.now)
        self.assertEqual(digest(api.case_inputs(fixtures.auto_case(),now=self.now)),
            '87bbfb2e6692700b2fb9a3a92e0cb4ace4a21746e44525615325f000069a78c7')
        self.assertEqual(digest(api.case_inputs(fixtures.keirin_case(),now=self.now)),
            '5952ead26af42cd27d33f8a7190ef7f280a0e35b9554df7a8968ff29cfba3619')

    def baseline(self,*,order=False,receipt_at=None):
        training,owner=baseline_training(order)
        folder=self.root/('baseline-order' if order else 'baseline-cash')
        if not folder.exists():seal_candidate(dict(training=training,owner_research_record=owner,excluded=[],summary=dict(
            state='FITTED_SHADOW_ONLY',fitted_model_count=30,production_promoted=False,actual_purchases=False)),folder)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc','learning.json','summary.json'):archive.writestr(name,(folder/name).read_bytes())
        raw=stream.getvalue();actual=dict(id=900,name='all-existing-model-learning-40-1',expired=False,size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(),created_at=(receipt_at or FIT_AT+timedelta(seconds=2)).isoformat(),
            expires_at=(self.now+timedelta(days=7)).isoformat(),workflow_run=dict(id=40,head_sha='c'*40,
                repository_id=1416489937,head_repository_id=1416489937))
        self.pin=dict(id=900,digest=actual['digest'],run_id=40,head_sha='c'*40)
        return raw,actual

    def carrier(self):
        if hasattr(self,'_carrier_pair'):return self._carrier_pair
        training,owner=baseline_training(False,True);folder=self.root/'carrier'
        if not folder.exists():seal_candidate(dict(training=training,owner_research_record=owner,excluded=[],summary=dict(
            state='FITTED_SHADOW_ONLY',fitted_model_count=14,production_promoted=False,actual_purchases=False)),folder)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc','learning.json','summary.json'):archive.writestr(name,(folder/name).read_bytes())
        raw=stream.getvalue();actual=dict(id=700,name='all-existing-model-learning-39-1',expired=False,size_in_bytes=len(raw),
            digest='sha256:'+sha256(raw).hexdigest(),created_at=(FIT_AT+timedelta(seconds=2)).isoformat(),
            expires_at=(self.now+timedelta(days=7)).isoformat(),workflow_run=dict(id=39,head_sha='e'*40,
                repository_id=1416489937,head_repository_id=1416489937))
        self.carrier_pin=dict(id=700,digest=actual['digest'],run_id=39,head_sha='e'*40)
        self._carrier_pair=(raw,actual)
        return self._carrier_pair

    def generated(self,*,order=False,cases=None,receipt_at=None):
        raw,actual=self.baseline(order=order,receipt_at=receipt_at);carrier_raw,carrier_actual=self.carrier();manifest=self.manifest(cases)
        root=self.root/'v2-output'
        with patch.object(api,'ROOT',self.repo),patch.object(api,'utc_now',return_value=self.now), \
                patch.object(api.future,'metadata',side_effect=lambda i:carrier_actual if i==700 else actual), \
                patch.object(api.future,'gh',side_effect=lambda p:carrier_raw if '/700/' in p else raw):
            status=api.generate(700,root,self.env,manifest)
        proof=dict(status,schema=api.STATUS,workflow_run_id=42,expected_head_sha=fixtures.HEAD)
        api._write(root.with_name(root.name+'.generation.json'),api.future.wire(proof))
        api._write(root.with_name(root.name+'.status.json'),api.future.wire(proof))
        return root,status,manifest,raw,actual

    def test_thirty_model_baseline_attaches_only_existing_ranker_with_three_source_closure(self):
        root,status,manifest,raw,actual=self.generated()
        self.assertTrue(status['ready']);self.assertEqual(status['baseline_attachment_count'],2)
        self.assertEqual(status['captured_native_input_count'],11);self.assertEqual(status['forecast_partition_count'],0)
        for record in api.local_records(root):
            sport,race=api.record_identity(record)
            for capsule in record['captured_native_inputs']:
                payload=capsule['native_payload']
                if capsule['cell_key']==sport+'/'+LEARNED_ID:
                    self.assertEqual(payload['baseline_attachment']['pin']['id'],900)
                    closure=payload['baseline_attachment']['source_metadata']['source_packet_closure']
                    self.assertEqual(len(closure['http_metadata']),2);self.assertEqual(closure['rendered_dom']['kind'],'RENDERED_DOM')
                    self.assertNotIn('status',closure['rendered_dom'])
                    self.assertEqual(payload['snapshot']['race']['as_of'],self.now.isoformat())
                    self.assertEqual(closure['http_metadata'][0]['response_received_at'],
                        closure['http_metadata'][0]['original_ledger_entry']['body_captured_at'])
                else:self.assertNotIn('baseline_attachment',payload);self.assertNotIn('learned_model',payload)
        for secret in ('source_lineage','owner_research_record','source_metadata','learned_model','source_url'):
            self.assertNotIn(secret,json.dumps(status))
        encoded=fixtures.packed(root);native=dict(id=801,name='all-existing-model-pairs-42-900003',expired=False,
            size_in_bytes=len(encoded),digest='sha256:'+sha256(encoded).hexdigest(),created_at=(self.now+timedelta(seconds=1)).isoformat(),
            expires_at=(self.now+timedelta(days=7)).isoformat(),workflow_run=dict(id=42,head_sha=fixtures.HEAD,
                repository_id=1416489937,head_repository_id=1416489937))
        reads=[]
        with patch.object(api,'ROOT',self.repo),patch.object(api,'utc_now',return_value=self.now+timedelta(seconds=5)), \
                patch.object(api.future,'metadata',side_effect=lambda i:reads.append(i) or (self.carrier()[1] if i==700 else actual if i==900 else native)), \
                patch.object(api.future,'gh',side_effect=lambda p:self.carrier()[0] if '/700/' in p else raw if '/900/' in p else encoded):
            checked=api.readback(801,root,self.env,manifest=manifest)
        self.assertTrue(checked['independent_pre_cutoff_receipt_verified'])
        self.assertTrue(checked['independent_baseline_artifact_receipts_verified']);self.assertIn(900,reads)
        self.assertEqual(checked['baseline_attachment_count'],2)

    def test_resealed_feature_change_cannot_become_original_source_packet_input(self):
        from race_ai import all_existing_model_future_baseline as helper
        original=helper.attach
        def corrupt(payload,context,**kwargs):
            changed=deepcopy(payload)
            feature=next(iter(changed['snapshot']['participants'][0]['features'].values()))
            feature['value']=.123456
            return original(changed,context,**kwargs)
        with patch.object(helper,'attach',side_effect=corrupt),self.assertRaisesRegex(ValueError,'BASELINE_ORIGINAL_NATIVE'):
            self.generated()

    def test_new_source_must_start_after_baseline_and_companions_cannot_borrow_primary_clock(self):
        raw,actual=self.baseline();carrier_raw,carrier_actual=self.carrier()
        for kind in ('companion','dom','whole-card'):
            case=fixtures.auto_case();meta=deepcopy(actual)
            if kind=='companion':
                case['capture_metadata']['ledger'][1]['request_started_at']=(self.now-timedelta(seconds=44)).isoformat()
                meta['created_at']=(self.now-timedelta(seconds=43)).isoformat()
            elif kind=='dom':meta['created_at']=(self.now-timedelta(seconds=43)).isoformat()
            else:meta['created_at']=(self.now-timedelta(seconds=15)).isoformat()
            manifest=self.manifest([case]);target=self.root/kind
            expected='BASELINE_DOM_SOURCE_CLOCK' if kind=='dom' else 'BASELINE_COMPANION_SOURCE_CLOCK'
            with patch.object(api,'ROOT',self.repo),patch.object(api,'utc_now',return_value=self.now), \
                    patch.object(api.future,'metadata',side_effect=lambda i:carrier_actual if i==700 else meta), \
                    patch.object(api.future,'gh',side_effect=lambda p:carrier_raw if '/700/' in p else raw), \
                    self.assertRaisesRegex(ValueError,expected):
                api.generate(700,target,self.env,manifest)
            self.assertFalse(target.exists())

    def test_wrong_baseline_pin_missing_fit_and_same_carrier_hold_without_new_capsules(self):
        raw,actual=self.baseline();carrier_raw,carrier_actual=self.carrier();original=self.manifest()
        for kind in ('digest','head','carrier','missing_sport','wrong_carrier_arg'):
            manifest=deepcopy(original);meta=deepcopy(actual);wire=raw;candidate=700
            if kind=='digest':manifest['baseline_artifacts']['autorace']['digest']='sha256:'+'f'*64
            elif kind=='head':meta['workflow_run']['head_sha']='e'*40
            elif kind=='carrier':manifest['baseline_artifacts']['autorace']['id']=700
            elif kind=='wrong_carrier_arg':candidate=900
            elif kind=='missing_sport':
                wire=carrier_raw;meta.update(digest='sha256:'+sha256(wire).hexdigest(),size_in_bytes=len(wire))
                for pin in manifest['baseline_artifacts'].values():pin['digest']=meta['digest']
            with patch.object(api,'ROOT',self.repo),patch.object(api,'utc_now',return_value=self.now), \
                    patch.object(api.future,'metadata',side_effect=lambda i:carrier_actual if i==700 else meta), \
                    patch.object(api.future,'gh',side_effect=lambda p:carrier_raw if '/700/' in p else wire), \
                    self.assertRaises(ValueError):
                api.generate(candidate,self.root/('out-'+kind),self.env,manifest)
            self.assertFalse((self.root/('out-'+kind)).exists())

    def test_original_order_only_owner_scope_is_accepted_without_new_training_or_cash_claim(self):
        root,status,manifest,raw,actual=self.generated(order=True)
        self.assertTrue(status['ready']);self.assertEqual(status['baseline_attachment_count'],2)
        for record in api.local_records(root):
            attached=next(c['native_payload'] for c in record['captured_native_inputs'] if 'baseline_attachment' in c['native_payload'])
            owner=attached['baseline_attachment']['owner_research_record']
            self.assertEqual(owner['schema'],research.ORDER_SCHEMA)
            self.assertEqual(owner['decision']['label_evaluation_scope'],EVALUATION_SCOPE)

if __name__=='__main__':unittest.main()
