"""Real-Git history fixtures; no owner key, API, provider or publication."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from race_ai.actions_contract import digest
from scripts.all_existing_model_official_result_issue import GitSnapshot


PATH='audit/state/official-result-recovery-issue-request.json'
REQUEST='audit/state/official-result-recovery-request.json'


class TransparentMergeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.git('init','-q')
        self.initial=self.commit(None,[], 'official-results-collect: initial')
        self.first_raw=self.marker(self.initial,77)
        self.first=self.commit(self.first_raw,[self.initial],'official-results-issue: first')

    def git(self,*args,raw=None):
        value=subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
            '-c','commit.gpgsign=false',*args],cwd=self.root,input=raw,capture_output=True,check=True)
        return value.stdout.decode().strip()

    def marker(self,target,run):
        return (json.dumps(dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1',
            repository_id=1416489937,workflow_id=392270247,pull_request=71,
            target=dict(head_sha=target,run_id=run,run_attempt=2),target_first_viewer_job_id=1001,
            recovery_request_sha256=digest({}),recovery_request_blob_sha256=sha256(b'{}').hexdigest()),
            sort_keys=True)+'\n').encode()

    def commit(self,marker,parents,subject,*,note='',mode='100644'):
        self.git('read-tree','--empty')
        files={REQUEST:('100644',b'{}'),'notes.txt':('100644',note.encode())}
        if marker is not None:files[PATH]=(mode,marker)
        for name,(permissions,raw) in files.items():
            blob=self.git('hash-object','-w','--stdin',raw=raw)
            self.git('update-index','--add','--cacheinfo',permissions+','+blob+','+name)
        tree=self.git('write-tree');arguments=['commit-tree',tree]
        for parent in parents:arguments.extend(('-p',parent))
        return self.git(*arguments,'-m',subject)

    def snapshot(self,target):
        head=self.commit(self.marker(target,999),[target],'official-results-issue: next')
        self.git('update-ref','refs/heads/fixture',head)
        self.git('symbolic-ref','HEAD','refs/heads/fixture');self.git('reset','--hard','-q',head)
        return GitSnapshot(self.root,head)

    def assert_rejected(self,target):
        with self.assertRaises(ValueError):self.snapshot(target).previous_issue(target)

    def test_merge_adopting_unchanged_marker_from_only_parent_with_it_keeps_real_issue(self):
        left=self.commit(self.first_raw,[self.first],'left source-free code',note='left')
        right=self.commit(None,[self.initial],'right UI without issue marker',note='right')
        merge=self.commit(self.first_raw,[left,right],'Merge unrelated UI',note='merged')
        target=self.commit(self.first_raw,[merge],'official-results-collect: current',note='target')
        changes=self.git('rev-list','--topo-order','--full-history',target,'--',PATH).splitlines()
        self.assertIn(merge,changes)  # Actual failure pattern: merge appears as a path change.
        try:actual=self.snapshot(target).previous_issue(target)
        except ValueError as exc:self.fail('Unchanged marker adoption must preserve its original issue: '+str(exc))
        self.assertEqual(actual,self.first_raw)

    def test_all_same_parent_merge_keeps_real_issue(self):
        left=self.commit(self.first_raw,[self.first],'left code',note='left')
        right=self.commit(self.first_raw,[self.first],'right code',note='right')
        merge=self.commit(self.first_raw,[left,right],'Merge unchanged issue marker',note='merged')
        self.assertEqual(self.snapshot(merge).previous_issue(merge),self.first_raw)

    def test_transparent_adoption_does_not_hide_an_earlier_issued_then_deleted_side_epoch(self):
        branch=self.commit(None,[self.initial],'official-results-collect: side',note='side')
        issued=self.commit(self.marker(branch,88),[branch],'official-results-issue: side')
        deleted=self.commit(None,[issued],'delete uncertain side marker')
        merge=self.commit(self.first_raw,[self.first,deleted],'Merge adoption after side deletion')
        self.assert_rejected(merge)

    def test_same_parent_bytes_do_not_hide_incomparable_issue_branch_and_reversion(self):
        branch=self.commit(None,[self.initial],'official-results-collect: side',note='side')
        issued=self.commit(self.marker(branch,88),[branch],'official-results-issue: side')
        reverted=self.commit(self.first_raw,[issued],'revert side marker to first bytes')
        merge=self.commit(self.first_raw,[self.first,reverted],'Merge apparent identical marker')
        self.assert_rejected(merge)

    def test_merge_selecting_one_of_two_different_valid_issue_markers_is_rejected(self):
        branch=self.commit(None,[self.initial],'official-results-collect: side',note='side')
        issued=self.commit(self.marker(branch,88),[branch],'official-results-issue: side')
        merge=self.commit(self.first_raw,[self.first,issued],'Merge conflicting issue histories')
        self.assert_rejected(merge)

    def test_merge_authored_marker_not_in_any_parent_is_rejected(self):
        branch=self.commit(None,[self.initial],'unrelated side',note='side')
        merge=self.commit(self.marker(branch,88),[self.first,branch],'Merge forged issue bytes')
        self.assert_rejected(merge)

    def test_merge_cannot_restore_older_marker_after_newer_linear_issue(self):
        target=self.commit(self.first_raw,[self.first],'official-results-collect: second')
        newer=self.commit(self.marker(target,88),[target],'official-results-issue: second')
        side=self.commit(None,[self.initial],'unrelated missing marker side',note='side')
        merge=self.commit(self.first_raw,[newer,side],'Merge rollback to old marker')
        self.assert_rejected(merge)

    def test_nonmerge_marker_reversion_is_never_filtered(self):
        target=self.commit(self.first_raw,[self.first],'official-results-collect: second')
        newer=self.commit(self.marker(target,88),[target],'official-results-issue: second')
        reverted=self.commit(self.first_raw,[newer],'ordinary marker rollback')
        self.assert_rejected(reverted)

    def test_deleted_path_and_merge_deletion_are_rejected(self):
        deleted=self.commit(None,[self.first],'delete latest issue marker')
        self.assert_rejected(deleted)
        side=self.commit(None,[self.initial],'unrelated missing side',note='side')
        merge=self.commit(None,[deleted,side],'Merge missing marker')
        self.assert_rejected(merge)

    def test_nonregular_equal_parent_blob_cannot_be_transparent(self):
        side=self.commit(self.first_raw,[self.initial],'nonregular marker side',mode='100755')
        merge=self.commit(self.first_raw,[self.first,side],'Merge regular-looking marker')
        self.assert_rejected(merge)

    def test_valid_later_issue_after_transparent_merge_preserves_complete_chain(self):
        side=self.commit(None,[self.initial],'unrelated missing side',note='side')
        merge=self.commit(self.first_raw,[self.first,side],'Merge unchanged adoption')
        target=self.commit(self.first_raw,[merge],'official-results-collect: second')
        raw=self.marker(target,88)
        newer=self.commit(raw,[target],'official-results-issue: second')
        current=self.commit(raw,[newer],'official-results-collect: third')
        self.assertEqual(self.snapshot(current).previous_issue(current),raw)


if __name__=='__main__':unittest.main()
