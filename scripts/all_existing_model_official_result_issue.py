"""Actions-only source-free issuer of one consumed exact-run recovery capsule.

No provider, browser, workflow dispatch or rerun API exists here. The existing
App reads the safe proof and separately decides whether to rerun the exact job.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess

from race_ai import all_existing_model_official_issue as I
from race_ai import all_existing_model_official_recovery as R
from race_ai import all_existing_model_official_continuation as C
from race_ai.actions_contract import digest
from race_ai.all_existing_model_official_issue_transport import GithubIssueTransport
from race_ai.boat_all_model_store import MAX_WIRE
from race_ai.boat_pdca_state import state_key
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_official_result_collect as collector
from scripts.boat_all_racers import _read,_write

ROOT=Path(__file__).resolve().parents[1]


def utc_now():return datetime.now(timezone.utc)


class GitSnapshot:
    """Read only fixed paths at exact local Git objects; never fetch or checkout."""
    def __init__(self,root,head):
        self.root=Path(root).resolve();I.need(I._hex(head),'CHECKOUT_HEAD')
        I.need(self._git(['rev-parse','--is-shallow-repository']).strip()==b'false','COMPLETE_GIT_HISTORY')
        I.need(self._git(['rev-parse','HEAD']).decode().strip()==head,'CHECKOUT_HEAD')
        parents=self._git(['show','-s','--format=%P',head]).decode().strip().split()
        I.need(len(parents)==1 and I._hex(parents[0]),'ISSUE_ONLY_PARENT')
        target=parents[0]
        self.facts=dict(head_sha=head,parents=parents,
            changed_files=self._git(['diff-tree','--no-ext-diff','--no-commit-id','--name-only','-r',head]).decode().splitlines(),
            subject=self._git(['show','-s','--format=%s',head]).decode().strip(),
            target_subject=self._git(['show','-s','--format=%s',target]).decode().strip(),
            recovery_raw=self.read(target,I.REQUEST_PATH,32768),
            current_recovery_raw=_read(self.root/I.REQUEST_PATH,32768))
    def _git(self,args,*,missing=False):
        result=subprocess.run(['git','--no-replace-objects',*args],cwd=self.root,
            capture_output=True,check=False,timeout=30)
        if missing and result.returncode==128:return None
        I.need(result.returncode==0 and len(result.stdout)<=MAX_WIRE,'GIT_SNAPSHOT')
        return result.stdout
    def read(self,head,path,limit):
        I.need(I._hex(head) and type(path) is str and (path in (I.ISSUE_PATH,I.REQUEST_PATH) or
            re.fullmatch(r'audit/state/official-result-collection-plan-[a-f0-9]{64}\.enc',path)) and
            type(limit) is int and 0<limit<=MAX_WIRE,'IMMUTABLE_PATH')
        self._git(['cat-file','-e',head+'^{commit}'])
        listing=self._git(['ls-tree',head,'--',path]).decode().strip()
        if not listing:return None
        I.need(re.fullmatch('100644 blob [a-f0-9]{40}\\t'+re.escape(path),listing) is not None,'REGULAR_GIT_BLOB')
        size=int(self._git(['cat-file','-s',head+':'+path]))
        I.need(0<size<=limit,'GIT_BLOB_BOUND')
        raw=self._git(['show',head+':'+path]);I.need(len(raw)==size,'GIT_BLOB_BYTES');return raw
    def previous_issue(self,head):
        # A collect commit cannot replace this marker with an older valid issue
        # and omit an intervening uncertain/denied source epoch. Derive the
        # latest immutable change from complete topology, never caller input or
        # commit dates; incomparable history is an explicit HOLD.
        I.need(I._hex(head),'HISTORY_HEAD')
        changes=self._git(['rev-list','--topo-order','--full-history','--max-count=129',head,'--',I.ISSUE_PATH]).decode().splitlines()
        I.need(len(changes)<=128,'ISSUE_HISTORY_BOUND')
        current=self.read(head,I.ISSUE_PATH,16384)
        if not changes:
            I.need(current is None,'BOOTSTRAP_HISTORY_MISSING');return None
        latest=changes[0]
        for previous in changes[1:]:self._git(['merge-base','--is-ancestor',previous,latest])
        raw=self.read(latest,I.ISSUE_PATH,16384)
        I.need(type(raw) is bytes and raw==current,'LATEST_ISSUE_MARKER_REQUIRED')
        value=I.validate_issue_request(read_json_bytes(raw))
        parents=self._git(['show','-s','--format=%P',latest]).decode().strip().split()
        changed=self._git(['diff-tree','--no-ext-diff','--no-commit-id','--name-only','-r',latest]).decode().splitlines()
        subject=self._git(['show','-s','--format=%s',latest]).decode().strip()
        I.need(parents==[value['target']['head_sha']] and changed==[I.ISSUE_PATH] and
            subject.startswith(I.PREFIX),'LATEST_ISSUE_COMMIT_REQUIRED')
        return raw


def trusted_environment():
    """Reject local/fork/rerun scope before any secret or GitHub lookup."""
    I.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')==I.REPOSITORY and
        os.environ.get('GITHUB_REPOSITORY_ID')==str(I.REPOSITORY_ID) and
        os.environ.get('GITHUB_EVENT_NAME')=='pull_request' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and
        os.environ.get('GITHUB_ACTOR')==I.OWNER and os.environ.get('GITHUB_ACTOR_ID')==str(I.OWNER_ID) and
        os.environ.get('GITHUB_TRIGGERING_ACTOR')==I.OWNER and
        os.environ.get('GITHUB_REF')=='refs/pull/71/merge' and
        os.environ.get('GITHUB_WORKFLOW_REF')==I.REPOSITORY+'/'+I.WORKFLOW_PATH+'@refs/pull/71/merge','ACTIONS_OWNER_ONLY')
    event=read_json_bytes(_read(Path(os.environ.get('GITHUB_EVENT_PATH','')),1024*1024))
    pr=event.get('pull_request',{});sender=event.get('sender',{})
    I.need(event.get('number')==71 and sender.get('id')==I.OWNER_ID and sender.get('login')==I.OWNER and
        event.get('repository',{}).get('id')==I.REPOSITORY_ID and event['repository'].get('full_name')==I.REPOSITORY and
        pr.get('head',{}).get('repo',{}).get('id')==I.REPOSITORY_ID and
        pr['head']['repo'].get('full_name')==I.REPOSITORY and pr['head'].get('ref')==I.BRANCH,'EVENT_SCOPE')
    head=pr['head'].get('sha');I.need(I._hex(head),'EVENT_HEAD')
    ident=os.environ.get('GITHUB_RUN_ID','');I.need(re.fullmatch('[1-9][0-9]{0,19}',ident) is not None,'ISSUER_RUN')
    return dict(head_sha=head,run_id=int(ident))


def _artifact_list(reader,run_id):
    rows=[];seen=set();total=None
    for page in range(1,17):
        route='actions/runs/'+str(run_id)+'/artifacts?per_page=100'+('' if page==1 else '&page='+str(page))
        value=reader.json(route);items=value.get('artifacts');count=value.get('total_count')
        I.need(type(items) is list and len(items)<=100 and type(count) is int and 0<=count<=1600 and
            (total is None or total==count),'ARTIFACT_LIST_COMPLETE');total=count
        for item in items:
            I.need(type(item) is dict and I._id(item.get('id')) and item['id'] not in seen,'ARTIFACT_LIST_UNIQUE')
            seen.add(item['id']);rows.append(item)
        I.need(len(rows)<=total,'ARTIFACT_LIST_COMPLETE')
        if len(rows)==total:return rows
        I.need(len(items)==100,'ARTIFACT_LIST_COMPLETE')
    I.need(False,'ARTIFACT_LIST_BOUND')


def _continuity(snapshot,issue,request,reader):
    previous_raw=snapshot.previous_issue(issue['target']['head_sha'])
    if previous_raw is None:
        I.check_pin_continuity(request['manifest']);return None
    previous=I.validate_issue_request(read_json_bytes(previous_raw))
    I.need(previous['target']['run_id']!=issue['target']['run_id'],'FRESH_SOURCE_EPOCH')
    raw=snapshot.read(previous['target']['head_sha'],I.REQUEST_PATH,32768)
    I.need(type(raw) is bytes and sha256(raw).hexdigest()==previous['recovery_request_blob_sha256'],'PREVIOUS_REQUEST_BYTES')
    original=read_json_bytes(raw);I.need(digest(original)==previous['recovery_request_sha256'],'PREVIOUS_REQUEST_DIGEST')
    current=reader.json('actions/runs/'+str(previous['target']['run_id']))
    I.need(current.get('head_sha')==previous['target']['head_sha'],'PREVIOUS_RUN_HEAD')
    names={'official-result-collection-journal-'+str(current['id']),
        'all-existing-official-results-'+str(current['id'])+'-900005'}
    artifacts=[reader.json('actions/artifacts/'+str(row['id'])) for row in _artifact_list(reader,current['id'])
        if row.get('name') in names]
    I.check_pin_continuity(request['manifest'],previous_request=original,previous_run=current,previous_artifacts=artifacts)
    return dict(issue=previous,request=original,current_run=current)


def _load_plan(snapshot,head,manifest,key,now):
    raw=snapshot.read(head,manifest['plan_path'],MAX_WIRE)
    I.need(type(raw) is bytes and raw==_read(collector.ROOT/manifest['plan_path'],MAX_WIRE) and
        sha256(raw).hexdigest()==manifest['plan_sha256'],'IMMUTABLE_PLAN_BYTES')
    return collector.load_plan(manifest,key=key,now=now)


def prepare_data(snapshot,issue,request,first,reader,*,key,now,continuity=None):
    """Authenticate all pinned inputs using existing readers; no source access."""
    authority=I.authority_for(request);authority.validate_request(request,now);manifest=request['manifest']
    groups={field:[reader.archive(pin) for pin in manifest[field]] for field in I.PIN_FIELDS}
    I.need(sum(len(a['raw']) for group in groups.values() for a in group)<=256*1024*1024,'TOTAL_EVIDENCE_BOUND')
    run_ids=sorted({p['run_id'] for p in manifest['prior_journal_artifacts']})
    actual_runs={ident:reader.json('actions/runs/'+str(ident)) for ident in run_ids}
    for run in actual_runs.values():I.run_scope(run)
    oldrun=actual_runs[R.OLD_RUN];others=[actual_runs[n] for n in run_ids if n!=R.OLD_RUN]
    runs=R._prior_runs(request,oldrun,others)
    I.need(issue['target']['run_id'] not in run_ids,'FRESH_TARGET_RUN')
    bodies={};receipts={}
    for pin,item in zip(manifest['prior_journal_artifacts'],groups['prior_journal_artifacts']):
        body,receipt=R._evidence(item['raw'],item['metadata'],pin,now,key)
        run=actual_runs[pin['run_id']]
        I.need(R.clock(run['run_started_at'])<=R.clock(body['epoch_started_at'])<=
            R.clock(item['metadata']['created_at'])+timedelta(seconds=1) and
            R.clock(item['metadata']['created_at'])<=R.clock(run['updated_at'])+timedelta(seconds=1),'PRIOR_JOURNAL_CLOCK')
        if pin['id']!=R.OLD_ARTIFACT:C._complete(body,item['metadata'],now)
        bodies[pin['id']]=body;receipts[pin['id']]=receipt
    oldbody=bodies[R.OLD_ARTIFACT];head=issue['target']['head_sha']
    oldplan=_load_plan(snapshot,head,oldbody['manifest'],key,R.clock(oldbody['epoch_started_at']))
    newplan=_load_plan(snapshot,head,manifest,key,now)
    # R's initial issuer is intentionally small. The Actions issuer additionally
    # authenticates every native/result original before signing either R or S.
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
    from race_ai.all_existing_model_order_only_pdca import _frozen
    from race_ai import all_existing_model_official_results as results
    native_records=[]
    for pin,item in zip(manifest['native_artifacts'],groups['native_artifacts']):
        C._pin_metadata(item['raw'],item['metadata'],pin,now)
        _,records=_verified_private_pairs_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],key=key)
        native_records.extend(records)
    frozen=_frozen(native_records);known,_=results._frozen(frozen)
    I.need(all((case['sport'],collector._race_key(case['race_id'],case['sport'])) in known for case in newplan['cases']),
        'CASE_WITHOUT_FROZEN_NATIVE')
    for pin,item in zip(manifest['checkpoint_artifacts'],groups['checkpoint_artifacts']):
        C._pin_metadata(item['raw'],item['metadata'],pin,now)
        results.observations_from_official_result_artifact(item['raw'],item['metadata'],now=now,
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'],frozen_native_payloads=frozen,key=key,allow_order_only=True)
    if continuity is not None:
        previous=continuity['issue'];target=previous['target'];original=continuity['request']
        first_old=reader.json('actions/runs/'+str(target['run_id'])+'/attempts/1')
        path=R.capsule_path(original,target['head_sha'],target['run_id'])
        raw=reader.read_file(reader.head(),path,MAX_WIRE);I.need(raw is not None,'PREVIOUS_CAPSULE_REQUIRED')
        body=I.archival_authority(raw,request=original,target=target,first_attempt=first_old,key=key)
        jp=[p for p in manifest['prior_journal_artifacts'] if p['run_id']==target['run_id']]
        I.need(len(jp)==1 and bodies[jp[0]['id']].get('recovery_authorization',{}).get('authorization_sha256')==digest(body),
            'PREVIOUS_JOURNAL_AUTHORITY')
    latest=max([R.clock(run['updated_at'])+timedelta(seconds=1) for run in runs]+
        [R.clock(a['metadata']['created_at'])+timedelta(seconds=1) for a in groups['prior_journal_artifacts']])
    before=latest+timedelta(hours=1);I.need(before<=now,'COOLDOWN')
    midnight=datetime.combine(now.astimezone(collector.JST).date()+timedelta(days=1),datetime.min.time(),tzinfo=collector.JST)
    expires=min(now+timedelta(hours=1),midnight);I.need((expires-now).total_seconds()>=600,'CURRENT_WINDOW')
    data=dict(request=deepcopy(request),target=deepcopy(issue['target']),issued_at=now.isoformat(),
        not_before=before.isoformat(),expires_at=expires.isoformat(),old_run=oldrun,prior_runs=others,
        first_attempt=first,old_plan=oldplan,new_plan=newplan)
    old=next(a for a in groups['prior_journal_artifacts'] if a['metadata']['id']==R.OLD_ARTIFACT)
    if authority is C:
        probe=next(p for p in manifest['prior_journal_artifacts'] if p['id']==request['probe_journal_artifact_id'])
        data.update(probe_first_attempt=reader.json('actions/runs/'+str(probe['run_id'])+'/attempts/1'),
            journal_archives=groups['prior_journal_artifacts'],native_archives=groups['native_artifacts'],
            checkpoint_archives=groups['checkpoint_artifacts'])
        path='recovery/official-results/'+request['probe_request_sha256']+'/'+probe['head_sha']+'/'+str(probe['run_id'])+'/2.enc'
        data['probe_capsule_raw']=reader.read_file(reader.head(),path,MAX_WIRE)
        I.need(data['probe_capsule_raw'] is not None,'ORIGINAL_PROBE_CAPSULE_REQUIRED')
    else:
        data.update(old_journal_raw=old['raw'],old_journal_metadata=old['metadata'])
        if request['schema']=='RACE_AI_OFFICIAL_RESULT_RECOVERY_REQUEST_V4':
            data['prior_journal_archives']=groups['prior_journal_artifacts']
    return data


def issue_once(*,snapshot,issuer_run_id,reader,writer,readback,key_loader,clock=utc_now):
    issue=I.validate_issue_request(read_json_bytes(snapshot.read(snapshot.facts['head_sha'],I.ISSUE_PATH,16384)))
    target=issue['target'];current=reader.json('actions/runs/'+str(target['run_id']))
    first=reader.json('actions/runs/'+str(target['run_id'])+'/attempts/1')
    jobs=reader.json('actions/runs/'+str(target['run_id'])+'/attempts/1/jobs?per_page=100')
    issuer=reader.json('actions/runs/'+str(issuer_run_id));pr=reader.json('pulls/71');now=clock()
    proof=I.admit_context(issue,issuer_run=issuer,current_pr=pr,snapshot=snapshot.facts,
        target_run=current,first_attempt=first,jobs=jobs,now=now)
    request=read_json_bytes(snapshot.facts['recovery_raw']);continuity=_continuity(snapshot,issue,request,reader)
    path=R.capsule_path(request,target['head_sha'],target['run_id']);parent=writer.head()
    I.need(reader.read_file(parent,path,MAX_WIRE) is None,'CANONICAL_CAPSULE_ALREADY_ISSUED')
    key=key_loader();data=prepare_data(snapshot,issue,request,first,reader,key=key,now=clock(),continuity=continuity)
    raw=I.authority_for(request).issue_consume_capsule(data,key)
    # No target run or PR lock spans Git. Repeat exact admission before the only
    # publication, then again after independent remote authenticated readback.
    def fresh_admission():
        return I.admit_context(issue,issuer_run=reader.json('actions/runs/'+str(issuer_run_id)),
            current_pr=reader.json('pulls/71'),snapshot=snapshot.facts,
            target_run=reader.json('actions/runs/'+str(target['run_id'])),first_attempt=first,jobs=jobs,now=clock())
    fresh_admission();I.verify_publication(raw,data=data,current_run=current,now=clock(),key=key,expected_raw=raw)
    commit=writer.publish_capsule(path,raw,parent)
    remote=readback.read_file(commit,path,MAX_WIRE);I.need(remote is not None,'REMOTE_CAPSULE_REQUIRED')
    verified=I.verify_publication(remote,data=data,current_run=reader.json('actions/runs/'+str(target['run_id'])),
        now=clock(),key=key,expected_raw=raw)
    fresh_admission()
    return dict(schema=I.PROOF,state='CONSUMED_CAPSULE_PUBLISHED_AND_READ_BACK',ready=True,
        repository_id=I.REPOSITORY_ID,workflow_id=I.WORKFLOW,pull_request=71,issuer_run_id=issuer_run_id,
        issuer_run_attempt=1,issuer_head_sha=snapshot.facts['head_sha'],issuer_actor_id=I.OWNER_ID,
        issue_request_sha256=digest(issue),recovery_request_sha256=digest(request),target=deepcopy(target),
        target_first_viewer_job_id=issue['target_first_viewer_job_id'],
        prior_full_verification_sha256=proof['prior_full_verification_sha256'],
        prior_full_jobs_sha256=proof['prior_full_jobs_sha256'],source_commit=commit,capsule_path=path,
        independent_git_readback_verified=True,source_requests=0,plaintext_published=False,
        production_promoted=False,actual_purchases=False,**verified)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--proof',type=Path,required=True)
    args=parser.parse_args(argv);trusted=False
    status=dict(schema=I.PROOF,state='HOLD_FIXED_RECOVERY_ISSUANCE',ready=False,source_requests=0,
        independent_git_readback_verified=False,plaintext_published=False,production_promoted=False,actual_purchases=False)
    try:
        env=trusted_environment();trusted=True;snapshot=GitSnapshot(ROOT,env['head_sha'])
        status=issue_once(snapshot=snapshot,issuer_run_id=env['run_id'],reader=GithubIssueTransport(),
            writer=GithubIssueTransport(),readback=GithubIssueTransport(),
            key_loader=lambda:state_key('production'),clock=utc_now)
    except Exception as exc:
        reason=str(exc)
        status['reason']=reason if re.fullmatch(r'(?:OFFICIAL_ISSUE|ALL_MODEL_[A-Z_]+)_[A-Z0-9_]{1,100}',reason) else 'ISSUANCE_UNAVAILABLE'
    if trusted:
        try:
            out=args.proof.absolute();I.need(out.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()) and
                not out.is_relative_to(ROOT),'PRIVATE_PROOF_PATH')
            _write(out,(json.dumps(status,sort_keys=True)+'\n').encode())
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as output:
                    output.write('requested=true\nready='+str(status['ready']).lower()+'\n')
        except Exception:
            status.update(state='HOLD_FIXED_RECOVERY_ISSUANCE',ready=False,reason='PROOF_UNAVAILABLE')
    print(json.dumps(status,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
