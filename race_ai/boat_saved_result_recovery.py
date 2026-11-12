"""Recover saved result journals from explicitly named existing Actions runs.

Exact archive-first run/list responses precede bounded metadata access. This
reader creates no forecasts, raw-page proofs, result revisions or receipts.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import re

from . import cycle_recovery as C, saved_view_feed as F
from .boat_history_store import wire
from .boat_owner_source_identity import authenticated_live_owner_run
from .boat_pdca_recipient import _json
from .boat_pdca_state import state_key
from .saved_result_sync import _merge

SCHEMA = 'RACE_AI_BOAT_SAVED_RESULT_RECOVERY_COUNTS_V1'
REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
WORKFLOW = 405276784
BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
MAX_RUNS = 16
MAX_PAGES = 128
MAX_ZIP_BYTES = 32*1024*1024
MAX_TOTAL_ZIP_BYTES = 64*1024*1024
MAX_METADATA_BYTES = 64*1024*1024
MAX_VIEW_BYTES = 64*1024*1024
_HEAD = re.compile(r'[a-f0-9]{40}\Z')


def _need(ok, reason):
    if not ok: raise ValueError('SAVED_RESULT_RECOVERY_'+reason)


def _now():
    return datetime.now(timezone.utc)


def _time(value):
    try:
        _need(type(value) is str and 0 < len(value) <= 64, 'CLOCK_INVALID')
        clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _need(clock.utcoffset() is not None, 'CLOCK_INVALID')
        return clock
    except (TypeError, ValueError, OverflowError):
        raise ValueError('SAVED_RESULT_RECOVERY_CLOCK_INVALID') from None


def _ident(value):
    _need(type(value) is int and 0 < value < 10**20, 'RUN_OR_ARTIFACT_ID_INVALID')
    return value


def _day(value):
    try:
        _need(type(value) is str and date.fromisoformat(value).isoformat() == value, 'DAY_INVALID')
    except (ValueError, TypeError):
        raise ValueError('SAVED_RESULT_RECOVERY_DAY_INVALID') from None
    return value


class _MetadataReader:
    """A function boundary intentionally exposing no availability-list hook."""
    def __init__(self, get):
        self.get = get; self.used = 0

    def read(self, path, limit):
        _need(self.used+limit <= MAX_METADATA_BYTES, 'METADATA_BOUND_INVALID')
        raw = self.get(path)
        _need(type(raw) is bytes and 0 < len(raw) <= limit, 'RESPONSE_BOUND_INVALID')
        self.used += len(raw)
        return raw

    def __call__(self, path):
        match = re.fullmatch(r'actions/runs/([1-9][0-9]{0,19})/artifacts\?per_page=100(?:&page=([1-9][0-9]{0,2}))?', path)
        _need(match is not None and int(match[2] or '1') <= MAX_PAGES, 'PAGINATION_BOUND_INVALID')
        raw = self.read(path, 4*1024*1024); value = _json(raw, 4*1024*1024)
        _need(type(value) is dict and type(value.get('total_count')) is int
              and 0 <= value['total_count'] <= 100*MAX_PAGES, 'PAGINATION_BOUND_INVALID')
        return raw


def _run(raw, ident, clock):
    run = _json(raw, 1024*1024)
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == ident
          and type(run.get('workflow_id')) is int and authenticated_live_owner_run(run)
          and type(run.get('head_sha')) is str
          and _HEAD.fullmatch(run['head_sha']), 'WORKFLOW_IDENTITY_INVALID')
    _need(all(type(run.get(name)) is dict and type(run[name].get('id')) is int
              and run[name]['id'] == REPO_ID and run[name].get('full_name') == REPO
              for name in ('repository', 'head_repository')), 'WORKFLOW_REPOSITORY_INVALID')
    _need(_time(run.get('created_at')) <= _time(run.get('updated_at')) <= clock, 'WORKFLOW_CLOCK_INVALID')
    return run


def _listed(row, run, clock):
    _need(type(row) is dict, 'ARTIFACT_LISTING_INVALID')
    ident = _ident(row.get('id')); name = row.get('name')
    _need(type(name) is str and 0 < len(name) <= 256, 'ARTIFACT_NAME_INVALID')
    if not name.startswith('race-existing-cycle-'): return None
    prefix = f'race-existing-cycle-{run["id"]}'
    if name == prefix: round_no = 1
    else:
        match = re.fullmatch(re.escape(prefix)+r'-cycle-(0[2-9]|1[0-9]|2[0-4])', name)
        _need(match is not None, 'ARTIFACT_RUN_OR_ROUND_INVALID')
        round_no = int(match[1])
    _need(type(row.get('size_in_bytes')) is int and 0 < row['size_in_bytes'] <= MAX_ZIP_BYTES
          and type(row.get('digest')) is str and re.fullmatch(r'sha256:[a-f0-9]{64}', row['digest'])
          and type(row.get('expired')) is bool, 'LISTED_ARTIFACT_BOUND_OR_HASH_INVALID')
    _need(_time(run['created_at']) <= _time(row.get('created_at')) <= clock, 'ARTIFACT_CLOCK_INVALID')
    return ident, round_no


def _archive_capability(get):
    # Dynamic __getattr__ transports are not attestations of authenticated ZIPs.
    value = vars(get).get('is_archived') if hasattr(get, '__dict__') else None
    declared = getattr(type(get), 'is_archived', None)
    if value is None and callable(declared): value = lambda ident: declared(get, ident)
    return value if callable(value) else None


def _metadata(raw, listed, run, clock, get):
    meta = _json(raw, 128*1024)
    _need(type(meta) is dict and all(type(meta.get(name)) is type(listed.get(name))
          and meta.get(name) == listed.get(name) for name in
          ('id', 'name', 'digest', 'size_in_bytes', 'created_at')), 'ARTIFACT_LISTING_CONFLICT')
    workflow = meta.get('workflow_run')
    _need(type(workflow) is dict and type(workflow.get('id')) is int and workflow['id'] == run['id']
          and workflow.get('head_sha') == run['head_sha']
          and all(type(workflow.get(name)) is int and workflow[name] == REPO_ID
                  for name in ('repository_id', 'head_repository_id')), 'ARTIFACT_RUN_HEAD_INVALID')
    # Serving exact metadata may first hydrate/authenticate its ZIP. Only that
    # completed operation can confer an archive exception to the live clock.
    capability = _archive_capability(get)
    archived = capability is not None and capability(meta['id']) is True
    created, expires = _time(meta.get('created_at')), _time(meta.get('expires_at'))
    _need(meta.get('expired') is False and _time(run['created_at']) <= created <= clock
          and created < expires and (archived or clock < expires), 'ARTIFACT_EXPIRED_OR_CLOCK_INVALID')
    _need(listed['expired'] is meta['expired'] or archived, 'ARTIFACT_LISTING_EXPIRY_CONFLICT')
    return meta, archived


def recover_saved_results(view, get, *, run_ids, key=None, now=None):
    """Append authentic journals; replay without new observations is byte-idempotent.

    Integrity errors and incomplete latest archives hold without selecting an
    older archive. Verified empty journals and runs without an archive leave the
    exact view untouched, including newly recovered forecasts and known results.
    Result clocks are checked against actual archive/observation clocks, not the
    forecast cutoff: publishing results after cutoff is the expected operation.
    """
    _need(type(run_ids) in (list, tuple, set, frozenset) and len(run_ids) <= MAX_RUNS, 'RUN_SCOPE_INVALID')
    runs = sorted({_ident(ident) for ident in run_ids})
    _need(callable(get), 'TRANSPORT_REQUIRED')
    if key is not None: key = state_key('production', key)

    def clock():
        value = _now() if now is None else now
        _need(type(value) is datetime and value.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        return value

    clock(); before = F.forecast_inventory(view); pin = F.originals_sha(view)
    _need(len(wire(view).encode()) <= MAX_VIEW_BYTES, 'EXISTING_VIEW_BOUND_INVALID')
    days = {_day(row['event_date_jst']) for row in view['records']}
    race_ids = {row['race_id'] for row in view['records']}
    counts = dict(schema=SCHEMA, status='UNCHANGED', runs_requested=len(runs), runs_scanned=0,
        listed_artifacts=0, matched_result_archives=0, archives_verified=0, archived_artifacts=0,
        verified_observations=0, empty_verified_journals=0,
        out_of_scope_observations=0, duplicate_observations=0,
        appended_observations=0, deferred_observations=0, updated_races=0, final_races=0, pending_races=0,
        void_races=0, unsupported_races=0, source_requests=0)
    reader = _MetadataReader(get); selected = []; seen = set()
    # Complete every exact listing before metadata reads: a vault reader may
    # hydrate an entire ZIP when metadata is requested, so reserve globally.
    for ident in runs:
        raw = reader.read(f'actions/runs/{ident}', 1024*1024)
        run = _run(raw, ident, clock()); rows = C.artifact_pages(reader, ident)
        counts['runs_scanned'] += 1; counts['listed_artifacts'] += len(rows)
        rounds = {}
        for row in rows:
            match = _listed(row, run, clock())
            if match is None: continue
            artifact, round_no = match
            _need(artifact not in seen, 'DUPLICATE_ARTIFACT_ACROSS_RUNS'); seen.add(artifact)
            _need(round_no not in rounds, 'DUPLICATE_RESULT_ROUND')
            rounds[round_no] = row; counts['matched_result_archives'] += 1
        if rounds: selected.append((run, rounds[max(rounds)]))
    _need(sum(row['size_in_bytes'] for _, row in selected) <= MAX_TOTAL_ZIP_BYTES, 'TOTAL_ZIP_BOUND_INVALID')
    _need(reader.used+128*1024*len(selected) <= MAX_METADATA_BYTES, 'METADATA_BOUND_INVALID')
    incoming = []
    for run, listed in selected:
        artifact = listed['id']
        meta_raw = reader.read(f'actions/artifacts/{artifact}', 128*1024)
        meta, archived = _metadata(meta_raw, listed, run, clock(), get)
        raw = get(f'actions/artifacts/{artifact}/zip')
        _need(type(raw) is bytes and len(raw) == meta['size_in_bytes'] and 0 < len(raw) <= MAX_ZIP_BYTES
              and meta['digest'] == 'sha256:'+sha256(raw).hexdigest(), 'ARTIFACT_ZIP_HASH_OR_BOUND_INVALID')
        try:
            day = C._result_day(raw, meta, key=key)
            items = C.result_archive(raw, meta, day, key=key)
        except (ValueError, KeyError, TypeError, UnicodeError, OverflowError):
            raise ValueError('SAVED_RESULT_RECOVERY_ARCHIVE_PAYLOAD_INVALID') from None
        observed_clock = clock(); saved = _time(meta['created_at'])
        _need(all(_time(item['captured_at']) <= observed_clock and
                  _time(item['captured_at']) < saved+timedelta(seconds=1) for item in items),
              'RESULT_CAPTURE_CLOCK_INVALID')
        counts['archives_verified'] += 1; counts['archived_artifacts'] += int(archived)
        counts['verified_observations'] += len(items)
        counts['empty_verified_journals'] += int(not items)
        # Validate full journals, including foreign days, before narrowing them.
        merged = _merge(items)
        counts['duplicate_observations'] += len(items)-len(merged)
        if day not in days:
            counts['out_of_scope_observations'] += len(merged); continue
        for item in merged:
            if item['race_id'] in race_ids: incoming.append(item)
            else: counts['out_of_scope_observations'] += 1
    merged = _merge(incoming)
    counts['duplicate_observations'] += len(incoming)-len(merged)
    existing = _merge([item for row in view['records'] for item in row.get('result_observations', [])])
    old = {(item['race_id'], _time(item['captured_at'])): item for item in existing}
    new = []
    for item in merged:
        previous = old.get((item['race_id'], _time(item['captured_at'])))
        if previous is None: new.append(item)
        else:
            _need(wire(previous) == wire(item), 'RESULT_CAPTURE_CONFLICT')
            counts['duplicate_observations'] += 1
    if not new: return view, counts
    output = F.update_view(view, new, synced_at=clock().isoformat())
    _need(F.forecast_inventory(output) == before and F.originals_sha(output) == pin,
          'FORECAST_ORIGINAL_CHANGED')
    from .boat_all_model_recovery import _check_history_row_bounds, _Deferred
    try:
        if len(wire(output).encode()) > MAX_VIEW_BYTES: raise _Deferred()
        _check_history_row_bounds(output)
    except _Deferred:
        # Keep the caller's already-recovered model originals publishable. A
        # result batch is atomic: never trim its journal or partially apply it.
        counts.update(status='DEFERRED', deferred_observations=len(new))
        return view, counts
    changed = {item['race_id'] for item in new}
    counts.update(status='UPDATED', appended_observations=len(new), updated_races=len(changed))
    for row in output['records']:
        if row['race_id'] not in changed: continue
        status = (row.get('result') or {}).get('status')
        name = {'final': 'final_races', 'pending': 'pending_races', 'void': 'void_races'}.get(status, 'unsupported_races')
        counts[name] += 1
    return output, counts
