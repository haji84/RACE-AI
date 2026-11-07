"""Prepare/read back twelve or fourteen BOAT P1 pairs from authenticated saved native inputs.

Only GitHub artifact reads occur here. Retained source observations keep their
original bytes and clocks; these new predictions require their own actual
pre-cutoff artifact receipt. No source-provider fetch or model fit occurs.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import json
import os
import re

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai.all_existing_model_learning import _sources, verify_training
from race_ai.all_existing_model_pairs import CAPSULE_FIELDS, make_private_pairs, record_partition_key, verify_private_record, _seal_cutoff
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.boat_venue_learning import read_candidate
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.existing_model_dispatch import _race_key
from race_ai.github_freeze_receipt import BASE
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future

ROUND = 900004
MANIFEST_SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V1'
MANIFEST_SCHEMA_V2 = 'RACE_AI_ALL_NATIVE_FUTURE_INPUT_V2'
SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_COUNTS_V1'
PROVENANCE_SCHEMA = 'RACE_AI_ALL_NATIVE_FUTURE_PROVENANCE_V1'
MANIFEST_FIELDS = {'schema', 'candidate_artifact_id', 'candidate_digest', 'source_input_artifact_id',
                   'source_input_digest', 'source_run_id', 'source_head_sha'}
FITTED_GROUPS = frozenset(('shared', 'shared_learned', 'boat_full', 'boat_observed', 'boat_ab', 'boat_clite'))
EXPECTED_CELLS = frozenset(c['cell_key'] for c in registry.cells() if c['sport'] == 'boat' and c['group'] in FITTED_GROUPS)
ALL_BOAT_CELLS = frozenset(c['cell_key'] for c in registry.cells() if c['sport'] == 'boat' and c['group'] != 'seller')
MINIMUM_LEAD = timedelta(minutes=10)
PHASES = future.SAFE_PHASES | frozenset(('MANIFEST', 'SOURCE_METADATA', 'SOURCE_DOWNLOAD', 'SOURCE_ADMISSION',
                                       'SOURCE_PROVENANCE', 'GENERATION_BINDING'))


def need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_NATIVE_FUTURE_'+reason)


def validate_manifest(value):
    """Pin the two actual artifacts and the input producer without aliases."""
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


def readback(ident, manifest, root, env, *, phase=None):
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--readback-artifact', type=int)
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
        result.update(readback(args.readback_artifact, manifest, root, env, phase=phase) if args.readback_artifact is not None
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
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
