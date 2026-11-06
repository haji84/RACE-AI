"""Invented private originals and owner key; no real dispatch or field claim."""
from copy import deepcopy
from datetime import datetime,timedelta
import base64
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import boat_video_learning as learning
from race_ai.boat_video_model_context import prepare_video_context
from race_ai.boat_video_evaluation import _wire
from tests.test_boat_video_model_context import fixture,AS_OF
from tests.test_boat_video_cycle_bridge import InventedAPI,wire,zipped
from tests.test_boat_video_learning import controlled_inputs
try:
    import numpy
except ImportError:numpy=None


HEAD='6'*40
KEY=bytes(range(1,33))  # Explicit fictional test key, never configured externally.
SEALED=datetime.fromisoformat(AS_OF)+timedelta(seconds=1)
SAVED=SEALED+timedelta(seconds=2)
BRANCH='feat/four-sport-forecast-audit-view-20261022'


def engine(test):
    try:return importlib.import_module('race_ai.boat_video_publication')
    except ModuleNotFoundError:test.fail('encrypted context producer is not connected')


def identity(**changes):
    value=dict(event_name='workflow_dispatch',repository='haji84/RACE-AI',
        repository_id=1416489937,workflow_id=392270247,head_branch=BRANCH,head_sha=HEAD,run_id=11000)
    value.update(changes);return value


