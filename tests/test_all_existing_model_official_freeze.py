"""Invented manifests and official metadata; no provider or live-key calls."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import all_existing_model_official_freeze as freeze
from tests import test_jra_official_sparse_adapter as jra


class OfficialFreezeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.root.chmod(0o700)
        self.manifest=dict(schema='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V1',execution_day='2026-11-07',
            sealed_path='audit/state/manual-official-capture/fictional',index_sha256='a'*64,maximum_races=8,
            source_metadata_path='audit/state/manual-official-source-metadata-'+'b'*64+'.enc',
            source_metadata_sha256='b'*64)

    def test_manifest_requires_exact_pins_and_current_execution_day(self):
        path=self.root/'input.json';path.write_text(json.dumps(self.manifest))
        self.assertEqual(freeze.load_manifest(path,now=jra.NOW),self.manifest)
        for change in ({'extra':1},{'maximum_races':9},{'sealed_path':'../private'},
                       {'source_metadata_path':'/tmp/key.enc'},{'execution_day':'2026-11-06'}):
            manifest=deepcopy(self.manifest);manifest.update(change);path.write_text(json.dumps(manifest))
            with self.subTest(change=change),self.assertRaises(ValueError):freeze.load_manifest(path,now=jra.NOW)

    def test_original_status_clock_and_hash_are_preserved_without_reconstruction(self):
        raw=jra.card();actual=jra.metadata(raw)
        manual=dict(url=actual['source_url'],final_url=actual['final_url'],captured_at=actual['response_received_at'],
            source_sha256=actual['source_sha256'],size=len(raw),content_type='text/html',capture_origin='IMPORTED_PRIOR_CAPTURE')
        self.assertEqual(freeze.bind_metadata(raw,manual,actual),actual)
        for key,value in (('status',403),('response_received_at','2026-11-07T01:00:02+00:00'),
                          ('source_sha256','f'*64),('byte_count',1)):
            changed=dict(actual,**{key:value})
            with self.subTest(key=key),self.assertRaises(ValueError):freeze.bind_metadata(raw,manual,changed)

    def test_copy_accepts_only_bounded_flat_cipher_files_and_checks_index_before_restore(self):
        source=self.root/'repo'/'audit/state/manual-official-capture/fictional';source.mkdir(parents=True)
        raw=b'fictional cipher';(source/'index.enc').write_bytes(raw);(source/'source-0000.enc').write_bytes(b'cipher')
        manifest=dict(self.manifest,index_sha256=hashlib.sha256(raw).hexdigest())
        target=self.root/'private'
        with patch.object(freeze,'ROOT',self.root/'repo'):
            freeze.copy_sealed(manifest,target)
        self.assertEqual(target.stat().st_mode&0o777,0o700)
        self.assertEqual({p.stat().st_mode&0o777 for p in target.iterdir()},{0o600})
        (source/'raw.html').write_bytes(b'private source')
        with patch.object(freeze,'ROOT',self.root/'repo'),self.assertRaises(ValueError):
            freeze.copy_sealed(manifest,self.root/'other')

    def _fixture(self,*,cards=None):
        import base64
        from datetime import timedelta
        from race_ai import manual_official_capture as capture
        from race_ai.boat_all_model_store import seal_forecasts
        from race_ai.all_existing_model_learning import fit
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from tests.test_all_existing_model_learning import observed_records
        key=bytes(range(32));envkey=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(key).decode())
        envkey.start();self.addCleanup(envkey.stop)
        network=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider GET forbidden'))
        network.start();self.addCleanup(network.stop)
        raw=jra.card();rule=jra.evidence();bodies=dict(cards or {jra.CARD_URL:raw})
        bodies[jra.RULE_URL]=rule['raw']
        actuals={url:jra.metadata(body,url) for url,body in bodies.items()}
        for metadata in actuals.values():metadata.pop('scope',None)
        terms=dict(schema=capture.TERMS_SCHEMA,execution_day='2026-11-07',purpose='PRIVATE_FACTUAL_ANALYSIS',
            public_redistribution=False,provider_model_training_permission_confirmed=False,
            owner_instruction_ref='FICTIONAL_OFFLINE_TEST',terms=[dict(sport='horse',
                terms_url='https://www.jra.go.jp/fixture-policy',policy_sha256='e'*64,
                policy_captured_at='2026-11-06T01:00:00+00:00',source_urls=list(actuals),
                uses=['private_retention','private_factual_analysis'])])
        capture.import_captures([dict(url=url,raw=bodies[url],
            captured_at=meta['response_received_at'],content_type='text/html',final_url=url)
            for url,meta in actuals.items()],execution_day='2026-11-07',terms_manifest=terms,
            cache_dir=self.root/'cache',clock=lambda:jra.NOW)
        sealed=self.root/'sealed'
        proof=capture.seal_cache(self.root/'cache',sealed,key=key,run_id='42',round_no=900002)
        repo=self.root/'repo';source=repo/self.manifest['sealed_path'];source.parent.mkdir(parents=True)
        shutil.copytree(sealed,source)
        original=seal_forecasts(dict(schema='RACE_AI_MANUAL_OFFICIAL_ORIGINAL_METADATA_V1',
            execution_day='2026-11-07',metadata_by_url=actuals),run_id='42',round_no=900002,key=key)
        original_sha=hashlib.sha256(original).hexdigest()
        path='audit/state/manual-official-source-metadata-'+original_sha+'.enc'
        (repo/path).write_bytes(original)
        manifest=dict(self.manifest,index_sha256=proof['index_sha256'],source_metadata_path=path,
                      source_metadata_sha256=original_sha)
        # An invented earlier BOAT fitted candidate transports unfitted horse
        # inputs; it cannot create or imply any horse prediction or coefficient.
        records=json.loads(json.dumps(observed_records()).replace('2030-04-01','2026-11-06').replace('20300401','20261106'))
        for row in records:
            row['scope']='OPERATOR_SUPPLIED_RESEARCH';row['native_payload']['scope']=row['scope']
            row['native_payload']['snapshot']['scope']=row['scope'];row['input_sha256']=freeze.digest(row['native_payload'])
        training=fit(records,now=datetime.fromisoformat('2026-11-06T08:00:00+00:00'),
            allow_source=lambda *_:True,allow_training=lambda *_:True)
        candidate=self.root/'candidate'
        seal_candidate(dict(training=training,excluded=[],summary=dict(state=training['state'],
            fitted_model_count=2,production_promoted=False,actual_purchases=False,plaintext_published=False)),candidate)
        zipped=io.BytesIO()
        with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc','learning.json','summary.json'):archive.writestr(name,(candidate/name).read_bytes())
        candidate_raw=zipped.getvalue()
        metadata=dict(id=700,name='all-existing-model-learning-42-1',size_in_bytes=len(candidate_raw),
            digest='sha256:'+hashlib.sha256(candidate_raw).hexdigest(),expired=False,
            created_at=(jra.NOW-timedelta(minutes=1)).isoformat(),expires_at=(jra.NOW+timedelta(days=7)).isoformat(),
            workflow_run=dict(id=42,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
        context=context_from_encrypted_artifact(candidate_raw,700,now=jra.NOW,_fetch=lambda _:metadata)
        env=dict(run_id=42,head_sha='a'*40,temp=self.root)
        return manifest,env,context,metadata

    @staticmethod
    def _archive(output):
        zipped=io.BytesIO()
        with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as archive:
            for folder in output.iterdir():
                for name in ('learning.enc','learning.json','summary.json'):
                    archive.writestr(folder.name+'/'+name,(folder/name).read_bytes())
        return zipped.getvalue()

    def test_actual_codec_restore_adapter_five_inputs_and_external_receipt_roundtrip(self):
        manifest,env,context,metadata=self._fixture();repo=self.root/'repo';output=self.root/'output'
        with patch.object(freeze,'ROOT',repo),patch.object(freeze,'utc_now',return_value=jra.NOW), \
                patch.object(freeze.future,'candidate',return_value=context):
            result=freeze.generate(700,output,env,manifest)
        self.assertTrue(result['ready']);self.assertEqual(result['partition_count'],1)
        self.assertEqual(result['captured_native_input_count'],5);self.assertEqual(result['forecast_partition_count'],0)
        self.assertNotIn('summary.json',{p.name for p in output.iterdir()})
        status=dict(result,schema=freeze.STATUS,workflow_run_id=42,expected_head_sha='a'*40)
        freeze._write(output.with_name('output.status.json'),freeze.future.wire(status))
        zipped=io.BytesIO()
        with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as archive:
            for folder in output.iterdir():
                for name in ('learning.enc','learning.json','summary.json'):
                    archive.writestr(folder.name+'/'+name,(folder/name).read_bytes())
        artifact=zipped.getvalue();receipt=dict(metadata,id=801,name='all-existing-model-pairs-42-900002',
            size_in_bytes=len(artifact),digest='sha256:'+hashlib.sha256(artifact).hexdigest(),
            created_at=(jra.NOW+timedelta(seconds=1)).isoformat())
        with patch.object(freeze,'utc_now',return_value=jra.NOW+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=artifact):
            readback=freeze.readback(801,output,env)
        self.assertTrue(readback['independent_pre_cutoff_receipt_verified'])
        self.assertEqual(readback['record_sha256'],result['record_sha256'])
        for text in (json.dumps(result),json.dumps(readback)):
            self.assertNotIn('native_payload',text);self.assertNotIn('source_url',text)

    def test_v2_manifest_requires_exact_bounded_exclusion_pins_without_changing_v1(self):
        descriptor=dict(id=801,digest='sha256:'+'c'*64,run_id=42,head_sha='a'*40)
        manifest=dict(self.manifest,schema='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V2',
                      excluded_native_artifacts=[descriptor])
        path=self.root/'v2.json';path.write_text(json.dumps(manifest))
        self.assertEqual(freeze.load_manifest(path,now=jra.NOW),manifest)
        invalid=[dict(manifest,extra=1),dict(manifest,excluded_native_artifacts=[]),
            dict(manifest,excluded_native_artifacts=[descriptor]*2),
            dict(manifest,excluded_native_artifacts=[dict(descriptor,id=True)]),
            dict(manifest,excluded_native_artifacts=[dict(descriptor,head_sha='b'*39)]),
            dict(manifest,excluded_native_artifacts=[dict(descriptor,run_id=0)]),
            dict(manifest,excluded_native_artifacts=[dict(descriptor,digest='c'*64)]),
            dict(self.manifest,excluded_native_artifacts=[descriptor])]
        for value in invalid:
            path.write_text(json.dumps(value))
            with self.subTest(value=value.keys()),self.assertRaises(ValueError):freeze.load_manifest(path,now=jra.NOW)
        self.assertEqual(freeze.authenticated_excluded_races(self.manifest,now=jra.NOW),(set(),0))

    def _generated(self,*,cards=None):
        manifest,env,context,metadata=self._fixture(cards=cards);output=self.root/'original'
        with patch.object(freeze,'ROOT',self.root/'repo'),patch.object(freeze,'utc_now',return_value=jra.NOW), \
                patch.object(freeze.future,'candidate',return_value=context):
            result=freeze.generate(700,output,env,manifest)
        raw=self._archive(output);receipt=dict(metadata,id=801,name='all-existing-model-pairs-42-900002',
            size_in_bytes=len(raw),digest='sha256:'+hashlib.sha256(raw).hexdigest(),
            created_at=(jra.NOW+timedelta(seconds=1)).isoformat())
        pin={key:receipt[key] for key in ('id','digest')}
        pin.update(run_id=42,head_sha='a'*40)
        return manifest,env,context,output,result,raw,receipt,pin

    def test_exclusions_authenticate_real_codec_and_all_metadata_pins_before_using_race_ids(self):
        manifest,_,_,_,_,raw,receipt,pin=self._generated()
        v2=dict(manifest,schema='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V2',excluded_native_artifacts=[pin])
        later=jra.NOW+timedelta(seconds=5)
        with patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=raw):
            races,count=freeze.authenticated_excluded_races(v2,now=later)
        self.assertEqual(count,1);self.assertEqual(len(races),1)
        for change in (dict(id=802),dict(digest='sha256:'+'d'*64),dict(expired=True),
                       dict(expires_at=(jra.NOW+timedelta(seconds=4)).isoformat()),
                       dict(workflow_run=dict(receipt['workflow_run'],id=43)),
                       dict(workflow_run=dict(receipt['workflow_run'],head_sha='b'*40)),
                       dict(created_at=(jra.NOW+timedelta(hours=6)).isoformat())):
            with self.subTest(change=change),patch.object(freeze.future,'metadata',return_value=dict(receipt,**change)), \
                    patch.object(freeze.future,'gh',return_value=raw),self.assertRaises(ValueError):
                freeze.authenticated_excluded_races(v2,now=later)
        corrupt=bytearray(raw);corrupt[-1]^=1
        with patch.object(freeze.future,'metadata',return_value=receipt), \
                patch.object(freeze.future,'gh',return_value=bytes(corrupt)),self.assertRaises(ValueError):
            freeze.authenticated_excluded_races(v2,now=later)
        members={}
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            for name in source.namelist():members[name]=source.read(name)
        name=next(key for key in members if key.endswith('/learning.enc'))
        members[name]=members[name][:-1]+bytes([members[name][-1]^1]);zipped=io.BytesIO()
        with zipfile.ZipFile(zipped,'w',zipfile.ZIP_DEFLATED) as target:
            for name,body in members.items():target.writestr(name,body)
        damaged=zipped.getvalue();actual=dict(receipt,size_in_bytes=len(damaged),
            digest='sha256:'+hashlib.sha256(damaged).hexdigest())
        changed=dict(v2,excluded_native_artifacts=[dict(pin,digest=actual['digest'])])
        with patch.object(freeze.future,'metadata',return_value=actual), \
                patch.object(freeze.future,'gh',return_value=damaged),self.assertRaises(ValueError):
            freeze.authenticated_excluded_races(changed,now=later)
        actual=dict(receipt,created_at=(jra.NOW+timedelta(hours=6)).isoformat())
        with patch.object(freeze.future,'metadata',return_value=actual), \
                patch.object(freeze.future,'gh',return_value=raw), \
                self.assertRaisesRegex(ValueError,'CAPTURED_INPUT_PRE_CUTOFF_CLOCK_INVALID'):
            freeze.authenticated_excluded_races(v2,now=jra.NOW+timedelta(hours=6,seconds=1))

    def test_v1_never_enters_exclusion_flow_or_adds_exclusion_status_fields(self):
        with patch.object(freeze,'authenticated_excluded_races',side_effect=AssertionError('V1 exclusion flow')):
            _,_,_,_,result,_,_,_=self._generated()
        self.assertFalse(any(key.startswith('excluded_') for key in result))

    def test_v2_preserves_whole_cache_and_old_eight_then_freezes_only_two_future_reserves(self):
        cards={}
        for number in range(1,17):
            url=jra.CARD_URL.replace('1120261107',f'{number:02d}20261107')
            body=jra.card().decode('cp932').replace('11レース',str(number)+'レース')
            if number>10:body=body.replace('class="past p','class="unavailable p')
            cards[url]=body.encode('cp932')
        manifest,env,context,old,initial,raw,receipt,pin=self._generated(cards=cards)
        self.assertEqual((initial['ready_races'],initial['captured_native_input_count']),(8,40))
        immutable={str(path):path.read_bytes() for base in (self.root/'repo',old)
                   for path in base.rglob('*') if path.is_file()}
        prior={record['race_id'] for record in freeze.local_records(old)}
        v2=dict(manifest,schema='RACE_AI_MANUAL_OFFICIAL_NATIVE_FREEZE_INPUT_V2',excluded_native_artifacts=[pin])
        output=self.root/'reserves';later=jra.NOW+timedelta(seconds=5)
        with patch.object(freeze,'ROOT',self.root/'repo'),patch.object(freeze,'utc_now',return_value=later), \
                patch.object(freeze.future,'candidate',return_value=context), \
                patch.object(freeze.future,'metadata',return_value=receipt),patch.object(freeze.future,'gh',return_value=raw):
            result=freeze.generate(700,output,env,v2)
        self.assertEqual((result['ready_races'],result['captured_native_input_count']),(2,10))
        self.assertEqual((result['excluded_native_artifact_count'],result['excluded_native_race_count'],
                          result['excluded_cached_card_count']),(1,8,8))
        records=freeze.local_records(output)
        self.assertFalse(prior&{record['race_id'] for record in records})
        for record in records:
            for capsule in record['captured_native_inputs']:
                native=capsule['native_payload']
                self.assertEqual(native['snapshot']['race']['as_of'],later.isoformat())
                for participant in native['snapshot']['participants']:
                    for feature in participant['features'].values():
                        self.assertEqual(feature['captured_at'],jra.metadata(b'fixture')['response_received_at'])
        self.assertEqual({path:Path(path).read_bytes() for path in immutable},immutable)
        status=dict(result,schema=freeze.STATUS,workflow_run_id=42,expected_head_sha='a'*40)
        freeze._write(output.with_name('reserves.status.json'),freeze.future.wire(status))
        backup=self._archive(output);actual=dict(receipt,id=802,size_in_bytes=len(backup),
            digest='sha256:'+hashlib.sha256(backup).hexdigest(),
            created_at=(later+timedelta(seconds=1)).isoformat())
        with patch.object(freeze,'utc_now',return_value=later+timedelta(seconds=5)), \
                patch.object(freeze.future,'metadata',return_value=actual),patch.object(freeze.future,'gh',return_value=backup):
            readback=freeze.readback(802,output,env)
        self.assertTrue(readback['independent_pre_cutoff_receipt_verified'])
        self.assertEqual((readback['excluded_native_artifact_count'],readback['excluded_native_race_count'],
                          readback['excluded_cached_card_count']),(1,8,8))


if __name__=='__main__':unittest.main()
