"""Trusted main I/O for one fixed study, using the existing owner readers.

No command entry, source acquisition, writer, new artifact, training or key
export. Missing original witness or any private evidence stays a bounded HOLD.
"""
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from hashlib import sha1, sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from scripts import boat_native_forward_study as study

BINDING_PATH = 'audit/state/boat-native-forward-study-witness.json'
_PHASES = frozenset(('MAIN_IDENTITY','SPEC','SOURCE_PINS','ORIGIN','CANDIDATE','WITNESS','HISTORY','COHORT'))


class StudyReads:
    """One bounded read-only GitHub namespace; never follows response URLs."""
    def __init__(self,get,*,cache_bytes=512*1024*1024):
        study.need(type(cache_bytes) is int and 0<cache_bytes<=512*1024*1024,'CACHE_BUDGET_INVALID')
        self.get=get;self.cache=OrderedDict();self.cache_limit_bytes=cache_bytes
        self.resident_bytes=0;self.total=0;self.get_count=0
    def __call__(self,path):
        allowed=(type(path) is str and (
            re.fullmatch(r'actions/(?:runs/[1-9][0-9]*(?:/(?:artifacts|jobs)\?per_page=100(?:&page=[1-9][0-9]*)?)?|artifacts/[1-9][0-9]*(?:/zip)?)',path) or
            re.fullmatch(r'git/commits/[a-f0-9]{40}',path) or
            re.fullmatch(r'git/trees/[a-f0-9]{40}\?recursive=1',path) or
            path=='git/ref/heads/feat/four-sport-forecast-audit-view-20261022' or
            re.fullmatch(r'contents/docs/evidence/20[0-9]{2}-[0-9]{2}-[0-9]{2}/p0-first-receipt.json\?ref=[a-f0-9]{40}',path) or
            re.fullmatch(r'contents/audit/state/boat-native-forward-study.json\?ref=[a-f0-9]{40}',path) or
            re.fullmatch(r'actions/workflows/[1-9][0-9]*/runs\?branch=(?:main|production%2Fboat-p0-p1-20261111)&head_sha=[a-f0-9]{40}(?:&created=20[0-9-]{8}\.\.20[0-9-]{8})?&per_page=100(?:&page=[1-9][0-9]*)?',path)))
        study.need(allowed,'READ_ENDPOINT_REJECTED')
        if path in self.cache:
            raw=self.cache.pop(path);self.cache[path]=raw
            return raw
        self.get_count+=1;raw=self.get(path)
        if type(raw) is bytes:self.total+=len(raw)
        study.need(type(raw) is bytes and 0<len(raw)<=64*1024*1024,'READ_RESPONSE_BOUND')
        if len(raw)<=self.cache_limit_bytes:
            while self.cache and (self.resident_bytes+len(raw)>self.cache_limit_bytes or len(self.cache)>=4096):
                unused,evicted=self.cache.popitem(last=False);self.resident_bytes-=len(evicted)
            self.cache[path]=raw
            self.resident_bytes+=len(raw)
        return raw


def _file(root,path,limit=32768):
    target=Path(root)/path
    study.need(target.is_file() and not target.is_symlink() and
        not any(p.is_symlink() for p in target.absolute().parents) and 0<target.stat().st_size<=limit,'CONFIG_FILE_BOUND')
    return target.read_bytes()


def _head(repo):return subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,timeout=10).decode().strip()


def verify_source_pins(repo,raw_spec):
    spec=study.load_spec(raw_spec)
    study.need(_head(repo)==spec['source_commit'],'SOURCE_CHECKOUT_CHANGED')
    study.need(not subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=repo,timeout=10).strip(),'SOURCE_BYTES_CHANGED')
    config=_file(repo,'audit/state/boat-venue-learning-context-input.json',8192)
    runtime=_file(repo,'audit/state/boat-model-runtime-input.json',16384)
    registry=_file(repo,'race_ai/all_existing_model_registry.py',128*1024)
    protocol=_file(repo,'docs/BOAT_AB_PROSPECTIVE_PROTOCOL_20261103.md')
    actual=dict(source_commit=_head(repo),candidate_context_config_sha256=sha256(config).hexdigest(),
        runtime_pointer_sha256=sha256(runtime).hexdigest(),registry_sha256=sha256(registry).hexdigest())
    study.need(all(actual[k]==spec[k] for k in actual) and study._json(config)['training_sha256']==spec['candidate_training_sha256'] and
        sha1(f'blob {len(protocol)}\0'.encode()+protocol).hexdigest()==spec['legacy_protocol_blob_sha'],'SOURCE_PINS_CHANGED')
    return actual


