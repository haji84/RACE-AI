"""Read-only known-commit fingerprint recovery; no default network or writer.

GitHub server-time presence is not source rights, full private-payload
retention, authentic model execution, a complete denominator or formal scores.
The caller must supply the pinned legacy verifier and an independently audited
bounded GitHub reader. Unknown commits never become permission to retry a PUT.
"""
import base64
import binascii
from datetime import datetime, timedelta, timezone
import json
import re

from .pr71_delivery_binding import _stamp
from .race_bound_freeze_receipt import verify_bound_receipt

BASE='https://api.github.com/repos/haji84/RACE-AI'
REPO='haji84/RACE-AI'
SCHEMA='RACE_AI_GITHUB_WITNESS_RESOLUTION_V1'
HEX40=re.compile(r'[a-f0-9]{40}\Z')
PATH=re.compile(r'audit/freezes/(\d{4}-\d{2}-\d{2})/[a-f0-9]{64}\.json\Z')


class WitnessResolutionError(ValueError):
    """Invalid or unavailable evidence; all recovery remains read-only."""


def _deny(code='EXTERNAL_WITNESS_UNRESOLVED_DO_NOT_WRITE'):
    raise WitnessResolutionError(code) from None


def _time(value):
    if not isinstance(value,str) or len(value)>64:
        _deny('INVALID_WITNESS_TIME')
    try:return _stamp(value)
    except (ValueError,TypeError):_deny('INVALID_WITNESS_TIME')


def _now(clock):
    value=clock()
    if not isinstance(value,datetime) or value.utcoffset() is None:
        _deny('INVALID_OBSERVATION_CLOCK')
    return value.astimezone(timezone.utc)


