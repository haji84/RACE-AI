"""Source-free history/pin admission using authored immutable GitHub metadata."""
from copy import deepcopy
import json
import unittest

from tests.test_all_existing_model_official_continuation import complete_fixture
from tests.test_official_result_issue_actions import MemorySnapshot,MemoryGithub


class Snapshot(MemorySnapshot):
    def __init__(self,data):
        super().__init__(data)
        self.issue.update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2',
            tested_execution_head_sha=self.target,intent_parent_sha='d'*40,failed_issue_dispositions=[])
        self.nodes={'1'*40:self.previous_raw};self.order=['1'*40]
    def issue_history(self,head):return list(self.order)
    def commit_facts(self,head):
        issue=json.loads(self.nodes[head]);parent=issue.get('intent_parent_sha',issue['target']['head_sha'])
        return dict(head_sha=head,parents=[parent],changed_files=['audit/state/official-result-recovery-issue-request.json'],
                    subject='official-results-issue: authored original')
    def is_ancestor(self,*_):return True
    def read(self,head,path,limit):
        if path.endswith('official-result-recovery-issue-request.json') and head in self.nodes:return self.nodes[head]
        return super().read(head,path,limit)


class FrozenSourceContinuityTests(unittest.TestCase):
    def api(self):
        from scripts import all_existing_model_official_result_issue as worker
        api=getattr(worker,'source_continuity',None)
        self.assertTrue(callable(api),'full pre-key source history continuity is missing')
        return api
    def test_latest_actual_source_and_its_exact_output_pins_are_retained(self):
        api=self.api();data,_=complete_fixture();snapshot=Snapshot(data);github=MemoryGithub(data)
        result=api(snapshot,snapshot.issue,data['request'],github)
        self.assertEqual(result['issue']['target']['run_id'],77)
        self.assertEqual(len(result['actual_source_epochs']),1)
        request=deepcopy(data['request']);request['manifest']['prior_journal_artifacts'].pop()
        with self.assertRaises(ValueError):api(snapshot,snapshot.issue,request,github)
    def test_an_older_actual_epoch_cannot_hide_behind_a_latest_request_omission(self):
        api=self.api();data,_=complete_fixture();snapshot=Snapshot(data);github=MemoryGithub(data)
        old=json.loads(snapshot.previous_raw);old['target']=dict(head_sha='6'*40,run_id=66,run_attempt=2)
        snapshot.nodes['2'*40]=json.dumps(old).encode();snapshot.order.append('2'*40)
        github.runs[66]=dict(github.runs[77],id=66,head_sha='6'*40)
        original=github.json
        def missing(path):
            if path=='actions/runs/66/artifacts?per_page=100&page=1':return dict(total_count=0,artifacts=[])
            return original(path)
        github.json=missing
        with self.assertRaisesRegex(ValueError,'PREVIOUS_ACTUAL_JOURNAL_REQUIRED'):
            api(snapshot,snapshot.issue,data['request'],github)


if __name__=='__main__':unittest.main()
