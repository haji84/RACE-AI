"""Project public athlete fields from verified official roster and dossier receipts."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unicodedata import category
from zoneinfo import ZoneInfo

from race_ai import keirin_official_public_source as official
from race_ai.keirin_note_view import _create, _private_root, canonical
from scripts import keirin_rider_dossier_readback as readback


STARTERS_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_STARTERS_V1'
DIRECTORY_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_V1'
DIRECTORY_FILE = 'public-rider-directory.json'
RECEIPT_FILE = 'public-rider-directory-receipt.json'
JST = ZoneInfo('Asia/Tokyo')
GRADES = frozenset(('SS', 'S1', 'S2', 'A1', 'A2', 'A3', 'L1'))
STYLES = frozenset(('逃', '追', '両'))


class ProjectionHold(ValueError):
    """Messages contain fixed reason codes and no source or roster fields."""


def _need(ok, reason):
    if not ok:
        raise ProjectionHold(reason)


def _text(value, limit):
    if type(value) is not str or not 0 < len(value) <= limit:
        return None
    if any(category(char).startswith('C') or char in '<>' for char in value):
        return None
    return ' '.join(value.split()) or None


def project_starters(schedule, *, published_at):
    """Open a dated official schedule receipt and release only public identities."""
    _need(official.reparse_day_schedule(schedule), 'PUBLIC_STARTERS_SCHEDULE_UNVERIFIED')
    published = official._aware(published_at)
    sources = {
        snapshot['url']: {row['raceNo']: row['sInfo'] for row in official._payload(snapshot)['rInfo']}
        for snapshot in schedule['snapshots']
        if official._check_url(snapshot['url']) == 'JSJ017'
    }

    races = []
    for race in schedule['races']:
        source_at = race['source_observed_at']
        _need(official._aware(source_at) <= published, 'PUBLIC_STARTERS_OBSERVATION_AFTER_PUBLICATION')
        raw_by_car = {row['syaban']: row for row in sources[race['source_url']][race['race_no']]}
        riders = []
        registrations = set()
        for starter in race['starters']:
            car, registration = starter['car'], starter['registration_id']
            row = raw_by_car[car]
            name = _text(row.get('senName'), 80)
            _need(name and registration == row['senNo'] and registration != '000000' and
                  registration not in registrations, 'PUBLIC_STARTERS_IDENTITY_UNVERIFIED')
            registrations.add(registration)
            person = dict(number=car, registration=registration, name=name)
            region = _text(row.get('huken'), 32)
            if region:
                person['region'] = region
            style = row.get('kyaku')
            if type(style) is str and style in STYLES:
                person['style'] = style
            riders.append(person)
        races.append(dict(race_id=race['race_id'], source_at=source_at, riders=riders))
    return dict(schema=STARTERS_SCHEMA, day=schedule['day_jst'],
                published_at=published.isoformat(), races=races)


def project_directory(files, receipt, *, now=None):
    """Project the exact original registry and dossiers from the protected restore."""
    _need(type(receipt) is dict and receipt.get('schema') == 'KEIRIN_RIDER_DOSSIER_RECOVERY_RECEIPT_V1' and
          type(files) is dict and set(files) == set(readback.FILES) and set(receipt['files']) == set(readback.FILES),
          'PUBLIC_RIDER_DIRECTORY_PIN_INVALID')
    for name, value in files.items():
        pin = receipt['files'][name]
        _need(type(value) is bytes and 0 < len(value) <= readback.MAX_EXPANDED and
              type(pin) is dict and set(pin) == {'bytes', 'sha256'} and
              type(pin['bytes']) is int and pin['bytes'] == len(value) and sha256(value).hexdigest() == pin['sha256'],
              'PUBLIC_RIDER_DIRECTORY_SOURCE_SHA_MISMATCH')
    archive_read_at = readback._clock(receipt['git_readback_at'])
    now = now or datetime.now(timezone.utc)
    _need(archive_read_at <= now, 'PUBLIC_RIDER_DIRECTORY_CLOCK_INVALID')
    readback._check_contents(files, receipt, archive_read_at, now)

    registry = readback._json(files[readback.REGISTRY])
    national = readback._json(files[readback.NATIONAL])
    profiles = {row['registration']: row for row in national['dossiers']}
    riders = []
    for person in sorted(registry['riders'], key=lambda row: row['registration']):
        registration = person['registration']
        name = _text(person['name'], 80)
        _need(name, 'PUBLIC_RIDER_DIRECTORY_NAME_INVALID')
        overall = profiles[registration]['finish_history']['periods']['all']
        row = dict(registration=registration, name=name, history=dict(
            observed_count=overall['observed_count'],
            finish_counts={str(rank): overall['finish_counts'][str(rank)] for rank in range(1, 10)},
            first_observed_day=overall['first_observed_day'],
            latest_observed_day=overall['latest_observed_day'],
        ))
        region = _text(person.get('prefecture_or_country'), 32)
        if region:
            row['region'] = region
        grade = person.get('class')
        if type(grade) is str and grade in GRADES:
            row['grade'] = grade
        riders.append(row)
    as_of = readback._clock(registry['retrieval_completed_at']).astimezone(JST).date().isoformat()
    return dict(schema=DIRECTORY_SCHEMA, as_of=as_of, history_start_day=receipt['history_start_day'],
                history_end_day=receipt['history_end_day'], riders=riders)


def directory_receipt(document, archive):
    """Record the released bytes and aggregate provenance, without source records."""
    body = canonical(document)
    source_commit = archive['archive_commit']
    source_cipher = archive['recovery_cipher_sha256']
    _need(type(source_commit) is str and re.fullmatch('[0-9a-f]{40}', source_commit) and
          type(source_cipher) is str and re.fullmatch('[0-9a-f]{64}', source_cipher),
          'PUBLIC_RIDER_DIRECTORY_ARCHIVE_PROVENANCE_INVALID')
    return dict(
        schema='RACE_AI_KEIRIN_PUBLIC_RIDER_DIRECTORY_PROJECTION_RECEIPT_V1',
        as_of=document['as_of'], history_start_day=document['history_start_day'],
        history_end_day=document['history_end_day'], registered_riders=len(document['riders']),
        riders_with_numeric_history=sum(row['history']['observed_count'] > 0 for row in document['riders']),
        numeric_finish_records=sum(row['history']['observed_count'] for row in document['riders']),
        archive_commit=source_commit, recovery_cipher_sha256=source_cipher,
        official_registry_sha256=archive['files'][readback.REGISTRY]['sha256'],
        national_dossiers_sha256=archive['files'][readback.NATIONAL]['sha256'],
        projection_sha256=sha256(body).hexdigest(), projection_bytes=len(body),
    )


def _write_directory(destination, document, proof):
    directory = _private_root(destination)
    installed = []
    with TemporaryDirectory(dir=directory) as temporary:
        scratch = Path(temporary)
        _create(scratch / DIRECTORY_FILE, canonical(document))
        _create(scratch / RECEIPT_FILE, canonical(proof))
        try:
            for name in (DIRECTORY_FILE, RECEIPT_FILE):
                output = directory / name
                os.link(scratch / name, output)
                installed.append(output)
        except OSError:
            for output in installed:
                output.unlink()
            raise ProjectionHold('PUBLIC_RIDER_DIRECTORY_OUTPUT_CONFLICT') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--restored-dir', required=True, type=Path)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = readback._json(readback._read(args.receipt, 64 * 1024))
        files = {
            name: readback._read(args.restored_dir / name, readback.MAX_EXPANDED)
            for name in readback.FILES
        }
        document = project_directory(files, receipt)
        proof = directory_receipt(document, receipt)
        _write_directory(args.output_dir, document, proof)
    except (ProjectionHold, readback.DossierHold) as error:
        print(json.dumps(dict(state=str(error))))
        return 2
    except (KeyError, TypeError, ValueError, OSError):
        print(json.dumps(dict(state='PUBLIC_RIDER_DIRECTORY_INPUT_INVALID')))
        return 2
    print(json.dumps(proof, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
