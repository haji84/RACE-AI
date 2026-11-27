"""Persist a study with the existing pinned-owner codec and an external hash.

Public output contains only validated model parameters, allowlisted aggregates,
and ciphertext. The complete study (including calibration IDs and originals)
is compressed and sealed, never copied to a public directory as plaintext.
Restoring requires the existing owner's private key and a separately retained
manifest SHA. Neither a hash nor successful encryption authenticates sources.
"""
from __future__ import annotations

import argparse
import base64
import gzip
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tarfile
import tempfile

from .model import RankModel, digest
from .policy import RACE_TIMEZONE, checked_day, checked_sha, clock, require
from .runtime import _canonical, _private_path, _write
from .view import CANDIDATES, _project, render_report

SCHEMA = 'DT_R1_ENCRYPTED_STUDY_BUNDLE_V1'
CHUNK_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
CORE_FILES = ('aggregate_report.json', 'evaluation_contract.json', 'frozen_model.json',
              'selection_receipt.json', 'pre_test_freeze.json',
              'test_forecasts.private.json', 'test_registry.private.json', 'test_outcomes.private.json')
CALIBRATION_KEYS = ('trifecta_1', 'trifecta_2', 'trifecta_4', 'trifecta_9',
                    'trifecta_12', 'exacta_1', 'exacta_2')
ALLOWED_FILES = frozenset(CORE_FILES + ('discovery_receipt.json',) +
    tuple(n + '.model.json' for n in CANDIDATES) + tuple(k + '.calibration.json' for k in CALIBRATION_KEYS))


def _read(path, limit=MAX_FILE_BYTES):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'BUNDLE_FILE_MISSING_OR_SYMLINK')
    require(0 < path.stat().st_size <= limit, 'BUNDLE_FILE_SIZE_INVALID')
    data = path.read_bytes()
    require(0 < len(data) <= limit, 'BUNDLE_FILE_SIZE_CHANGED')
    return data


def _hash_file(path):
    h, size = sha256(), 0
    with Path(path).open('rb') as handle:
        while block := handle.read(1024 * 1024):
            size += len(block); h.update(block)
    return h.hexdigest(), size


