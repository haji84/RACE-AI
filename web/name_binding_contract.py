"""Independent six-registration name proof; no source, save or prediction I/O.

Lexical abbreviation consistency is checked only after all independently
observed registrations agree. The original B program remains the digest input.
"""
import copy
from datetime import datetime
import hashlib
import re
import unicodedata

if __package__:
    from . import race_contract as facts
else:
    import race_contract as facts


MAX_BYTES = 64_000
TOP = {'schema_version', 'kind', 'race_id', 'closed_at', 'baseline_snapshot_id',
       'b_program_sha256', 'program_identity_sha256', 'generated_at',
       'capture_eligible_pre_race', 'source', 'bindings', 'snapshot_id'}
SOURCE = {'source_url', 'source_sha256', 'captured_at', 'available_at',
          'upstream_published_at', 'body_identity_verified', 'parser', 'observed_racers'}
OBSERVED = {'lane', 'racer_registration_id', 'name'}
BINDING = {'lane', 'racer_registration_id', 'program_name', 'verified_full_name', 'name_relation'}
RECEIPT = {'schema_version', 'request_id', 'baseline_request_id', 'snapshot',
           'runner_saved_at', 'cloud_saved_at', 'cloud_eligible_pre_race',
           'baseline_snapshot_id', 'b_program_sha256', 'program_identity_sha256'}
SHA = re.compile(r'[0-9a-f]{64}')
NONCE = re.compile(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}')


def _require(condition):
    if not condition:
        raise ValueError('NAME_BINDING_INVALID')


def _keys(value, fields):
    _require(isinstance(value, dict) and set(value) == fields)


def _sha(value):
    _require(isinstance(value, str) and SHA.fullmatch(value) is not None)


def _name(value):
    _require(isinstance(value, str) and 0 < len(value) <= 128)
    _require(all(not unicodedata.category(char).startswith('C') for char in value))
    normalized = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
    _require(bool(normalized) and len(normalized) <= 128)
    return normalized


def _relation(program_name, observed_name):
    original, observed = _name(program_name), _name(observed_name)
    if original == observed:
        return 'EXACT_CANONICAL_NAME'
    _require(len(original) == 4 and len(observed) > 4 and observed.startswith(original))
    return 'VERIFIED_B_ABBREVIATION'


def _context(race, baseline_snapshot_id, b_program_sha256, now):
    _sha(baseline_snapshot_id); _sha(b_program_sha256)
    _require(isinstance(now, datetime))
    clock = facts._time(now)
    day, closed, identities = facts._program(race)
    _require(clock.astimezone(facts.JST).date() == day)
    boats = {boat['lane']: boat for boat in race['boats']}
    for boat in boats.values():
        _require(re.fullmatch(r'[1-9][0-9]{3}', boat['racer_registration_id']) is not None)
        _name(boat['name'])
    return clock, day, closed, identities, boats


def _rows(rows, fields, identities):
    _require(isinstance(rows, list) and len(rows) == 6)
    result = {}
    for row in rows:
        _keys(row, fields)
        lane = row['lane']
        _require(type(lane) is int and lane in identities and lane not in result)
        _require(row['racer_registration_id'] == identities[lane]['racer_registration_id'])
        result[lane] = row
    return result


def build_name_binding(detail, race, *, baseline_snapshot_id, b_program_sha256, generated_at, now):
    """Freeze a parser-verified body projection, retaining both observed names."""
    try:
        clock, day, closed, identities, boats = _context(race, baseline_snapshot_id, b_program_sha256, now)
        url = facts._endpoint(race['race_id'], 'racelist')
        _require(isinstance(detail, dict) and detail['status'] == 'OFFICIAL_BODY_IDENTITY_VERIFIED'
            and detail['race_id'] == race['race_id'] and detail['date_jst'] == day.isoformat()
            and detail['venue'] == race['race_id'][9:11] and facts._time(detail['closed_at']) == closed
            and detail['source_url'] == url and detail['redistribution_authorized'] is False)
        _sha(detail['source_sha256'])
        captured = facts._time(detail['first_observed_at'])
        rows = detail['boats']
        _require(isinstance(rows, list) and len(rows) == 6)
        observed = []
        for row in rows:
            _require(isinstance(row, dict) and row['verified_source'] is True
                and row['race_id'] == race['race_id'] and row['source_url'] == url
                and facts._time(row['captured_at']) == captured and facts._time(row['closed_at']) == closed)
            observed.append({key: row[key] for key in OBSERVED})
        checked = _rows(observed, OBSERVED, identities)
        # Registration/body evidence is complete before any lexical check.
        bindings = [dict(lane=lane, racer_registration_id=identities[lane]['racer_registration_id'],
            program_name=boats[lane]['name'], verified_full_name=checked[lane]['name'],
            name_relation=_relation(boats[lane]['name'], checked[lane]['name'])) for lane in range(1, 7)]
        value = dict(schema_version=1, kind='OFFICIAL_RACELIST_NAME_BINDING', race_id=race['race_id'],
            closed_at=facts.stamp(closed), baseline_snapshot_id=baseline_snapshot_id,
            b_program_sha256=b_program_sha256, program_identity_sha256=facts.program_digest(race),
            generated_at=facts.stamp(generated_at), capture_eligible_pre_race=captured < closed,
            source=dict(source_url=url, source_sha256=detail['source_sha256'],
                captured_at=facts.stamp(captured), available_at=facts.stamp(captured),
                upstream_published_at=None, body_identity_verified=True, parser='official-racelist/v1',
                observed_racers=[checked[lane] for lane in range(1, 7)]), bindings=bindings)
        value['snapshot_id'] = hashlib.sha256(facts.canonical(value)).hexdigest()
        return validate_name_binding(value, race, baseline_snapshot_id=baseline_snapshot_id,
            b_program_sha256=b_program_sha256, now=clock)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError('NAME_BINDING_INVALID') from exc