def _identity(identity):
    study.need(type(identity) is dict and set(identity)=={'commit','run_id','attempt','repository'} and
        identity['repository']=='haji84/RACE-AI' and study._hex(identity['commit'],40) and
        study._id(identity['run_id']) and type(identity['attempt']) is int and identity['attempt']==1,'TRUSTED_MAIN_REQUIRED')


def _current_main(identity,get,now):
    _identity(identity)
    run=study._json(get('actions/runs/'+str(identity['run_id'])),1024*1024)
    study.need(run.get('id')==identity['run_id'] and run.get('head_sha')==identity['commit'] and
        run.get('head_branch')=='main' and run.get('event') in ('push','workflow_run') and
        run.get('path')==study.WORKFLOW and run.get('name')==study.WORKFLOW_NAME and
        study._id(run.get('workflow_id')) and type(run.get('run_attempt')) is int and run['run_attempt']==1 and
        run.get('status')=='in_progress' and run.get('conclusion') is None and study._time(run['created_at'])<=now,
        'TRUSTED_MAIN_REQUIRED')
    for field in ('repository','head_repository'):
        value=run.get(field)
        study.need(type(value) is dict and type(value.get('id')) is int and value['id']==1416489937 and
            value.get('full_name')=='haji84/RACE-AI','TRUSTED_MAIN_REQUIRED')
    return run


def _restore_candidate(repo,raw_spec):
    """Only Actions holds the owner key; reuse the existing retained candidate."""
    from race_ai.boat_pdca_state import state_key
    from race_ai import boat_venue_research_runtime as existing
    from race_ai.boat_venue_learning_handoff import restore_learning_candidate
    from race_ai.boat_venue_learning import read_candidate
    study.need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI',
        'ACTIONS_OWNER_KEY_ONLY')
    state_key('production')
    config,pointer,unused=existing._recovery_inputs(Path(repo)/'audit/state/boat-venue-learning-context-input.json',
        Path(repo)/'audit/state/all-existing-model-full-native-ci-learning-input.json')
    spec=study.load_spec(raw_spec)
    study.need(config['training_sha256']==spec['candidate_training_sha256'],'CANDIDATE_CHANGED')
    runner=Path(os.environ['RUNNER_TEMP'])
    study.need(runner.is_dir() and not runner.is_symlink() and
        not runner.resolve().is_relative_to(Path(repo).resolve()),'PRIVATE_RUNNER_REQUIRED')
    with tempfile.TemporaryDirectory(prefix='native-forward-candidate-',dir=runner) as folder:
        candidate=Path(folder)/'candidate'
        result=restore_learning_candidate(pointer,candidate,repo)
        study.need(result['encrypted_readback_verified'] is True,'CANDIDATE_READBACK_REQUIRED')
        training=read_candidate(candidate)['training']
        return study.candidate_bindings(spec,training)


def _hold(phase,*,nonce=None,spec_sha256=None):
    result=dict(schema='RACE_AI_NATIVE_FORWARD_STUDY_COUNTS_V1',registration_status='HOLD',
        evaluation_status='UNREGISTERED_HOLD',failure_phase=phase if phase in _PHASES else 'SPEC',
        official_raw_qualified=False,qualifying_g8_count=0,promotion_allowed=False,new_forecasts=0,source_requests=0)
    if study._hex(nonce):result['nonce']=nonce
    if study._hex(spec_sha256):result['spec_sha256']=spec_sha256
    return result


def _schedule(packet,get,now):
    """Read only the existing authenticated canonical P0 schedule, not its forecasts."""
    from scripts import boat_owner_active_snapshot_audit as active
    from race_ai import boat_all_model_recovery as originals
    from race_ai.frozen_day_cycle import read_p0,official_id
    run=packet['run'];scope=packet['scope'];reads=active._Reads(get)
    listed,owner=active._canonical_p0(reads,run,scope['inventory'],now,expected_owner_sha=study.SOURCE)
    raw_meta=reads(f'actions/artifacts/{listed["id"]}')
    meta,unused=originals._metadata(raw_meta,listed,owner,now,reads)
    raw=reads(f'actions/artifacts/{meta["id"]}/zip')
    day=study._time(run['created_at']).astimezone(study.JST).date().isoformat()
    document,unused=read_p0(raw,meta,expected_day=day)
    return [dict(race_id=official_id(s['race_id']),cutoff_at=s['sales_cutoff_at'],
        roster={str(r['lane']):r['registration_no'] for r in s['observations']}) for s in document['predictions']]