def validate_public_model(model):
    """Reject free-form metadata or names before copying an unchanged model."""
    from .features import FEATURE_NAMES
    from .context import EXTRA_NAMES
    from .agari import AGARI_NAMES
    from .abilities import ABILITY_NAMES, VERSION as ABILITY_VERSION
    RankModel.from_dict(model)
    require(set(model) == set('schema model_id feature_names pair_names mean scale weights pair_weights temperature fit_meta model_sha256'.split()),
            'PUBLIC_MODEL_FIELDS_INVALID')
    allowed_names = set(FEATURE_NAMES + EXTRA_NAMES + AGARI_NAMES + ABILITY_NAMES)
    require(set(model['feature_names']) <= allowed_names, 'PUBLIC_FEATURE_NAMES_INVALID')
    meta = model['fit_meta']
    dates = {'fit_before_day', 'training_first_day', 'training_last_day', 'parameter_information_end_day'}
    counts = {'training_races', 'input_races', 'no_top3_label', 'iterations'}
    flags = {'use_pairs', 'optimizer_converged', 'feature_digest_required'}
    scalar = dates | counts | flags | {'ridge', 'objective', 'training_fingerprint', 'created_at',
                                      'cohort', 'optimizer_message', 'feature_mask'}
    nested = {'temperature_calibration': {'start_day', 'end_day', 'loss', 'races'},
              'selection': {'candidate', 'period', 'criterion', 'contract_sha256'},
              'context': {'analysis_at', 'current_geometry_for_history_is_assumption',
                          'venue_file_sha256', 'timing_file_sha256', 'weather_file_sha256'},
              'five_abilities': {'version', 'discovery_selected', 'discovery_receipt_sha256'}}
    require(isinstance(meta, dict) and set(meta) <= scalar | set(nested) | {'source_code_sha256'}, 'PUBLIC_MODEL_METADATA_FIELDS')
    for key, value in meta.items():
        if key in dates:
            checked_day(value)
        elif key in counts:
            require(type(value) is int and value >= 0, 'PUBLIC_MODEL_COUNT_INVALID')
        elif key in flags:
            require(type(value) is bool, 'PUBLIC_MODEL_FLAG_INVALID')
        elif key in ('ridge', 'objective'):
            require(type(value) in (int, float) and math.isfinite(value), 'PUBLIC_MODEL_NUMBER_INVALID')
        elif key == 'training_fingerprint':
            checked_sha(value)
        elif key == 'created_at':
            clock(value)
        elif key == 'cohort':
            require(value in {'retrospective_archived_inputs_no_pre_cutoff_attestation', 'prospective'}, 'PUBLIC_MODEL_COHORT_INVALID')
        elif key == 'optimizer_message':
            require(value in {'CONVERGENCE: RELATIVE REDUCTION OF F <= FACTR*EPSMCH',
                              'CONVERGENCE: NORM OF PROJECTED GRADIENT <= PGTOL',
                              'STOP: TOTAL NO. OF ITERATIONS REACHED LIMIT',
                              'STOP: TOTAL NO. OF F,G EVALUATIONS EXCEEDS LIMIT', 'ABNORMAL: '},
                    'PUBLIC_OPTIMIZER_MESSAGE_INVALID')
        elif key == 'feature_mask':
            require(isinstance(value, list) and len(value) == len(model['feature_names']) and all(type(v) is bool for v in value),
                    'PUBLIC_FEATURE_MASK_INVALID')
        elif key == 'source_code_sha256':
            allowed_code = {p.name for p in Path(__file__).parent.glob('*.py')}
            require(isinstance(value, dict) and set(value) <= allowed_code, 'PUBLIC_CODE_NAMES_INVALID')
            for item in value.values(): checked_sha(item)
        else:
            require(isinstance(value, dict) and set(value) <= nested[key], 'PUBLIC_MODEL_NESTED_FIELDS')
            for name, item in value.items():
                if name.endswith('sha256'):
                    if item is not None: checked_sha(item)
                elif name.endswith('_day'):
                    checked_day(item)
                elif name.endswith('_at'):
                    clock(item)
                elif name == 'candidate':
                    require(item in CANDIDATES, 'PUBLIC_CANDIDATE_INVALID')
                elif name == 'period':
                    require(item == 'tune', 'PUBLIC_SELECTION_PERIOD_INVALID')
                elif name == 'criterion':
                    require(item == 'joint_top3_log_loss', 'PUBLIC_SELECTION_CRITERION_INVALID')
                elif name == 'discovery_selected':
                    require(isinstance(item, list) and set(item) <= set(ABILITY_NAMES), 'PUBLIC_DISCOVERY_NAMES_INVALID')
                elif name == 'version':
                    require(item == ABILITY_VERSION, 'PUBLIC_ABILITY_VERSION_INVALID')
                elif name == 'current_geometry_for_history_is_assumption':
                    require(type(item) is bool, 'PUBLIC_CONTEXT_FLAG_INVALID')
                else:
                    require(type(item) in (int, float) and math.isfinite(item), 'PUBLIC_METADATA_NUMBER_INVALID')
    return model


