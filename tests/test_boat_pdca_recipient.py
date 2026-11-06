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

    def test_git_rewrite_chain_cannot_redirect_a_validated_github_destination(self):
        import subprocess
        from race_ai.boat_pdca_github_handoff import GitStateRepository
        repo=self.root/'repo'
        subprocess.run(['git','init',str(repo)],check=True,capture_output=True)
        def run(*args):return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
        good='https://github.com/haji84/RACE-AI.git'
        run('remote','add','origin','review-safe-alias')
        run('config','url.'+good+'.insteadOf','review-safe-alias')
        run('config','url.file:///unrelated.git.insteadOf',good)
        self.assertEqual(run('remote','get-url','origin').stdout.decode().strip(),good)
        with self.assertRaisesRegex(ValueError,'REWRITES_REJECTED'):GitStateRepository(repo)
        run('config','--remove-section','url.'+good)
        run('config','--remove-section','url.file:///unrelated.git')
        run('remote','set-url','origin',good)
        transport=GitStateRepository(repo)
        run('config','url.file:///unrelated.git.pushInsteadOf',good)
        with self.assertRaisesRegex(ValueError,'REWRITES_REJECTED'):transport.head()

    def test_workflow_consumer_restores_the_producer_artifacts_nested_checkpoint(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import shlex
        import shutil
        from unittest.mock import patch
        from scripts.boat_pdca_transfer import main
        state,_=invented_research_state(self.root);r=self.transfer(state,self.root/'offer')
        self.m.receive_transfer(self.pointer(r),self.root/'producer',key=OWNER,
            fetch=lambda _:(self.root/'offer/transfer.enc').read_bytes(),run_id='200',source_head=HEAD,now=NOW)
        # upload-artifact roots sealed/* and status.json at their common parent.
        incoming=self.root/'boat-owner-state-incoming'
        shutil.copytree(self.root/'producer/sealed',incoming/'sealed')
        (incoming/'status.json').write_text('{"status":"OWNER_PDCA_TRANSFER_SEALED"}')
        workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/forecast-audit-ui.yml').read_text()
        command=next(line.strip()[5:] for line in workflow.splitlines()
                     if line.strip().startswith('run: python -m scripts.boat_pdca_transfer verify '))
        env={'RACE_AI_STATE_KEY':base64.b64encode(OWNER).decode(),'RUNNER_TEMP':str(self.root),
             'RACE_AI_SOURCE_HEAD':HEAD,'GITHUB_RUN_ID':'200','RACE_AI_EXPECTED_TRANSFER_SHA':r['cipher_sha256']}
        self.assertIn('--input audit/state/boat-pdca-transfer-input.json',command)
        def verify(folder,root,**kw):return self.m.verify_received_checkpoint(folder,root,now=NOW,**kw)
        with patch.dict(os.environ,env),patch('scripts.boat_pdca_transfer.bounded_json',return_value=self.pointer(r)),patch('scripts.boat_pdca_transfer.verify_received_checkpoint',side_effect=verify),redirect_stdout(StringIO()):
            argv=[os.path.expandvars(part) for part in shlex.split(command)][3:]
            code=main(argv)
        self.assertEqual(code,0)
        proof=json.loads((self.root/'boat-owner-state-readback/status.json').read_text())
        self.assertTrue(proof['production_schema_readback_verified'])

    def test_state_content_identity_ignores_sqlite_layout_and_detects_retained_changes(self):
        state,_=invented_research_state(self.root);first=PdcaState(state)
        other=PdcaState.create(self.root/'copy.sqlite',mode='production')
        try:
            fingerprint=first.content_sha256();first.db.backup(other.db)
            self.assertEqual(fingerprint,other.content_sha256())
            with other.db:other._put('additional-original.json',b'fictional retained original')
            self.assertNotEqual(fingerprint,other.content_sha256())
            first.db.backup(other.db);same_count=other.inventory()
            with other.db:other.db.execute("UPDATE scores SET body=body||' '")
            self.assertEqual(same_count,other.inventory())
            self.assertNotEqual(fingerprint,other.content_sha256())
        finally:first.close();other.close()

    def test_merge_retains_both_sources_and_previous_active_file_head(self):
        a=self.root/'a';b=self.root/'b';a.mkdir(mode=0o700);b.mkdir(mode=0o700)
        old_path,_=invented_research_state(a);new_path,_=invented_research_state(b)
        old=PdcaState(old_path);new=PdcaState(new_path)
        try:
            with old.db:old_sha=old._put('history.sqlite',b'fictional previous history')
            with new.db:new_sha=new._put('history.sqlite',b'fictional incoming history')
            source_id=new.content_sha256();before=old.inventory()
            self.assertEqual(old.merge_from(new),source_id)
            self.assertEqual(old.db.execute("SELECT sha FROM heads WHERE name='history.sqlite'").fetchone(),(old_sha,))
            self.assertEqual(old._get(new_sha),b'fictional incoming history')
            self.assertTrue(old.verify_contribution(source_id))
            self.assertEqual(old.inventory()['pairs'],before['pairs'])
            first=old.content_sha256();old.merge_from(new)
            self.assertEqual(first,old.content_sha256())
            with old.db:old.db.execute("UPDATE scores SET body=body||' '")
            with self.assertRaises(ValueError):old.verify_contribution(source_id)
        finally:old.close();new.close()

    def test_conflicting_pair_receipts_cannot_replace_previous_original(self):
        from race_ai.actions_contract import digest
        a=self.root/'a';b=self.root/'b';a.mkdir(mode=0o700);b.mkdir(mode=0o700)
        old_path,pair=invented_research_state(a);new_path,_=invented_research_state(b)
        old=PdcaState(old_path);new=PdcaState(new_path)
        try:
            before=old.content_sha256();ident=pair['pair_sha256']
            receipt_sha=new.db.execute('SELECT receipt_sha FROM pairs WHERE sha=?',(ident,)).fetchone()[0]
            receipt=json.loads(new._get(receipt_sha));receipt['write_completed_at']='2026-11-06T01:30:00.001000+09:00'
            receipt['receipt_sha256']=digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
            with new.db:
                changed=new._put(f'pairs/{ident}.receipt.json',(wire(receipt)+'\n').encode())
                new.db.execute('UPDATE pairs SET receipt_sha=? WHERE sha=?',(changed,ident))
            with self.assertRaisesRegex(ValueError,'MERGE_RECORD_CONFLICT'):old.merge_from(new)
            self.assertEqual(before,old.content_sha256())
        finally:old.close();new.close()

    def test_next_transfer_unions_previous_originals_instead_of_losing_another_workers_data(self):
        a=self.root/'a';b=self.root/'b';a.mkdir(mode=0o700);b.mkdir(mode=0o700)
        old_path,_=invented_research_state(a);new_path,_=invented_research_state(b)
        s=PdcaState(old_path)
        with s.db:s._put('previous-worker-original.json',b'fictional preserved prior research')
        s.close()
        first=self.transfer(old_path,self.root/'first')
        old=self.m.receive_transfer(self.pointer(first),self.root/'old',key=OWNER,
            fetch=lambda _:(self.root/'first/transfer.enc').read_bytes(),run_id='200',source_head=HEAD,now=NOW)
        previous=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
            source_commit='d'*40,cipher_path='state/boat-pdca/v1/g000001/state.enc',
            cipher_sha256=old['cipher_sha256'],scope=old['scope'])
        second=self.transfer(new_path,self.root/'second',previous=previous)
        def fetch(url):return (self.root/('old/sealed/state.enc' if '/g000001/' in url else 'second/transfer.enc')).read_bytes()
        produced=self.m.receive_transfer(self.pointer(second),self.root/'new',key=OWNER,fetch=fetch,
            run_id='201',source_head=HEAD,previous_pointer=previous,now=NOW)
        self.assertEqual(produced['scope']['generation'],2)
        proof=self.m.verify_received_checkpoint(self.root/'new/sealed',self.root/'reader',key=OWNER,
            expected_run_id='201',expected_source_head=HEAD,expected_transfer_sha=second['cipher_sha256'],now=NOW)
        self.assertTrue(proof['incoming_originals_verified'])
        self.assertEqual((self.root/'reader/materialized/previous-worker-original.json').read_bytes(),b'fictional preserved prior research')

    def test_union_retains_divergent_pair_and_result_revisions_for_the_same_race(self):
        from race_ai.boat_history_store import HistoryStore
        from race_ai.boat_history_comparison import prepare_pair,freeze_pair
        from tests.test_boat_history_comparison import current
        from tests.test_boat_pdca_state import result
        a=self.root/'a';b=self.root/'b';a.mkdir(mode=0o700);b.mkdir(mode=0o700)
        old_path,pair_a=invented_research_state(a);new_path,_=invented_research_state(b)
        old=self.transfer(old_path,self.root/'first')
        sealed=self.m.receive_transfer(self.pointer(old),self.root/'old',key=OWNER,
            fetch=lambda _:(self.root/'first/transfer.enc').read_bytes(),run_id='200',source_head=HEAD,now=NOW)
        # Separate valid journal for the same race, with its own later frozen pair.
        new_path.unlink();history=HistoryStore(b/'history.sqlite')
        pair_b=prepare_pair(current(),history,'2026-11-06T01:31:00+09:00');history.close()
        freeze_pair(pair_b,b/'later.json',clock=lambda:instant('2026-11-06T01:31:00+09:00'))
        incoming=PdcaState.create(new_path,mode='production');incoming.retain_pair(b/'later.json')
        later=result(pair_b);later['captured_at']='2026-11-06T11:20:00+09:00'
        incoming.score(pair_b['pair_sha256'],later,NOW);incoming.close()
        previous=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
            source_commit='d'*40,cipher_path='state/boat-pdca/v1/g000001/state.enc',
            cipher_sha256=sealed['cipher_sha256'],scope=sealed['scope'])
        transfer=self.transfer(new_path,self.root/'second',previous=previous)
        def fetch(url):return (self.root/('old/sealed/state.enc' if '/g000001/' in url else 'second/transfer.enc')).read_bytes()
        report=self.m.receive_transfer(self.pointer(transfer),self.root/'new',key=OWNER,fetch=fetch,
            run_id='201',source_head=HEAD,previous_pointer=previous,now=NOW)
        self.assertEqual(report['pairs'],2);self.assertEqual(report['result_revisions'],2)
        self.assertEqual(report['scorings'],3)
        self.assertTrue(self.m.verify_received_checkpoint(self.root/'new/sealed',self.root/'reader',key=OWNER,
            expected_run_id='201',expected_source_head=HEAD,expected_transfer_sha=transfer['cipher_sha256'],now=NOW)['incoming_originals_verified'])
