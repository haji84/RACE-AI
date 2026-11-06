"""Invented data: deliver to the configured owner's recipient without exporting its key."""
from copy import deepcopy
from pathlib import Path
import base64
import json
import os
import tempfile
import unittest
from unittest.mock import patch

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

    def canonical(self,state_path,folder,*,generation=1,previous_sha=None,key=OWNER):
        state=PdcaState(state_path)
        try:proof=state.checkpoint(folder,generation=generation,previous_cipher_sha256=previous_sha,key=key)
        finally:state.close()
        pointer=dict(schema='RACE_AI_BOAT_PRODUCTION_STATE_INPUT_V1',status='READY',repository_id='1416489937',
            source_commit='d'*40,cipher_path=f'state/boat-pdca/v1/g{generation:06d}/state.enc',
            cipher_sha256=proof['cipher_sha256'],scope=proof['scope'])
        return pointer,(folder/'state.enc').read_bytes()

    def receive_stale(self,transfer,cipher,current,current_cipher,out,*,key=OWNER):
        pointer=self.pointer(transfer)
        records={
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+pointer['source_commit']+'/'+pointer['cipher_path']:cipher,
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+current['source_commit']+'/'+current['cipher_path']:current_cipher}
        calls=[]
        def fetch(url):calls.append(url);return records[url]
        value=self.m.receive_transfer(pointer,out,key=key,fetch=fetch,run_id='201',source_head=HEAD,
            previous_pointer=current,now=NOW)
        self.assertEqual(len(calls),2)
        return value

    def test_verified_same_generation_is_already_covered_without_another_checkpoint(self):
        state,_=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        current,current_cipher=self.canonical(state,self.root/'canonical')
        before=state.read_bytes();out=self.root/'covered'
        with patch.object(PdcaState,'checkpoint',side_effect=AssertionError('no new checkpoint for covered originals')):
            result=self.receive_stale(transfer,cipher,current,current_cipher,out)
        self.assertEqual(result['status'],'OWNER_PDCA_TRANSFER_ALREADY_COVERED')
        self.assertFalse(result['encrypted_checkpoint_created'])
        self.assertTrue(result['production_schema_readback_verified'])
        self.assertTrue(result['incoming_originals_covered'])
        self.assertEqual(result['scope'],current['scope'])
        self.assertEqual(result['cipher_sha256'],current['cipher_sha256'])
        self.assertEqual(result['pairs_verified'],1)
        self.assertEqual(result['score_replays'],1)
        self.assertFalse(result['plaintext_published'])
        self.assertEqual(list(out.iterdir()),[])
        self.assertEqual(state.read_bytes(),before)

    def test_later_canonical_keeps_every_incoming_original_and_newer_result_revision(self):
        from tests.test_boat_pdca_state import result
        state,pair=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        first,_=self.canonical(state,self.root/'first')
        updated=result(pair);updated.update(captured_at='2026-11-06T11:30:00+09:00',source_sha256='c'*64)
        updated['data']['payouts'][0]['payout_per_100_yen']=2400
        current_state=PdcaState(state)
        try:current_state.score(pair['pair_sha256'],updated,NOW)
        finally:current_state.close()
        current,current_cipher=self.canonical(state,self.root/'canonical',generation=2,previous_sha=first['cipher_sha256'])
        before=state.read_bytes();out=self.root/'covered'
        with patch.object(PdcaState,'checkpoint',side_effect=AssertionError('covered transfer must not advance generation')):
            result=self.receive_stale(transfer,cipher,current,current_cipher,out)
        self.assertEqual(result['status'],'OWNER_PDCA_TRANSFER_ALREADY_COVERED')
        self.assertFalse(result['encrypted_checkpoint_created'])
        self.assertEqual(result['scope']['generation'],2)
        self.assertEqual(result['result_revisions'],2)
        self.assertEqual(list(out.iterdir()),[])
        self.assertEqual(state.read_bytes(),before)

    def test_same_generation_with_missing_incoming_originals_is_not_skipped(self):
        from tests.test_boat_pdca_state import result
        state,pair=invented_research_state(self.root)
        current,current_cipher=self.canonical(state,self.root/'canonical')
        updated=result(pair);updated.update(captured_at='2026-11-06T11:30:00+09:00',source_sha256='c'*64)
        updated['data']['payouts'][0]['payout_per_100_yen']=2400
        changed=PdcaState(state)
        try:changed.score(pair['pair_sha256'],updated,NOW)
        finally:changed.close()
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        out=self.root/'rejected'
        with self.assertRaisesRegex(ValueError,'STATE_REGRESSION_'):
            self.receive_stale(transfer,cipher,current,current_cipher,out)
        self.assertFalse((out/'sealed').exists())
        self.assertFalse((out/'incoming.sqlite').exists())

    def test_later_generation_with_conflicting_original_result_is_not_skipped(self):
        from tests.test_boat_pdca_state import result
        state,pair=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        other=PdcaState.create(self.root/'conflicting.sqlite',mode='production')
        try:
            other.retain_pair(self.root/'pair.json')
            conflict=result(pair);conflict['source_sha256']='c'*64
            conflict['data']['payouts'][0]['payout_per_100_yen']=2400
            other.score(pair['pair_sha256'],conflict,NOW)
        finally:other.close()
        current,current_cipher=self.canonical(self.root/'conflicting.sqlite',self.root/'canonical',generation=2,previous_sha='e'*64)
        with self.assertRaisesRegex(ValueError,'STATE_REGRESSION_'):
            self.receive_stale(transfer,cipher,current,current_cipher,self.root/'rejected')
        self.assertFalse((self.root/'rejected/sealed').exists())
        self.assertFalse((self.root/'rejected/incoming.sqlite').exists())

    def test_already_covered_candidate_still_authenticates_incoming_and_canonical_cipher(self):
        state,_=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        current,current_cipher=self.canonical(state,self.root/'canonical')
        wrong_current,wrong_cipher=self.canonical(state,self.root/'wrong-key-canonical',key=os.urandom(32))
        for name,incoming,raw,prior,prior_raw in (
            ('incoming-hash',transfer,cipher+b'changed',current,current_cipher),
            ('canonical-hash',transfer,cipher,current,current_cipher+b'changed'),
            ('canonical-key',transfer,cipher,wrong_current,wrong_cipher)):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'HASH|AUTHENTICATION'):
                self.receive_stale(incoming,raw,prior,prior_raw,self.root/name)
            self.assertFalse((self.root/name/'incoming.sqlite').exists())
            self.assertFalse((self.root/name/'sealed').exists())
        with self.assertRaisesRegex(ValueError,'OWNER_KEY'):
            self.receive_stale(transfer,cipher,current,current_cipher,self.root/'wrong-owner',key=os.urandom(32))

    def test_already_covered_candidate_rejects_validly_encrypted_but_tampered_transport(self):
        state,_=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        current,current_cipher=self.canonical(state,self.root/'canonical')
        body=json.loads(cipher);raw=bytearray(base64.b64decode(body['ciphertext']));raw[-1]^=1
        body['ciphertext']=base64.b64encode(raw).decode();tampered=(wire(body)+'\n').encode()
        changed=dict(transfer,cipher_sha256=sha(tampered))
        with self.assertRaisesRegex(ValueError,'RECIPIENT_TRANSFER_AUTHENTICATION_FAILED'):
            self.receive_stale(changed,tampered,current,current_cipher,self.root/'rejected')
        self.assertFalse((self.root/'rejected/incoming.sqlite').exists())

    def test_forward_generation_keeps_exact_parent_identity_checks(self):
        state,_=invented_research_state(self.root)
        current,_=self.canonical(state,self.root/'canonical')
        transfer=self.transfer(state,self.root/'offer',previous=current)
        for field,value in (('cipher_sha256','e'*64),('source_commit','e'*40)):
            prior=dict(current,**{field:value})
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'RECIPIENT_PREVIOUS_STATE_MISMATCH'):
                self.m.receive_transfer(self.pointer(transfer),self.root/field,key=OWNER,
                    fetch=lambda _:self.fail('parent mismatch must fail before source GET'),
                    run_id='201',source_head=HEAD,previous_pointer=prior,now=NOW)

    def test_cli_already_covered_succeeds_without_new_encrypted_output(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts.boat_pdca_transfer import main
        state,_=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        incoming=self.pointer(transfer);current,current_cipher=self.canonical(state,self.root/'canonical')
        records={
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+incoming['source_commit']+'/'+incoming['cipher_path']:cipher,
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+current['source_commit']+'/'+current['cipher_path']:current_cipher}
        offered=self.root/'incoming.json';offered.write_text(wire(incoming))
        previous=self.root/'previous.json';previous.write_text(wire(current))
        output=self.root/'received';gha=self.root/'github-output';printed=StringIO()
        receive=self.m.receive_transfer
        def replay(pointer,root,**kwargs):
            return receive(pointer,root,fetch=records.__getitem__,now=NOW,**kwargs)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(OWNER).decode(),'GITHUB_OUTPUT':str(gha)}),\
                patch('scripts.boat_pdca_transfer.receive_transfer',side_effect=replay),redirect_stdout(printed):
            code=main(['receive','--input',str(offered),'--previous-input',str(previous),
                '--private-dir',str(output),'--run-id','201','--source-head',HEAD])
        self.assertEqual(code,0)
        report=json.loads((output/'status.json').read_text())
        self.assertEqual(report['status'],'OWNER_PDCA_TRANSFER_ALREADY_COVERED')
        self.assertFalse(report['encrypted_checkpoint_created'])
        self.assertEqual(gha.read_text(),'encrypted=false\n')
        self.assertEqual({path.name for path in output.iterdir()},{'status.json'})
        self.assertNotIn(base64.b64encode(OWNER).decode(),printed.getvalue())

    def cli_receive_stale(self,transfer,cipher,current,current_cipher,output,*,error=None):
        from contextlib import redirect_stdout
        from io import StringIO
        from scripts.boat_pdca_transfer import main
        incoming=self.pointer(transfer)
        records={
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+incoming['source_commit']+'/'+incoming['cipher_path']:cipher,
            'https://raw.githubusercontent.com/haji84/RACE-AI/'+current['source_commit']+'/'+current['cipher_path']:current_cipher}
        offered=self.root/(output.name+'-input.json');offered.write_text(wire(incoming))
        previous=self.root/(output.name+'-previous.json');previous.write_text(wire(current))
        gha=self.root/(output.name+'-outputs');printed=StringIO();receive=self.m.receive_transfer
        def replay(pointer,root,**kwargs):
            if error is not None:raise error
            return receive(pointer,root,fetch=records.__getitem__,now=NOW,**kwargs)
        with patch.dict(os.environ,{'RACE_AI_STATE_KEY':base64.b64encode(OWNER).decode(),'GITHUB_OUTPUT':str(gha)}),\
                patch('scripts.boat_pdca_transfer.receive_transfer',side_effect=replay),redirect_stdout(printed):
            code=main(['receive','--input',str(offered),'--previous-input',str(previous),
                '--private-dir',str(output),'--run-id','201','--source-head',HEAD])
        return code,printed.getvalue(),gha

    def test_cli_noncoverage_is_explicit_rebase_hold_without_import_or_rewrite(self):
        state,_=invented_research_state(self.root)
        current,current_cipher=self.canonical(state,self.root/'canonical')
        extra=b'fictional extra captured original'
        changed=PdcaState(state)
        try:
            with changed.db:changed._put('capture/extra-original.bin',extra)
        finally:changed.close()
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        originals={path:(path.read_bytes(),path.stat().st_mtime_ns)
            for path in [state,self.root/'pair.json',self.root/'canonical/state.enc',self.root/'offer/transfer.enc']}
        before=deepcopy((transfer,current));output=self.root/'rebase'
        with patch.object(PdcaState,'checkpoint',side_effect=AssertionError('rebase HOLD cannot issue a checkpoint')):
            code,printed,gha=self.cli_receive_stale(transfer,cipher,current,current_cipher,output)
        self.assertEqual(code,0)
        report=json.loads((output/'status.json').read_text())
        self.assertEqual(report['status'],'HOLD_TRANSFER_REBASE_REQUIRED')
        self.assertEqual(report['reason'],'STATE_REGRESSION_FILES')
        self.assertFalse(report['incoming_originals_covered'])
        self.assertFalse(report['transfer_imported'])
        self.assertFalse(report['encrypted_checkpoint_created'])
        self.assertTrue(report['canonical_state_preserved'])
        self.assertEqual(report['required_next_generation'],2)
        self.assertEqual(report['source_gets'],2)
        self.assertEqual(gha.read_text(),'encrypted=false\n')
        self.assertEqual({path.name for path in output.iterdir()},{'status.json'})
        self.assertEqual(originals,{path:(path.read_bytes(),path.stat().st_mtime_ns) for path in originals})
        self.assertEqual((transfer,current),before)
        self.assertNotIn(extra.decode(),printed)
        self.assertNotIn(str(self.root),printed)
        self.assertNotIn(base64.b64encode(OWNER).decode(),printed)

    def test_library_noncoverage_remains_value_error_with_original_state_reason(self):
        state,_=invented_research_state(self.root)
        current,current_cipher=self.canonical(state,self.root/'canonical')
        changed=PdcaState(state)
        try:
            with changed.db:changed._put('capture/extra-original.bin',b'fictional extra original')
        finally:changed.close()
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        output=self.root/'library-rejected'
        with self.assertRaisesRegex(ValueError,'^STATE_REGRESSION_FILES$') as caught:
            self.receive_stale(transfer,cipher,current,current_cipher,output)
        self.assertEqual(type(caught.exception).__name__,'StaleTransferRebaseRequired')
        self.assertEqual(caught.exception.required_next_generation,2)
        self.assertEqual(list(output.iterdir()),[])

    def test_cli_authentication_future_or_untyped_failures_are_still_fatal(self):
        from tests.test_boat_pdca_state import result
        state,pair=invented_research_state(self.root)
        transfer=self.transfer(state,self.root/'offer');cipher=(self.root/'offer/transfer.enc').read_bytes()
        current,current_cipher=self.canonical(state,self.root/'canonical')
        wrong,wrong_cipher=self.canonical(state,self.root/'wrong-canonical',key=os.urandom(32))
        future=PdcaState.create(self.root/'future.sqlite',mode='production')
        try:
            future.retain_pair(self.root/'pair.json')
            outcome=result(pair);outcome['captured_at']='2026-11-06T13:00:00+09:00'
            future.score(pair['pair_sha256'],outcome,'2026-11-06T13:05:00+09:00')
        finally:future.close()
        future_pointer,future_cipher=self.canonical(self.root/'future.sqlite',self.root/'future-canonical')
        invalid_mode=deepcopy(current);invalid_mode['scope']['mode']='synthetic'
        for name,raw,prior,prior_raw,error in (
            ('incoming-hash',cipher+b'changed',current,current_cipher,None),
            ('current-key',cipher,wrong,wrong_cipher,None),
            ('future-current',cipher,future_pointer,future_cipher,None),
            ('invalid-mode',cipher,invalid_mode,current_cipher,None),
            ('untyped-same-code',cipher,current,current_cipher,ValueError('STATE_REGRESSION_FILES')),
            ('unknown',cipher,current,current_cipher,RuntimeError('private-sentinel'))):
            with self.subTest(name=name):
                output=self.root/name
                code,printed,gha=self.cli_receive_stale(transfer,raw,prior,prior_raw,output,error=error)
                self.assertEqual(code,2)
                self.assertEqual(json.loads(printed)['status'],'OWNER_TRANSFER_REJECTED')
                self.assertNotIn('HOLD_TRANSFER_REBASE_REQUIRED',printed)
                self.assertNotIn('private-sentinel',printed)
                self.assertFalse((output/'status.json').exists())
                self.assertFalse((output/'sealed').exists())
                self.assertFalse((output/'incoming.sqlite').exists())
                self.assertEqual(list(output.iterdir()) if output.exists() else [],[])
                self.assertFalse(gha.exists())

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
        def verify(folder,root,**kw):return self.m.verify_received_checkpoint(folder,root,now=NOW,**kw)
        with patch.dict(os.environ,env),patch('scripts.boat_pdca_transfer.verify_received_checkpoint',side_effect=verify),redirect_stdout(StringIO()):
            argv=[os.path.expandvars(part) for part in shlex.split(command)][3:]
            code=main(argv)
        self.assertEqual(code,0)
        proof=json.loads((self.root/'boat-owner-state-readback/status.json').read_text())
        self.assertTrue(proof['production_schema_readback_verified'])