def _study(directory):
    directory = _private_path(directory)
    names = sorted(p.name for p in directory.iterdir())
    require(set(CORE_FILES) <= set(names) and set(names) <= ALLOWED_FILES, 'STUDY_FILES_INCOMPLETE_OR_UNEXPECTED')
    inspected = {}
    def document(name):
        raw = _read(directory / name)
        inspected[name] = (sha256(raw).hexdigest(), len(raw))
        return json.loads(raw)
    model = document('frozen_model.json')
    validate_public_model(model)
    report = document('aggregate_report.json')
    checked_sha(report.get('source_audit', {}).get('dataset_sha256'), 'BUNDLE_DATASET_SHA_REQUIRED')
    contract = document('evaluation_contract.json')
    freeze = document('pre_test_freeze.json')
    require(report.get('production_promoted') is False, 'RESEARCH_ONLY_REQUIRED')
    require(report.get('model_sha256') == freeze.get('model_sha256') == model['model_sha256'], 'BUNDLE_MODEL_BINDING_MISMATCH')
    expected_contract = digest({k: v for k, v in contract.items() if k != 'contract_sha256'})
    require(expected_contract == contract.get('contract_sha256') == freeze.get('contract_sha256') ==
            report.get('evaluation_contract', {}).get('contract_sha256'), 'BUNDLE_CONTRACT_BINDING_MISMATCH')
    require(report['evaluation_contract'] == contract, 'BUNDLE_EMBEDDED_CONTRACT_MISMATCH')
    require(digest(report['source_audit']) == contract['source_audit_sha256'], 'BUNDLE_SOURCE_AUDIT_MISMATCH')
    selected = document('selection_receipt.json')
    require(selected.get('model_sha256') == model['model_sha256'] and selected.get('selected') == report.get('selected_candidate'),
            'BUNDLE_SELECTION_BINDING_MISMATCH')
    require(selected.get('test_results_consulted') is False, 'BUNDLE_SELECTION_NOT_FROZEN')
    if model['fit_meta'].get('selection'):
        chosen = model['fit_meta']['selection']
        require(chosen.get('candidate') == report.get('selected_candidate') and
                chosen.get('contract_sha256') == contract['contract_sha256'], 'BUNDLE_FITTED_SELECTION_MISMATCH')
    from .calibration import _check_artifact
    for key, expected in freeze.get('calibration_sha256', {}).items():
        require(key in CALIBRATION_KEYS, 'BUNDLE_CALIBRATOR_NAME_INVALID')
        artifact = document(key + '.calibration.json')
        _check_artifact(artifact)
        require(digest(artifact) == expected and artifact['lineage']['model_sha256'] == model['model_sha256'],
                'BUNDLE_CALIBRATOR_BINDING_MISMATCH')
    actual_cal = {p[:-len('.calibration.json')] for p in names if p.endswith('.calibration.json')}
    require(actual_cal == set(freeze.get('calibration_sha256', {})), 'BUNDLE_CALIBRATOR_SET_MISMATCH')
    files, total = [], 0
    for name in names:
        path = directory / name
        require(path.is_file() and not path.is_symlink(), 'BUNDLE_FILE_MISSING_OR_SYMLINK')
        hashed, size = _hash_file(path)
        require(name not in inspected or inspected[name] == (hashed, size), 'STUDY_CHANGED_DURING_INSPECTION')
        require(0 < size <= MAX_FILE_BYTES, 'BUNDLE_FILE_SIZE_INVALID')
        total += size
        require(total <= MAX_TOTAL_BYTES, 'BUNDLE_TOTAL_SIZE_EXCEEDED')
        files.append({'file': name, 'sha256': hashed, 'bytes': size})
    return model, report, contract, files


class _HashedReader:
    """Bind the actual bytes consumed by tar, including a concurrent replacement."""
    def __init__(self, handle):
        self.handle, self.hash, self.size = handle, sha256(), 0

    def read(self, size):
        block = self.handle.read(size)
        self.hash.update(block); self.size += len(block)
        return block


def public_projection(report):
    out = _project(report)
    out['schema'] = 'dt-r1-public-evidence-v1'
    out['scope'] = 'REUSED_RETROSPECTIVE_ARCHIVE_NOT_FUTURE_PROOF'
    out['production_promoted'] = False
    out['selection_losses'] = {name: float(cell['tune_joint_top3_log_loss'])
        for name, cell in report.get('candidate_selection', {}).items()
        if name in CANDIDATES and type(cell.get('tune_joint_top3_log_loss')) in (float, int)
        and math.isfinite(cell['tune_joint_top3_log_loss'])}
    counts = report.get('five_abilities', {})
    out['five_abilities'] = {key: counts[key] for key in ('feature_count', 'reviewed_motion_races',
        'competition_proxy_races', 'discovery_score_count') if type(counts.get(key)) is int and counts[key] >= 0}
    out['five_abilities']['physical_energy_measured'] = False
    from .abilities import ABILITY_NAMES
    out['five_abilities']['discovered_feature_names'] = [name for name in counts.get('discovered_feature_names', []) if name in ABILITY_NAMES]
    return out


