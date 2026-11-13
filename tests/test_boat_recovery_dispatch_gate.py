"""Main recovery admission is internal, same-day and never a failure bypass."""
import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import importlib
import unittest
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

    def test_source_hold_and_no_remaining_request_budget_do_not_resume(self):
        for change in (dict(source_wait={'state':'AUTHORIZATION_WAIT'}),
                       dict(previous_session_requests=220,lifetime_requests=220)):
            args,proof=evidence()
            original=proof['repairs'][0]['original_control'];fixed=proof['repairs'][0]['control']
            original.update(change);fixed.update(change);args['continuation_proof']=original
            self.assertFalse(gate.decide(**args,recovery_proof=proof)['dispatch_allowed'])

    def test_existing_new_day_and_successful_continuation_remain_available(self):
        args=deepcopy(self.args);args['history']=dict(total_count=0,workflow_runs=[])
        out=gate.decide(**args)
        self.assertTrue(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])
        args=deepcopy(self.args);args['history']['workflow_runs'][0]['conclusion']='success'
        args['continuation_proof'].update(prepared_round=None,previous_stop_reason='WORKER_HANDOFF')
        out=gate.decide(**args)
        self.assertTrue(out['dispatch_allowed']);self.assertFalse(out['recovery_required'])

if __name__=='__main__':unittest.main()
