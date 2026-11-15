"""Explicit Actions operator issuance and strict thirty-cell order-only fit.

Normal CI remains a verifier, never an issuer. This separately invoked wrapper
requires a public operator request, uses only the existing Actions owner key,
and preserves its fresh private owner record in authenticated ciphertext.
"""
import argparse
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
import hmac
import io
import json
import os
from pathlib import Path
import re
import tempfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import all_existing_model_research as research
from race_ai import boat_all_model_store as store
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.official_order_only_result import EVALUATION_SCOPE
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_learning as learning
from scripts import all_existing_model_learning_ci as ci
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write

ROOT=Path(__file__).resolve().parents[1]
REQUEST_SCHEMA='RACE_AI_OWNER_ORDER_ONLY_FIT_REQUEST_V1'
AUDIT_SCHEMA='RACE_AI_OWNER_ORDER_ONLY_FIT_AUDIT_V1'
REQUEST=dict(schema=REQUEST_SCHEMA,owner_instruction_ref='OWNER_INSTRUCTION_20261107_PERSONAL_RESEARCH',
    purpose='EXISTING_ALL_FAMILIES_ORDER_ONLY_SHADOW_FIT',
    cohort_policy='EARLIEST_COMPLETE_EIGHT_RACES_PER_SPORT',cohort_size=8,target_fitted_model_count=30,
    sports=['autorace','boat','horse','keirin'],label_evaluation_scope=EVALUATION_SCOPE,
    provider_permission_confirmed=False,production_promoted=False,actual_purchases=False,
    commercial_use_permitted=False,public_raw_data_permitted=False)
COUNTS={sport:8 for sport in REQUEST['sports']}


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_ORDER_ONLY_FIT_'+reason)


def _request(manifest):
    need(manifest.get('schema')==ci.SCHEMA_V4,'EXPLICIT_V4_REQUIRED')
    path=ROOT/manifest['owner_research_record']
    need(path.is_file() and not any(p.is_symlink() for p in (path,*path.parents)),'PUBLIC_REQUEST_REQUIRED')
    value=read_json_bytes(_read(path,16384))
    need(type(value) is dict and set(value)==set(REQUEST) and all(type(value[k]) is type(expected) and
         value[k]==expected for k,expected in REQUEST.items()),'PUBLIC_REQUEST_SCOPE_INVALID')
    return value


def _argument(arguments,name):
    need(arguments.count(name)==1,'COMMAND_SCOPE_INVALID')
    index=arguments.index(name)
    need(index+1<len(arguments),'COMMAND_SCOPE_INVALID')
    return index,arguments[index+1]


def _run(arguments,*,now):
    stdout=io.StringIO();stderr=io.StringIO()
    with redirect_stdout(stdout),redirect_stderr(stderr):
        try:code=learning.main(arguments,now=now)
        except SystemExit:raise ValueError('ALL_MODEL_ORDER_ONLY_FIT_COMMAND_ARGUMENTS_REJECTED') from None
    encoded=stdout.getvalue().encode()
    need(len(encoded)<=256*1024 and len(stderr.getvalue().encode())<=256*1024,'COMMAND_OUTPUT_BOUND')
    summary=read_json_bytes(encoded)
    need(type(code) is int and code in (0,2) and type(summary) is dict,'COMMAND_OUTPUT_INVALID')
    return code,summary


def _reason(value,fallback):
    return value if type(value) is str and re.fullmatch('ALL_MODEL_[A-Z0-9_]{1,120}',value) else \
        'ALL_MODEL_ORDER_ONLY_FIT_'+fallback


def _hold(summary,fallback):
    print(json.dumps(dict(state='HOLD_OWNER_ORDER_ONLY_FIT',ready=False,fitted_model_count=0,
        reason=_reason(summary.get('reason'),fallback),production_promoted=False,plaintext_published=False)))
    return 2


