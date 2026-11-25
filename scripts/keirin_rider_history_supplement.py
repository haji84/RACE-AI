"""Build private descriptive history without rewriting any forecast original.

The source racecard identities must be checked independently against the
current official register. Source availability is conservatively assigned to
the actual build time, separate from the dates of the historical finishes.
"""
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
import re

from race_ai.keirin_note_view import canonical, _private_root, _create
from race_ai.keirin_public_two_source_normalizer import _url_role
from scripts.keirin_rider_profile_identity import IdentityIndex, name_key


SCHEMA = 'RACE_AI_KEIRIN_RIDER_HISTORY_SUPPLEMENT_V1'
RID = re.compile(r'20[0-9]{10}')
HASH = re.compile(r'[a-f0-9]{64}')


def need(condition, code):
    if not condition:
        raise ValueError('KEIRIN_RIDER_HISTORY_' + code)


def instant(value):
    need(isinstance(value, str), 'CLOCK_INVALID')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.utcoffset() is not None, 'CLOCK_INVALID')
    return parsed.astimezone(timezone.utc)


def indexed(rows, code):
    need(isinstance(rows, list), code)
    result = {}
    for row in rows:
        need(isinstance(row, dict) and isinstance(row.get('race_id'), str)
             and RID.fullmatch(row['race_id']), code)
        need(row['race_id'] not in result, 'DUPLICATE_' + code)
        result[row['race_id']] = row
    return result


def _people(rows, number):
    need(isinstance(rows, list) and 5 <= len(rows) <= 9, 'ROSTER_IDENTITY_MISMATCH')
    output = {}
    for row in rows:
        need(isinstance(row, dict), 'ROSTER_IDENTITY_MISMATCH')
        car = row.get(number)
        need(type(car) is int and 1 <= car <= 9 and car not in output
             and isinstance(row.get('name'), str) and name_key(row['name']), 'ROSTER_IDENTITY_MISMATCH')
        output[car] = row
    return output


def roster_day(roster):
    races = indexed(roster.get('races'), 'ROSTER_RACE')
    days = {date.fromisoformat(race_id[:8]).isoformat() for race_id in races}
    need(len(days) == 1, 'ROSTER_DATE')
    day = next(iter(days))
    need(roster.get('date', day) == day, 'ROSTER_DATE')
    return day


