"""V2 source-free reuse guards; authored Git/API facts and fixture crypto only."""
from copy import deepcopy
import json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch

from race_ai import all_existing_model_official_prepare as P
from scripts import all_existing_model_official_result_prepare as W
from tests.test_official_result_prepare import context,DAY

V2='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V2'


def reused_context():
    value,ctx,_=context();source=value['previous_source'];ancestor=dict(
        head_sha=source['head_sha'],run_id=source['run_id'],run_attempt=1,first_viewer_job_id=source['first_viewer_job_id'])
    value.pop('verified_parent');value.update(schema=V2,verified_code_ancestor=ancestor)
    parent='a'*40;s=ctx['snapshot'];s.update(parents=[parent],issuer_parent=dict(head_sha=parent,
        parents=[source['head_sha']],changed_files=[W.I.ISSUE_PATH],subject='official-results-issue: exact',
        issue_raw=s['latest_issue_raw']),tested_workflow_blob='b'*40,
        data_only_changes=[dict(path=W.I.ISSUE_PATH,old_mode='100644',new_mode='100644',status='M'),
                           dict(path=P.PATH,old_mode='000000',new_mode='100644',status='A')])
    ctx.update(parent_current=ctx['source_current'],parent_first=ctx['source_first'],parent_jobs=ctx['source_jobs'])
    ctx['executed_workflow']=dict(commit_sha='e'*40,head_sha=s['head_sha'],blob_sha='b'*40)
    return value,ctx


class ReusedContextTests(unittest.TestCase):
    def test_real_fixture_mac_native_result_and_three_output_cli(self):
        from tests.test_official_result_prepare_actions import PreparationActionsTests
        PreparationActionsTests()._real_crypto_preparation(reuse_code=True)
    def test_exact_source_code_ancestor_accepts_without_parent_whole_first(self):
        value,ctx=reused_context();proof=P.admit_context(value,**ctx)
        self.assertTrue(proof['reused_code_ancestor']);self.assertFalse(proof['parent_whole_first_verified'])
        self.assertEqual(proof['verified_code_ancestor'],value['verified_code_ancestor'])
        self.assertEqual(proof['immediate_issuer_parent'],ctx['snapshot']['parents'][0])
    def test_unrelated_ancestor_source_attempt_or_workflow_mismatch_rejects(self):
        for change in ('ancestor','attempt','running','skipped','fork','workflow','extra','mode','parent','issue'):
            value,ctx=reused_context()
            if change=='ancestor':value['verified_code_ancestor']['head_sha']='f'*40
            elif change=='attempt':ctx['source_current']['run_attempt']=3
            elif change=='running':ctx['source_current']['status']='in_progress'
            elif change=='skipped':ctx['source_jobs']['jobs'][0]['steps'][0]['conclusion']='skipped'
            elif change=='fork':ctx['current_pr']['head']['repo']['id']=12
            elif change=='workflow':ctx['executed_workflow']['blob_sha']='f'*40
            elif change=='extra':ctx['snapshot']['data_only_changes'].append(dict(path='race_ai/x.py'))
            elif change=='mode':ctx['snapshot']['data_only_changes'][0]['new_mode']='120000'
            elif change=='parent':ctx['snapshot']['issuer_parent']['parents'].append('f'*40)
            else:ctx['snapshot']['issuer_parent']['subject']='ordinary: unsafe'
            with self.subTest(change=change),self.assertRaises(ValueError):P.admit_context(value,**ctx)
    def test_request_exact_schema_types_and_source_identity(self):
        value,_=reused_context();self.assertEqual(P.validate_prepare_request(value),value)
        for change in ('extra','both','boolean','viewer'):
            bad=deepcopy(value)
            if change=='extra':bad['unknown']=True
            elif change=='both':bad['verified_parent']=bad['verified_code_ancestor']
            elif change=='boolean':bad['verified_code_ancestor']['run_id']=True
            else:bad['verified_code_ancestor']['first_viewer_job_id']=77
            with self.subTest(change=change),self.assertRaises(ValueError):P.validate_prepare_request(bad)


