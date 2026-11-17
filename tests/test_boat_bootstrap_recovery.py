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
