"""Bounded, private result-reconciliation ledger for the existing encrypted vault.

This module does not access the network, alter predictions, or determine hits.
The caller must load and authenticate the saved-day view before admitting rows.
"""
from datetime import date, datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
import re

SCHEMA = 'RACE_AI_RESULT_DUE_LEDGER_V1'
MAX_PENDING = 8192
MAX_SCANNED_DAYS = 1200
MAX_SCAN_ROUND = 1 << 30
RACE_ID = re.compile(r'[0-9]{8}-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')
STATUS = frozenset(('missing', 'pending', 'unsupported'))


def _need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _day(value):
    _need(type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value), 'RESULT_DUE_DAY_INVALID')
    try:
        _need(date.fromisoformat(value).isoformat() == value, 'RESULT_DUE_DAY_INVALID')
    except ValueError:
        raise ValueError('RESULT_DUE_DAY_INVALID') from None
    return value


def _rid_day(value):
    _need(type(value) is str and RACE_ID.fullmatch(value), 'RESULT_DUE_RACE_ID_INVALID')
    return _day(value[:4]+'-'+value[4:6]+'-'+value[6:8])


def _clock(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('RESULT_DUE_CLOCK_INVALID') from None
    _need(parsed.utcoffset() is not None, 'RESULT_DUE_CLOCK_INVALID')
    return parsed


def ledger(control, *, now):
    """Create and validate metadata within the authenticated private control."""
    _need(type(control) is dict, 'RESULT_DUE_CONTROL_INVALID')
    clock = _clock(now)
    doc = control.setdefault('result_due_ledger', dict(schema=SCHEMA, pending={}, scanned_days=[], scan_round=0))
    _need(type(doc) is dict and set(doc) == {'schema', 'pending', 'scanned_days', 'scan_round'}
          and doc['schema'] == SCHEMA, 'RESULT_DUE_SCHEMA_INVALID')
    pending, days, counter = doc['pending'], doc['scanned_days'], doc['scan_round']
    _need(type(pending) is dict and len(pending) <= MAX_PENDING, 'RESULT_DUE_PENDING_BOUND')
    _need(type(days) is list and len(days) <= MAX_SCANNED_DAYS and len(set(days)) == len(days),
          'RESULT_DUE_SCAN_BOUND')
    _need(all(_day(day) for day in days), 'RESULT_DUE_DAY_INVALID')
    _need(type(counter) is int and 0 <= counter < MAX_SCAN_ROUND, 'RESULT_DUE_SCAN_ROUND_INVALID')
    for rid, item in pending.items():
        day = _rid_day(rid)
        _need(day <= clock.astimezone(JST).date().isoformat(), 'RESULT_DUE_FUTURE_RACE_INVALID')
        _need(type(item) is dict and set(item) == {'first_seen_at', 'last_status'}
              and item['last_status'] in STATUS, 'RESULT_DUE_ENTRY_INVALID')
        _need(_clock(item['first_seen_at']) <= clock, 'RESULT_DUE_ENTRY_CLOCK_INVALID')
    return doc


def choose_older_day(doc, *, all_days, recent_days):
    """Rotate old unresolved days and backfill older historical days fairly.

    Selecting an old saved day does not authorize an official source request.
    """
    days = sorted({_day(day) for day in all_days}, reverse=True)
    recent = {_day(day) for day in recent_days}
    _need(recent <= set(days), 'RESULT_DUE_RECENT_DAY_MISSING')
    older = [day for day in days if day not in recent]
    pending_days = {_rid_day(rid) for rid in doc['pending']}
    # An unavailable original is a count-only HOLD, not a reason to skip
    # unrelated current results or to invent a successful reconciliation.
    due = [day for day in older if day in pending_days]
    unchecked = [day for day in reversed(older) if day not in doc['scanned_days']]
    n = doc['scan_round']
    if due and (n % 2 == 0 or not unchecked):
        selected = due[(n // 2) % len(due)]
    elif unchecked:
        selected = unchecked[0]
    elif due:
        selected = due[(n // 2) % len(due)]
    else:
        selected = None
    if selected is not None:
        doc['scan_round'] = (n + 1) % MAX_SCAN_ROUND
    return selected


def record_scanned(doc, day):
    """Only call after authenticated historical day read has succeeded."""
    day = _day(day)
    if day not in doc['scanned_days']:
        _need(len(doc['scanned_days']) < MAX_SCANNED_DAYS, 'RESULT_DUE_SCAN_BOUND')
        doc['scanned_days'].append(day)


def reconciled_status(row):
    """Treat display-only reference settlements as unresolved for formal work."""
    result = row.get('result') or {}
    status = result.get('status') or 'missing'
    reference = result.get('cutoff_reconciliation') or {}
    if status in ('final', 'void') and (result.get('formal_eligible') is False
            or type(reference) is dict and reference.get('formal_eligible') is False):
        return 'unsupported'
    return status


def update(doc, rows, *, now):
    """Keep all unsettled IDs, prune only final/void in a verified saved view."""
    now = _clock(now).isoformat()
    seen = set()
    for row in rows:
        rid = row['race_id']
        _rid_day(rid)
        _need(rid not in seen, 'RESULT_DUE_DUPLICATE_RACE')
        seen.add(rid)
        state = reconciled_status(row)
        if state in ('final', 'void'):
            doc['pending'].pop(rid, None)
            continue
        _need(state in STATUS, 'RESULT_DUE_UNKNOWN_RESULT_STATE')
        entry = doc['pending'].setdefault(rid, dict(first_seen_at=now, last_status=state))
        entry['last_status'] = state
        _need(len(doc['pending']) <= MAX_PENDING, 'RESULT_DUE_PENDING_BOUND')
    return dict(pending=len(doc['pending']), pending_days=len({_rid_day(rid) for rid in doc['pending']}),
                scanned_old_days=len(doc['scanned_days']))


def unavailable_days(doc, all_days):
    """Missing authenticated saved days remain in the private ledger."""
    available = {_day(day) for day in all_days}
    return len({_rid_day(rid) for rid in doc['pending']} - available)
