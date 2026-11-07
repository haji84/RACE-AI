"""Authored thirty-cell candidates and frozen inputs; no real source operation."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_research as research
from race_ai import boat_all_model_store as origin_store
from race_ai.all_existing_model_learning import fit,verify_training
from race_ai.all_existing_model_pairs import make_private_pairs
from race_ai.boat_venue_learning import seal_candidate
from race_ai.official_order_only_result import EVALUATION_SCOPE
from scripts import all_existing_model_native_future as future
from scripts import all_existing_model_learning as learning
from tests import test_all_existing_model_native_future as boat
from tests.test_all_existing_model_common_eight_per_sport import common_records,FIXTURE_NOW
from tests.test_all_existing_model_matrix import _shift_dates
from tests.test_all_existing_model_learning import observed_records
from tests.test_boat_venue_research import SOURCE,CONTENT
from tests.test_boat_venue_learning import POINTER

KEY=bytes(range(32));NOW=datetime(2030,2,2,14,10,tzinfo=timezone.utc)


def metadata(ident,name,raw,*,saved,run=42,head='a'*40):
    return dict(id=ident,name=name,expired=False,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
        created_at=saved.isoformat(),expires_at=(NOW+timedelta(days=7)).isoformat(),workflow_run=dict(
            id=run,head_sha=head,repository_id=1416489937,head_repository_id=1416489937))


@lru_cache(maxsize=1)
def fitted():
    rows,cohort=learning._select_common_eight_per_sport(common_records(),now=FIXTURE_NOW)
    trained=fit(rows,now=FIXTURE_NOW,allow_order_only=True,allow_source=lambda *_:True,allow_training=lambda *_:True)
    binding=dict(source_pointer=SOURCE,state_content_sha256=CONTENT,dataset_pointer=POINTER,
        source_refs=sorted(set().union(*(learning._record_source_refs(row) for row in rows))),
        intake_sha256=learning._intake_identity(rows,common_cohort=cohort),
        registry_sha256=registry.registry_sha256(),label_evaluation_scope=EVALUATION_SCOPE)
    with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode()):
        owner=research.issue_decision(**binding,now=FIXTURE_NOW,expires_at=NOW+timedelta(days=30))
    trained.update(cohort,training_basis='OWNER_PERSONAL_RESEARCH',owner_research_decision_sha256=digest(owner),
        owner_bound_intake_sha256=binding['intake_sha256'],source_content_sha256=CONTENT,
        venue_dataset_sha256=POINTER['dataset_sha256'],intake_identity_semantics='ORIGINAL_COMMON_EIGHT_PER_SPORT_V1')
    trained['training_sha256']=digest({key:value for key,value in trained.items() if key!='training_sha256'})
    verify_training(trained)
    baseline={}
    from race_ai.four_sport_learning import LEARNED_ID
    for sport in ('boat','autorace','keirin','horse'):
        old=fit([row for row in rows if row['sport']==sport and row['model_id']==LEARNED_ID],
            now=FIXTURE_NOW-timedelta(days=1),allow_order_only=True,allow_source=lambda *_:True,allow_training=lambda *_:True)
        baseline[sport]=old['models'][sport+'/'+LEARNED_ID]['native_training']
    source_rows=json.loads(json.dumps(observed_records()).replace('2030-04-01','2030-01-01').replace('20300401','20300101'))
    for row in source_rows:row['input_sha256']=digest(row['native_payload'])
    borrower=fit(source_rows,now=FIXTURE_NOW-timedelta(days=2))
    return trained,owner,baseline,borrower


def native_requests(baselines):
    from race_ai.four_sport_learning import LEARNED_ID
    requests=boat.requests(day='2030-02-02',cutoff='23:59:00')+boat.extra_requests(day='2030-02-02')
    for request in requests:
        native=request['native_payload'];native['scope']='SYNTHETIC_ONLY'
        if 'scope' in native.get('snapshot',{}):native['snapshot']['scope']='SYNTHETIC_ONLY'
        info=registry.identity(request['cell_key'].split('/',1)[1],'boat',native)
        request['native_payload']=json.loads(json.dumps(native).replace(info['race_cutoff_at'],'2030-02-02T23:59:00+09:00'))
    for row in common_records(1):
        if row['sport']=='boat':continue
        native=_shift_dates(row['native_payload'],18);sport=row['sport'];mid=row['model_id']
        if registry.group(mid)=='autorace_personal':
            native['registered_roster']['native_input_sha256']=digest(native['snapshot'])
        info=registry.identity(mid,sport,native)
        native=json.loads(json.dumps(native).replace(info['race_cutoff_at'],'2030-02-02T23:59:00+09:00'))
        if registry.group(mid)=='autorace_personal':
            native['registered_roster']['native_input_sha256']=digest(native['snapshot'])
        requests.append(dict(cell_key=sport+'/'+mid,native_payload=native))
    for request in requests:
        sport,mid=request['cell_key'].split('/',1)
        if mid==LEARNED_ID:request['native_payload']['learned_model']=deepcopy(baselines[sport])
    return requests


class NativeFutureV3ManifestTests(unittest.TestCase):
    def test_explicit_v3_pins_do_not_change_v1_v2_contracts(self):
        value=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3',candidate_cell_count=30,
            candidate_artifact_id=200,candidate_digest='sha256:'+'a'*64,
            source_input_artifacts=[dict(id=100,digest='sha256:'+'b'*64,run_id=8,head_sha='c'*40)])
        self.assertEqual(future.validate_manifest(value),value)
        for change in (dict(candidate_cell_count=True),dict(candidate_cell_count=31),dict(extra=1),
                       dict(source_input_artifacts=[]),dict(source_input_artifacts=value['source_input_artifacts']*2)):
            with self.subTest(change=change),self.assertRaises(ValueError):future.validate_manifest(dict(value,**change))


class NativeFutureOriginTests(unittest.TestCase):
    """The separate original-proof envelope needs no model fitting."""
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.temp=Path(temporary.name)
        fixture_key=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        fixture_key.start();self.addCleanup(fixture_key.stop)
        self.root=self.temp/'future';self.env=dict(run_id=42,head_sha='d'*40,temp=self.temp)
        self.manifest=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3',candidate_cell_count=30,
            candidate_artifact_id=200,candidate_digest='sha256:'+'a'*64,
            source_input_artifacts=[dict(id=100,digest='sha256:'+'b'*64,run_id=8,head_sha='c'*40)])
        self.audit=dict(schema='SYNTHETIC_ORIGINAL_PROOF',original_generated_at='2030-02-02T14:00:00+00:00',
            selected_at=(NOW-timedelta(seconds=5)).isoformat())
        self.generation=dict(manifest_sha256=digest(self.manifest),source_audit_sha256=digest(self.audit),
            workflow_run_id=42,expected_head_sha='d'*40,cutoff_at=(NOW+timedelta(hours=1)).isoformat(),
            local_record_sha256=['1'*64],local_member_sha256={'2'*64+'/learning.enc':'3'*64},origin_generated_at=NOW.isoformat())
        self.generation['owner_generation_mac']=future._generation_mac_v3(self.generation)
        self.mapping={};self.now=NOW+timedelta(seconds=4)
        for change in (patch.object(future.future,'utc_now',side_effect=lambda:self.now),
            patch.object(future.future,'metadata',side_effect=lambda ident:json.loads(self.mapping[str(ident)])),
            patch.object(future.future,'gh',side_effect=lambda route:self.mapping[route])):
            change.start();self.addCleanup(change.stop)
    def seal(self):
        future._seal_origin_v3(self.manifest,self.generation,self.audit,self.root,self.env)
        folder=self.root.with_name(self.root.name+'.origin');raw=boat.zipped(folder)
        actual=metadata(202,'all-native-future-origin-42-900010',raw,saved=NOW+timedelta(seconds=2),head='d'*40)
        self.mapping['202']=json.dumps(actual).encode();self.mapping['actions/artifacts/202/zip']=raw
        return folder,actual
    def test_origin_is_private_one_member_cipher_and_independently_restores_original_bundle(self):
        folder,actual=self.seal();self.assertEqual({p.name for p in folder.iterdir()},{'origin.enc'})
        self.assertEqual(folder.stat().st_mode&0o777,0o700)
        raw=(folder/'origin.enc').read_bytes();self.assertEqual((folder/'origin.enc').stat().st_mode&0o777,0o600)
        bundle=origin_store.open_forecasts(raw,key=KEY)
        self.assertEqual(set(bundle),{'schema','manifest','generation','source_audit'})
        self.assertEqual(bundle['generation'],self.generation);self.assertEqual(bundle['source_audit'],self.audit)
        self.assertEqual(origin_store.forecast_header(raw)['round_no'],900010)
        admitted=future._origin_artifact_v3(202,self.manifest,self.root,self.env,self.generation,self.audit)
        self.assertTrue(admitted['independent_origin_receipt_verified'])
        self.assertEqual(admitted['origin_artifact_digest'],actual['digest'])
    def test_origin_wrong_head_late_receipt_tamper_extra_member_and_local_replacement_reject(self):
        folder,actual=self.seal();valid=self.mapping['202'];original_zip=self.mapping['actions/artifacts/202/zip']
        for reason,bad,clock in (
                ('ORIGIN_ACTUAL_IDENTITY',dict(actual,workflow_run=dict(actual['workflow_run'],head_sha='e'*40)),self.now),
                ('ORIGIN_ACTUAL_IDENTITY',dict(actual,expired=True),self.now),
                ('ORIGIN_ACTUAL_BYTES',dict(actual,digest='sha256:'+'f'*64),self.now),
                ('ORIGIN_ACTUAL_BYTES',dict(actual,size_in_bytes=actual['size_in_bytes']+1),self.now),
                ('ORIGIN_PRE_CUTOFF_CLOCK_BINDING',dict(actual,created_at=(NOW-timedelta(days=1)).isoformat()),self.now),
                ('ORIGIN_ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED',
                    dict(actual,created_at=(NOW+timedelta(minutes=51)).isoformat()),NOW+timedelta(minutes=52))):
            self.mapping['202']=json.dumps(bad).encode()
            self.now=clock
            with self.subTest(metadata=bad),self.assertRaisesRegex(ValueError,reason):
                future._origin_artifact_v3(202,self.manifest,self.root,self.env,self.generation,self.audit)
        self.mapping['202']=valid;self.now=NOW+timedelta(seconds=4)
        original_cipher=(folder/'origin.enc').read_bytes()
        for members in ({'origin.enc':original_cipher[:-1]+bytes([original_cipher[-1]^1])},
                        {'origin.enc':original_cipher,'source.json':b'never publish raw proof'}):
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as archive:
                for name,raw in members.items():archive.writestr(name,raw)
            raw=buffer.getvalue();self.mapping['actions/artifacts/202/zip']=raw
            changed=dict(actual,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
            self.mapping['202']=json.dumps(changed).encode()
            with self.subTest(members=list(members)),self.assertRaises(ValueError):
                future._origin_artifact_v3(202,self.manifest,self.root,self.env,self.generation,self.audit)
        self.mapping['202']=valid;self.mapping['actions/artifacts/202/zip']=original_zip
        replacement=deepcopy(self.audit);replacement['original_generated_at']='1999-01-01T00:00:00Z'
        changed=origin_store.open_forecasts(original_cipher,key=KEY);changed['source_audit']=replacement
        (folder/'origin.enc').write_bytes(origin_store.seal_forecasts(changed,run_id='42',round_no=900010,key=KEY))
        with self.assertRaisesRegex(ValueError,'ORIGIN_BUNDLE_BINDING'):
            future._origin_artifact_v3(202,self.manifest,self.root,self.env,self.generation,self.audit)
    def test_main_outputs_origin_names_and_forwards_optional_receipt_without_plaintext(self):
        manifest=self.temp/'manifest.json';manifest.write_text(json.dumps(self.manifest))
        output=self.temp/'outputs';result=dict(ready=True,forecast_partition_count=30,origin_ready=True,
            origin_artifact_name='all-native-future-origin-42-900010',independent_origin_receipt_verified=True,
            complete_independent_receipts_verified=True,origin_local_only=False)
        with (patch.object(future.future,'environment',return_value=self.env),
                patch.object(future,'readback',return_value=result) as mocked,
                patch.dict(os.environ,GITHUB_OUTPUT=str(output)),redirect_stdout(io.StringIO()) as stdout):
            self.assertEqual(future.main(['--manifest',str(manifest),'--out-dir',str(self.root),
                '--readback-artifact','201','--readback-origin-artifact','202']),0)
        self.assertEqual(mocked.call_args.kwargs['readback_origin_artifact'],202)
        self.assertIn('origin_ready=true\n',output.read_text())
        self.assertIn('origin_artifact_name=all-native-future-origin-42-900010\n',output.read_text())
        self.assertTrue(json.loads(stdout.getvalue())['complete_independent_receipts_verified'])
        self.assertNotIn('owner_generation_mac',stdout.getvalue());self.assertNotIn('source_audit',stdout.getvalue())
    def test_origin_plain_limit_rejects_before_writing_or_replacing_an_original(self):
        audit=dict(self.audit,oversize='x'*origin_store.MAX_PLAIN)
        with self.assertRaisesRegex(ValueError,'ORIGIN_PLAIN_BOUND'):
            future._seal_origin_v3(self.manifest,self.generation,audit,self.root,self.env)
        self.assertFalse(self.root.with_name(self.root.name+'.origin').exists())
        folder,_=self.seal();before=(folder/'origin.enc').read_bytes()
        with self.assertRaises(ValueError):future._seal_origin_v3(self.manifest,self.generation,self.audit,self.root,self.env)
        self.assertEqual((folder/'origin.enc').read_bytes(),before)


class NativeFutureV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.trained,cls.owner,cls.baselines,cls.borrower=fitted()
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.temp=Path(temporary.name)
        environment=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment.start();self.addCleanup(environment.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider/GitHub GET forbidden'))
        network.start();self.addCleanup(network.stop)
        candidate=self.temp/'candidate'
        seal_candidate(dict(training=deepcopy(self.trained),owner_research_record=deepcopy(self.owner),excluded=[],
            summary=dict(state='FITTED_SHADOW_ONLY',fitted_model_count=30,actual_purchases=False,production_promoted=False)),candidate)
        raw=boat.zipped(candidate);self.candidate=metadata(200,'all-existing-model-learning-7-1',raw,
            saved=FIXTURE_NOW+timedelta(minutes=1),run=7)
        self.context=dict(training=deepcopy(self.trained),receipt=deepcopy(self.candidate))
        self.requests=native_requests(self.baselines);self.now=NOW;self.root=self.temp/'future'
        self.mapping={'actions/artifacts/200':json.dumps(self.candidate).encode(),'actions/artifacts/200/zip':raw}
        context=dict(training=deepcopy(self.borrower),receipt=metadata(90,'all-existing-model-learning-6-1',b'older fixture',
            saved=FIXTURE_NOW-timedelta(days=1),run=6))
        self.source_context=context
        source=self.temp/'source'
        make_private_pairs(context,self.requests,source,now=NOW-timedelta(minutes=6),allow_source=lambda *_:True)
        (source/'summary.json').unlink();source_raw=boat.zipped(source)
        self.source=metadata(100,'all-existing-model-pairs-8-1',source_raw,saved=NOW-timedelta(minutes=5),run=8,head='c'*40)
        self.mapping.update({'actions/artifacts/100':json.dumps(self.source).encode(),'actions/artifacts/100/zip':source_raw})
        self.manifest=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3',candidate_cell_count=30,candidate_artifact_id=200,
            candidate_digest=self.candidate['digest'],source_input_artifacts=[dict(id=100,digest=self.source['digest'],run_id=8,head_sha='c'*40)])
        self.env=dict(run_id=42,head_sha='d'*40,temp=self.temp)
        self.patches=[patch.object(future.future,'utc_now',side_effect=lambda:self.now),
            patch.object(future.future,'gh',side_effect=lambda route:self.mapping[route]),
            patch.object(future.future,'metadata',side_effect=lambda ident:json.loads(self.mapping['actions/artifacts/'+str(ident)]))]
        for change in self.patches:change.start();self.addCleanup(change.stop)
    def records(self):return future.source_v3(self.manifest)[1]
    def test_all_four_sports_real_codec_forecasts_preserve_capsules_and_actual_partial_binding(self):
        before=deepcopy(self.requests);result=future.generate(self.manifest,self.root,self.env)
        self.assertTrue(result['ready'],result);self.assertEqual(result['forecast_partition_count'],30)
        self.assertTrue(result['all_thirty_cells_produced'])
        self.assertEqual(result['forecast_counts_by_sport'],dict(boat=14,autorace=6,keirin=5,horse=5))
        local=future.local_records_v3(self.root)
        self.assertEqual({p['cell_key']:p['native_payload'] for p in local},
                         {request['cell_key']:request['native_payload'] for request in before})
        self.assertEqual({p['generated_at'] for p in local},{NOW.isoformat()});self.assertEqual(self.requests,before)
        raw=boat.zipped(self.root);self.mapping['actions/artifacts/201/zip']=raw
        self.mapping['actions/artifacts/201']=json.dumps(metadata(201,'all-existing-model-pairs-42-900004',raw,
            saved=NOW+timedelta(seconds=2),head='d'*40)).encode();self.now+=timedelta(seconds=4)
        origin_folder=self.root.with_name(self.root.name+'.origin');origin_raw=boat.zipped(origin_folder)
        self.assertTrue(result['origin_ready']);self.assertFalse(result['independent_origin_receipt_verified'])
        self.assertEqual({p.name for p in origin_folder.iterdir()},{'origin.enc'})
        self.mapping['actions/artifacts/202/zip']=origin_raw
        self.mapping['actions/artifacts/202']=json.dumps(metadata(202,'all-native-future-origin-42-900010',origin_raw,
            saved=NOW+timedelta(seconds=3),head='d'*40)).encode()
        admitted=future.readback(201,self.manifest,self.root,self.env,readback_origin_artifact=202)
        self.assertTrue(admitted['independent_pre_cutoff_receipt_verified']);self.assertEqual(admitted['forecast_partition_count'],30)
        self.assertTrue(admitted['independent_origin_receipt_verified']);self.assertTrue(admitted['complete_independent_receipts_verified'])
        self.assertFalse(admitted['origin_local_only'])
        valid_origin=self.mapping['actions/artifacts/202'];actual_origin=json.loads(valid_origin)
        self.mapping['actions/artifacts/202']=json.dumps(dict(actual_origin,
            workflow_run=dict(actual_origin['workflow_run'],head_sha='e'*40))).encode()
        with self.assertRaisesRegex(ValueError,'ORIGIN_ACTUAL_IDENTITY'):
            future.readback(201,self.manifest,self.root,self.env,readback_origin_artifact=202)
        self.mapping['actions/artifacts/202']=json.dumps(dict(actual_origin,created_at=(NOW+timedelta(minutes=40)).isoformat())).encode()
        self.now=NOW+timedelta(minutes=41)
        with self.assertRaisesRegex(ValueError,'ORIGIN_ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED'):
            future.readback(201,self.manifest,self.root,self.env,readback_origin_artifact=202)
        self.mapping['actions/artifacts/202']=valid_origin;self.now=NOW+timedelta(seconds=4)
        bad=bytearray(origin_raw);bad[len(bad)//2]^=1;bad=bytes(bad)
        self.mapping['actions/artifacts/202/zip']=bad
        self.mapping['actions/artifacts/202']=json.dumps(dict(actual_origin,size_in_bytes=len(bad),
            digest='sha256:'+sha256(bad).hexdigest())).encode()
        with self.assertRaises(ValueError):future.readback(201,self.manifest,self.root,self.env,readback_origin_artifact=202)
        self.mapping['actions/artifacts/202/zip']=origin_raw;self.mapping['actions/artifacts/202']=valid_origin
        valid=self.mapping['actions/artifacts/201']
        self.mapping['actions/artifacts/201']=json.dumps(metadata(201,'all-existing-model-pairs-42-900004',raw,
            saved=NOW+timedelta(minutes=40),head='d'*40)).encode();self.now=NOW+timedelta(minutes=41)
        with self.assertRaisesRegex(ValueError,'ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED'):
            future.readback(201,self.manifest,self.root,self.env)
        self.mapping['actions/artifacts/201']=valid;self.now=NOW+timedelta(seconds=4)
        source_path=self.root.with_name(self.root.name+'.source.json');generation_path=self.root.with_name(self.root.name+'.generation.json')
        audit=json.loads(source_path.read_bytes());audit['original_source_partitions'][0]['original_generated_at']='1999-01-01T00:00:00Z'
        source_path.write_bytes(future.future.wire(audit));generation=json.loads(generation_path.read_bytes())
        generation['source_audit_sha256']=digest(audit);generation_path.write_bytes(future.future.wire(generation))
        with self.assertRaisesRegex(ValueError,'GENERATION_PROVENANCE_MAC'):future.readback(201,self.manifest,self.root,self.env)
    def test_missing_baseline_and_old_native_clock_hold_only_that_sport_without_retimestamping(self):
        records=self.records();before=deepcopy(records)
        from race_ai.four_sport_learning import LEARNED_ID
        for record in records:
            for capsule in record.get('captured_native_inputs',[]):
                if capsule['cell_key']=='horse/'+LEARNED_ID:
                    capsule['native_payload'].pop('learned_model');capsule['input_sha256']=digest(capsule['native_payload'])
        horse_records=[dict(generated_at=record['generated_at'],captured_native_inputs=[deepcopy(cap)
            for cap in record.get('captured_native_inputs',[]) if cap['cell_key'].startswith('horse/')]) for record in records]
        horse_records=[record for record in horse_records if record['captured_native_inputs']]
        prepared=future.prepare_requests_v3(self.context,horse_records,now=NOW)
        self.assertEqual(prepared['forecast_counts_by_sport']['horse'],0)
        self.assertEqual(prepared['held_sports']['horse']['reason'],'HOLD_MISSING_NATIVE_BASELINE')
        self.assertEqual(prepared['requests'],[]);self.assertFalse(prepared['all_thirty_cells_produced'])
        self.assertEqual(before[0]['generated_at'],records[0]['generated_at'])
        requests=deepcopy(self.requests)
        for request in requests:
            if request['cell_key']=='horse/'+LEARNED_ID:request['native_payload'].pop('learned_model')
        folder=self.temp/'partial-source'
        make_private_pairs(self.source_context,requests,folder,now=NOW-timedelta(minutes=6),allow_source=lambda *_:True)
        (folder/'summary.json').unlink();raw=boat.zipped(folder)
        actual=metadata(101,'all-existing-model-pairs-8-2',raw,saved=NOW-timedelta(minutes=5),run=8,head='c'*40)
        self.mapping['actions/artifacts/101']=json.dumps(actual).encode();self.mapping['actions/artifacts/101/zip']=raw
        self.manifest['source_input_artifacts']=[dict(id=101,digest=actual['digest'],run_id=8,head_sha='c'*40)]
        result=future.generate(self.manifest,self.root,self.env)
        self.assertTrue(result['ready']);self.assertEqual(result['forecast_partition_count'],25)
        self.assertFalse(result['all_thirty_cells_produced']);self.assertEqual(result['forecast_counts_by_sport']['horse'],0)
        raw=boat.zipped(self.root);self.mapping['actions/artifacts/201/zip']=raw
        self.mapping['actions/artifacts/201']=json.dumps(metadata(201,'all-existing-model-pairs-42-900004',raw,
            saved=NOW+timedelta(seconds=2),head='d'*40)).encode();self.now=NOW+timedelta(seconds=4)
        result=future.readback(201,self.manifest,self.root,self.env)
        self.assertEqual(result['forecast_partition_count'],25);self.assertFalse(result['all_thirty_cells_produced'])
        self.assertEqual(result['held_sports']['horse']['reason'],'HOLD_MISSING_NATIVE_BASELINE')
        self.assertFalse(result['independent_origin_receipt_verified']);self.assertFalse(result['complete_independent_receipts_verified'])
        self.assertTrue(result['origin_local_only'])
    def test_candidate_wait_missing_cells_conflicts_and_old_input_model_chronology_fail_closed(self):
        records=self.records()
        with self.assertRaisesRegex(ValueError,'CANDIDATE_NOT_YET_AVAILABLE'):
            future.prepare_requests_v3(self.context,records,now=FIXTURE_NOW+timedelta(minutes=1))
        duplicated=deepcopy(records);caps=next(r['captured_native_inputs'] for r in duplicated if r.get('captured_native_inputs'))
        bad=deepcopy(caps[0]);bad['native_payload']['fixture-conflict']=True;bad['input_sha256']=digest(bad['native_payload']);caps.append(bad)
        with self.assertRaisesRegex(ValueError,'CONFLICTING_SOURCE_CAPSULE'):
            future.prepare_requests_v3(self.context,duplicated,now=NOW)
        from race_ai.four_sport_learning import LEARNED_ID
        only_horse=[dict(generated_at=record['generated_at'],captured_native_inputs=[deepcopy(cap)
            for cap in record.get('captured_native_inputs',[]) if cap['cell_key'].startswith('horse/')]) for record in records]
        only_horse=[record for record in only_horse if record['captured_native_inputs']]
        result=future.prepare_requests_v3(self.context,only_horse+deepcopy(only_horse),now=NOW)
        self.assertEqual(len(result['requests']),5)
        old=deepcopy(only_horse)
        for record in old:
            for cap in record['captured_native_inputs']:
                if cap['cell_key']=='horse/'+LEARNED_ID:
                    cap['native_payload']['snapshot']['race']['as_of']=(FIXTURE_NOW-timedelta(seconds=1)).isoformat()
                    cap['captured_as_of']=cap['native_payload']['snapshot']['race']['as_of']
                    cap['input_sha256']=digest(cap['native_payload'])
        held=future.prepare_requests_v3(self.context,old,now=NOW)
        self.assertEqual(held['held_sports']['horse']['reason'],'HOLD_NATIVE_INPUT_PRECEDES_MODEL_CLOCK')
        incomplete=deepcopy(only_horse);incomplete[0]['captured_native_inputs'].pop()
        held=future.prepare_requests_v3(self.context,incomplete,now=NOW)
        self.assertEqual(held['held_sports']['horse']['reason'],'HOLD_INCOMPLETE_NATIVE_CELLS')
        replay=deepcopy(only_horse)
        replay[0].update(cell_key=replay[0]['captured_native_inputs'][0]['cell_key'],
            training=dict(training_sha256=self.trained['training_sha256']))
        held=future.prepare_requests_v3(self.context,replay,now=NOW)
        self.assertEqual(held['held_sports']['horse']['reason'],'HOLD_ALREADY_FROZEN_WITH_CANDIDATE')
    def test_source_pins_and_owner_scope_are_strict(self):
        wrong=deepcopy(self.manifest);wrong['source_input_artifacts'][0]['head_sha']='e'*40
        with self.assertRaises(ValueError):future.source_v3(wrong)
        for change in ('mac','scope','intake'):
            owner=deepcopy(self.owner);trained=deepcopy(self.trained)
            if change=='mac':owner['mac']='0'*64
            elif change=='scope':owner['decision']['label_evaluation_scope']='CASH'
            else:owner['decision']['intake_sha256']='f'*64
            if change!='mac':
                owner['mac']=research._mac(owner['decision'],schema=research.ORDER_SCHEMA)
                trained['owner_research_decision_sha256']=digest(owner)
                trained['training_sha256']=digest({key:value for key,value in trained.items() if key!='training_sha256'})
            with self.subTest(change=change),self.assertRaises(ValueError):
                future._training_v3(trained,owner,require_owner=True)


if __name__=='__main__':unittest.main()