def build_supplement(roster_raw, identities, registry, book, *, registry_sha256,
                     archive_sha256s, clock):
    """Return a new display sidecar and count-only report; inputs stay untouched."""
    need(type(roster_raw) is bytes and 0 < len(roster_raw) <= 12 * 1024 * 1024, 'ROSTER_BYTES_INVALID')
    need(isinstance(registry, dict) and registry.get('complete') is True, 'REGISTRY_INCOMPLETE')
    need(isinstance(registry_sha256, str) and HASH.fullmatch(registry_sha256), 'REGISTRY_SHA_INVALID')
    need(isinstance(identities, dict) and identities.get('schema') == 'KEIRIN_SAVED_ROSTER_IDENTITIES_V1', 'IDENTITY_SCHEMA')
    need(identities.get('registry_sha256') == registry_sha256, 'REGISTRY_SHA_MISMATCH')
    roster_sha = sha256(roster_raw).hexdigest()
    need(identities.get('source_roster_sha256') in (None, roster_sha), 'ROSTER_SHA_MISMATCH')
    need(isinstance(archive_sha256s, list) and len(archive_sha256s) == 2
         and len(set(archive_sha256s)) == 2
         and all(isinstance(value, str) and HASH.fullmatch(value) for value in archive_sha256s), 'ARCHIVE_SHAS_INVALID')
    need(isinstance(clock, datetime) and clock.utcoffset() is not None, 'CLOCK_INVALID')
    now = clock.astimezone(timezone.utc)
    need(instant(registry['retrieval_completed_at']) <= now, 'REGISTRY_CAPTURE_AFTER_BUILD')
    need(instant(identities['generated_at']) <= now, 'IDENTITY_CLOCK_AFTER_BUILD')
    catalog = IdentityIndex(registry['riders'], [])
    sources = indexed(identities['races'], 'IDENTITY_RACE')
    roster = json.loads(roster_raw)
    need(isinstance(roster, dict), 'ROSTER_SCHEMA')
    races = indexed(roster.get('races'), 'ROSTER_RACE')
    day = roster_day(roster)
    attached, held = [], Counter()
    for race_id, race in sorted(races.items()):
        need(race_id[:8] == day.replace('-', ''), 'ROSTER_RACE_DAY')
        source = sources.get(race_id)
        if source is None:
            held['IDENTITY_SOURCE_MISSING'] += 1
            continue
        try:
            expected = _people(race.get('riders'), 'number')
            people = _people(source.get('riders'), 'car')
            need(expected.keys() == people.keys(), 'ROSTER_IDENTITY_MISMATCH')
            need(isinstance(source.get('source_sha256'), str) and HASH.fullmatch(source['source_sha256']), 'IDENTITY_SOURCE_SHA_INVALID')
            _url_role(source['source_url'], 'k', race_id)
            need(instant(source['captured_at']) <= instant(identities['generated_at']) <= now, 'IDENTITY_CAPTURE_TIME_INVALID')
            riders, registrations = [], set()
            for car, person in sorted(people.items()):
                old = expected[car]
                need(name_key(person['name']) == name_key(old['name']), 'ROSTER_IDENTITY_MISMATCH')
                registration = catalog.bind((name_key(person['name']), person.get('cohort'), person.get('prefecture')))
                need(registration is not None and registration == person.get('registration')
                     and registration not in registrations, 'OFFICIAL_IDENTITY_BINDING_FAILED')
                need(old.get('registration') in (None, registration), 'ROSTER_IDENTITY_MISMATCH')
                registrations.add(registration)
                history = book.finish_history(registration, race_id=race_id)
                riders.append(dict(car=car, name=old['name'], registration=registration, history=history))
            attached.append(dict(race_id=race_id, riders=riders))
        except (ValueError, TypeError, KeyError) as error:
            code = str(error).removeprefix('KEIRIN_RIDER_HISTORY_')
            if code not in {'ROSTER_IDENTITY_MISMATCH', 'IDENTITY_SOURCE_SHA_INVALID',
                            'IDENTITY_CAPTURE_TIME_INVALID', 'OFFICIAL_IDENTITY_BINDING_FAILED'}:
                code = 'IDENTITY_SOURCE_INVALID'
            held[code] += 1
    doc = dict(schema=SCHEMA, generated_at=now.isoformat(), knowledge_as_of=now.isoformat(),
               source_roster_sha256=roster_sha, registry_sha256=registry_sha256,
               archive_sha256s=list(archive_sha256s), predictive_model_changed=False, races=attached)
    summary = dict(schema='KEIRIN_RIDER_HISTORY_BUILD_SUMMARY_V1', generated_at=now.isoformat(),
                   registered_races=len(races), attached_races=len(attached), held_races=sum(held.values()),
                   attached_riders=sum(len(row['riders']) for row in attached), holds_by_reason=dict(held),
                   supplement_sha256=sha256(canonical(doc)).hexdigest(), source_roster_sha256=roster_sha,
                   registry_sha256=registry_sha256, archive_sha256s=list(archive_sha256s),
                   predictive_model_changed=False, accuracy_improvement_proven=False,
                   source_availability='CURRENT_BUILD_TIME_NOT_HISTORICAL_PUBLICATION_ATTESTATION')
    return doc, summary


def write_supplement(path, document):
    path = Path(path)
    _private_root(path.parent)
    need(not path.exists(), 'OUTPUT_ALREADY_EXISTS')
    _create(path, canonical(document))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster', type=Path, required=True)
    parser.add_argument('--identities', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--registry-sha256', required=True)
    parser.add_argument('--archive-db', type=Path, action='append', required=True)
    parser.add_argument('--archive-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        from scripts.keirin_build_rider_dossiers import load_archive_book
        _private_root(args.output.parent)
        need(not args.output.exists(), 'OUTPUT_ALREADY_EXISTS')
        registry_raw = args.registry.read_bytes()
        need(sha256(registry_raw).hexdigest() == args.registry_sha256, 'REGISTRY_SHA_MISMATCH')
        registry = json.loads(registry_raw)
        roster_raw = args.roster.read_bytes()
        roster = json.loads(roster_raw)
        book, _, archive_summary = load_archive_book(args.archive_db, registry, roster_day(roster),
            archive_manifest=json.loads(args.archive_manifest.read_bytes()))
        archive_shas = archive_summary['archive_sha256s']
        document, summary = build_supplement(roster_raw, json.loads(args.identities.read_bytes()), registry,
            book, registry_sha256=args.registry_sha256, archive_sha256s=archive_shas,
            clock=datetime.now(timezone.utc))
        write_supplement(args.output, document)
        summary['archive_admission'] = archive_summary
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
    except Exception:
        raise SystemExit('HOLD_RIDER_HISTORY_SUPPLEMENT_INVALID') from None


if __name__ == '__main__':
    main()
