"""Main recovery admission is internal, same-day and never a failure bypass."""
import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import importlib
import unittest
from unittest.mock import patch
from scripts import boat_main_dispatch_gate as base
from scripts import boat_failed_recovery_contract as contract
try:
    gate=importlib.import_module('scripts.boat_recovery_dispatch_gate')
except ModuleNotFoundError:
    gate=None

NOW=datetime(2030,4,1,2,35,tzinfo=timezone.utc)
DAY='2030-04-01'

def evidence():
    run=dict(id=99,head_sha=base.RELEASE_SHA,head_branch=base.RELEASE_REF,
        name=base.WORKFLOW,event='workflow_dispatch',status='completed',conclusion='failure',
        created_at='2030-04-01T01:30:00Z')
    control=dict(previous_run_id=99,day_jst=DAY,previous_session_requests=88,
        completed_round=2,prepared_round=3,lifetime_requests=88,lifetime_completed_rounds=2,
        day_start_lifetime_requests=0,source_wait=None,previous_halted_reason=None,previous_stop_reason=None,
        receipt=dict(id=702,digest='sha256:'+'b'*64,created_at='2030-04-01T02:31:00Z'),
        source_control_receipt=dict(id=703,digest='sha256:'+'c'*64,created_at='2030-04-01T02:31:01Z'))
    fixed=deepcopy(control)
    fixed.update(completed_round=3,prepared_round=None,lifetime_completed_rounds=3)
    fixed['recovery']=dict(schema=contract.SCHEMA,previous_run_id=99,round_no=3,
        verified_at=NOW.isoformat(),original_control_receipt=deepcopy(control['receipt']),
        p1_receipt=dict(id=123,digest='sha256:'+'d'*64,created_at='2030-04-01T02:00:00Z'),
        result_receipt=dict(id=701,digest='sha256:'+'e'*64,created_at='2030-04-01T02:30:01Z'))
    proof=dict(schema=contract.PROOF_SCHEMA,head_sha=base.RELEASE_SHA,day_jst=DAY,
        verified_at=NOW.isoformat(),history_sha256=contract.history_digest([run]),latest_control=fixed,
        repairs=[dict(run_id=99,original_control=control,control=fixed,vault_commit='f'*40,
                      original_artifact_ids=[123,701])])
    args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=base.RELEASE_SHA)),
        owner_doc=dict(encoding='base64',content=base64.b64encode(base.RELEASE_TOKEN.encode()).decode()),
        history=dict(total_count=1,workflow_runs=[run]),continuation_proof=control)
    return args,proof

class RecoveryGateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(gate,'Cross-run recovery admission is absent')
        self.args,self.proof=evidence()

    def test_failure_without_recovery_never_dispatches_but_requests_repair(self):
        out=gate.decide(**self.args)
        self.assertFalse(out['dispatch_allowed'])
        self.assertTrue(out['recovery_required'])

    def test_verified_recovery_admits_next_worker_without_relabeling_failed_run(self):
        before=deepcopy((self.args,self.proof))
        out=gate.decide(**self.args,recovery_proof=self.proof)
        self.assertTrue(out['dispatch_allowed'])
        self.assertEqual(out['status'],'READY_VERIFIED_RECOVERED_OWNER_CONTINUATION')
        self.assertFalse(out['recovery_required'])
        self.assertEqual((self.args,self.proof),before)
        self.assertEqual(out['official_source_requests'],0)

    def orphan(self):
        args, proof = evidence()
        args['history']['workflow_runs'][0]['run_attempt'] = 1
        original = proof['repairs'][0]['original_control']
        fixed = deepcopy(original)
        fixed['prepared_round'] = None
        fixed['recovery'] = dict(schema='RACE_AI_ORPHAN_P1_ABANDONMENT_V1', previous_run_id=99,
            round_no=3, verified_at=NOW.isoformat(), original_control_receipt=deepcopy(original['receipt']),
            original_control=deepcopy(original),
            p1_receipt=dict(id=123,digest='sha256:'+'d'*64,created_at='2030-04-01T02:00:00Z'),
            continuity_receipt=deepcopy(original['receipt']),
            source_control_receipt=deepcopy(original['source_control_receipt']),
            checkpoint_AES_authenticated=True,public_control_matches_AES=True,
            missing_result_inventory_verified=True,first_receipt_union_verified=True,
            completed_round_advanced=False,originals_rewritten=False)
        proof['repairs'][0].update(control=fixed, original_artifact_ids=[123,702,703],
                                  original_head_sha=base.RELEASE_SHA)
        proof['latest_control'] = deepcopy(fixed)
        return args, proof

    def test_orphan_is_abandoned_without_completed_round_or_counter_increase(self):
        args, proof = self.orphan()
        before = deepcopy((args, proof))
        decision = gate.decide(**args, recovery_proof=proof)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(proof['latest_control']['completed_round'], 2)
        self.assertEqual(proof['latest_control']['lifetime_completed_rounds'], 2)
        self.assertEqual((args, proof), before)
        for field, value in [('completed_round',3),('lifetime_completed_rounds',3),
                             ('lifetime_requests',0),('day_start_lifetime_requests',88)]:
            altered=deepcopy(proof)
            altered['repairs'][0]['control'][field]=value
            altered['latest_control'][field]=value
            with self.subTest(field=field):
                self.assertFalse(gate.decide(**args,recovery_proof=altered)['dispatch_allowed'])

    def test_exact_reviewed_previous_owner_can_recover_under_new_current_dispatch_release(self):
        from unittest.mock import patch
        previous_eff='eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
        previous_m2='86b029ae5bddd5d4956497d8b32b2c92b8eec521'
        previous_profile='f55351dce855177a51330f72c37d6238ba2c9e3e'
        for previous,current in (('84128e0ec8bd9fe3da64ad49f74b8511b07e72be','e'*40),
                                 (previous_eff,'e'*40),(previous_eff,base.RELEASE_SHA),
                                 (previous_m2,'e'*40),(previous_m2,base.RELEASE_SHA),
                                 (previous_profile,'e'*40),(previous_profile,base.RELEASE_SHA)):
            with self.subTest(previous=previous,current=current):
                args, proof = self.orphan()
                args['history']['workflow_runs'][0]['head_sha']=previous
                proof['repairs'][0]['original_head_sha']=previous
                proof['history_sha256']=contract.history_digest(args['history']['workflow_runs'])
                proof['head_sha']=current
                args['release']['object']['sha']=current
                before=deepcopy((args,proof))
                with patch.object(base,'RELEASE_SHA',current):
                    decision=gate.decide(**args,recovery_proof=proof)
                    self.assertTrue(decision['dispatch_allowed'])
                    self.assertEqual(decision['release_sha'],current)
                    self.assertEqual((args,proof),before)
                    old_proof=deepcopy(proof);old_proof['head_sha']=previous
                    self.assertFalse(gate.decide(**args,recovery_proof=old_proof)['dispatch_allowed'])
                    args['release']['object']['sha']=previous
                    self.assertEqual(gate.decide(**args,recovery_proof=proof)['status'],
                                     'HOLD_RELEASE_SHA_MISMATCH')
                    args['release']['object']['sha']=current
                    args['history']['workflow_runs'][0]['head_sha']='d'*40
                    proof['repairs'][0]['original_head_sha']='d'*40
                    proof['history_sha256']=contract.history_digest(args['history']['workflow_runs'])
                    self.assertFalse(gate.decide(**args,recovery_proof=proof)['dispatch_allowed'])

    def test_zero_round_recovery_preserves_prior_same_day_owner_usage(self):
        original=self.proof['repairs'][0]['original_control']
        original.update(completed_round=0,prepared_round=None,
            previous_session_requests=0,lifetime_requests=11524,
            day_start_lifetime_requests=11072,lifetime_completed_rounds=608)
        fixed=deepcopy(original)
        fixed['recovery']=dict(schema='RACE_AI_NO_PENDING_FAILED_OWNER_V1',
            previous_run_id=99,round_no=None,verified_at=NOW.isoformat(),
            original_control_receipt=deepcopy(original['receipt']),source_attempts=0,
            no_p1_or_result_artifacts_verified=True,no_future_forecast_generated=True,
            originals_rewritten=False)
        self.proof['repairs'][0].update(control=fixed,vault_commit=None,original_artifact_ids=[])
        self.proof['latest_control']=deepcopy(fixed)
        self.args['continuation_proof']=deepcopy(original)
        before=deepcopy((self.args,self.proof))
        out=gate.decide(**self.args,recovery_proof=self.proof)
        self.assertTrue(out['dispatch_allowed'],'Main must consume the reviewed zero-round proof')
        self.assertEqual(out['status'],'READY_VERIFIED_RECOVERED_OWNER_CONTINUATION')
        self.assertEqual((self.args,self.proof),before)
        self.assertEqual(out['official_source_requests'],0)
        tampered=deepcopy(self.proof)
        for row in (tampered['latest_control'],tampered['repairs'][0]['control']):
            row['lifetime_requests']=11072
        self.assertFalse(gate.decide(**self.args,recovery_proof=tampered)['dispatch_allowed'])

    def test_failed_repair_leaves_next_invocation_in_recovery_not_forecast_mode(self):
        for _ in range(2):
            result=gate.decide(**self.args,recovery_proof=None)
            self.assertFalse(result['dispatch_allowed'])
            self.assertTrue(result['recovery_required'])

    def test_wrong_release_missing_policy_active_owner_and_midnight_stay_closed(self):
        changes=[dict(release=dict(ref='refs/heads/'+base.RELEASE_REF,object=dict(sha='0'*40))),
                 dict(owner_doc={}),dict(now=NOW.replace(hour=16)-timedelta(days=1))]
        for change in changes:
            with self.subTest(change=change):
                args=dict(self.args,**change)
                try:out=gate.decide(**args,recovery_proof=self.proof)
                except ValueError:continue
                self.assertFalse(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])
        args=deepcopy(self.args);args['history']['workflow_runs'][0]['status']='in_progress'
        out=gate.decide(**args,recovery_proof=self.proof)
        self.assertFalse(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])

    def test_stale_or_forged_proof_never_authorizes(self):
        for key,value in [('head_sha','0'*40),('history_sha256','0'*64),('verified_at','2030-04-01T02:00:00Z'),('repairs',[])]:
            proof=deepcopy(self.proof);proof[key]=value
            with self.subTest(key=key):self.assertFalse(gate.decide(**self.args,recovery_proof=proof)['dispatch_allowed'])
        proof=deepcopy(self.proof);proof['latest_control']['lifetime_requests']=0
        self.assertFalse(gate.decide(**self.args,recovery_proof=proof)['dispatch_allowed'])

    def test_source_hold_and_counter_contradiction_do_not_resume(self):
        for change in (dict(source_wait={'state':'AUTHORIZATION_WAIT'}),
                       dict(previous_session_requests=221,lifetime_requests=220)):
            args,proof=evidence()
            original=proof['repairs'][0]['original_control'];fixed=proof['repairs'][0]['control']
            original.update(change);fixed.update(change);args['continuation_proof']=original
            self.assertFalse(gate.decide(**args,recovery_proof=proof)['dispatch_allowed'])

    def test_verified_recovery_can_continue_after_310_authentic_gets(self):
        args, proof=evidence()
        for control in (args['continuation_proof'], proof['repairs'][0]['original_control'],
                        proof['repairs'][0]['control'],proof['latest_control']):
            control.update(previous_session_requests=310,lifetime_requests=310)
        out=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(out['dispatch_allowed'])
        self.assertEqual(out['status'],'READY_VERIFIED_RECOVERED_OWNER_CONTINUATION')

    def test_existing_new_day_and_successful_continuation_remain_available(self):
        args=deepcopy(self.args);args['history']=dict(total_count=0,workflow_runs=[])
        out=gate.decide(**args)
        self.assertTrue(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])
        args=deepcopy(self.args);args['history']['workflow_runs'][0]['conclusion']='success'
        args['continuation_proof'].update(prepared_round=None,previous_stop_reason='WORKER_HANDOFF')
        out=gate.decide(**args)
        self.assertTrue(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])


    @patch.object(base,'RELEASE_SHA','a74f1e940e7fc0852e63938f8138bdb58bd93163')
    def test_bb_original_recovery_requires_actual_a74_checkout_and_a74_bound_proof(self):
        protected='a74f1e940e7fc0852e63938f8138bdb58bd93163'
        previous='bb49215034b779ea1493b35dd91e5c3ebfc04032'
        args,proof=self.orphan()
        args['history']['workflow_runs'][0]['head_sha']=previous
        proof['repairs'][0]['original_head_sha']=previous
        proof['history_sha256']=contract.history_digest(args['history']['workflow_runs'])
        proof['head_sha']=protected
        args['release']['object']['sha']=protected
        before=deepcopy((args,proof))
        decision=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(decision['release_sha'],protected)
        self.assertEqual(decision['official_source_requests'],0)
        for change in (lambda p:p.update(head_sha=previous),
                       lambda p:p['repairs'][0].update(original_head_sha=protected),
                       lambda p:p['repairs'][0].update(original_head_sha='f'*40)):
            invalid=deepcopy(proof);change(invalid)
            with self.subTest(proof=invalid['head_sha']):
                self.assertFalse(gate.decide(**args,recovery_proof=invalid)['dispatch_allowed'])
        old=deepcopy(args);old['release']['object']['sha']=previous
        self.assertEqual(gate.decide(**old,recovery_proof=proof)['status'],
                         'HOLD_RELEASE_SHA_MISMATCH')
        active=deepcopy(args)
        active['history']['workflow_runs'][0].update(status='in_progress',conclusion=None)
        self.assertFalse(gate.decide(**active,recovery_proof=proof)['dispatch_allowed'])
        self.assertEqual((args,proof),before)


    def test_a74_original_recovery_requires_research_cache_checkout_and_new_bound_proof(self):
        protected='f1f8ed4ffb2a29e6b702685f49de63918610479d'
        previous='a74f1e940e7fc0852e63938f8138bdb58bd93163'
        args,proof=self.orphan()
        args['history']['workflow_runs'][0]['head_sha']=previous
        proof['repairs'][0]['original_head_sha']=previous
        proof['history_sha256']=contract.history_digest(args['history']['workflow_runs'])
        proof['head_sha']=protected
        args['release']['object']['sha']=protected
        before=deepcopy((args,proof))
        decision=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(decision['release_sha'],protected)
        self.assertEqual(decision['official_source_requests'],0)
        for change in (lambda p:p.update(head_sha=previous),
                       lambda p:p['repairs'][0].update(original_head_sha=protected),
                       lambda p:p['repairs'][0].update(original_head_sha='f'*40)):
            invalid=deepcopy(proof);change(invalid)
            with self.subTest(proof=invalid['head_sha']):
                self.assertFalse(gate.decide(**args,recovery_proof=invalid)['dispatch_allowed'])
        old=deepcopy(args);old['release']['object']['sha']=previous
        self.assertEqual(gate.decide(**old,recovery_proof=proof)['status'],
                         'HOLD_RELEASE_SHA_MISMATCH')
        active=deepcopy(args)
        active['history']['workflow_runs'][0].update(status='in_progress',conclusion=None)
        self.assertFalse(gate.decide(**active,recovery_proof=proof)['dispatch_allowed'])
        self.assertEqual((args,proof),before)

    def test_bb_original_recovery_requires_research_cache_checkout_and_new_bound_proof(self):
        protected='f1f8ed4ffb2a29e6b702685f49de63918610479d'
        previous='bb49215034b779ea1493b35dd91e5c3ebfc04032'
        args,proof=self.orphan()
        args['history']['workflow_runs'][0]['head_sha']=previous
        proof['repairs'][0]['original_head_sha']=previous
        proof['history_sha256']=contract.history_digest(args['history']['workflow_runs'])
        proof['head_sha']=protected
        args['release']['object']['sha']=protected
        before=deepcopy((args,proof))
        decision=gate.decide(**args,recovery_proof=proof)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(decision['release_sha'],protected)
        self.assertEqual(decision['official_source_requests'],0)
        for change in (lambda p:p.update(head_sha=previous),
                       lambda p:p['repairs'][0].update(original_head_sha=protected),
                       lambda p:p['repairs'][0].update(original_head_sha='f'*40)):
            invalid=deepcopy(proof);change(invalid)
            with self.subTest(proof=invalid['head_sha']):
                self.assertFalse(gate.decide(**args,recovery_proof=invalid)['dispatch_allowed'])
        old=deepcopy(args);old['release']['object']['sha']=previous
        self.assertEqual(gate.decide(**old,recovery_proof=proof)['status'],
                         'HOLD_RELEASE_SHA_MISMATCH')
        active=deepcopy(args)
        active['history']['workflow_runs'][0].update(status='in_progress',conclusion=None)
        self.assertFalse(gate.decide(**active,recovery_proof=proof)['dispatch_allowed'])
        self.assertEqual((args,proof),before)


if __name__=='__main__':unittest.main()
