"""Invented source packets and real AES/ZIP; no provider or owner key."""
import base64
from copy import deepcopy
from datetime import datetime,timedelta
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

from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
from race_ai.jra_official_result_adapter import parse_result
from race_ai.manual_official_capture import official_rights_ref
from tests import test_jra_official_result_adapter as fixture

KEY=bytes(range(32));HEAD='a'*40


class OfficialResultFreezeTests(unittest.TestCase):
    def setUp(self):
        self.freeze=importlib.import_module('scripts.all_existing_model_official_result_freeze')
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.root.chmod(0o700);self.repo=self.root/'repo';self.repo.mkdir()
        owner=patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode());owner.start();self.addCleanup(owner.stop)
        no_provider=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('provider forbidden'))
        no_provider.start();self.addCleanup(no_provider.stop)
        self.native=fixture.frozen();raw=fixture.result_html();meta=fixture.source_metadata(raw)
        observation=parse_result(raw,meta,frozen_native_payload=self.native,now=fixture.NOW,
            source_rights_ref=official_rights_ref('horse'))
        self.packet=dict(schema=self.freeze.PACKET,execution_day='2026-11-07',
            captures=[dict(raw_base64=base64.b64encode(raw).decode(),metadata=meta)],observations=[observation])
        self.zip_native=b'fixture boundary: authenticated native ZIP'
        self.pin=dict(id=700,digest='sha256:'+sha256(self.zip_native).hexdigest(),run_id=41,head_sha='b'*40)
        self.meta=dict(id=700,name='all-existing-model-pairs-41-900002',digest=self.pin['digest'],
            expired=False,size_in_bytes=len(self.zip_native),created_at='2026-11-07T01:11:00+00:00',
            expires_at='2026-11-14T01:11:00+00:00',workflow_run=dict(id=41,head_sha='b'*40,
                repository_id=1416489937,head_repository_id=1416489937))
        self.env=dict(run_id=42,head_sha=HEAD,temp=self.root)
        self.records=[dict(captured_native_inputs=[dict(native_payload=self.native)])]
        self.manifest=self.sealed(self.packet)

    def sealed(self,packet):
        cipher=seal_forecasts(packet,run_id='40',round_no=900005,key=KEY)
        hashed=sha256(cipher).hexdigest();relative='audit/state/official-result-source-packet-'+hashed+'.enc'
        path=self.repo/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(cipher)
        return dict(schema=self.freeze.SCHEMA,execution_day=packet['execution_day'],packet_path=relative,
            packet_sha256=hashed,native_artifacts=[deepcopy(self.pin)],allow_order_only=False)

    def patches(self):
        from contextlib import ExitStack
        stack=ExitStack();stack.enter_context(patch.object(self.freeze,'ROOT',self.repo))
        stack.enter_context(patch.object(self.freeze,'utc_now',return_value=fixture.NOW))
        self.fetch_meta=stack.enter_context(patch.object(self.freeze.future,'metadata',return_value=self.meta))
        self.fetch_zip=stack.enter_context(patch.object(self.freeze.future,'gh',return_value=self.zip_native))
        self.admit=stack.enter_context(patch.object(self.freeze,'_verified_private_pairs_artifact',
            return_value=({'independent_pre_cutoff_receipt_verified':True},self.records)))
        return stack

    def generated(self):
        target=self.root/'output'
        with self.patches():status=self.freeze.generate(target,self.env,self.manifest)
        self.freeze._write(target.with_name(target.name+'.status.json'),self.freeze.future.wire(dict(status,
            schema=self.freeze.STATUS,workflow_run_id=42,expected_head_sha=HEAD)))
        return target,status

    def result_archive(self,target):
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('results.enc',(target/'results.enc').read_bytes())
        raw=body.getvalue();meta=dict(self.meta,id=801,name='all-existing-official-results-42-900005',
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
            created_at=(fixture.NOW+timedelta(seconds=2)).isoformat(),workflow_run=dict(self.meta['workflow_run'],id=42,head_sha=HEAD))
        return raw,meta

    def test_manifest_exact_current_day_paths_and_native_pins(self):
        path=self.root/'input.json';path.write_text(json.dumps(self.manifest))
        self.assertEqual(self.freeze.load_manifest(path,now=fixture.NOW),self.manifest)
        for change in ({'extra':1},{'execution_day':'2026-11-06'},{'allow_order_only':1},
                       {'packet_path':'../private.enc'},{'native_artifacts':[]},
                       {'native_artifacts':[self.pin,self.pin]},
                       {'native_artifacts':[dict(self.pin,head_sha='x'*40)]}):
            path.write_text(json.dumps(dict(self.manifest,**change)))
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.freeze.load_manifest(path,now=fixture.NOW)

    def test_real_cipher_local_replay_and_exact_single_output_without_private_summary(self):
        target,status=self.generated()
        self.assertEqual({p.name for p in target.iterdir()},{'results.enc'})
        self.assertEqual(target.stat().st_mode&0o777,0o700)
        self.assertEqual((target/'results.enc').stat().st_mode&0o777,0o600)
        value=open_forecasts((target/'results.enc').read_bytes(),key=KEY)
        self.assertEqual(value['observations'],self.packet['observations'])
        self.assertEqual(value['captures'],self.packet['captures'])
        self.assertEqual(value['run_id'],42);self.assertEqual(value['code_sha'],HEAD)
        self.assertEqual(value['generated_at'],fixture.NOW.isoformat())
        self.assertEqual(status['ordinary_settled_result_count'],1)
        self.assertFalse(status['independent_result_artifact_receipt_verified'])
        for private in ('ordered_top3','raw_base64','roster',fixture.URL):self.assertNotIn(private,json.dumps(status))
        self.admit.assert_called_once()
        with self.patches(),self.assertRaisesRegex(ValueError,'OUTPUT_EXISTS'):
            self.freeze.generate(target,self.env,self.manifest)

    def test_actual_native_metadata_is_checked_before_zip_or_decryption(self):
        changes=({'digest':'sha256:'+'f'*64},{'expired':True},{'id':701},
            {'name':'all-existing-model-pairs-42-900002'},
            {'created_at':(fixture.NOW+timedelta(seconds=1)).isoformat()},
            {'workflow_run':dict(self.meta['workflow_run'],head_sha='c'*40)})
        for index,change in enumerate(changes):
            with self.patches(),self.subTest(change=change):
                self.fetch_meta.return_value=dict(self.meta,**change)
                with self.assertRaises(ValueError):self.freeze.generate(self.root/str(index),self.env,self.manifest)
                self.fetch_zip.assert_not_called();self.admit.assert_not_called()

    def test_packet_cipher_authentication_and_original_result_replay_reject_tampering(self):
        for index,kind in enumerate(('cipher','source_sha','roster','future','packet_schema')):
            packet=deepcopy(self.packet)
            if kind=='source_sha':packet['captures'][0]['metadata']['source_sha256']='f'*64
            if kind=='roster':packet['observations'][0]['roster']['1']='jra:invented'
            if kind=='future':packet['captures'][0]['metadata']['response_received_at']=(fixture.NOW+timedelta(seconds=1)).isoformat()
            if kind=='packet_schema':packet['extra']=1
            manifest=self.sealed(packet)
            if kind=='cipher':(self.repo/manifest['packet_path']).write_bytes(b'invalid')
            target=self.root/('bad'+str(index))
            with self.patches(),self.subTest(kind=kind),self.assertRaises(ValueError):
                self.freeze.generate(target,self.env,manifest)
            self.assertFalse(target.exists())

    def test_actual_result_zip_metadata_and_exact_original_cipher_readback(self):
        target,status=self.generated();raw,meta=self.result_archive(target)
        with self.patches():
            self.fetch_meta.side_effect=lambda ident:self.meta if ident==700 else meta
            self.fetch_zip.side_effect=lambda path:self.zip_native if '/700/' in path else raw
            with patch.object(self.freeze,'utc_now',return_value=fixture.NOW+timedelta(seconds=5)):
                result=self.freeze.readback(801,target,self.env,self.manifest)
        self.assertTrue(result['independent_result_artifact_receipt_verified'])
        self.assertEqual(result['ordinary_settled_result_count'],1)
        self.assertEqual(result['result_cipher_sha256'],status['result_cipher_sha256'])
        # Re-encryption is a different original even with the same plaintext.
        value=open_forecasts((target/'results.enc').read_bytes(),key=KEY)
        other=seal_forecasts(value,run_id='42',round_no=900005,key=KEY)
        (target/'results.enc').write_bytes(other)
        with self.patches(),self.assertRaises(ValueError):
            self.freeze.readback(801,target,self.env,self.manifest)

    def test_missing_key_holds_before_any_github_or_source_packet_access(self):
        with patch.dict(os.environ,{},clear=True),self.patches(),self.assertRaises(ValueError):
            self.freeze.generate(self.root/'none',self.env,self.manifest)
        self.fetch_meta.assert_not_called();self.fetch_zip.assert_not_called()

    def test_real_native_pair_artifact_is_independently_admitted_before_result_replay(self):
        from race_ai.actions_contract import digest
        from race_ai.all_existing_model_learning import fit
        from race_ai.all_existing_model_pairs import make_private_pairs
        from race_ai.boat_venue_learning import seal_candidate
        from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
        from race_ai.four_sport_model_suite import ALL_MODELS
        from tests.test_all_existing_model_learning import observed_records
        from tests import test_jra_official_sparse_adapter as input_fixture
        records=json.loads(json.dumps(observed_records()).replace('2030-04-01','2026-11-06').replace('20300401','20261106'))
        for row in records:row['input_sha256']=digest(row['native_payload'])
        training=fit(records,now=datetime.fromisoformat('2026-11-06T08:00:00+00:00'))
        candidate=self.root/'candidate'
        seal_candidate(dict(training=training,excluded=[],summary=dict(state=training['state'],
            fitted_model_count=len(training['models']),production_promoted=False,actual_purchases=False,
            plaintext_published=False)),candidate)
        candidate_zip=io.BytesIO()
        with zipfile.ZipFile(candidate_zip,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('learning.enc','learning.json','summary.json'):archive.writestr(name,(candidate/name).read_bytes())
        candidate_raw=candidate_zip.getvalue();candidate_meta=dict(self.meta,id=600,
            name='all-existing-model-learning-41-1',size_in_bytes=len(candidate_raw),
            digest='sha256:'+sha256(candidate_raw).hexdigest(),
            created_at=(input_fixture.NOW-timedelta(minutes=1)).isoformat())
        context=context_from_encrypted_artifact(candidate_raw,600,now=input_fixture.NOW,_fetch=lambda _:candidate_meta)
        pairs=self.root/'native-pairs'
        make_private_pairs(context,[dict(cell_key='horse/'+ALL_MODELS[0],native_payload=self.native)],pairs,
            now=input_fixture.NOW,allow_source=lambda *_:True)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for folder in pairs.iterdir():
                if folder.is_dir():
                    for name in ('learning.enc','learning.json','summary.json'):
                        archive.writestr(folder.name+'/'+name,(folder/name).read_bytes())
        raw=stream.getvalue();meta=dict(self.meta,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        manifest=dict(self.manifest,native_artifacts=[dict(self.pin,digest=meta['digest'])])
        with patch.object(self.freeze,'ROOT',self.repo),patch.object(self.freeze,'utc_now',return_value=fixture.NOW), \
                patch.object(self.freeze.future,'metadata',return_value=meta), \
                patch.object(self.freeze.future,'gh',return_value=raw):
            status=self.freeze.generate(self.root/'actual-native',self.env,manifest)
        self.assertTrue(status['ready']);self.assertEqual(status['ordinary_settled_result_count'],1)

    def test_remote_reencryption_cannot_replace_the_exact_original_cipher(self):
        target,_=self.generated();payload=open_forecasts((target/'results.enc').read_bytes(),key=KEY)
        cipher=seal_forecasts(payload,run_id='42',round_no=900005,key=KEY)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('results.enc',cipher)
        raw=stream.getvalue();_,meta=self.result_archive(target)
        meta.update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
        with self.patches():
            self.fetch_meta.side_effect=lambda ident:self.meta if ident==700 else meta
            self.fetch_zip.side_effect=lambda path:self.zip_native if '/700/' in path else raw
            with patch.object(self.freeze,'utc_now',return_value=fixture.NOW+timedelta(seconds=5)), \
                    self.assertRaisesRegex(ValueError,'ACTUAL_ORIGINAL_CIPHER_READBACK'):
                self.freeze.readback(801,target,self.env,self.manifest)

    def test_cli_missing_key_reports_static_hold_without_private_paths(self):
        output=io.StringIO()
        from contextlib import redirect_stdout
        with patch.dict(os.environ,{},clear=True),patch.object(self.freeze.future,'gh') as fetch, \
                redirect_stdout(output):
            self.assertEqual(self.freeze.main(['--input','/private/secret-input.json',
                '--out-dir','/private/secret-output']),0)
        status=json.loads(output.getvalue());self.assertFalse(status['ready'])
        self.assertEqual(status['source_requests'],0);self.assertNotIn('/private',output.getvalue())
        fetch.assert_not_called()

    def test_explicit_order_only_keeps_rank_labels_and_monetary_values_separate(self):
        from tests import test_autorace_official_result_adapter as auto
        from race_ai.autorace_official_result_adapter import parse_result as auto_parse
        data=auto.fixture();raw=auto.wire(data['result']);native=data['frozen'];metadata=data['metadata']
        metadata.pop('auto_result_archive_context')
        observation=auto_parse(raw,metadata,frozen_native_payload=native,now=auto.NOW,
            source_rights_ref=official_rights_ref('autorace'),allow_order_only=True)
        packet=dict(schema=self.freeze.PACKET,execution_day=auto.NOW.astimezone(self.freeze.JST).date().isoformat(),
            captures=[dict(raw_base64=base64.b64encode(raw).decode(),metadata=metadata)],observations=[observation])
        manifest=self.sealed(packet);self.records=[dict(captured_native_inputs=[dict(native_payload=native)])]
        self.meta.update(created_at=(auto.NOW-timedelta(hours=1)).isoformat(),
            expires_at=(auto.NOW+timedelta(days=7)).isoformat())
        with self.patches(),patch.object(self.freeze,'utc_now',return_value=auto.NOW):
            with self.assertRaises(ValueError):self.freeze.generate(self.root/'strict',self.env,manifest)
            manifest['allow_order_only']=True
            summary=self.freeze.generate(self.root/'typed',self.env,manifest)
        self.assertEqual(summary['ordinary_settled_result_count'],0)
        self.assertEqual(summary['order_only_confirmed_result_count'],1)
        self.assertFalse(summary['monetary_evaluation_available'])
        value=open_forecasts((self.root/'typed/results.enc').read_bytes(),key=KEY)
        self.assertEqual(value['observations'][0]['status'],'rank_confirmed')
        self.assertIsNone(value['observations'][0]['payout_per_100_yen'])

    def test_cli_preserves_generation_proof_when_actual_readback_temporarily_fails(self):
        from contextlib import redirect_stdout
        manifest_path=self.root/'input.json';manifest_path.write_text(json.dumps(self.manifest))
        target=self.root/'cli-output';args=['--input',str(manifest_path),'--out-dir',str(target)]
        with self.patches(),patch.object(self.freeze.future,'environment',return_value=self.env), \
                patch.dict(os.environ,GITHUB_OUTPUT=''),redirect_stdout(io.StringIO()):
            self.freeze.main(args)
        generation=target.with_name(target.name+'.generation.json');original=generation.read_bytes()
        raw,meta=self.result_archive(target)
        with self.patches(),patch.object(self.freeze.future,'environment',return_value=self.env), \
                patch.dict(os.environ,GITHUB_OUTPUT=''),redirect_stdout(io.StringIO()):
            self.fetch_meta.side_effect=lambda ident:self.meta if ident==700 else (_ for _ in ()).throw(ValueError('TEMPORARY'))
            self.freeze.main(args+['--readback-artifact','801'])
        self.assertEqual(generation.read_bytes(),original)
        self.assertFalse(json.loads(target.with_name(target.name+'.status.json').read_text())['ready'])
        output=io.StringIO()
        with self.patches(),patch.object(self.freeze.future,'environment',return_value=self.env), \
                patch.dict(os.environ,GITHUB_OUTPUT=''),redirect_stdout(output), \
                patch.object(self.freeze,'utc_now',return_value=fixture.NOW+timedelta(seconds=5)):
            self.fetch_meta.side_effect=lambda ident:self.meta if ident==700 else meta
            self.fetch_zip.side_effect=lambda path:self.zip_native if '/700/' in path else raw
            self.freeze.main(args+['--readback-artifact','801'])
        self.assertTrue(json.loads(output.getvalue())['independent_result_artifact_receipt_verified'])
        self.assertEqual(generation.read_bytes(),original)


if __name__=='__main__':unittest.main()
