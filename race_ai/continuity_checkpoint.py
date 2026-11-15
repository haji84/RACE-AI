"""Publish a fresh final handoff containing sealed JSON, never retained ZIPs.

This copies existing state without reserializing, repairing, or claiming it is
ready. Original forecast/result archives remain independently authenticated by
recovery; embedding them here would recursively grow every worker handoff.
"""
import argparse
import ctypes
from datetime import date, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_CONTROL_BYTES = 1024 * 1024
CONTROL_SCHEMAS = {
    'repeat-session.json': {'RACE_AI_BOUNDED_REPEAT_V1', 'RACE_AI_CONTINUOUS_REPEAT_V2'},
    'bootstrap-source-control.json': {'RACE_AI_BOOTSTRAP_SOURCE_CONTROL_V1'},
}
WAIT_STATES = {'RATE_LIMIT_WAIT', 'TRANSIENT_SOURCE_WAIT', 'AUTHORIZATION_WAIT',
               'WAITING_PUBLICATION', 'SOURCE_REVIEW_WAIT'}


def _need(condition, reason):
    if not condition:
        raise ValueError('checkpoint rejected: ' + reason)


def _safe_path(value):
    path = Path(os.path.abspath(value))
    for part in reversed((path, *path.parents)):
        try:
            mode = part.lstat().st_mode
        except FileNotFoundError:
            continue
        _need(not stat.S_ISLNK(mode), 'symlink path')
        if part != path:
            _need(stat.S_ISDIR(mode), 'non-directory parent')
    return path


