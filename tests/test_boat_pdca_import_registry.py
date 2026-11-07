"""Invented owner-encrypted imports: replay without replacing a canonical stream."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest

from race_ai.boat_history_store import instant,wire
from race_ai.boat_pdca_state import sha
from race_ai.boat_pdca_recipient import receiver_document,encrypt_transfer,receive_transfer,verify_received_checkpoint
from tests.test_boat_pdca_github_handoff import invented_research_state


class AcceptedImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.key=os.urandom(32);self.head='b'*40;self.now=instant('2026-11-06T12:00:00+09:00')
        state,pair=invented_research_state(self.root);self.pair_sha=pair['pair_sha256']
        receiver=receiver_document(key=self.key,run_id='100',source_head=self.head)
        transfer=encrypt_transfer(state,receiver,expected_receiver_sha=sha((wire(receiver)+'\n').encode()),
            expected_run_id='100',expected_source_head=self.head,output=self.root/'transport',now=self.now)
        self.pointer=dict(transfer,status='READY',source_commit='a'*40,
            cipher_path='state/boat-pdca-incoming/v1/'+transfer['cipher_sha256']+'.enc')
        receive_transfer(self.pointer,self.root/'producer',key=self.key,fetch=lambda url:(self.root/'transport/transfer.enc').read_bytes(),
                         run_id='200',source_head=self.head,now=self.now)
        report=verify_received_checkpoint(self.root/'producer/sealed',self.root/'consumer',key=self.key,
            expected_run_id='200',expected_source_head=self.head,expected_transfer_sha=transfer['cipher_sha256'],now=self.now)
        self.consumer=self.root/'consumer-proof.json';self.consumer.write_text(wire(report)+'\n')

    def register(self):
        from race_ai.boat_pdca_import_registry import register_import
        return register_import(self.root/'producer/sealed',self.consumer,
            expected_consumer_sha=sha(self.consumer.read_bytes()),archive_commit='c'*40,key=self.key,now=self.now)

    def test_exact_accepted_initial_stream_is_restored_without_fresh_encryption(self):
        from race_ai.boat_pdca_import_registry import reuse_import
        entry=self.register();registry={'schema':'RACE_AI_BOAT_ACCEPTED_IMPORTS_V1','repository_id':'1416489937','imports':[entry]}
        calls=[]
        def fetch(url):calls.append(url);return (self.root/'producer/sealed/state.enc').read_bytes()
        out=reuse_import(self.pointer,registry,self.root/'reused',key=self.key,fetch=fetch,now=self.now)
        self.assertEqual(out['pairs_verified'],1);self.assertEqual(out['score_replays'],1)
        self.assertFalse(out['encrypted_checkpoint_created']);self.assertFalse(out['canonical_state_changed'])
        self.assertEqual(len(calls),1);self.assertIn('/'+'c'*40+'/state/boat-pdca-imports/',calls[0])
        self.assertEqual((self.root/'reused/materialized/pairs'/(self.pair_sha+'.json')).read_bytes(),(self.root/'pair.json').read_bytes())

    def test_registry_tamper_or_wrong_key_stops_before_source_get(self):
        from race_ai.boat_pdca_import_registry import reuse_import
        entry=self.register()
        for field,value in [('archive_commit','d'*40),('cipher_sha256','e'*64),('transfer_sha256','f'*64)]:
            bad=deepcopy(entry);bad[field]=value
            registry={'schema':'RACE_AI_BOAT_ACCEPTED_IMPORTS_V1','repository_id':'1416489937','imports':[bad]}
            with self.subTest(field=field),self.assertRaises(ValueError):
                reuse_import(self.pointer,registry,self.root/field,key=self.key,fetch=lambda u:self.fail('tampered registry performed GET'),now=self.now)
        registry={'schema':'RACE_AI_BOAT_ACCEPTED_IMPORTS_V1','repository_id':'1416489937','imports':[entry]}
        with self.assertRaises(ValueError):reuse_import(self.pointer,registry,self.root/'wrong',key=os.urandom(32),fetch=lambda u:self.fail('wrong key GET'),now=self.now)

    def test_unknown_transfer_does_not_claim_reuse_or_weaken_original_receiver(self):
        from race_ai.boat_pdca_import_registry import reuse_import
        registry={'schema':'RACE_AI_BOAT_ACCEPTED_IMPORTS_V1','repository_id':'1416489937','imports':[]}
        self.assertIsNone(reuse_import(self.pointer,registry,self.root/'unknown',key=self.key,fetch=lambda u:self.fail('unknown replay GET'),now=self.now))

    def test_receive_cli_uses_verified_import_even_when_another_canonical_stream_exists(self):
        import base64,io,json
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from scripts.boat_pdca_transfer import main
        entry=self.register();registry={'schema':'RACE_AI_BOAT_ACCEPTED_IMPORTS_V1','repository_id':'1416489937','imports':[entry]}
        for name,value in [('input.json',self.pointer),('registry.json',registry),('previous.json',{'status':'READY','source_commit':'d'*40})]:
            (self.root/name).write_text(wire(value))
        out=io.StringIO()
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(self.key).decode()}),\
             patch('race_ai.boat_pdca_import_registry._fetch_cipher',return_value=(self.root/'producer/sealed/state.enc').read_bytes()),redirect_stdout(out):
            code=main(['receive','--input',str(self.root/'input.json'),'--previous-input',str(self.root/'previous.json'),
                '--accepted-imports',str(self.root/'registry.json'),'--private-dir',str(self.root/'cli'),
                '--run-id','300','--source-head',self.head])
        self.assertEqual(code,0,out.getvalue())
        report=json.loads((self.root/'cli/status.json').read_text())
        self.assertEqual(report['pairs_verified'],1);self.assertFalse(report['canonical_state_changed'])
        self.assertNotIn(base64.b64encode(self.key).decode(),out.getvalue())
