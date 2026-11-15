"""Prepare/read back BOAT or explicit thirty-cell future pairs from saved native inputs.

Only GitHub artifact reads occur here. Retained source observations keep their
original bytes and clocks; these new predictions require their own actual
pre-cutoff artifact receipt. No source-provider fetch or model fit occurs.
"""
import argparse
import hmac
import io
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
import re
import stat
import zipfile
import zlib

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import boat_all_model_store as origin_store
from race_ai.all_existing_model_learning import _sources, verify_training
from race_ai.all_existing_model_pairs import CAPSULE_FIELDS, make_private_pairs, record_partition_key, verify_private_record, _seal_cutoff
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.boat_venue_learning import read_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact, _candidate_from_zip, MEMBER_LIMITS
from race_ai.existing_model_dispatch import _race_key
from race_ai.github_freeze_receipt import BASE
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future

ROUND = 900004
ORIGIN_ROUND = 900010
ORIGIN_SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_ORIGIN_V1'
MANIFEST_SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V1'
MANIFEST_SCHEMA_V2 = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V2'
MANIFEST_SCHEMA_V3 = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V3'
MANIFEST_SCHEMA_V4 = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V4'
SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_COUNTS_V1'
PROVENANCE_SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_PROVENANCE_V1'
MANIFEST_FIELDS = {'schema', 'candidate_artifact_id', 'candidate_digest', 'source_input_artifact_id',
                   'source_input_digest', 'source_run_id', 'source_head_sha'}
FITTED_GROUPS = frozenset(('shared', 'shared_learned', 'boat_full', 'boat_observed', 'boat_ab', 'boat_clite'))
EXPECTED_CELLS = frozenset(c['cell_key'] for c in registry.cells() if c['sport'] == 'boat' and c['group'] in FITTED_GROUPS)
ALL_BOAT_CELLS = frozenset(c['cell_key'] for c in registry.cells() if c['sport'] == 'boat' and c['group'] != 'seller')
V3_CELLS = {sport:frozenset(c['cell_key'] for c in registry.cells() if c['sport']==sport and c['group']!='seller')
            for sport in ('boat','autorace','keirin','horse')}
V4_CELLS = {sport:V3_CELLS[sport] for sport in ('boat','horse')}
MINIMUM_LEAD = timedelta(minutes=10)
PHASES = future.SAFE_PHASES | frozenset(('MANIFEST', 'SOURCE_METADATA', 'SOURCE_DOWNLOAD', 'SOURCE_ADMISSION',
                                       'SOURCE_PROVENANCE', 'GENERATION_BINDING', 'SEAL_ORIGIN',
                                       'ORIGIN_METADATA', 'ORIGIN_DOWNLOAD', 'ORIGIN_ADMISSION'))


def need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_NATIVE_FUTURE_'+reason)