def _read(path, limit):
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    _need(stat.S_ISREG(before.st_mode), 'state must be a regular file')
    _need(0 < before.st_size <= limit, 'state size')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        _need(stat.S_ISREG(opened.st_mode) and
              (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
              'state changed during open')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    _need(len(raw) == before.st_size and len(raw) <= limit and
          (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
          (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'state changed during read')
    return raw


def _sealed_json(raw, seal):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _need(key not in result, 'duplicate JSON key')
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError('checkpoint rejected: nonfinite JSON')

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    _need(type(value) is dict, 'state object required')
    claimed = value.get(seal)
    _need(type(claimed) is str and re.fullmatch('[0-9a-f]{64}', claimed), 'state seal format')
    wire = json.dumps({k: v for k, v in value.items() if k != seal},
                      sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    _need(hmac.compare_digest(claimed, hashlib.sha256(wire).hexdigest()), 'state seal mismatch')
    return value


def _day(value):
    _need(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'day format')
    date.fromisoformat(value)
    return value


def _count(value):
    return type(value) is int and value >= 0


def _reason(value):
    return value is None or type(value) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', value)


def _control(raw, member, expected_run):
    key = 'session_sha256' if member == 'repeat-session.json' else 'source_control_sha256'
    value = _sealed_json(raw, key)
    _need(type(value.get('schema')) is str and value['schema'] in CONTROL_SCHEMAS[member],
          'source schema')
    _need(type(value.get('run_id')) is int and value['run_id'] == expected_run, 'run identity')
    _day(value.get('day_jst'))
    for field in ('requests_used', 'completed_round'):
        _need(_count(value.get(field)), 'source count')
    prepared = value.get('prepared_round')
    _need(prepared is None or type(prepared) is int and prepared == value['completed_round'] + 1,
          'prepared round')
    for total, base, used in (
        ('lifetime_requests', 'lifetime_requests_base', 'requests_used'),
        ('lifetime_completed_rounds', 'lifetime_completed_rounds_base', 'completed_round'),
    ):
        count = value.get(total, value[used])
        _need(_count(count) and count >= value[used], 'lifetime count')
        if base in value:
            _need(_count(value[base]) and value[base] + value[used] == count, 'lifetime count')
    for field in ('halted_reason', 'previous_halted_reason', 'control_reason'):
        _need(_reason(value.get(field)), 'source reason')
    wait = value.get('source_wait')
    if wait is not None:
        _need(type(wait) is dict and set(wait) ==
              {'state', 'reason', 'retry_at', 'http_status', 'attempts'}, 'source wait shape')
        _need(type(wait['state']) is str and wait['state'] in WAIT_STATES and wait['reason'] is not None and
              _reason(wait['reason']), 'source wait state/reason')
        _need(type(wait['attempts']) is int and wait['attempts'] >= 1, 'source wait attempts')
        _need(wait['http_status'] is None or type(wait['http_status']) is int and
              100 <= wait['http_status'] <= 599, 'source wait HTTP status')
        if wait['retry_at'] is not None:
            _need(type(wait['retry_at']) is str, 'source wait timestamp')
            _need(datetime.fromisoformat(wait['retry_at'].replace('Z', '+00:00')).utcoffset()
                  is not None, 'source wait timestamp')
    return value


def _continuity(raw, control, expected_run):
    value = _sealed_json(raw, 'state_sha256')
    _need(value.get('schema') == 'RACE_AI_RECOVERED_FIRST_RECEIPTS_V1', 'continuity schema')
    _need(_day(value.get('day_jst')) == control['day_jst'], 'continuity day identity')
    if 'run_id' in value:
        _need(type(value['run_id']) is int and value['run_id'] == expected_run, 'continuity run identity')
    _need(type(value.get('complete')) is bool, 'continuity completeness')
    for field in ('rows', 'observations', 'receipts', 'excluded_repeats', 'index_entries'):
        _need(type(value.get(field)) is list and all(type(row) is dict for row in value[field]),
              'continuity collection')
    _need(type(value.get('scanned_runs')) is list and
          all(type(run) is int and run > 0 for run in value['scanned_runs']), 'scanned runs')
    for field in ('training_proofs', 'history_proofs'):
        _need(field not in value or type(value[field]) is dict, 'continuity proofs')
    for field in ('source_control', 'learning_context', 'history_context', 'entry_observation_history'):
        _need(value.get(field) is None or type(value[field]) is dict, 'continuity context')


def _publish(staging, output):
    # Linux Actions provides renameat2: unlike rename(), NOREPLACE also rejects
    # an empty destination directory created after our initial existence check.
    rename = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    _need(rename is not None, 'atomic no-replace publishing unavailable')
    result = rename(-100, os.fsencode(staging), -100, os.fsencode(output), 1)
    if result != 0:
        raise ValueError('checkpoint rejected: output cannot be published without replacement')


def build_checkpoint(source_dir, out_dir, *, expected_run):
    """Copy exact control/state bytes to a new private directory, or return None.

    A missing control is not a successful source session and produces no output.
    A present invalid repeat session is rejected, never replaced by bootstrap.
    The expanded limit matches recovery's existing ZIP-member contract; a raw
    JSON size is not the compressed artifact size. This function does no I/O to
    remote services and never changes source files or retained original ZIPs.
    """
    _need(type(expected_run) is int and expected_run > 0, 'expected run required')
    try:
        source = _safe_path(source_dir)
        output = _safe_path(out_dir)
        _need(output != source and source not in output.parents, 'output inside source')
        _need(not os.path.lexists(output), 'output already exists')
        if not source.exists():
            return None
        _need(source.is_dir(), 'source directory required')
        member = 'repeat-session.json'
        raw = _read(source / member, MAX_CONTROL_BYTES)
        if raw is None:
            member = 'bootstrap-source-control.json'
            raw = _read(source / member, MAX_CONTROL_BYTES)
        if raw is None:
            return None
        control = _control(raw, member, expected_run)
        selected = {member: raw}
        state = _read(source / 'continuity.json', MAX_EXPANDED_BYTES - len(raw))
        if state is not None:
            _continuity(state, control, expected_run)
            selected['continuity.json'] = state
        _need(output.parent.is_dir(), 'output parent required')
        staging = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
        try:
            for name, body in selected.items():
                fd = os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
            _publish(staging, output)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return output
    except (OSError, UnicodeError, RecursionError) as exc:
        raise ValueError('checkpoint rejected: unreadable or malformed state/path') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--expected-run', required=True, type=int)
    args = parser.parse_args(argv)
    try:
        checkpoint = build_checkpoint(args.source_dir, args.out_dir, expected_run=args.expected_run)
    except ValueError:
        parser.exit(1, 'checkpoint rejected: no output published\n')
    print(json.dumps({'checkpoint_created': checkpoint is not None}))


if __name__ == '__main__':
    main()