def _candidate(output,record):
    from race_ai.all_existing_model_runtime import _private_directory,_private_file
    _private_directory(output)
    need({p.name for p in output.iterdir()}=={'learning.enc','learning.json','summary.json'},'CANDIDATE_LAYOUT')
    for path in output.iterdir():_private_file(path)
    payload=read_candidate(output);trained=payload['training']
    expected={cell['cell_key'] for cell in registry.cells() if registry.group(cell['model_id'])!='seller'}
    need(len(expected)==30 and set(trained['models'])==expected and all(
         type(model.get(name)) is int and model[name]==count
         for model in trained['models'].values()
         for name,count in (('unique_races',8),('train_races',6),('validation_races',2))),
         'THIRTY_EIGHT_RACE_SIX_TWO_MODELS_REQUIRED')
    need(trained.get('common_eight_per_sport') is True and trained.get('required_common_cells')==30 and
         type(trained.get('record_count')) is int and trained['record_count']==240 and
         trained.get('cohort_counts_by_sport')==COUNTS and
         type(trained.get('common_cohort_sha256')) is str and re.fullmatch('[a-f0-9]{64}',trained['common_cohort_sha256']) and
         trained.get('label_evaluation_scope')==EVALUATION_SCOPE,'COMMON_COHORT_BINDING_INVALID')
    need(payload.get('owner_research_record')==record and
         trained.get('owner_research_decision_sha256')==digest(record) and
         trained.get('production_promoted') is False and type(payload.get('summary')) is dict and
         payload['summary'].get('actual_purchases') is False and payload['summary'].get('production_promoted') is False,
         'CANDIDATE_OWNER_SCOPE_INVALID')
    return trained


def _owner_record(path,issued,*,now):
    from race_ai.all_existing_model_runtime import _private_file
    _private_file(path);record=read_json_bytes(_read(path,100000))
    need(type(record) is dict and set(record)=={'schema','decision','mac'} and
         record['schema']==research.ORDER_SCHEMA and type(record['decision']) is dict and
         set(record['decision'])==research.FIELDS|{'label_evaluation_scope'},'ISSUED_OWNER_RECORD_INVALID')
    decision=record['decision']
    need(type(record['mac']) is str and re.fullmatch('[a-f0-9]{64}',record['mac']) and
         hmac.compare_digest(record['mac'],research._mac(decision,schema=research.ORDER_SCHEMA)) and
         decision['repository_id']=='1416489937' and decision['basis']=='OWNER_PERSONAL_RESEARCH' and
         decision['purpose']==research.ORDER_PURPOSE and decision['instruction_ref']==research.INSTRUCTION and
         decision['label_evaluation_scope']==EVALUATION_SCOPE and all(decision[field] is False
             for field in research.FALSE_FIELDS) and
         ci._clock(decision['issued_at'])<=now<ci._clock(decision['expires_at']) and
         issued.get('decision_sha256')==digest(record),'ISSUED_OWNER_RECORD_INVALID')
    return record


