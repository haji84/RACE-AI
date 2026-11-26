"""Release only rider marginals from verified frozen research forecasts."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from math import fsum, isfinite
import re
import unicodedata

from .keirin_joint_forecast import EPS, JST, validate_forecast
from .keirin_nationwide_auto_generator import VENUE, digest, when


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RANK_DISTRIBUTION_V1'
MODEL_ID = 'comparison-B-residual'
SCOPE = 'PROSPECTIVE_RESEARCH'
PREMISE = 'ALL_FINISH_NO_TIES'
CALIBRATION = 'UNVALIDATED'
MAX_RACES = 300
RACE_FIELDS = {'race_id', 'cutoff_at', 'source_as_of', 'generated_at', 'frozen_at',
               'witnessed_at', 'source_joint_sha256', 'model_sha256', 'scope',
               'premise', 'calibration_status', 'riders'}


def _need(ok, code):
    if not ok:
        raise ValueError('KEIRIN_PUBLIC_RANK_' + code)


def _sha(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def _name(value):
    _need(type(value) is str and 0 < len(value) <= 100 and
          all(c not in '<>' and not unicodedata.category(c).startswith('C') for c in value),
          'NAME')
    normalized = ''.join(unicodedata.normalize('NFKC', value).split())
    _need(bool(normalized), 'NAME')
    return normalized


def _registration(value):
    return value is None or (type(value) is str and value != '000000' and
                             re.fullmatch('[0-9]{6}', value) is not None)


def _clock(value):
    try:
        return when(value)
    except (ValueError, OverflowError):
        raise ValueError('KEIRIN_PUBLIC_RANK_CLOCK') from None


def _chronology(row):
    cutoff, captured, generated, frozen, witnessed = (_clock(row.get(field)) for field in
        ('cutoff_at', 'source_as_of', 'generated_at', 'frozen_at', 'witnessed_at'))
    rid = row['race_id']
    source_day = date.fromisoformat(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}')
    cutoff_day = cutoff.astimezone(JST).date()
    _need(source_day <= cutoff_day <= source_day + timedelta(days=1) and
          captured <= generated <= frozen <= witnessed < cutoff, 'CHRONOLOGY')
    return witnessed


def _indexed_riders(riders, *, key):
    _need(type(riders) is list and 5 <= len(riders) <= 9, 'FIELD')
    rows = {}
    registrations = set()
    for row in riders:
        _need(type(row) is dict, 'RIDER')
        car = row.get(key)
        registration = row.get('registration')
        _need(type(car) is int and 1 <= car <= 9 and car not in rows and
              _registration(registration), 'RIDER')
        if registration is not None:
            _need(registration not in registrations, 'DUPLICATE_REGISTRATION')
            registrations.add(registration)
        _name(row.get('name'))
        rows[car] = row
    return rows


def project_rank_race(record, *, roster, expected_joint_sha256, frozen_at, witnessed_at):
    """Use an externally verified joint hash, named public field and archive clocks.

    The original captured cutoff is only a published-source cutoff. The caller
    supplies the original freeze and independent cipher witness, never the later
    public projection timestamp as proof of pre-cutoff generation.
    """
    try:
        validate_forecast(record)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ValueError('KEIRIN_PUBLIC_RANK_JOINT_INVALID') from None
    _need(_sha(expected_joint_sha256) and digest(record) == expected_joint_sha256 and
          _sha(record['model_version']) and record['model_id'] == MODEL_ID and
          record['scope'] == SCOPE, 'JOINT_BINDING')
    _need(type(roster) is dict and roster.get('race_id') == record['race_id'] and
          _clock(roster.get('cutoff_at')) == _clock(record['cutoff_at']), 'RACE_ROSTER')
    original = _indexed_riders(record['riders'], key='car')
    public = _indexed_riders(roster.get('riders'), key='number')
    _need(original.keys() == public.keys(), 'ROSTER_CARS')
    riders = []
    for car, rider in sorted(public.items()):
        matched = original[car]
        registration = rider.get('registration')
        saved_registration = matched.get('registration')
        _need(_name(rider['name']) == _name(matched['name']) and
              (registration is None or saved_registration is None or registration == saved_registration),
              'ROSTER_IDENTITY')
        riders.append(dict(number=car, name=rider['name'], registration=registration,
                           probabilities=matched['rank_probabilities'].copy()))
    row = dict(race_id=record['race_id'], cutoff_at=record['cutoff_at'],
               source_as_of=record['source_as_of'], generated_at=record['generated_at'],
               frozen_at=frozen_at, witnessed_at=witnessed_at, source_joint_sha256=expected_joint_sha256,
               model_sha256=record['model_version'], scope=SCOPE, premise=PREMISE,
               calibration_status=CALIBRATION, riders=riders)
    _chronology(row)
    return row


def checked_day(packet):
    """Validate the disclosure shape and conservation of every rider and rank."""
    _need(type(packet) is dict and set(packet) == {'schema', 'day', 'published_at', 'races'} and
          packet['schema'] == SCHEMA, 'SCHEMA')
    day = packet['day']
    try:
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day, 'DAY')
    except ValueError:
        raise ValueError('KEIRIN_PUBLIC_RANK_DAY') from None
    published = _clock(packet['published_at'])
    races = packet['races']
    _need(type(races) is list and 1 <= len(races) <= MAX_RACES, 'DAY_RACES')
    seen = set()
    for row in races:
        _need(type(row) is dict and set(row) == RACE_FIELDS, 'RACE_FIELDS')
        rid = row['race_id']
        _need(type(rid) is str and VENUE.fullmatch(rid) and rid[:8] == day.replace('-', '') and
              1 <= int(rid[-2:]) <= 12 and rid not in seen, 'RACE_ID')
        seen.add(rid)
        _need(row['scope'] == SCOPE and row['premise'] == PREMISE and
              row['calibration_status'] == CALIBRATION and _sha(row['source_joint_sha256']) and
              _sha(row['model_sha256']) and _chronology(row) <= published, 'RACE_PROVENANCE')
        riders = _indexed_riders(row['riders'], key='number')
        for rider in riders.values():
            _need(set(rider) == {'number', 'name', 'registration', 'probabilities'}, 'RIDER_FIELDS')
            probs = rider['probabilities']
            _need(type(probs) is list and len(probs) == len(riders) and
                  all(type(p) in (int, float) and 0 <= p <= 1 and isfinite(p) for p in probs) and
                  abs(fsum(probs) - 1.) <= EPS, 'RIDER_RANK_ROW')
        _need(all(abs(fsum(column) - 1.) <= EPS for column in
                  zip(*(rider['probabilities'] for rider in riders.values()), strict=True)),
              'RANK_COLUMN')
    return packet


def project_recovered_day(raw_cipher, private_pem, receipt_raw, publication_raw, witness_raw,
                          public_rosters, *, published_at):
    """Run the existing independent RSA recovery checks before any projection.

    The workflow must supply the pinned Git receipts and the independently
    downloaded, validated roster. No source bytes or full guesses leave memory.
    """
    from scripts import keirin_joint_forward_score as forward
    from scripts import keirin_joint_original_readback as reader
    from scripts import keirin_joint_recovery_score as recovery

    try:
        receipt, publication, witness = (recovery._json(raw, 128 * 1024) for raw in
                                         (receipt_raw, publication_raw, witness_raw))
        recovery._anchors(receipt, publication, witness)
        _need(type(raw_cipher) is bytes and 0 < len(raw_cipher) <= recovery.MAX_CIPHER and
              len(raw_cipher) == receipt['recovery_cipher_bytes'] and
              sha256(raw_cipher).hexdigest() == receipt['recovery_cipher_sha256'], 'RECOVERY_CIPHER')
        _need(type(private_pem) is bytes and 0 < len(private_pem) <= 20000, 'OWNER_SECRET')
        recovery._guard_sources()
        verified = reader.verify_recovery(raw_cipher, private_pem,
            expected_original_note_sha256=receipt['original_note_sha256'],
            expected_original_cipher_sha256=receipt['original_cipher_sha256'],
            expected_original_archive_commit=receipt['original_archive_commit'],
            expected_original_created_at=receipt['expected_original_created_at'],
            expected_original_git_readback_at=receipt['expected_original_git_readback_at'])
        now = datetime.now(timezone.utc)
        recovery._readback(verified, receipt, publication, now)
        payload = reader.history.decrypt_evidence(raw_cipher, private_pem)
        note_raw = reader._b64(payload['original_note_b64'], reader.MAX_NOTE)
        _need(sha256(note_raw).hexdigest() == receipt['original_note_sha256'], 'RECOVERY_NOTE')
        note = reader._json(note_raw)
        ids, frozen, _ = forward._publication(note, publication, witness,
                                              receipt['original_note_sha256'], now)
        day = verified['day_jst']
        files, _ = reader._files(note, day)
        records = forward._cohort(files['comparison_joint_originals.json'], ids)
        projections = forward._cohort(files['joint_forecasts.json'], ids)
        _need(type(public_rosters) is list and len(public_rosters) <= MAX_RACES and
              all(type(row) is dict and type(row.get('race_id')) is str for row in public_rosters),
              'PUBLIC_ROSTERS')
        rosters = {row['race_id']: row for row in public_rosters}
        _need(len(rosters) == len(public_rosters) and ids <= rosters.keys(), 'PUBLIC_ROSTER_COHORT')
        return checked_day(dict(schema=SCHEMA, day=day, published_at=published_at, races=[
            project_rank_race(records[rid], roster=rosters[rid],
                expected_joint_sha256=projections[rid]['source_joint_sha256'],
                frozen_at=frozen, witnessed_at=witness['observed_at']) for rid in sorted(ids)]))
    except Exception:
        raise ValueError('KEIRIN_PUBLIC_RANK_RECOVERY_OR_PROJECTION_HELD') from None
