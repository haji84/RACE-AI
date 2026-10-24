"""Independent postclose labels bound to one fully finalized forecast.

The full-name projection is private validation context. B, its parents, and
the source record are never rewritten or published to the legacy race store.
"""
import copy
import hashlib
import re

if __package__:
    from . import race_contract as facts
    from .name_bound_inputs import _context
    from .name_bound_prediction import validate_name_bound_envelope
else:
    import race_contract as facts
    from name_bound_inputs import _context
    from name_bound_prediction import validate_name_bound_envelope

MAX_BYTES = 256_000
TOP = set('schema_version kind race_id date_jst closed_at program_identity_sha256 validation_program_identity_sha256 forecast_link parents_read_at generated_at result_storage_scope result_record snapshot_id'.split())
LINK = set('request_id snapshot_id envelope_sha256 baseline_request_id name_binding_request_id receipt_confirmed_at'.split())
RECEIPT = set('schema_version request_id forecast_request_id snapshot runner_saved_at cloud_saved_at cloud_eligible_pre_race'.split())
MARKER = set('schema_version race_id request_id forecast_request_id snapshot_id receipt_sha256 receipt_confirmed_at'.split())
INVALID = (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError)


def _require(value):
    if not value:
        raise ValueError('NAME_BOUND_RESULT_INVALID')


def digest(value):
    return hashlib.sha256(facts.canonical(value)).hexdigest()


def _nonce(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}', value) is not None


def _stamp(value):
    parsed = facts._time(value)
    _require(isinstance(value, str) and value == facts.stamp(parsed))
    return parsed


def result_context(race, forecast, now):
    """Replay the complete forecast and its own parents after today's close."""
    try:
        checked = validate_name_bound_envelope(forecast, race, now=now)
        clock, day, closed, projected, base_link, name_link = _context(
            race, checked['baseline'], checked['name_binding'], now)
        confirmed = facts._time(checked['finalization']['receipt_confirmed_at'])
        _require(confirmed <= closed <= clock)
        receipt = checked['receipt']
        link = dict(request_id=receipt['request_id'], snapshot_id=receipt['snapshot']['snapshot_id'],
            envelope_sha256=digest(checked), baseline_request_id=base_link['request_id'],
            name_binding_request_id=name_link['request_id'], receipt_confirmed_at=checked['finalization']['receipt_confirmed_at'])
        return clock, day, closed, copy.deepcopy(projected), link
    except INVALID as exc:
        raise ValueError('NAME_BOUND_RESULT_INVALID') from exc


def build_name_bound_result(record, race, forecast, *, parents_read_at, generated_at, now):
    """Build a detached packet; memory saved_at remains its actual measured value."""
    try:
        _, day, closed, projected, link = result_context(race, forecast, now)
        packet = dict(schema_version=1, kind='NAME_BOUND_OFFICIAL_RESULT_LABEL', race_id=race['race_id'],
            date_jst=day.isoformat(), closed_at=facts.stamp(closed), program_identity_sha256=facts.program_digest(race),
            validation_program_identity_sha256=facts.program_digest(projected), forecast_link=link,
            parents_read_at=facts.stamp(parents_read_at), generated_at=facts.stamp(generated_at),
            result_storage_scope='SQLITE_MEMORY_NOT_DURABLE', result_record=copy.deepcopy(record))
        packet['snapshot_id'] = digest(packet)
        return validate_name_bound_result(packet, race, forecast, now=now)
    except INVALID as exc:
        raise ValueError('NAME_BOUND_RESULT_INVALID') from exc


