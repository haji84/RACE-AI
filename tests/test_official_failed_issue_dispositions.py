"""Authored GitHub proof ZIPs; no keys, source requests or remote mutations."""
from copy import deepcopy
from hashlib import sha256
from datetime import timedelta
import io
import json
import unittest
import zipfile
from unittest.mock import patch


def packed_proof(value):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        info=zipfile.ZipInfo('official-result-recovery-issue-proof.json',date_time=(2030,1,1,0,0,0))
        archive.writestr(info,json.dumps(value,sort_keys=True).encode())
    return stream.getvalue()

from tests.test_official_result_issue import context,actual_run
from tests.test_official_issue_frozen_v2 import frozen_context


def fixture():
    from race_ai import all_existing_model_official_issue as I
    old,ctx,data=context();head='e'*40;raw=json.dumps(old,sort_keys=True).encode()
    current,_,_=frozen_context();current['failed_issue_dispositions']=[dict(intent_head_sha=head,issue_blob_sha256=sha256(raw).hexdigest())]
    recovery=ctx['snapshot']['recovery_raw'];target=deepcopy(ctx['target_run']);now=ctx['now']
    run=actual_run(dict(ctx['issuer_run'],head_sha=head,status='completed',conclusion='success'))
    proof=dict(schema=I.PROOF,state='HOLD_FIXED_RECOVERY_ISSUANCE',ready=False,source_requests=0,
        independent_git_readback_verified=False,plaintext_published=False,production_promoted=False,actual_purchases=False,
        reason='OFFICIAL_ISSUE_CURRENT_PR')
    packed=packed_proof(proof);meta=dict(id=600,name=f'official-result-recovery-issue-proof-{run["id"]}-1',expired=False,
        digest='sha256:'+sha256(packed).hexdigest(),size_in_bytes=len(packed),created_at=now.isoformat(),
        expires_at=(now+timedelta(days=7)).isoformat(),workflow_run=dict(id=run['id'],head_sha=head,
        repository_id=I.REPOSITORY_ID,head_repository_id=I.REPOSITORY_ID))
    class Snapshot:
        facts=dict(head_sha='b'*40)
        def read(self,selected,path,limit):return raw if path==I.ISSUE_PATH else recovery
        def commit_facts(self,selected):return dict(head_sha=selected,parents=[old['target']['head_sha']],
            changed_files=[I.ISSUE_PATH],subject=I.PREFIX+' failed')
        def issue_history(self,selected):return [head]
        def is_ancestor(self,*_):return True
    class Reader:
        def __init__(self):
            self.target=deepcopy(target);self.head_value='1'*40;self.cap=None;self.ready=deepcopy(proof);self.job_done=True
            self.overrides={};self.calls=[];self.archive_override=None
        def metadata(self):
            body=packed_proof(self.ready)
            return dict(deepcopy(meta),digest='sha256:'+sha256(body).hexdigest(),size_in_bytes=len(body))
        def json(self,path):
            self.calls.append(path)
            if path in self.overrides:return deepcopy(self.overrides[path])
            if path.startswith('actions/workflows/'):return dict(total_count=1,workflow_runs=[deepcopy(run)])
            if path.endswith('/attempts/1/jobs?per_page=100'):
                return dict(total_count=1,jobs=[dict(id=501,run_id=run['id'],run_attempt=1,head_sha=head,
                    name='Source-free exact-run recovery issuer',status='completed' if self.job_done else 'in_progress',conclusion='success')])
            if '/artifacts?' in path:return dict(total_count=1,artifacts=[self.metadata()])
            if path.startswith('actions/artifacts/'):return self.metadata()
            if path.endswith('/attempts/1'):return deepcopy(target)
            if path.startswith('actions/runs/'):return deepcopy(self.target)
            raise AssertionError(path)
        def archive(self,pin):
            if self.archive_override is not None:return deepcopy(self.archive_override)
            return dict(raw=packed_proof(self.ready),metadata=self.metadata())
        def head(self):return self.head_value
        def read_file(self,*_):return self.cap
    return current,Snapshot(),Reader(),now


