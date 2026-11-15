"""Synthetic V2 intent policy; no owner key, source, network or Git mutation."""
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from tests.test_official_result_issue import context,ISSUER


def frozen_context():
    from race_ai import all_existing_model_official_issue as I
    value,ctx,data=context();execution=value['target']['head_sha'];parent='c'*40;current='d'*40
    value.update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2',tested_execution_head_sha=execution,
                 intent_parent_sha=parent,failed_issue_dispositions=[])
    source=dict(schema='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1',tested_execution_head_sha=execution,
        intent_head_sha=ISSUER,intent_parent_sha=parent,target=value['target'],issue_request_blob_sha256='1'*64,
        recovery_request_blob_sha256=value['recovery_request_blob_sha256'],protected_files_sha256='2'*64)
    raw=json.dumps(value,sort_keys=True).encode();source['issue_request_blob_sha256']=sha256(raw).hexdigest()
    ctx['current_pr']['head']['sha']=current
    ctx['snapshot'].update(parents=[parent],execution_head_sha=execution,intent_head_sha=ISSUER,
        current_head_sha=current,source_issue_head=ISSUER,latest_issue_head_sha=ISSUER,
        latest_issue_raw=raw,
        source_is_ancestor=True,intent_is_ancestor_of_current=True,protected_files_sha256='2'*64,
        frozen_code_execution=True,current_pr_code_executed=False,tested_workflow_blob='3'*40,
        executed_workflow=dict(commit_sha='4'*40,head_sha=ISSUER,blob_sha='3'*40),
        source_frozen_binding=source,current_admission=dict(current_pr_head_sha=current,
            intent_is_ancestor=True,current_issue_head_sha=ISSUER),frozen_binding=dict(
            execution_head_sha=execution,intent_head_sha=ISSUER,source_issue_head=ISSUER,
            protected_files_sha256='2'*64,tested_workflow_blob='3'*40,
            executed_workflow=dict(commit_sha='4'*40,head_sha=ISSUER,blob_sha='3'*40)))
    return value,ctx,data


class FrozenIssueSchemaTests(unittest.TestCase):
    def test_archival_outer_returns_exact_legacy_bytes_without_current_intent(self):
        from race_ai import all_existing_model_official_issue as I
        from race_ai import all_existing_model_official_recovery as R
        from race_ai.all_existing_model_official_frozen_capsule import wrap_capsule
        from tests.test_all_existing_model_official_recovery import fixture,KEY
        from tests.test_official_frozen_capsule import binding
        self.assertTrue(callable(getattr(I,'archival_capsule_bytes',None)),'archival inner bridge is missing')
        data,_,_=fixture();inner=R.issue_consume_capsule(data,KEY);outer=wrap_capsule(inner,binding(data['target']),key=KEY)
        kwargs=dict(request=data['request'],target=data['target'],first_attempt=data['first_attempt'],key=KEY)
        self.assertEqual(I.archival_capsule_bytes(outer,**kwargs),inner)
        self.assertEqual(I.archival_capsule_bytes(inner,**kwargs),inner)
        self.assertEqual(I.archival_authority(outer,**kwargs),I.archival_authority(inner,**kwargs))
    def test_version_two_explicit_execution_and_real_parent_are_strict(self):
        from race_ai import all_existing_model_official_issue as I
        self.assertTrue(hasattr(I,'SCHEMA_V2'),'versioned frozen intent is missing')
        value,_,_=frozen_context()
        self.assertEqual(I.validate_issue_request(value),value)
        for change in (dict(tested_execution_head_sha='e'*40),dict(intent_parent_sha='bad'),
                       dict(failed_issue_dispositions=[dict(intent_head_sha='f'*40,issue_blob_sha256='bad')]),
                       dict(failed_issue_dispositions=[dict(intent_head_sha='f'*40,issue_blob_sha256='0'*64)]*2)):
            with self.subTest(change=change),self.assertRaises(ValueError):I.validate_issue_request(dict(value,**change))

    def test_frozen_execution_admits_unrelated_current_code_with_true_git_roles(self):
        from race_ai import all_existing_model_official_issue as I
        value,ctx,_=frozen_context()
        proof=I.admit_context(value,**ctx)
        self.assertEqual(proof['tested_execution_head_sha'],value['target']['head_sha'])
        self.assertEqual(proof['intent_head_sha'],ISSUER)
        self.assertEqual(proof['admitted_current_pr_head'],ctx['current_pr']['head']['sha'])
        self.assertFalse(proof['current_pr_code_executed'])

    def test_frozen_policy_cannot_convert_current_or_untested_code_into_execution(self):
        from race_ai import all_existing_model_official_issue as I
        for change in ('execution','parent','files','divergent','hidden_epoch','closure','workflow','import',
                       'actor','fork','first_failed','python_skipped'):
            value,ctx,_=frozen_context();facts=ctx['snapshot']
            if change=='execution':facts['execution_head_sha']='e'*40
            elif change=='parent':facts['parents']=['e'*40]
            elif change=='files':facts['changed_files'].append('race_ai/unreviewed.py')
            elif change=='divergent':facts['intent_is_ancestor_of_current']=False
            elif change=='hidden_epoch':facts['latest_issue_head_sha']='e'*40
            elif change=='closure':facts['source_frozen_binding']['protected_files_sha256']='e'*64
            elif change=='workflow':facts['executed_workflow']['blob_sha']='e'*40
            elif change=='import':facts['current_pr_code_executed']=True
            elif change=='actor':ctx['issuer_run']['actor']['id']=9
            elif change=='fork':ctx['current_pr']['head']['repo']['id']=9
            elif change=='first_failed':ctx['first_attempt']['conclusion']='failure'
            else:ctx['jobs']['jobs'][0]['steps'][0]['conclusion']='skipped'
            with self.subTest(change=change),self.assertRaises(ValueError):I.admit_context(value,**ctx)


if __name__=='__main__':unittest.main()