def _adapter(request,manifest,env,output,audit,*,key):
    def fit(arguments,*,now):
        need(type(arguments) is list and arguments[0]=='fit','COMMAND_SCOPE_INVALID')
        need(all(arguments.count(flag)==1 for flag in ('--allow-order-only','--keep-other-sports',
             '--full-native-boat-cohort')) and '--derive-from-observed' not in arguments and
             '--cohort-race-id' not in arguments,'COMMAND_SCOPE_INVALID')
        _,cohort=_argument(arguments,'--cohort-size');need(cohort=='8','COMMAND_SCOPE_INVALID')
        owner_index,public_owner=_argument(arguments,'--owner-research-record')
        out_index,target=_argument(arguments,'--out-dir')
        need(public_owner==manifest['owner_research_record'] and Path(target).absolute()==output,
             'COMMAND_SCOPE_INVALID')
        need('--common-eight-per-sport' not in arguments,'COMMAND_SCOPE_INVALID')
        with tempfile.TemporaryDirectory(prefix='owner-order-only-fit-',dir=env['temp']) as temporary:
            private=Path(temporary);private.chmod(0o700);owner=private/'owner-research.json'
            scoped=list(arguments);scoped[owner_index+1]=str(owner);scoped.append('--common-eight-per-sport')
            issue=list(scoped);issue[0]='issue-decision';del issue[out_index:out_index+2]
            # load_intake performs the strict complete-eight selection before
            # the existing issue-decision branch can create any owner MAC.
            code,issued=_run(issue,now=now)
            if code!=0:return _hold(issued,'COHORT_OR_OWNER_ISSUANCE_HOLD')
            need(issued.get('state')=='OWNER_ALL_MODEL_RESEARCH_DECISION_RECORDED' and
                 owner.is_file(),'COHORT_OR_OWNER_ISSUANCE_HOLD')
            record=_owner_record(owner,issued,now=now)
            body=dict(schema=AUDIT_SCHEMA,owner_fit_request=deepcopy(request),owner_research_record=record,
                operator_request_sha256=digest(request),ci_manifest_sha256=digest(manifest),
                workflow_run_id=env['run_id'],head_sha=env['head_sha'],created_at=now.isoformat())
            cipher=store.seal_forecasts(body,run_id=str(env['run_id']),round_no=1,key=key)
            backup=output.with_name(output.name+'.owner-research.enc');_write(backup,cipher)
            need(store.open_forecasts(_read(backup,store.MAX_WIRE),key=key)==body,'OWNER_RECORD_ENCRYPTED_READBACK')
            from hashlib import sha256
            audit.update(owner_record_ready=True,owner_record_cipher_sha256=sha256(cipher).hexdigest(),
                owner_research_decision_sha256=digest(record))
            code,summary=_run(scoped,now=now)
            if code!=0:return _hold(summary,'NATIVE_FIT_HOLD')
            trained=_candidate(output,record)
            print(json.dumps(dict(state='OWNER_ORDER_ONLY_FIT_ENCRYPTED_LOCAL_ONLY',ready=True,
                fitted_model_count=30,common_eight_per_sport=True,required_common_cells=30,record_count=240,
                common_cohort_sha256=trained['common_cohort_sha256'],cohort_counts_by_sport=COUNTS,
                label_evaluation_scope=EVALUATION_SCOPE,monetary_evaluation_available=False,
                **audit,provider_permission_confirmed=False,production_promoted=False,actual_purchases=False,
                plaintext_published=False),sort_keys=True))
            return 0
    return fit


def main(argv=None,*,now=None,_fetch=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--restored-dir',required=True)
    parser.add_argument('--out-dir',required=True)
    parser.add_argument('--state-input',default='audit/state/boat-pdca-production-input.json')
    parser.add_argument('--dataset-input',default='audit/state/boat-venue-dataset-input.json')
    args=parser.parse_args(argv);audit=dict(owner_record_ready=False)
    result=dict(state='HOLD_OWNER_ORDER_ONLY_FIT',ready=False,fitted_model_count=0,provider_source_requests=0,
        production_promoted=False,actual_purchases=False,plaintext_published=False)
    try:
        key=state_key('production')
        need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
             os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937','TRUSTED_ACTIONS_REQUIRED')
        manifest=ci._manifest(args.input);request=_request(manifest);env=future.environment()
        output=future.output_path(args.out_dir,env);ci._output(output)
        backup=output.with_name(output.name+'.owner-research.enc')
        need(not os.path.lexists(backup),'OWNER_RECORD_BACKUP_EXISTS_DO_NOT_RESET')
        captured=io.StringIO()
        with redirect_stdout(captured):
            code=ci.main(['--input',args.input,'--restored-dir',args.restored_dir,'--out-dir',str(output),
                '--state-input',args.state_input,'--dataset-input',args.dataset_input],now=now,_fetch=_fetch,
                _fit=_adapter(request,manifest,env,output,audit,key=key))
        need(len(captured.getvalue().encode())<=256*1024,'CI_OUTPUT_BOUND')
        summary=read_json_bytes(captured.getvalue().encode())
        if code==0 and summary.get('ready') is True and summary.get('fitted_model_count')==30:
            result.update(summary,operator_request_sha256=digest(request));status=0
        else:
            result.update(audit,reason=_reason(summary.get('reason'),'CI_FIT_HOLD'));status=2
    except Exception as exc:
        reason=str(exc)
        if not re.fullmatch('ALL_MODEL_ORDER_ONLY_FIT_[A-Z_]{1,100}',reason):reason='ALL_MODEL_ORDER_ONLY_FIT_OPERATION_REJECTED'
        result.update(audit,reason=reason);status=2
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            output.write('owner_record_ready='+str(audit['owner_record_ready']).lower()+'\n')
    print(json.dumps(result,sort_keys=True));return status


if __name__=='__main__':raise SystemExit(main())
