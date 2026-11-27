"""Restore retained research models inside the existing protected owner job.

Only keirin-result-live/observe-results on reviewed main, manually dispatched,
may call this entry point. The unchanged official continuation runtime checks
the checkout, repository, job and existing owner key before any download.
The direct study and B candidate use externally pinned retained ciphertext;
Codex uses its existing frozen-model loader. No provider, scoring, training,
forecast, state publication or model-adoption path is called. Restored files
exist only in a private temporary directory, removed before the safe receipt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from scripts import keirin_official_nationwide_continuation as continuation


SCHEMA = 'DT_R1_OWNER_MODEL_RESTORE_V1'
BACK_RECEIPT = Path('research/chatgpt_dt_r1/evidence/20261128-continuation/back-retention.json')
PUBLIC_FIELDS = {
    'dt_r1_direct': ('model_id', 'model_sha256', 'manifest_sha256', 'archive_commit',
                     'restored_files', 'encrypted_shards', 'calibration_artifacts'),
    'codex_frozen': ('model_id', 'sealed_model_sha256', 'tree_sha256'),
    'dt_r1_back': ('model_id', 'artifact_sha256', 'candidate_bytes_sha256', 'manifest_sha256',
                   'archive_commit', 'restored_files', 'receipt_file_sha256'),
}
RUNTIME_CODES = frozenset('OFFICIAL_CONTINUATION_' + code for code in (
    'TRUSTED_RUNTIME_REQUIRED', 'EXACT_SOURCE_JOB_REQUIRED', 'STUDY_MANUAL_ONLY',
    'OWNER_KEY_PAIR_REQUIRED', 'PRIVATE_ROOT_OUTSIDE_REPOSITORY',
    'RUN_CODE_IDENTITY_REQUIRED', 'CHECKOUT_CODE_CHANGED'))


def _need(ok):
    if not ok:
        raise ValueError('OWNER_RESTORE_COMPONENT_IDENTITY_UNVERIFIED')


def _write_cipher(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)


def _restore_direct(repo, private_root, private, day):
    from research.chatgpt_dt_r1 import retained_readback as retained
    from research.chatgpt_dt_r1.preserve_verified_bundle import (
        MANIFEST_SHA, MODEL_SHA, manifest_info, verify_directory)

    raw = retained.fetch_exact('manifest.json', 5577, MANIFEST_SHA)
    members = manifest_info(raw)
    folder = private_root / 'direct-ciphertext'
    folder.mkdir(mode=0o700)
    _write_cipher(folder / 'manifest.json', raw)
    for name, expected in sorted(members.items()):
        _write_cipher(folder / name, retained.fetch_exact(name, expected['bytes'], expected['sha256']))
    verify_directory(folder)
    from research.chatgpt_dt_r1.bundle import restore_study
    restored = restore_study(folder, private_root / 'direct-restored',
        expected_manifest_sha256=MANIFEST_SHA, owner_private_pem=private)
    _need(restored.get('status') == 'STUDY_RESTORED_AND_VERIFIED' and
          restored.get('model_sha256') == MODEL_SHA and restored.get('files') == 24 and
          restored.get('manifest_sha256') == MANIFEST_SHA and restored.get('production_promoted') is False)
    calibration_count = sum(item['file'].endswith('.calibration.json') for item in json.loads(raw)['files'])
    _need(calibration_count == 7)
    return dict(model_id='chatgpt-dt-r1', model_sha256=MODEL_SHA, manifest_sha256=MANIFEST_SHA,
        archive_commit=retained.ARCHIVE_COMMIT, restored_files=24, encrypted_shards=8,
        calibration_artifacts=calibration_count, owner_decryption_verified=True)


def _restore_codex(repo, private_root, private, day):
    from race_ai import keirin_official_learned_replay as existing
    trained, manifest = existing.load_candidate(repo, private, day)
    _need(trained is not None and manifest['model_id'] == 'keirin-conditional-order-trees-v1' and
          manifest['sealed_model_sha256'] == existing.FROZEN_MODEL_SHA256)
    return dict(model_id=manifest['model_id'], sealed_model_sha256=manifest['sealed_model_sha256'],
                tree_sha256=manifest['tree_sha256'], owner_decryption_verified=True)


def _restore_back(repo, private_root, private, day):
    receipt_path = repo / BACK_RECEIPT
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError('OWNER_RESTORE_BACK_RETENTION_RECEIPT_REQUIRED')
    from research.chatgpt_dt_r1 import back_candidate
    from research.chatgpt_dt_r1.retained_back_readback import verified_bundle
    with verified_bundle(receipt_path) as verified:
        receipt = verified['receipt']
        restored = back_candidate.restore_candidate(verified['directory'], private_root / 'back-restored',
            expected_manifest_sha256=receipt['manifest']['sha256'], owner_private_pem=private)
        _need(restored.get('status') == 'B_CANDIDATE_RESTORED' and
              restored.get('artifact_sha256') == receipt['artifact_sha256'] and
              restored.get('manifest_sha256') == receipt['manifest']['sha256'] and
              restored.get('production_promoted') is False)
        return dict(model_id='chatgpt-dt-r1', artifact_sha256=receipt['artifact_sha256'],
            candidate_bytes_sha256=receipt['candidate_bytes_sha256'],
            manifest_sha256=receipt['manifest']['sha256'], archive_commit=receipt['archive_commit'],
            restored_files=2, receipt_file_sha256=verified['receipt_file_sha256'],
            owner_decryption_verified=True)


def _public_component(name, result):
    _need(isinstance(result, dict) and result.get('owner_decryption_verified') is True)
    selected = {key: result[key] for key in PUBLIC_FIELDS[name]}
    expected_id = 'keirin-conditional-order-trees-v1' if name == 'codex_frozen' else 'chatgpt-dt-r1'
    _need(selected['model_id'] == expected_id)
    for key, value in selected.items():
        if key.endswith('_sha256'):
            _need(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)
        elif key == 'archive_commit':
            _need(type(value) is str and re.fullmatch('[0-9a-f]{40}', value) is not None)
        elif key != 'model_id':
            _need(type(value) is int and 0 <= value <= 100)
    return dict(selected, status='RESTORED', owner_decryption_verified=True)


def _scope():
    return dict(schema=SCHEMA, scope='OWNER_MODEL_RESTORATION_ONLY',
        source_authenticated=False, production_promoted=False,
        provider_source_requests=0, state_writes=0, new_forecasts=0, training_runs=0)


def run_restore(*, repo, private_root, owner_public_pem, owner_private_pem,
                day=None, clock=continuation.now_utc):
    # Reuse the exact main/job/manual/key guard; never simulate its environment.
    repo, root, day, _, commit = continuation._runtime(repo=repo, private_root=private_root,
        owner_public_pem=owner_public_pem, owner_private_pem=owner_private_pem,
        day=day, clock=clock, mode='study')
    report = dict(_scope(), reader_code_commit=commit, reader_run_id=os.environ['GITHUB_RUN_ID'],
                  day_jst=day, started_at=clock().isoformat(), models={})
    with TemporaryDirectory(prefix='owner-model-restore-', dir=root) as work:
        folder = Path(work)
        for name, restore in (('dt_r1_direct', _restore_direct), ('codex_frozen', _restore_codex),
                              ('dt_r1_back', _restore_back)):
            try:
                report['models'][name] = _public_component(name, restore(repo, folder, owner_private_pem, day))
            except Exception:
                # Keep completed component checks, never private exceptions,
                # originals, external paths or partial decrypted payloads.
                report['models'][name] = dict(status='HOLD', reason='MODEL_RESTORE_UNVERIFIED',
                                             owner_decryption_verified=False)
    restored = sum(item['owner_decryption_verified'] for item in report['models'].values())
    return dict(report, restored_models=restored, owner_decryption_verified=restored == 3,
        state='OWNER_MODELS_RESTORED_AND_VERIFIED' if restored == 3 else 'HOLD_OWNER_MODEL_RESTORE_INCOMPLETE',
        verified_at=clock().isoformat(), ephemeral_plaintext_removed=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--owner-public-pem', type=Path, required=True)
    parser.add_argument('--day')
    args = parser.parse_args(argv)
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        report = run_restore(repo=args.repo, private_root=args.private_root,
            owner_public_pem=args.owner_public_pem, owner_private_pem=private, day=args.day)
    except Exception as error:
        reason = str(error) if str(error) in RUNTIME_CODES else 'OWNER_RESTORE_RUNTIME_UNAVAILABLE'
        report = dict(_scope(), state='HOLD_OWNER_RESTORE_RUNTIME', reason=reason,
                      owner_decryption_verified=False)
    finally:
        private = b''
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['state'] == 'OWNER_MODELS_RESTORED_AND_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
