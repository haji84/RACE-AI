"""Fetch pinned GitHub ciphertext, then run the explicitly scoped native fit.

No source-provider request, decision issuance, historical forecast generation
or production promotion occurs here. Expired artifacts remain unavailable.
"""
import argparse
from contextlib import redirect_stdout
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import tempfile

from race_ai.permissioned_source_delivery import read_json_bytes
from scripts.boat_all_racers import _read,_write,_key_ready
from scripts import all_existing_model_learning as learning

SCHEMA='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V1'
SCHEMA_V2='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V2'
SCHEMA_V3='RACE_AI_ALL_EXISTING_MODEL_CI_INPUT_V3'
ROOT=Path(__file__).resolve().parents[1]
BASE='repos/haji84/RACE-AI/actions/artifacts/'
MAX_ARCHIVE=64*1024*1024
MAX_TOTAL_ARCHIVES=256*1024*1024


def _need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_CI_'+reason)


def _clock(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        _need(result.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
        return result
    except (TypeError,AttributeError,ValueError):
        raise ValueError('ALL_MODEL_CI_AWARE_CLOCK_REQUIRED') from None


def _manifest(path):
    document=read_json_bytes(_read(Path(path),32*1024))
    fields={'schema','native_artifacts','result_artifacts','cohort_size','owner_research_record'}
    legacy=type(document) is dict and set(document)==fields and document.get('schema')==SCHEMA
    mixed=type(document) is dict and set(document)==fields|{'keep_other_sports'} and \
        document.get('schema')==SCHEMA_V2 and document.get('keep_other_sports') is True
    full=type(document) is dict and set(document)==fields|{'keep_other_sports','full_native_boat_cohort'} and \
        document.get('schema')==SCHEMA_V3 and document.get('full_native_boat_cohort') is True and \
        type(document.get('keep_other_sports')) is bool
    _need(legacy or mixed or full,'MANIFEST_SCHEMA_INVALID')
    _need(type(document['cohort_size']) is int and document['cohort_size']==8,'COMMON_EIGHT_COHORT_REQUIRED')
    native=document['native_artifacts'];results=document['result_artifacts']
    _need(type(native) is list and type(results) is list and 1<=len(native) and
          len(native)+len(results)<=32,'BOUNDED_ARTIFACT_LIST_REQUIRED')
    seen=set()
    for item in native+results:
        _need(type(item) is dict and set(item)=={'id','digest'} and type(item['id']) is int and
            0<item['id']<10**16 and type(item['digest']) is str and
            re.fullmatch('sha256:[a-f0-9]{64}',item['digest']) and item['id'] not in seen,
            'ARTIFACT_PIN_INVALID')
        seen.add(item['id'])
    record=document['owner_research_record']
    _need(type(record) is str and 0<len(record)<=240 and
          re.fullmatch(r'audit/state/[a-zA-Z0-9_.-]+\.json',record) and
          not PurePosixPath(record).is_absolute() and '..' not in PurePosixPath(record).parts,
          'OWNER_RECORD_PATH_INVALID')
    full=ROOT/record
    _need(full.is_file() and not any(p.is_symlink() for p in (full,*full.parents)),
          'OWNER_RECORD_PATH_INVALID')
    return document


def _gh(path):
    """Capture redirect/error details privately; never send stderr to logs."""
    _need(type(path) is str and re.fullmatch(re.escape(BASE)+r'[1-9][0-9]{0,15}(?:/zip)?',path),
          'GITHUB_ENDPOINT_INVALID')
    process=subprocess.run(['gh','api',path],capture_output=True,timeout=50,check=False)
    _need(process.returncode==0,'GITHUB_ARTIFACT_FETCH_FAILED')
    return process.stdout


def _metadata(raw,pin,kind,now,*,allow_generic=False):
    _need(type(raw) is bytes and 0<len(raw)<=32*1024,'METADATA_BOUND_INVALID')
    value=read_json_bytes(raw);run=value.get('workflow_run') if type(value) is dict else None
    _need(type(value) is dict and value.get('id')==pin['id'] and value.get('digest')==pin['digest'] and
          value.get('expired') is False and type(value.get('size_in_bytes')) is int and
          0<value['size_in_bytes']<=MAX_ARCHIVE and type(run) is dict and type(run.get('id')) is int and
          0<run['id']<10**20 and all(type(run.get(k)) is int and run[k]==1416489937
              for k in ('repository_id','head_repository_id')) and type(run.get('head_sha')) is str and
          re.fullmatch('[a-f0-9]{40}',run['head_sha']),'ARTIFACT_METADATA_MISMATCH')
    _need(_clock(value.get('created_at'))<=now<_clock(value.get('expires_at')),'ARTIFACT_EXPIRED_OR_FUTURE')
    name=value.get('name');run_id=str(run['id'])
    if kind=='native':
        if type(name) is str and re.fullmatch('all-existing-model-pairs-'+run_id+'-[1-9][0-9]*',name):
            flag='--native-archive-dir'
        else:
            _need(type(name) is str and re.fullmatch('boat-all-model-forecasts-'+run_id+r'-r(0|[1-9][0-9]{0,5})',name),
                  'NATIVE_ARTIFACT_NAME_INVALID')
            flag='--native-round-archive-dir'
    else:
        from race_ai.repeated_cycle import matches
        _need(type(name) is str and len(name)<=200 and (matches(name,'race-existing-cycle-'+run_id) or
            allow_generic and re.fullmatch('all-existing-official-results-'+run_id+'-[1-9][0-9]{0,5}',name)),
              'RESULT_ARTIFACT_NAME_INVALID')
        flag='--result-archive-dir'
    return value,flag


def _output(path):
    target=Path(path).absolute()
    _need('..' not in target.parts and not target.exists() and
          not any(p.is_symlink() for p in (target,*target.parents)) and
          not any((p/'.git').exists() for p in (target,*target.parents)),
          'OUTPUT_EXISTS_OR_NOT_PRIVATE')
    return target


def _runner_root():
    value=os.environ.get('RUNNER_TEMP')
    _need(type(value) is str and bool(value),'RUNNER_TEMP_REQUIRED')
    root=Path(value).absolute()
    _need('..' not in root.parts and root.is_dir() and
          not any(p.is_symlink() for p in (root,*root.parents)) and
          not any((p/'.git').exists() for p in (root,*root.parents)) and
          root.stat().st_uid==os.getuid() and not root.stat().st_mode&0o022,
          'RUNNER_TEMP_PRIVATE_REQUIRED')
    return root


def main(argv=None,*,now=None,_fetch=None,_fit=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest','--input',dest='manifest',required=True)
    parser.add_argument('--restored-dir',required=True)
    parser.add_argument('--out-dir',required=True)
    parser.add_argument('--state-input',default='audit/state/boat-pdca-production-input.json')
    parser.add_argument('--dataset-input',default='audit/state/boat-venue-dataset-input.json')
    args=parser.parse_args(argv)
    try:
        if not _key_ready():
            print(json.dumps(dict(state='HOLD_OWNER_STATE_KEY_MISSING',provider_source_requests=0,
                production_promoted=False,plaintext_published=False)));return 0
        started=now or datetime.now(timezone.utc)
        _need(type(started) is datetime and started.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
        output=_output(args.out_dir);manifest=_manifest(args.manifest);runner=_runner_root()
        fetch=_fetch or _gh;fitter=_fit or learning.main
        arguments=['fit','--restored-dir',args.restored_dir,'--out-dir',str(output),
            '--state-input',args.state_input,'--dataset-input',args.dataset_input,
            '--owner-research-record',manifest['owner_research_record'],'--cohort-size','8']
        arguments.append('--full-native-boat-cohort' if manifest.get('full_native_boat_cohort') is True else
            '--derive-from-observed')
        if manifest.get('keep_other_sports') is True:arguments.append('--keep-other-sports')
        counts=dict(native=0,result=0);total=0
        with tempfile.TemporaryDirectory(prefix='all-model-learning-ci-',dir=runner) as temporary:
            private=Path(temporary);private.chmod(0o700)
            for kind,items in (('native',manifest['native_artifacts']),('result',manifest['result_artifacts'])):
                for pin in items:
                    path=BASE+str(pin['id']);encoded=fetch(path)
                    metadata,flag=_metadata(encoded,pin,kind,started,
                        allow_generic=manifest['schema'] in (SCHEMA_V2,SCHEMA_V3))
                    total+=metadata['size_in_bytes']
                    _need(total<=MAX_TOTAL_ARCHIVES,'TOTAL_ARCHIVE_BOUND_INVALID')
                    raw=fetch(path+'/zip')
                    _need(type(raw) is bytes and len(raw)==metadata['size_in_bytes'] and
                          'sha256:'+hashlib.sha256(raw).hexdigest()==pin['digest'],
                          'ARCHIVE_BYTES_MISMATCH')
                    folder=private/str(pin['id']);folder.mkdir(mode=0o700)
                    _write(folder/'metadata.json',encoded);_write(folder/'archive.zip',raw)
                    arguments.extend((flag,str(folder)));counts[kind]+=1
            # The existing CLI re-fetches metadata, authenticates ciphertext and
            # the exact owner decision, joins separate outcomes and runs native
            # fitting. It never issues a missing/new owner decision implicitly.
            _output(output)
            captured=io.StringIO()
            with redirect_stdout(captured):
                code=fitter(arguments,now=started if now is not None else datetime.now(timezone.utc))
            text=captured.getvalue()
            _need(len(text.encode())<=256*1024,'FIT_OUTPUT_INVALID')
            summary=read_json_bytes(text.encode())
            _need(type(code) is int and code in (0,2) and type(summary) is dict and
                  type(summary.get('state')) is str,'FIT_OUTPUT_INVALID')
            # Only the established CLI's structured aggregate result escapes.
            summary.update(ci_native_artifacts_downloaded=counts['native'],
                ci_result_artifacts_downloaded=counts['result'],provider_source_requests=0,
                plaintext_published=False,production_promoted=False)
            print(json.dumps(summary,sort_keys=True));return code
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('ALL_MODEL_CI_[A-Z_]{1,100}',str(exc)) else \
            'ALL_MODEL_CI_OPERATION_REJECTED'
        print(json.dumps(dict(state='HOLD_ALL_MODEL_CI_INTAKE',reason=reason,provider_source_requests=0,
            plaintext_published=False,production_promoted=False)));return 2


if __name__=='__main__':raise SystemExit(main())
