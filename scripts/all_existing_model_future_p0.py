"""Prepare/read back nine private future P0 pairs using saved GitHub inputs only."""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
import time

from race_ai.actions_contract import digest
from race_ai import boat_model_runtime as runtime
from race_ai.all_existing_model_learning import _sources
from race_ai.all_existing_model_pairs import make_private_pairs, verify_private_record, record_partition_key, _seal_cutoff
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.boat_pdca_state import state_key
from race_ai.boat_private_original_archive import open_original_zip
from race_ai.boat_venue_dataset import readback_dataset
from race_ai.boat_venue_learning import read_candidate, _pin
from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
from race_ai.github_freeze_receipt import BASE
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts.boat_all_model_cycle import gh, _read, _receipt
from scripts.boat_history_collect import private_root, save
from scripts.boat_saved_view_feed import git_auth

ROOT = Path(__file__).resolve().parents[1]
ROUND = 900001
SCHEMA = 'RACE_AI_ALL_EXISTING_MODEL_FUTURE_P0_COUNTS_V1'
HEAD = re.compile(r'[a-f0-9]{40}\Z')


def need(ok, reason):
    if not ok:
        raise ValueError('ALL_MODEL_FUTURE_P0_CLI_'+reason)


def utc_now():
    return datetime.now(timezone.utc)


def stamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return parsed


def wire(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()


def environment():
    state_key('production')
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI'
         and os.environ.get('GITHUB_REPOSITORY_ID') == '1416489937', 'TRUSTED_ACTIONS_REQUIRED')
    run = os.environ.get('GITHUB_RUN_ID', '')
    need(re.fullmatch(r'[1-9][0-9]{0,19}', run), 'CURRENT_RUN_REQUIRED')
    temp = Path(os.environ.get('RUNNER_TEMP', ''))
    need(temp.is_absolute() and temp.is_dir() and not any(p.is_symlink() for p in (temp, *temp.parents))
         and not temp.resolve().is_relative_to(ROOT.resolve()), 'PRIVATE_TEMP_REQUIRED')
    actual = read_json_bytes(gh('actions/runs/'+run))
    need(type(actual) is dict and actual.get('id') == int(run) and type(actual.get('head_sha')) is str
         and HEAD.fullmatch(actual['head_sha']) and all(type(actual.get(k)) is dict and
         actual[k].get('id') == 1416489937 and actual[k].get('full_name') == 'haji84/RACE-AI'
         for k in ('repository', 'head_repository')), 'ACTUAL_RUN_IDENTITY_REQUIRED')
    return dict(run_id=int(run), head_sha=actual['head_sha'], temp=temp)


def output_path(value, env):
    path = Path(value).absolute()
    need('..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)) and
         path != env['temp'] and path.resolve().is_relative_to(env['temp'].resolve()) and
         not any((p/'.git').exists() for p in (path, *path.parents)), 'PRIVATE_OUTPUT_REQUIRED')
    # RUNNER_TEMP itself may have the runner's normal directory permissions.
    # Native payloads live only in the fresh 0700 child and 0600 files.
    if path.parent != env['temp']:
        private_root(path.parent)
    return path


def metadata(ident):
    need(type(ident) is int and ident > 0, 'ARTIFACT_ID_REQUIRED')
    value = read_json_bytes(gh('actions/artifacts/'+str(ident)))
    need(type(value) is dict and value.get('id') == ident, 'ACTUAL_METADATA_REQUIRED')
    return value


def candidate(ident, env):
    raw = gh('actions/artifacts/'+str(ident)+'/zip')
    # The existing reader obtains independently fetched metadata after owner
    # decryption. No caller-authored receipt is substituted for that request.
    context = context_from_encrypted_artifact(raw, ident, now=utc_now(),
        _fetch=lambda url: metadata(ident) if url == BASE+'/actions/artifacts/'+str(ident) else None)
    receipt = context['receipt']; run = receipt['workflow_run']
    need(run['id'] == env['run_id'] and run['head_sha'] == env['head_sha'] and re.fullmatch(
        r'(boat-venue-learning|all-existing-model-learning)-'+str(env['run_id'])+r'-[1-9][0-9]*', receipt['name']),
        'CURRENT_CANDIDATE_ARTIFACT_REQUIRED')
    return context