def published_fixture():
    from race_ai import all_existing_model_official_failed_issue as api
    from race_ai import all_existing_model_official_issue as I
    from race_ai.actions_contract import digest
    issue,snapshot,reader,now=fixture()
    recovery=snapshot.read(issue['target']['head_sha'],I.REQUEST_PATH,32768)
    issue['recovery_request_blob_sha256']=sha256(recovery).hexdigest()
    issue['recovery_request_sha256']=digest(json.loads(recovery))
    before=api.verify_failed_dispositions(snapshot,issue,reader,now=now)
    source='b'*40;raw=json.dumps(issue,sort_keys=True).encode();read=snapshot.read;facts=snapshot.commit_facts
    binding=dict(schema='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1',tested_execution_head_sha=issue['target']['head_sha'],
        intent_head_sha=source,intent_parent_sha=issue['intent_parent_sha'],target=deepcopy(issue['target']),
        issue_request_blob_sha256=sha256(raw).hexdigest(),recovery_request_blob_sha256=issue['recovery_request_blob_sha256'],
        protected_files_sha256='2'*64)
    snapshot.facts=dict(head_sha=source,source_issue_head=source,source_frozen_binding=binding)
    snapshot.read=lambda h,p,l:raw if h==source and p==I.ISSUE_PATH else read(h,p,l)
    snapshot.commit_facts=lambda h:dict(head_sha=source,parents=[issue['intent_parent_sha']],changed_files=[I.ISSUE_PATH],subject=I.PREFIX+' current') if h==source else facts(h)
    reader.target.update(run_attempt=2,status='in_progress',conclusion=None)
    reader.cap=b'opaque authenticated current-C2 outer bytes, authenticated later with the owner key'
    _,ctx,_=context();active_run=actual_run(dict(ctx['issuer_run'],id=99,head_sha=source,status='completed',conclusion='success'))
    ready=dict(schema=I.PROOF_V2,state='CONSUMED_CAPSULE_PUBLISHED_AND_READ_BACK',ready=True,
        repository_id=I.REPOSITORY_ID,workflow_id=I.WORKFLOW,pull_request=71,issuer_run_id=99,issuer_run_attempt=1,
        issuer_head_sha=source,issuer_actor_id=I.OWNER_ID,tested_execution_head_sha=issue['target']['head_sha'],
        issue_request_sha256=digest(issue),recovery_request_sha256=issue['recovery_request_sha256'],target=deepcopy(issue['target']),
        target_first_viewer_job_id=issue['target_first_viewer_job_id'],independent_git_readback_verified=True,
        source_requests=0,plaintext_published=False,production_promoted=False,actual_purchases=False,
        outer_capsule_sha256=sha256(reader.cap).hexdigest(),inner_capsule_sha256='3'*64,
        source_frozen_binding_sha256=digest(binding),failed_issue_dispositions=deepcopy(before['failed_issues']),
        failed_issue_dispositions_sha256=digest(before['failed_issues']),verified_failed_issue_count=1)
    class PublishedReader:
        def __init__(self):self.proof=ready;self.old=reader;self.run=active_run;self.cap=reader.cap;self.job_done=True
        def meta(self):
            body=packed_proof(self.proof)
            return dict(id=699,name='official-result-recovery-issue-proof-99-1',expired=False,digest='sha256:'+sha256(body).hexdigest(),
                size_in_bytes=len(body),created_at=now.isoformat(),expires_at=(now+timedelta(days=7)).isoformat(),
                workflow_run=dict(id=99,head_sha=source,repository_id=I.REPOSITORY_ID,head_repository_id=I.REPOSITORY_ID))
        def json(self,path):
            if path=='actions/workflows/392270247/runs?head_sha='+source+'&event=pull_request&per_page=100':
                return dict(total_count=1,workflow_runs=[deepcopy(self.run)])
            if path=='actions/runs/99/attempts/1/jobs?per_page=100':
                return dict(total_count=1,jobs=[dict(id=599,run_id=99,run_attempt=1,head_sha=source,
                    name='Source-free exact-run recovery issuer',status='completed' if self.job_done else 'in_progress',conclusion='success')])
            if path=='actions/runs/99/artifacts?per_page=100':return dict(total_count=1,artifacts=[self.meta()])
            return self.old.json(path)
        def archive(self,pin):
            return dict(raw=packed_proof(self.proof),metadata=self.meta()) if pin['id']==699 else self.old.archive(pin)
        def head(self):return self.old.head()
        def read_file(self,*_):return self.cap
    return issue,snapshot,PublishedReader(),now,before


class FailedIssueDispositionTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('race_ai.all_existing_model_official_failed_issue'),'failed-anchor verifier module is missing')
        from race_ai import all_existing_model_official_failed_issue as worker
        api=getattr(worker,'verify_failed_dispositions',None)
        self.assertTrue(callable(api),'explicit failed-anchor verification is missing')
        return api

    def test_unused_baseline_anchor_is_retained_and_unrelated_state_append_is_stable(self):
        api=self.api();issue,snapshot,reader,now=fixture()
        first=api(snapshot,issue,reader,now=now)
        self.assertEqual(first['verified_failed_issue_count'],1)
        reader.head_value='2'*40
        self.assertEqual(api(snapshot,issue,reader,now=now),first)

    def test_actual_second_attempt_live_cap_or_missing_terminal_proof_never_counts_as_failed(self):
        api=self.api()
        for change in ('attempt2','cap','running','ready','source'):
            issue,snapshot,reader,now=fixture()
            if change=='attempt2':reader.target['run_attempt']=2
            elif change=='cap':reader.cap=b'unknown existing capability'
            elif change=='running':reader.job_done=False
            elif change=='ready':reader.ready['ready']=True
            else:reader.ready['source_requests']=1
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now)


    def test_no_failed_descriptors_needs_no_transport_or_key(self):
        api=self.api();issue,snapshot,reader,now=fixture();issue['failed_issue_dispositions']=[]
        reader.json=lambda *_:self.fail('no failed anchors must query no transport')
        self.assertEqual(api(snapshot,issue,reader,now=now),dict(schema='RACE_AI_OFFICIAL_FAILED_ISSUE_DISPOSITIONS_V1',verified_failed_issue_count=0,failed_issues=[]))

    def test_history_raw_parent_or_recovery_mismatch_holds_before_transport(self):
        api=self.api()
        for change in ('history','issue_raw','parent','files','prefix','request'):
            issue,snapshot,reader,now=fixture();read=snapshot.read;facts=snapshot.commit_facts
            if change=='history':snapshot.issue_history=lambda *_:[]
            elif change=='issue_raw':issue['failed_issue_dispositions'][0]['issue_blob_sha256']='0'*64
            elif change=='request':snapshot.read=lambda h,p,l:read(h,p,l)+b' ' if p.endswith('recovery-request.json') else read(h,p,l)
            else:
                def changed(h):
                    out=facts(h)
                    if change=='parent':out['parents']=['f'*40]
                    elif change=='files':out['changed_files'].append('unreviewed.py')
                    else:out['subject']='unreviewed'
                    return out
                snapshot.commit_facts=changed
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now)
            self.assertEqual(reader.calls,[])

    def test_actual_owner_workflow_list_and_jobs_must_be_complete_and_bound(self):
        api=self.api()
        for change in ('run_count','run_missing','run_owner','run_attempt','job_count','job_head','job_id','job_failure'):
            issue,snapshot,reader,now=fixture()
            route='actions/workflows/392270247/runs?head_sha='+'e'*40+'&event=pull_request&per_page=100'
            if change.startswith('run'):
                value=reader.json(route)
                if change=='run_count':value['total_count']=101
                elif change=='run_missing':value=dict(total_count=0,workflow_runs=[])
                elif change=='run_owner':value['workflow_runs'][0]['actor']['id']=1
                else:value['workflow_runs'][0]['run_attempt']=2
            else:
                route='actions/runs/88/attempts/1/jobs?per_page=100';value=reader.json(route)
                if change=='job_count':value['total_count']=2
                elif change=='job_head':value['jobs'][0]['head_sha']='f'*40
                elif change=='job_id':value['jobs'][0]['id']=True
                else:value['jobs'][0]['conclusion']='failure'
            reader.overrides[route]=value
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now)

    def test_proof_safe_fields_are_strict_and_publication_uncertainty_is_not_zero(self):
        api=self.api()
        changes=[{'source_requests':False},{'source_requests':1},{'plaintext_published':0},
                 {'actual_purchases':True},{'production_promoted':True},{'ready':True},
                 {'independent_git_readback_verified':True},{'state':'other'},{'schema':'other'},
                 {'reason':'unsafe private detail'},{'publication_attempt':{'state':'UNCONFIRMED_DO_NOT_REISSUE'}},
                 {'reason':'OFFICIAL_ISSUE_TRANSPORT_PUBLICATION_UNCONFIRMED'}]
        for change in changes:
            issue,snapshot,reader,now=fixture();reader.ready.update(change)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'ZERO_SOURCE|EXPLICIT_UNUSED'):
                api(snapshot,issue,reader,now=now)

    def test_proof_actual_metadata_zip_and_receipt_must_match(self):
        api=self.api()
        for change in ('expired','clock','head','digest','size','archive_raw','archive_meta','missing','duplicate'):
            issue,snapshot,reader,now=fixture();route='actions/runs/88/artifacts?per_page=100'
            value=reader.json(route);meta=value['artifacts'][0]
            if change=='expired':meta['expired']=True
            elif change=='clock':meta['created_at']=(now+timedelta(seconds=1)).isoformat()
            elif change=='head':meta['workflow_run']['head_sha']='f'*40
            elif change=='digest':meta['digest']='sha256:'+'f'*64
            elif change=='size':meta['size_in_bytes']=1
            elif change=='archive_raw':reader.archive_override=dict(raw=b'other',metadata=deepcopy(meta))
            elif change=='archive_meta':reader.archive_override=dict(raw=packed_proof(reader.ready),metadata=dict(meta,id=601))
            elif change=='missing':value=dict(total_count=0,artifacts=[])
            else:value=dict(total_count=2,artifacts=[meta,dict(meta,id=601)])
            reader.overrides[route]=value
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now)

    def test_published_same_target_uses_current_ready_proof_and_preserves_exact_failed_summary(self):
        api=self.api();issue,snapshot,reader,now,before=published_fixture()
        self.assertEqual(api(snapshot,issue,reader,now=now,published=True),before)
        reader.old.head_value='2'*40
        self.assertEqual(api(snapshot,issue,reader,now=now,published=True),before)
        with self.assertRaises(ValueError):api(snapshot,issue,reader,now=now)

    def test_published_same_target_rejects_stale_cap_binding_or_changed_ready_disposition(self):
        api=self.api()
        for change in ('cap','issuer','binding','issue','hash','failed','count','ready','source','job','run','attempt','privacy'):
            issue,snapshot,reader,now,_=published_fixture()
            if change=='cap':reader.cap+=b'x'
            elif change=='issuer':reader.proof['issuer_head_sha']='f'*40
            elif change=='binding':reader.proof['source_frozen_binding_sha256']='f'*64
            elif change=='issue':reader.proof['issue_request_sha256']='f'*64
            elif change=='hash':reader.proof['failed_issue_dispositions_sha256']='f'*64
            elif change=='failed':reader.proof['failed_issue_dispositions'][0]['issue_blob_sha256']='f'*64
            elif change=='count':reader.proof['verified_failed_issue_count']=True
            elif change=='ready':reader.proof['ready']=False
            elif change=='source':reader.proof['source_requests']=False
            elif change=='job':reader.job_done=False
            elif change=='run':reader.run['actor']['id']=1
            elif change=='attempt':reader.old.target['run_attempt']=3
            else:reader.proof['plaintext_published']=True
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now,published=True)

    def test_published_other_failed_target_still_requires_fresh_first_only_absence(self):
        api=self.api();issue,snapshot,reader,now=fixture()
        issue['target']=dict(head_sha='f'*40,run_id=99,run_attempt=2);issue['tested_execution_head_sha']='f'*40
        expected=api(snapshot,issue,reader,now=now)
        self.assertEqual(api(snapshot,issue,reader,now=now,published=True),expected)
        reader.target['run_attempt']=2
        with self.assertRaises(ValueError):api(snapshot,issue,reader,now=now,published=True)
        reader.target['run_attempt']=1;reader.cap=b'old unknown capability'
        with self.assertRaises(ValueError):api(snapshot,issue,reader,now=now,published=True)

    def test_published_producer_summary_cannot_replace_old_fresh_receipts(self):
        from race_ai.actions_contract import digest
        api=self.api()
        for change in ('first','proof','extra','bool','new_issuer'):
            issue,snapshot,reader,now,_=published_fixture()
            rows=reader.proof['failed_issue_dispositions']
            if change=='first':rows[0]['target_first_attempt']['updated_at']=(now-timedelta(seconds=2)).isoformat()
            elif change=='proof':rows[0]['issuer_proofs'][0]['proof_sha256']='f'*64
            elif change=='extra':rows[0]['unexpected']=1
            elif change=='bool':rows[0]['target_first_attempt']['run_attempt']=True
            else:
                route='actions/workflows/392270247/runs?head_sha='+'e'*40+'&event=pull_request&per_page=100'
                runs=reader.old.json(route);runs['workflow_runs'].append(dict(runs['workflow_runs'][0],id=89));runs['total_count']=2
                reader.old.overrides[route]=runs
            reader.proof['failed_issue_dispositions_sha256']=digest(rows)
            with self.subTest(change=change),self.assertRaises(ValueError):api(snapshot,issue,reader,now=now,published=True)

    def test_published_binding_parent_must_equal_actual_current_issue_parent(self):
        from race_ai.actions_contract import digest
        api=self.api();issue,snapshot,reader,now,_=published_fixture()
        snapshot.facts['source_frozen_binding']['intent_parent_sha']='f'*40
        reader.proof['source_frozen_binding_sha256']=digest(snapshot.facts['source_frozen_binding'])
        with self.assertRaises(ValueError):api(snapshot,issue,reader,now=now,published=True)

    def test_readonly_transport_admits_only_literal_complete_workflow_run_list(self):
        from race_ai.all_existing_model_official_issue_transport import _route
        good='actions/workflows/392270247/runs?head_sha='+'e'*40+'&event=pull_request&per_page=100'
        _route('GET',good)
        for bad in (good.replace('392270247','1'),good.replace('pull_request','push'),good+'&page=2',good.replace('e'*40,'x'*40)):
            with self.subTest(bad=bad),self.assertRaises(ValueError):_route('GET',bad)
        with self.assertRaises(ValueError):_route('POST',good)


if __name__=='__main__':unittest.main()