def validate_manifest(value):
    """Pin the two actual artifacts and the input producer without aliases."""
    if type(value) is dict and value.get('schema')==MANIFEST_SCHEMA_V4:
        from race_ai.all_existing_model_future_baseline import validate_pin
        need(set(value)=={'schema','candidate_cell_count','candidate_artifact_id','candidate_digest',
             'source_input_artifacts','horse_baseline_artifact'} and type(value['candidate_cell_count']) is int and
             value['candidate_cell_count']==19,'NINETEEN_MANIFEST_FIELDS')
        prior={key:deepcopy(item) for key,item in value.items() if key!='horse_baseline_artifact'}
        prior.update(schema=MANIFEST_SCHEMA_V3,candidate_cell_count=30);validate_manifest(prior)
        baseline=validate_pin(value['horse_baseline_artifact'])
        need(baseline['id'] not in {value['candidate_artifact_id'],*(p['id'] for p in value['source_input_artifacts'])},
             'DISTINCT_BASELINE_ARTIFACT_REQUIRED')
        return deepcopy(value)
    if type(value) is dict and value.get('schema')==MANIFEST_SCHEMA_V3:
        need(set(value)=={'schema','candidate_cell_count','candidate_artifact_id','candidate_digest',
             'source_input_artifacts'} and type(value['candidate_cell_count']) is int and
             value['candidate_cell_count']==30,'MANIFEST_FIELDS')
        need(type(value['candidate_artifact_id']) is int and value['candidate_artifact_id']>0 and
             type(value['candidate_digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',value['candidate_digest']),
             'MANIFEST_PINS')
        pins=value['source_input_artifacts'];seen={value['candidate_artifact_id']}
        need(type(pins) is list and 1<=len(pins)<=16,'SOURCE_ARTIFACT_BOUND')
        for pin in pins:
            need(type(pin) is dict and set(pin)=={'id','digest','run_id','head_sha'} and
                 all(type(pin[k]) is int and 0<pin[k]<10**20 for k in ('id','run_id')) and pin['id'] not in seen and
                 type(pin['digest']) is str and re.fullmatch('sha256:[a-f0-9]{64}',pin['digest']) and
                 type(pin['head_sha']) is str and future.HEAD.fullmatch(pin['head_sha']),'MANIFEST_PINS')
            seen.add(pin['id'])
        return deepcopy(value)
    need(type(value) is dict and ((value.get('schema') == MANIFEST_SCHEMA and set(value) == MANIFEST_FIELDS) or
         (value.get('schema') == MANIFEST_SCHEMA_V2 and set(value) == MANIFEST_FIELDS | {'candidate_cell_count'})), 'MANIFEST_FIELDS')
    if value['schema'] == MANIFEST_SCHEMA_V2:
        _expected_cells(value['candidate_cell_count'])
    need(all(type(value[k]) is int and value[k] > 0 for k in
             ('candidate_artifact_id', 'source_input_artifact_id', 'source_run_id')), 'MANIFEST_IDS')
    need(all(type(value[k]) is str and re.fullmatch(r'sha256:[a-f0-9]{64}', value[k]) for k in
             ('candidate_digest', 'source_input_digest')) and type(value['source_head_sha']) is str and
             future.HEAD.fullmatch(value['source_head_sha']), 'MANIFEST_PINS')
    need(value['candidate_artifact_id'] != value['source_input_artifact_id'], 'DISTINCT_ARTIFACTS')
    return deepcopy(value)



def _expected_cells(candidate_cell_count):
    need(type(candidate_cell_count) is int and candidate_cell_count in (12, 14), 'CANDIDATE_CELL_COUNT')
    cells = EXPECTED_CELLS if candidate_cell_count == 12 else ALL_BOAT_CELLS
    need(len(cells) == candidate_cell_count and EXPECTED_CELLS <= ALL_BOAT_CELLS and
         len(ALL_BOAT_CELLS-EXPECTED_CELLS) == 2, 'REGISTERED_BOAT_CELLS')
    return cells


def _manifest_count(manifest):
    # Leave the V1 dictionary untouched: its original digest remains exact.
    return 12 if manifest['schema'] == MANIFEST_SCHEMA else manifest['candidate_cell_count']


def _count_word(candidate_cell_count):
    return 'TWELVE' if candidate_cell_count == 12 else 'FOURTEEN'


def _retained_source_clocks(requests, now):
    """Keep source capture separate from a later native conversion clock."""
    clocks = {}; unknown = set()
    def visit(value):
        if type(value) is dict:
            rights = value.get('source_rights_ref')
            references = {value[k] for k in ('source_ref', 'source_url') if type(value.get(k)) is str}
            if type(rights) is str:
                for reference in references:
                    captured = value.get('captured_at')
                    if type(captured) is str:
                        need(future.stamp(captured) <= now, 'FUTURE_RETAINED_SOURCE_CAPTURE')
                        source = dict(source_ref=reference, source_rights_ref=rights, captured_at=captured,
                            source_sha256=value.get('source_sha256'), published_at=value.get('published_at'))
                        clocks[digest(source)] = source
                    else:
                        unknown.add((reference, rights))
            for child in value.values(): visit(child)
        elif type(value) is list:
            for child in value: visit(child)
    for request in requests: visit(request['native_payload'])
    need(bool(clocks), 'RETAINED_SOURCE_CAPTURE_REQUIRED')
    return [clocks[key] for key in sorted(clocks)], len(unknown)


def prepare_requests(context, source_verified_records, *, now, candidate_cell_count=12):
    """Select one complete future case from already authenticated records.

    This helper performs no authentication, source retrieval, encryption or
    clock adjustment. Its caller must first use the actual candidate reader
    and private-pairs artifact reader. All returned native payloads are exact
    copies of the admitted capsules, including their original capture clocks.
    """
    need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK')
    training = context['training']; verify_training(training)
    expected_cells = _expected_cells(candidate_cell_count)
    need(set(training['models']) == expected_cells, 'EXACT_'+_count_word(candidate_cell_count)+'_BOAT_CANDIDATE_CELLS')
    available_at = future.stamp(context['receipt']['created_at'])+timedelta(seconds=1)
    need(available_at <= now, 'CANDIDATE_NOT_YET_AVAILABLE')
    need(type(source_verified_records) is list and 0 < len(source_verified_records) <= 16_384, 'SOURCE_RECORDS')
    known = {c['cell_key'] for c in registry.cells()}; groups = {}
    for record in source_verified_records:
        capsules = record.get('captured_native_inputs', [])
        need(type(capsules) is list, 'SOURCE_CAPSULE_LIST')
        for capsule in capsules:
            need(type(capsule) is dict and set(capsule) == CAPSULE_FIELDS and
                 type(capsule['cell_key']) is str and capsule['cell_key'] in known and
                 type(capsule['native_payload']) is dict, 'SOURCE_CAPSULE_FIELDS')
            cell = capsule['cell_key']; sport, mid = cell.split('/', 1); native = capsule['native_payload']
            need(capsule['input_sha256'] == digest(native), 'SOURCE_INPUT_HASH')
            info = registry.identity(mid, sport, native)
            need(future.stamp(capsule['captured_as_of']) == future.stamp(info['as_of']) and
                 future.stamp(capsule['cutoff_at']) == future.stamp(info['cutoff_at']) and
                 future.stamp(info['as_of']) <= now, 'SOURCE_INPUT_CLOCK_BINDING')
            key = (sport, _race_key(info['race_id'], sport)); case = groups.setdefault(key, {})
            if cell in case:
                need(digest(case[cell][0]) == digest(capsule), 'CONFLICTING_SOURCE_CAPSULE')
            else:
                case[cell] = (deepcopy(capsule), info)
    # Exclude the entire fitted cohort, even when another cell uses a BOAT
    # alias for the same race. No held-out label becomes a future comparison.
    past = {_race_key(rid, model['sport']) for model in training['models'].values()
            for rid in model['train_race_ids']+model['validation_race_ids']}
    eligible = []
    for (sport, race), case in groups.items():
        if sport != 'boat': continue
        cutoff = min(future.stamp(info['cutoff_at']) for _, info in case.values())
        if now+MINIMUM_LEAD >= cutoff: continue
        need(expected_cells <= set(case), 'COMPLETE_'+_count_word(candidate_cell_count)+'_NATIVE_CELLS_REQUIRED')
        need(race not in past, 'ANY_CANDIDATE_COHORT_RACE_REUSED')
        first = next(iter(case.values()))[1]
        need(all(info['stage'] == 'P1' and info['scope'] == training['scope'] and
                 info['roster'] == first['roster'] and
                 future.stamp(info['cutoff_at']) == cutoff == future.stamp(info['race_cutoff_at'])
                 for _, info in case.values()), 'SAME_P1_NATIVE_RACE_REQUIRED')
        need(all(future.stamp(case[cell][1]['as_of']) >= available_at for cell in expected_cells),
             'NATIVE_INPUT_PRECEDES_CANDIDATE_AVAILABILITY')
        eligible.append((cutoff, race, case))
    if not eligible:
        return dict(state='HOLD_NO_COMPLETE_NATIVE_FUTURE_RACE_WITH_MARGIN', requests=[], source_audit={},
                    source_refs=[], source_requests=0)
    cutoff, race, case = min(eligible, key=lambda value:(value[0], value[1]))
    requests = [dict(cell_key=cell, native_payload=deepcopy(case[cell][0]['native_payload'])) for cell in sorted(case)]
    # The extra registered, unfitted sources are retained as capsules in the
    # same forecast carrier; they do not receive manufactured predictions.
    native_ages = [(now-future.stamp(info['as_of'])).total_seconds() for _, info in case.values()]
    source_clocks, unknown_clock_count = _retained_source_clocks(requests, now)
    ages = [(now-future.stamp(source['captured_at'])).total_seconds() for source in source_clocks]
    audit = dict(schema=PROVENANCE_SCHEMA, selected_at=now.isoformat(), race_id=race, sport='boat', stage='P1',
        cutoff_at=cutoff.isoformat(), source_native_input_count=len(case), fitted_native_input_count=candidate_cell_count,
        retained_unfitted_native_input_count=len(set(case)-expected_cells),
        source_age_seconds_min=min(ages), source_age_seconds_max=max(ages),
        source_age_basis='ACTUAL_SELECTION_TIME_MINUS_RETAINED_SOURCE_CAPTURE',
        native_input_age_seconds_min=min(native_ages), native_input_age_seconds_max=max(native_ages),
        source_capture_count=len(source_clocks), source_capture_clock_missing_count=unknown_clock_count,
        retained_source_clocks=source_clocks,
        provider_refetched=False, source_clocks_rewritten=False, candidate_available_at=available_at.isoformat(),
        capsules=[deepcopy(case[cell][0]) for cell in sorted(case)])
    allowed = set().union(*(_sources(request['native_payload']) for request in requests))
    return dict(state=_count_word(candidate_cell_count)+'_SAVED_NATIVE_FUTURE_REQUESTS_READY', requests=requests, source_audit=audit,
                source_refs=sorted(allowed), source_requests=0)


def candidate(manifest, *, phase=None):
    ident = manifest['candidate_artifact_id']
    future.mark(phase, 'CANDIDATE_DOWNLOAD')
    raw = future.gh('actions/artifacts/'+str(ident)+'/zip')
    def fetch(url):
        need(url == BASE+'/actions/artifacts/'+str(ident), 'CANDIDATE_METADATA_ROUTE')
        future.mark(phase, 'CANDIDATE_METADATA')
        actual = future.metadata(ident)
        future.mark(phase, 'CANDIDATE_ADMISSION')
        return actual
    future.mark(phase, 'CANDIDATE_ADMISSION')
    context = context_from_encrypted_artifact(raw, ident, now=future.utc_now(), _fetch=fetch)
    need(context['receipt']['digest'] == manifest['candidate_digest'], 'CANDIDATE_MANIFEST_DIGEST')
    if manifest['schema'] in (MANIFEST_SCHEMA_V3,MANIFEST_SCHEMA_V4):
        owner=_candidate_from_zip(raw).get('owner_research_record')
        _training_profile(context['training'],owner,require_owner=True,
            profile='V4' if manifest['schema']==MANIFEST_SCHEMA_V4 else 'V3')
        context['owner_research_record']=owner
    # This artifact may legitimately be produced by an earlier run. The
    # encrypted artifact reader, rather than the current-run identity, admits it.
    return context


def source(manifest, *, phase=None):
    ident = manifest['source_input_artifact_id']
    future.mark(phase, 'SOURCE_METADATA')
    actual = future.metadata(ident)
    need(actual.get('digest') == manifest['source_input_digest'], 'SOURCE_MANIFEST_DIGEST')
    future.mark(phase, 'SOURCE_DOWNLOAD')
    raw = future.gh('actions/artifacts/'+str(ident)+'/zip')
    future.mark(phase, 'SOURCE_ADMISSION')
    return _verified_private_pairs_artifact(raw, actual, now=future.utc_now(),
        expected_run_id=manifest['source_run_id'], expected_head_sha=manifest['source_head_sha'])


def local_records(root, *, candidate_cell_count=12):
    """Read actual local ciphertext and replay the explicitly selected cells."""
    from race_ai.all_existing_model_runtime import _private_directory, _private_file
    _private_directory(root)
    expected_cells = _expected_cells(candidate_cell_count)
    children = list(root.iterdir())
    need(len(children) == candidate_cell_count and all(re.fullmatch('[a-f0-9]{64}', p.name) for p in children),
         'EXACT_'+_count_word(candidate_cell_count)+'_OPAQUE_PARTITIONS')
    records = []
    for folder in sorted(children):
        _private_directory(folder)
        need({p.name for p in folder.iterdir()} == {'learning.enc', 'learning.json', 'summary.json'}, 'PARTITION_LAYOUT')
        for path in folder.iterdir(): _private_file(path)
        payload = read_candidate(folder)
        need(verify_private_record(payload) is True and 'pair' in payload and payload['pair']['stage'] == 'P1' and
             folder.name == record_partition_key(payload), 'PRIVATE_PAIR_READBACK')
        public = read_json_bytes(future._read(folder/'summary.json', 1024*1024, private=True))
        need(public == dict(payload['summary'], encrypted_readback_verified=True, plaintext_published=False), 'PARTITION_PUBLIC_BINDING')
        records.append(payload)
    need({p['cell_key'] for p in records} == expected_cells and
         len({_race_key(p['pair']['race_id'], 'boat') for p in records}) == 1 and
         len({p['training']['training_sha256'] for p in records}) == 1 and
         len({digest(p['training_receipt']) for p in records}) == 1, _count_word(candidate_cell_count)+'_SAME_RACE_CELLS')
    return records


def _lineage(manifest, prepared, admission):
    audit = prepared['source_audit']
    return dict(manifest_sha256=digest(manifest), **{k:manifest[k] for k in manifest if k != 'schema'},
        source_audit_sha256=digest(audit), source_input_saved_at=admission['saved_at'],
        source_native_input_count=audit['source_native_input_count'],
        retained_unfitted_native_input_count=audit['retained_unfitted_native_input_count'],
        source_age_seconds_min=audit['source_age_seconds_min'], source_age_seconds_max=audit['source_age_seconds_max'],
        source_age_basis=audit['source_age_basis'], source_age_measured_at=audit['selected_at'],
        native_input_age_seconds_min=audit['native_input_age_seconds_min'], native_input_age_seconds_max=audit['native_input_age_seconds_max'],
        source_capture_count=audit['source_capture_count'], source_capture_clock_missing_count=audit['source_capture_clock_missing_count'],
        provider_refetched=False)


def generate(manifest, root, env, *, phase=None):
    if manifest['schema']==MANIFEST_SCHEMA_V3:return _generate_v3(manifest,root,env,phase=phase)
    if manifest['schema']==MANIFEST_SCHEMA_V4:return _generate_v3(manifest,root,env,phase=phase,profile='V4')
    need(not root.exists(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    context = candidate(manifest, phase=phase)
    admission, records = source(manifest, phase=phase)
    future.mark(phase, 'BUILD_REQUESTS')
    count = _manifest_count(manifest)
    prepared = prepare_requests(context, records, now=future.utc_now(), candidate_cell_count=count)
    if not prepared['requests']:
        return dict(state=prepared['state'], ready=False, forecast_partition_count=0)
    allowed = {tuple(pair) for pair in prepared['source_refs']}
    future.mark(phase, 'SEAL_PAIRS')
    summary = make_private_pairs(context, prepared['requests'], root, now=future.utc_now(),
        allow_source=lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in allowed)
    need(summary.get('forecast_partition_count') == summary.get('partition_count') == count and
         summary.get('frozen_input_only_partition_count') == 0 and summary.get('encrypted_readback_verified') is True and
         summary.get('captured_native_input_count') == len(prepared['requests']), _count_word(count)+'_ENCRYPTED_PAIRS')
    future.mark(phase, 'LOCAL_READBACK')
    aggregate = read_json_bytes(future._read(root/'summary.json', 1024*1024, private=True))
    need(aggregate == summary, 'AGGREGATE_BINDING')
    (root/'summary.json').unlink()
    local = local_records(root, candidate_cell_count=count)
    cutoff = min(_seal_cutoff(p) for p in local)
    future.mark(phase, 'FINAL_MARGIN')
    need(future.utc_now()+MINIMUM_LEAD < cutoff, 'CUTOFF_MARGIN_ELAPSED')
    lineage = _lineage(manifest, prepared, admission)
    result = dict(lineage, schema=SCHEMA, state=_count_word(count)+'_FUTURE_P1_PAIRS_ENCRYPTED_LOCAL_ONLY', ready=True,
        forecast_partition_count=count, baseline_forecast_count=count, learned_forecast_count=count,
        captured_native_input_count=summary['captured_native_input_count'], cutoff_at=cutoff.isoformat(),
        training_sha256=context['training']['training_sha256'], encrypted_readback_verified=True,
        workflow_run_id=env['run_id'], expected_head_sha=env['head_sha'],
        local_record_sha256=sorted(digest(p) for p in local))
    future.mark(phase, 'SOURCE_PROVENANCE')
    # These private sidecars stay OUTSIDE the strict opaque upload tree. Logs
    # retain only their digest, source artifact pins, ages and aggregate counts.
    future.save(root.with_name(root.name+'.source.json'), future.wire(prepared['source_audit']))
    future.save(root.with_name(root.name+'.generation.json'), future.wire(result))
    return {k:v for k,v in result.items() if k != 'local_record_sha256'}


def readback(ident, manifest, root, env, *, phase=None,readback_origin_artifact=None):
    if manifest['schema']==MANIFEST_SCHEMA_V3:
        return _readback_v3(ident,manifest,root,env,phase=phase,origin_ident=readback_origin_artifact)
    if manifest['schema']==MANIFEST_SCHEMA_V4:
        return _readback_v3(ident,manifest,root,env,phase=phase,origin_ident=readback_origin_artifact,profile='V4')
    need(readback_origin_artifact is None,'ORIGIN_V_THREE_ONLY')
    future.mark(phase, 'LOCAL_READBACK')
    count = _manifest_count(manifest)
    local = local_records(root, candidate_cell_count=count)
    future.mark(phase, 'GENERATION_BINDING')
    previous = read_json_bytes(future._read(root.with_name(root.name+'.generation.json'), 128*1024, private=True))
    audit = read_json_bytes(future._read(root.with_name(root.name+'.source.json'), 32*1024*1024, private=True))
    need(previous.get('schema') == SCHEMA and previous.get('ready') is True and
         previous.get('workflow_run_id') == env['run_id'] and previous.get('expected_head_sha') == env['head_sha'] and
         previous.get('manifest_sha256') == digest(manifest) and
         all(previous.get(k) == manifest[k] for k in manifest if k != 'schema') and
         previous.get('source_audit_sha256') == digest(audit) and
         previous.get('local_record_sha256') == sorted(digest(p) for p in local) and
         previous.get('training_sha256') == local[0]['training']['training_sha256'] and
         previous.get('candidate_artifact_id') == local[0]['training_receipt']['id'] and
         previous.get('candidate_digest') == local[0]['training_receipt']['digest'], 'GENERATION_STATUS_BINDING')
    # The retained source audit must also match the actual encrypted capsules;
    # it cannot substitute a different source input after local generation.
    capsules = [capsule for record in local for capsule in record.get('captured_native_inputs', [])]
    need(sorted(digest(c) for c in capsules) == sorted(digest(c) for c in audit['capsules']), 'SOURCE_PROVENANCE_BINDING')
    future.mark(phase, 'PAIR_ARTIFACT_METADATA')
    actual = future.metadata(ident)
    need(actual.get('name') == f'all-existing-model-pairs-{env["run_id"]}-{ROUND}', 'PAIR_ARTIFACT_NAME')
    future.mark(phase, 'PAIR_ARTIFACT_DOWNLOAD')
    raw = future.gh('actions/artifacts/'+str(ident)+'/zip')
    future.mark(phase, 'PAIR_ARTIFACT_ADMISSION')
    admission, records = _verified_private_pairs_artifact(raw, actual, now=future.utc_now(),
        expected_run_id=env['run_id'], expected_head_sha=env['head_sha'])
    need(future.stamp(actual['created_at'])+timedelta(seconds=1)+MINIMUM_LEAD <
         min(_seal_cutoff(record) for record in records), 'ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED')
    need(admission['forecast_partition_count'] == admission['partition_count'] == count and
         admission['frozen_input_only_partition_count'] == 0 and
         admission['captured_native_input_count'] == previous['captured_native_input_count'] and
         {digest(p) for p in records} == {digest(p) for p in local}, 'ACTUAL_'+_count_word(count)+'_PAIR_READBACK')
    lineage = {k:previous[k] for k in _lineage(manifest, dict(source_audit=audit),
               dict(saved_at=previous['source_input_saved_at']))}
    return dict(lineage, state=_count_word(count)+'_FUTURE_P1_PAIRS_ACTUAL_PRE_CUTOFF_VERIFIED', ready=True,
        forecast_partition_count=count, baseline_forecast_count=count, learned_forecast_count=count,
        captured_native_input_count=admission['captured_native_input_count'], cutoff_at=previous['cutoff_at'],
        artifact_id=ident, artifact_digest=actual['digest'], saved_at=actual['created_at'],
        independent_pre_cutoff_receipt_verified=True, encrypted_readback_verified=True,
        training_sha256=records[0]['training']['training_sha256'])


def _training_v3(training,owner=None,*,require_owner=False):
    from race_ai import all_existing_model_research as research
    from race_ai.official_order_only_result import EVALUATION_SCOPE
    verify_training(training)
    cells=set().union(*V3_CELLS.values())
    need(len(cells)==30 and {sport:len(value) for sport,value in V3_CELLS.items()}==
         dict(boat=14,autorace=6,keirin=5,horse=5) and set(training['models'])==cells,'EXACT_THIRTY_CANDIDATE_CELLS')
    need(training.get('common_eight_per_sport') is True and training.get('required_common_cells')==30 and
         training.get('record_count')==240 and training.get('cohort_counts_by_sport')==
         dict(boat=8,autorace=8,keirin=8,horse=8) and training.get('label_evaluation_scope')==EVALUATION_SCOPE and
         training.get('training_basis')=='OWNER_PERSONAL_RESEARCH' and all(
             (model['unique_races'],model['train_races'],model['validation_races'])==(8,6,2)
             for model in training['models'].values()),'THIRTY_COMMON_OWNER_SCOPE')
    if owner is None and not require_owner:return
    need(type(owner) is dict and set(owner)=={'schema','decision','mac'} and owner.get('schema')==research.ORDER_SCHEMA and
         type(owner.get('decision')) is dict and set(owner['decision'])==research.FIELDS|{'label_evaluation_scope'},
         'OWNER_V_TWO_RECORD_REQUIRED')
    decision=owner['decision'];clock=future.stamp(training['created_at'])
    need(type(owner['mac']) is str and re.fullmatch('[a-f0-9]{64}',owner['mac']) and
         hmac.compare_digest(owner['mac'],research._mac(decision,schema=research.ORDER_SCHEMA)) and
         decision['repository_id']=='1416489937' and decision['basis']=='OWNER_PERSONAL_RESEARCH' and
         decision['purpose']==research.ORDER_PURPOSE and decision['instruction_ref']==research.INSTRUCTION and
         decision['label_evaluation_scope']==EVALUATION_SCOPE and all(decision[k] is False for k in research.FALSE_FIELDS) and
         future.stamp(decision['issued_at'])<=clock<future.stamp(decision['expires_at']) and
         digest(owner)==training.get('owner_research_decision_sha256') and
         decision['intake_sha256']==training.get('owner_bound_intake_sha256') and
         decision['source_content_sha256']==training.get('source_content_sha256') and
         decision['registry_sha256']==training['registry_sha256'] and
         sorted(decision['registered_model_ids'])==sorted(training['registered_model_ids']) and
         decision['model_cells']==sorted(c['cell_key'] for c in registry.cells()), 'OWNER_V_TWO_TRAINING_BINDING')


def _training_v4(training,owner=None,*,require_owner=False):
    from race_ai import all_existing_model_research as research
    verify_training(training);cells=set().union(*V4_CELLS.values())
    need(len(cells)==19 and set(training['models'])==cells and
         training.get('training_basis')=='OWNER_PERSONAL_RESEARCH' and
         'common_eight_per_sport' not in training and 'label_evaluation_scope' not in training and
         sum(len(model['source_lineage']) for model in training['models'].values())==152,
         'EXACT_NINETEEN_ORDINARY_OWNER_SCOPE')
    cohorts={}
    for cell,model in training['models'].items():
        sport=model['sport'];need((model['unique_races'],model['train_races'],model['validation_races'])==(8,6,2),
            'NINETEEN_EIGHT_SIX_TWO_COHORT')
        cohort=(frozenset(_race_key(race,sport) for race in model['train_race_ids']),
            frozenset(_race_key(race,sport) for race in model['validation_race_ids']),
            frozenset((_race_key(row['race_id'],sport),future.stamp(row['cutoff_at']),row['result_sha256'])
                for row in model['source_lineage']))
        need(sport not in cohorts or cohorts[sport]==cohort,'NINETEEN_SAME_SPORT_COHORT')
        cohorts[sport]=cohort
        need(all('native_generation_evidence' in row and 'input_derivation' not in row and
             (sport!='boat' or row['native_generation_evidence']['stage']=='P1')
             for row in model['source_lineage']),'NINETEEN_ORIGINAL_NATIVE_RECEIPTS_REQUIRED')
    if owner is None and not require_owner:return
    from race_ai.all_existing_model_future_baseline import verify_owner
    verify_owner(training,owner,schema=research.SCHEMA)


def _training_profile(training,owner=None,*,require_owner=False,profile='V3'):
    need(profile in ('V3','V4'),'FUTURE_PROTOCOL')
    return (_training_v3 if profile=='V3' else _training_v4)(training,owner,require_owner=require_owner)


def _profile_cells(profile):
    need(profile in ('V3','V4'),'FUTURE_PROTOCOL')
    return V3_CELLS if profile=='V3' else V4_CELLS


def _baseline_context_v4(manifest,context):
    from race_ai.all_existing_model_future_baseline import load_baseline
    baseline=load_baseline(manifest['horse_baseline_artifact'],now=future.utc_now(),fetch_metadata=future.metadata,
        fetch_zip=lambda ident:future.gh('actions/artifacts/'+str(ident)+'/zip'))
    need(baseline['receipt']['id']!=context['receipt']['id'] and
         future.stamp(baseline['receipt']['created_at'])+timedelta(seconds=1)<=
         future.stamp(context['training']['created_at']),'DISTINCT_PRE_FIT_BASELINE_REQUIRED')
    return baseline


def source_v3(manifest,*,phase=None):
    admissions=[];records=[];total=0
    for pin in manifest['source_input_artifacts']:
        future.mark(phase,'SOURCE_METADATA');actual=future.metadata(pin['id'])
        need(actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'],'SOURCE_MANIFEST_DIGEST')
        future.mark(phase,'SOURCE_DOWNLOAD');raw=future.gh('actions/artifacts/'+str(pin['id'])+'/zip')
        total+=len(raw);need(total<=256*1024*1024,'SOURCE_ARCHIVE_TOTAL_BOUND')
        future.mark(phase,'SOURCE_ADMISSION')
        admission,parts=_verified_private_pairs_artifact(raw,actual,now=future.utc_now(),
            expected_run_id=pin['run_id'],expected_head_sha=pin['head_sha'])
        admissions.append(admission);records.extend(parts)
        need(len(records)<=16384,'SOURCE_RECORDS')
    return admissions,records


def prepare_requests_v3(context,source_verified_records,*,now,profile='V3',baseline_context=None):
    """Select exact original capsules after actual source/candidate admission."""
    from race_ai.four_sport_learning import LEARNED_ID
    need(type(now) is datetime and now.utcoffset() is not None,'AWARE_CLOCK')
    training=context['training'];_training_profile(training,context.get('owner_research_record'),profile=profile)
    cell_sets=_profile_cells(profile)
    available=future.stamp(context['receipt']['created_at'])+timedelta(seconds=1)
    need(available<=now,'CANDIDATE_NOT_YET_AVAILABLE')
    need(type(source_verified_records) is list and 0<len(source_verified_records)<=16384,'SOURCE_RECORDS')
    expected=set().union(*cell_sets.values());groups={};past={(model['sport'],_race_key(race,model['sport']))
        for model in training['models'].values() for race in model['train_race_ids']+model['validation_race_ids']}
    for record in source_verified_records:
        capsules=record.get('captured_native_inputs',[]);need(type(capsules) is list,'SOURCE_CAPSULE_LIST')
        for capsule in capsules:
            need(type(capsule) is dict and set(capsule)==CAPSULE_FIELDS and capsule.get('cell_key') in
                 {c['cell_key'] for c in registry.cells()} and type(capsule.get('native_payload')) is dict,'SOURCE_CAPSULE_FIELDS')
            cell=capsule['cell_key'];sport,mid=cell.split('/',1);native=capsule['native_payload']
            need(capsule['input_sha256']==digest(native),'SOURCE_INPUT_HASH')
            if cell not in expected:continue
            info=registry.identity(mid,sport,native)
            need(future.stamp(capsule['captured_as_of'])==future.stamp(info['as_of']) and
                 future.stamp(capsule['cutoff_at'])==future.stamp(info['cutoff_at']) and
                 future.stamp(info['as_of'])<=now,'SOURCE_INPUT_CLOCK_BINDING')
            key=(sport,_race_key(info['race_id'],sport));case=groups.setdefault(key,{})
            origin=dict(source_record_sha256=digest(record),original_generated_at=record.get('generated_at'),cell_key=cell,
                input_sha256=capsule['input_sha256'])
            need(type(origin['original_generated_at']) is str and future.stamp(origin['original_generated_at'])<=now,
                 'SOURCE_GENERATION_CLOCK')
            if cell in case:need(digest(case[cell][0])==digest(capsule),'CONFLICTING_SOURCE_CAPSULE')
            else:case[cell]=(deepcopy(capsule),info,[])
            case[cell][2].append(origin)
            if record.get('cell_key')==cell and record.get('training',{}).get('training_sha256')==training['training_sha256']:
                origin['already_forecast_with_candidate']=True
    selected=[];held={};counts={sport:0 for sport in cell_sets};comparisons={}
    for sport,cells in cell_sets.items():
        cases=[]
        for (kind,race),case in groups.items():
            if kind!=sport:continue
            cutoff=min(future.stamp(info['race_cutoff_at']) for _,info,_ in case.values())
            if now+MINIMUM_LEAD<cutoff:cases.append((cutoff,race,case))
        reason='HOLD_NO_COMPLETE_NATIVE_FUTURE_RACE_WITH_MARGIN';unavailable=sorted(cells)
        for cutoff,race,case in sorted(cases,key=lambda value:(value[0],value[1])):
            if not cells<=set(case):reason='HOLD_INCOMPLETE_NATIVE_CELLS';unavailable=sorted(cells-set(case));continue
            first=case[next(iter(cells))][1]
            if not all(info['scope']==training['scope'] and info['roster']==first['roster'] and
                future.stamp(info['cutoff_at'])==cutoff==future.stamp(info['race_cutoff_at']) and
                (sport!='boat' or info['stage']=='P1') for _,info,_ in case.values()):
                reason='HOLD_NATIVE_RACE_ROSTER_CUTOFF_CONFLICT';continue
            if (sport,race) in past:reason='HOLD_CANDIDATE_COHORT_RACE_REUSED';continue
            if any(origin.get('already_forecast_with_candidate') for _,_,origins in case.values() for origin in origins):
                reason='HOLD_ALREADY_FROZEN_WITH_CANDIDATE';continue
            ranker=case[sport+'/'+LEARNED_ID][0]['native_payload']
            if type(ranker.get('learned_model')) is not dict:
                reason='HOLD_MISSING_NATIVE_BASELINE';unavailable=[sport+'/'+LEARNED_ID];continue
            if profile=='V4' and sport=='horse':
                if baseline_context is None:
                    reason='HOLD_MISSING_AUTHENTICATED_RESEARCH_BASELINE';unavailable=[sport+'/'+LEARNED_ID];continue
                from race_ai.all_existing_model_future_baseline import verify_attachment
                try:
                    for origin in case[sport+'/'+LEARNED_ID][2]:
                        verify_attachment(ranker,baseline_context,sport=sport,now=now,
                            generated_at=origin['original_generated_at'])
                except (ValueError,KeyError,TypeError,AttributeError):
                    reason='HOLD_NATIVE_BASELINE_ATTACHMENT_INVALID';unavailable=[sport+'/'+LEARNED_ID];continue
            model=training['models'][sport+'/'+LEARNED_ID]['native_training'];asof=future.stamp(case[sport+'/'+LEARNED_ID][1]['as_of'])
            if asof<=future.stamp(model['trained_until']) or future.stamp(model['created_at'])>asof:
                reason='HOLD_NATIVE_INPUT_PRECEDES_MODEL_CLOCK';unavailable=[sport+'/'+LEARNED_ID];continue
            allowed=set().union(*(_sources(case[cell][0]['native_payload']) for cell in cells))
            analysis=lambda ref,rights,purpose:purpose=='analysis' and (ref,rights) in allowed
            failure=False
            for cell in sorted(cells):
                native=case[cell][0]['native_payload'];member=training['models'][cell];mid=cell.split('/',1)[1]
                try:
                    registry.predict(mid,sport,native,None,at=now,allow_source=analysis)
                    registry.predict(mid,sport,native,member['parameters'],at=now,allow_source=analysis,
                        native_training=member['native_training'])
                except (ValueError,KeyError,TypeError,AttributeError):failure=True;unavailable=[cell];break
            if failure:reason='HOLD_NATIVE_BASELINE_OR_CANDIDATE_NOT_EXECUTABLE';continue
            selected.append((sport,race,cutoff,case));counts[sport]=len(cells)
            if profile=='V4':comparisons[sport]=dict(
                baseline_model_sha256=ranker['learned_model']['model_sha256'],candidate_model_sha256=model['model_sha256'],
                ranker_parameters_identical=ranker['learned_model'].get('weights')==model.get('weights'),
                improvement_claimed=False)
            break
        if counts[sport]==0:held[sport]=dict(reason=reason,unavailable_source_cells=unavailable,not_generated_cells=sorted(cells))
    requests=[dict(cell_key=cell,native_payload=deepcopy(case[cell][0]['native_payload']))
        for sport,_,_,case in selected for cell in sorted(cell_sets[sport])]
    capsules=[deepcopy(case[cell][0]) for sport,_,_,case in selected for cell in sorted(cell_sets[sport])]
    origins={digest(origin):deepcopy(origin) for sport,_,_,case in selected for cell in cell_sets[sport] for origin in case[cell][2]}
    clocks,unknown=_retained_source_clocks(requests,now) if requests else ([],0)
    audit=dict(schema='RACE_AI_ALL_NATIVE_FUTURE_PROVENANCE_V3',selected_at=now.isoformat(),
        candidate_available_at=available.isoformat(),capsules=capsules,original_source_partitions=[origins[k] for k in sorted(origins)],
        selected_cases=[dict(sport=sport,race_id=race,cutoff_at=cutoff.isoformat()) for sport,race,cutoff,_ in selected],
        retained_source_clocks=clocks,source_capture_clock_missing_count=unknown,source_clocks_rewritten=False,
        native_input_clocks_rewritten=False,provider_refetched=False,
        owner_research_record=deepcopy(context.get('owner_research_record')))
    if profile=='V4':
        audit['schema']='RACE_AI_ALL_NATIVE_FUTURE_PROVENANCE_V4'
        audit['horse_baseline_receipt']=deepcopy(baseline_context['receipt']) if baseline_context else None
    result=dict(requests=requests,source_audit=audit,source_refs=sorted(set().union(*(_sources(r['native_payload'])
        for r in requests))) if requests else [],forecast_counts_by_sport=counts,held_sports=held,
        source_requests=0)
    result['all_thirty_cells_produced' if profile=='V3' else 'all_nineteen_cells_produced']=sum(counts.values())==len(expected)
    if profile=='V4':result['ranker_comparisons']=comparisons
    return result


def local_records_v3(root,*,profile='V3'):
    from race_ai.all_existing_model_runtime import _private_directory,_private_file
    _private_directory(root);children=list(root.iterdir())
    cell_sets=_profile_cells(profile)
    need(1<=len(children)<=sum(map(len,cell_sets.values())) and
         all(re.fullmatch('[a-f0-9]{64}',p.name) for p in children),'THIRTY_OR_PARTIAL_OPAQUE_PARTITIONS')
    records=[];cases={}
    for folder in sorted(children):
        _private_directory(folder);need({p.name for p in folder.iterdir()}=={'learning.enc','learning.json','summary.json'},'PARTITION_LAYOUT')
        for path in folder.iterdir():_private_file(path)
        payload=read_candidate(folder)
        need(verify_private_record(payload) is True and 'pair' in payload and folder.name==record_partition_key(payload),'PRIVATE_PAIR_READBACK')
        public=read_json_bytes(future._read(folder/'summary.json',1024*1024,private=True))
        need(public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False),'PARTITION_PUBLIC_BINDING')
        sport=payload['pair']['sport'];need(sport in cell_sets,'THIRTY_SPORT')
        cases.setdefault(sport,[]).append(payload);records.append(payload)
    for sport,parts in cases.items():
        need(len(parts)==len(cell_sets[sport]) and {p['cell_key'] for p in parts}==cell_sets[sport] and
             len({_race_key(p['pair']['race_id'],sport) for p in parts})==1,'COMPLETE_SPORT_PAIR_CELLS')
    need(len({p['training']['training_sha256'] for p in records})==1 and
         len({digest(p['training_receipt']) for p in records})==1,'SAME_THIRTY_CANDIDATE')
    _training_profile(records[0]['training'],profile=profile)
    return records


def _generation_mac_v3(value):
    from race_ai.boat_pdca_state import state_key
    domain=(b'RACE_AI_ALL_NATIVE_FUTURE_GENERATION_V4' if value.get('future_protocol')=='V4_FIXED_NINETEEN_V1'
        else b'RACE_AI_ALL_NATIVE_FUTURE_GENERATION_V3')
    key=hmac.digest(state_key('production'),domain,'sha256')
    return hmac.digest(key,future.wire({k:v for k,v in value.items() if k!='owner_generation_mac'}),'sha256').hex()


def _origin_name_v3(env):
    return f'all-native-future-origin-{env["run_id"]}-{ORIGIN_ROUND}'


def _origin_bundle_v3(manifest,generation,audit):
    return dict(schema=ORIGIN_SCHEMA,manifest=deepcopy(manifest),generation=deepcopy(generation),source_audit=deepcopy(audit))


def _open_origin_v3(raw,manifest,generation,audit,env):
    header=origin_store.forecast_header(raw)
    need(header['run_id']==str(env['run_id']) and header['round_no']==ORIGIN_ROUND,'ORIGIN_HEADER_BINDING')
    bundle=origin_store.open_forecasts(raw)
    need(type(bundle) is dict and set(bundle)=={'schema','manifest','generation','source_audit'} and
         bundle==_origin_bundle_v3(manifest,generation,audit) and bundle['schema']==ORIGIN_SCHEMA and
         generation.get('manifest_sha256')==digest(manifest) and generation.get('source_audit_sha256')==digest(audit) and
         generation.get('workflow_run_id')==env['run_id'] and generation.get('expected_head_sha')==env['head_sha'] and
         type(generation.get('owner_generation_mac')) is str and
         hmac.compare_digest(generation['owner_generation_mac'],_generation_mac_v3(generation)),'ORIGIN_BUNDLE_BINDING')
    need(future.stamp(audit['selected_at'])<=future.stamp(generation['origin_generated_at'])<=future.utc_now(),
         'ORIGIN_GENERATION_CLOCK')
    return bundle


def _local_origin_v3(root,manifest,generation,audit,env):
    from race_ai.all_existing_model_runtime import _private_directory
    folder=root.with_name(root.name+'.origin');_private_directory(folder)
    need({path.name for path in folder.iterdir()}=={'origin.enc'},'ORIGIN_PRIVATE_LAYOUT')
    raw=future._read(folder/'origin.enc',origin_store.MAX_WIRE,private=True)
    return raw,_open_origin_v3(raw,manifest,generation,audit,env)


def _seal_origin_v3(manifest,generation,audit,root,env):
    folder=root.with_name(root.name+'.origin')
    need(not folder.exists() and not folder.is_symlink(),'ORIGIN_EXISTS_DO_NOT_RESET')
    bundle=_origin_bundle_v3(manifest,generation,audit)
    need(len(future.wire(bundle))-1<=origin_store.MAX_PLAIN,'ORIGIN_PLAIN_BOUND')
    raw=origin_store.seal_forecasts(bundle,run_id=str(env['run_id']),round_no=ORIGIN_ROUND)
    need(_open_origin_v3(raw,manifest,generation,audit,env)==bundle,'ORIGIN_LOCAL_READBACK')
    future.private_root(folder);future.save(folder/'origin.enc',raw)
    restored,_=_local_origin_v3(root,manifest,generation,audit,env)
    need(restored==raw,'ORIGIN_LOCAL_BYTES')
    return dict(origin_ready=True,origin_artifact_name=_origin_name_v3(env),origin_cipher_sha256=sha256(raw).hexdigest())


def _origin_artifact_v3(ident,manifest,root,env,generation,audit,*,phase=None):
    local,_=_local_origin_v3(root,manifest,generation,audit,env)
    future.mark(phase,'ORIGIN_METADATA');actual=future.metadata(ident);run=actual.get('workflow_run')
    need(type(ident) is int and ident>0 and actual.get('id')==ident and actual.get('expired') is False and
         actual.get('name')==_origin_name_v3(env) and type(run) is dict and type(run.get('id')) is int and
         run['id']==env['run_id'] and run.get('head_sha')==env['head_sha'] and
         all(type(run.get(field)) is int and run[field]==1416489937 for field in
             ('repository_id','head_repository_id')),'ORIGIN_ACTUAL_IDENTITY')
    saved=future.stamp(actual['created_at']);now=future.utc_now()
    need(saved<=now<future.stamp(actual['expires_at']),'ORIGIN_ACTUAL_CLOCK')
    need(future.stamp(generation['origin_generated_at'])<saved+timedelta(seconds=1),'ORIGIN_PRE_CUTOFF_CLOCK_BINDING')
    need(saved+timedelta(seconds=1)+MINIMUM_LEAD<future.stamp(generation['cutoff_at']),
         'ORIGIN_ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED')
    need(type(actual.get('size_in_bytes')) is int and 0<actual['size_in_bytes']<=origin_store.MAX_WIRE+1024*1024 and
         type(actual.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}',actual['digest']),'ORIGIN_ACTUAL_BYTES')
    future.mark(phase,'ORIGIN_DOWNLOAD');raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    need(type(raw) is bytes and 0<len(raw)<=origin_store.MAX_WIRE+1024*1024 and
         type(actual.get('size_in_bytes')) is int and actual['size_in_bytes']==len(raw) and
         actual.get('digest')=='sha256:'+sha256(raw).hexdigest(),'ORIGIN_ACTUAL_BYTES')
    future.mark(phase,'ORIGIN_ADMISSION')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist();need(len(entries)==1,'ORIGIN_ONE_MEMBER_REQUIRED')
            entry=entries[0]
            need(entry.filename==entry.orig_filename=='origin.enc' and not entry.flag_bits&0x41 and
                 stat.S_IFMT(entry.external_attr>>16) in (0,stat.S_IFREG) and
                 entry.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) and
                 0<entry.file_size<=origin_store.MAX_WIRE,'ORIGIN_MEMBER_INVALID')
            with archive.open(entry) as stream:cipher=stream.read(origin_store.MAX_WIRE+1)
            need(len(cipher)==entry.file_size and cipher==local,'ORIGIN_IMMUTABLE_BYTES')
    except (zipfile.BadZipFile,RuntimeError,EOFError,zlib.error):
        raise ValueError('ALL_MODEL_NATIVE_FUTURE_ORIGIN_ZIP_INVALID') from None
    _open_origin_v3(cipher,manifest,generation,audit,env)
    return dict(origin_artifact_id=ident,origin_artifact_digest=actual['digest'],origin_saved_at=actual['created_at'],
        origin_cipher_sha256=sha256(cipher).hexdigest(),origin_local_only=False,
        independent_origin_receipt_verified=True)


def _local_member_hashes_v3(root):
    return {str(path.relative_to(root)):sha256(future._read(path,MEMBER_LIMITS[path.name],private=True)).hexdigest()
        for folder in sorted(root.iterdir()) for path in sorted(folder.iterdir())}


def _archive_member_hashes_v3(raw):
    # The existing pair-artifact reader admits every member and its bounds first.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        return {entry.filename:sha256(archive.read(entry)).hexdigest() for entry in archive.infolist()}


def _generate_v3(manifest,root,env,*,phase=None,profile='V3'):
    need(not root.exists() and not root.with_name(root.name+'.origin').exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    context=candidate(manifest,phase=phase)
    baseline=_baseline_context_v4(manifest,context) if profile=='V4' else None
    admissions,records=source_v3(manifest,phase=phase)
    future.mark(phase,'BUILD_REQUESTS');prepared=prepare_requests_v3(context,records,now=future.utc_now(),
        profile=profile,baseline_context=baseline)
    complete_key='all_thirty_cells_produced' if profile=='V3' else 'all_nineteen_cells_produced'
    word='THIRTY' if profile=='V3' else 'NINETEEN';target=sum(map(len,_profile_cells(profile).values()))
    public={key:prepared[key] for key in ('forecast_counts_by_sport','held_sports',complete_key)}
    if profile=='V4':public['ranker_comparisons']=prepared['ranker_comparisons']
    if not prepared['requests']:return dict(public,state='HOLD_NO_COMPLETE_'+word+'_NATIVE_FUTURE_CASE',ready=False,
        forecast_partition_count=0,origin_ready=False,origin_artifact_name=_origin_name_v3(env),
        independent_origin_receipt_verified=False,complete_independent_receipts_verified=False,origin_local_only=True)
    allowed={tuple(pair) for pair in prepared['source_refs']};count=len(prepared['requests'])
    future.mark(phase,'SEAL_PAIRS')
    summary=make_private_pairs({key:context[key] for key in ('training','receipt')},prepared['requests'],root,now=future.utc_now(),
        allow_source=lambda ref,rights,purpose:purpose=='analysis' and (ref,rights) in allowed)
    need(summary.get('forecast_partition_count')==summary.get('partition_count')==count and
         summary.get('frozen_input_only_partition_count')==0 and summary.get('captured_native_input_count')==count,
         'THIRTY_OR_PARTIAL_ENCRYPTED_PAIRS')
    need(read_json_bytes(future._read(root/'summary.json',1024*1024,private=True))==summary,'AGGREGATE_BINDING')
    (root/'summary.json').unlink();local=local_records_v3(root,profile=profile);cutoff=min(_seal_cutoff(p) for p in local)
    need(future.utc_now()+MINIMUM_LEAD<cutoff,'CUTOFF_MARGIN_ELAPSED')
    audit=prepared['source_audit'];audit['source_admissions']=admissions
    need(len(future.wire(audit))<=32*1024*1024,'SOURCE_AUDIT_BOUND')
    result=dict(public,schema=SCHEMA,state=word+'_CANDIDATE_FUTURE_PAIRS_ENCRYPTED_LOCAL_ONLY',ready=True,
        candidate_cell_count=target,candidate_artifact_id=manifest['candidate_artifact_id'],candidate_digest=manifest['candidate_digest'],
        source_input_artifacts=manifest['source_input_artifacts'],manifest_sha256=digest(manifest),source_audit_sha256=digest(audit),
        forecast_partition_count=count,baseline_forecast_count=count,learned_forecast_count=count,captured_native_input_count=count,
        cutoff_at=cutoff.isoformat(),training_sha256=context['training']['training_sha256'],workflow_run_id=env['run_id'],
        expected_head_sha=env['head_sha'],encrypted_readback_verified=True,local_record_sha256=sorted(digest(p) for p in local),
        local_member_sha256=_local_member_hashes_v3(root),origin_ready=True,origin_artifact_name=_origin_name_v3(env),
        independent_origin_receipt_verified=False,complete_independent_receipts_verified=False,origin_local_only=True,
        origin_generated_at=future.utc_now().isoformat())
    if profile=='V4':result.update(future_protocol='V4_FIXED_NINETEEN_V1',
        horse_baseline_artifact=deepcopy(manifest['horse_baseline_artifact']))
    result['owner_generation_mac']=_generation_mac_v3(result)
    future.save(root.with_name(root.name+'.source.json'),future.wire(audit))
    future.save(root.with_name(root.name+'.generation.json'),future.wire(result))
    future.mark(phase,'SEAL_ORIGIN');origin=_seal_origin_v3(manifest,result,audit,root,env)
    return dict({key:value for key,value in result.items() if key not in
        ('local_record_sha256','local_member_sha256','owner_generation_mac')},**origin)


def _readback_v3(ident,manifest,root,env,*,phase=None,origin_ident=None,profile='V3'):
    previous=read_json_bytes(future._read(root.with_name(root.name+'.generation.json'),128*1024,private=True))
    audit=future.runtime._json(future._read(root.with_name(root.name+'.source.json'),32*1024*1024,private=True),32*1024*1024)
    need(type(previous.get('owner_generation_mac')) is str and re.fullmatch('[a-f0-9]{64}',previous['owner_generation_mac']) and
         hmac.compare_digest(previous['owner_generation_mac'],_generation_mac_v3(previous)),'GENERATION_PROVENANCE_MAC')
    actual=future.metadata(ident);need(actual.get('name')==f'all-existing-model-pairs-{env["run_id"]}-{ROUND}','PAIR_ARTIFACT_NAME')
    need(future.stamp(actual['created_at'])+timedelta(seconds=1)+MINIMUM_LEAD<future.stamp(previous['cutoff_at']),
         'ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED')
    origin=dict(origin_local_only=True,independent_origin_receipt_verified=False,complete_independent_receipts_verified=False)
    if origin_ident is not None:
        origin.update(_origin_artifact_v3(origin_ident,manifest,root,env,previous,audit,phase=phase))
    else:
        local_origin,_=_local_origin_v3(root,manifest,previous,audit,env)
        origin['origin_cipher_sha256']=sha256(local_origin).hexdigest()
    local=local_records_v3(root,profile=profile)
    need(all(future.stamp(record['generated_at'])<=future.stamp(previous['origin_generated_at']) for record in local),
         'ORIGIN_FORECAST_GENERATION_CLOCK')
    need(previous.get('ready') is True and previous.get('manifest_sha256')==digest(manifest) and
         previous.get('candidate_artifact_id')==manifest['candidate_artifact_id']==local[0]['training_receipt']['id'] and
         previous.get('candidate_digest')==manifest['candidate_digest']==local[0]['training_receipt']['digest'] and
         previous.get('source_input_artifacts')==manifest['source_input_artifacts'] and
         previous.get('workflow_run_id')==env['run_id'] and previous.get('expected_head_sha')==env['head_sha'] and
         previous.get('source_audit_sha256')==digest(audit) and
         previous.get('training_sha256')==local[0]['training']['training_sha256'] and
         previous.get('local_record_sha256')==sorted(digest(p) for p in local) and
         previous.get('local_member_sha256')==_local_member_hashes_v3(root),'GENERATION_STATUS_BINDING')
    _training_profile(local[0]['training'],audit.get('owner_research_record'),require_owner=True,profile=profile)
    capsules=[c for p in local for c in p.get('captured_native_inputs',[])]
    need(sorted(digest(c) for c in capsules)==sorted(digest(c) for c in audit['capsules']),'SOURCE_PROVENANCE_BINDING')
    cell_sets=_profile_cells(profile);target=sum(map(len,cell_sets.values()))
    counts={sport:sum(p['pair']['sport']==sport for p in local) for sport in cell_sets}
    complete_key='all_thirty_cells_produced' if profile=='V3' else 'all_nineteen_cells_produced'
    need(previous.get('forecast_counts_by_sport')==counts and previous.get(complete_key)==(len(local)==target) and
         set(previous.get('held_sports',{}))=={sport for sport,count in counts.items() if count==0} and
         {(p['pair']['sport'],_race_key(p['pair']['race_id'],p['pair']['sport'])) for p in local}==
         {(case['sport'],case['race_id']) for case in audit['selected_cases']},'PARTIAL_SPORT_BINDING')
    if profile=='V4':
        from race_ai.all_existing_model_future_baseline import verify_attachment
        need(previous.get('future_protocol')=='V4_FIXED_NINETEEN_V1' and previous.get('candidate_cell_count')==19 and
             previous.get('horse_baseline_artifact')==manifest['horse_baseline_artifact'],'NINETEEN_GENERATION_BINDING')
        baseline=_baseline_context_v4(manifest,dict(training=local[0]['training'],receipt=local[0]['training_receipt']))
        need(audit.get('horse_baseline_receipt')==baseline['receipt'],'NINETEEN_BASELINE_RECEIPT_BINDING')
        for capsule in capsules:
            if capsule['cell_key']=='horse/multisport-chronological-ranker-v1':
                origins=[o for o in audit['original_source_partitions'] if o['cell_key']==capsule['cell_key'] and
                    o['input_sha256']==capsule['input_sha256']]
                need(bool(origins),'NINETEEN_BASELINE_ORIGINAL_GENERATION_REQUIRED')
                for original in origins:verify_attachment(capsule['native_payload'],baseline,sport='horse',
                    now=future.utc_now(),generated_at=original['original_generated_at'])
        comparisons={}
        from race_ai.four_sport_learning import LEARNED_ID
        for record in local:
            if record['cell_key'].split('/',1)[1]!=LEARNED_ID:continue
            sport=record['pair']['sport'];old=record['native_payload']['learned_model']
            new=record['training']['models'][record['cell_key']]['native_training']
            comparisons[sport]=dict(baseline_model_sha256=old['model_sha256'],candidate_model_sha256=new['model_sha256'],
                ranker_parameters_identical=old.get('weights')==new.get('weights'),improvement_claimed=False)
        need(previous.get('ranker_comparisons')==comparisons,'NINETEEN_RANKER_IDENTITY_BINDING')
    raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    admission,parts=_verified_private_pairs_artifact(raw,actual,now=future.utc_now(),
        expected_run_id=env['run_id'],expected_head_sha=env['head_sha'])
    need(future.stamp(actual['created_at'])+timedelta(seconds=1)+MINIMUM_LEAD<min(_seal_cutoff(p) for p in parts),
         'ACTUAL_SAVE_CUTOFF_MARGIN_ELAPSED')
    need(admission['forecast_partition_count']==admission['partition_count']==len(local) and
         admission['frozen_input_only_partition_count']==0 and admission['captured_native_input_count']==len(capsules) and
         sorted(digest(p) for p in parts)==sorted(digest(p) for p in local) and
         _archive_member_hashes_v3(raw)==previous['local_member_sha256'],'ACTUAL_THIRTY_OR_PARTIAL_PAIR_READBACK')
    result={key:value for key,value in previous.items() if key not in
        ('local_record_sha256','local_member_sha256','owner_generation_mac')}
    origin['complete_independent_receipts_verified']=origin['independent_origin_receipt_verified']
    result.update(state=('THIRTY' if profile=='V3' else 'NINETEEN')+'_CANDIDATE_FUTURE_PAIRS_ACTUAL_PRE_CUTOFF_VERIFIED',artifact_id=ident,
        artifact_digest=actual['digest'],saved_at=actual['created_at'],independent_pre_cutoff_receipt_verified=True,**origin)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--readback-artifact', type=int)
    parser.add_argument('--readback-origin-artifact', type=int)
    args = parser.parse_args(argv)
    result = dict(schema=SCHEMA, state='HOLD_NATIVE_FUTURE', ready=False, forecast_partition_count=0,
        independent_pre_cutoff_receipt_verified=False, source_requests=0, plaintext_published=False,
        production_promoted=False, actual_purchases=False, accuracy_improvement_proven=False)
    status = None; current_phase = ['ENVIRONMENT']
    def phase(name): current_phase[0] = name if name in PHASES else 'UNKNOWN_PHASE'
    try:
        env = future.environment(phase=phase)
        phase('OUTPUT_PATH'); root = future.output_path(args.out_dir, env)
        status = root.with_name(root.name+'.status.json')
        result.update(artifact_name=f'all-existing-model-pairs-{env["run_id"]}-{ROUND}',
                      expected_head_sha=env['head_sha'], workflow_run_id=env['run_id'])
        phase('MANIFEST')
        manifest = validate_manifest(read_json_bytes(future._read(args.manifest, 8192)))
        if manifest['schema'] in (MANIFEST_SCHEMA_V3,MANIFEST_SCHEMA_V4):
            result.update(origin_ready=False,origin_artifact_name=_origin_name_v3(env),
                independent_origin_receipt_verified=False,complete_independent_receipts_verified=False,origin_local_only=True)
        need(args.readback_origin_artifact is None or
             (manifest['schema'] in (MANIFEST_SCHEMA_V3,MANIFEST_SCHEMA_V4) and args.readback_artifact is not None),
             'ORIGIN_REQUIRES_V_THREE_PAIR_READBACK')
        readback_options=dict(phase=phase)
        if args.readback_origin_artifact is not None:readback_options['readback_origin_artifact']=args.readback_origin_artifact
        result.update(readback(args.readback_artifact, manifest, root, env, **readback_options) if args.readback_artifact is not None
                      else generate(manifest, root, env, phase=phase))
    except Exception as exc:
        reason = str(exc)
        result.update(state='HOLD_NATIVE_FUTURE', ready=False, reason=reason if re.fullmatch(
            r'ALL_MODEL_NATIVE_FUTURE_[A-Z_]{1,100}', reason) else 'NATIVE_FUTURE_OPERATION_REJECTED',
            failure_phase=current_phase[0], **future.safe_diagnostic(exc))
    if status is not None: future.save(status, future.wire(result), replace=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('ready='+str(result['ready']).lower()+'\n')
            if result.get('artifact_name'): stream.write('artifact_name='+result['artifact_name']+'\n')
            if result.get('expected_head_sha'): stream.write('expected_head_sha='+result['expected_head_sha']+'\n')
            if 'origin_ready' in result:
                stream.write('origin_ready='+str(result['origin_ready']).lower()+'\n')
                stream.write('origin_artifact_name='+result['origin_artifact_name']+'\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
