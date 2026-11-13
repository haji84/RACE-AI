"""Fresh-run recovery of actual encrypted fixture originals; no provider calls."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.private_cycle_ui_fixture import _artifacts
from tests.test_boat_private_original_vault import packed, KEY, HEAD
from race_ai.boat_private_original_archive import seal_original_zip
from race_ai.actions_contract import digest
from race_ai import repeated_cycle

try:
    recovery = importlib.import_module('race_ai.boat_pending_round_recovery')
except ModuleNotFoundError:
    recovery = None

DAY = '2030-04-01'
NOW = datetime(2030, 4, 1, 2, 35, tzinfo=timezone.utc)



def encrypted(raw, metadata, kind):
    meta=deepcopy(metadata)
    meta['workflow_run'].update(repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD)
    cipher=seal_original_zip(raw, run_id=meta['workflow_run']['id'], head_sha=HEAD, kind=kind, key=KEY)
    outer=packed({'private-original.enc':cipher})
    meta.update(digest='sha256:'+sha256(outer).hexdigest(),size_in_bytes=len(outer))
    return outer,meta


def fixture():
    p1_raw, p1_meta = deepcopy(_artifacts()[0][1])
    p1_meta.update(name='boat-national-cutoff-99-cycle-03', expires_at='2030-04-08T02:00:00Z')
    p1_raw, p1_meta = encrypted(p1_raw, p1_meta, 'P1')
    session = dict(day_jst=DAY, run_id=99, requests_used=88, completed_round=2,
                   prepared_round=3, lifetime_requests=88, lifetime_completed_rounds=2,
                   day_start_lifetime_requests=0, source_wait=None, halted_reason=None)
    report = dict(day_jst=DAY, run_id='99', code_sha=HEAD, round_no=3,
                  first_forecast_artifacts=[p1_meta], bounded_repeat_session=session,
                  result_observation_versions=0, updated_at='2030-04-01T02:30:00Z')
    report['report_sha256'] = digest(report)
    original = packed({'status.json': json.dumps(report), 'official-result-observations.json': b'[]',
                       'current-p1-original.zip': p1_raw})
    result_meta = dict(id=701, name='race-existing-cycle-99-cycle-03', expired=False,
                       created_at='2030-04-01T02:30:01Z', expires_at='2030-04-08T02:30:00Z',
                       workflow_run=dict(id=99, head_repository_id=1416489937))
    result_raw, result_meta = encrypted(original, result_meta, 'RESULT')
    run = dict(id=99, head_sha=HEAD, workflow_id=405276784,
               head_branch='production/boat-p0-p1-20261111', event='workflow_dispatch',
               status='completed', conclusion='failure', run_attempt=1,
               created_at='2030-04-01T01:30:00Z', updated_at='2030-04-01T02:32:00Z',
               repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
               head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))
    control = dict(previous_run_id=99, day_jst=DAY, previous_session_requests=88,
                   completed_round=2, prepared_round=3, lifetime_requests=88,
                   lifetime_completed_rounds=2, day_start_lifetime_requests=0,
                   source_wait=None, previous_halted_reason=None, previous_stop_reason=None,
                   receipt=dict(id=702, digest='sha256:'+'b'*64, created_at='2030-04-01T02:31:00Z'),
                   source_control_receipt=dict(id=703, digest='sha256:'+'c'*64, created_at='2030-04-01T02:31:01Z'))
    artifacts = [p1_meta, result_meta]
    responses = {f'actions/runs/99/artifacts?per_page=100':
                 json.dumps(dict(total_count=2, artifacts=artifacts)).encode()}
    for raw, meta in ((p1_raw, p1_meta), (result_raw, result_meta)):
        responses[f'actions/artifacts/{meta["id"]}'] = json.dumps(meta).encode()
        responses[f'actions/artifacts/{meta["id"]}/zip'] = raw
    return run, control, responses


class RecoveryCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(recovery, 'Durable pending-round recovery is not implemented')
        env = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        env.start(); self.addCleanup(env.stop)
        self.run_meta, self.control, self.responses = fixture()

    def recover(self):
        return recovery.verify_pending_round(lambda p: self.responses[p], self.run_meta, self.control, now=NOW)



class PendingRoundRecoveryTests(RecoveryCase):
    def test_new_process_restores_round_without_changing_originals_or_inference(self):
        before = deepcopy((self.control, self.responses))
        with patch('urllib.request.urlopen', side_effect=AssertionError('provider access')):
            result = self.recover()
        c = result['control']
        self.assertEqual(c['completed_round'], 3)
        self.assertIsNone(c['prepared_round'])
        self.assertEqual(c['lifetime_requests'], 88)
        self.assertEqual(c['lifetime_completed_rounds'], 3)
        self.assertEqual((self.control, self.responses), before)
        self.assertEqual(result['original_artifact_ids'], [123, 701])
        self.assertGreater(result['replayed_p1_rows'], 0)
        self.assertEqual(result['new_forecasts'], 0)

    def test_recovered_control_starts_new_worker_without_resetting_day_budget(self):
        c = self.recover()['control']
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'session.json'
            s = repeated_cycle.start(path, day=DAY, run_id=100, now=NOW, source_control=c)
            self.assertEqual(s['lifetime_requests'], 88)
            self.assertEqual(s['day_start_lifetime_requests'], 0)
            self.assertEqual(s['lifetime_completed_rounds'], 3)
            self.assertTrue(repeated_cycle.prepare(path, 1, now=NOW)['active'])
            repeated_cycle.SourceGuard(path, clock=lambda:NOW).charge('forecast')
            self.assertEqual(repeated_cycle.load(path)['lifetime_requests'], 89)

    def test_missing_result_never_advances(self):
        del self.responses['actions/artifacts/701/zip']
        with self.assertRaises((KeyError, ValueError)): self.recover()
        self.assertEqual(self.control['completed_round'], 2)

    def test_corrupt_ciphertext_never_advances(self):
        self.responses['actions/artifacts/701/zip'] += b'corrupt'
        with self.assertRaises(ValueError): self.recover()

    def test_foreign_run_head_and_active_run_rejected(self):
        for changes in (dict(head_sha='f'*40), dict(id=100), dict(status='in_progress'),
                        dict(run_attempt=2), dict(event='pull_request'), dict(conclusion='cancelled')):
            old = deepcopy(self.run_meta); self.run_meta.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.recover()
            self.run_meta = old

    def test_source_holds_and_unknown_day_counters_rejected(self):
        for changes in (dict(source_wait={'state':'AUTHORIZATION_WAIT'}),
                        dict(previous_halted_reason='SOURCE_HTTP_403_NO_RETRY'),
                        dict(day_start_lifetime_requests=None), dict(lifetime_requests=87),
                        dict(prepared_round=4), dict(completed_round=True), dict(lifetime_requests=241)):
            old = deepcopy(self.control); self.control.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.recover()
            self.control = old

    def test_old_day_must_not_authorize_today_forecasts(self):
        with self.assertRaises(ValueError):
            recovery.verify_pending_round(lambda p:self.responses[p], self.run_meta, self.control,
                now=datetime(2030,4,2,2,35,tzinfo=timezone.utc))

    def test_forged_control_counters_disagree_with_sealed_result(self):
        self.control.update(previous_session_requests=87, lifetime_requests=87)
        with self.assertRaises(ValueError): self.recover()

    def test_recovery_does_not_silently_accept_duplicate_originals(self):
        key='actions/runs/99/artifacts?per_page=100'
        listing=json.loads(self.responses[key]); duplicate=deepcopy(listing['artifacts'][1]);duplicate['id']=999
        listing['artifacts'].append(duplicate);listing['total_count']=3
        self.responses[key]=json.dumps(listing).encode()
        with self.assertRaises(ValueError): self.recover()


class RecoveryAdmissionTests(RecoveryCase):
    def test_fresh_recovery_proof_admits_failed_parent_without_claiming_run_success(self):
        self.assertTrue(hasattr(recovery, 'verify_dispatch_proof'), 'No recovery-to-dispatch gate')
        checked = self.recover()
        self.run_meta['name']='BOAT nationwide cutoff-ordered A/B research (no Vercel)'
        proof=dict(schema=recovery.PROOF_SCHEMA,head_sha=HEAD,day_jst=DAY,verified_at=NOW.isoformat(),
                   history_sha256=recovery.history_digest([self.run_meta]),
                   latest_control=checked['control'],
                   repairs=[dict(run_id=99,original_control=self.control,control=checked['control'],
                                 vault_commit='d'*40,original_artifact_ids=checked['original_artifact_ids'])])
        accepted=recovery.verify_dispatch_proof(proof,[self.run_meta],self.control,HEAD,NOW)
        self.assertEqual(accepted['completed_round'],3)
        self.assertEqual(self.run_meta['conclusion'],'failure')
        for changes in (dict(head_sha='b'*40),dict(vault_commit=None)):
            changed=deepcopy(proof)
            if 'vault_commit' in changes:changed['repairs'][0].update(changes)
            else:changed.update(changes)
            self.assertIsNone(recovery.verify_dispatch_proof(changed,[self.run_meta],self.control,HEAD,NOW))
        tampered=deepcopy(proof);tampered['latest_control']['lifetime_requests']=0
        self.assertIsNone(recovery.verify_dispatch_proof(tampered,[self.run_meta],self.control,HEAD,NOW))

    def test_evidence_must_match_fresh_history_and_not_expire(self):
        self.assertTrue(hasattr(recovery,'verify_dispatch_proof'),'No recovery-to-dispatch gate')
        self.assertIsNone(recovery.verify_dispatch_proof({},[self.run_meta],self.control,HEAD,NOW))

class PhysicalRecoveryTests(RecoveryCase):
    def test_recovery_after_failed_read_retains_exact_cipher_and_is_idempotent(self):
        from scripts.boat_recover_failed_owner import retain_verified_pair
        from tests.test_boat_private_original_vault import VaultTests
        fixture_git=VaultTests();fixture_git.setUp();self.addCleanup(fixture_git.doCleanups)
        checked=self.recover()
        def retain():
            return retain_verified_pair(checked,self.run_meta,fixture_git.writer.repo,now=NOW,
                transport=fixture_git.writer,readback_transport=fixture_git.reader)
        first=retain()
        self.assertTrue(first['independent_git_readback_verified'])
        for locator in first['locators']:
            readback=fixture_git.restore(locator)
            ident=locator['artifact_id']
            self.assertEqual(readback['raw_zip'],self.responses[f'actions/artifacts/{ident}/zip'])
        commit=fixture_git.writer.head()
        second=retain()
        self.assertEqual(second['status'],'EXACT_ORIGINAL_VAULT_UNCHANGED')
        self.assertEqual(fixture_git.writer.head(),commit)

    def test_failed_recovery_invocation_cannot_emit_dispatch_permission(self):
        from scripts.boat_recover_failed_owner import recover_history
        self.run_meta['name']='BOAT nationwide cutoff-ordered A/B research (no Vercel)'
        self.responses['actions/runs/99']=json.dumps(self.run_meta).encode()
        parameters=dict(runs=[self.run_meta],get=lambda p:self.responses[p],
            load_control=lambda _:deepcopy(self.control),
            replay_day=lambda:dict(complete=True,rows=[dict(stage='P0')]),
            now=NOW,expected_head=HEAD)
        def unavailable(*_):raise ValueError('VAULT_GITHUB_HTTP_503')
        with self.assertRaises(ValueError):recover_history(**parameters,retain=unavailable)
        proof=recover_history(**parameters,retain=lambda *_:dict(independent_git_readback_verified=True,source_commit='d'*40))
        self.assertIsNotNone(recovery.verify_dispatch_proof(proof,[self.run_meta],self.control,HEAD,NOW))
        self.assertEqual(self.control['prepared_round'],3)

if __name__=='__main__': unittest.main()