def original_p0(files):
    need('p0-source.json' in files, 'CURRENT_P0_PACKET_MISSING')
    packet = read_json_bytes(_read(files['p0-source.json'], runtime.FILE_LIMITS['p0-source.json'], private=True))
    need(type(packet) is dict and set(packet) == {'document', 'receipt'}, 'P0_PACKET_SCHEMA')
    proof = packet['receipt']; ident = proof.get('artifact_id') if type(proof) is dict else None
    actual = metadata(ident); raw = gh('actions/artifacts/'+str(ident)+'/zip')
    need(actual.get('digest') == 'sha256:'+sha256(raw).hexdigest() and
         actual.get('size_in_bytes') == len(raw) and actual.get('expired') is False and
         stamp(actual['created_at']) <= utc_now() < stamp(actual['expires_at']), 'P0_ACTUAL_BYTES_OR_CLOCK')
    with open_original_zip(raw, actual, expected_kind='P0', max_plain_zip_bytes=runtime.FILE_LIMITS['p0-source.json']) as archive:
        need(archive.namelist() == ['forecasts.json'], 'P0_ORIGINAL_MEMBER_REQUIRED')
        document = read_json_bytes(archive.read('forecasts.json'))
    need(digest(document) == digest(packet['document']) and _receipt(actual, document) == proof,
         'P0_RUNTIME_ORIGINAL_BINDING')
    return document, proof


def local_records(root):
    from race_ai.all_existing_model_runtime import _private_directory, _private_file
    _private_directory(root)
    children = list(root.iterdir())
    need(len(children) == 9 and all(re.fullmatch('[a-f0-9]{64}', p.name) for p in children),
         'EXACT_NINE_OPAQUE_PARTITIONS_REQUIRED')
    records = []
    for folder in sorted(children):
        _private_directory(folder)
        need({p.name for p in folder.iterdir()} == {'learning.enc', 'learning.json', 'summary.json'}, 'PARTITION_LAYOUT')
        for path in folder.iterdir(): _private_file(path)
        payload = read_candidate(folder)
        need(verify_private_record(payload) is True and 'pair' in payload and payload['pair']['stage'] == 'P0'
             and folder.name == record_partition_key(payload), 'PRIVATE_PAIR_READBACK')
        public = read_json_bytes(_read(folder/'summary.json', 1024*1024, private=True))
        need(public == dict(payload['summary'], encrypted_readback_verified=True, plaintext_published=False),
             'PARTITION_PUBLIC_BINDING')
        records.append(payload)
    need(len({p['cell_key'] for p in records}) == 9 and len({p['pair']['race_id'] for p in records}) == 1,
         'EXACT_NINE_SAME_RACE_CELLS_REQUIRED')
    return records


def generate(ident, root, env):
    from race_ai.all_existing_model_future_p0 import build_future_p0_requests
    need(not root.exists(), 'OUTPUT_EXISTS_DO_NOT_RESET')
    context = candidate(ident, env)
    pointer = read_json_bytes(_read(ROOT/runtime.INPUT_PATH, 64*1024)); runtime._validate_pointer(pointer)
    git_auth()  # Existing process-scoped GitHub credential; restore performs reads only.
    with tempfile.TemporaryDirectory(prefix='future-p0-private-', dir=env['temp']) as temporary:
        private = Path(temporary)
        restored = runtime.restore_runtime(pointer, ROOT, private/'runtime')
        files = restored['files']; document, proof = original_p0(files)
        baseline = read_json_bytes(_read(files['ranker.json'], runtime.FILE_LIMITS['ranker.json'], private=True))
        dataset_options = {}; source_refs = _sources(document)
        dataset_path = ROOT/'audit/state/boat-venue-dataset-input.json'
        if dataset_path.exists():
            dataset_pointer = read_json_bytes(_read(dataset_path, 8192)); dataset_url = _pin(dataset_pointer)
            need(context['training'].get('venue_dataset_sha256') == dataset_pointer['dataset_sha256'], 'DATASET_CANDIDATE_BINDING')
            report = readback_dataset(dataset_pointer, private/'dataset', ROOT)
            need(report.get('status') == 'ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED' and
                 report.get('plaintext_published') is False, 'DATASET_READBACK_REQUIRED')
            from race_ai.boat_venue_feature_adapter import RIGHTS
            source_refs.add((dataset_url, RIGHTS))
            dataset_options = dict(dataset_folder=private/'dataset', dataset_pointer=dataset_pointer,
                                   dataset_verified_at=utc_now().isoformat())
        # GitHub created_at has one-second precision. Wait for actual time;
        # never move a supplied clock or receipt forward to clear this guard.
        ready_at = stamp(context['receipt']['created_at'])+timedelta(seconds=1)
        remaining = (ready_at-utc_now()).total_seconds()
        if remaining > 0:
            need(remaining <= 2, 'CANDIDATE_RECEIPT_FROM_FUTURE')
            time.sleep(remaining+.02)
        now = utc_now()
        need(now >= ready_at, 'CANDIDATE_RECEIPT_PRECISION_WINDOW')
        def analysis(ref, rights, purpose):
            return purpose == 'analysis' and (ref, rights) in source_refs
        prepared = build_future_p0_requests(document, proof, now=now, baseline_ranker=baseline,
            training=context['training'], allow_source=analysis, **dataset_options)
        if not prepared['requests']:
            return dict(state=prepared['state'], ready=False, forecast_partition_count=0)
        need(len(prepared['requests']) == 9, 'NINE_REQUESTS_REQUIRED')
        allowed = {tuple(pair) for pair in prepared['source_refs']}
        need(allowed <= source_refs, 'SOURCE_CLOSURE_REQUIRED')
        summary = make_private_pairs(context, prepared['requests'], root, now=utc_now(),
            allow_source=lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in allowed)
        need(summary.get('forecast_partition_count') == summary.get('partition_count') == 9 and
             summary.get('frozen_input_only_partition_count') == 0 and summary.get('encrypted_readback_verified') is True,
             'NINE_ENCRYPTED_PAIRS_REQUIRED')
        # The aggregate is stored outside the upload tree. Only opaque codec
        # partitions may enter the all-or-none independently admitted ZIP.
        aggregate = read_json_bytes(_read(root/'summary.json', 1024*1024, private=True))
        need(aggregate == summary, 'AGGREGATE_BINDING')
        (root/'summary.json').unlink()
        records = local_records(root)
        cutoff = min(_seal_cutoff(p) for p in records)
        need(utc_now()+timedelta(minutes=10) < cutoff, 'CUTOFF_MARGIN_ELAPSED')
        return dict(state='NINE_FUTURE_P0_PAIRS_ENCRYPTED_LOCAL_ONLY', ready=True,
            forecast_partition_count=9, baseline_forecast_count=9, learned_forecast_count=9,
            captured_native_input_count=summary['captured_native_input_count'], cutoff_at=cutoff.isoformat(),
            training_sha256=context['training']['training_sha256'], candidate_artifact_id=ident,
            encrypted_readback_verified=True, source_audit_sha256=digest(prepared['source_audit']),
            runtime_pointer=pointer, runtime_pointer_sha256=digest(pointer),
            venue_enriched=bool(dataset_options))


