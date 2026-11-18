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
