"""Verify the exact, retrospectively assembled dossier and registry in owner memory."""
import argparse
import base64
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import zlib

from race_ai import keirin_official_run_history as history
from race_ai.keirin_note_view import _create, _private_root

KEY_ENV = 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
MAX_COMPRESSED = 8 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
NATIONAL = 'national-dossiers.json'
REGISTRY = 'official-current-registry.json'
FILES = (NATIONAL, REGISTRY)
METRICS = ('day_jst', 'registered_riders', 'riders_with_numeric_history',
           'numeric_finish_records', 'history_start_day', 'history_end_day')


class DossierHold(ValueError):
    """Only fixed codes from this module may be published."""


def need(ok, code):
    if not ok:
        raise DossierHold(code)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'DOSSIER_JSON_INVALID')
            result[key] = value
        return result

    def nonfinite(_):
        raise DossierHold('DOSSIER_JSON_INVALID')

    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)


def _date(value):
    parsed = date.fromisoformat(value)
    need(parsed.isoformat() == value, 'DOSSIER_DATE_INVALID')
    return parsed


def _clock(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.utcoffset() is not None, 'DOSSIER_CLOCK_INVALID')
    return parsed


def _sha(raw):
    return sha256(raw).hexdigest()


def _unpack(item, pin):
    need(type(pin) is dict and set(pin) == {'sha256', 'bytes'} and
         type(pin['bytes']) is int and 0 < pin['bytes'] <= MAX_EXPANDED and
         type(pin['sha256']) is str and re.fullmatch('[0-9a-f]{64}', pin['sha256']) and
         type(item) is dict and set(item) == {'gzip_base64', 'sha256', 'bytes'} and
         type(item['bytes']) is int and item['bytes'] == pin['bytes'] and item['sha256'] == pin['sha256'],
         'DOSSIER_FILE_PIN_MISMATCH')
    encoded = item['gzip_base64']
    need(type(encoded) is str and 0 < len(encoded) <= 4 * ((MAX_COMPRESSED + 2) // 3),
         'DOSSIER_COMPRESSED_SIZE')
    compressed = base64.b64decode(encoded, validate=True)
    need(0 < len(compressed) <= MAX_COMPRESSED, 'DOSSIER_COMPRESSED_SIZE')
    stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
    expanded = stream.decompress(compressed, pin['bytes'] + 1)
    need(stream.eof and not stream.unconsumed_tail and not stream.unused_data and
         len(expanded) == pin['bytes'] and _sha(expanded) == pin['sha256'], 'DOSSIER_FILE_BYTES_MISMATCH')
    return expanded


def _index(rows):
    need(type(rows) is list and 0 < len(rows) <= 10000, 'DOSSIER_IDENTITY_INVALID')
    indexed = {}
    for row in rows:
        number = row['registration']
        need(type(number) is str and re.fullmatch('[0-9]{6}', number) and number != '000000' and
             number not in indexed and type(row['name']) is str and row['name'].strip(),
             'DOSSIER_IDENTITY_INVALID')
        indexed[number] = row
    return indexed


def _check_contents(files, receipt, sealed, now):
    registry = _json(files[REGISTRY])
    dossier = _json(files[NATIONAL])
    need(registry['schema'] == 'KEIRIN_OFFICIAL_CURRENT_REGISTRY_V1' and registry['complete'] is True and
         registry['scope'] == 'NEW_CURRENT_SOURCE_KNOWLEDGE_NOT_BACKDATED_ORIGINAL_INPUT' and
         dossier['schema'] == 'KEIRIN_BASIC_RIDER_DOSSIERS_V1' and
         dossier['scope'] == 'RETROSPECTIVE_CURRENT_REGISTRY_IDENTITY_RECONCILIATION' and
         dossier['historical_as_of_authenticated'] is False and dossier['registry_captured_after_history_cutoff'] is True,
         'DOSSIER_SCOPE_INVALID')
    day = _date(receipt['day_jst'])
    need(dossier['registry_sha256'] == receipt['files'][REGISTRY]['sha256'] and
         _date(dossier['as_of_exclusive']) == day, 'DOSSIER_REGISTRY_BINDING_MISMATCH')
    opened, closed = (_clock(registry[key]) for key in ('retrieval_started_at', 'retrieval_completed_at'))
    generated = _clock(dossier['generated_at'])
    need(closed.astimezone(ZoneInfo('Asia/Tokyo')).date() >= day and
         opened <= closed == _clock(dossier['identity_knowledge_as_of']) <= generated <= sealed <= now and
         _clock(dossier['source_download_started_at']) <= _clock(dossier['source_download_completed_at']) <= generated,
         'DOSSIER_CLOCK_INVALID')
    first, last = (_date(receipt[key]) for key in ('history_start_day','history_end_day'))
    spans = [(_date(row['included_start_day']), _date(row['included_end_day'])) for row in dossier['archive_sources']]
    need(spans and all(first <= a <= b <= last < day for a, b in spans) and
         min(a for a, _ in spans) == first and max(b for _, b in spans) == last, 'DOSSIER_PERIOD_INVALID')
    people, entries = _index(registry['riders']), _index(dossier['dossiers'])
    need(people.keys() == entries.keys(), 'DOSSIER_REGISTRATIONS_MISMATCH')
    observed = total = 0
    for number, row in entries.items():
        person = people[number]
        # A resumed acquisition may reuse a page captured before its final run began.
        need(_clock(person['captured_at']) <= closed, 'DOSSIER_CLOCK_INVALID')
        finish = row['finish_history']
        need(row['name'] == person['name'] and finish['registration'] == number and
             _date(finish['as_of_exclusive']) == day, 'DOSSIER_IDENTITY_INVALID')
        overall = finish['periods']['all']
        n = overall['observed_count']
        counts = overall['finish_counts']
        need(type(n) is int and n >= 0 and overall['missing_finish_count'] is None and
             type(counts) is dict and set(counts) == {str(rank) for rank in range(1,10)} and
             all(type(count) is int and count >= 0 for count in counts.values()) and sum(counts.values()) == n,
             'DOSSIER_OBSERVATION_COUNT_MISMATCH')
        if n:
            need(first <= _date(overall['first_observed_day']) <= _date(overall['latest_observed_day']) <= last,
                 'DOSSIER_PERIOD_INVALID')
            observed += 1
        else:
            need(overall['first_observed_day'] is None and overall['latest_observed_day'] is None,
                 'DOSSIER_PERIOD_INVALID')
        total += n
    for key, actual in (('registered_riders', len(people)), ('riders_with_numeric_history', observed),
                        ('numeric_finish_records', total)):
        need(type(receipt[key]) is int and receipt[key] == actual, 'DOSSIER_EXPECTED_COUNTS_MISMATCH')


def _restore(output_dir, files):
    destination = Path(output_dir)
    need('..' not in destination.parts, 'DOSSIER_OUTPUT_INVALID')
    destination = _private_root(destination)
    with TemporaryDirectory(dir=destination) as scratch:
        for name in FILES:
            _create(Path(scratch)/name, files[name])
        installed = []
        try:
            for name in FILES:
                final = destination/name
                os.link(Path(scratch)/name, final)
                installed.append(final)
        except OSError:
            for path in installed:
                path.unlink()
            raise DossierHold('DOSSIER_RESTORE_CONFLICT_OR_FAILURE') from None


def verify_recovery(raw_cipher, private_pem, receipt, *, output_dir=None, now=None):
    """Return aggregate readback status after verifying both original byte streams."""
    try:
        need(type(raw_cipher) is bytes and 0 < len(raw_cipher) <= history.MAX_CIPHER_BYTES and
             receipt['schema'] == 'KEIRIN_RIDER_DOSSIER_RECOVERY_RECEIPT_V1' and
             type(receipt['recovery_cipher_bytes']) is int and len(raw_cipher) == receipt['recovery_cipher_bytes']
             and _sha(raw_cipher) == receipt['recovery_cipher_sha256'], 'DOSSIER_CIPHER_PIN_MISMATCH')
        try:
            payload = history.decrypt_evidence(raw_cipher, private_pem)
        except Exception:
            raise DossierHold('DOSSIER_DECRYPTION_FAILED') from None
        metrics = {key:receipt[key] for key in METRICS}
        need(type(payload) is dict and set(payload) == {'schema', 'day_jst', 'safe_report', 'files'} and
             payload['schema'] == 'KEIRIN_RIDER_DOSSIER_RECOVERY_V1' and payload['day_jst'] == receipt['day_jst']
             and payload['safe_report'] == metrics and set(receipt['files']) == set(payload['files']) == set(FILES),
             'DOSSIER_PAYLOAD_BINDING_MISMATCH')
        envelope = _json(raw_cipher)
        need(envelope['day_jst'] == receipt['day_jst'], 'DOSSIER_ENVELOPE_DAY_MISMATCH')
        files = {name:_unpack(payload['files'][name],receipt['files'][name]) for name in FILES}
        _check_contents(files, receipt, _clock(envelope['observed_at']), now or datetime.now(timezone.utc))
        if output_dir is not None:
            _restore(output_dir, files)
        return dict(schema='KEIRIN_RIDER_DOSSIER_READBACK_V1', state='RIDER_DOSSIER_READBACK_VERIFIED',
                    **metrics, files=receipt['files'], recovery_cipher_sha256=_sha(raw_cipher),
                    files_verified=len(files), files_restored=output_dir is not None,
                    historical_as_of_authenticated=False, forecast_original_authenticated=False,
                    official_results_verified=False, accuracy_improvement_proven=False)
    except DossierHold:
        raise
    except Exception:
        raise DossierHold('DOSSIER_CONTENT_OR_OUTPUT_INVALID') from None


def _read(path, bound):
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= bound, 'DOSSIER_LOCAL_FILE_INVALID')
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os,'O_NOFOLLOW',0)), 'rb') as stream:
        value = stream.read(info.st_size + 1)
    need(len(value) == info.st_size, 'DOSSIER_LOCAL_FILE_INVALID')
    return value


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DossierHold('DOSSIER_ARGUMENTS_INVALID')


def main(argv=None):
    private_value = os.environ.pop(KEY_ENV, '')
    try:
        pem = private_value.encode('utf-8')
        del private_value
        parser = _Parser(description=__doc__, allow_abbrev=False)
        parser.add_argument('--cipher', required=True, type=Path)
        parser.add_argument('--receipt', required=True, type=Path)
        parser.add_argument('--output-dir', type=Path)
        args = parser.parse_args(argv)
        need(bool(pem), 'DOSSIER_OWNER_SECRET_UNAVAILABLE')
        result = verify_recovery(_read(args.cipher, history.MAX_CIPHER_BYTES), pem,
                                 _json(_read(args.receipt, 64*1024)), output_dir=args.output_dir)
    except DossierHold as err:
        print(json.dumps({'state':str(err),'files_restored':False}))
        return 2
    except Exception:
        print(json.dumps({'state':'DOSSIER_INPUT_INVALID','files_restored':False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