def event(request):
    return dict(inputs=deepcopy(request['inputs']),ref=BRANCH,
                repository={'id':1416489937,'full_name':'haji84/RACE-AI'})


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        self.report,self.evidence=fixture()
        self.context=prepare_video_context(self.report,self.evidence,race_id=self.report['race_id'],
            cutoff_at=self.report['cutoff_at'],roster=self.report['roster'],as_of=AS_OF)
        self.media=self.root/'private-fictional-original.bin'
        self.media.write_bytes(b'fictional decoder input; not actual exhibition footage');self.media.chmod(0o600)
        self.report_path=self.root/(self.report['report_sha256']+'.json')
        self.report_path.write_bytes(_wire(self.report));self.report_path.chmod(0o600)
        self.item=dict(report_path=self.report_path,media_path=self.media,
                       identity_evidence=self.evidence,video_context=self.context)

    def prepare(self,**changes):
        args=dict(expected_head_sha=HEAD,key=KEY,clock=lambda:SEALED);args.update(changes)
        return engine(self).prepare_publication([self.item],**args)

    def test_cipher_roundtrip_fresh_nonce_and_no_plaintext_request_fields(self):
        mod=engine(self);before=(self.media.read_bytes(),self.report_path.read_bytes(),deepcopy(self.item))
        summary,request=self.prepare();summary2,request2=self.prepare()
        self.assertEqual(summary['status'],'READY_ENCRYPTED_CONTEXT_PUBLICATION')
        self.assertEqual(set(request),{'ref','inputs'});self.assertEqual(request['ref'],BRANCH)
        self.assertEqual(set(request['inputs']),{'video_context_cipher'})
        outer=json.loads(request['inputs']['video_context_cipher'])
        self.assertEqual(set(outer),{'schema','nonce','ciphertext'})
        self.assertEqual(len(base64.b64decode(outer['nonce'])),12)
        self.assertNotEqual(request,request2)
        self.assertLessEqual(len(wire(request)),65535)
        self.assertNotIn('feature_cells',json.dumps(request));self.assertNotIn('identity_evidence',json.dumps(summary))
        doc,meta=mod.decrypt_publication(request['inputs']['video_context_cipher'].encode(),
            expected_head_sha=HEAD,key=KEY,available_at=SAVED)
        self.assertEqual(doc,dict(schema='RACE_AI_BOAT_VIDEO_CONTEXT_ARCHIVE_V1',contexts=[self.context]))
        self.assertEqual(meta['sealed_at'],SEALED.isoformat())
        self.assertEqual((self.media.read_bytes(),self.report_path.read_bytes(),self.item),before)

    def test_no_owner_key_holds_without_original_reads_or_dispatch(self):
        mod=engine(self);sent=[]
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':''}):
            summary,request=mod.prepare_publication(None,expected_head_sha=HEAD,clock=lambda:SEALED)
            self.assertEqual(summary['status'],'HOLD_OWNER_STATE_KEY_REQUIRED');self.assertIsNone(request)
            out=mod.dispatch_publication(summary,request,platform_ready=True,send=sent.append,clock=lambda:SAVED)
            received,cipher=mod.receive_publication({},identity=identity(),clock=lambda:SAVED)
        self.assertEqual(out['status'],'HOLD_OWNER_STATE_KEY_REQUIRED')
        self.assertEqual(received['status'],'HOLD_OWNER_STATE_KEY_REQUIRED');self.assertIsNone(cipher)
        self.assertEqual(sent,[])

    def test_invalid_keys_never_become_public_fixture_or_short_owner_keys(self):
        mod=engine(self)
        from race_ai.boat_pdca_state import PUBLIC_FIXTURE_KEY
        for key in (b'',b'a'*32,KEY[:16],PUBLIC_FIXTURE_KEY):
            with self.subTest(length=len(key)):
                summary,request=self.prepare(key=key)
                self.assertEqual(summary['status'],'HOLD_OWNER_STATE_KEY_REQUIRED');self.assertIsNone(request)

    def test_tamper_wrong_key_wrong_head_and_expiry_fail_closed(self):
        mod=engine(self);_,request=self.prepare();raw=request['inputs']['video_context_cipher'].encode()
        for change in ('cipher','key','head','late'):
            altered=raw;key=KEY;head=HEAD;at=SAVED
            if change=='cipher':
                outer=json.loads(raw);cipher=bytearray(base64.b64decode(outer['ciphertext']));cipher[0]^=1
                outer['ciphertext']=base64.b64encode(cipher).decode();altered=wire(outer)
            if change=='key':key=bytes(range(2,34))
            if change=='head':head='7'*40
            if change=='late':at=datetime.fromisoformat(self.report['cutoff_at'])
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'BOAT_VIDEO_PUBLICATION_REJECTED'):
                mod.decrypt_publication(altered,expected_head_sha=head,key=key,available_at=at)

    def test_missing_altered_originals_and_resealed_context_cannot_be_published(self):
        mod=engine(self)
        for change in ('missing_media','wrong_media','missing_report','changed_context'):
            item=deepcopy(self.item)
            if change=='missing_media':item['media_path']=self.root/'absent.bin'
            if change=='wrong_media':
                other=self.root/'other.bin';other.write_bytes(b'different');item['media_path']=other
            if change=='missing_report':item['report_path']=self.root/'absent.json'
            if change=='changed_context':
                item['video_context']['participants'][0]['feature_cells']['straight_mean_speed']['value']+=1
                body=item['video_context'];body.pop('context_sha256');body['context_sha256']=digest(body)
            with self.subTest(change=change):
                summary,request=mod.prepare_publication([item],expected_head_sha=HEAD,key=KEY,clock=lambda:SEALED)
                self.assertEqual(summary['status'],'HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE');self.assertIsNone(request)

    def test_expired_preparation_and_oversized_request_do_not_call_api(self):
        mod=engine(self);sent=[]
        summary,request=self.prepare(clock=lambda:datetime.fromisoformat(self.report['cutoff_at']))
        self.assertEqual(summary['status'],'HOLD_VIDEO_PUBLICATION_DEADLINE');self.assertIsNone(request)
        good,request=self.prepare()
        request['inputs']['video_context_cipher']='x'*65535
        out=mod.dispatch_publication(good,request,key=KEY,clock=lambda:SAVED,
                                    platform_ready=True,send=sent.append)
        self.assertEqual(out['status'],'HOLD_DISPATCH_PAYLOAD_TOO_LARGE');self.assertEqual(sent,[])

    def test_platform_gate_and_gh_stdin_never_put_cipher_or_key_in_arguments(self):
        mod=engine(self);summary,request=self.prepare();sent=[]
        held=mod.dispatch_publication(summary,request,key=KEY,clock=lambda:SAVED,send=sent.append)
        self.assertEqual(held['status'],'HOLD_PLATFORM_ACTIVATION_UNVERIFIED');self.assertEqual(sent,[])
        with patch.object(mod.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as run:
            out=mod.dispatch_publication(summary,request,key=KEY,clock=lambda:SAVED,platform_ready=True)
        self.assertEqual(out['status'],'DISPATCH_REQUEST_ACCEPTED_NOT_ARTIFACT_RECEIPT')
        argv=run.call_args.args[0]
        self.assertEqual(argv,['gh','api','repos/haji84/RACE-AI/actions/workflows/392270247/dispatches',
                               '--method','POST','--input','-'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']),request)
        self.assertNotIn(request['inputs']['video_context_cipher'],argv)

    def test_invalid_injected_sender_does_not_fall_back_to_real_gh(self):
        mod=engine(self);summary,request=self.prepare()
        with patch.object(mod.subprocess,'run',side_effect=AssertionError('unexpected API')) as api:
            result=mod.dispatch_publication(summary,request,key=KEY,clock=lambda:SAVED,
                                            platform_ready=True,send=[])
        self.assertEqual(result['status'],'HOLD_PUBLICATION_INPUT_OR_DISPATCH_REJECTED')
        api.assert_not_called()

    def test_receiver_validates_actual_job_identity_and_keeps_ciphertext_for_upload(self):
        mod=engine(self);_,request=self.prepare()
        summary,raw=mod.receive_publication(event(request),identity=identity(),key=KEY,clock=lambda:SAVED)
        self.assertEqual(summary['status'],'READY_ENCRYPTED_CONTEXT_ARTIFACT')
        self.assertEqual(raw,request['inputs']['video_context_cipher'].encode())
        for field,bad in (('event_name','pull_request'),('workflow_id',405276784),
                          ('head_branch','main'),('head_sha','7'*40),('repository_id',999)):
            with self.subTest(field=field):
                result,cipher=mod.receive_publication(event(request),identity=identity(**{field:bad}),
                    key=KEY,clock=lambda:SAVED)
                self.assertEqual(result['status'],'HOLD_PUBLICATION_INPUT_REJECTED');self.assertIsNone(cipher)

    def test_receiver_cli_exports_only_cipher_file_and_safe_step_outputs(self):
        mod=engine(self);_,request=self.prepare();event_path=self.root/'event.json'
        event_path.write_bytes(wire(event(request)));event_path.chmod(0o600)
        out=self.root/'out';outputs=self.root/'outputs'
        env=dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(),
            GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937',GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/forecast-audit-ui.yml@refs/heads/'+BRANCH,
            GITHUB_REF='refs/heads/'+BRANCH,GITHUB_SHA=HEAD,GITHUB_RUN_ID='11000',GITHUB_OUTPUT=str(outputs))
        # A real future-dated context cannot be accepted by today's CLI clock;
        # exercise its protected output path using an explicit trusted test clock.
        with patch.dict(os.environ,env,clear=True),patch.object(sys,'argv',[
            'boat_video_publication','receive','--event-file',str(event_path),'--out',str(out)]),\
            patch.object(mod,'_now',return_value=SAVED),patch('sys.stdout',new_callable=io.StringIO) as stdout:
            self.assertEqual(mod.main(),0)
        self.assertEqual({p.name for p in out.iterdir()},{'video-context.enc'})
        self.assertEqual((out/'video-context.enc').read_bytes(),request['inputs']['video_context_cipher'].encode())
        self.assertEqual((out/'video-context.enc').stat().st_mode&0o777,0o600)
        self.assertEqual(out.stat().st_mode&0o777,0o700)
        printed=json.loads(stdout.getvalue());self.assertNotIn('inputs',printed)
        self.assertIn('ready=true',outputs.read_text());self.assertNotIn('feature_cells',stdout.getvalue())

    def test_receiver_missing_owner_key_creates_no_artifact(self):
        mod=engine(self);_,request=self.prepare();event_path=self.root/'event-hold.json'
        event_path.write_bytes(wire(event(request)));event_path.chmod(0o600)
        out=self.root/'held';outputs=self.root/'held-outputs'
        env=dict(os.environ,RACE_AI_STATE_KEY='',GITHUB_EVENT_NAME='workflow_dispatch',
            GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/forecast-audit-ui.yml@refs/heads/'+BRANCH,
            GITHUB_REF='refs/heads/'+BRANCH,GITHUB_SHA=HEAD,GITHUB_RUN_ID='11000',GITHUB_OUTPUT=str(outputs))
        with patch.dict(os.environ,env,clear=True),patch.object(sys,'argv',[
            'boat_video_publication','receive','--event-file',str(event_path),'--out',str(out)]),\
            patch('sys.stdout',new_callable=io.StringIO) as stdout:
            self.assertEqual(mod.main(),0)
        self.assertFalse(out.exists())
        self.assertEqual(json.loads(stdout.getvalue())['status'],'HOLD_OWNER_STATE_KEY_REQUIRED')
        self.assertIn('ready=false',outputs.read_text())

    def cipher_api(self,request,*,producer_event='workflow_dispatch',plain=False,head=HEAD):
        api=InventedAPI();envelope=api.add(self.context,ident=5000,saved=SAVED.isoformat(),run=11000)
        raw=zipped('video-contexts.json',wire({'schema':'RACE_AI_BOAT_VIDEO_CONTEXT_ARCHIVE_V1','contexts':[self.context]})) \
            if plain else zipped('video-context.enc',request['inputs']['video_context_cipher'].encode())
        meta=json.loads(api.records['actions/artifacts/5000'])
        meta.update(size_in_bytes=len(raw),digest='sha256:'+hashlib.sha256(raw).hexdigest())
        meta['workflow_run']['head_sha']=head
        producer=json.loads(api.records['actions/runs/11000'])
        producer.update(workflow_id=392270247,event=producer_event,head_sha=head)
        api.records['actions/artifacts/5000']=wire(meta);api.records['actions/artifacts/5000/zip']=raw
        api.records['actions/runs/11000']=wire(producer)
        return api,meta

    def test_cipher_artifact_actual_api_zip_reader_reaches_existing_admission(self):
        from race_ai.boat_video_archive import VideoContextArchiveReader
        mod=engine(self);_,request=self.prepare();summary,cipher=mod.receive_publication(
            event(request),identity=identity(),key=KEY,clock=lambda:SAVED)
        api,meta=self.cipher_api(request)
        reader=VideoContextArchiveReader(api.get,owner_key=KEY,clock=lambda:SAVED+timedelta(seconds=10))
        reader.load([5000]);snapshot=deepcopy(controlled_inputs(1)[0][0]['learning_snapshot'])
        snapshot.update(as_of=(SAVED+timedelta(seconds=2)).isoformat(),sales_cutoff_at=self.report['cutoff_at'])
        for participant in snapshot['participants']:
            participant['registration_no']=str(4200+participant['lane'])
        envelope=reader.select(snapshot)
        admitted,proof=learning._admit(envelope,snapshot,reader.verify)
        self.assertEqual(admitted,self.context);self.assertEqual(proof['id'],5000)
        self.assertEqual(envelope['receipt'],meta);self.assertEqual(len(api.calls),3)
        self.assertFalse(admitted['production_eligible']);self.assertFalse(admitted['independent_human_heldout_verified'])

    def test_reader_rejects_pr_plaintext_wrong_head_or_missing_owner_key_for392(self):
        from race_ai.boat_video_archive import VideoContextArchiveReader
        _,request=self.prepare()
        for change in ('pr','plaintext','head','key'):
            api,_=self.cipher_api(request,producer_event='pull_request' if change=='pr' else 'workflow_dispatch',
                plain=change=='plaintext',head='7'*40 if change=='head' else HEAD)
            with self.subTest(change=change),patch.dict(os.environ,{'RACE_AI_STATE_KEY':''}),\
                 self.assertRaisesRegex(ValueError,'BOAT_VIDEO_ARCHIVE_REJECTED'):
                VideoContextArchiveReader(api.get,owner_key=None if change=='key' else KEY,
                    clock=lambda:SAVED+timedelta(seconds=10)).load([5000])

    def test_legacy405_plaintext_route_does_not_require_or_read_owner_key(self):
        from race_ai.boat_video_archive import VideoContextArchiveReader
        engine(self);api=InventedAPI();api.add(self.context,ident=5000,saved=SAVED.isoformat(),run=11000)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':''}):
            reader=VideoContextArchiveReader(api.get,clock=lambda:SAVED+timedelta(seconds=10))
            reader.load([5000])
        self.assertEqual(reader.artifact_ids,[5000])

    def test_historical_cipher_read_uses_original_server_receipt_not_late_wall_clock(self):
        from race_ai.boat_video_archive import VideoContextArchiveReader
        _,request=self.prepare();api,meta=self.cipher_api(request)
        reader=VideoContextArchiveReader(api.get,owner_key=KEY,clock=lambda:SAVED+timedelta(days=1))
        reader.load([5000])
        proof=reader.verify(meta,self.context['context_sha256'],(SAVED+timedelta(seconds=2)).isoformat())
        self.assertEqual(proof['created_at'],SAVED.isoformat())

    @unittest.skipIf(numpy is None,'optional NumPy is required for physical V2 replay')
    def test_physical_v2_original_calibration_replays_before_encrypted_export(self):
        from tests.test_boat_video_physical_context import physical_fixture
        from race_ai.boat_video_physical_context import prepare_physical_video_context
        mod=engine(self);report,evidence,manifest,args=physical_fixture()
        context=prepare_physical_video_context(report,evidence,manifest,**args)
        path=self.root/(report['report_sha256']+'.json');path.write_bytes(_wire(report));path.chmod(0o600)
        item=dict(report_path=path,media_path=self.media,identity_evidence=evidence,
                  video_context=context,calibration_manifest=manifest)
        summary,request=mod.prepare_publication([item],expected_head_sha=HEAD,key=KEY,clock=lambda:SEALED)
        self.assertEqual(summary['status'],'READY_ENCRYPTED_CONTEXT_PUBLICATION')
        decoded,_=mod.decrypt_publication(request['inputs']['video_context_cipher'].encode(),
            expected_head_sha=HEAD,key=KEY,available_at=SAVED)
        self.assertEqual(decoded['contexts'],[context])
        self.assertEqual(decoded['contexts'][0]['coordinate_space'],'WATER_PLANE_METRES')
        item.pop('calibration_manifest')
        failed,request=mod.prepare_publication([item],expected_head_sha=HEAD,key=KEY,clock=lambda:SEALED)
        self.assertEqual(failed['status'],'HOLD_ORIGINALS_OR_CONTEXT_UNAVAILABLE');self.assertIsNone(request)


if __name__=='__main__':unittest.main()
