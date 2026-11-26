"""Verify an existing owner RSA recovery copy, then run the existing joint scorer.

Only safe aggregates leave memory. No network, model promotion, source-path
following, forecast mutation or state write is performed here.
"""
import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import re
import stat

KEY_ENV = 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
ROOT = Path(__file__).resolve().parents[1]
MAX_CIPHER = 24 * 1024 * 1024
MAX_NOTE = 8 * 1024 * 1024
SOURCE_SHA256 = {
    'scripts/keirin_joint_original_readback.py': '0c3aced968a1ade54dc5085b306435433f3c033944674c584c7e1a1535f5603c',
    'race_ai/keirin_official_run_history.py': '6ca4ffe0211186d4b08cd8d897c79c5e1dbcb4ba460f0aa73410ca317adf1266',
    'scripts/keirin_joint_forward_score.py': '2ab3c69f169bff5b026fe6d766896b489909cca187e2720f84cbc1dd41264dd2',
    'race_ai/keirin_paired_measurement.py': '7e7b3f3a5cc28dac65ebd995d0910fa96f43aa590cb68e77407fb757a518c1c2',
}


class RecoveryScoreHold(ValueError):
    """Only fixed, non-private reason codes are exposed."""


def _need(condition, code):
    if not condition:
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_' + code)


def _sha(value, length=64):
    return type(value) is str and re.fullmatch('[0-9a-f]{'+str(length)+'}', value) is not None


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _json(raw, limit=MAX_CIPHER):
    _need(type(raw) is bytes and 0 < len(raw) <= limit, 'INPUT_BYTES_INVALID')
    def pairs(values):
        result = {}
        for key, value in values:
            _need(key not in result, 'JSON_INVALID')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _need(False, 'JSON_INVALID'))
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_JSON_INVALID') from None


def _time(value):
    try:
        _need(type(value) is str and len(value) <= 64, 'CLOCK_INVALID')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(parsed.utcoffset() is not None, 'CLOCK_INVALID')
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_CLOCK_INVALID') from None


def _read(path, limit):
    try:
        path = Path(path)
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, 'LOCAL_FILE_INVALID')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            raw = stream.read(limit + 1)
        _need(len(raw) == info.st_size, 'LOCAL_FILE_INVALID')
        return raw
    except OSError:
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_LOCAL_FILE_UNAVAILABLE') from None


def _guard_sources():
    for name, expected in SOURCE_SHA256.items():
        _need(sha256(_read(ROOT / name, 2 * 1024 * 1024)).hexdigest() == expected, 'SOURCE_SHA_MISMATCH')
    return dict(SOURCE_SHA256)


def _module(name, source):
    module = importlib.import_module(name)
    _need(Path(module.__file__).resolve() == (ROOT / source).resolve(), 'SOURCE_PATH_MISMATCH')
    return module


def _anchors(receipt, publication, witness):
    _need(type(receipt) is dict and receipt.get('schema') == 'KEIRIN_JOINT_ORIGINAL_RECOVERY_RECEIPT_V1', 'RECEIPT_INVALID')
    _need(type(publication) is dict and type(witness) is dict, 'ORIGIN_RECEIPT_INVALID')
    for key in ('recovery_cipher_sha256', 'original_note_sha256', 'original_cipher_sha256'):
        _need(_sha(receipt.get(key)), 'RECEIPT_HASH_INVALID')
    for key in ('original_archive_commit', 'recovery_archive_commit'):
        _need(_sha(receipt.get(key), 40), 'RECEIPT_COMMIT_INVALID')
    _need(receipt.get('copy_is_new_pre_cutoff_forecast') is False and
          receipt.get('encryption_format_only_not_official_result') is True and
          receipt.get('formal_PR71_admission') is False and
          receipt.get('private_plaintext_uploaded') is False and
          receipt.get('original_cipher_rewritten') is False, 'RECEIPT_SCOPE_INVALID')
    archive = publication.get('publication')
    _need(type(archive) is dict and receipt['original_note_sha256'] == publication.get('original_note_sha256') and
          receipt['original_cipher_sha256'] == publication.get('cipher_sha256') == witness.get('cipher_sha256') and
          receipt['original_archive_commit'] == archive.get('source_commit') == witness.get('archive_commit'), 'ORIGIN_BINDING_MISMATCH')
    for receipt_key, witness_key in (('original_witness_run', 'action_run'), ('original_witness_job', 'job_id')):
        _need(type(receipt.get(receipt_key)) is int and receipt[receipt_key] > 0 and
              type(witness.get(witness_key)) is int and receipt[receipt_key] == witness[witness_key], 'ORIGIN_JOB_MISMATCH')
    created = publication.get('original_snapshot_created_at', publication.get('generated_at'))
    _need(_time(receipt.get('expected_original_created_at')) == _time(created) and
          _time(receipt.get('expected_original_git_readback_at')) == _time(witness.get('observed_at')), 'ORIGIN_CLOCK_MISMATCH')
    path = receipt.get('recovery_archive_path')
    _need(type(path) is str and re.fullmatch(r'state/keirin/research/joint-comparison/v1/\d{4}-\d{2}-\d{2}/'+
          receipt['recovery_cipher_sha256']+r'\.sealed\.json', path), 'RECEIPT_PATH_INVALID')