def resolve_anchor_witness(prepared,commit_sha,persisted_at,*,expected_branch,
                           github_fetch=None,trusted_legacy_verifier=None,clock=None):
    """Resolve at most one exact-commit list/run/blob read, never a mutation.

    prepared is the unchanged prepare_anchor result. A missing commit returns
    STOPPED without a reader call. Evidence refusal raises a sanitized error.
    Calls to a legacy verifier are restricted to the selected run then its
    exact committed blob. Callbacks cannot retarget a copied expected anchor.
    """
    if (type(prepared) is not dict or set(prepared)!={'path','anchor','status','eligible_for_hit_at_8'}
        or prepared['status']!='PREPARED_NOT_WRITTEN' or prepared['eligible_for_hit_at_8'] is not False):
        _deny('ORIGINAL_PREPARED_ANCHOR_REQUIRED')
    path=prepared['path'];a=prepared['anchor']
    if (not isinstance(path,str) or not PATH.fullmatch(path) or type(a) is not dict
        or set(a)!={'schema','race_id','prediction_sha256','cutoff_at'}
        or a['schema']!='RACE_AI_GITHUB_FREEZE_ANCHOR_V1'
        or not isinstance(a['race_id'],str) or not 8<=len(a['race_id'])<=250
        or not isinstance(a['prediction_sha256'],str)
        or not re.fullmatch(r'[a-f0-9]{64}',a['prediction_sha256'])):
        _deny('INVALID_EXPECTED_FINGERPRINT')
    anchor={key:a[key] for key in ('schema','race_id','prediction_sha256','cutoff_at')}
    cutoff=_time(anchor['cutoff_at']);persisted=_time(persisted_at)
    if (persisted>=cutoff or PATH.fullmatch(path)[1]!=cutoff.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        or not isinstance(expected_branch,str) or not re.fullmatch(r'audit/freeze-[A-Za-z0-9._/-]{1,80}',expected_branch)
        or '..' in expected_branch or '//' in expected_branch or expected_branch.endswith('/')):
        _deny('INVALID_EXPECTED_CUTOFF_OR_BRANCH')
    result={'schema':SCHEMA,'status':'STOPPED_COMMIT_UNKNOWN_DO_NOT_WRITE',
        'receipt':None,'commit_sha':commit_sha,'model_race_id':anchor['race_id'],
        'prediction_sha256':anchor['prediction_sha256'],'external_server_time':None,
        'external_pre_cutoff_presence_verified':False,'eligible_for_hit_at_8':False,
        'source_rights_verified':False,'full_private_payload_retention_verified':False,
        'producer_execution_authenticated':False,'github_reads':0}
    if commit_sha is None:return result
    if not isinstance(commit_sha,str) or not HEX40.fullmatch(commit_sha):
        _deny('EXACT_SUBMISSION_COMMIT_REQUIRED')
    if not callable(github_fetch) or not callable(trusted_legacy_verifier):
        _deny('TRUSTED_READ_ONLY_TRANSPORT_AND_PINNED_VERIFIER_REQUIRED')
    clock=clock or (lambda:datetime.now(timezone.utc));started=_now(clock)
    reads=0
    def get(url):
        nonlocal reads
        reads+=1
        if reads>3:_deny('GITHUB_READ_BUDGET_EXCEEDED')
        try:return github_fetch(url)
        except Exception:_deny('GITHUB_READ_UNAVAILABLE_DO_NOT_WRITE')
    listing=get(BASE+'/actions/runs?head_sha='+commit_sha+'&event=push&per_page=100')
    if (type(listing) is not dict or type(listing.get('total_count')) is not int
        or not 0<=listing['total_count']<=100 or type(listing.get('workflow_runs')) is not list
        or len(listing['workflow_runs'])!=listing['total_count']):
        _deny('INCOMPLETE_OR_INVALID_RUN_LIST')
    candidates=[];seen=set()
    for row in listing['workflow_runs']:
        if (type(row) is not dict or type(row.get('id')) is not int or not 1<=row['id']<=10**15
            or row['id'] in seen or row.get('head_sha')!=commit_sha or row.get('event')!='push'
            or type(row.get('repository')) is not dict or row['repository'].get('full_name')!=REPO):
            _deny('INVALID_RUN_LIST_IDENTITY')
        seen.add(row['id']);at=_time(row.get('created_at'))
        if row.get('head_branch')==expected_branch and persisted<=at<cutoff and at<=started:
            candidates.append((at,row['id'],row['created_at']))
    if not candidates:_deny()
    server_at,run_id,_=min(candidates)
    run_url=BASE+'/actions/runs/'+str(run_id)
    blob_url=BASE+'/contents/'+path+'?ref='+commit_sha
    expected_urls=(run_url,blob_url);position=0;individual_time=None;violated=False
    validated_run=False;validated_blob=False
    original=(json.dumps(anchor,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode('utf-8')
    def guarded(url):
        nonlocal position,individual_time,violated,validated_run,validated_blob
        if position>=2 or url!=expected_urls[position]:
            violated=True
            _deny('UNEXPECTED_VERIFIER_READ')
        position+=1;data=get(url)
        if url==run_url:
            if (type(data) is not dict or type(data.get('id')) is not int or data['id']!=run_id
                or data.get('head_sha')!=commit_sha or data.get('head_branch')!=expected_branch
                or data.get('event')!='push' or type(data.get('repository')) is not dict
                or data['repository'].get('full_name')!=REPO):_deny('INDIVIDUAL_RUN_IDENTITY_MISMATCH')
            at=_time(data.get('created_at'))
            if not persisted<=at<cutoff or at!=server_at or at>started:_deny('INDIVIDUAL_RUN_TIME_MISMATCH')
            individual_time=data['created_at']
            validated_run=True
            return {'id':run_id,'head_sha':commit_sha,'event':'push',
                    'repository':{'full_name':REPO},'created_at':individual_time}
        if (type(data) is not dict or data.get('type')!='file' or data.get('encoding')!='base64'
            or not isinstance(data.get('content'),str) or len(data['content'])>100000):
            _deny('PINNED_ORIGINAL_ANCHOR_REQUIRED')
        try:raw=base64.b64decode(''.join(data['content'].split()),validate=True)
        except (ValueError,binascii.Error):_deny('PINNED_ORIGINAL_ANCHOR_REQUIRED')
        if raw!=original:_deny('ORIGINAL_ANCHOR_BYTES_MISMATCH')
        validated_blob=True
        return {'type':'file','encoding':'base64','content':data['content']}
    receipt={'run_id':run_id,'path':path}
    verifier_receipt=dict(receipt)
    try:
        passed=verify_bound_receipt(verifier_receipt,anchor['prediction_sha256'],persisted_at,
            anchor['cutoff_at'],expected_race_id=anchor['race_id'],
            trusted_legacy_verifier=trusted_legacy_verifier,github_fetch=guarded)
    except WitnessResolutionError:raise
    except Exception:_deny('BOUND_RECEIPT_VERIFICATION_FAILED')
    finished=_now(clock)
    if (passed is not True or position!=2 or reads!=3 or violated or finished<started
        or not validated_run or not validated_blob
        or set(verifier_receipt)!={'run_id','path'}
        or type(verifier_receipt['run_id']) is not int or verifier_receipt['run_id']!=run_id
        or type(verifier_receipt['path']) is not str or verifier_receipt['path']!=path):
        _deny('INCOMPLETE_OR_REVERSED_WITNESS_READ')
    result.update(status='EXTERNAL_FINGERPRINT_PRESENT_BEFORE_CUTOFF',receipt=receipt,
        external_server_time=individual_time,external_pre_cutoff_presence_verified=True,
        github_reads=reads,observed_at=finished.isoformat())
    return result
