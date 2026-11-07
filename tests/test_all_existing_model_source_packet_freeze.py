"""Offline invented browser packets, real owner codec and no source requests."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import manual_official_capture as capture
from race_ai.boat_all_model_store import seal_forecasts
from tests import test_autorace_official_sparse_adapter as auto
from tests import test_keirin_official_sparse_adapter as keirin

try:
    freeze=importlib.import_module('scripts.all_existing_model_source_packet_freeze')
except ModuleNotFoundError:
    freeze=None

KEY=bytes(range(32))
HEAD='a'*40


def b64(raw):return base64.b64encode(raw).decode('ascii')


def auto_case(number=1,cutoff='10:58'):
    data=auto.fixture();data['metadata']['scope']='OPERATOR_SUPPLIED_RESEARCH'
    data['race']['body'].update(raceNo=number,telvoteTime=cutoff)
    request=auto.wire(dict(placeCode=3,raceDate='2030-01-15',raceNo=number))
    request_sha=sha256(request).hexdigest()
    data['metadata']['ledger'][0]['request_body_sha256']=request_sha
    data['metadata']['ledger'][1]['request_body_sha256']=request_sha
    auto.reseal_source(data,'race')
    dom=data['dom'].replace(b'1R',str(number).encode()+b'R').replace(b'10:58',cutoff.encode())
    data['metadata']['rendered_dom'].update(byte_count=len(dom),source_sha256=sha256(dom).hexdigest())
    return dict(sport='autorace',program_raw_b64=b64(auto.wire(data['program'])),
        race_info_raw_b64=b64(auto.wire(data['race'])),rendered_dom_b64=b64(dom),
        capture_metadata=data['metadata'],request_bodies_b64={request_sha:b64(request)})


def keirin_case():
    a,ma,b,mb,dom=keirin.capture(*keirin.fixture())
    return dict(sport='keirin',racelist_raw_b64=b64(a),racelist_metadata=ma,
        racelive_raw_b64=b64(b),racelive_metadata=mb,rendered_dom_b64=b64(dom),browser_metadata=None)


def packet(cases):
    terms=dict(schema=capture.TERMS_SCHEMA,execution_day='2030-01-15',purpose='PRIVATE_FACTUAL_ANALYSIS',
        public_redistribution=False,provider_model_training_permission_confirmed=False,
        owner_instruction_ref='FICTIONAL_OFFLINE_AUTHORIZATION',terms=[dict(sport='autorace',
            terms_url='https://autorace.jp/policy/',policy_sha256='e'*64,
            policy_captured_at=(auto.NOW-timedelta(days=1)).isoformat(),
            source_urls=[auto.BASE+'Live/isesaki',auto.BASE+'Program',auto.BASE+'OtherRaceInfo'],
            uses=['private_retention','private_factual_analysis'])])
    if any(case['sport']=='keirin' for case in cases):
        terms['terms'].append(dict(sport='keirin',terms_url='https://keirin.jp/pc/dfw/portal/guest/sitepolicy/',
            policy_sha256='d'*64,policy_captured_at=(auto.NOW-timedelta(days=1)).isoformat(),
            source_urls=['https://keirin.jp/pc/racelist','https://keirin.jp/pc/racelive'],
            uses=['private_retention','private_factual_analysis']))
    return dict(schema='RACE_AI_OFFICIAL_SOURCE_PACKET_V1',execution_day='2030-01-15',
                cases=cases,terms_manifest=terms)


def packed(root):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for folder in root.iterdir():
            for name in ('learning.enc','learning.json','summary.json'):
                archive.writestr(folder.name+'/'+name,(folder/name).read_bytes())
    return output.getvalue()


class SourcePacketFreezeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(freeze,'source packet freeze command is missing')
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.root.chmod(0o700)
        self.repo=self.root/'repo';self.repo.mkdir()
        owner=patch.dict(os.environ,RACE_AI_STATE_KEY=b64(KEY));owner.start();self.addCleanup(owner.stop)
        net=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('source GET forbidden'))
        net.start();self.addCleanup(net.stop)
        self.env=dict(run_id=42,head_sha=HEAD,temp=self.root)

    def sealed(self,value=None):
        value=packet([auto_case()]) if value is None else value
        raw=seal_forecasts(value,run_id='42',round_no=900003,key=KEY)
        cipher_sha=sha256(raw).hexdigest();path='audit/state/official-source-packet-'+cipher_sha+'.enc'
        target=self.repo/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        manifest=dict(schema='RACE_AI_OFFICIAL_SOURCE_PACKET_FREEZE_INPUT_V1',execution_day='2030-01-15',
            packet_path=path,packet_sha256=cipher_sha,maximum_races_per_sport={'autorace':8})
        return manifest,target,raw

    def context(self):
        from race_ai.all_existing_model_learning import fit
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from tests.test_all_existing_model_learning import observed_records
        records=json.loads(json.dumps(observed_records()).replace('2030-04-01','2030-01-14').replace('20300401','20300114'))
        for row in records:
            row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['scope']=row['scope']
            row['native_payload']['snapshot']['scope']=row['scope'];row['input_sha256']=freeze.digest(row['native_payload'])
        training=fit(records,now=datetime.fromisoformat('2030-01-14T08:00:00+00:00'),
            allow_source=lambda *_:True,allow_training=lambda *_:True)
        folder=self.root/'candidate'
        seal_candidate(dict(training=training,excluded=[],summary=dict(state=training['state'],fitted_model_count=2,
            production_promoted=False,actual_purchases=False,plaintext_published=False)),folder)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc','learning.json','summary.json'):archive.writestr(name,(folder/name).read_bytes())
        raw=output.getvalue();receipt=dict(id=700,name='all-existing-model-learning-42-1',expired=False,
            size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(auto.NOW-timedelta(minutes=1)).isoformat(),expires_at=(auto.NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
        return context_from_encrypted_artifact(raw,700,now=auto.NOW,_fetch=lambda _:receipt)

    def generated(self,*,mixed=False,cases=None):
        value=packet(cases) if cases is not None else packet([auto_case(),keirin_case()]) if mixed else None
        manifest,_,_=self.sealed(value)
        if mixed:manifest['maximum_races_per_sport']['keirin']=8
        context=self.context();output=self.root/'output'
        with patch.object(freeze,'ROOT',self.repo),patch.object(freeze,'utc_now',return_value=auto.NOW), \
                patch.object(freeze.future,'candidate',return_value=context):
            status=freeze.generate(700,output,self.env,manifest)
        freeze._write(output.with_name('output.status.json'),freeze.future.wire(dict(status,schema=freeze.STATUS,
            workflow_run_id=42,expected_head_sha=HEAD)))
        raw=packed(output);receipt=dict(id=801,name='all-existing-model-pairs-42-900003',expired=False,
            size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
            created_at=(auto.NOW+timedelta(seconds=1)).isoformat(),expires_at=(auto.NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42,head_sha=HEAD,repository_id=1416489937,head_repository_id=1416489937))
        return output,status,raw,receipt

    def test_manifest_is_exact_current_day_and_cipher_path_bound(self):
        manifest,_,_=self.sealed();path=self.root/'manifest.json';path.write_text(json.dumps(manifest))
        self.assertEqual(freeze.load_manifest(path,now=auto.NOW),manifest)
        changes=[{'extra':'unused'},{'execution_day':'2030-01-14'},
            {'packet_path':'../private.enc'},{'packet_sha256':'f'*64},
            {'maximum_races_per_sport':{}},{'maximum_races_per_sport':{'autorace':True}},
            {'maximum_races_per_sport':{'horse':8}},{'maximum_races_per_sport':{'autorace':9}}]
        for change in changes:
            path.write_text(json.dumps(dict(manifest,**change)))
            with self.subTest(change=change),self.assertRaises(ValueError):freeze.load_manifest(path,now=auto.NOW)

    def test_packet_authentication_terms_case_bound_and_symlinks(self):
        value=packet([auto_case()]);manifest,path,raw=self.sealed(value)
        with patch.object(freeze,'ROOT',self.repo):
            self.assertEqual(freeze.load_packet(manifest,key=KEY,now=auto.NOW),value)
            path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
            with self.assertRaises(ValueError):freeze.load_packet(manifest,key=KEY,now=auto.NOW)
            path.unlink();outside=self.root/'outside.enc';outside.write_bytes(raw);path.symlink_to(outside)
            with self.assertRaises(ValueError):freeze.load_packet(manifest,key=KEY,now=auto.NOW)
        invalid=[]
        for change in ({'cases':[]},{'cases':[auto_case()]*33},{'execution_day':'2030-01-14'},{'extra':1}):
            invalid.append(dict(value,**change))
        for field,replacement in (('purpose','PUBLIC_REUSE'),('public_redistribution',True),
                                  ('provider_model_training_permission_confirmed',True)):
            invalid.append(dict(value,terms_manifest=dict(value['terms_manifest'],**{field:replacement})))
        for wrong in invalid:
            manifest,_,_=self.sealed(wrong)
            with patch.object(freeze,'ROOT',self.repo),self.subTest(wrong=wrong.keys()),self.assertRaises(ValueError):
                freeze.load_packet(manifest,key=KEY,now=auto.NOW)

    def test_normal_ui_original_bytes_replay_six_cells_without_clock_or_global_mutation(self):
        case=auto_case();before=deepcopy(case)
        converted=freeze.case_inputs(case,now=auto.NOW)
        self.assertEqual(converted['state'],'READY');self.assertEqual(len(converted['requests']),6)
        self.assertEqual(case,before)
        self.assertEqual({r['cell_key'] for r in converted['requests']},freeze.CELLS['autorace'])
        for request in converted['requests']:
            self.assertEqual(request['native_payload']['source_evidence'][0]['captured_at'],
                             case['capture_metadata']['ledger'][0]['body_captured_at'])
            self.assertNotIn('learned_model',request['native_payload'])
        for field,value in (('program_raw_b64','%%%'),('rendered_dom_b64',case['rendered_dom_b64']+'='),
                            ('request_bodies_b64',{'f'*64:b64(b'{}')})):
            with self.subTest(field=field),self.assertRaises(ValueError):
                freeze.case_inputs(dict(case,**{field:value}),now=auto.NOW)

    def test_selection_is_bounded_future_only_and_requires_complete_source_closure(self):
        manifest,_,_=self.sealed();manifest['maximum_races_per_sport']={'autorace':2}
        value=packet([auto_case(3,'10:40'),auto_case(1,'10:30'),auto_case(2,'10:35'),auto_case(4,'09:16')])
        selected,counts=freeze.select_cases(value,manifest,now=auto.NOW)
        self.assertEqual([row['race_id'].rsplit(':',1)[1] for row in selected],['1','2'])
        self.assertEqual(counts['held_cases'],1)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_RACE'):
            freeze.select_cases(packet([auto_case(),auto_case()]),manifest,now=auto.NOW)
        value=packet([auto_case()]);value['terms_manifest']['terms'][0]['source_urls'].remove(auto.BASE+'Program')
        with self.assertRaisesRegex(ValueError,'SOURCE_TERMS_CLOSURE'):
            freeze.select_cases(value,manifest,now=auto.NOW)

    def test_an_adapter_cannot_silently_drop_a_required_native_cell(self):
        case=auto_case();converted=freeze.case_inputs(case,now=auto.NOW)
        converted['requests'].pop()
        with patch.object(freeze.autorace,'build_requests',return_value=converted), \
                self.assertRaisesRegex(ValueError,'EXACT_NATIVE_CELLS'):
            freeze.case_inputs(case,now=auto.NOW)

    def test_keirin_original_browser_body_replay_and_mixed_eleven_capsule_readback(self):
        case=keirin_case();before=deepcopy(case)
        converted=freeze.case_inputs(case,now=auto.NOW)
        self.assertEqual(converted['state'],'READY');self.assertEqual(len(converted['requests']),5)
        self.assertEqual(case,before)
        self.assertEqual({r['cell_key'] for r in converted['requests']},freeze.CELLS['keirin'])
        output,status,raw,receipt=self.generated(mixed=True)
        self.assertEqual(status['captured_native_input_count'],11);self.assertEqual(status['ready_races'],2)
        self.assertEqual(status['ready_races_by_sport'],{'autorace':1,'keirin':1})
        with patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=raw):
            result=freeze.readback(801,output,self.env)
        self.assertTrue(result['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(result['captured_native_input_count'],11)

    def test_actual_codec_input_only_generation_and_independent_actual_receipt(self):
        output,status,raw,receipt=self.generated()
        self.assertTrue(status['ready']);self.assertEqual(status['captured_native_input_count'],6)
        self.assertEqual(status['forecast_partition_count'],0)
        self.assertFalse(status['independent_pre_cutoff_receipt_verified'])
        self.assertEqual({p.stat().st_mode&0o777 for p in output.iterdir()},{0o700})
        self.assertNotIn('summary.json',{p.name for p in output.iterdir()})
        self.assertEqual(len(freeze.local_records(output)),1)
        with patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=raw):
            admitted=freeze.readback(801,output,self.env)
        self.assertTrue(admitted['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(admitted['record_sha256'],status['record_sha256'])
        for public in (status,admitted):
            text=json.dumps(public)
            for private in ('native_payload','source_url','recent_finishes','parameters'):
                self.assertNotIn(private,text)
            self.assertNotIn('1001',public.values())

    def test_eight_auto_races_retain_all_forty_eight_native_capsules(self):
        output,status,raw,receipt=self.generated(cases=[auto_case(number) for number in range(1,9)])
        self.assertEqual((status['ready_races'],status['captured_native_input_count']),(8,48))
        self.assertEqual(len(freeze.local_records(output)),8)
        with patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=raw):
            actual=freeze.readback(801,output,self.env)
        self.assertTrue(actual['independent_pre_cutoff_receipt_verified'])
        self.assertEqual((actual['ready_races'],actual['captured_native_input_count']),(8,48))

    def test_actual_receipt_wrong_run_head_name_cipher_or_late_upload_rejected(self):
        output,_,raw,receipt=self.generated()
        bad=[dict(receipt,name='all-existing-model-pairs-42-900002'),
             dict(receipt,created_at=(auto.NOW+timedelta(hours=2)).isoformat()),
             dict(receipt,workflow_run=dict(receipt['workflow_run'],id=43)),
             dict(receipt,workflow_run=dict(receipt['workflow_run'],head_sha='b'*40))]
        for actual in bad:
            with self.subTest(actual=actual['name']),patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(hours=3)), \
                    patch.object(freeze.future,'metadata',return_value=actual), \
                    patch.object(freeze.future,'gh',return_value=raw),self.assertRaises(ValueError):
                freeze.readback(801,output,self.env)
        damaged=raw[:-1]+bytes([raw[-1]^1])
        with patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt), \
                patch.object(freeze.future,'gh',return_value=damaged),self.assertRaises(ValueError):
            freeze.readback(801,output,self.env)

    def test_status_lineage_is_sha_bound_and_cannot_publish_private_exception_values(self):
        output,_,raw,receipt=self.generated();path=output.with_name('output.status.json')
        previous=json.loads(path.read_bytes());previous['source_packet_sha256']='https://private.invalid/source'
        path.write_text(json.dumps(previous));path.chmod(0o600)
        with patch.object(freeze,'utc_now',return_value=auto.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt), \
                patch.object(freeze.future,'gh',return_value=raw),self.assertRaisesRegex(ValueError,'LOCAL_GENERATION_STATUS'):
            freeze.readback(801,output,self.env)

    def test_physical_time_used_for_final_margin_after_sealing(self):
        manifest,_,_=self.sealed();context=self.context();output=self.root/'output';clock=[auto.NOW]
        original=freeze.make_private_pairs
        def elapsed(*args,**kwargs):
            result=original(*args,**kwargs);clock[0]=auto.NOW+timedelta(hours=2);return result
        with patch.object(freeze,'ROOT',self.repo),patch.object(freeze,'utc_now',side_effect=lambda:clock[0]), \
                patch.object(freeze.future,'candidate',return_value=context), \
                patch.object(freeze,'make_private_pairs',side_effect=elapsed), \
                self.assertRaisesRegex(ValueError,'FINAL_MARGIN_ELAPSED'):
            freeze.generate(700,output,self.env,manifest)
        self.assertTrue(output.exists())

    def test_main_fail_closed_status_and_actions_output_never_expose_exception_text(self):
        output=self.root/'output';github=self.root/'github-output';stdout=io.StringIO()
        from contextlib import redirect_stdout
        with patch.object(freeze.future,'environment',return_value=self.env), \
                patch.object(freeze.future,'output_path',return_value=output), \
                patch.object(freeze,'load_manifest',side_effect=ValueError('private source https://secret.invalid/raw')), \
                patch.dict(os.environ,GITHUB_OUTPUT=str(github)),redirect_stdout(stdout):
            self.assertEqual(freeze.main(['--candidate-artifact','700','--input','fictional','--out-dir',str(output)]),0)
        status=json.loads(stdout.getvalue());self.assertFalse(status['ready'])
        self.assertNotIn('secret',stdout.getvalue());self.assertIn('ready=false',github.read_text())
        self.assertEqual(status['source_requests'],0)
        self.assertFalse(output.exists());self.assertTrue(output.with_name('output.status.json').exists())


if __name__=='__main__':unittest.main()
