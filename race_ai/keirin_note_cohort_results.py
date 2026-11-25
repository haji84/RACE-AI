"""Admit owner-decrypted two-source trifecta observations for research scoring.

The caller binds the bytes to the existing authenticated note index and
supplies a result-side cutoff only after independently checking the actual
starting field against the registered field. This module does not decode
the encrypted feed or authenticate a post-race field from the note alone.
"""

from datetime import date, datetime

from race_ai.keirin_note_feed import checked_result_checks, result_clock
from race_ai.keirin_secondary_result_consensus import RID
from scripts.keirin_note_collect_results import SCHEMA as PACKET, _status, checked_observation


SCHEMA = 'KEIRIN_NOTE_COHORT_RESULT_READBACK_V1'
RESULT_STATES = {'MATCHED': 'matched', 'HOLD': 'held', 'PENDING': 'pending'}


def _need(condition, reason):
    if not condition:
        raise ValueError('KEIRIN_NOTE_COHORT_' + reason)


def _cutoff(value):
    _need(type(value) is str, 'CUTOFF_REQUIRED')
    at = datetime.fromisoformat(value)
    _need(at.utcoffset() is not None, 'CUTOFF_TIME_ZONE_REQUIRED')
    return at


def _observations(packets, day, read_at):
    latest = {}
    for packet in packets:
        _need(type(packet) is dict and set(packet) == {'schema', 'day_jst', 'observations'} and
              packet['schema'] == PACKET and packet['day_jst'] == day and
              type(packet['observations']) is list and bool(packet['observations']), 'PACKET_SCHEMA_OR_DAY')
        in_packet = set()
        for row in packet['observations']:
            checked_observation(row)
            race = row['race_id']
            _need(race.startswith(day.replace('-', '')) and race not in in_packet, 'PACKET_RACE_ID')
            in_packet.add(race)
            predecessor = latest.get(race)
            captured = result_clock(row['captured_at'])
            prior_digest = predecessor['observation_sha256'] if predecessor is not None else None
            _need(row['previous_observation_sha256'] == prior_digest and captured <= read_at,
                  'REVISION_PREDECESSOR_OR_READBACK_TIME')
            if predecessor is not None:
                _need(result_clock(predecessor['captured_at']) < captured, 'REVISION_CLOCK_NOT_INCREASING')
            latest[race] = row
    return latest


def admit(readback, *, day, registered):
    """Return (outcomes, matched_trifectas, checked_at) for the registered day.

    Unregistered but valid note observations cannot influence a score. A
    missing digest-backed observation is an invalid/incomplete readback.
    A race with no observation and no index digest remains missing.
    """
    _need(type(day) is str and date.fromisoformat(day).isoformat() == day, 'DAY')
    _need(type(readback) is dict and set(readback) == {'schema', 'date', 'checked_at', 'packets', 'result_checks'} and
          readback['schema'] == SCHEMA and readback['date'] == day and type(readback['packets']) is list,
          'READBACK_SCHEMA_OR_DAY')
    day_prefix = day.replace('-', '')
    _need(type(registered) is dict and all(type(race) is str and RID.fullmatch(race) and
          race.startswith(day_prefix) for race in registered), 'REGISTERED_RACE_IDS')
    read_at = result_clock(readback['checked_at'])
    checks = checked_result_checks(readback['result_checks'])
    _need(all(race.startswith(day_prefix) and result_clock(check['checked_at']) <= read_at
              for race, check in checks.items()), 'INDEX_DAY_OR_READBACK_TIME')
    latest = _observations(readback['packets'], day, read_at)
    _need(set(latest) == {race for race, check in checks.items() if check['digest'] is not None},
          'INDEX_OBSERVATION_SET_MISMATCH')
    for race, row in latest.items():
        index = checks[race]
        _need(index['digest'] == row['observation_sha256'] and index['status'] == _status(row) and
              result_clock(row['captured_at']) <= result_clock(index['checked_at']), 'INDEX_LATEST_REVISION_MISMATCH')

    outcomes = {}
    winners = {}
    for race in sorted(latest.keys() & registered.keys()):
        row = latest[race]
        state = RESULT_STATES[checks[race]['status']]
        if state == 'held':
            outcomes[race] = {'state': state, 'reason': row['state'].removeprefix('HOLD_').lower()}
        elif state == 'pending':
            outcomes[race] = {'state': state}
        else:
            entry = registered[race]
            _need(type(entry) is dict, 'REGISTERED_ENTRY')
            actual_cutoff = entry.get('result_cutoff_at')
            if actual_cutoff is None:
                outcomes[race] = {'state': 'held', 'reason': 'independent_roster_or_cutoff_unverified'}
                continue
            cutoff = max(_cutoff(entry.get('cutoff_at')), _cutoff(actual_cutoff))
            cars = entry.get('starter_cars')
            _need(type(cars) is list and 3 <= len(cars) <= 9 and
                  all(type(car) is int and 1 <= car <= 9 for car in cars) and len(set(cars)) == len(cars),
                  'INVALID_REGISTERED_STARTERS')
            if any(result_clock(receipt['observed_at']) < cutoff for receipt in row['provider_receipts']):
                outcomes[race] = {'state': 'held', 'reason': 'source_observed_before_result_cutoff'}
                continue
            if not set(row['winning_triple']).issubset(cars):
                outcomes[race] = {'state': 'held', 'reason': 'winner_outside_registered_starters'}
                continue
            outcomes[race] = {'state': state}
            winners[race] = list(row['winning_triple'])
    return outcomes, winners, readback['checked_at']
