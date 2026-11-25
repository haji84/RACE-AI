"""Read an owner-encrypted research recovery copy of exact joint originals.

Only the existing RSA-OAEP/AES-GCM envelope format is reused. This is not an
official-result revision, a PR71 forecast admission, a scorer or a new model.
Independent callers provide the original P-256 header hash, ciphertext/commit
and original Git witness clocks. A later recovery-copy clock is not substituted
for the original commitment. No source path inside the plaintext is opened.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zlib

from race_ai import keirin_official_run_history as history
from race_ai.keirin_joint_forecast import public_projection, validate_forecast
from race_ai.keirin_note_view import canonical


SCHEMA = 'KEIRIN_JOINT_ORIGINAL_RECOVERY_V1'
KEY_ENV = 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
MAX_NOTE = 8 * 1024 * 1024
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_MEMBERS = 400
MAX_RACES = 300
FILES = ('comparison_baselines.json', 'comparison_inputs.json',
         'comparison_joint_originals.json', 'joint_forecasts.json', 'races.json')
CODE = (
    'scripts/keirin_accuracy_study.py', 'scripts/keirin_boosted_choice_study.py',
    'scripts/keirin_ordered_ticket_study.py', 'scripts/keirin_line_event_study.py',
    'race_ai/keirin_archive_study.py', 'race_ai/keirin_joint_finish.py',
)


class RecoveryHold(ValueError):
    """Fixed reason codes are safe to publish; private exception text is not."""


def _need(condition, code):
    if not condition:
        raise RecoveryHold(code)


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _time(value):
    try:
        _need(type(value) is str and len(value) <= 64, 'JOINT_RECOVERY_CLOCK_INVALID')
        clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(clock.utcoffset() is not None, 'JOINT_RECOVERY_CLOCK_INVALID')
        return clock
    except (ValueError, TypeError):
        raise RecoveryHold('JOINT_RECOVERY_CLOCK_INVALID') from None


def _json(raw):
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, 'JOINT_RECOVERY_JSON_INVALID')
            result[key] = value
        return result

    def reject(_):
        raise RecoveryHold('JOINT_RECOVERY_JSON_INVALID')

    try:
        return json.loads(raw, object_pairs_hook=distinct, parse_constant=reject)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise RecoveryHold('JOINT_RECOVERY_JSON_INVALID') from None


def _b64(value, limit):
    _need(type(value) is str and 0 < len(value) <= 4 * ((limit + 2) // 3),
          'JOINT_RECOVERY_BASE64_INVALID')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise RecoveryHold('JOINT_RECOVERY_BASE64_INVALID') from None
    _need(0 < len(raw) <= limit, 'JOINT_RECOVERY_BASE64_INVALID')
    return raw


def _files(note, day):
    prefix = 'data/' + day + '/'
    files = note.get('files')
    _need(type(files) is dict and set(files) == {prefix + name for name in FILES},
          'JOINT_RECOVERY_FILE_SET_INVALID')
    decoded, digests = {}, {}
    for name in FILES:
        item = files[prefix + name]
        _need(type(item) is dict and set(item) == {'text', 'bytes', 'sha256'}
              and type(item['text']) is str and type(item['bytes']) is int
              and _sha(item['sha256']), 'JOINT_RECOVERY_FILE_BYTES_MISMATCH')
        raw = item['text'].encode('utf-8')
        _need(0 < len(raw) <= MAX_NOTE and len(raw) == item['bytes']
              and sha256(raw).hexdigest() == item['sha256'], 'JOINT_RECOVERY_FILE_BYTES_MISMATCH')
        decoded[name], digests[name] = _json(raw), item['sha256']
    return decoded, digests


def _archive(note):
    archives = note.get('preserved_archives')
    _need(type(archives) is dict and set(archives) == {'comparison-originals.tar.gz'},
          'JOINT_RECOVERY_ARCHIVE_INVALID')
    item = archives['comparison-originals.tar.gz']
    _need(type(item) is dict and set(item) == {'base64', 'bytes', 'sha256'},
          'JOINT_RECOVERY_ARCHIVE_INVALID')
    raw = _b64(item['base64'], MAX_ARCHIVE)
    _need(type(item['bytes']) is int and len(raw) == item['bytes']
          and _sha(item['sha256']) and sha256(raw).hexdigest() == item['sha256'],
          'JOINT_RECOVERY_ARCHIVE_INVALID')
    # Bound the entire gzip expansion, including PAX/extended tar headers,
    # before tarfile can parse metadata that is absent from regular members.
    try:
        inflater = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        expanded = inflater.decompress(raw, MAX_EXPANDED + 1)
        _need(len(expanded) <= MAX_EXPANDED and not inflater.unconsumed_tail,
              'JOINT_RECOVERY_ARCHIVE_TOO_LARGE')
        _need(inflater.eof and not inflater.unused_data, 'JOINT_RECOVERY_ARCHIVE_INVALID')
    except zlib.error:
        raise RecoveryHold('JOINT_RECOVERY_ARCHIVE_INVALID') from None
    members, total = {}, 0
    try:
        with tarfile.open(fileobj=BytesIO(expanded), mode='r:') as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                _need(member.isfile() and not path.is_absolute() and '..' not in path.parts
                      and path.as_posix() == member.name and member.name not in members
                      and 0 < member.size <= MAX_NOTE and len(members) < MAX_MEMBERS,
                      'JOINT_RECOVERY_ARCHIVE_MEMBER_INVALID')
                allowed = (member.name in {'frozen-model/model.json', 'frozen-model/freeze-prospective.py'}
                    or re.fullmatch(r'frozen-model/stage-[012]\.txt', member.name)
                    or member.name in {'frozen-code/' + name for name in CODE}
                    or re.fullmatch(r'sources/[0-9a-f]{64}\.html', member.name))
                _need(allowed, 'JOINT_RECOVERY_ARCHIVE_MEMBER_INVALID')
                total += member.size
                _need(total <= MAX_EXPANDED, 'JOINT_RECOVERY_ARCHIVE_TOO_LARGE')
                stream = archive.extractfile(member)
                _need(stream is not None, 'JOINT_RECOVERY_ARCHIVE_MEMBER_INVALID')
                data = stream.read(member.size + 1)
                _need(len(data) == member.size, 'JOINT_RECOVERY_ARCHIVE_MEMBER_INVALID')
                members[member.name] = data
    except (tarfile.TarError, OSError, EOFError):
        raise RecoveryHold('JOINT_RECOVERY_ARCHIVE_INVALID') from None
    model_raw = members.get('frozen-model/model.json')
    _need(model_raw is not None and _sha(note.get('model_sha256'))
          and sha256(model_raw).hexdigest() == note['model_sha256'],
          'JOINT_RECOVERY_MODEL_ARCHIVE_MISMATCH')
    model = _json(model_raw)
    hashes = model.get('source_files_sha256') if type(model) is dict else None
    stages = model.get('stage_sha256') if type(model) is dict else None
    _need(type(hashes) is dict and set(hashes) == set(CODE)
          and type(stages) is list and len(stages) == 3,
          'JOINT_RECOVERY_MODEL_ARCHIVE_MISMATCH')
    expected = {**{'frozen-code/' + name: digest for name, digest in hashes.items()},
                **{f'frozen-model/stage-{n}.txt': digest for n, digest in enumerate(stages)}}
    _need(all(_sha(digest) and name in members and sha256(members[name]).hexdigest() == digest
              for name, digest in expected.items()), 'JOINT_RECOVERY_MODEL_ARCHIVE_MISMATCH')
    return members, item['sha256']


def _index(document, day):
    _need(type(document) is dict and type(document.get('races')) is list
          and 1 <= len(document['races']) <= MAX_RACES, 'JOINT_RECOVERY_COHORT_INVALID')
    result = {}
    for row in document['races']:
        _need(type(row) is dict and type(row.get('race_id')) is str
              and re.fullmatch(day.replace('-', '') + '[0-9]{4}', row['race_id'])
              and row['race_id'] not in result, 'JOINT_RECOVERY_COHORT_INVALID')
        result[row['race_id']] = row
    return result


def _roster(rows, cars, key='car'):
    _need(type(rows) is list and len(rows) == len(cars), 'JOINT_RECOVERY_ROSTER_MISMATCH')
    identities = {}
    for rider in rows:
        _need(type(rider) is dict and type(rider.get(key)) is int and rider[key] in cars
              and rider[key] not in identities and type(rider.get('name')) is str
              and 0 < len(rider['name']) <= 100, 'JOINT_RECOVERY_ROSTER_MISMATCH')
        identities[rider[key]] = (rider['name'], rider.get('registration'))
    _need(set(identities) == set(cars), 'JOINT_RECOVERY_ROSTER_MISMATCH')
    return identities


def _records(note, files, digests, members, day):
    inputs = _index(files['comparison_inputs.json'], day)
    baseline = _index(files['comparison_baselines.json'], day)
    candidate = _index(files['comparison_joint_originals.json'], day)
    projections = _index(files['joint_forecasts.json'], day)
    displays = _index(files['races.json'], day)
    _need(all(set(other) == set(inputs) for other in (baseline, candidate, projections, displays)),
          'JOINT_RECOVERY_COHORT_MISMATCH')
    cutoffs, generated, sources = [], [], set()
    for rid, item in sorted(inputs.items()):
        before, after = baseline[rid], candidate[rid]
        for record in (before, after):
            try:
                validate_forecast(record)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                raise RecoveryHold('JOINT_RECOVERY_FORECAST_INVALID') from None
            _need(_time(record['generated_at']) < _time(record['cutoff_at'])
                  and record['scope'] == 'PROSPECTIVE_RESEARCH', 'JOINT_RECOVERY_FORECAST_LATE')
        shared = ('race_id', 'cars', 'cutoff_at', 'source_as_of', 'generated_at',
                  'source_forecast_generated_at', 'input_sha256', 'source_packet_sha256', 'model_version')
        _need(all(before.get(key) == after.get(key) for key in shared)
              and before['model_version'] == note['model_sha256']
              and before['model_id'] == 'comparison-B-before-saved'
              and after['model_id'] == 'comparison-B-residual', 'JOINT_RECOVERY_PAIR_METADATA_MISMATCH')
        actual = item.get('input')
        _need(type(actual) is dict and set(actual) == {'race_id', 'riders', 'line_groups'}
              and actual['race_id'] == rid, 'JOINT_RECOVERY_INPUT_INVALID')
        _need(sha256(canonical(actual)).hexdigest() == before['input_sha256'],
              'JOINT_RECOVERY_INPUT_SHA_MISMATCH')
        _need(before['source_packet_sha256'] == digests['comparison_inputs.json'],
              'JOINT_RECOVERY_INPUT_FILE_SHA_MISMATCH')
        cars = before['cars']
        riders = actual.get('riders')
        groups = actual.get('line_groups')
        _need(type(riders) is list and len(riders) == len(cars)
              and all(type(r) is dict and type(r.get('car')) is int for r in riders)
              and sorted(r['car'] for r in riders) == sorted(cars)
              and type(groups) is list and all(type(group) is list and group for group in groups)
              and sorted(c for group in groups for c in group) == sorted(cars),
              'JOINT_RECOVERY_INPUT_INVALID')
        identities = _roster(item.get('roster'), cars)
        _need(_roster(before['riders'], cars) == identities == _roster(after['riders'], cars),
              'JOINT_RECOVERY_ROSTER_MISMATCH')
        _need(item.get('cutoff_at') == before['cutoff_at']
              and item.get('source_as_of') == before['source_as_of']
              and item.get('forecast_generated_at') == before['generated_at'] == before['source_forecast_generated_at'],
              'JOINT_RECOVERY_PAIR_METADATA_MISMATCH')
        source = item.get('source')
        _need(type(source) is dict and source.get('race_id') == rid
              and source.get('http_status') == 200 and _sha(source.get('raw_sha256')),
              'JOINT_RECOVERY_SOURCE_BYTES_MISMATCH')
        source_path = 'sources/' + source['raw_sha256'] + '.html'
        raw = members.get(source_path)
        _need(raw is not None and type(source.get('raw_bytes')) is int
              and len(raw) == source['raw_bytes'] and sha256(raw).hexdigest() == source['raw_sha256'],
              'JOINT_RECOVERY_SOURCE_BYTES_MISMATCH')
        _need(source.get('captured_at') == item['source_as_of']
              and _time(source.get('requested_at')) <= _time(source['captured_at'])
              <= _time(before['generated_at']) < _time(before['cutoff_at']),
              'JOINT_RECOVERY_SOURCE_CLOCK_MISMATCH')
        # The exact full original is authoritative; this is its saved display.
        _need(projections[rid] == public_projection(after), 'JOINT_RECOVERY_PROJECTION_MISMATCH')
        display = displays[rid]
        displayed = _roster(display.get('riders'), cars, key='number')
        _need(all(displayed[car][0] == identities[car][0] for car in cars)
              and display.get('cutoff') == before['cutoff_at'] and display.get('lines') == groups,
              'JOINT_RECOVERY_DISPLAY_MISMATCH')
        cutoffs.append(_time(before['cutoff_at']))
        generated.append(_time(before['generated_at']))
        sources.add(source_path)
    return len(inputs), cutoffs, generated, len(sources)


def verify_recovery(raw_rsa_cipher, owner_private_pem, *, expected_original_note_sha256,
                    expected_original_cipher_sha256, expected_original_archive_commit,
                    expected_original_created_at, expected_original_git_readback_at):
    """Authenticate a research copy and return safe counts and provenance only.

    Expected hashes and clocks must come from the independently checked original
    P-256 archive/receipt. They must not be inferred from this recovery payload.
    RSA envelope creation/readback may occur after the original race cutoffs.
    """
    _need(type(raw_rsa_cipher) is bytes and 0 < len(raw_rsa_cipher) <= history.MAX_CIPHER_BYTES,
          'JOINT_RECOVERY_CIPHER_INVALID')
    _need(_sha(expected_original_note_sha256) and _sha(expected_original_cipher_sha256)
          and type(expected_original_archive_commit) is str
          and re.fullmatch('[0-9a-f]{40}', expected_original_archive_commit),
          'JOINT_RECOVERY_EXPECTED_BINDING_INVALID')
    created, witnessed = _time(expected_original_created_at), _time(expected_original_git_readback_at)
    try:
        payload = history.decrypt_evidence(raw_rsa_cipher, owner_private_pem)
    except Exception:
        raise RecoveryHold('JOINT_RECOVERY_DECRYPTION_FAILED') from None
    try:
        _need(type(payload) is dict and payload.get('schema') == SCHEMA,
              'JOINT_RECOVERY_PAYLOAD_INVALID')
        expected = {'original_note_sha256': expected_original_note_sha256,
                    'original_cipher_sha256': expected_original_cipher_sha256,
                    'original_archive_commit': expected_original_archive_commit}
        _need(all(payload.get(key) == value for key, value in expected.items()),
              'JOINT_RECOVERY_EXTERNAL_BINDING_MISMATCH')
        day = payload.get('day_jst')
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day,
              'JOINT_RECOVERY_DAY_INVALID')
        safe = payload.get('safe_report')
        _need(type(safe) is dict and safe.get('day_jst') == day,
              'JOINT_RECOVERY_PAYLOAD_INVALID')
        _need(_time(safe.get('original_created_at')) == created
              and _time(safe.get('original_git_readback_at')) == witnessed,
              'JOINT_RECOVERY_EXTERNAL_CLOCK_MISMATCH')
        _need(safe.get('original_header') == {'schema': 'RACE_AI_SAVED_WEB_VIEW_V1',
                    'source_content_sha256': expected_original_note_sha256},
              'JOINT_RECOVERY_ORIGINAL_HEADER_MISMATCH')
        raw_note = _b64(payload.get('original_note_b64'), MAX_NOTE)
        _need(sha256(raw_note).hexdigest() == expected_original_note_sha256,
              'JOINT_RECOVERY_NOTE_SHA_MISMATCH')
        note = _json(raw_note)
        _need(type(note) is dict and note.get('schema') == 'RACE_AI_KEIRIN_NOTE_VIEW_V1'
              and note.get('scope') == 'OWNER_FROZEN_JOINT_COMPARISON_RESEARCH'
              and note.get('dates') == [day] and note.get('formal_model_admission') is False
              and note.get('production_weight_switch') is False and note.get('wagers_placed') is False,
              'JOINT_RECOVERY_NOTE_SCOPE_INVALID')
        files, digests = _files(note, day)
        members, archive_sha = _archive(note)
        count, cutoffs, generated, source_count = _records(note, files, digests, members, day)
        earliest = min(cutoffs)
        _need(_time(safe.get('earliest_cutoff')) == earliest
              and _time(note.get('imported_at')) <= created <= witnessed < earliest
              and max(generated) <= created, 'JOINT_RECOVERY_ORIGINAL_COMMITMENT_LATE')
    except RecoveryHold:
        raise
    except Exception:
        raise RecoveryHold('JOINT_RECOVERY_CONTENT_INVALID') from None
    return {'schema': 'KEIRIN_JOINT_ORIGINAL_READBACK_V1',
        'state': 'INDEPENDENT_RESEARCH_ORIGINAL_PLAINTEXT_READBACK_VERIFIED',
        'day_jst': day, 'readback_at': datetime.now(timezone.utc).isoformat(),
        'recovery_cipher_sha256': sha256(raw_rsa_cipher).hexdigest(),
        **expected, 'original_created_at': expected_original_created_at,
        'original_git_readback_at': expected_original_git_readback_at,
        'earliest_cutoff': earliest.isoformat(), 'latest_cutoff': max(cutoffs).isoformat(),
        'paired_races': count, 'full_forecast_records_verified': 2 * count,
        'source_files_verified': source_count, 'note_files_verified': len(files),
        'archived_files_verified': len(members), 'preserved_archive_sha256': archive_sha,
        'model_sha256': note['model_sha256'], 'all_originals_before_earliest_cutoff': True,
        'independent_research_plaintext_readback': True,
        'actual_organizer_cutoff_authenticated': False, 'formal_PR71': False,
        'official_results_read': False, 'model_refitted': False, 'production_weights_promoted': False}


def _read(path, limit):
    try:
        path = Path(path)
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit,
              'JOINT_RECOVERY_LOCAL_FILE_INVALID')
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            raw = stream.read(limit + 1)
        _need(len(raw) == info.st_size, 'JOINT_RECOVERY_LOCAL_FILE_INVALID')
        return raw
    except OSError:
        raise RecoveryHold('JOINT_RECOVERY_LOCAL_FILE_UNAVAILABLE') from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RecoveryHold('JOINT_RECOVERY_ARGUMENTS_INVALID')


def main(argv=None):
    # Remove the existing secret before any possible subprocess or diagnostics.
    private_pem = os.environ.pop(KEY_ENV, '').encode('utf-8')
    try:
        parser = _Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument('--cipher', required=True, type=Path)
        parser.add_argument('--receipt', required=True, type=Path)
        args = parser.parse_args(argv)
        _need(bool(private_pem), 'JOINT_RECOVERY_OWNER_SECRET_UNAVAILABLE')
        receipt = _json(_read(args.receipt, 64 * 1024))
        raw = _read(args.cipher, history.MAX_CIPHER_BYTES)
        _need(type(receipt) is dict and _sha(receipt.get('recovery_cipher_sha256'))
              and sha256(raw).hexdigest() == receipt['recovery_cipher_sha256'],
              'JOINT_RECOVERY_CIPHER_SHA_MISMATCH')
        report = verify_recovery(raw, private_pem,
            expected_original_note_sha256=receipt['original_note_sha256'],
            expected_original_cipher_sha256=receipt['original_cipher_sha256'],
            expected_original_archive_commit=receipt['original_archive_commit'],
            expected_original_created_at=receipt['expected_original_created_at'],
            expected_original_git_readback_at=receipt['expected_original_git_readback_at'])
    except RecoveryHold as error:
        print(json.dumps({'state': str(error), 'independent_research_plaintext_readback': False,
                          'formal_PR71': False}))
        return 2
    except Exception:
        print(json.dumps({'state': 'JOINT_RECOVERY_INPUT_INVALID',
                          'independent_research_plaintext_readback': False, 'formal_PR71': False}))
        return 2
    finally:
        private_pem = b''
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
