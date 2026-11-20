"""One owner-authorized reconciliation of one ambiguous historical stop.

This is not a provider-stop release. The original marker stays byte-for-byte
unchanged and continues to block ordinary collectors. A trusted, explicitly
selected main dispatch may claim this one attempt before source I/O. No claim
is reusable, including after a crash, lost push acknowledgement or timeout.
This module has no provider transport, credentials, source values or scorer.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
import json
import math
import os
import re
import time
import uuid

from . import keirin_nationwide_cipher_history as archive
from . import keirin_github_provider_stop as stop
from .keirin_result_diagnostics import ROUTES


RACE = '202611208105'
DAY = '2026-11-21'
JST = timezone(timedelta(hours=9))
LEASE_SECONDS = 600
WORKFLOW_REF = 'haji84/RACE-AI/.github/workflows/keirin-nationwide-ab-auto.yml@refs/heads/main'
MARKER_PATH = stop.ROOT + '/2026-11-20.json'
MARKER_BLOB = '78983856f723be165b07aefc2aee951534ff1857'
MARKER = dict(schema=stop.SCHEMA, day_jst='2026-11-20', code=stop.DENIED,
              observed_at='2026-11-20T09:24:45.201674+00:00')
ROOT = 'state/keirin/ab/provider-reconciliation/v1/' + RACE
CLAIM_PATH = ROOT + '/' + DAY + '.claim.json'
FINISH_PATH = ROOT + '/' + DAY + '.finish.json'
CLAIM_SCHEMA = 'RACE_AI_KEIRIN_SINGLE_RESULT_RECONCILIATION_CLAIM_V1'
FINISH_SCHEMA = 'RACE_AI_KEIRIN_SINGLE_RESULT_RECONCILIATION_FINISH_V1'
PURPOSES = ('OFFICIAL_CALENDAR', 'CALENDAR_SCRIPT', 'FORM_SCRIPT',
    'OFFICIAL_RACE_LIST', 'RACE_LIST_VIEW_SCRIPT', 'RACE_LIST_CONTROLLER_SCRIPT',
    'OFFICIAL_FINAL_RESULT', 'OFFICIAL_PAYOUT_UNIT')
FINISH_STATES = frozenset(('FAILED', 'ORDER_ONLY_ARCHIVED', 'FOUR_ARMS_ARCHIVED'))
_ISSUER = object()


class ReconciliationError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ReconciliationError('HOLD_RECONCILIATION_' + code)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def _aware(now):
    need(isinstance(now, datetime) and now.utcoffset() is not None, 'CLOCK_INVALID')
    return now.astimezone(timezone.utc)


def _runtime(repo, now, source_commit, *, require_day=True):
    now = _aware(now)
    need(type(source_commit) is str and archive.COMMIT.fullmatch(source_commit), 'CODE_IDENTITY_INVALID')
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and
         os.environ.get('GITHUB_REPOSITORY') == archive.REPO and
         os.environ.get('GITHUB_REPOSITORY_ID') == archive.REPO_ID and
         os.environ.get('GITHUB_REF') == 'refs/heads/main' and
         os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and
         os.environ.get('GITHUB_WORKFLOW_REF') == WORKFLOW_REF and
         os.environ.get('CANARY_RECONCILE') == 'true' and
         os.environ.get('GITHUB_RUN_ATTEMPT') == '1' and
         archive.RUN.fullmatch(os.environ.get('GITHUB_RUN_ID', '')) and
         os.environ.get('GITHUB_SHA') == source_commit and
         os.environ.get('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true', 'TRUSTED_DISPATCH_REQUIRED')
    need(not require_day or now.astimezone(JST).date().isoformat() == DAY, 'RUNTIME_WINDOW_CLOSED')
    repo = archive._remote(repo, synthetic_local=False)
    need(archive._cmd(repo, 'rev-parse', 'HEAD')[1] == source_commit, 'CHECKOUT_SHA_CHANGED')
    return Path(repo).resolve()


def _entry(repo, head, path):
    _, item = archive._cmd(repo, '--no-replace-objects', 'ls-tree', '-z',
                          '--full-tree', head, '--', path)
    if not item:
        return None
    found = re.fullmatch(r'(100644 blob|040000 tree) ([a-f0-9]{40})\t'+re.escape(path)+r'\x00', item)
    need(found is not None, 'UNTRUSTED_STATE_ENTRY')
    return found[1], found[2]


def _fixed_marker(repo, head, *, sole):
    need(_entry(repo, head, MARKER_PATH) == ('100644 blob', MARKER_BLOB), 'LEGACY_MARKER_CHANGED')
    need(archive.read_blob_bytes(repo, head, MARKER_PATH, max_bytes=8192) == _canonical(MARKER),
         'LEGACY_MARKER_CHANGED')
    if sole:
        need((_entry(repo, head, stop.ROOT) or ('',))[0] == '040000 tree', 'STOP_TREE_INVALID')
        _, size = archive._cmd(repo, '--no-replace-objects', 'cat-file', '-s', head+':'+stop.ROOT)
        need(size.isascii() and size.isdecimal() and len(size) <= 5 and int(size) <= 4096,
             'STOP_TREE_INVALID')
        _, listing = archive._cmd(repo, '--no-replace-objects', 'ls-tree', '-z', head+':'+stop.ROOT)
        need(listing == '100644 blob '+MARKER_BLOB+'\t2026-11-20.json\0', 'ADDITIONAL_STOP_PRESENT')


def _unclaimed(repo, head):
    parts = ROOT.split('/')
    for end in range(1, len(parts)):
        entry = _entry(repo, head, '/'.join(parts[:end]))
        need(entry is None or entry[0] == '040000 tree', 'UNTRUSTED_STATE_ANCESTOR')
    # Any prior namespace, even malformed/orphaned, consumes this one attempt.
    need(_entry(repo, head, ROOT) is None, 'ATTEMPT_ALREADY_CONSUMED')


def _append(repo, parent, path, raw, message):
    """One normal fast-forward push; never retry an ambiguous acknowledgement."""
    need(_entry(repo, parent, path) is None, 'RECEIPT_ALREADY_EXISTS')
    with TemporaryDirectory(prefix='keirin-reconciliation-') as folder:
        tree = Path(folder)/'branch'
        archive._cmd(repo, 'worktree', 'add', '--detach', str(tree), parent)
        try:
            target = tree/path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            archive._cmd(tree, 'add', '--', path)
            archive._cmd(tree, '-c', 'user.name=RACE-AI',
                '-c', 'user.email=race-ai@users.noreply.github.com', 'commit', '-m', message)
            commit = archive._cmd(tree, 'rev-parse', 'HEAD')[1]
            need(archive.COMMIT.fullmatch(commit), 'COMMIT_IDENTITY_INVALID')
            code, _ = archive._cmd(tree, 'push', 'origin', 'HEAD:refs/heads/'+archive.BRANCH, okay=True)
            need(code == 0, 'PUSH_NOT_ACKNOWLEDGED')
        finally:
            archive._cmd(repo, 'worktree', 'remove', '--force', str(tree), okay=True)
    return commit


def _readback(repo, head, commit, path, raw):
    code, _ = archive._cmd(repo, '--no-replace-objects', 'merge-base', '--is-ancestor',
                           commit, head, okay=True)
    need(code == 0 and (_entry(repo, head, path) or ('',))[0] == '100644 blob' and
         archive.read_blob_bytes(repo, head, path, max_bytes=8192) == raw, 'REMOTE_READBACK_FAILED')


def begin(*, repo, now, source_commit, race_id=RACE):
    """Consume the exact fixed attempt durably before granting source access."""
    try:
        started_tick = time.monotonic()
        need(math.isfinite(started_tick), 'MONOTONIC_CLOCK_INVALID')
        need(race_id == RACE, 'RACE_SCOPE_INVALID')
        repo = _runtime(repo, now, source_commit)
        now = _aware(now)
        midnight = datetime(2026, 11, 22, tzinfo=JST).astimezone(timezone.utc)
        expires = min(now+timedelta(seconds=LEASE_SECONDS), midnight)
        deadline_tick = started_tick + (expires-now).total_seconds()
        head = archive._refresh(repo)
        _fixed_marker(repo, head, sole=True)
        _unclaimed(repo, head)
        claim = dict(schema=CLAIM_SCHEMA, race_id=RACE, day_jst=DAY,
            attempt_id=uuid.uuid4().hex, run_id=os.environ['GITHUB_RUN_ID'],
            source_commit=source_commit, prior_state_commit=head, legacy_stop_blob=MARKER_BLOB,
            started_at=now.isoformat(), expires_at=expires.isoformat(),
            permitted_purposes=list(PURPOSES), max_source_requests=len(PURPOSES),
            legacy_incident_resolved=False, general_source_release=False)
        raw = _canonical(claim)
        commit = _append(repo, head, CLAIM_PATH, raw,
                         'safety(keirin): claim one reviewed result reconciliation')
        observed = archive._refresh(repo)
        _readback(repo, observed, commit, CLAIM_PATH, raw)
        _fixed_marker(repo, observed, sole=True)
        need(_entry(repo, observed, FINISH_PATH) is None, 'ATTEMPT_ALREADY_FINISHED')
        tick = time.monotonic()
        need(math.isfinite(tick) and started_tick <= tick < deadline_tick,
             'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        return ReconciliationLease(_issuer=_ISSUER, repo=repo, claim=claim,
            claim_raw=raw, claim_commit=commit, monotonic_started=started_tick,
            deadline_tick=deadline_tick)
    except ReconciliationError:
        raise
    except Exception:
        raise ReconciliationError('HOLD_RECONCILIATION_CLAIM_NOT_VERIFIED') from None


class ReconciliationLease:
    """Process-local permission for one exact ordered request sequence.

    The collector remains responsible for published form-token binding,
    redirect refusal, response validation and immediately persisting actual
    denials. A lease cannot be restored from its public receipt.
    """
    def __init__(self, *, _issuer, repo, claim, claim_raw, claim_commit,
                 monotonic_started, deadline_tick):
        need(_issuer is _ISSUER, 'ISSUER_INVALID')
        self._repo = repo; self._claim = claim; self._raw = claim_raw
        self.claim_commit = claim_commit
        self._started = datetime.fromisoformat(claim['started_at'])
        self._expires = datetime.fromisoformat(claim['expires_at'])
        self._last = self._started
        self._last_tick = monotonic_started
        self._deadline_tick = deadline_tick
        self._used = []; self._closed = False; self._finish_attempted = False
        self._lock = RLock()

    @property
    def request_count(self):
        return len(self._used)

    def _active(self, *, now, repo, race_id=RACE):
        need(not self._closed, 'LEASE_CLOSED')
        tick = time.monotonic()
        need(math.isfinite(tick) and self._last_tick <= tick < self._deadline_tick,
             'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        now = _aware(now)
        need(race_id == RACE and Path(repo).resolve() == self._repo, 'LEASE_SCOPE_CHANGED')
        need(self._last <= now < self._expires, 'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        _runtime(self._repo, now, self._claim['source_commit'])
        need(os.environ['GITHUB_RUN_ID'] == self._claim['run_id'], 'RUN_ID_CHANGED')
        head = archive._refresh(self._repo)
        _fixed_marker(self._repo, head, sole=True)
        _readback(self._repo, head, self.claim_commit, CLAIM_PATH, self._raw)
        need(_entry(self._repo, head, FINISH_PATH) is None, 'ATTEMPT_ALREADY_FINISHED')
        # A slow remote check cannot use the earlier caller timestamp to grant
        # a source request after expiry. Wall-clock and elapsed bounds both hold.
        after = time.monotonic()
        need(math.isfinite(after) and tick <= after < self._deadline_tick,
             'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        self._last = now
        self._last_tick = after

    def assert_active(self, *, now, repo, race_id=RACE):
        with self._lock:
            try:
                self._active(now=now, repo=repo, race_id=race_id)
            except Exception as exc:
                self._closed = True
                if isinstance(exc, ReconciliationError): raise
                raise ReconciliationError('HOLD_RECONCILIATION_LEASE_NOT_VERIFIED') from None

    def before_request(self, *, purpose, method, url, now):
        with self._lock:
            try:
                need(type(purpose) is str and self.request_count < len(PURPOSES) and
                     purpose == PURPOSES[self.request_count], 'REQUEST_SEQUENCE_INVALID')
                host, path, expected_method = ROUTES[purpose]
                need(method == expected_method and type(url) is str and
                     url == 'https://'+host+path, 'REQUEST_ROUTE_INVALID')
                self.assert_active(now=now, repo=self._repo)
                # Consume before the caller invokes its transport. No response
                # or exception can restore this permission for another try.
                self._used.append(purpose)
            except Exception as exc:
                self._closed = True
                if isinstance(exc, ReconciliationError): raise
                raise ReconciliationError('HOLD_RECONCILIATION_REQUEST_NOT_VERIFIED') from None

    def finish(self, *, state, now):
        with self._lock:
            # Close first, including when outcome persistence fails. This does
            # not depend on receiving another caller callback after an error.
            self._closed = True
            need(not self._finish_attempted, 'FINISH_ALREADY_ATTEMPTED')
            self._finish_attempted = True
            try:
                need(state in FINISH_STATES, 'FINISH_STATE_INVALID')
                at = _aware(now)
                need(at >= self._last, 'FINISH_CLOCK_CHANGED')
                _runtime(self._repo, at, self._claim['source_commit'], require_day=False)
                need(os.environ['GITHUB_RUN_ID'] == self._claim['run_id'], 'RUN_ID_CHANGED')
                if state != 'FAILED': need(self.request_count >= 7, 'RESULT_STEPS_INCOMPLETE')
                if state == 'FOUR_ARMS_ARCHIVED': need(self.request_count == 8, 'UNIT_STEP_INCOMPLETE')
                head = archive._refresh(self._repo)
                # A newly recorded refusal does not prevent saving the failed
                # attempt or an already verified order-only archive receipt.
                _fixed_marker(self._repo, head, sole=False)
                _readback(self._repo, head, self.claim_commit, CLAIM_PATH, self._raw)
                need(_entry(self._repo, head, FINISH_PATH) is None, 'RECEIPT_ALREADY_EXISTS')
                result = dict(schema=FINISH_SCHEMA, race_id=RACE,
                    attempt_id=self._claim['attempt_id'], run_id=self._claim['run_id'],
                    source_commit=self._claim['source_commit'], claim_commit=self.claim_commit,
                    legacy_stop_blob=MARKER_BLOB, state=state, finished_at=at.isoformat(),
                    requests_consumed=self.request_count, purposes_consumed=list(self._used),
                    legacy_incident_resolved=False, general_source_release=False)
                raw = _canonical(result)
                commit = _append(self._repo, head, FINISH_PATH, raw,
                                 'safety(keirin): record reviewed result reconciliation outcome')
                observed = archive._refresh(self._repo)
                _readback(self._repo, observed, commit, FINISH_PATH, raw)
                _fixed_marker(self._repo, observed, sole=False)
                return result
            except ReconciliationError:
                raise
            except Exception:
                raise ReconciliationError('HOLD_RECONCILIATION_FINISH_NOT_VERIFIED') from None