def validate_name_bound_result(packet, race, forecast, *, now):
    try:
        clock, day, closed, projected, link = result_context(race, forecast, now)
        _require(isinstance(packet, dict) and set(packet) == TOP and len(facts.canonical(packet)) <= MAX_BYTES)
        _require(type(packet['schema_version']) is int and packet['schema_version'] == 1
            and packet['kind'] == 'NAME_BOUND_OFFICIAL_RESULT_LABEL' and packet['race_id'] == race['race_id']
            and packet['date_jst'] == day.isoformat() and packet['closed_at'] == facts.stamp(closed)
            and packet['program_identity_sha256'] == facts.program_digest(race)
            and packet['validation_program_identity_sha256'] == facts.program_digest(projected)
            and facts.canonical(packet['forecast_link']) == facts.canonical(link)
            and packet['result_storage_scope'] == 'SQLITE_MEMORY_NOT_DURABLE'
            and packet['snapshot_id'] == digest({k:v for k,v in packet.items() if k != 'snapshot_id'}))
        record = facts.validate_record(packet['result_record'], projected, clock, require_same_day=True)
        _require(record['kind'] == 'raceresult' and record['status'] == 'AVAILABLE'
            and record['body_identity_verified'] is True and record['eligible_pre_race'] is False
            and record['storage_eligible_pre_race'] is False
            and record.get('rights_review') == 'user-confirmation-2026-10-15-official-facts'
            and isinstance(record['data'], dict) and len(record['data']['results']) == 6)
        parents, generated = map(_stamp, (packet['parents_read_at'], packet['generated_at']))
        # Parser-owned strings retain their original precision/offset and hash.
        # Only newly authored packet/envelope stamps require canonical spelling.
        captured, saved = map(facts._time, (record['captured_at'], record['saved_at']))
        _require(facts._time(link['receipt_confirmed_at']) <= closed <= parents <= captured <= saved <= generated <= clock
            and all(t.astimezone(facts.JST).date() == day for t in (parents, captured, saved, generated)))
        return copy.deepcopy(packet)
    except INVALID as exc:
        raise ValueError('NAME_BOUND_RESULT_INVALID') from exc


def validate_name_bound_result_envelope(envelope, race, forecast, *, now):
    try:
        clock, day, closed, _, link = result_context(race, forecast, now)
        _require(isinstance(envelope, dict) and set(envelope) == {'receipt', 'finalization'}
            and len(facts.canonical(envelope)) <= MAX_BYTES)
        receipt, marker = envelope['receipt'], envelope['finalization']
        _require(isinstance(receipt, dict) and set(receipt) == RECEIPT
            and type(receipt['schema_version']) is int and receipt['schema_version'] == 1
            and _nonce(receipt['request_id']) and _nonce(receipt['forecast_request_id'])
            and receipt['forecast_request_id'] == link['request_id'] and receipt['cloud_eligible_pre_race'] is False)
        packet = validate_name_bound_result(receipt['snapshot'], race, forecast, now=clock)
        _require(isinstance(marker, dict) and set(marker) == MARKER
            and type(marker['schema_version']) is int and marker['schema_version'] == 1)
        expected = dict(schema_version=1, race_id=race['race_id'], request_id=receipt['request_id'],
            forecast_request_id=receipt['forecast_request_id'], snapshot_id=packet['snapshot_id'],
            receipt_sha256=digest(receipt), receipt_confirmed_at=marker['receipt_confirmed_at'])
        _require(facts.canonical(marker) == facts.canonical(expected))
        generated = _stamp(packet['generated_at'])
        runner, cloud, confirmed = map(_stamp, (receipt['runner_saved_at'], receipt['cloud_saved_at'], marker['receipt_confirmed_at']))
        _require(closed <= generated <= runner <= cloud <= confirmed <= clock
            and all(t.astimezone(facts.JST).date() == day for t in (runner, cloud, confirmed)))
        return copy.deepcopy(envelope)
    except INVALID as exc:
        raise ValueError('NAME_BOUND_RESULT_ENVELOPE_INVALID') from exc


def result_bundle(envelope, race, forecast, *, now):
    """Convert only validated labels to the unchanged schema1 evaluation input."""
    checked = validate_name_bound_result_envelope(envelope, race, forecast, now=now)
    receipt = checked['receipt']
    packet = receipt['snapshot']
    record = packet['result_record']
    projected_hash = packet['validation_program_identity_sha256']
    bundle = dict(schema_version=1, race_id=packet['race_id'], date_jst=packet['date_jst'], closed_at=packet['closed_at'],
        program_sha256=projected_hash, published_at=checked['finalization']['receipt_confirmed_at'],
        latest={'raceresult':record['snapshot_id']}, records=[dict(record=record, program_sha256=projected_hash,
            cloud_saved_at=receipt['cloud_saved_at'], cloud_eligible_pre_race=False)])
    # Keep the public conversion coupled to the legacy consumer's exact contract.
    projected = result_context(race, forecast, now)[3]
    facts.validate_cloud_bundle(bundle, projected, now)
    return bundle
