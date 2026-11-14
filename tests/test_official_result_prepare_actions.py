"""Preparation transport/output guards; fixture keys only, no service calls."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
import io,json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import seal_forecasts,open_forecasts
from tests.test_all_existing_model_official_recovery import KEY
from tests.test_official_result_prepare import context,plans,DAY

try:
    from scripts import all_existing_model_official_result_prepare as worker
except ImportError:
    worker=None


class PreparationActionsTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(worker,'source-free preparation CLI must exist');return worker

    def test_local_execution_rejects_before_secret_transport_or_output(self):
        api=self.api();out=io.StringIO()
        with patch.dict(os.environ,{},clear=True),patch.object(api,'state_key',side_effect=AssertionError('NO_KEY')),\
             patch.object(api,'ReadOnlyGithub',side_effect=AssertionError('NO_GITHUB')),redirect_stdout(out):
            self.assertEqual(api.main(['--out-dir','/unavailable/private-plan']),0)
        result=json.loads(out.getvalue());self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)

    def test_read_only_transport_has_no_publication_or_request_writer_interface(self):
        api=self.api();base=Mock();reader=api.ReadOnlyGithub(base)
        self.assertFalse(hasattr(reader,'publish_capsule'));self.assertFalse(hasattr(reader,'_call'))
        reader.json('pulls/71');base.json.assert_called_once_with('pulls/71')
        reader.archive(dict(id=42));base.archive.assert_called_once_with(dict(id=42))
        reader.head();reader.read_file('a'*40,'path',10)
        base.head.assert_called_once();base.read_file.assert_called_once_with('a'*40,'path',10)

    def test_real_crypto_cli_prepares_from_read_only_memory_github_without_publication(self):
        self._real_crypto_preparation()

    def _real_crypto_preparation(self,reuse_code=False):
        """Transport/topology are authored; MAC/native/RESULT/AES are real."""
        from datetime import timedelta
        from tests.official_result_prepare_fixtures import single_fixture
        from tests.test_official_result_issue import actual_run,BRANCH,REPO
        from tests.test_official_recovery_preflight import jobs
        api=self.api();value,data,_,now=single_fixture();source=value['previous_source'];parent=value['verified_parent']
        if reuse_code:
            parent=dict(head_sha=source['head_sha'],run_id=source['run_id'],run_attempt=1,first_viewer_job_id=source['first_viewer_job_id'])
            value.pop('verified_parent');value.update(schema=api.P.SCHEMA_V2,verified_code_ancestor=parent)
        raw=api.collector.future.wire(data['source_request'])
        previous=dict(schema=api.I.SCHEMA,repository_id=api.I.REPOSITORY_ID,workflow_id=api.I.WORKFLOW,pull_request=71,
            target={k:source[k] for k in ('head_sha','run_id','run_attempt')},target_first_viewer_job_id=source['first_viewer_job_id'],
            recovery_request_sha256=source['recovery_request_sha256'],recovery_request_blob_sha256=source['recovery_request_blob_sha256'])
        facts=dict(head_sha='8'*40,parents=[parent['head_sha']],changed_files=[api.P.PATH],
            subject='official-results-prepare: authored exact parent',source_is_ancestor=True,
            recovery_raw=raw,current_recovery_raw=raw,latest_issue_raw=api.collector.future.wire(previous))
        if reuse_code:
            facts.update(parents=['9'*40],tested_workflow_blob='b'*40,
                issuer_parent=dict(head_sha='9'*40,parents=[source['head_sha']],changed_files=[api.I.ISSUE_PATH],
                    subject='official-results-issue: authored C',issue_raw=facts['latest_issue_raw']),
                data_only_changes=[dict(path=api.I.ISSUE_PATH,old_mode='100644',new_mode='100644',status='M'),
                    dict(path=api.P.PATH,old_mode='000000',new_mode='100644',status='A')])
        plans_by_path={data['source_request']['manifest']['plan_path']:data['source_plan_raw']}
        old_body=open_forecasts(api.collector._journal_cipher(next(a for a in data['groups']['prior_journal_artifacts']
            if a['metadata']['id']==api.R.OLD_ARTIFACT)['raw']),key=KEY)
        plans_by_path[old_body['manifest']['plan_path']]=data['old_plan_raw']
        class Snapshot:
            def __init__(self):self.facts=facts
            def prepare_facts(self,_):return deepcopy(facts)
            def read(self,head,path,limit):return api.collector.future.wire(value) if path==api.P.PATH else plans_by_path[path]
        firsts={source['run_id']:data['source_first_attempt']}
        firsts[data['probe_first_attempt']['id']]=data['probe_first_attempt']
        if not reuse_code:
            firsts[parent['run_id']]=actual_run(dict(data['source_first_attempt'],id=parent['run_id'],head_sha=parent['head_sha'],
                run_attempt=1,updated_at=(now-timedelta(seconds=5)).isoformat()))
        runs={r['id']:r for r in (data['old_run'],*data['prior_runs'])}
        if not reuse_code:runs[parent['run_id']]=firsts[parent['run_id']]
        runs[501]=actual_run(dict(firsts[parent['run_id']],id=501,head_sha='8'*40,status='in_progress',conclusion=None))
        archives={a['metadata']['id']:a for rows in data['groups'].values() for a in rows}
        class Reader:
            def __init__(self):self.calls=[]
            def json(self,path):
                self.calls.append(path)
                if path=='git/commits/'+'e'*40:return dict(sha='e'*40,parents=[dict(sha='8'*40)],tree=dict(sha='1'*40))
                if path.startswith('git/trees/'):
                    index=['1'*40,'2'*40,'3'*40].index(path.rsplit('/',1)[1]);last=index==2
                    return dict(sha=path.rsplit('/',1)[1],truncated=False,tree=[dict(
                        path=['.github','workflows','forecast-audit-ui.yml'][index],mode='100644' if last else '040000',
                        type='blob' if last else 'tree',sha='b'*40 if last else ['2'*40,'3'*40][index],
                        **({'size':123} if last else {}))])
                if path=='pulls/71':return dict(number=71,state='open',user=dict(id=173585154,login='haji84'),
                    head=dict(sha='8'*40,ref=BRANCH,repo=dict(id=1416489937,full_name=REPO)),
                    base=dict(ref='codex/actions-four-sport-e2e',repo=dict(id=1416489937,full_name=REPO)))
                if '/artifacts?' in path:
                    values=[a['metadata'] for a in archives.values() if a['metadata']['workflow_run']['id']==source['run_id']]
                    return dict(total_count=len(values),artifacts=deepcopy(values))
                if path.startswith('actions/artifacts/'):return deepcopy(archives[int(path.split('/')[2])]['metadata'])
                ident=int(path.split('/')[2])
                if path.endswith('/attempts/1'):return deepcopy(firsts[ident])
                if path.endswith('/attempts/1/jobs?per_page=100'):
                    result=jobs(firsts[ident]);result['jobs'][0]['id']=parent['first_viewer_job_id'] if ident==parent['run_id'] else source['first_viewer_job_id']
                    return result
                return deepcopy(runs[ident])
            def archive(self,pin):return deepcopy(archives[pin['id']])
            def head(self):return 'f'*40
            def read_file(self,commit,path,limit):
                return data['source_capsule_raw'] if path.endswith('/'+str(source['run_id'])+'/2.enc') else data['probe_capsule_raw']
        reader=Reader();key=Mock(return_value=KEY)
        with patch.dict(os.environ,dict(GITHUB_SHA='e'*40,GITHUB_WORKFLOW_SHA='e'*40)):
            result=api.prepare_once(snapshot=Snapshot(),prepare_run_id=501,reader=reader,key_loader=key,clock=lambda:now)
        self.assertTrue(result['counts']['ready']);self.assertEqual(result['counts']['source_requests'],0)
        self.assertEqual(result['counts']['grants_issued'],0);key.assert_called_once()
        if reuse_code:
            self.assertEqual(result['counts']['schema'],api.P.COUNTS_V2)
            self.assertTrue(result['counts']['reused_code_ancestor']);self.assertFalse(result['counts']['parent_whole_first_verified'])
            self.assertNotIn('verified_parent',result['counts'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'prepared';api.write_outputs(root,result)
            self.assertEqual({p.name for p in root.iterdir()},{'sealedplan.enc','request.json','counts.json'})

    def test_prepare_snapshot_reads_only_regular_committed_intent_bytes(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def git(*args):
                return subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                    '-c','commit.gpgsign=false',*args],cwd=root,capture_output=True,check=True).stdout.decode().strip()
            git('init','-q');file=root/api.I.REQUEST_PATH;file.parent.mkdir(parents=True);file.write_bytes(b'{}')
            git('add','.');git('commit','-qm','ordinary verified code parent')
            intent=root/api.P.PATH;intent.write_bytes(b'{"fixture":"intent"}\n');git('add','.');git('commit','-qm','official-results-prepare: authored')
            head=git('rev-parse','HEAD');snapshot=api.PrepareSnapshot(root,head)
            self.assertEqual(snapshot.read(head,api.P.PATH,32768),intent.read_bytes())

    def test_unverified_code_parent_cannot_reach_owner_key_loader(self):
        api=self.api();request,ctx,_=context();ctx['parent_current']['status']='in_progress'
        snapshot=Mock();snapshot.facts=ctx['snapshot'];snapshot.read.return_value=json.dumps(request).encode()
        snapshot.prepare_facts.return_value=ctx['snapshot']
        source=request['previous_source'];parent=request['verified_parent']
        values={'actions/runs/99':ctx['prepare_run'],'pulls/71':ctx['current_pr'],
            f"actions/runs/{parent['run_id']}":ctx['parent_current'],f"actions/runs/{parent['run_id']}/attempts/1":ctx['parent_first'],
            f"actions/runs/{parent['run_id']}/attempts/1/jobs?per_page=100":ctx['parent_jobs'],
            f"actions/runs/{source['run_id']}":ctx['source_current'],f"actions/runs/{source['run_id']}/attempts/1":ctx['source_first'],
            f"actions/runs/{source['run_id']}/attempts/1/jobs?per_page=100":ctx['source_jobs']}
        reader=Mock();reader.json.side_effect=lambda path:deepcopy(values[path]);key=Mock(side_effect=AssertionError('NO_KEY'))
        with self.assertRaisesRegex(ValueError,'FULL_PARENT_OR_SOURCE'):
            api.prepare_once(snapshot=snapshot,prepare_run_id=99,reader=reader,key_loader=key,clock=lambda:DAY)
        key.assert_not_called();reader.archive.assert_not_called()

    def test_exact_three_files_and_no_extra_plaintext_are_written(self):
        api=self.api();value,_,source=context();old,journal=plans();plan=api.P.derive_plan(api.P.SINGLE,old,journal)
        cipher=seal_forecasts(plan,run_id='99',round_no=api.P.ROUND,key=KEY)
        request=api.P.build_recovery_request(value,source,plan_sha256=sha256(cipher).hexdigest(),now=DAY)
        counts=dict(schema=api.P.COUNTS,ready=True,plan_cipher_sha256=sha256(cipher).hexdigest(),
            recovery_request_sha256=digest(request),prepare_run_id=99,prepared_at=DAY.isoformat())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'out';api.write_outputs(root,dict(plan_cipher=cipher,request=request,counts=counts))
            self.assertEqual({p.name for p in root.iterdir()},{'sealedplan.enc','request.json','counts.json'})
            self.assertTrue(all(p.stat().st_mode&0o777==0o600 for p in root.iterdir()))
            self.assertEqual(open_forecasts((root/'sealedplan.enc').read_bytes(),key=KEY),plan)
            with self.assertRaises(ValueError):api.write_outputs(root,dict(plan_cipher=cipher,request=request,counts=counts))
            bad=dict(plan_cipher=cipher,request=request,counts=counts,raw_source=b'FORBIDDEN')
            with self.assertRaises(ValueError):api.write_outputs(Path(directory)/'bad',bad)

    def test_output_path_rejects_checkout_relative_symlink_and_existing_directory(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as directory:
            temp=Path(directory);env=dict(temp=temp)
            for path in (Path('relative'),temp,temp/'../escape'):
                with self.subTest(path=path),self.assertRaises(ValueError):api.output_root(path,env)
            (temp/'used').mkdir()
            with self.assertRaises(ValueError):api.output_root(temp/'used',env)
            (temp/'link').symlink_to(temp/'used',target_is_directory=True)
            with self.assertRaises(ValueError):api.output_root(temp/'link/out',env)

    def test_partial_write_retains_cipher_but_has_no_ready_proof(self):
        """Post-admission staging only; source crypto is exercised separately."""
        api=self.api();value,_,source=context();old,journal=plans();plan=api.P.derive_plan(api.P.SINGLE,old,journal)
        cipher=seal_forecasts(plan,run_id='99',round_no=api.P.ROUND,key=KEY)
        request=api.P.build_recovery_request(value,source,plan_sha256=sha256(cipher).hexdigest(),now=DAY)
        outcome=dict(plan_cipher=cipher,request=request,counts=dict(schema=api.P.COUNTS,ready=True,
            plan_cipher_sha256=sha256(cipher).hexdigest(),recovery_request_sha256=digest(request),
            prepare_run_id=99,prepared_at=DAY.isoformat()))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'out';snapshot=Mock();snapshot.read.return_value=b'{}';actual_write=api._write
            def write(path,raw):
                if path.name=='request.json':raise OSError('AUTHORED_DISK_FAILURE')
                return actual_write(path,raw)
            with patch.dict(os.environ,RUNNER_TEMP=directory),patch.object(api.issue,'trusted_environment',
                    return_value=dict(run_id=99,head_sha='b'*40)),patch.object(api,'PrepareSnapshot',return_value=snapshot),\
                 patch.object(api,'_read',return_value=b'{}'),patch.object(api,'ReadOnlyGithub'),\
                 patch.object(api,'prepare_once',return_value=outcome),patch.object(api,'_write',side_effect=write),redirect_stdout(io.StringIO()):
                api.main(['--out-dir',str(out)])
            self.assertTrue((out/'sealedplan.enc').is_file())
            self.assertFalse(json.loads((out/'counts.json').read_bytes())['ready'])

    def test_failure_after_ready_counts_write_atomically_invalidates_artifact_proof(self):
        """A post-write fsync/close error cannot leave an apparently ready ZIP."""
        api=self.api();value,_,source=context();old,journal=plans();plan=api.P.derive_plan(api.P.SINGLE,old,journal)
        cipher=seal_forecasts(plan,run_id='99',round_no=api.P.ROUND,key=KEY)
        request=api.P.build_recovery_request(value,source,plan_sha256=sha256(cipher).hexdigest(),now=DAY)
        outcome=dict(plan_cipher=cipher,request=request,counts=dict(schema=api.P.COUNTS,ready=True,
            plan_cipher_sha256=sha256(cipher).hexdigest(),recovery_request_sha256=digest(request),
            prepare_run_id=99,prepared_at=DAY.isoformat()))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'out';snapshot=Mock();snapshot.read.return_value=b'{}';actual_write=api._write
            def write(path,raw):
                actual_write(path,raw)
                if path.name=='counts.json':raise OSError('AUTHORED_POST_WRITE_FAILURE')
            with patch.dict(os.environ,RUNNER_TEMP=directory),patch.object(api.issue,'trusted_environment',
                    return_value=dict(run_id=99,head_sha='b'*40)),patch.object(api,'PrepareSnapshot',return_value=snapshot),\
                 patch.object(api,'_read',return_value=b'{}'),patch.object(api,'ReadOnlyGithub'),\
                 patch.object(api,'prepare_once',return_value=outcome),patch.object(api,'_write',side_effect=write),redirect_stdout(io.StringIO()):
                api.main(['--out-dir',str(out)])
            self.assertFalse(json.loads((out/'counts.json').read_bytes())['ready'])

    def test_secondary_hold_write_failure_removes_ready_proof_and_unsafe_file_is_rejected(self):
        api=self.api()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'counts.json';file.write_text('{"ready":true}');file.chmod(0o600)
            with patch.object(api,'save',side_effect=OSError('AUTHORED_DISK_FAILURE')),self.assertRaises(OSError):
                api.hold_counts(root,dict(ready=False))
            self.assertFalse(file.exists())
            file.write_text('{"ready":true}');file.chmod(0o644)
            with patch.object(api,'save') as write,self.assertRaisesRegex(ValueError,'PRIVATE_COUNTS_FILE'):
                api.hold_counts(root,dict(ready=False))
            write.assert_not_called();file.unlink()
            target=root/'untouched';target.write_text('AUTHORED_DO_NOT_READ');file.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'PRIVATE_COUNTS_FILE'):api.hold_counts(root,dict(ready=False))
            self.assertEqual(target.read_text(),'AUTHORED_DO_NOT_READ')


if __name__=='__main__':unittest.main()
