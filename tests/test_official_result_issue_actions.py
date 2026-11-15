"""Actions issuer exercised with authored ciphertext and in-memory GitHub only."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import json
import os
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts
from tests.test_all_existing_model_official_recovery import KEY
from tests.test_official_result_issue import actual_run, BRANCH, REPO, ISSUER, PATH
from tests.test_all_existing_model_official_continuation import complete_fixture, PLAN_BYTES

try:
    from scripts import all_existing_model_official_result_issue as worker
except ImportError:
    worker=None


class MemorySnapshot:
    def __init__(self,data):
        self.target=data['target']['head_sha'];self.raw=json.dumps(data['request'],sort_keys=True).encode()
        old=open_forecasts(data['probe_capsule_raw'],key=KEY)['body']
        self.previous_raw=json.dumps(dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1',
            repository_id=1416489937,workflow_id=392270247,pull_request=71,target=old['target'],
            target_first_viewer_job_id=1001,recovery_request_sha256=digest(old['request']),
            recovery_request_blob_sha256=sha256(json.dumps(old['request'],sort_keys=True).encode()).hexdigest())).encode()
        self.previous_request_raw=json.dumps(old['request'],sort_keys=True).encode()
        self.issue=dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1',repository_id=1416489937,
            workflow_id=392270247,pull_request=71,target=data['target'],target_first_viewer_job_id=1002,
            recovery_request_sha256=digest(data['request']),recovery_request_blob_sha256=sha256(self.raw).hexdigest())
        self.facts=dict(head_sha=ISSUER,parents=[self.target],changed_files=[PATH],subject='official-results-issue: exact',
            target_subject='official-results-collect: exact',recovery_raw=self.raw,current_recovery_raw=self.raw)
    def read(self,head,path,limit):
        if path==PATH:return json.dumps(self.issue).encode() if head==ISSUER else self.previous_raw
        if path.endswith('official-result-recovery-request.json'):
            return self.raw if head in (ISSUER,self.target) else self.previous_request_raw
        return PLAN_BYTES[path]
    def previous_issue(self,head):return self.previous_raw


class MemoryGithub:
    def __init__(self,data):
        self.data=data;self.now=data['issued_at'];self.published=[];self.raw=None;self.commit='f'*40
        self.first=actual_run(data['first_attempt']);self.issuer=actual_run(dict(self.first,id=99,head_sha=ISSUER,status='in_progress',conclusion=None))
        self.pr=dict(number=71,state='open',user=dict(id=173585154,login='haji84'),head=dict(sha=ISSUER,ref=BRANCH,
            repo=dict(id=1416489937,full_name=REPO)),base=dict(ref='codex/actions-four-sport-e2e',repo=dict(id=1416489937,full_name=REPO)))
        self.archives={a['metadata']['id']:a for field in ('journal_archives','native_archives','checkpoint_archives') for a in data[field]}
        self.runs={r['id']:actual_run(r) for r in [data['old_run'],*data['prior_runs'],data['first_attempt']]}
    def json(self,path):
        if path=='pulls/71':return deepcopy(self.pr)
        if path=='actions/runs/99':return deepcopy(self.issuer)
        if path.endswith('/attempts/1/jobs?per_page=100'):
            first=self.first
            return dict(total_count=1,jobs=[dict(id=1002,run_id=first['id'],run_attempt=1,head_sha=first['head_sha'],
                name='Viewer audit contract',status='completed',conclusion='success',steps=[dict(name=name,number=i+1,
                status='completed',conclusion='success',started_at=first['run_started_at'],completed_at=first['updated_at'])
                for i,name in enumerate(('Python synthetic journal to viewer projection tests','Verify isolated experimental video decoding and measurements'))])])
        if '/artifacts?' in path:
            run=int(path.split('/')[2]);values=[a['metadata'] for a in self.archives.values() if a['metadata']['workflow_run']['id']==run]
            return dict(total_count=len(values),artifacts=deepcopy(values))
        if path.startswith('actions/artifacts/'):return deepcopy(self.archives[int(path.split('/')[2])]['metadata'])
        if path.endswith('/attempts/1'):
            run=int(path.split('/')[2]);return actual_run(self.data['probe_first_attempt'] if run==77 else self.first)
        if path.startswith('actions/runs/'):return deepcopy(self.runs[int(path.split('/')[2])])
        raise AssertionError(path)
    def archive(self,pin):return deepcopy(self.archives[pin['id']])
    def head(self):return self.commit
    def read_file(self,commit,path,limit):
        if '/77/2.enc' in path:return self.data['probe_capsule_raw']
        return self.raw
    def publish_capsule(self,path,raw,expected_parent,*,before_publish=None):
        if self.raw is not None:raise AssertionError('overwrite')
        if before_publish is not None:before_publish()
        self.published.append(path);self.raw=raw;self.commit='d'*40;return self.commit


class ActionsIssueTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(worker,'Actions-only issue wrapper must exist');return worker

    def test_local_execution_rejects_before_key_github_or_output(self):
        api=self.api();output=io.StringIO()
        with patch.dict(os.environ,{},clear=True),patch.object(api,'state_key',side_effect=AssertionError('key forbidden')), \
                patch.object(api,'GithubIssueTransport',side_effect=AssertionError('GH forbidden')),redirect_stdout(output):
            self.assertEqual(api.main(['--proof','/nonexistent/private-proof.json']),0)
        result=json.loads(output.getvalue());self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)
        self.assertNotIn('artifact_name',result)

    def fixture(self):
        data,now=complete_fixture();return deepcopy(data),now

    def test_actual_authored_continuation_is_issued_and_remote_readback_is_required(self):
        api=self.api();data,now=self.fixture();snapshot=MemorySnapshot(data);github=MemoryGithub(data)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for path,raw in PLAN_BYTES.items():
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            with patch.object(api.collector,'ROOT',root), \
                    patch.object(api.collector,'collect',side_effect=AssertionError('source collector forbidden')), \
                    patch.object(api.collector,'browser_capture',side_effect=AssertionError('browser forbidden')):
                result=api.issue_once(snapshot=snapshot,issuer_run_id=99,reader=github,writer=github,
                    readback=github,key_loader=lambda:KEY,clock=lambda:now)
        self.assertTrue(result['ready'],result);self.assertTrue(result['independent_git_readback_verified'])
        self.assertEqual(result['target'],data['target']);self.assertEqual(result['source_requests'],0)
        self.assertEqual(len(github.published),1)
        self.assertNotIn('old_plan',json.dumps(result));self.assertNotIn('journal_archives',json.dumps(result))
        self.assertEqual(result['old_source_requests_upper_bound'],32)

    def test_authenticated_later_denial_or_unknown_stops_before_publication(self):
        from tests.test_all_existing_model_official_continuation import zipped
        from race_ai.boat_all_model_store import seal_forecasts
        api=self.api()
        for change in ('denied','unknown'):
            data,now=self.fixture();item=data['journal_archives'][1]
            body=open_forecasts(api.collector._journal_cipher(item['raw']),key=KEY)
            if change=='denied':body['browser_process_diagnostic']=dict(stdout_stopped_host=True)
            else:body['browser_attempt']['state']='RESERVED'
            raw=zipped(seal_forecasts(body,run_id='77',round_no=900006,key=KEY),'collection.enc')
            item['raw']=raw;item['metadata'].update(size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
            data['request']['manifest']['prior_journal_artifacts'][1]['digest']=item['metadata']['digest']
            snapshot=MemorySnapshot(data);github=MemoryGithub(data)
            with self.subTest(change=change),self.assertRaises(ValueError):api.issue_once(snapshot=snapshot,
                issuer_run_id=99,reader=github,writer=github,readback=github,key_loader=lambda:KEY,clock=lambda:now)
            self.assertEqual(github.published,[])

    def test_remote_readback_tamper_and_target_race_never_claim_ready(self):
        api=self.api();data,now=self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for path,raw in PLAN_BYTES.items():
                target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            class TamperedReader:
                def __init__(self,github):self.github=github
                def read_file(self,commit,path,limit):
                    raw=self.github.read_file(commit,path,limit)
                    return raw[:-1]+bytes([raw[-1]^1])
            github=MemoryGithub(data)
            with patch.object(api.collector,'ROOT',root),self.assertRaises(ValueError):
                api.issue_once(snapshot=MemorySnapshot(data),issuer_run_id=99,reader=github,writer=github,
                    readback=TamperedReader(github),key_loader=lambda:KEY,clock=lambda:now)
            self.assertEqual(len(github.published),1)
            class RacedGithub(MemoryGithub):
                calls=0
                def json(self,path):
                    value=super().json(path)
                    if path=='actions/runs/88':
                        self.calls+=1
                        if self.calls>=2:value['run_attempt']=2
                    return value
            github=RacedGithub(data)
            with patch.object(api.collector,'ROOT',root),self.assertRaises(ValueError):
                api.issue_once(snapshot=MemorySnapshot(data),issuer_run_id=99,reader=github,writer=github,
                    readback=github,key_loader=lambda:KEY,clock=lambda:now)
            self.assertEqual(github.published,[])

    def test_integrated_sixteen_registry_prepares_actual_all_prior_inputs_and_remote_proof(self):
        import importlib.util
        if importlib.util.find_spec('race_ai.all_existing_model_official_probe16') is None:
            self.skipTest('committed S dependency is tested in combined integration checkout')
        from race_ai.boat_all_model_store import seal_forecasts,forecast_header
        api=self.api();data,now=self.fixture();request=data['request']
        request.update(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4',
            mode='FIXED_ATTEMPT_TWO_SINGLE_NORMAL_UI_PROBE_16')
        for key in ('probe_journal_artifact_id','probe_result_artifact_id','probe_request_sha256'):request.pop(key)
        original=PLAN_BYTES[request['manifest']['plan_path']];header=forecast_header(original)
        plan=deepcopy(data['new_plan']);plan['maximum_requests']=16
        raw=seal_forecasts(plan,run_id=header['run_id'],round_no=header['round_no'],key=KEY)
        hashed=sha256(raw).hexdigest();path='audit/state/official-result-collection-plan-'+hashed+'.enc'
        request['manifest'].update(plan_path=path,plan_sha256=hashed)
        snapshot=MemorySnapshot(data);github=MemoryGithub(data)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,body in dict(PLAN_BYTES,**{path:raw}).items():
                out=root/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(body)
            original_read=snapshot.read
            snapshot.read=lambda head,name,limit:raw if name==path else original_read(head,name,limit)
            with patch.object(api.collector,'ROOT',root):
                proof=api.issue_once(snapshot=snapshot,issuer_run_id=99,reader=github,writer=github,
                    readback=github,key_loader=lambda:KEY,clock=lambda:now)
        self.assertTrue(proof['ready']);self.assertEqual(proof['maximum_new_requests'],16)
        body=open_forecasts(github.raw,key=KEY)['body']
        self.assertEqual(len(body['prior_journal_receipts']),2)
        self.assertIsNone(body['old_source_requests_actual']);self.assertEqual(body['old_source_requests_upper_bound'],32)

    def test_no_second_signing_when_canonical_capsule_exists(self):
        api=self.api();data,now=self.fixture();snapshot=MemorySnapshot(data);github=MemoryGithub(data);github.raw=b'existing'
        with self.assertRaises(ValueError):api.issue_once(snapshot=snapshot,issuer_run_id=99,
            reader=github,writer=github,readback=github,key_loader=lambda:KEY,clock=lambda:now)
        self.assertEqual(github.published,[])

    def test_publication_callback_rechecks_real_scope_and_expiry_before_writing(self):
        api=self.api()
        for change in ('pr','expired'):
            data,now=self.fixture();clock=[now]
            class LateChange(MemoryGithub):
                callback_seen=False
                def publish_capsule(self,path,raw,expected_parent,*,before_publish=None):
                    self.callback_seen=callable(before_publish)
                    if change=='pr':self.pr['head']['sha']='c'*40
                    else:clock[0]=now+timedelta(hours=2)
                    before_publish()
                    raise AssertionError('changed permission was published')
            github=LateChange(data)
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for path,raw in PLAN_BYTES.items():
                    target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
                with self.subTest(change=change),patch.object(api.collector,'ROOT',root),self.assertRaises(ValueError):
                    api.issue_once(snapshot=MemorySnapshot(data),issuer_run_id=99,reader=github,
                        writer=github,readback=github,key_loader=lambda:KEY,clock=lambda:clock[0])
            self.assertTrue(github.callback_seen)
            self.assertEqual(github.published,[])

    def test_unconfirmed_publication_hashes_remain_a_hold_not_a_source_grant(self):
        from race_ai.all_existing_model_official_issue_transport import PublicationUnconfirmed
        api=self.api();output=io.StringIO()
        error=PublicationUnconfirmed('f'*40,'recovery/official-results/'+'1'*64+'/'+
            '2'*40+'/77/2.enc',b'synthetic-cipher','a'*40)
        with tempfile.TemporaryDirectory() as directory:
            proof=Path(directory)/'proof.json'
            with patch.dict(os.environ,{'RUNNER_TEMP':directory}), \
                    patch.object(api,'trusted_environment',return_value={'head_sha':ISSUER,'run_id':99}), \
                    patch.object(api,'GitSnapshot'),patch.object(api,'GithubIssueTransport'), \
                    patch.object(api,'issue_once',side_effect=error),redirect_stdout(output):
                self.assertEqual(api.main(['--proof',str(proof)]),0)
            result=json.loads(proof.read_bytes())
        self.assertFalse(result['ready']);self.assertEqual(result['source_requests'],0)
        self.assertFalse(result['independent_git_readback_verified'])
        self.assertEqual(result['reason'],'OFFICIAL_ISSUE_TRANSPORT_PUBLICATION_UNCONFIRMED')
        self.assertEqual(result['publication_attempt']['commit_sha'],'f'*40)
        self.assertEqual(result['publication_attempt']['state'],'UNCONFIRMED_DO_NOT_REISSUE')
        self.assertNotIn('synthetic-cipher',output.getvalue())

    def test_previous_missing_journal_or_incomplete_source_outcome_cannot_be_skipped(self):
        api=self.api()
        for change in ('missing','unknown','denied'):
            data,now=self.fixture();snapshot=MemorySnapshot(data);github=MemoryGithub(data)
            if change=='missing':github.archives.pop(90001)
            elif change=='unknown':github.runs[77]['status']='in_progress'
            else:
                # A wrong actual ZIP digest cannot impersonate an authenticated
                # completed journal, even when caller pins remain unchanged.
                github.archives[90001]['raw']=b'PK\x03\x04denied'
            with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):
                api.issue_once(snapshot=snapshot,issuer_run_id=99,reader=github,writer=github,
                    readback=github,key_loader=lambda:KEY,clock=lambda:now)
            self.assertEqual(github.published,[])

class IssuerWorkflowTests(unittest.TestCase):
    def test_only_explicit_scoped_jobs_can_write_and_issuer_routes_before_secret_step(self):
        # Check our explicit permission/step boundary without introducing a YAML
        # dependency into the existing complete Python discovery environment.
        raw=(Path(__file__).resolve().parents[1]/'.github/workflows/forecast-audit-ui.yml').read_text()
        parts=re.split(r'^  ([a-z_][a-z_0-9]*):\n',raw,flags=re.M)
        jobs=dict(zip(parts[1::2],parts[2::2]))
        self.assertTrue('official_result_recovery_issuer' in jobs,'source-free issuer job missing')
        def permissions(block,indent):
            match=re.search(r'^'+indent+r'permissions:\n((?:'+indent+r'  [^\n]+\n)+)',block,re.M)
            return {key:value for key,value in re.findall(r'^'+indent+r'  ([a-z]+): ([a-z]+)',match[1],re.M)} if match else {}
        self.assertEqual(permissions(raw,''),{'contents':'read'})
        self.assertEqual(permissions(jobs['viewer_contract'],'    '),{'contents':'read','actions':'read'})
        job=jobs['official_result_recovery_issuer']
        self.assertEqual(permissions(job,'    '),{'contents':'write','actions':'read'})
        steps=re.split(r'^      - ',job,flags=re.M)[1:]
        checkout=next(block for block in steps if re.search(r'^        uses: actions/checkout@',block,re.M))
        options=dict(re.findall(r'^          ([a-z-]+): ([^\n]+)',checkout,re.M))
        self.assertEqual(options.get('fetch-depth'),'0')
        self.assertEqual(options.get('filter'),'blob:none')
        self.assertEqual(options.get('fetch-tags'),'false')
        route=next(block for block in steps if re.search(r'^        id: issue_route$',block,re.M))
        execute=next(block for block in steps if re.search(r'^        id: issue$',block,re.M))
        self.assertLess(steps.index(route),steps.index(execute))
        self.assertIn("        if: steps.issue_route.outputs.requested == 'true' && steps.frozen_execution.outputs.ready == 'true'\n",execute)
        prepare=next(block for block in steps if re.search(r'^        id: prepare$',block,re.M))
        self.assertIn("        if: steps.issue_route.outputs.prepare_requested == 'true' && steps.frozen_execution.outputs.ready == 'true'\n",prepare)
        self.assertEqual([block for block in steps if 'RACE_AI_STATE_KEY:' in block],[execute,prepare])
        self.assertFalse(re.search(r'^  schedule:',raw,re.M))
        for name,other in jobs.items():
            if name not in ('official_result_recovery_issuer','official_future_source_capture'):
                self.assertNotEqual(permissions(other,'    ').get('contents'),'write')


class IssuerHistoryTests(unittest.TestCase):
    def test_collect_commit_cannot_replace_latest_issue_marker_with_stale_bytes(self):
        import subprocess
        api=worker;self.assertIsNotNone(api)
        from tests.test_official_result_issue import fixture
        data,_,_=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def git(*args):
                result=subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid',*args],
                    cwd=root,capture_output=True,check=True)
                return result.stdout.decode().strip()
            git('init','-q')
            source=root/'audit/state/official-result-recovery-request.json';source.parent.mkdir(parents=True)
            source.write_text(json.dumps(data['request'],sort_keys=True));git('add','.');git('commit','-qm','official-results-collect: initial')
            initial=git('rev-parse','HEAD')
            def marker(target,run):
                return dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1',repository_id=1416489937,
                    workflow_id=392270247,pull_request=71,target=dict(head_sha=target,run_id=run,run_attempt=2),
                    target_first_viewer_job_id=1001,recovery_request_sha256=digest(data['request']),
                    recovery_request_blob_sha256=sha256(source.read_bytes()).hexdigest())
            path=root/PATH;previous=marker(initial,77);path.write_text(json.dumps(previous));git('add','.');git('commit','-qm','official-results-issue: first')
            (root/'source-note.txt').write_text('new source request\n');git('add','.');git('commit','-qm','official-results-collect: next')
            target=git('rev-parse','HEAD');path.write_text(json.dumps(marker(target,88)));git('add','.');git('commit','-qm','official-results-issue: next')
            head=git('rev-parse','HEAD');snapshot=api.GitSnapshot(root,head)
            self.assertEqual(json.loads(snapshot.previous_issue(target)),previous)
            # A collect commit now rewrites the marker to an older valid target.
            path.write_text(json.dumps(previous));git('add','.');git('commit','-qm','official-results-collect: malicious marker reset')
            bad_target=git('rev-parse','HEAD');path.write_text(json.dumps(marker(bad_target,99)));git('add','.');git('commit','-qm','official-results-issue: cannot skip epoch')
            bad=api.GitSnapshot(root,git('rev-parse','HEAD'))
            with self.assertRaises(ValueError):bad.previous_issue(bad_target)
