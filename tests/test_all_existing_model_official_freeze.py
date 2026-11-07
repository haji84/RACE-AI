"""Invented manifests and official metadata; no provider or live-key calls."""
from copy import deepcopy
from datetime import datetime
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

    def test_actual_codec_restore_adapter_five_inputs_and_external_receipt_roundtrip(self):
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
        raw=jra.card();rule=jra.evidence();actuals={jra.CARD_URL:jra.metadata(raw),jra.RULE_URL:rule['metadata']}
        for metadata in actuals.values():metadata.pop('scope',None)
        terms=dict(schema=capture.TERMS_SCHEMA,execution_day='2026-11-07',purpose='PRIVATE_FACTUAL_ANALYSIS',
            public_redistribution=False,provider_model_training_permission_confirmed=False,
            owner_instruction_ref='FICTIONAL_OFFLINE_TEST',terms=[dict(sport='horse',
                terms_url='https://www.jra.go.jp/fixture-policy',policy_sha256='e'*64,
                policy_captured_at='2026-11-06T01:00:00+00:00',source_urls=list(actuals),
                uses=['private_retention','private_factual_analysis'])])
        capture.import_captures([dict(url=url,raw=raw if url==jra.CARD_URL else rule['raw'],
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
        env=dict(run_id=42,head_sha='a'*40,temp=self.root);output=self.root/'output'
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


if __name__=='__main__':unittest.main()