def export_study(directory, destination, owner_public_pem, *, now=None, chunk_bytes=CHUNK_BYTES):
    from race_ai import keirin_official_run_history as codec
    require(type(chunk_bytes) is int and 1024 <= chunk_bytes <= CHUNK_BYTES, 'BUNDLE_CHUNK_BOUND_INVALID')
    directory = _private_path(directory)
    model, report, contract, files = _study(directory)
    codec.storage.checked_public_key(owner_public_pem)
    at = now or datetime.now(timezone.utc).isoformat()
    day = clock(at).astimezone(RACE_TIMEZONE).date().isoformat()
    identity = digest({'model_sha256': model['model_sha256'], 'files': files})
    dest = Path(destination)
    require(not dest.is_symlink() and not dest.exists(), 'BUNDLE_DESTINATION_EXISTS_NO_REPLACE')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.mkdir(mode=0o700)
    manifest = {'schema': SCHEMA, 'bundle_id': identity, 'created_at': at, 'day': day,
        'owner_spki_sha256': codec.storage.PINNED_OWNER_SPKI_SHA256,
        'model_sha256': model['model_sha256'], 'contract_sha256': contract['contract_sha256'],
        'dataset_sha256': report['source_audit'].get('dataset_sha256'),
        'files': files, 'shards': [], 'public_files': [], 'production_promoted': False,
        'source_authenticated': False, 'owner_decryption_verified': False}
    # Temporary compressed plaintext is always outside any repository.
    with tempfile.TemporaryDirectory(prefix='dt-r1-seal-') as tmp:
        archive_path = _private_path(Path(tmp) / 'study.tar.gz')
        with tarfile.open(archive_path, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
            for item in files:
                source = directory / item['file']
                require(_hash_file(source) == (item['sha256'], item['bytes']), 'STUDY_CHANGED_DURING_EXPORT')
                info = tarfile.TarInfo(item['file']); info.size = item['bytes']; info.mode = 0o600
                with source.open('rb') as handle:
                    consumed = _HashedReader(handle)
                    archive.addfile(info, consumed)
                    require((consumed.hash.hexdigest(), consumed.size) == (item['sha256'], item['bytes']),
                            'STUDY_ARCHIVED_BYTES_CHANGED')
                require(_hash_file(source) == (item['sha256'], item['bytes']), 'STUDY_CHANGED_DURING_EXPORT')
        archive_hash, archive_size = _hash_file(archive_path)
        require(archive_size <= MAX_ARCHIVE_BYTES, 'BUNDLE_ARCHIVE_TOO_LARGE')
        manifest['archive'] = {'encoding': 'gzip_tar', 'sha256': archive_hash, 'bytes': archive_size}
        with archive_path.open('rb') as handle:
            while block := handle.read(chunk_bytes):
                i = len(manifest['shards'])
                payload = {'schema': SCHEMA, 'day_jst': day, 'bundle_id': identity, 'ordinal': i,
                    'data_b64': base64.b64encode(block).decode('ascii'),
                    'safe_report': {'day_jst': day, 'scope': SCHEMA, 'ordinal': i}}
                sealed = codec.seal_evidence(payload, owner_public_pem, day, at)
                name = f'shard-{i:06d}.sealed.json'; _write(dest / name, sealed)
                manifest['shards'].append({'file': name, 'ordinal': i, 'bytes': len(sealed),
                    'sha256': sha256(sealed).hexdigest(), 'data_bytes': len(block)})
    public = {'frozen_model.json': _canonical(model), 'public_report.json': _canonical(public_projection(report)),
              'dashboard.html': render_report(report).encode('utf-8')}
    for name, raw in public.items():
        _write(dest / name, raw)
        manifest['public_files'].append({'file': name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
    raw = _canonical(manifest); _write(dest / 'manifest.json', raw)
    hashed = sha256(raw).hexdigest()
    verify_bundle(dest, expected_manifest_sha256=hashed)
    return {'status': 'ENCRYPTED_STUDY_SAVED', 'manifest_sha256': hashed, 'model_sha256': model['model_sha256'],
            'files': len(files), 'shards': len(manifest['shards']), 'owner_decryption_verified': False}


def verify_bundle(directory, *, expected_manifest_sha256):
    from race_ai import keirin_official_run_history as codec
    checked_sha(expected_manifest_sha256, 'EXTERNAL_BUNDLE_MANIFEST_SHA_REQUIRED')
    directory = Path(directory)
    raw = _read(directory / 'manifest.json', 1024 * 1024)
    require(sha256(raw).hexdigest() == expected_manifest_sha256, 'BUNDLE_MANIFEST_SHA_MISMATCH')
    manifest = json.loads(raw)
    require(raw == _canonical(manifest) and manifest.get('schema') == SCHEMA, 'BUNDLE_MANIFEST_SCHEMA_INVALID')
    for key in ('model_sha256', 'contract_sha256', 'dataset_sha256', 'bundle_id'):
        checked_sha(manifest.get(key), 'BUNDLE_PUBLIC_SHA_INVALID')
    require(manifest.get('owner_spki_sha256') == codec.storage.PINNED_OWNER_SPKI_SHA256, 'BUNDLE_OWNER_PIN_MISMATCH')
    files = manifest.get('files', [])
    require(isinstance(files, list) and len(files) == len({f['file'] for f in files}) and
            set(CORE_FILES) <= {f['file'] for f in files} <= ALLOWED_FILES, 'BUNDLE_FILE_SET_INVALID')
    require(all(type(f['bytes']) is int and 0 < f['bytes'] <= MAX_FILE_BYTES for f in files) and
            sum(f['bytes'] for f in files) <= MAX_TOTAL_BYTES, 'BUNDLE_TOTAL_SIZE_EXCEEDED')
    for item in files: checked_sha(item['sha256'])
    require(digest({'model_sha256': manifest['model_sha256'], 'files': files}) == manifest['bundle_id'], 'BUNDLE_IDENTITY_MISMATCH')
    shards = manifest.get('shards', [])
    require(isinstance(shards, list) and 0 < len(shards) <= 1024, 'BUNDLE_SHARDS_REQUIRED')
    total = 0
    for i, item in enumerate(shards):
        require(item.get('file') == f'shard-{i:06d}.sealed.json' and item.get('ordinal') == i, 'BUNDLE_SHARD_ORDER_INVALID')
        sealed = _read(directory / item['file'], codec.MAX_CIPHER_BYTES)
        require(len(sealed) == item['bytes'] and sha256(sealed).hexdigest() == item['sha256'], 'BUNDLE_SHARD_SHA_MISMATCH')
        envelope = codec._checked_cipher(sealed)
        require(envelope['day_jst'] == manifest['day'] and envelope['observed_at'] == manifest['created_at'], 'BUNDLE_SHARD_CLOCK_MISMATCH')
        require(type(item['data_bytes']) is int and 0 < item['data_bytes'] <= CHUNK_BYTES, 'BUNDLE_CHUNK_BOUND_INVALID')
        total += item['data_bytes']
    require(manifest['archive']['encoding'] == 'gzip_tar' and total == manifest['archive']['bytes'] <= MAX_ARCHIVE_BYTES,
            'BUNDLE_ARCHIVE_SIZE_INVALID')
    checked_sha(manifest['archive']['sha256'])
    public = manifest.get('public_files', [])
    require(len(public) == 3 and {p['file'] for p in public} == {'frozen_model.json', 'public_report.json', 'dashboard.html'},
            'BUNDLE_PUBLIC_FILE_SET_INVALID')
    for item in public:
        data = _read(directory / item['file'], 16 * 1024 * 1024)
        require(len(data) == item['bytes'] and sha256(data).hexdigest() == item['sha256'], 'BUNDLE_PUBLIC_SHA_MISMATCH')
    allowed_output = {'manifest.json'} | {p['file'] for p in public} | {p['file'] for p in shards}
    require({p.name for p in directory.iterdir()} == allowed_output, 'BUNDLE_UNEXPECTED_PUBLIC_FILE')
    model = validate_public_model(json.loads(_read(directory / 'frozen_model.json')))
    require(model['model_sha256'] == manifest['model_sha256'], 'BUNDLE_MODEL_BINDING_MISMATCH')
    return manifest


def restore_study(directory, destination, *, expected_manifest_sha256, owner_private_pem):
    from race_ai import keirin_official_run_history as codec
    directory = Path(directory)
    manifest = verify_bundle(directory, expected_manifest_sha256=expected_manifest_sha256)
    dest = _private_path(destination)
    require(not dest.exists(), 'RESTORE_DESTINATION_EXISTS_NO_RESET')
    with tempfile.TemporaryDirectory(prefix='dt-r1-restore-') as tmp:
        tmp = _private_path(tmp)
        archive_path = tmp / 'study.tar.gz'
        with archive_path.open('xb') as archive:
            os.chmod(archive_path, 0o600)
            for i, item in enumerate(manifest['shards']):
                data = _read(directory / item['file'], codec.MAX_CIPHER_BYTES)
                require(sha256(data).hexdigest() == item['sha256'], 'BUNDLE_SHARD_CHANGED')
                payload = codec.decrypt_evidence(data, owner_private_pem)
                require(payload.get('schema') == SCHEMA and payload.get('bundle_id') == manifest['bundle_id'] and
                        payload.get('ordinal') == i and payload.get('day_jst') == manifest['day'], 'BUNDLE_SHARD_BINDING_MISMATCH')
                block = base64.b64decode(payload['data_b64'], validate=True)
                require(len(block) == item['data_bytes'], 'BUNDLE_DECRYPTED_SIZE_MISMATCH')
                archive.write(block)
        require(_hash_file(archive_path) == (manifest['archive']['sha256'], manifest['archive']['bytes']), 'BUNDLE_ARCHIVE_SHA_MISMATCH')
        staging = tmp / 'verified'; staging.mkdir(mode=0o700)
        expected = {f['file']: f for f in manifest['files']}; seen = set()
        # Inspect each 512-byte header before tarfile can expand a PAX/GNU
        # extension. Only our regular USTAR files are accepted. The expanded
        # byte budget includes declared files, padding, and bounded trailers.
        budget = sum(512 + ((f['bytes'] + 511) // 512) * 512 for f in expected.values()) + 10240
        with gzip.open(archive_path, 'rb') as archive:
            consumed = 0
            def bounded_read(size):
                nonlocal consumed
                require(0 <= size <= budget - consumed + 1, 'BUNDLE_EXPANDED_SIZE_EXCEEDED')
                block = archive.read(size); consumed += len(block)
                require(consumed <= budget, 'BUNDLE_EXPANDED_SIZE_EXCEEDED')
                return block
            while True:
                header = bounded_read(512)
                require(len(header) == 512, 'BUNDLE_TAR_HEADER_INCOMPLETE')
                if header == bytes(512):
                    trailer = bounded_read(budget - consumed + 1)
                    require(len(trailer) >= 512 and not any(trailer), 'BUNDLE_TAR_TRAILER_INVALID')
                    break
                require(header[257:263] == b'ustar\0' and header[156:157] in (b'0', b'\0'), 'BUNDLE_TAR_EXTENSIONS_REFUSED')
                member = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
                require(member.name in expected and member.name not in seen and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE),
                        'BUNDLE_TAR_MEMBER_INVALID')
                item = expected[member.name]
                require(member.size == item['bytes'], 'BUNDLE_TAR_SIZE_MISMATCH')
                raw = bounded_read(item['bytes'])
                require(len(raw) == item['bytes'] and sha256(raw).hexdigest() == item['sha256'], 'BUNDLE_RESTORED_FILE_SHA_MISMATCH')
                padding = bounded_read((-item['bytes']) % 512)
                require(len(padding) == (-item['bytes']) % 512 and not any(padding), 'BUNDLE_TAR_PADDING_INVALID')
                _write(staging / member.name, raw); seen.add(member.name)
        require(seen == set(expected), 'BUNDLE_TAR_INCOMPLETE')
        model, report, contract, restored_files = _study(staging)
        require(model['model_sha256'] == manifest['model_sha256'] and
                contract['contract_sha256'] == manifest['contract_sha256'] and
                report['source_audit'].get('dataset_sha256') == manifest['dataset_sha256'] and
                restored_files == manifest['files'], 'BUNDLE_RESTORED_IDENTITY_MISMATCH')
        # All authentication and semantic checks precede destination creation.
        dest = _private_path(dest); dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        dest.mkdir(mode=0o700, exist_ok=False)
        for name in sorted(seen): _write(dest / name, (staging / name).read_bytes())
    return {'status': 'STUDY_RESTORED_AND_VERIFIED', 'model_sha256': manifest['model_sha256'],
            'manifest_sha256': expected_manifest_sha256, 'files': len(manifest['files']), 'production_promoted': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export'); export.add_argument('--study-dir', required=True, type=Path)
    export.add_argument('--output-dir', required=True, type=Path); export.add_argument('--owner-public-key', required=True, type=Path)
    for name in ('verify', 'restore'):
        item = sub.add_parser(name); item.add_argument('--bundle-dir', required=True, type=Path)
        item.add_argument('--manifest-sha256', required=True)
        if name == 'restore':
            item.add_argument('--output-dir', required=True, type=Path); item.add_argument('--owner-private-key', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'export':
        result = export_study(args.study_dir, args.output_dir, args.owner_public_key.read_bytes())
    elif args.command == 'restore':
        result = restore_study(args.bundle_dir, args.output_dir, expected_manifest_sha256=args.manifest_sha256,
                               owner_private_pem=_read(_private_path(args.owner_private_key), 20000))
    else:
        manifest = verify_bundle(args.bundle_dir, expected_manifest_sha256=args.manifest_sha256)
        result = {'status': 'BUNDLE_BYTES_VERIFIED', 'model_sha256': manifest['model_sha256'],
                  'files': len(manifest['files']), 'owner_decryption_verified': False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
