"""Invented data: deliver to the configured owner's recipient without exporting its key."""
from copy import deepcopy
from pathlib import Path
import base64
import json
import os
import tempfile
import unittest

from race_ai.boat_history_store import instant,wire
from race_ai.boat_pdca_state import PdcaState,PUBLIC_FIXTURE_KEY,sha
from tests.test_boat_pdca_github_handoff import invented_research_state

OWNER=os.urandom(32)  # Invented-data test only; never used with actual data.
HEAD='b'*40
NOW=instant('2026-11-06T12:00:00+09:00')


class RecipientTests(unittest.TestCase):
    def setUp(self):
        from race_ai import boat_pdca_recipient
        self.m=boat_pdca_recipient
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def receiver(self):
        return self.m.receiver_document(key=OWNER,run_id='100',source_head=HEAD)

    def transfer(self,state,output,*,receiver=None,previous=None):
        receiver=receiver or self.receiver()
        return self.m.encrypt_transfer(state,receiver,expected_receiver_sha=sha((wire(receiver)+'\n').encode()),
            expected_run_id='100',expected_source_head=HEAD,output=output,previous_pointer=previous,now=NOW)

    def pointer(self,report,commit='a'*40):
        return dict(report,status='READY',source_commit=commit,
            cipher_path='state/boat-pdca-incoming/v1/'+report['cipher_sha256']+'.enc')

    def test_receiver_is_stable_public_identity_and_refuses_fixture_root(self):
        one=self.receiver();two=self.m.receiver_document(key=OWNER,run_id='101',source_head=HEAD)
        self.assertEqual(one['public_key'],two['public_key'])
        self.assertEqual(one['key_id'],two['key_id'])
        self.assertNotIn(base64.b64encode(OWNER).decode(),wire(one))
        self.assertEqual(set(one),{'schema','repository_id','mode','public_key','key_id','run_id','source_head'})
        with self.assertRaises(ValueError):self.m.receiver_document(key=PUBLIC_FIXTURE_KEY,run_id='100',source_head=HEAD)

    def test_independent_receiver_pin_and_run_head_are_required_before_reading_state(self):
        r=self.receiver()
        for edits in ({'expected_receiver_sha':'0'*64},{'expected_run_id':'101'},
                      {'expected_source_head':'c'*40}):
            kwargs=dict(expected_receiver_sha=sha((wire(r)+'\n').encode()),expected_run_id='100',
                        expected_source_head=HEAD,output=self.root/'absent')
            kwargs.update(edits)
            with self.assertRaises(ValueError):self.m.encrypt_transfer(self.root/'missing.sqlite',r,**kwargs)
            self.assertFalse((self.root/'absent').exists())

    def test_separate_receiver_and_reader_preserve_originals_and_replay(self):
        state,pair=invented_research_state(self.root)
        report=self.transfer(state,self.root/'out');pointer=self.pointer(report)
        cipher=(self.root/'out/transfer.enc').read_bytes()
        self.assertNotIn(b'SQLite format 3',cipher)
        self.assertNotIn(base64.b64encode(OWNER),cipher)
        urls=[]
        def fetch(url):urls.append(url);return cipher
        produced=self.m.receive_transfer(pointer,self.root/'producer',key=OWNER,fetch=fetch,
            run_id='200',source_head=HEAD,now=NOW)
        self.assertTrue(produced['encrypted_checkpoint_created'])
        self.assertEqual(urls,['https://raw.githubusercontent.com/haji84/RACE-AI/'+'a'*40+'/'+pointer['cipher_path']])
        verified=self.m.verify_received_checkpoint(self.root/'producer/sealed',self.root/'consumer',key=OWNER,
            expected_run_id='200',expected_source_head=HEAD,expected_transfer_sha=report['cipher_sha256'],now=NOW)
        self.assertTrue(verified['production_schema_readback_verified'])
        self.assertEqual(verified['pairs_verified'],1)
        self.assertEqual(verified['score_replays'],1)
        original=self.root/'pair.json'
        restored=self.root/'consumer/materialized/pairs'/f"{pair['pair_sha256']}.json"
        self.assertEqual(restored.read_bytes(),original.read_bytes())

    def test_wrong_root_tamper_and_input_locator_never_emit_plaintext(self):
        state,_=invented_research_state(self.root);r=self.transfer(state,self.root/'out')
        p=self.pointer(r);raw=(self.root/'out/transfer.enc').read_bytes()
        with self.assertRaises(ValueError):self.m.receive_transfer(p,self.root/'wrong',key=os.urandom(32),
            fetch=lambda _:raw,run_id='200',source_head=HEAD,now=NOW)
        self.assertFalse((self.root/'wrong/incoming.sqlite').exists())
        for field,value in [('source_commit','../main'),('cipher_path','other/state.enc')]:
            bad=deepcopy(p);bad[field]=value
            with self.assertRaises(ValueError):self.m.receive_transfer(bad,self.root/'bad-path',key=OWNER,
                fetch=lambda _:self.fail('invalid locator performed GET'),run_id='200',source_head=HEAD,now=NOW)
        envelope=json.loads(raw);body=bytearray(base64.b64decode(envelope['ciphertext']));body[-1]^=1
        envelope['ciphertext']=base64.b64encode(body).decode();changed=(wire(envelope)+'\n').encode()
        bad=deepcopy(p);bad['cipher_sha256']=sha(changed);bad['cipher_path']='state/boat-pdca-incoming/v1/'+sha(changed)+'.enc'
        with self.assertRaises(ValueError):self.m.receive_transfer(bad,self.root/'tampered',key=OWNER,
            fetch=lambda _:changed,run_id='200',source_head=HEAD,now=NOW)
        self.assertFalse((self.root/'tampered/incoming.sqlite').exists())

    def test_next_generation_preserves_results_and_requires_previous_state(self):
        state,pair=invented_research_state(self.root)
        first=self.transfer(state,self.root/'first')
        a=self.m.receive_transfer(self.pointer(first),self.root/'a',key=OWNER,
            fetch=lambda _:(self.root/'first/transfer.enc').read_bytes(),run_id='200',source_head=HEAD,now=NOW)
        previous=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
            source_commit='d'*40,cipher_path='state/boat-pdca/v1/g000001/state.enc',
            cipher_sha256=a['cipher_sha256'],scope=a['scope'])
        from tests.test_boat_pdca_state import result
        s=PdcaState(state);updated=result(pair);updated['captured_at']='2026-11-06T11:30:00+09:00'
        updated['source_sha256']='c'*64;updated['data']['payouts'][0]['payout_per_100_yen']=2400
        s.score(pair['pair_sha256'],updated,NOW);s.close()
        second=self.transfer(state,self.root/'second',previous=previous)
        def fetch(url):return (self.root/('a/sealed/state.enc' if '/g000001/' in url else 'second/transfer.enc')).read_bytes()
        b=self.m.receive_transfer(self.pointer(second),self.root/'b',key=OWNER,fetch=fetch,
            run_id='201',source_head=HEAD,previous_pointer=previous,now=NOW)
        self.assertEqual(b['scope']['generation'],2)
        self.assertEqual(b['scope']['previous_cipher_sha256'],a['cipher_sha256'])
        self.assertEqual(b['result_revisions'],2)
        with self.assertRaises(ValueError):self.m.receive_transfer(self.pointer(second),self.root/'no-parent',key=OWNER,
            fetch=fetch,run_id='201',source_head=HEAD,now=NOW)

    def test_invalid_json_base64_bounds_and_absent_key_are_fail_closed(self):
        from unittest.mock import patch
        state,_=invented_research_state(self.root);r=self.transfer(state,self.root/'out')
        raw=(self.root/'out/transfer.enc').read_bytes();p=self.pointer(r)
        with patch.dict(os.environ,{},clear=True):
            hold=self.m.receive_transfer(p,self.root/'no-key',fetch=lambda _:self.fail('keyless GET'),
                run_id='200',source_head=HEAD,now=NOW)
        self.assertEqual(hold['source_gets'],0);self.assertFalse((self.root/'no-key').exists())
        malformed=json.loads(raw);malformed['nonce']+='\n'
        bad_raw=(wire(malformed)+'\n').encode()
        bad=self.pointer(dict(r,cipher_sha256=sha(bad_raw)))
        with self.assertRaises(ValueError):self.m.receive_transfer(bad,self.root/'bad64',key=OWNER,
            fetch=lambda _:bad_raw,run_id='200',source_head=HEAD,now=NOW)
        duplicate=raw[:-2]+b',"nonce":"AAAA"}\n'
        bad=self.pointer(dict(r,cipher_sha256=sha(duplicate)))
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.m.receive_transfer(bad,self.root/'duplicate',key=OWNER,
            fetch=lambda _:duplicate,run_id='200',source_head=HEAD,now=NOW)
        with patch.object(self.m,'MAX_TRANSFER',len(raw)-1):
            with self.assertRaisesRegex(ValueError,'HASH'):self.m.receive_transfer(p,self.root/'large',key=OWNER,
                fetch=lambda _:raw,run_id='200',source_head=HEAD,now=NOW)

    def test_cli_receiver_publishes_public_metadata_only_and_sanitizes_errors(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from scripts.boat_pdca_transfer import main
        encoded=base64.b64encode(OWNER).decode();out=StringIO()
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':encoded}),redirect_stdout(out):
            code=main(['receiver','--private-dir',str(self.root/'receiver'),'--run-id','100','--source-head',HEAD])
        self.assertEqual(code,0);self.assertNotIn(encoded,out.getvalue())
        self.assertEqual(json.loads((self.root/'receiver/receiver.json').read_text())['key_id'],self.receiver()['key_id'])
        with patch('scripts.boat_pdca_transfer.receiver_document',side_effect=RuntimeError(encoded)),redirect_stdout(out):
            code=main(['receiver','--private-dir',str(self.root/'error'),'--run-id','100','--source-head',HEAD])
        self.assertEqual(code,2);self.assertNotIn(encoded,out.getvalue())

    def test_git_transport_ref_is_fixed_and_completed_cipher_publication_is_create_only(self):
        import subprocess
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        repo=self.root/'repo';bare=self.root/'bare.git'
        for args in (['init',str(repo)],['init','--bare',str(bare)]):
            subprocess.run(['git',*args],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'remote','add','origin',str(bare)],check=True,capture_output=True)
        class LocalGit(GitStateRepository):
            def _check_remote(self):self.fetch_url=self.push_url=str(bare)
        with self.assertRaises(ValueError):LocalGit(repo,ref='main')
        state,_=invented_research_state(self.root);report=self.transfer(state,self.root/'offer')
        transport=LocalGit(repo,ref='state/boat-pdca-transfer')
        pointer=self.m.publish_incoming(repo,self.root/'offer',transport=transport)
        repeated=self.m.publish_incoming(repo,self.root/'offer',transport=transport)
        self.assertEqual(pointer,repeated)
        self.m.receive_transfer(pointer,self.root/'producer',key=OWNER,
            fetch=lambda _:(self.root/'offer/transfer.enc').read_bytes(),run_id='200',source_head=HEAD,now=NOW)
        consumer=self.m.verify_received_checkpoint(self.root/'producer/sealed',self.root/'consumer',key=OWNER,
            expected_run_id='200',expected_source_head=HEAD,expected_transfer_sha=report['cipher_sha256'],now=NOW)
        consumer_file=self.root/'consumer.json';consumer_file.write_text(wire(consumer)+'\n')
        kwargs=dict(expected_run_id='200',expected_source_head=HEAD,expected_transfer_sha=report['cipher_sha256'],
            expected_consumer_sha=sha(consumer_file.read_bytes()),expected_recipient_key_id=self.receiver()['key_id'],
            consumer_proof=consumer_file,transport=LocalGit(repo),initialize=True)
        final=self.m.publish_received(repo,self.root/'producer/sealed',**kwargs)
        self.assertEqual(final['scope']['generation'],1)
        self.assertEqual(final['status'],'READY')
        with self.assertRaises(ValueError):self.m.publish_received(repo,self.root/'producer/sealed',**kwargs)
