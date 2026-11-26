"""Project public athlete fields from verified official roster and dossier receipts."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
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


def project_sp_starter_row(card_args, snapshot):
    """Read publicly named riders from the verified SP source for an admitted snapshot."""
    from race_ai import keirin_official_sp_receipt as sp

    observed = official._aware(card_args['detail_observed_at'])
    calendar = card_args['calendar_receipt']
    card = sp.parse_race_detail(card_args['detail_raw'], expected_day=card_args['expected_day'],
        expected_venue_code=card_args['venue_code'], expected_race_number=card_args['race_number'],
        observed_at=observed, expected_sha256=card_args['detail_sha256'],
        calendar_receipt=dict(calendar, observed_at=official._aware(calendar['observed_at'])))
    cut = snapshot['cutoff_source']
    expected = {rider['car']: rider['athlete_id'] for rider in snapshot['riders']}
    actual = {rider['car']: rider['registration_id'] for rider in card['riders']}
    _need(card['race_id'] == snapshot['race_id'] and card['no_published_roster_exclusion_observed'] and
          card['source_url'] == cut['url'] and card_args['detail_sha256'] == cut['bytes_sha256'] and
          observed == official._aware(cut['captured_at']) and
          official._aware(card['official_cutoff_at']) == official._aware(snapshot['published_cutoff_at']) and
          actual == expected, 'PUBLIC_STARTERS_SP_SOURCE_BINDING')
    riders = []
    for rider in card['riders']:
        name = _text(rider['name'], 80)
        _need(name and rider['registration_id'] != '000000', 'PUBLIC_STARTERS_SP_IDENTITY')
        riders.append(dict(number=rider['car'], registration=rider['registration_id'], name=name))
    return dict(race_id=card['race_id'], source_at=observed.isoformat(), riders=riders)


def _checked_starters(body):
    """Allow only display fields, including optional fields in an existing public document."""
    from race_ai import keirin_nationwide_forecast_view as nationwide

    _need(type(body) is dict and set(body) == {'schema', 'day', 'published_at', 'races'} and
          body['schema'] == STARTERS_SCHEMA, 'PUBLIC_STARTERS_DOCUMENT')
    day = nationwide._day(body['day'])
    posted = official._aware(body['published_at'])
    rows = body['races']
    _need(type(rows) is list and len(rows) <= nationwide.MAX_RACES, 'PUBLIC_STARTERS_ROWS')
    seen = set()
    for row in rows:
        _need(type(row) is dict and {'race_id', 'riders'} <= set(row) <=
              {'race_id', 'riders', 'source_at', 'source_url'}, 'PUBLIC_STARTERS_FIELDS')
        rid = row['race_id']
        _need(type(rid) is str and re.fullmatch(day.replace('-', '') + '[0-9]{4}', rid) and
              1 <= int(rid[-2:]) <= 12 and rid not in seen, 'PUBLIC_STARTERS_RACE')
        seen.add(rid)
        if 'source_at' in row:
            _need(type(row['source_at']) is str and official._aware(row['source_at']) <= posted,
                  'PUBLIC_STARTERS_SOURCE_CLOCK')
        if 'source_url' in row:
            _need(row['source_url'] in ('https://keirin.jp/sp/race', 'https://keirin.jp/sp/racelist'),
                  'PUBLIC_STARTERS_SAFE_SOURCE_URL')
        riders = row['riders']
        _need(type(riders) is list and 1 <= len(riders) <= 9, 'PUBLIC_STARTERS_RIDER_COUNT')
        cars, people = set(), set()
        for rider in riders:
            _need(type(rider) is dict and {'number', 'registration', 'name'} <= set(rider) <=
                  {'number', 'registration', 'name', 'region', 'style', 'grade', 'score'},
                  'PUBLIC_STARTERS_RIDER_FIELDS')
            car, registration, name = rider['number'], rider['registration'], rider['name']
            _need(type(car) is int and 1 <= car <= 9 and car not in cars and
                  type(registration) is str and re.fullmatch('[0-9]{6}', registration) and
                  registration != '000000' and registration not in people and _text(name, 80),
                  'PUBLIC_STARTERS_RIDER_IDENTITY')
            cars.add(car)
            people.add(registration)
            _need('region' not in rider or _text(rider['region'], 32), 'PUBLIC_STARTERS_RIDER_REGION')
            _need('style' not in rider or rider['style'] in tuple(STYLES), 'PUBLIC_STARTERS_RIDER_STYLE')
            _need('grade' not in rider or rider['grade'] in tuple(GRADES), 'PUBLIC_STARTERS_RIDER_GRADE')
            if 'score' in rider:
                score = rider['score']
                _need(type(score) in (int, float) and 0 <= score <= 150 and isfinite(score),
                      'PUBLIC_STARTERS_RIDER_SCORE')
    return body


def publish_starters(repo, *, day, rows, published_at, store=None):
    """Add named races to the existing public registry without replacing published rows."""
    from race_ai import keirin_public_forecasts as public

    posted = official._aware(published_at)
    body = _checked_starters(dict(schema=STARTERS_SCHEMA, day=day, published_at=posted.isoformat(), races=rows))
    if not rows:
        return dict(state='PUBLIC_STARTERS_NO_ELIGIBLE_RACES', day_jst=day, new_races=0)
    store = store or public.PublicForecastGit(repo)
    parent = store.head()
    _need(parent is not None, 'PUBLIC_STARTERS_REGISTRY_REQUIRED')
    path = f'starters/{day}.json'
    prior = public._previous_candidates(store, parent, path, day, _checked_starters)
    raw = store.read_previous(parent, f'forecasts/{day}.json')
    _need(raw is not None, 'PUBLIC_STARTERS_REGISTRY_REQUIRED')
    registry = public.checked(public._json(raw))
    registered = {race['race_id'] for race in registry['races']}
    old = {row['race_id']: row for row in prior['races']} if prior else {}
    new = {row['race_id']: row for row in body['races']}
    _need(registry['day'] == day and (old.keys() | new.keys()) <= registered, 'PUBLIC_STARTERS_UNREGISTERED_RACE')
    additions = {rid: row for rid, row in new.items() if rid not in old}
    state, commit = 'PUBLIC_STARTERS_CURRENT', parent
    if additions:
        _need(prior is None or official._aware(prior['published_at']) <= posted, 'PUBLIC_STARTERS_CLOCK_BACKWARDS')
        combined = {**old, **additions}
        body = _checked_starters(dict(body, races=[combined[rid] for rid in sorted(combined)]))
        commit, encoded = public._commit_projection(store, parent, path, body)
        public._push_projection(store, parent, path, commit, encoded)
        state = 'PUBLIC_STARTERS_UPDATED'
    return dict(state=state, day_jst=day, registered_races=len(registered),
                published_races=len(old) + len(additions), new_races=len(additions), commit=commit)


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