class WorkflowOriginTests(unittest.TestCase):
    def fixture(self):
        head='d'*40;merge='e'*40;blob='b'*40;trees=['1'*40,'2'*40,'3'*40]
        values={'git/commits/'+merge:dict(sha=merge,parents=[dict(sha=head)],tree=dict(sha=trees[0]))}
        for index,path in enumerate(('.github','workflows','forecast-audit-ui.yml')):
            last=index==2
            values['git/trees/'+trees[index]]=dict(sha=trees[index],truncated=False,tree=[dict(
                path=path,mode='100644' if last else '040000',type='blob' if last else 'tree',
                sha=blob if last else trees[index+1],**({'size':123} if last else {}))])
        return head,merge,blob,values
    def test_exact_merge_workflow_uses_only_four_existing_gets(self):
        head,merge,blob,values=self.fixture();reader=Mock();reader.json.side_effect=lambda p:deepcopy(values[p])
        with patch.dict(os.environ,dict(GITHUB_SHA=merge,GITHUB_WORKFLOW_SHA=merge),clear=True):
            proof=W.executed_workflow(reader,head,blob)
        self.assertEqual(proof['blob_sha'],blob);self.assertEqual(reader.json.call_count,4)
    def test_bad_env_commit_tree_mode_duplicate_truncation_and_blob_reject(self):
        for change in ('env','unrelated','duplicate','truncated','mode','blob'):
            head,merge,blob,values=self.fixture();env=dict(GITHUB_SHA=merge,GITHUB_WORKFLOW_SHA=merge)
            if change=='env':env['GITHUB_WORKFLOW_SHA']='f'*40
            elif change=='unrelated':values['git/commits/'+merge]['parents']=[dict(sha='f'*40)]
            elif change=='duplicate':values['git/trees/'+'1'*40]['tree']*=2
            elif change=='truncated':values['git/trees/'+'1'*40]['truncated']=True
            elif change=='mode':values['git/trees/'+'3'*40]['tree'][0]['mode']='120000'
            else:values['git/trees/'+'3'*40]['tree'][0]['sha']='f'*40
            reader=Mock();reader.json.side_effect=lambda p:deepcopy(values[p])
            with self.subTest(change=change),patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):
                W.executed_workflow(reader,head,blob)

    def test_invalid_workflow_or_source_context_never_reaches_key_or_archive(self):
        for change in ('missing_env','bad_tree','source_unverified'):
            value,ctx=reused_context();head,merge,blob,trees=self.fixture()
            # Actual D fixture uses the context head rather than the independent
            # minimal workflow helper's dddd head.
            trees['git/commits/'+merge]['parents']=[dict(sha=ctx['snapshot']['head_sha'])]
            source=value['previous_source'];run=ctx['prepare_run']['id']
            values=dict(trees);values.update({'actions/runs/'+str(run):ctx['prepare_run'],'pulls/71':ctx['current_pr'],
                'actions/runs/'+str(source['run_id']):ctx['source_current'],
                'actions/runs/'+str(source['run_id'])+'/attempts/1':ctx['source_first'],
                'actions/runs/'+str(source['run_id'])+'/attempts/1/jobs?per_page=100':ctx['source_jobs']})
            if change=='bad_tree':values['git/trees/'+'3'*40]['tree'][0]['mode']='120000'
            if change=='source_unverified':values['actions/runs/'+str(source['run_id'])]['status']='in_progress'
            snapshot=Mock();snapshot.facts=ctx['snapshot'];snapshot.read.return_value=json.dumps(value).encode()
            snapshot.prepare_facts.return_value=ctx['snapshot'];reader=Mock();reader.json.side_effect=lambda p:deepcopy(values[p])
            key=Mock(side_effect=AssertionError('NO_KEY'));env={} if change=='missing_env' else dict(GITHUB_SHA=merge,GITHUB_WORKFLOW_SHA=merge)
            with self.subTest(change=change),patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):
                W.prepare_once(snapshot=snapshot,prepare_run_id=run,reader=reader,key_loader=key,clock=lambda:DAY)
            key.assert_not_called();reader.archive.assert_not_called()


class GitEquivalenceTests(unittest.TestCase):
    def test_real_git_direct_issue_prep_chain_and_extra_code_mode_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):return subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                '-c','commit.gpgsign=false',*args],cwd=root,capture_output=True,check=True).stdout.decode().strip()
            git('init','-q');paths=[W.I.REQUEST_PATH,W.I.WORKFLOW_PATH,'race_ai/code.py']
            for name in paths:p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}' if name.endswith('.json') else 'fixed')
            git('add','.');git('commit','-qm','official-results-collect: tested B');b=git('rev-parse','HEAD')
            value,ctx=reused_context();value['verified_code_ancestor']['head_sha']=value['previous_source']['head_sha']=b
            issue=json.loads(ctx['snapshot']['latest_issue_raw']);issue['target']['head_sha']=b
            p=root/W.I.ISSUE_PATH;p.write_text(json.dumps(issue));git('add','.');git('commit','-qm','official-results-issue: C');c=git('rev-parse','HEAD')
            p=root/P.PATH;p.write_text(json.dumps(value));git('add','.');git('commit','-qm','official-results-prepare: D');d=git('rev-parse','HEAD')
            snapshot=W.PrepareSnapshot(root,d);facts=snapshot.prepare_facts(value)
            self.assertEqual(facts['issuer_parent']['head_sha'],c);self.assertEqual(len(facts['data_only_changes']),2)
            for change in ('mode','content','rename','delete','symlink','submodule','merge'):
                git('reset','--hard','-q',d)
                code=root/'race_ai/code.py'
                if change=='mode':code.chmod(0o755)
                elif change=='content':code.write_text('different execution code')
                elif change=='rename':code.rename(code.with_name('renamed.py'))
                elif change=='delete':code.unlink()
                elif change=='symlink':p.unlink();p.symlink_to('untrusted-preparation.json')
                elif change=='submodule':git('update-index','--add','--cacheinfo','160000,'+b+',submodule')
                if change=='merge':
                    head=git('commit-tree',git('rev-parse','HEAD^{tree}'),'-p',c,'-p',b,'-m','official-results-prepare: merge')
                    git('checkout','-q','--detach',head)
                else:
                    if change!='submodule':git('add','-A')
                    git('commit','--amend','--no-edit','-q');head=git('rev-parse','HEAD')
                with self.subTest(change=change),self.assertRaises(ValueError):
                    W.PrepareSnapshot(root,head).prepare_facts(value)


if __name__=='__main__':unittest.main()