def readback(ident, root, env):
    local = local_records(root)
    actual = metadata(ident); raw = gh('actions/artifacts/'+str(ident)+'/zip')
    need(actual.get('name') == f'all-existing-model-pairs-{env["run_id"]}-{ROUND}', 'PAIR_ARTIFACT_NAME')
    admission, records = _verified_private_pairs_artifact(raw, actual, now=utc_now(),
        expected_run_id=env['run_id'], expected_head_sha=env['head_sha'])
    need(admission['forecast_partition_count'] == admission['partition_count'] == 9 and
         admission['frozen_input_only_partition_count'] == 0 and
         {digest(p) for p in records} == {digest(p) for p in local}, 'ACTUAL_NINE_PAIR_READBACK_REQUIRED')
    return dict(state='NINE_FUTURE_P0_PAIRS_ACTUAL_PRE_CUTOFF_VERIFIED', ready=True,
        forecast_partition_count=9, baseline_forecast_count=9, learned_forecast_count=9,
        artifact_id=ident, artifact_digest=actual['digest'], saved_at=actual['created_at'],
        independent_pre_cutoff_receipt_verified=True, encrypted_readback_verified=True,
        training_sha256=records[0]['training']['training_sha256'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument('--candidate-artifact', type=int)
    command.add_argument('--readback-artifact', type=int)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args(argv)
    result = dict(schema=SCHEMA, state='HOLD_FUTURE_P0', ready=False,
        forecast_partition_count=0, independent_pre_cutoff_receipt_verified=False,
        source_requests=0, plaintext_published=False, production_promoted=False,
        actual_purchases=False, accuracy_improvement_proven=False)
    status = None
    try:
        env = environment(); root = output_path(args.out_dir, env)
        status = root.with_name(root.name+'.status.json')
        result.update(artifact_name=f'all-existing-model-pairs-{env["run_id"]}-{ROUND}',
                      expected_head_sha=env['head_sha'], workflow_run_id=env['run_id'])
        result.update(generate(args.candidate_artifact, root, env) if args.candidate_artifact else
                      readback(args.readback_artifact, root, env))
    except Exception as exc:
        reason = str(exc)
        result.update(state='HOLD_FUTURE_P0', ready=False, reason=reason if re.fullmatch(
            r'ALL_MODEL_FUTURE_P0(?:_CLI)?_[A-Z_]{1,100}', reason) else 'FUTURE_P0_OPERATION_REJECTED')
    if status is not None:
        save(status, wire(result), replace=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('ready='+str(result['ready']).lower()+'\n')
            if result.get('artifact_name'): stream.write('artifact_name='+result['artifact_name']+'\n')
            if result.get('expected_head_sha'): stream.write('expected_head_sha='+result['expected_head_sha']+'\n')
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