def _cohort_packets(spec,receipt,get,now,current_packet):
    from scripts import boat_current_pair_eligibility_audit as existing
    lower=study._time(receipt['registered_after']);upper=study._time(receipt['window_ends_at'])
    interval=(lower-timedelta(days=1)).date().isoformat()+'..'+upper.date().isoformat()
    route=('actions/workflows/405276784/runs?branch=production%2Fboat-p0-p1-20261111&head_sha='+
        spec['source_commit']+'&created='+interval+'&per_page=100')
    runs=study._pages(get,route,'workflow_runs',maximum=32);packets=[]
    for run in sorted(runs,key=lambda r:(study._time(r['created_at']),r['id'])):
        study.need(run.get('head_sha')==spec['source_commit'] and run.get('head_branch')=='production/boat-p0-p1-20261111' and
            run.get('event')=='workflow_dispatch' and type(run.get('workflow_id')) is int and run['workflow_id']==405276784 and
            type(run.get('run_attempt')) is int and run['run_attempt']==1,'SOURCE_HISTORY_CHANGED')
        # A running producer may save newer originals without updating run
        # metadata. Registration eligibility is checked on each authenticated record.
        if study._time(run['created_at'])>=upper:continue
        selected=[]
        if current_packet is not None and current_packet['run']['id']==run['id']:
            active,reads,scope=existing._scope(get,run['id'],now,spec['source_commit'])
            if all(scope[k]==current_packet['scope'].get(k) for k in ('run','job','rounds','inventory','final_control')):
                selected=[current_packet]
        if not selected:
            existing.audit_current_pairs(get=get,run_id=run['id'],now=now,
                expected_owner_sha=spec['source_commit'],_study_sink=selected.append)
        study.need(len(selected)==1 and type(selected[0]['records']) is list,'SOURCE_PACKET_INCOMPLETE')
        original=selected[0];cells=set(spec['cells'])
        packet=dict(original,records=[item for item in original['records']
            if 'pair' not in item['payload'] or item['payload']['cell_key'] in cells])
        packet['schedule']=_schedule(original,get,now);packets.append(packet)
    return packets


def audit_native_forward_study(repo,main_repo,*,get,now,main_identity,current_packet=None,clock=None):
    """Add a summary to the existing main report; never registers on every run."""
    phase='MAIN_IDENTITY';raw_spec=None;spec=None
    observed=clock or (lambda:now)
    try:
        _identity(main_identity)
        study.need(_head(main_repo)==main_identity['commit'],'MAIN_CHECKOUT_CHANGED')
        reads=StudyReads(get);_current_main(main_identity,reads,study._now(observed()))
        phase='SPEC';raw_spec=_file(main_repo,study.SPEC_PATH);spec=study.load_spec(raw_spec)
        binding=study._json(_file(main_repo,BINDING_PATH))
        phase='SOURCE_PINS';verify_source_pins(repo,raw_spec)
        if binding.get('status')=='UNBOUND':
            phase='ORIGIN'
            study.need(set(binding)=={'schema','status','nonce','spec_sha256'} and
                binding['schema']=='RACE_AI_NATIVE_FORWARD_STUDY_WITNESS_BINDING_V1' and
                binding['nonce']==spec['nonce'] and binding['spec_sha256']==sha256(raw_spec).hexdigest(),'WITNESS_BINDING_CHANGED')
            study.verify_registration_origin(spec,main_identity['commit'],reads)
            phase='CANDIDATE';candidate=_restore_candidate(repo,raw_spec)
            return study.registration_summary(raw_spec,candidate,main_commit=main_identity['commit'],
                main_run_id=main_identity['run_id'],main_run_attempt=main_identity['attempt'])
        phase='CANDIDATE';candidate=_restore_candidate(repo,raw_spec)
        phase='WITNESS'
        receipt=study.verify_registration_witness(raw_spec,binding,candidate=candidate,get=reads,now=observed())
        phase='HISTORY';packets=_cohort_packets(spec,receipt,reads,observed(),current_packet)
        phase='COHORT'
        return study.analyze_native_cohort(spec,receipt,candidate,packets,now=observed())['public']
    except Exception:
        return _hold(phase,nonce=spec.get('nonce') if type(spec) is dict else None,
            spec_sha256=sha256(raw_spec).hexdigest() if type(raw_spec) is bytes else None)