def validate_name_binding(snapshot, race, *, baseline_snapshot_id, b_program_sha256, now):
    """Replay a pinned proof on its race's current JST date, including after close."""
    try:
        clock, day, closed, identities, boats = _context(race, baseline_snapshot_id, b_program_sha256, now)
        _keys(snapshot, TOP)
        _require(len(facts.canonical(snapshot)) <= MAX_BYTES)
        for field in ('snapshot_id', 'baseline_snapshot_id', 'b_program_sha256', 'program_identity_sha256'):
            _sha(snapshot[field])
        _require(type(snapshot['schema_version']) is int and snapshot['schema_version'] == 1
            and snapshot['kind'] == 'OFFICIAL_RACELIST_NAME_BINDING'
            and snapshot['race_id'] == race['race_id'] and snapshot['closed_at'] == facts.stamp(closed)
            and snapshot['baseline_snapshot_id'] == baseline_snapshot_id
            and snapshot['b_program_sha256'] == b_program_sha256
            and snapshot['program_identity_sha256'] == facts.program_digest(race))
        unsigned = {key:value for key,value in snapshot.items() if key != 'snapshot_id'}
        _require(snapshot['snapshot_id'] == hashlib.sha256(facts.canonical(unsigned)).hexdigest())
        source = snapshot['source']; _keys(source, SOURCE); _sha(source['source_sha256'])
        _require(source['source_url'] == facts._endpoint(race['race_id'], 'racelist')
            and source['body_identity_verified'] is True and source['parser'] == 'official-racelist/v1'
            and source['upstream_published_at'] is None)
        captured, available, generated = (facts._time(value) for value in
            (source['captured_at'], source['available_at'], snapshot['generated_at']))
        _require(source['captured_at'] == facts.stamp(captured)
            and source['available_at'] == source['captured_at']
            and snapshot['generated_at'] == facts.stamp(generated)
            and captured == available <= generated <= clock and generated < closed
            and all(value.astimezone(facts.JST).date() == day for value in (captured, generated))
            and snapshot['capture_eligible_pre_race'] is True)
        observed = _rows(source['observed_racers'], OBSERVED, identities)
        bindings = _rows(snapshot['bindings'], BINDING, identities)
        for lane in range(1, 7):
            row, observation = bindings[lane], observed[lane]
            _require(row['program_name'] == boats[lane]['name']
                and row['verified_full_name'] == observation['name']
                and row['name_relation'] == _relation(boats[lane]['name'], observation['name']))
        return copy.deepcopy(snapshot)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError('NAME_BINDING_INVALID') from exc


def validate_name_binding_receipt(receipt, race, *, baseline_snapshot_id, b_program_sha256, now):
    """Check separately measured durable clocks; this function makes no save claim."""
    try:
        clock, day, closed, _, _ = _context(race, baseline_snapshot_id, b_program_sha256, now)
        _keys(receipt, RECEIPT)
        _require(len(facts.canonical(receipt)) <= MAX_BYTES
            and type(receipt['schema_version']) is int and receipt['schema_version'] == 1
            and receipt['cloud_eligible_pre_race'] is True)
        for key in ('request_id', 'baseline_request_id'):
            _require(isinstance(receipt[key], str) and NONCE.fullmatch(receipt[key]) is not None)
        snapshot = validate_name_binding(receipt['snapshot'], race, baseline_snapshot_id=baseline_snapshot_id,
            b_program_sha256=b_program_sha256, now=clock)
        for key in ('baseline_snapshot_id', 'b_program_sha256', 'program_identity_sha256'):
            _require(receipt[key] == snapshot[key])
        runner, cloud = (facts._time(receipt[key]) for key in ('runner_saved_at', 'cloud_saved_at'))
        _require(facts._time(snapshot['generated_at']) <= runner <= cloud <= clock
            and runner < closed and cloud < closed
            and all(value.astimezone(facts.JST).date() == day for value in (runner, cloud)))
        return copy.deepcopy(receipt)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError('NAME_BINDING_RECEIPT_INVALID') from exc


def project_name_bound_program(snapshot, race, *, baseline_snapshot_id, b_program_sha256, now):
    """Return an explicit copy for validation; never rewrite stored B or receipts."""
    proof = validate_name_binding(snapshot, race, baseline_snapshot_id=baseline_snapshot_id,
        b_program_sha256=b_program_sha256, now=now)
    names = {row['lane']:row['verified_full_name'] for row in proof['bindings']}
    projected = copy.deepcopy(race)
    for boat in projected['boats']:
        boat['name'] = names[boat['lane']]
    return projected
