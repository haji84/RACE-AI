"""One charged B capture before P0 retention failure; invented AES only."""
from copy import deepcopy
import json
from hashlib import sha256
import unittest

from race_ai import boat_pending_round_recovery as recovery
from race_ai.boat_source_control import build_summary,read_summary
from race_ai.frozen_day_cycle import read_p0
from tests.test_boat_pending_round_recovery import ZeroRoundFailedOwnerTests,encrypted,DAY,NOW,KEY,HEAD
from tests.test_boat_private_original_vault import packed
from tests.test_continuity_checkpoint import sealed
from tests.test_frozen_day_cycle import sample


class BootstrapRecoveryTests(unittest.TestCase):
    def test_cli_failure_reports_public_code_location_without_private_exception_text(self):
        from scripts import boat_recover_failed_owner as cli
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import io
        out=io.StringIO()
        with patch.object(cli,'_packages'),patch.object(cli,'_invocation_context',
            side_effect=RuntimeError('private-owner-payload-sentinel')),redirect_stdout(out):
            code=cli.main(['--history','private-history-path','--expected-head',HEAD,'--output','private-output-path'])
        report=json.loads(out.getvalue())
        self.assertEqual(code,2)
        self.assertEqual(report.get('failure_class'),'RuntimeError')
        self.assertIn('scripts/boat_recover_failed_owner.py:',report.get('failure_at',''))
        self.assertNotIn('sentinel',out.getvalue())
        self.assertNotIn('private-history-path',out.getvalue())

    def setUp(self):
        f=ZeroRoundFailedOwnerTests();f.setUp();self.addCleanup(f.doCleanups)
        self.run=deepcopy(f.run_meta)
        self.doc,_,_=sample()
        self.doc.update(source_requests=1,source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',
            source_sha256='a'*64,captured_at='2030-04-01T01:40:00Z',code_sha=HEAD)
        self.boot=dict(schema='RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1',run_id=99,day_jst=DAY,
            requests_used=1,completed_round=0,prepared_round=None,lifetime_requests_base=88,
            lifetime_requests=89,day_start_lifetime_requests=88,lifetime_completed_rounds_base=7,
            lifetime_completed_rounds=7,source_wait=None,previous_halted_reason=None,control_reason=None)
        self.responses={};self.rebuild()

    def rebuild(self,*,member='bootstrap-source-control.json'):
        def metadata(raw,name,ident,at):
            return dict(id=ident,name=name,expired=False,created_at=at,expires_at='2030-04-08T02:35:00Z',
                digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),
                workflow_run=dict(id=99,repository_id=1416489937,head_repository_id=1416489937,head_sha=HEAD))
        plain=packed({'forecasts.json':json.dumps(self.doc).encode()})
        self.p0,self.p0meta=encrypted(plain,metadata(plain,'boat-p0-existing-99',701,'2030-04-01T01:43:00Z'),'P0')
        inner=packed({member:sealed(self.boot,'source_control_sha256')})
        self.cont,self.contmeta=encrypted(inner,metadata(inner,'race-cycle-continuity-99',702,'2030-04-01T02:31:00Z'),'CONTINUITY')
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(self.cont)) as z:cipher=z.read('private-original.enc')
        summary=build_summary(cipher,run_id=99,head_sha=HEAD,key=KEY)
        self.public=packed({'source-control.json':json.dumps(summary).encode()})
        self.publicmeta=metadata(self.public,'race-source-control-99',703,'2030-04-01T02:31:01Z')
        self.control=read_summary(self.public,self.publicmeta,self.cont,self.contmeta,run_id=99,head_sha=HEAD)
        metas=[self.p0meta,self.contmeta,self.publicmeta]
        self.responses['actions/runs/99']=json.dumps(self.run).encode()
        self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(dict(total_count=3,artifacts=metas)).encode()
        for raw,meta in ((self.p0,self.p0meta),(self.cont,self.contmeta),(self.public,self.publicmeta)):
            self.responses[f'actions/artifacts/{meta["id"]}']=json.dumps(meta).encode()
            self.responses[f'actions/artifacts/{meta["id"]}/zip']=raw
        _,rows=read_p0(self.p0,self.p0meta,expected_day=DAY)
        # Use the actual recovery reader's output, including its verified
        # learning sidecar; raw read_p0 rows alone missed the live mismatch.
        from race_ai.observed_weight_learning import attach_snapshots
        rows=attach_snapshots(self.doc,rows)
        self.replay=dict(complete=True,day_jst=DAY,rows=rows,receipts=[self.p0meta])

    def verify(self):
        return recovery.verify_no_pending_failed_owner(lambda p:self.responses[p],self.run,self.control,
            now=NOW,replayed_state=self.replay)

    def test_captured_bootstrap_is_authenticated_retained_and_never_resets_one_get(self):
        before=deepcopy(self.control)
        checked=self.verify()
        self.assertEqual({k:v for k,v in checked['control'].items() if k!='recovery'},before)
        self.assertEqual(checked['control']['previous_session_requests'],1)
        self.assertEqual(checked['original_artifact_ids'],[701,702,703])
        self.assertEqual([r['raw_zip'] for r in checked['originals']],[self.p0,self.cont,self.public])
        self.assertEqual(checked['control']['recovery']['source_attempts'],1)
        self.assertEqual((checked['official_source_requests'],checked['new_forecasts']),(0,0))

    def test_missing_replay_mismatched_first_original_and_unaccounted_gets_hold(self):
        for value in (None,dict(self.replay,complete=False),dict(self.replay,rows=[]),dict(self.replay,receipts=[])):
            with self.subTest(replay=value is None):
                self.replay=value
                with self.assertRaises((ValueError,TypeError)):self.verify()
                self.rebuild()
        self.control['previous_session_requests']=2
        with self.assertRaises(ValueError):self.verify()

    def test_changed_learning_sidecar_is_rejected_without_rewriting_replay(self):
        self.replay['rows'][0]['learning_snapshot_sha256']='f'*64
        original=deepcopy(self.replay)
        with self.assertRaisesRegex(ValueError,'ROUND_RECOVERY_BOOTSTRAP_FIRST_RECEIPT_CONFLICT'):
            self.verify()
        self.assertEqual(self.replay,original)

    def test_wrong_key_corrupt_zip_changed_source_and_source_wait_fail_closed(self):
        from unittest.mock import patch
        import base64,os
        with patch.dict(os.environ,RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(KEY))).decode()):
            with self.assertRaises(ValueError):self.verify()
        self.responses['actions/artifacts/701/zip']=self.p0+b'changed'
        with self.assertRaises(ValueError):self.verify()
        self.rebuild();self.doc['source_requests']=2;self.rebuild()
        with self.assertRaises(ValueError):self.verify()
        self.doc['source_requests']=1;self.doc['source_url']='https://example.invalid/B';self.rebuild()
        with self.assertRaises(ValueError):self.verify()
        self.doc['source_url']='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh';self.rebuild()
        self.control['source_wait']=dict(state='AUTHORIZATION_WAIT')
        with self.assertRaises(ValueError):self.verify()

    def test_history_proof_requires_actual_vault_readback_and_binds_original_receipts(self):
        from scripts.boat_recover_failed_owner import recover_history
        params=dict(runs=[self.run],get=lambda p:self.responses[p],load_control=lambda _:deepcopy(self.control),
            replay_day=lambda:self.replay,now=NOW,expected_head=HEAD)
        with self.assertRaises(ValueError):recover_history(**params,retain=lambda *_:dict(independent_git_readback_verified=False))
        proof=recover_history(**params,retain=lambda *_:dict(independent_git_readback_verified=True,source_commit='d'*40))
        self.assertIsNotNone(recovery.verify_dispatch_proof(proof,[self.run],self.control,HEAD,NOW))
        for changed in (dict(vault_commit=None),dict(original_artifact_ids=[])):
            bad=deepcopy(proof);bad['repairs'][0].update(changed)
            self.assertIsNone(recovery.verify_dispatch_proof(bad,[self.run],self.control,HEAD,NOW))
        bad=deepcopy(proof);bad['repairs'][0]['control']['recovery']['continuity_receipt']['digest']='sha256:'+'f'*64
        self.assertIsNone(recovery.verify_dispatch_proof(bad,[self.run],self.control,HEAD,NOW))

    def test_real_vault_roundtrip_preserves_bootstrap_p0_and_both_receipts(self):
        from scripts.boat_recover_failed_owner import retain_verified_pair
        from tests.test_boat_private_original_vault import VaultTests
        from race_ai.boat_private_original_vault import restore_original
        f=VaultTests();f.setUp();self.addCleanup(f.doCleanups)
        checked=self.verify()
        saved=retain_verified_pair(checked,self.run,f.writer.repo,now=NOW,
            transport=f.writer,readback_transport=f.reader)
        self.assertTrue(saved['independent_git_readback_verified'])
        for locator,original in zip(saved['locators'],checked['originals']):
            restored=restore_original(locator,f.reader.repo,key=KEY,transport=f.reader)
            self.assertEqual(restored['raw_zip'],original['raw_zip'])
            self.assertEqual(restored['metadata_raw'],original['metadata_raw'])

    def _release_origin_fixture(self, origin='bb49215034b779ea1493b35dd91e5c3ebfc04032'):
        """Genuine public-key capsules, never a mocked authentication result."""
        import base64,os,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tests.test_boat_private_original_vault_private_pairs import MemoryRemote,MemoryVault
        environment=patch.dict(os.environ,
            {'RACE_AI_STATE_KEY':base64.b64encode(KEY).decode()},clear=True)
        environment.start();self.addCleanup(environment.stop)
        network=patch('urllib.request.OpenerDirector.open',
                      side_effect=AssertionError('provider/GitHub transport forbidden in release fixture'))
        network.start();self.addCleanup(network.stop)
        processes=patch('subprocess.Popen',
                        side_effect=AssertionError('processes forbidden in memory-vault release fixture'))
        processes.start();self.addCleanup(processes.stop)
        self.run['head_sha']=origin;self.doc['code_sha']=origin
        with patch(__name__+'.HEAD',origin), \
             patch('tests.test_boat_pending_round_recovery.HEAD',origin):
            self.rebuild()
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.release_root=Path(temporary.name)
        repo=self.release_root/'repo';repo.mkdir(mode=0o700)
        reader=self.release_root/'reader';reader.mkdir(mode=0o700)
        self.release_remote=MemoryRemote()
        self.release_writer=MemoryVault(self.release_remote,repo)
        self.release_reader=MemoryVault(self.release_remote,reader)
        self.release_reads=[];self.release_retained=[];self.release_checked=[]

    def _release_get(self,route):
        self.release_reads.append(route)
        return self.responses[route]

    def _release_proof(self,expected_head):
        from scripts.boat_recover_failed_owner import recover_history,retain_verified_pair
        def retain(checked,run):
            self.release_checked.append(checked)
            saved=retain_verified_pair(checked,run,self.release_writer.repo,now=NOW,
                transport=self.release_writer,readback_transport=self.release_reader)
            self.release_retained.append(saved)
            return saved
        return recover_history([self.run],get=self._release_get,
            load_control=lambda run:recovery.read_final_control(self._release_get,run),
            replay_day=lambda:deepcopy(self.replay),retain=retain,
            now=NOW,expected_head=expected_head)

    def test_next_release_reads_bb_sealed_p0_and_control_with_real_independent_vault_readback(self):
        from race_ai import boat_private_original_vault as V
        bb='bb49215034b779ea1493b35dd91e5c3ebfc04032';next_head='e'*40
        self._release_origin_fixture(bb)
        before=deepcopy((self.run,self.doc,self.control,self.responses,self.replay))
        try:proof=self._release_proof(next_head)
        except ValueError as error:
            self.fail('Exact BB sealed first-P0/control readback under new release was refused: '+str(error))
        self.assertEqual(proof['head_sha'],next_head)
        repair=proof['repairs'][0]
        self.assertEqual(repair['original_head_sha'],bb)
        self.assertEqual(repair['original_artifact_ids'],[701,702,703])
        self.assertEqual(proof['latest_control']['previous_session_requests'],1)
        self.assertEqual(proof['latest_control']['lifetime_requests'],89)
        self.assertEqual(proof['latest_control']['day_start_lifetime_requests'],88)
        self.assertEqual(proof['latest_control']['lifetime_completed_rounds'],7)
        self.assertEqual((proof['latest_control']['completed_round'],
                          proof['latest_control']['prepared_round']),(0,None))
        self.assertEqual({k:v for k,v in proof['latest_control'].items() if k!='recovery'},self.control)
        self.assertEqual(len(self.release_retained),1)
        saved=self.release_retained[0]
        self.assertTrue(saved['independent_git_readback_verified'])
        self.assertEqual(repair['vault_commit'],saved['source_commit'])
        self.assertEqual([item['raw_zip'] for item in self.release_checked[0]['originals']],
                         [self.p0,self.cont,self.public])
        self.assertEqual((self.release_checked[0]['official_source_requests'],
                          self.release_checked[0]['new_forecasts']),(0,0))
        self.assertEqual(len(saved['locators']),3)
        for locator in saved['locators']:
            original=V.restore_original(locator,self.release_reader.repo,key=KEY,transport=self.release_reader)
            ident=locator['artifact_id']
            self.assertEqual(original['raw_zip'],self.responses[f'actions/artifacts/{ident}/zip'])
            self.assertEqual(original['metadata_raw'],self.responses[f'actions/artifacts/{ident}'])
            self.assertEqual(original['metadata']['workflow_run']['head_sha'],bb)
        self.assertIsNotNone(recovery.verify_dispatch_proof(proof,[self.run],self.control,next_head,NOW))
        for defect in ('old_proof_head','foreign_original_head','missing_original_head','counter_reset'):
            bad=deepcopy(proof)
            if defect=='old_proof_head':bad['head_sha']=bb
            elif defect=='foreign_original_head':bad['repairs'][0]['original_head_sha']='f'*40
            elif defect=='missing_original_head':bad['repairs'][0].pop('original_head_sha')
            else:bad['latest_control']['lifetime_requests']=0
            with self.subTest(defect=defect):
                self.assertIsNone(recovery.verify_dispatch_proof(bad,[self.run],self.control,next_head,NOW))
        self.assertEqual((self.run,self.doc,self.control,self.responses,self.replay),before)

    def test_bb_completed_owner_callback_is_only_recovery_provenance_for_the_new_release(self):
        from copy import deepcopy
        from scripts import boat_recover_failed_owner as cli
        from tests.test_boat_recovery_invocation import callback,MAIN,WORKFLOW_REF
        bb='bb49215034b779ea1493b35dd91e5c3ebfc04032';next_head='e'*40
        self._release_origin_fixture(bb)
        event=callback();event['workflow_run']['head_sha']=bb
        before=deepcopy(event)
        try:
            accepted=cli.trusted_main_invocation('workflow_run',event,workflow_ref=WORKFLOW_REF,
                ref='refs/heads/main',sha=MAIN,expected_source_head=next_head)
        except ValueError as error:
            self.fail('Completed exact BB owner callback cannot reach new-release recovery: '+str(error))
        self.assertTrue(accepted)
        self.assertEqual(event,before)
        for change in (dict(head_sha='f'*40),dict(run_attempt=2),dict(status='in_progress'),
                       dict(head_repository=dict(id=1,full_name='haji84/RACE-AI'))):
            bad=deepcopy(event);bad['workflow_run'].update(change)
            with self.subTest(change=tuple(change)),self.assertRaises(ValueError):
                cli.trusted_main_invocation('workflow_run',bad,workflow_ref=WORKFLOW_REF,
                    ref='refs/heads/main',sha=MAIN,expected_source_head=next_head)

    def test_bb_original_readback_does_not_authorize_old_bb_checkout_to_emit_new_release_proof(self):
        import os,io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from scripts import boat_recover_failed_owner as cli
        from tests.test_boat_recovery_invocation import MAIN,REPO,WORKFLOW_REF
        bb='bb49215034b779ea1493b35dd91e5c3ebfc04032';next_head='e'*40
        self._release_origin_fixture(bb)
        event=self.release_root/'event.json'
        # A real permitted schedule isolates checkout authority from whether
        # the earlier callback origin has already entered the readback list.
        event.write_text(json.dumps(dict(repository=REPO,schedule='30 20 * * *')))
        env=dict(RACE_AI_STATE_KEY=os.environ['RACE_AI_STATE_KEY'],GITHUB_EVENT_NAME='schedule',
            GITHUB_EVENT_PATH=str(event),GITHUB_WORKFLOW_REF=WORKFLOW_REF,
            GITHUB_REF='refs/heads/main',GITHUB_SHA=MAIN)
        proof_path=self.release_root/'proof.json';out=io.StringIO()
        with patch.dict(os.environ,env,clear=True),patch.object(cli,'_packages'), \
             patch('scripts.boat_private_original_vault._environment',return_value=self.release_writer.repo), \
             patch.object(cli.subprocess,'check_output',return_value=bb.encode()), \
             patch('scripts.boat_private_original_vault._private_path') as output, \
             patch('scripts.github_existing_cycle.gh',
                   side_effect=AssertionError('old checkout must not read remote originals')) as remote, \
             redirect_stdout(out):
            code=cli.main(['--history',str(self.release_root/'history.json'),
                           '--expected-head',next_head,'--output',str(proof_path)])
        report=json.loads(out.getvalue())
        self.assertEqual(code,2)
        self.assertEqual(report['reason'],'ROUND_RECOVERY_CHECKOUT_RELEASE_CHANGED')
        self.assertFalse(report['successor_dispatch_allowed'])
        self.assertFalse(proof_path.exists())
        output.assert_not_called();remote.assert_not_called()
        self.assertEqual(self.release_retained,[])

    def test_unreviewed_foreign_sealed_original_origin_is_refused_before_vault_retention(self):
        self._release_origin_fixture('f'*40)
        before=deepcopy((self.run,self.doc,self.control,self.responses,self.replay))
        head=self.release_remote.current;objects=deepcopy(self.release_remote.objects)
        with self.assertRaisesRegex(ValueError,'ROUND_RECOVERY_RUN_CHANGED'):
            self._release_proof('e'*40)
        self.assertEqual(self.release_retained,[])
        self.assertEqual(self.release_checked,[])
        self.assertFalse(any(route.endswith('/zip') for route in self.release_reads))
        self.assertEqual((self.release_remote.current,self.release_remote.objects),(head,objects))
        self.assertEqual((self.run,self.doc,self.control,self.responses,self.replay),before)

    def test_bb_readback_still_requires_exact_first_p0_aead_and_source_bound_capsule(self):
        import io,zipfile
        from race_ai import boat_private_original_archive as native
        bb='bb49215034b779ea1493b35dd91e5c3ebfc04032'
        self._release_origin_fixture(bb)
        with zipfile.ZipFile(io.BytesIO(self.p0)) as archive:
            cipher=archive.read(native.CIPHER_MEMBER)
        self.assertTrue(cipher.startswith(native.MAGIC))
        bad_tag=cipher[:-1]+bytes([cipher[-1]^1])
        # Preserve envelope framing and the outer receipt digest, so the
        # negative case really reaches AEAD authentication, not ZIP damage.
        with self.assertRaisesRegex(ValueError,'PRIVATE_ORIGINAL_AUTHENTICATION_FAILED'):
            native._open_envelope(bad_tag,key=KEY)
        foreign_doc=deepcopy(self.doc);foreign_doc['code_sha']='f'*40
        foreign_cipher=native.seal_original_zip(packed({'forecasts.json':json.dumps(foreign_doc).encode()}),
            run_id=99,head_sha='f'*40,kind='P0',key=KEY)
        _,foreign_header=native._open_envelope(foreign_cipher,key=KEY)
        self.assertEqual(foreign_header['head_sha'],'f'*40)
        baseline=deepcopy(self.responses)
        for case,raw in (('tampered_aead_tag',packed({native.CIPHER_MEMBER:bad_tag})),
                         ('other_source_cipher',packed({native.CIPHER_MEMBER:foreign_cipher}))):
            with self.subTest(case=case):
                self.responses=deepcopy(baseline)
                metadata=json.loads(self.responses['actions/artifacts/701'])
                metadata.update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
                self.responses['actions/artifacts/701']=json.dumps(metadata).encode()
                self.responses['actions/artifacts/701/zip']=raw
                listing=json.loads(self.responses['actions/runs/99/artifacts?per_page=100'])
                listing['artifacts']=[metadata if item['id']==701 else item for item in listing['artifacts']]
                self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(listing).encode()
                before=deepcopy((self.run,self.doc,self.control,self.responses,self.replay))
                self.release_reads.clear()
                with self.assertRaises(ValueError):self._release_proof('e'*40)
                self.assertIn('actions/artifacts/701/zip',self.release_reads,
                    'new release must reach the real BB original before refusing its invalid crypto/source')
                self.assertEqual(self.release_retained,[])
                self.assertEqual(self.release_checked,[])
                self.assertEqual((self.run,self.doc,self.control,self.responses,self.replay),before)
        self.responses=baseline

    def test_public_counter_disagreement_and_wrong_capture_or_code_never_authorize(self):
        self.control['lifetime_requests']+=1
        with self.assertRaises(ValueError):self.verify()
        self.rebuild()
        for field,value in (('captured_at','2030-04-01T02:33:00Z'),('code_sha','f'*40)):
            original=self.doc[field];self.doc[field]=value;self.rebuild()
            with self.subTest(field=field),self.assertRaises(ValueError):self.verify()
            self.doc[field]=original;self.rebuild()
        self.boot['lifetime_requests_base']=87;self.boot['lifetime_requests']=88;self.rebuild()
        with self.assertRaises(ValueError):self.verify()


    def test_next_release_reads_a74_sealed_p0_and_control_with_real_independent_vault_readback(self):
        from race_ai import boat_private_original_vault as V
        a74='a74f1e940e7fc0852e63938f8138bdb58bd93163';next_head='e'*40
        self._release_origin_fixture(a74)
        before=deepcopy((self.run,self.doc,self.control,self.responses,self.replay))
        try:proof=self._release_proof(next_head)
        except ValueError as error:
            self.fail('Exact A74 sealed first-P0/control readback under new release was refused: '+str(error))
        self.assertEqual(proof['head_sha'],next_head)
        repair=proof['repairs'][0]
        self.assertEqual(repair['original_head_sha'],a74)
        self.assertEqual(repair['original_artifact_ids'],[701,702,703])
        self.assertEqual(proof['latest_control']['previous_session_requests'],1)
        self.assertEqual(proof['latest_control']['lifetime_requests'],89)
        self.assertEqual(proof['latest_control']['day_start_lifetime_requests'],88)
        self.assertEqual(proof['latest_control']['lifetime_completed_rounds'],7)
        self.assertEqual((proof['latest_control']['completed_round'],
                          proof['latest_control']['prepared_round']),(0,None))
        self.assertEqual({k:v for k,v in proof['latest_control'].items() if k!='recovery'},self.control)
        self.assertEqual(len(self.release_retained),1)
        saved=self.release_retained[0]
        self.assertTrue(saved['independent_git_readback_verified'])
        self.assertEqual(repair['vault_commit'],saved['source_commit'])
        self.assertEqual([item['raw_zip'] for item in self.release_checked[0]['originals']],
                         [self.p0,self.cont,self.public])
        self.assertEqual((self.release_checked[0]['official_source_requests'],
                          self.release_checked[0]['new_forecasts']),(0,0))
        self.assertEqual(len(saved['locators']),3)
        for locator in saved['locators']:
            original=V.restore_original(locator,self.release_reader.repo,key=KEY,transport=self.release_reader)
            ident=locator['artifact_id']
            self.assertEqual(original['raw_zip'],self.responses[f'actions/artifacts/{ident}/zip'])
            self.assertEqual(original['metadata_raw'],self.responses[f'actions/artifacts/{ident}'])
            self.assertEqual(original['metadata']['workflow_run']['head_sha'],a74)
        self.assertIsNotNone(recovery.verify_dispatch_proof(proof,[self.run],self.control,next_head,NOW))
        for defect in ('old_proof_head','foreign_original_head','missing_original_head','counter_reset'):
            bad=deepcopy(proof)
            if defect=='old_proof_head':bad['head_sha']=a74
            elif defect=='foreign_original_head':bad['repairs'][0]['original_head_sha']='f'*40
            elif defect=='missing_original_head':bad['repairs'][0].pop('original_head_sha')
            else:bad['latest_control']['lifetime_requests']=0
            with self.subTest(defect=defect):
                self.assertIsNone(recovery.verify_dispatch_proof(bad,[self.run],self.control,next_head,NOW))
        self.assertEqual((self.run,self.doc,self.control,self.responses,self.replay),before)

    def test_a74_completed_owner_callback_is_only_recovery_provenance_for_the_new_release(self):
        from copy import deepcopy
        from scripts import boat_recover_failed_owner as cli
        from tests.test_boat_recovery_invocation import callback,MAIN,WORKFLOW_REF
        a74='a74f1e940e7fc0852e63938f8138bdb58bd93163';next_head='e'*40
        self._release_origin_fixture(a74)
        event=callback();event['workflow_run']['head_sha']=a74
        before=deepcopy(event)
        try:
            accepted=cli.trusted_main_invocation('workflow_run',event,workflow_ref=WORKFLOW_REF,
                ref='refs/heads/main',sha=MAIN,expected_source_head=next_head)
        except ValueError as error:
            self.fail('Completed exact A74 owner callback cannot reach new-release recovery: '+str(error))
        self.assertTrue(accepted)
        self.assertEqual(event,before)
        for change in (dict(head_sha='f'*40),dict(run_attempt=2),dict(status='in_progress'),
                       dict(head_repository=dict(id=1,full_name='haji84/RACE-AI'))):
            bad=deepcopy(event);bad['workflow_run'].update(change)
            with self.subTest(change=tuple(change)),self.assertRaises(ValueError):
                cli.trusted_main_invocation('workflow_run',bad,workflow_ref=WORKFLOW_REF,
                    ref='refs/heads/main',sha=MAIN,expected_source_head=next_head)

    def test_a74_original_readback_does_not_authorize_old_a74_checkout_to_emit_new_release_proof(self):
        import os,io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from scripts import boat_recover_failed_owner as cli
        from tests.test_boat_recovery_invocation import MAIN,REPO,WORKFLOW_REF
        a74='a74f1e940e7fc0852e63938f8138bdb58bd93163';next_head='e'*40
        self._release_origin_fixture(a74)
        event=self.release_root/'event.json'
        # A real permitted schedule isolates checkout authority from whether
        # the earlier callback origin has already entered the readback list.
        event.write_text(json.dumps(dict(repository=REPO,schedule='30 20 * * *')))
        env=dict(RACE_AI_STATE_KEY=os.environ['RACE_AI_STATE_KEY'],GITHUB_EVENT_NAME='schedule',
            GITHUB_EVENT_PATH=str(event),GITHUB_WORKFLOW_REF=WORKFLOW_REF,
            GITHUB_REF='refs/heads/main',GITHUB_SHA=MAIN)
        proof_path=self.release_root/'proof.json';out=io.StringIO()
        with patch.dict(os.environ,env,clear=True),patch.object(cli,'_packages'), \
             patch('scripts.boat_private_original_vault._environment',return_value=self.release_writer.repo), \
             patch.object(cli.subprocess,'check_output',return_value=a74.encode()), \
             patch('scripts.boat_private_original_vault._private_path') as output, \
             patch('scripts.github_existing_cycle.gh',
                   side_effect=AssertionError('old checkout must not read remote originals')) as remote, \
             redirect_stdout(out):
            code=cli.main(['--history',str(self.release_root/'history.json'),
                           '--expected-head',next_head,'--output',str(proof_path)])
        report=json.loads(out.getvalue())
        self.assertEqual(code,2)
        self.assertEqual(report['reason'],'ROUND_RECOVERY_CHECKOUT_RELEASE_CHANGED')
        self.assertFalse(report['successor_dispatch_allowed'])
        self.assertFalse(proof_path.exists())
        output.assert_not_called();remote.assert_not_called()
        self.assertEqual(self.release_retained,[])

    def test_a74_readback_still_requires_exact_first_p0_aead_and_source_bound_capsule(self):
        import io,zipfile
        from race_ai import boat_private_original_archive as native
        a74='a74f1e940e7fc0852e63938f8138bdb58bd93163'
        self._release_origin_fixture(a74)
        with zipfile.ZipFile(io.BytesIO(self.p0)) as archive:
            cipher=archive.read(native.CIPHER_MEMBER)
        self.assertTrue(cipher.startswith(native.MAGIC))
        bad_tag=cipher[:-1]+bytes([cipher[-1]^1])
        # Preserve envelope framing and the outer receipt digest, so the
        # negative case really reaches AEAD authentication, not ZIP damage.
        with self.assertRaisesRegex(ValueError,'PRIVATE_ORIGINAL_AUTHENTICATION_FAILED'):
            native._open_envelope(bad_tag,key=KEY)
        foreign_doc=deepcopy(self.doc);foreign_doc['code_sha']='f'*40
        foreign_cipher=native.seal_original_zip(packed({'forecasts.json':json.dumps(foreign_doc).encode()}),
            run_id=99,head_sha='f'*40,kind='P0',key=KEY)
        _,foreign_header=native._open_envelope(foreign_cipher,key=KEY)
        self.assertEqual(foreign_header['head_sha'],'f'*40)
        baseline=deepcopy(self.responses)
        for case,raw in (('tampered_aead_tag',packed({native.CIPHER_MEMBER:bad_tag})),
                         ('other_source_cipher',packed({native.CIPHER_MEMBER:foreign_cipher}))):
            with self.subTest(case=case):
                self.responses=deepcopy(baseline)
                metadata=json.loads(self.responses['actions/artifacts/701'])
                metadata.update(digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw))
                self.responses['actions/artifacts/701']=json.dumps(metadata).encode()
                self.responses['actions/artifacts/701/zip']=raw
                listing=json.loads(self.responses['actions/runs/99/artifacts?per_page=100'])
                listing['artifacts']=[metadata if item['id']==701 else item for item in listing['artifacts']]
                self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(listing).encode()
                before=deepcopy((self.run,self.doc,self.control,self.responses,self.replay))
                self.release_reads.clear()
                with self.assertRaises(ValueError):self._release_proof('e'*40)
                self.assertIn('actions/artifacts/701/zip',self.release_reads,
                    'new release must reach the real A74 original before refusing its invalid crypto/source')
                self.assertEqual(self.release_retained,[])
                self.assertEqual(self.release_checked,[])
                self.assertEqual((self.run,self.doc,self.control,self.responses,self.replay),before)
        self.responses=baseline

    def test_a74_same_day_failed_history_retains_its_original_source_identity(self):
        from scripts import boat_recover_failed_owner as cli
        a74='a74f1e940e7fc0852e63938f8138bdb58bd93163';next_head='e'*40
        self._release_origin_fixture(a74)
        history=dict(total_count=1,workflow_runs=[deepcopy(self.run)])
        before=deepcopy(history)
        try:
            selected=cli.today_owners(history,now=NOW,expected_head=next_head)
        except ValueError as error:
            self.fail('Exact A74 failed-owner history cannot reach new-release recovery: '+str(error))
        self.assertEqual(selected,[self.run])
        self.assertEqual(selected[0]['head_sha'],a74)
        self.assertEqual(history,before)
        for change in (dict(head_sha='f'*40),dict(status='in_progress'),
                       dict(conclusion='success'),dict(head_branch='main')):
            bad=deepcopy(history);bad['workflow_runs'][0].update(change)
            with self.subTest(change=tuple(change)),self.assertRaises(ValueError):
                cli.today_owners(bad,now=NOW,expected_head=next_head)
        self.assertEqual(history,before)
        self.assertEqual(self.release_reads,[])
        self.assertEqual(self.release_retained,[])

    def test_reviewed_a74_origin_keeps_every_prior_origin_and_refuses_unreviewed_sources(self):
        from scripts.boat_failed_recovery_contract import reviewed_recovery_origin
        next_head='e'*40
        for origin in (
            '84128e0ec8bd9fe3da64ad49f74b8511b07e72be',
            'b491fb21ce58ba085dd8f54bb7326442b840d8f4',
            'c123b8538006b3189181195bbc91d8f28d216ba5',
            'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
            '86b029ae5bddd5d4956497d8b32b2c92b8eec521',
            'f55351dce855177a51330f72c37d6238ba2c9e3e',
            'bb49215034b779ea1493b35dd91e5c3ebfc04032',
            'a74f1e940e7fc0852e63938f8138bdb58bd93163'):
            with self.subTest(origin=origin):
                self.assertTrue(reviewed_recovery_origin(origin,next_head))
        self.assertTrue(reviewed_recovery_origin(next_head,next_head))
        for origin in (None,True,1,'f'*40,'a74f1e94',
                       'refs/heads/production/boat-p0-p1-20261111'):
            with self.subTest(unreviewed=origin):
                self.assertFalse(reviewed_recovery_origin(origin,next_head))
        for malformed in (None,True,1,'e'*39,'E'*40,'e'*41):
            with self.subTest(expected_head=malformed):
                self.assertFalse(reviewed_recovery_origin(
                    'a74f1e940e7fc0852e63938f8138bdb58bd93163',malformed))

    def test_fbc_outside_the_exact_saved_bootstrap_instance_never_admits_a_release(self):
        fbc='fbc743be548bfd123e46cdbfe290515a59e5e0d3';next_head='e'*40
        self._release_origin_fixture(fbc)
        before=deepcopy(self.control)
        with self.assertRaisesRegex(ValueError,'RUN_CHANGED'):self._release_proof(next_head)
        self.assertEqual(self.control,before)
        self.assertEqual(self.release_retained,[])

    def _bootstrap_models_fixture(self):
        import os
        from pathlib import Path
        from unittest.mock import patch
        from race_ai import boat_all_model_cycle as engine,boat_all_model_store as store,saved_view_feed as feed
        from race_ai.boat_saved_view_intake import project_native_state
        from scripts import boat_bootstrap_recovery_adapter as contract
        from tests.test_boat_all_model_cycle import AllModelCycleTests
        from tests.test_boat_all_model_recovery import zipped
        from tests.test_saved_view_feed import ProjectionTests
        from tests.test_boat_private_original_vault_private_pairs import MemoryRemote,MemoryVault
        from race_ai.actions_contract import digest
        fixture=AllModelCycleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        if not hasattr(AllModelCycleTests,'fitted'):AllModelCycleTests.setUpClass()
        files=fixture.runtime(fitted=True)
        old=ProjectionTests();old.setUp();self.addCleanup(old.doCleanups)
        base=deepcopy(old.view)
        fbc='fbc743be548bfd123e46cdbfe290515a59e5e0d3'
        self._release_origin_fixture(fbc)
        private=self.release_root/'runtime-temp';private.mkdir(mode=0o700)
        context=patch.dict(os.environ,GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937',GITHUB_RUN_ID='100',GITHUB_SHA='e'*40,
            RUNNER_TEMP=str(private),GH_TOKEN='synthetic-github-token-only')
        context.start();self.addCleanup(context.stop)
        from race_ai import boat_all_model_recovery as model_recovery
        observed_clock=patch.object(model_recovery,'_now',return_value=NOW)
        observed_clock.start();self.addCleanup(observed_clock.stop)
        self.assertTrue(hasattr(contract,'BOOTSTRAP_MODEL_ORIGINALS'), 'known saved bootstrap model scope is absent')
        scope=patch.object(contract,'BOOTSTRAP_MODEL_ORIGINALS',{99:(fbc,DAY,708)})
        scope.start();self.addCleanup(scope.stop)
        files.update(source_code_commit=fbc,run_id='99')
        receipt=dict(repository_id='1416489937',repository='haji84/RACE-AI',run_id='99',head_sha=fbc,
            artifact_id=701,created_at=self.p0meta['created_at'],payload_sha256=digest(self.doc),independently_verified=True)
        self.models_payload=engine.forecast_saved_p0(self.doc,receipt,files,
            now=NOW.replace(hour=1,minute=44,second=0,microsecond=0))
        self.models_payload['source_code_commit']=fbc
        raw=zipped(store.seal_forecasts(self.models_payload,run_id='99',round_no=0,key=KEY))
        self.models_meta=dict(id=708,name='boat-all-model-forecasts-99-r0',expired=False,
            digest='sha256:'+sha256(raw).hexdigest(),size_in_bytes=len(raw),created_at='2030-04-01T01:44:01Z',
            expires_at='2030-04-08T02:35:00Z',workflow_run=deepcopy(self.p0meta['workflow_run']))
        self.responses['actions/artifacts/708']=json.dumps(self.models_meta).encode()
        self.responses['actions/artifacts/708/zip']=raw
        self._set_model_listing()
        self.replay.update(schema='RACE_AI_RECOVERED_FIRST_RECEIPTS_V1',observations=[])
        self.replay['state_sha256']=digest(self.replay)
        base['forecast_base_sha256']=feed.originals_sha(base)
        self.feed_bootstrap=dict(key=b'x'*32,view_id='b'*64,cipher_sha256='c'*64,
            forecast_sha256=feed.forecast_anchor(base),pages_commit='d'*40)
        class Feed(MemoryVault):
            def __init__(self,remote,repo):
                super().__init__(remote,repo);self.ref=feed.REF;self._saved_history_context=None
            def validate_tree(self,commit):pass
            def exists(self,commit,path):return commit in self.objects and path in self.objects[commit]
            def commit_snapshot(self,files,parent):
                value=sha256(parent.encode()+b''.join(p.encode()+v for p,v in sorted(files.items()))).hexdigest()[:40]
                self.objects[value]=dict(files);return value
            def push(self,commit,parent):
                if self.remote.current!=parent:raise ValueError('STATE_REF_CONCURRENT_UPDATE')
                self.remote.objects.update(deepcopy(self.objects));self.remote.current=commit
        remote=MemoryRemote();self.feed_writer=Feed(remote,self.release_writer.repo)
        self.feed_reader=Feed(remote,self.release_reader.repo)
        self.feed_writer.fetch(remote.current)
        raw=feed.encrypt_view(base,self.feed_bootstrap['key'],view_id='b'*64,source_sha='c'*64,
            generation=1,previous='c'*64)
        header=json.loads(raw)['header'];ident=sha256(raw).hexdigest()
        first=self.feed_writer.commit_snapshot({'views/'+ident+'.json':raw,
            'latest.json':json.dumps(dict(header=header,cipher_sha256=ident)).encode()},remote.current)
        self.feed_writer.push(first,remote.current);self.feed_nonhistory=first
        published=feed.publish_view(self.feed_writer,self.feed_bootstrap,base,parent=first,
            previous=ident,generation=1,history=True)
        self.feed_initial=published['commit']
        self.bootstrap_model_options=dict(now=NOW,expected_head='e'*40,get=self._release_get,
            bootstrap=self.feed_bootstrap,transport=self.feed_writer,readback_transport=self.feed_reader,
            protection_transport=self.release_writer,protection_readback_transport=self.release_reader)

    def _set_model_listing(self):
        self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(dict(total_count=4,
            artifacts=[self.p0meta,self.contmeta,self.publicmeta,self.models_meta])).encode()

    def _restore_bootstrap_models(self):
        from scripts import boat_recover_failed_owner as cli
        return cli.restore_failed_bootstrap_models(self.run,self.replay,self.release_writer.repo,
            **self.bootstrap_model_options)

    def _current_bootstrap_proof(self,runs=None,clock=None):
        from scripts import boat_recover_failed_owner as cli
        def retain(checked,run):
            return cli.retain_verified_pair(checked,run,self.release_writer.repo,now=NOW,
                transport=self.release_writer,readback_transport=self.release_reader)
        options={} if clock is None else {'clock':clock}
        return cli.recover_history(runs or [self.run],get=self._release_get,
            load_control=lambda run:recovery.read_final_control(self._release_get,run),
            replay_day=lambda:deepcopy(self.replay),retain=retain,now=NOW,expected_head='e'*40,
            restore_bootstrap_models=lambda *_:cli.restore_failed_bootstrap_models(self.run,self.replay,
                self.release_writer.repo,**dict(self.bootstrap_model_options,**options)),**options)

    def _successful_successor(self,ident=100,total=93,used=4,day_base=88,rounds=8,offset=0):
        from race_ai.boat_private_original_archive import seal_original_zip
        from tests.test_continuity_checkpoint import session
        created=NOW.replace(minute=33,second=offset,microsecond=0)
        saved=NOW.replace(minute=34,second=offset,microsecond=0)
        successor=dict(self.run,id=ident,head_sha='e'*40,conclusion='success',
            created_at=created.isoformat(),updated_at=saved.replace(second=offset+2).isoformat())
        body=session(run_id=ident,requests_used=used,completed_round=1,prepared_round=None,
            lifetime_requests_base=total-used,lifetime_requests=total,day_start_lifetime_requests=day_base,
            lifetime_completed_rounds_base=rounds-1,lifetime_completed_rounds=rounds,
            halted_reason='WORKER_HANDOFF',source_wait=None)
        cipher=seal_original_zip(packed({'repeat-session.json':body}),run_id=ident,head_sha='e'*40,kind='CONTINUITY',key=KEY)
        continuity=packed({'private-original.enc':cipher})
        summary=packed({'source-control.json':json.dumps(build_summary(cipher,run_id=ident,head_sha='e'*40,key=KEY)).encode()})
        metas=[]
        for number,name,raw,second in ((802+(ident-100)*10,'race-cycle-continuity',continuity,offset),
                                     (803+(ident-100)*10,'race-source-control',summary,offset+1)):
            meta=dict(self.contmeta,id=number,name=f'{name}-{ident}',size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
                created_at=saved.replace(second=second).isoformat(),workflow_run=dict(self.contmeta['workflow_run'],id=ident,head_sha='e'*40))
            metas.append(meta);self.responses[f'actions/artifacts/{number}']=json.dumps(meta).encode()
            self.responses[f'actions/artifacts/{number}/zip']=raw
        self.responses[f'actions/runs/{ident}']=json.dumps(successor).encode()
        self.responses[f'actions/runs/{ident}/artifacts?per_page=100']=json.dumps(dict(total_count=2,artifacts=metas)).encode()
        return successor

    def test_known_saved_bootstrap_cannot_emit_proof_without_its_model_recovery_hook(self):
        from scripts import boat_bootstrap_recovery_adapter as contract
        from unittest.mock import patch
        self.assertTrue(hasattr(contract,'BOOTSTRAP_MODEL_ORIGINALS'),'required r0 recovery is absent')
        fbc='fbc743be548bfd123e46cdbfe290515a59e5e0d3';self._release_origin_fixture(fbc)
        with patch.object(contract,'BOOTSTRAP_MODEL_ORIGINALS',{99:(fbc,DAY,708)}), \
             self.assertRaisesRegex(ValueError,'BOOTSTRAP_MODELS_REQUIRED'):
            self._release_proof('e'*40)

    def test_saved_r0_is_authenticated_retained_and_independently_projected_without_generating(self):
        from scripts import boat_recover_failed_owner as cli
        from race_ai import boat_all_model_cycle as engine,saved_view_feed as feed,boat_private_original_vault as vault
        from unittest.mock import patch
        self.assertTrue(callable(getattr(cli,'restore_failed_bootstrap_models',None)),'saved r0 restore hook is absent')
        self._bootstrap_models_fixture();before=deepcopy((self.control,self.models_payload,self.responses))
        with patch.object(engine,'forecast_saved_p0',side_effect=AssertionError('recovery generated a forecast')):
            proof=self._restore_bootstrap_models()
        self.assertEqual(proof['forecasts'],5)
        self.assertEqual(proof['new_forecasts'],0)
        self.assertEqual(proof['forecast_inventory_sha256'],proof['restored_inventory_sha256'])
        self.assertEqual(proof['issued_models_sha256'],proof['included_issued_models_sha256'])
        current=feed.current_view(self.feed_reader,self.feed_bootstrap,day=DAY)[3]
        predictions=[p for row in current['records'] for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p]
        self.assertEqual(sum(p.get('artifact_id')==708 for p in predictions),5)
        self.assertTrue(any(p.get('artifact_id')==701 for p in predictions))
        locator=vault.lookup_original(708,self.release_reader.repo,transport=self.release_reader)
        original=vault.restore_original(locator,self.release_reader.repo,key=KEY,transport=self.release_reader)
        self.assertEqual(original['raw_zip'],self.responses['actions/artifacts/708/zip'])
        self.assertEqual((self.control,self.models_payload,self.responses),before)
        again=self._restore_bootstrap_models()
        self.assertEqual(again['forecast_inventory_sha256'],proof['forecast_inventory_sha256'])
        self.assertEqual(again['new_forecasts'],0)

    def test_missing_or_changed_r0_and_lost_readback_never_authorize_continuation(self):
        from scripts import boat_recover_failed_owner as cli
        from unittest.mock import patch
        self.assertTrue(callable(getattr(cli,'restore_failed_bootstrap_models',None)),'saved r0 restore hook is absent')
        self._bootstrap_models_fixture()
        original=deepcopy(self.responses)
        for defect in ('missing','metadata','cipher','first_p0'):
            self.responses=deepcopy(original)
            if defect=='missing':
                self.responses['actions/runs/99/artifacts?per_page=100']=json.dumps(dict(total_count=3,
                    artifacts=[self.p0meta,self.contmeta,self.publicmeta])).encode()
            elif defect=='metadata':
                changed=dict(self.models_meta,digest='sha256:'+'f'*64)
                self.responses['actions/artifacts/708']=json.dumps(changed).encode()
            elif defect=='cipher':
                raw=self.responses['actions/artifacts/708/zip']
                self.responses['actions/artifacts/708/zip']=raw[:-1]+bytes([raw[-1]^1])
            else:
                self.replay['rows']=[]
            with self.subTest(defect=defect),self.assertRaises(ValueError):self._restore_bootstrap_models()
            self.assertEqual(self.feed_writer.head(),self.feed_initial)
        self.responses=original

    def test_issued_map_must_include_every_authenticated_saved_r0_slot(self):
        from scripts import boat_all_model_cycle as cli,boat_recover_failed_owner as recovery_cli
        from race_ai import saved_view_feed as feed
        self.assertTrue(callable(getattr(recovery_cli,'restore_failed_bootstrap_models',None)),'saved r0 restore hook is absent')
        self.assertTrue(callable(getattr(cli,'require_saved_bootstrap_models',None)),'issued-map guard is absent')
        self._bootstrap_models_fixture();self._restore_bootstrap_models()
        view=feed.current_view(self.feed_reader,self.feed_bootstrap,day=DAY)[3]
        maps={'P0':{},'P1':{}};cli._inventory(view,maps)
        receipt=dict(run_id='99',head_sha=self.run['head_sha'],artifact_id=701)
        checked=cli.require_saved_bootstrap_models(self.doc,receipt,maps['P0'],view,key=KEY,now=NOW)
        self.assertEqual(checked['forecasts'],5)
        for defect in ('missing_model','missing_view','changed_original'):
            issued=deepcopy(maps['P0']);damaged=deepcopy(view)
            if defect=='missing_model':
                row=next(row for row in view['records'] if any(p and p.get('artifact_id')==708
                    for p in [row.get('prediction'),*row.get('comparison_predictions',[])]))
                model=next(p['model_id'] for p in [row.get('prediction'),*row.get('comparison_predictions',[])]
                    if p and p.get('artifact_id')==708)
                issued[row['race_id']].remove(model)
            elif defect=='missing_view':damaged['records']=[]
            else:
                p=next(p for row in damaged['records'] for p in row['comparison_predictions'] if p.get('artifact_id')==708)
                p['generated_at']='2030-04-01T01:44:00.000001Z'
            with self.subTest(defect=defect),self.assertRaises(ValueError):
                cli.require_saved_bootstrap_models(self.doc,receipt,issued,damaged,key=KEY,now=NOW)
        self.assertIsNone(cli.require_saved_bootstrap_models(self.doc,receipt,{}, {'records':[]},
            key=KEY,now=NOW.replace(day=2)))
        self.assertIsNone(cli.require_saved_bootstrap_models(self.doc,dict(receipt,run_id='100'),{},
            {'records':[]},key=KEY,now=NOW))

    def test_existing_saved_r0_still_requires_its_actual_vault_locator_and_authenticated_bytes(self):
        from scripts import boat_recover_failed_owner as cli
        from race_ai import boat_private_original_vault as vault
        self._bootstrap_models_fixture()
        saved=cli.retain_verified_pair(self.verify(),self.run,self.release_writer.repo,now=NOW,
            transport=self.release_writer,readback_transport=self.release_reader)
        core_commit=saved['source_commit']
        self._restore_bootstrap_models()
        model_commit=self.release_remote.current
        locator=vault.lookup_original(708,self.release_writer.repo,transport=self.release_writer)
        self.release_remote.current=core_commit
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_MODEL_VAULT_ORIGINAL_MISSING'):
            self._restore_bootstrap_models()
        self.release_remote.current=model_commit
        path=locator['batch_path'];body=self.release_remote.objects[model_commit][path]
        self.release_remote.objects[model_commit][path]=body[:-1]+bytes([body[-1]^1])
        with self.assertRaises(ValueError):self._restore_bootstrap_models()

    def test_bootstrap_recovery_cannot_activate_history_for_a_non_history_feed(self):
        self._bootstrap_models_fixture()
        self.feed_writer.remote.current=self.feed_nonhistory
        with self.assertRaisesRegex(ValueError,'BOOTSTRAP_MODEL_HISTORY_CURRENT_REQUIRED'):
            self._restore_bootstrap_models()

    def test_bootstrap_model_restore_is_required_in_the_new_head_bound_dispatch_proof(self):
        from scripts import boat_recover_failed_owner as cli
        from scripts import boat_bootstrap_recovery_adapter as adapter
        from unittest.mock import patch
        self.assertTrue(callable(getattr(cli,'restore_failed_bootstrap_models',None)),'saved r0 restore hook is absent')
        self.assertTrue(callable(getattr(adapter,'verify_current_recovery_proof',None)),'current caller adapter is absent')
        self._bootstrap_models_fixture()
        proof=self._current_bootstrap_proof()
        self.assertIsNotNone(adapter.verify_current_recovery_proof(proof,[self.run],self.control,'e'*40,NOW))
        self.assertIsNone(recovery.verify_dispatch_proof(proof,[self.run],self.control,'e'*40,NOW))
        self.assertIsNone(adapter.verify_current_recovery_proof(proof['historical_proof'],
            [self.run],self.control,'e'*40,NOW))
        for defect in ('missing','old_head','missing_inventory','missing_issued','missing_vault'):
            changed=deepcopy(proof);model=changed['repairs'][0]['bootstrap_models']
            if defect=='missing':changed['repairs'][0].pop('bootstrap_models')
            elif defect=='old_head':changed['head_sha']=self.run['head_sha']
            elif defect=='missing_inventory':model['restored_inventory_sha256']='f'*64
            elif defect=='missing_issued':model['included_issued_models_sha256']='f'*64
            else:model['vault_commit']=None
            with self.subTest(defect=defect):
                self.assertIsNone(adapter.verify_current_recovery_proof(changed,[self.run],self.control,'e'*40,NOW))

    def test_successful_successor_keeps_failed_fbc_history_and_inherits_its_one_request(self):
        from scripts import boat_bootstrap_recovery_adapter as adapter
        from race_ai.boat_private_original_archive import seal_original_zip
        from tests.test_continuity_checkpoint import session
        self.assertTrue(callable(getattr(adapter,'verify_current_recovery_proof',None)),'current caller adapter is absent')
        self._bootstrap_models_fixture()
        successor=self._successful_successor()
        runs=[successor,self.run];before=deepcopy(runs)
        proof=self._current_bootstrap_proof(runs)
        fresh=recovery.read_final_control(self._release_get,successor)
        checked=adapter.verify_current_recovery_proof(proof,runs,fresh,'e'*40,NOW)
        self.assertIsNotNone(checked)
        self.assertEqual(checked['lifetime_requests'],93)
        self.assertEqual(checked['day_start_lifetime_requests'],88)
        self.assertEqual(runs,before)
        for defect in ('lost_history','renamed_head','active','wait','prepared','reset_lifetime','reset_day_base'):
            changed=deepcopy(proof);history=deepcopy(runs);control=deepcopy(fresh)
            if defect=='lost_history':history.pop()
            elif defect=='renamed_head':history[1]['head_sha']='e'*40
            elif defect=='active':history[0].update(status='in_progress',conclusion=None)
            elif defect=='wait':control['source_wait']={'state':'SOURCE_REVIEW_WAIT'}
            elif defect=='prepared':control['prepared_round']=2
            elif defect=='reset_lifetime':control['lifetime_requests']=88
            else:control['day_start_lifetime_requests']=89
            if defect in ('wait','prepared','reset_lifetime','reset_day_base'):
                changed['current_control']=control;changed['latest_control']=control
            with self.subTest(defect=defect):
                self.assertIsNone(adapter.verify_current_recovery_proof(changed,history,control,'e'*40,NOW))

    def test_every_authenticated_successor_control_keeps_counters_and_day_baseline(self):
        self._bootstrap_models_fixture()
        for defect in ('requests','day_base','rounds','round_base'):
            middle=self._successful_successor(total=100,used=11,
                day_base=89 if defect=='day_base' else 88,rounds=12 if defect=='rounds' else 8)
            latest=self._successful_successor(101,total=93 if defect=='requests' else 104,used=4,
                rounds=8 if defect in ('rounds','round_base') else 9,offset=10)
            with self.subTest(defect=defect),self.assertRaisesRegex(ValueError,'FINAL_PROOF_REJECTED'):
                self._current_bootstrap_proof([latest,middle,self.run])

    def test_other_day_or_other_canonical_owner_preflight_loads_no_runtime_or_key(self):
        from scripts import boat_all_model_cycle as cli,boat_bootstrap_recovery_adapter as adapter
        from unittest.mock import patch
        self.assertTrue(callable(getattr(cli,'preflight_saved_bootstrap_models',None)),'fatal original-restore preflight is absent')
        fbc='fbc743be548bfd123e46cdbfe290515a59e5e0d3';self._release_origin_fixture(fbc)
        with patch.object(adapter,'BOOTSTRAP_MODEL_ORIGINALS',{99:(fbc,DAY,708)}), \
             patch.object(cli,'prepare_runtime',side_effect=AssertionError('unrelated owner runtime was loaded')), \
             patch.object(cli,'_owner',side_effect=AssertionError('unrelated owner key was loaded')):
            self.assertIsNone(cli.preflight_saved_bootstrap_models(self.doc,self.p0meta,now=NOW.replace(day=2)))
            changed=deepcopy(self.p0meta);changed['workflow_run']['id']=100
            self.assertIsNone(cli.preflight_saved_bootstrap_models(self.doc,changed,now=NOW))

    def test_canonical_first_owner_missing_view_fails_original_restore_before_resume(self):
        import os,io
        from types import SimpleNamespace
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from scripts import boat_all_model_cycle as cli,github_existing_cycle as worker
        from race_ai import saved_view_feed as feed,boat_all_model_cycle as engine
        self.assertTrue(callable(getattr(cli,'preflight_saved_bootstrap_models',None)),'fatal original-restore preflight is absent')
        self._bootstrap_models_fixture()
        issued=self.release_root/'issued.json';issued.write_text('{}');issued.chmod(0o600)
        before=feed.current_view(self.feed_reader,self.feed_bootstrap)[3]
        output=io.StringIO()
        with patch.object(worker,'ROOT',self.release_writer.repo), \
             patch.object(worker,'original',return_value=(self.doc,self.replay['rows'],self.p0meta,self.p0)), \
             patch.object(worker,'_video_sources',return_value=(SimpleNamespace(verify=None,artifact_ids=[]),None)), \
             patch.object(worker,'recover',return_value=deepcopy(self.replay)), \
             patch.object(cli,'prepare_runtime',return_value={'issued_p0_models_path':str(issued)}), \
             patch.object(cli,'_existing_view',return_value=before),patch.object(cli,'utc_now',return_value=NOW), \
             patch.object(engine,'forecast_saved_p0',side_effect=AssertionError('restore generated a replacement')), \
             redirect_stdout(output),self.assertRaisesRegex(ValueError,'BOOTSTRAP_MODEL_COVERAGE_REQUIRED'):
            worker.restore(DAY)
        self.assertNotIn('ORIGINAL_REUSED_NO_REGENERATION',output.getvalue())

    def test_completed_validation_uses_actual_finish_clock_without_rewriting_original_clocks(self):
        import inspect
        from datetime import timedelta
        from unittest.mock import patch
        from scripts import boat_recover_failed_owner as cli,boat_bootstrap_recovery_adapter as adapter
        self.assertIn('clock',inspect.signature(cli.recover_history).parameters,'completion clock is absent')
        self._bootstrap_models_fixture();completed=[False];later=NOW+timedelta(seconds=601)
        original=cli.retain_verified_pair;before=deepcopy((self.doc,self.control,self.models_payload))
        def retained(checked,*args,**kwargs):
            result=original(checked,*args,**kwargs)
            if 708 in checked['original_artifact_ids']:completed[0]=True
            return result
        with patch.object(cli,'retain_verified_pair',side_effect=retained):
            proof=self._current_bootstrap_proof(clock=lambda:later if completed[0] else NOW)
        self.assertEqual(proof['verified_at'],later.isoformat())
        self.assertEqual(proof['historical_proof']['repairs'][0]['control']['recovery']['verified_at'],later.isoformat())
        self.assertEqual((self.doc,self.control,self.models_payload),before)
        self.assertIsNotNone(adapter.verify_current_recovery_proof(proof,[self.run],self.control,'e'*40,later))
        self.assertIsNone(adapter.verify_current_recovery_proof(proof,[self.run],self.control,'e'*40,
            later+timedelta(seconds=601)))

    def test_day_crossing_during_model_retention_never_emits_current_day_permission(self):
        import inspect
        from unittest.mock import patch
        from scripts import boat_recover_failed_owner as cli
        self.assertIn('clock',inspect.signature(cli.recover_history).parameters,'completion clock is absent')
        self._bootstrap_models_fixture();completed=[False];original=cli.retain_verified_pair
        def retained(checked,*args,**kwargs):
            result=original(checked,*args,**kwargs)
            if 708 in checked['original_artifact_ids']:completed[0]=True
            return result
        with patch.object(cli,'retain_verified_pair',side_effect=retained),self.assertRaises(ValueError):
            self._current_bootstrap_proof(clock=lambda:NOW.replace(day=2) if completed[0] else NOW)