def _readback(report, receipt, publication, now):
    _need(type(report) is dict and report.get('schema') == 'KEIRIN_JOINT_ORIGINAL_READBACK_V1' and
          report.get('state') == 'INDEPENDENT_RESEARCH_ORIGINAL_PLAINTEXT_READBACK_VERIFIED' and
          report.get('independent_research_plaintext_readback') is True and
          report.get('all_originals_before_earliest_cutoff') is True and
          report.get('actual_organizer_cutoff_authenticated') is False and
          report.get('formal_PR71') is False and report.get('production_weights_promoted') is False, 'READBACK_SCOPE_INVALID')
    for key in ('recovery_cipher_sha256', 'original_note_sha256', 'original_cipher_sha256', 'original_archive_commit'):
        _need(report.get(key) == receipt[key], 'READBACK_BINDING_MISMATCH')
    count = report.get('paired_races')
    _need(type(count) is int and count > 0 and count == publication.get('races') and
          type(report.get('full_forecast_records_verified')) is int and
          report['full_forecast_records_verified'] == 2 * count, 'READBACK_COHORT_MISMATCH')
    _need(_time(report.get('original_created_at')) == _time(receipt['expected_original_created_at']) and
          _time(report.get('original_git_readback_at')) == _time(receipt['expected_original_git_readback_at']) and
          _time(receipt['expected_original_git_readback_at']) <= _time(report.get('readback_at')) <= now, 'READBACK_CLOCK_MISMATCH')


