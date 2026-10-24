"""Strict separate source packet for name-bound numeric research.

SQLite memory readback is explicitly nondurable. The caller and cloud store
must independently measure durable file and cloud readback clocks.
"""
import copy
import hashlib

if __package__:
    from . import race_contract as facts
    from .evaluation_contract import _checked_prediction
    from .name_binding_contract import validate_finalized_name_binding, project_name_bound_program
    from .original_exhibition_contract import validate_original_observation
else:
    import race_contract as facts
    from evaluation_contract import _checked_prediction
    from name_binding_contract import validate_finalized_name_binding, project_name_bound_program
    from original_exhibition_contract import validate_original_observation

MAX_BYTES = 256_000
TOP = {'schema_version', 'kind', 'race_id', 'date_jst', 'closed_at',
    'program_identity_sha256', 'validation_program_identity_sha256', 'baseline_link',
    'name_binding_link', 'parents_read_at', 'generated_at', 'beforeinfo_storage_scope',
    'beforeinfo_record', 'original_observation', 'snapshot_id'}


def _require(value):
    if not value: raise ValueError('NAME_BOUND_INPUTS_INVALID')


def _digest(value): return hashlib.sha256(facts.canonical(value)).hexdigest()


def _context(race, baseline, binding, now):
    clock = facts._time(now)
    day, closed, _ = facts._program(race)
    _require(clock.astimezone(facts.JST).date() == day)
    checked = _checked_prediction(baseline, race, clock, day, closed)
    _require(checked is not None)
    envelope = validate_finalized_name_binding(binding, race, baseline, now=clock)
    receipt = envelope['receipt']
    projected = project_name_bound_program(receipt['snapshot'], race,
        baseline_snapshot_id=receipt['baseline_snapshot_id'], b_program_sha256=receipt['b_program_sha256'], now=clock)
    base_link = dict(request_id=baseline['request_id'], snapshot_id=baseline['snapshot']['snapshot_id'],
        receipt_sha256=_digest(baseline), b_program_sha256=baseline['program_sha256'], cloud_saved_at=baseline['cloud_saved_at'])
    name_link = dict(request_id=receipt['request_id'], snapshot_id=receipt['snapshot']['snapshot_id'],
        envelope_sha256=_digest(envelope), receipt_confirmed_at=envelope['finalization']['receipt_confirmed_at'])
    return clock, day, closed, projected, base_link, name_link


def build_name_bound_inputs(beforeinfo_record, original_observation, race, baseline, binding, *, parents_read_at, generated_at, now):
    try:
        _, day, closed, projected, base_link, name_link = _context(race, baseline, binding, now)
        value = dict(schema_version=1, kind='NAME_BOUND_EXHIBITION_INPUTS', race_id=race['race_id'],
            date_jst=day.isoformat(), closed_at=facts.stamp(closed), program_identity_sha256=facts.program_digest(race),
            validation_program_identity_sha256=facts.program_digest(projected), baseline_link=base_link, name_binding_link=name_link,
            parents_read_at=facts.stamp(parents_read_at), generated_at=facts.stamp(generated_at),
            beforeinfo_storage_scope='SQLITE_MEMORY_NOT_DURABLE', beforeinfo_record=copy.deepcopy(beforeinfo_record),
            original_observation=copy.deepcopy(original_observation))
        value['snapshot_id'] = _digest(value)
        return validate_name_bound_inputs(value, race, baseline, binding, now=now)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError('NAME_BOUND_INPUTS_INVALID') from exc


def validate_name_bound_inputs(packet, race, baseline, binding, *, now):
    try:
        clock, day, closed, projected, base_link, name_link = _context(race, baseline, binding, now)
        _require(isinstance(packet, dict) and set(packet) == TOP and len(facts.canonical(packet)) <= MAX_BYTES)
        _require(type(packet['schema_version']) is int and packet['schema_version'] == 1
            and packet['kind'] == 'NAME_BOUND_EXHIBITION_INPUTS' and packet['race_id'] == race['race_id']
            and packet['date_jst'] == day.isoformat() and packet['closed_at'] == facts.stamp(closed)
            and packet['program_identity_sha256'] == facts.program_digest(race)
            and packet['validation_program_identity_sha256'] == facts.program_digest(projected)
            and packet['baseline_link'] == base_link and packet['name_binding_link'] == name_link
            and packet['beforeinfo_storage_scope'] == 'SQLITE_MEMORY_NOT_DURABLE'
            and packet['snapshot_id'] == _digest({k:v for k,v in packet.items() if k != 'snapshot_id'}))
        record = facts.validate_record(packet['beforeinfo_record'], projected, clock, require_same_day=True)
        _require(record['kind'] == 'beforeinfo' and record['status'] == 'AVAILABLE'
            and record['storage_eligible_pre_race'] is True and record['eligible_pre_race'] is True
            and record.get('rights_review') == 'user-confirmation-2026-10-15-official-facts'
            and all(b['display_time'] is not None for b in record['data']['boats']))
        original = packet['original_observation']
        validate_original_observation(original, projected, clock)
        _require(original['status'] == 'AVAILABLE' and original['capture_eligible_pre_race'] is True)
        displays = {b['lane']:b['display_time'] for b in record['data']['boats']}
        _require(all(b['display_time_s'] == displays[b['lane']] for b in original['boats']))
        parents, generated = (facts._time(packet[k]) for k in ('parents_read_at', 'generated_at'))
        captures = [facts._time(record['captured_at']), *[facts._time(s['captured_at']) for s in original['sources']]]
        saved = facts._time(record['saved_at'])
        _require(packet['parents_read_at'] == facts.stamp(parents) and packet['generated_at'] == facts.stamp(generated)
            and max(facts._time(base_link['cloud_saved_at']), facts._time(name_link['receipt_confirmed_at'])) <= parents <= min(captures)
            and max(*captures, saved) <= generated <= clock
            and all(t.astimezone(facts.JST).date() == day and t < closed for t in [parents, generated, saved, *captures]))
        return copy.deepcopy(packet)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError, RecursionError) as exc:
        raise ValueError('NAME_BOUND_INPUTS_INVALID') from exc
