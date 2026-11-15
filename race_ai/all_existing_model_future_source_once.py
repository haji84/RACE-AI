"""One experiment-wide consumed source reservation on the existing Git ref.

The literal path cannot change with a date, HEAD, run, cases or baseline. Any
existing marker stops before source dispatch, including malformed/expired ones.
No result-recovery permission or legacy recovery path is widened here.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import hmac
import re

from .actions_contract import digest
from . import all_existing_model_future_source_capture as core
from .all_existing_model_official_issue_transport import GithubIssueTransport
from .boat_all_model_store import seal_forecasts,open_forecasts,forecast_header,MAX_WIRE

PATH='future-source/all-thirty-first-forward-cycle-v1/autorace-keirin/consumed.enc'
SCHEMA='RACE_AI_OFFICIAL_FUTURE_SOURCE_ONCE_RESERVATION_V1'
PURPOSE='ALL_THIRTY_FIRST_FORWARD_CYCLE_V1'
DOMAIN=b'RACE_AI_OFFICIAL_FUTURE_SOURCE_ONCE_MAC_V1'
ROUND=900026
need=core.need
FIELDS={'schema','purpose','state','marker_path','repository_id','pull_request','target','execution_day',
    'issued_at','expires_at','manifest_sha256','plan_sha256','cases','baseline_artifacts','carrier_artifact',
    'baseline_receipts','baseline_models','history','prior_journal_artifacts','source_requests_actual',
    'source_request_upper_bound','old_source_requests_actual','old_source_requests_upper_bound','old_browser_outcome'}


class FutureSourceMarkerTransport(GithubIssueTransport):
    @staticmethod
    def _validate_path(path):need(type(path) is str and path==PATH,'CANONICAL_ONCE_PATH')
    _commit_message='Retain consumed first all-model forward source reservation'


def body(manifest,env,contexts,history,plan,*,now):
    now=core.clock(now);core.validate_manifest(manifest,now=now)
    need(env.get('run_attempt')==1 and type(env.get('run_attempt')) is int and
        type(env.get('run_id')) is int and env['run_id']>0 and type(env.get('head_sha')) is str and
        re.fullmatch('[a-f0-9]{40}',env['head_sha']),'ONCE_ACTUAL_ATTEMPT_ONE')
    core.prepare_capture(manifest,contexts,now=now)
    midnight=(now.astimezone(core.policy.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))
    expires=min(now+timedelta(hours=1),midnight,
        *(core.clock(c['cutoff_at'])-timedelta(seconds=600) for c in manifest['cases']))
    need(expires-now>=timedelta(seconds=100),'ONCE_CAPTURE_WINDOW_TOO_SHORT')
    receipts={sport:deepcopy(context['receipt']) for sport,context in contexts.items()}
    models={sport:dict(training_sha256=context['training']['training_sha256'],
        native_model_sha256=digest(context['training']['models'][sport+'/'+core.LEARNED_ID]['native_training']),
        native_created_at=context['training']['models'][sport+'/'+core.LEARNED_ID]['native_training']['created_at'])
        for sport,context in contexts.items()}
    audit={k:v for k,v in history.items() if k not in ('bodies','receipts','runs')}
    return dict(schema=SCHEMA,purpose=PURPOSE,state='CONSUMED_BEFORE_DISPATCH',marker_path=PATH,
        repository_id=1416489937,pull_request=71,target=dict(run_id=env['run_id'],head_sha=env['head_sha'],run_attempt=1),
        execution_day=manifest['execution_day'],issued_at=now.isoformat(),expires_at=expires.isoformat(),
        manifest_sha256=digest(manifest),plan_sha256=digest(plan),cases=deepcopy(manifest['cases']),
        baseline_artifacts=deepcopy(manifest['baseline_artifacts']),carrier_artifact=deepcopy(manifest['carrier_artifact']),
        baseline_receipts=receipts,baseline_models=models,history=audit,prior_journal_artifacts=deepcopy(manifest['prior_journal_artifacts']),
        source_requests_actual=None,source_request_upper_bound=32,old_source_requests_actual=None,
        old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN')


def _mac(value,key):
    need(type(key) is bytes and len(key)==32,'ONCE_EXPLICIT_KEY')
    return hmac.digest(hmac.digest(key,DOMAIN,'sha256'),digest(value).encode(),'sha256').hex()


def _validate(value):
    need(type(value) is dict and set(value)==FIELDS and value['schema']==SCHEMA and value['purpose']==PURPOSE and
        value['state']=='CONSUMED_BEFORE_DISPATCH' and value['marker_path']==PATH and
        type(value['repository_id']) is int and value['repository_id']==1416489937 and
        type(value['pull_request']) is int and value['pull_request']==71,'ONCE_SCOPE')
    target=value['target']
    need(type(target) is dict and set(target)=={'run_id','head_sha','run_attempt'} and
        type(target['run_id']) is int and target['run_id']>0 and type(target['run_attempt']) is int and
        target['run_attempt']==1 and type(target['head_sha']) is str and re.fullmatch('[a-f0-9]{40}',target['head_sha']),
        'ONCE_TARGET')
    issued=core.clock(value['issued_at']);expires=core.clock(value['expires_at'])
    midnight=issued.astimezone(core.policy.JST).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    need(value['execution_day']==issued.astimezone(core.policy.JST).date().isoformat() and
        issued+timedelta(seconds=100)<=expires<=min(midnight,issued+timedelta(hours=1)) and
        value['source_requests_actual'] is None and type(value['source_request_upper_bound']) is int and
        value['source_request_upper_bound']==32 and value['old_source_requests_actual'] is None and
        type(value['old_source_requests_upper_bound']) is int and value['old_source_requests_upper_bound']==32 and
        value['old_browser_outcome']=='UNKNOWN','ONCE_CLOCK_OR_COUNT')
    need(all(type(value[k]) is str and re.fullmatch('[a-f0-9]{64}',value[k]) for k in
        ('manifest_sha256','plan_sha256')),'ONCE_BINDING_HASH')
    cases=value['cases'];need(type(cases) is list and len(cases)==2 and
        {c['sport'] for c in cases}==core.SPORTS and all(c['expected_date']==value['execution_day'] and
        expires+timedelta(seconds=600)<=core.clock(c['cutoff_at']) for c in cases),'ONCE_CASE_CUTOFF')
    need(type(value['baseline_artifacts']) is dict and set(value['baseline_artifacts'])==core.SPORTS and
        type(value['baseline_receipts']) is dict and set(value['baseline_receipts'])==core.SPORTS and
        type(value['baseline_models']) is dict and set(value['baseline_models'])==core.SPORTS,'ONCE_BASELINES')
    for sport in core.SPORTS:
        core.validate_pin(value['baseline_artifacts'][sport]);model=value['baseline_models'][sport]
        need(core.clock(value['baseline_receipts'][sport]['created_at'])+timedelta(seconds=1)<=issued and
            core.clock(model['native_created_at'])<issued and all(type(model[k]) is str and
            re.fullmatch('[a-f0-9]{64}',model[k]) for k in ('training_sha256','native_model_sha256')),
            'ONCE_BASELINE_AVAILABILITY')
    core.validate_pin(value['carrier_artifact'])
    from scripts.all_existing_model_official_result_collect import _pins
    _pins(value['prior_journal_artifacts'])


def issue(value,key):
    """Pure AES/MAC; callers publish create-only and independently read back."""
    _validate(value)
    return seal_forecasts(dict(schema=SCHEMA,body=deepcopy(value),mac=_mac(value,key)),
        run_id=str(value['target']['run_id']),round_no=ROUND,key=key)


def validate(raw,expected,key,*,now):
    _validate(expected)
    value=open_forecasts(raw,key=key);header=forecast_header(raw)
    need(set(value)=={'schema','body','mac'} and value['schema']==SCHEMA and value['body']==expected and
        hmac.compare_digest(value['mac'],_mac(value['body'],key)) and header['round_no']==ROUND and
        header['run_id']==str(expected['target']['run_id']) and expected['marker_path']==PATH and
        expected['purpose']==PURPOSE and expected['state']=='CONSUMED_BEFORE_DISPATCH' and
        expected['target']['run_attempt']==1 and core.clock(expected['issued_at'])<=now<core.clock(expected['expires_at']),
        'ONCE_AUTHENTICATED_RESERVATION')
    return dict(marker_path=PATH,authorization_sha256=digest(expected),marker_cipher_sha256=sha256(raw).hexdigest(),
        issued_at=expected['issued_at'],expires_at=expected['expires_at'],source_requests_actual=None,source_request_upper_bound=32)


def reserve(value,key,transport,*,now):
    """No source calls; publication is a single canonical create-only CAS."""
    parent=transport.head()
    need(transport.read_file(parent,PATH,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    raw=issue(value,key);validate(raw,value,key,now=now)
    commit=transport.publish_capsule(PATH,raw,parent)
    actual=transport.read_file(commit,PATH,MAX_WIRE)
    need(actual==raw,'ONCE_ACTUAL_READBACK_BYTES')
    audit=validate(actual,value,key,now=now)
    return dict(audit,commit_sha=commit,_ciphertext=raw)