def score_recovery(raw_cipher, private_pem, receipt_raw, publication_raw, witness_raw, roster_raw, results_raw, clock=None):
    """Verify exact recovered originals before returning existing score aggregates."""
    try:
        receipt, publication, witness = (_json(raw, 128 * 1024) for raw in
                                        (receipt_raw, publication_raw, witness_raw))
        _anchors(receipt, publication, witness)
        _need(type(raw_cipher) is bytes and 0 < len(raw_cipher) <= MAX_CIPHER and
              sha256(raw_cipher).hexdigest() == receipt['recovery_cipher_sha256'] and
              type(receipt.get('recovery_cipher_bytes')) is int and len(raw_cipher) == receipt['recovery_cipher_bytes'], 'CIPHER_SHA_MISMATCH')
        _need(type(private_pem) is bytes and 0 < len(private_pem) <= 20000, 'OWNER_SECRET_UNAVAILABLE')
        sources = _guard_sources()
        reader = _module('scripts.keirin_joint_original_readback', 'scripts/keirin_joint_original_readback.py')
        history = _module('race_ai.keirin_official_run_history', 'race_ai/keirin_official_run_history.py')
        try:
            verified = reader.verify_recovery(raw_cipher, private_pem,
                expected_original_note_sha256=receipt['original_note_sha256'],
                expected_original_cipher_sha256=receipt['original_cipher_sha256'],
                expected_original_archive_commit=receipt['original_archive_commit'],
                expected_original_created_at=receipt['expected_original_created_at'],
                expected_original_git_readback_at=receipt['expected_original_git_readback_at'])
        except Exception:
            raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_VERIFY_FAILED') from None
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        _need(isinstance(now, datetime) and now.utcoffset() is not None, 'CLOCK_INVALID')
        now = now.astimezone(timezone.utc)
        _readback(verified, receipt, publication, now)
        try:
            payload = history.decrypt_evidence(raw_cipher, private_pem)
        except Exception:
            raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_DECRYPT_FAILED') from None
        _need(type(payload) is dict and payload.get('schema') == reader.SCHEMA and
              all(payload.get(key) == receipt[key] for key in
                  ('original_note_sha256', 'original_cipher_sha256', 'original_archive_commit')), 'PAYLOAD_BINDING_MISMATCH')
        value = payload.get('original_note_b64')
        _need(type(value) is str and 0 < len(value) <= 4 * ((MAX_NOTE + 2) // 3), 'NOTE_BASE64_INVALID')
        try:
            note = base64.b64decode(value, validate=True)
        except (ValueError, TypeError):
            raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_NOTE_BASE64_INVALID') from None
        _need(0 < len(note) <= MAX_NOTE and sha256(note).hexdigest() == receipt['original_note_sha256'], 'NOTE_SHA_MISMATCH')
        scorer = _module('scripts.keirin_joint_forward_score', 'scripts/keirin_joint_forward_score.py')
        try:
            report = scorer.score_joint(note, publication_raw, witness_raw, roster_raw, results_raw,
                expected_note_sha256=receipt['original_note_sha256'], clock=lambda: now)
            report['measured_comparison']['original_authentication'] = 'INDEPENDENT_RSA_READBACK_VERIFIED'
        except Exception:
            raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_SCORING_FAILED') from None
        report.update(original_plaintext_authentication='INDEPENDENT_RSA_READBACK_VERIFIED',
            independent_research_plaintext_readback=True, actual_organizer_cutoff_authenticated=False,
            rsa_readback_report_sha256=sha256(_canonical(verified)).hexdigest(),
            rsa_readback_source=dict(repository='haji84/RACE-AI',commit=receipt['recovery_archive_commit'],
                path=receipt['recovery_archive_path'],cipher_sha256=receipt['recovery_cipher_sha256'],
                verification_sources_sha256=sources),
            recovery_receipt_sha256=sha256(receipt_raw).hexdigest(),
            flow_state='NO_PRE_CUTOFF_FLOW_ORIGINAL',formalPR71=False,formal_PR71=False,
            accuracy_improvement_proven=False)
        return report
    except RecoveryScoreHold:
        raise
    except Exception:
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_INPUT_INVALID') from None
    finally:
        private_pem = b''


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RecoveryScoreHold('JOINT_RECOVERY_SCORE_ARGUMENTS_INVALID')


def main(argv=None):
    # Pop before argument errors, source checks, imports or other diagnostics.
    private_value = os.environ.pop(KEY_ENV, '')
    private_pem = b''
    try:
        private_pem = private_value.encode('utf-8')
        private_value = ''
        parser = _Parser(description=__doc__, allow_abbrev=False)
        for name in ('cipher', 'receipt', 'publication', 'witness', 'roster', 'results'):
            parser.add_argument('--'+name, required=True, type=Path)
        args = parser.parse_args(argv)
        _need(bool(private_pem), 'OWNER_SECRET_UNAVAILABLE')
        report = score_recovery(_read(args.cipher, MAX_CIPHER), private_pem,
            *(_read(getattr(args, name), MAX_CIPHER) for name in ('receipt', 'publication', 'witness', 'roster', 'results')))
    except RecoveryScoreHold as error:
        print(json.dumps(dict(state=str(error),original_plaintext_authentication='UNVERIFIED',
            independent_research_plaintext_readback=False,formalPR71=False,accuracy_improvement_proven=False,
            flow_state='NO_PRE_CUTOFF_FLOW_ORIGINAL')))
        return 2
    except Exception:
        print(json.dumps(dict(state='JOINT_RECOVERY_SCORE_INPUT_INVALID',original_plaintext_authentication='UNVERIFIED',
            independent_research_plaintext_readback=False,formalPR71=False,accuracy_improvement_proven=False,
            flow_state='NO_PRE_CUTOFF_FLOW_ORIGINAL')))
        return 2
    finally:
        private_pem = b''
        private_value = ''
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
