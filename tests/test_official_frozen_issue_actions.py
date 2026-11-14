"""Synthetic Actions I2 flow with real original codecs and injected Git facts.

Full Git DAG, namespace and private-checkout proofs live in the companion
real-Git snapshot/bootstrap tests. No owner credential or provider is used.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import all_existing_model_official_issue as I
from race_ai.actions_contract import digest
from tests.test_all_existing_model_official_recovery import KEY
from tests.test_all_existing_model_official_continuation import complete_fixture, PLAN_BYTES
from tests.test_official_frozen_source_continuity import Snapshot
from tests.test_official_result_issue_actions import MemoryGithub, ISSUER
from scripts import all_existing_model_official_result_issue as worker


class FrozenSnapshot(Snapshot):
    def __init__(self,data):
        super().__init__(data);self.revoked=False;self.closure_changed=False;self.refreshes=[]
        self.issue['intent_parent_sha']='c'*40
        raw=json.dumps(self.issue,sort_keys=True).encode()
        binding=dict(schema='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1',tested_execution_head_sha=self.target,
            intent_head_sha=ISSUER,intent_parent_sha=self.issue['intent_parent_sha'],target=deepcopy(self.issue['target']),
            issue_request_blob_sha256=sha256(raw).hexdigest(),recovery_request_blob_sha256=sha256(self.raw).hexdigest(),
            protected_files_sha256='2'*64)
        self.facts.update(parents=[self.issue['intent_parent_sha']],execution_head_sha=self.target,
            intent_head_sha=ISSUER,source_issue_head=ISSUER,latest_issue_head_sha=ISSUER,latest_issue_raw=raw,
            source_is_ancestor=True,intent_is_ancestor_of_current=True,protected_files_sha256='2'*64,
            frozen_code_execution=True,current_pr_code_executed=False,tested_workflow_blob='3'*40,
            executed_workflow=dict(commit_sha='4'*40,head_sha=ISSUER,blob_sha='3'*40),source_frozen_binding=binding)
        self.refresh(dict(head=dict(sha='8'*40)))
    def refresh(self,pr):
        I.need(not self.revoked,'FROZEN_TEST_ACTIVE_INTENT');I.need(not self.closure_changed,'FROZEN_TEST_CLOSURE')
        current=pr['head']['sha'];self.refreshes.append(current)
        self.facts.update(current_head_sha=current,current_admission=dict(current_pr_head_sha=current,
            intent_is_ancestor=True,current_issue_head_sha=ISSUER))
        return deepcopy(self.facts)


class MovingGithub(MemoryGithub):
    def __init__(self,data):
        super().__init__(data);self.pr['head']['sha']='8'*40;self.callback_change=None;self.after_change=None
    def publish_capsule(self,path,raw,expected_parent,*,before_publish=None):
        self.pr['head']['sha']='a'*40
        if self.callback_change:self.callback_change()
        result=super().publish_capsule(path,raw,expected_parent,before_publish=before_publish)
        self.pr['head']['sha']='9'*40
        if self.after_change:self.after_change()
        return result


class FrozenIssueActionsTests(unittest.TestCase):
    def run_issue(self,snapshot,github,now,*,after_prepare=None,key_loader=lambda:KEY):
        original=worker.prepare_data
        def prepare(*args,**kwargs):
            result=original(*args,**kwargs);github.pr['head']['sha']='7'*40
            if after_prepare:after_prepare()
            return result
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for path,raw in PLAN_BYTES.items():
                item=root/path;item.parent.mkdir(parents=True,exist_ok=True);item.write_bytes(raw)
            with patch.object(worker.collector,'ROOT',root),patch.object(worker,'prepare_data',side_effect=prepare):
                return worker.issue_once(snapshot=snapshot,issuer_run_id=99,reader=github,writer=github,
                    readback=github,key_loader=key_loader,clock=lambda:now)

    def test_real_cipher_publication_survives_three_unrelated_tips_without_resigning(self):
        from race_ai.all_existing_model_official_frozen_capsule import unwrap_capsule
        data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
        result=self.run_issue(snapshot,github,now)
        self.assertEqual(result['schema'],I.PROOF_V2,'frozen publication must use the V2 proof')
        self.assertEqual(result['admitted_current_pr_head'],'9'*40)
        self.assertEqual(len(github.published),1)
        self.assertTrue({'8'*40,'7'*40,'a'*40,'9'*40}<=set(snapshot.refreshes))
        inner=unwrap_capsule(github.raw,expected_binding=snapshot.facts['source_frozen_binding'],key=KEY)
        self.assertNotEqual(github.raw,inner)
        self.assertEqual(result['outer_capsule_sha256'],sha256(github.raw).hexdigest())
        self.assertEqual(result['capsule_sha256'],result['outer_capsule_sha256'])
        self.assertEqual(result['inner_capsule_sha256'],sha256(inner).hexdigest())
        self.assertEqual(I.archival_capsule_bytes(github.raw,request=data['request'],target=data['target'],
            first_attempt=data['first_attempt'],key=KEY),inner)
        self.assertEqual(result['failed_issue_dispositions'],[])
        self.assertEqual(result['failed_issue_dispositions_sha256'],digest([]))
        self.assertEqual(result['verified_failed_issue_count'],0)
        self.assertFalse(result['current_pr_code_executed'])

    def test_revocation_and_authority_change_stop_before_key_or_publication(self):
        for phase in ('initial','prepared','callback','readback'):
            for change in ('revoked','closure_changed'):
                data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
                alter=lambda:setattr(snapshot,change,True)
                after=None;key_calls=[]
                if phase=='initial':alter()
                elif phase=='prepared':after=alter
                elif phase=='callback':github.callback_change=alter
                else:github.after_change=alter
                def key():key_calls.append(True);return KEY
                with self.subTest(phase=phase,change=change),self.assertRaisesRegex(ValueError,'FROZEN_TEST'):
                    self.run_issue(snapshot,github,now,after_prepare=after,key_loader=key)
                if phase=='initial':self.assertEqual(key_calls,[])
                self.assertEqual(len(github.published),1 if phase=='readback' else 0)

    def test_changed_binding_cannot_create_a_second_grant_after_data_admission(self):
        data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
        def change():
            snapshot.facts['source_frozen_binding']['protected_files_sha256']='5'*64
            snapshot.facts['protected_files_sha256']='5'*64
        with self.assertRaisesRegex(ValueError,'STABLE_FROZEN_SOURCE_BINDING'):
            self.run_issue(snapshot,github,now,after_prepare=change)
        self.assertEqual(github.published,[])

    def test_revocation_during_keyless_history_admission_precedes_key_lookup(self):
        data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
        original=worker.source_continuity
        def history(*args,**kwargs):
            result=original(*args,**kwargs);snapshot.revoked=True;return result
        with patch.object(worker,'source_continuity',side_effect=history),\
             self.assertRaisesRegex(ValueError,'FROZEN_TEST_ACTIVE_INTENT'):
            self.run_issue(snapshot,github,now,key_loader=lambda:self.fail('owner key after revoked history'))
        self.assertEqual(github.published,[])

    def test_old_failed_target_change_during_history_is_rechecked_before_key(self):
        data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
        changed=[False];original=worker.source_continuity
        def history(*args,**kwargs):
            result=original(*args,**kwargs);changed[0]=True;return result
        def failed(*args,**kwargs):
            if changed[0]:raise ValueError('OFFICIAL_ISSUE_FAILED_TARGET_BECAME_ACTIVE')
            return dict(schema='RACE_AI_OFFICIAL_FAILED_ISSUE_DISPOSITIONS_V1',
                        verified_failed_issue_count=0,failed_issues=[])
        with patch.object(worker,'source_continuity',side_effect=history),\
             patch.object(worker,'failed_dispositions',side_effect=failed),\
             self.assertRaisesRegex(ValueError,'FAILED_TARGET_BECAME_ACTIVE'):
            self.run_issue(snapshot,github,now,key_loader=lambda:self.fail('key after old target became active'))
        self.assertEqual(github.published,[])

    def test_uncertain_failed_anchor_is_rejected_before_owner_key(self):
        data,now=complete_fixture();snapshot=FrozenSnapshot(data);github=MovingGithub(data)
        with patch.object(worker,'failed_dispositions',side_effect=ValueError('OFFICIAL_ISSUE_FAILED_UNCERTAIN')),\
             self.assertRaisesRegex(ValueError,'FAILED_UNCERTAIN'):
            self.run_issue(snapshot,github,now,key_loader=lambda:self.fail('key before failed-anchor admission'))
        self.assertEqual(github.published,[])

    def test_main_requires_executed_checkout_witness_before_issuance(self):
        from scripts import official_frozen_execution as F
        data,_=complete_fixture();snapshot=FrozenSnapshot(data)
        with tempfile.TemporaryDirectory() as directory:
            proof=Path(directory)/'proof.json';output=io.StringIO()
            with patch.dict(os.environ,RUNNER_TEMP=directory),\
                 patch.object(worker,'trusted_environment',return_value=dict(head_sha=ISSUER,run_id=99)),\
                 patch.object(worker,'GithubIssueTransport'),\
                 patch.object(F,'FrozenGitSnapshot',return_value=snapshot),\
                 patch.object(F,'execution_witness',side_effect=ValueError('OFFICIAL_FROZEN_EXECUTION_ROOT')) as witness,\
                 patch.object(worker,'issue_once',side_effect=AssertionError('issuer before witness')),\
                 patch.object(worker,'state_key',side_effect=AssertionError('owner key before witness')),redirect_stdout(output):
                worker.main(['--proof',str(proof),'--frozen-git-root',directory,
                    '--frozen-intent-head',ISSUER,'--frozen-execution-head',snapshot.target])
            result=json.loads(proof.read_bytes())
        witness.assert_called_once();self.assertFalse(result['ready'])
        self.assertEqual(result['schema'],I.PROOF_V2)
        self.assertEqual(result['source_requests'],0)
        self.assertEqual(result['reason'],'OFFICIAL_FROZEN_EXECUTION_ROOT')

    def test_partial_frozen_runtime_flags_fail_closed_with_safe_v2_status(self):
        output=io.StringIO()
        with patch.dict(os.environ,{},clear=True),patch.object(worker,'state_key',side_effect=AssertionError('key forbidden')),redirect_stdout(output):
            self.assertEqual(worker.main(['--proof','/nonexistent/private.json','--frozen-intent-head',ISSUER]),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['schema'],I.PROOF_V2)
        self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)


if __name__=='__main__':unittest.main()
