"""Proof-only matching of older ACTIVE rejection originals.

The internal receipt factory binds bytes and decoded data; it does not
authenticate them. Only the existing authenticated reader may mint production
receipts. This module does not repair a view or publish evidence.
"""
from copy import deepcopy
import hashlib
import json
import re


SCHEMA = 'RACE_AI_SAVED_REJECTION_ANCHOR_PROOF_V1'
MAX_SNAPSHOTS = 32
MAX_CIPHERTEXT_BYTES = 256 * 1024 * 1024
_MAX_VIEW_BYTES = 64 * 1024 * 1024
_ACTIVE = 'result_observation_rejections'
_HISTORY = 'saved_result_rejection_reason_variants'
_BINDING_REASON = 'SAVED_MODEL_VIEW_RESULT_REASON_VARIANT_BINDING'
_HOLD_REASONS = frozenset((
    'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED', 'CURRENT_HISTORY_INVALID',
    'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING',
))


class VerifiedSnapshot:
    __slots__ = (
        '_view', '_header', '_ciphertext', '_snapshot_sha', '_cipher_sha256',
        '_view_sha256', '_header_sha256', '_binding_sha256',
    )

    def __init__(self):
        raise TypeError('INTERNAL_RECEIPT_FACTORY_REQUIRED')

    def __repr__(self):
        return 'VerifiedSnapshot()'


class AnchorProofDecision:
    __slots__ = ('_summary', '_plan')

    def __init__(self):
        raise TypeError('INTERNAL_DECISION_FACTORY_REQUIRED')

    def public_summary(self):
        return deepcopy(self._summary)

    def __repr__(self):
        return 'AnchorProofDecision(status=' + self._summary['status'] + ')'


class _ProofRejected(ValueError):
    def __init__(self, reason):
        self.reason = reason if reason in _HOLD_REASONS else 'INPUT_OR_CHAIN_INVALID'
        super().__init__(self.reason)


def _proof_require(condition, reason='INPUT_OR_CHAIN_INVALID'):
    if not condition:
        raise _ProofRejected(reason)


def _proof_plain_tree(value, depth=0):
    _proof_require(depth <= 64)
    if type(value) is dict:
        _proof_require(all(type(key) is str for key in value))
        for child in value.values():
            _proof_plain_tree(child, depth + 1)
    elif type(value) is list:
        for child in value:
            _proof_plain_tree(child, depth + 1)
    else:
        _proof_require(type(value) in (str, int, float, bool, type(None)))


def _proof_wire(value):
    _proof_plain_tree(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(',', ':')).encode('utf-8')


def _proof_digest(value):
    return hashlib.sha256(_proof_wire(value)).hexdigest()


def _proof_sha(value, length=64):
    return type(value) is str and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def _proof_header(header):
    _proof_require(type(header) is dict)
    fields = {'schema', 'source_content_sha256', 'view_id', 'forecast_sha256',
              'generation', 'previous_cipher_sha256'}
    schema = header.get('schema')
    if schema == 'RACE_AI_SAVED_WEB_VIEW_V4':
        fields.add('forecast_inventory_sha256')
    elif schema == 'RACE_AI_SAVED_WEB_HISTORY_V5':
        fields.add('history_index_sha256')
    else:
        _proof_require(schema == 'RACE_AI_SAVED_WEB_VIEW_V3')
    _proof_require(set(header) == fields and type(header.get('generation')) is int
        and 1 <= header['generation'] <= 999999)
    for name in fields - {'schema', 'generation'}:
        _proof_require(_proof_sha(header[name]))


def _proof_view_shape(view):
    _proof_require(type(view) is dict and view.get('schema') == 'RACE_AI_PRIVATE_CYCLE_VIEW_V1'
        and type(view.get('records')) is list and len(view['records']) <= 10000)
    _proof_require(len(_proof_wire(view)) <= _MAX_VIEW_BYTES)


def _proof_receipt_binding(snapshot_sha, cipher_sha, view_sha, header_sha, size):
    return _proof_digest(dict(snapshot_sha=snapshot_sha, cipher_sha256=cipher_sha,
        view_sha256=view_sha, header_sha256=header_sha, ciphertext_bytes=size))


def _verified_snapshot(view, *, header, manifest_cipher_sha256, snapshot_sha, ciphertext):
    """Bind trusted-reader outputs; this factory makes no AEAD-authentication claim."""
    try:
        _proof_require(_proof_sha(snapshot_sha, 40) and _proof_sha(manifest_cipher_sha256))
        _proof_require(type(ciphertext) is bytes and 0 < len(ciphertext) <= MAX_CIPHERTEXT_BYTES)
        _proof_header(header)
        _proof_view_shape(view)
        _proof_require(hashlib.sha256(ciphertext).hexdigest() == manifest_cipher_sha256)
        receipt = object.__new__(VerifiedSnapshot)
        receipt._view = deepcopy(view)
        receipt._header = deepcopy(header)
        receipt._ciphertext = ciphertext
        receipt._snapshot_sha = snapshot_sha
        receipt._cipher_sha256 = manifest_cipher_sha256
        receipt._view_sha256 = _proof_digest(receipt._view)
        receipt._header_sha256 = _proof_digest(receipt._header)
        receipt._binding_sha256 = _proof_receipt_binding(
            snapshot_sha, manifest_cipher_sha256, receipt._view_sha256,
            receipt._header_sha256, len(ciphertext))
        return receipt
    except Exception:
        raise ValueError('INPUT_OR_CHAIN_INVALID') from None


def _proof_verify_receipt(receipt):
    _proof_require(type(receipt) is VerifiedSnapshot)
    _proof_require(_proof_sha(receipt._snapshot_sha, 40) and _proof_sha(receipt._cipher_sha256)
        and type(receipt._ciphertext) is bytes and bool(receipt._ciphertext))
    _proof_header(receipt._header)
    _proof_view_shape(receipt._view)
    _proof_require(hashlib.sha256(receipt._ciphertext).hexdigest() == receipt._cipher_sha256
        and _proof_digest(receipt._view) == receipt._view_sha256
        and _proof_digest(receipt._header) == receipt._header_sha256
        and _proof_receipt_binding(receipt._snapshot_sha, receipt._cipher_sha256,
            receipt._view_sha256, receipt._header_sha256, len(receipt._ciphertext)) == receipt._binding_sha256)


def _proof_decision(status, counts, snapshots, plan, *, reason=None):
    summary = dict(schema=SCHEMA, status=status, counts=counts, snapshots=snapshots,
        originals_changed=False, observations_reconciled=0, source_requests=0,
        publication_performed=False, forecast_generated=False, broader_goals_proven=False)
    if reason is not None:
        summary['reason'] = reason
    decision = object.__new__(AnchorProofDecision)
    decision._summary = deepcopy(summary)
    decision._plan = deepcopy(plan)
    return decision


def _proof_hold(reason):
    safe = reason if type(reason) is str and reason in _HOLD_REASONS else 'INPUT_OR_CHAIN_INVALID'
    return _proof_decision('HOLD', None, [], None, reason=safe)


def _proof_rows(view, reason):
    rows = {}
    for row in view['records']:
        _proof_require(type(row) is dict and type(row.get('race_id')) is str
            and 0 < len(row['race_id']) <= 250 and row['race_id'] not in rows, reason)
        rows[row['race_id']] = row
    return rows


def _proof_capture(item, guard, reason):
    try:
        _proof_require(type(item) is dict, reason)
        captured = guard._clock(item.get('captured_at'))
        guard._sha(item.get('source_sha256'))
        _proof_require(guard._reason_metadata(item, rejection=True), reason)
        return captured, item['source_sha256']
    except _ProofRejected:
        raise
    except Exception:
        raise _ProofRejected(reason) from None


def _proof_current_groups(view, guard):
    reason = 'CURRENT_HISTORY_INVALID'
    rows = _proof_rows(view, reason)
    targets = {}
    active_count = history_count = 0
    for race_id, row in rows.items():
        values = row.get(_ACTIVE, [])
        history = row.get(_HISTORY, [])
        _proof_require(type(values) is list and len(values) <= 10000
            and type(history) is list and len(history) <= 10000, reason)
        active_count += len(values)
        history_count += len(history)
        active = {}
        for item in values:
            key = _proof_capture(item, guard, reason)
            wire = guard._wire(item)
            _proof_require(key not in active or guard._wire(active[key]) == wire, reason)
            active.setdefault(key, item)
        groups = {}
        for item in history:
            key = _proof_capture(item, guard, reason)
            groups.setdefault(key, []).append(item)
        for key, originals in groups.items():
            wires = [guard._wire(item) for item in originals]
            _proof_require(2 <= len(wires) == len(set(wires))
                and all(guard._same_except_reason(originals[0], item, rejection=True)
                        for item in originals), reason)
            if key in active:
                _proof_require(guard._wire(active[key]) in wires, reason)
            else:
                targets[(race_id, *key)] = frozenset(wires)
        try:
            guard._observations([row], _ACTIVE, rejection=True)
        except guard.SavedModelViewError as error:
            _proof_require(getattr(error, 'reason_code', None) == _BINDING_REASON, reason)
        except Exception:
            raise _ProofRejected(reason) from None
    return rows, targets, active_count, history_count


def match_rejection_anchor_proofs(current, older_chain, *, guard):
    """Return an all-groups proof decision without changing or restoring a view."""
    try:
        _proof_require(type(current) is VerifiedSnapshot and type(older_chain) is tuple)
        receipts = (current, *older_chain)
        _proof_require(len(receipts) <= MAX_SNAPSHOTS, 'BOUND_EXCEEDED')
        _proof_require(all(type(receipt) is VerifiedSnapshot
            and type(receipt._ciphertext) is bytes for receipt in receipts))
        _proof_require(sum(len(receipt._ciphertext) for receipt in receipts) <= MAX_CIPHERTEXT_BYTES,
                       'BOUND_EXCEEDED')
        for receipt in receipts:
            _proof_verify_receipt(receipt)
        _proof_require(len({receipt._snapshot_sha for receipt in receipts}) == len(receipts))
        for newer, older in zip(receipts, receipts[1:]):
            _proof_require(newer._header['previous_cipher_sha256'] == older._cipher_sha256
                and newer._header['generation'] == older._header['generation'] + 1
                and newer._header['view_id'] == older._header['view_id']
                and newer._header['forecast_sha256'] == older._header['forecast_sha256']
                and newer._header['source_content_sha256'] == older._header['source_content_sha256'])
        rows, targets, active_count, history_count = _proof_current_groups(current._view, guard)
        counts = dict(snapshots_checked=len(receipts), current_active_rejections=active_count,
            retained_history_originals=history_count, orphan_groups=len(targets),
            proved_groups=0, older_active_bodies_checked=0, planned_active_originals=0)
        snapshots = [dict(snapshot_sha=receipt._snapshot_sha, cipher_sha256=receipt._cipher_sha256)
                     for receipt in receipts]
        if not targets:
            return _proof_decision('NO_ORPHAN_ANCHORS', counts, snapshots, ())
        proved = {}
        for receipt in older_chain:
            older_rows = _proof_rows(receipt._view, 'INPUT_OR_CHAIN_INVALID')
            for race_id, row in older_rows.items():
                values = row.get(_ACTIVE, [])
                _proof_require(type(values) is list and len(values) <= 10000)
                for item in values:
                    key = (race_id, *_proof_capture(item, guard, 'INPUT_OR_CHAIN_INVALID'))
                    counts['older_active_bodies_checked'] += 1
                    if key not in targets:
                        continue
                    for name in ('sport', 'event_date_jst', 'race_no'):
                        _proof_require(name not in rows[race_id] or name not in row
                            or rows[race_id][name] == row[name], 'ACTIVE_PROOF_CONFLICT')
                    wire = guard._wire(item)
                    _proof_require(wire in targets[key], 'ACTIVE_PROOF_CONFLICT')
                    _proof_require(key not in proved or proved[key][0] == wire,
                                   'ACTIVE_PROOF_CONFLICT')
                    if key not in proved:
                        proved[key] = (wire, deepcopy(item))
        _proof_require(all(key in proved for key in targets), 'ACTIVE_PROOF_MISSING')
        plan = tuple((key[0], proved[key][1]) for key in targets)
        counts['proved_groups'] = len(proved)
        counts['planned_active_originals'] = len(plan)
        return _proof_decision('ALL_ORPHAN_ANCHORS_PROVEN', counts, snapshots, plan)
    except _ProofRejected as error:
        return _proof_hold(error.reason)
    except Exception:
        return _proof_hold('INPUT_OR_CHAIN_INVALID')


# Actions-only selected-snapshot transport. The pure receipts above bind bytes;
# only the unchanged pinned F/H reader authenticates private ciphertext.
import base64 as _io_base64
from contextlib import redirect_stdout as _io_stdout, redirect_stderr as _io_stderr
import hashlib as _io_hashlib
import importlib.util as _io_importlib
import io as _io_stream
import json as _io_json
import os
from pathlib import Path as _IOPath
import re as _io_re
import subprocess as _io_subprocess
import sys as _io_sys
from types import ModuleType as _IOModule

_CURRENT_SNAPSHOT = '6eea8632c5d9a5504092c7b7c45ba57f3e7d6ddb'
_OLDER_SNAPSHOT = '71c1b06f36c4b6c01fcca6432c64ff5f4a18b8b9'
_SELECTED_WIRE_LIMIT = 12 * 1024 * 1024
_IO_EFFECTS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    publication_performed=False, forecast_generated=False, broader_goals_proven=False)
_IO_COUNT_NAMES = (
    'snapshots_checked', 'current_active_rejections', 'retained_history_originals',
    'orphan_groups', 'proved_groups', 'older_active_bodies_checked', 'planned_active_originals',
)
_IO_REASONS = {
    'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED', 'CURRENT_HISTORY_INVALID',
    'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING', 'TRUSTED_MAIN_REQUIRED',
    'AUTHENTICATED_PAIR_UNAVAILABLE', 'PUBLIC_REPORT_INVALID', 'CLI_ARGUMENTS_REJECTED',
}


def _io_require(condition):
    if not condition:
        raise ValueError('SELECTED_SNAPSHOT_REQUIRED')


def _io_commit(value):
    _io_require(type(value) is str and _io_re.fullmatch(r'[a-f0-9]{40}', value) is not None)
    return value


class AncestryHold(ValueError):
    """Fixed public ancestry failure class; no private detail is retained."""
    __slots__ = ('reason',)

    def __init__(self, reason):
        self.reason = (reason if type(reason) is str and reason in
            ('BOUND_EXCEEDED', 'INPUT_OR_CHAIN_INVALID') else 'INPUT_OR_CHAIN_INVALID')
        super().__init__(self.reason)


class ReadBudget:
    """One aggregate byte/snapshot/parent-hop budget shared by selected reads."""
    __slots__ = ('_remaining', '_snapshots', '_snapshot_limit', '_remaining_hops')

    def __init__(self, limit=256 * 1024 * 1024, snapshot_limit=32, hop_limit=128):
        _io_require(type(limit) is int and 0 < limit <= 256 * 1024 * 1024
            and type(snapshot_limit) is int and 0 < snapshot_limit <= 32
            and type(hop_limit) is int and 0 < hop_limit <= 128)
        self._remaining = limit
        self._snapshot_limit = snapshot_limit
        self._snapshots = set()
        self._remaining_hops = hop_limit

    @property
    def remaining(self):
        return self._remaining

    @property
    def remaining_hops(self):
        return self._remaining_hops

    def consume(self, raw):
        _io_require(type(raw) is bytes and bool(raw))
        if len(raw) > self._remaining:
            raise AncestryHold('BOUND_EXCEEDED')
        self._remaining -= len(raw)

    def enter(self, snapshot_sha):
        _io_commit(snapshot_sha)
        _io_require(snapshot_sha not in self._snapshots)
        if len(self._snapshots) >= self._snapshot_limit:
            raise AncestryHold('BOUND_EXCEEDED')
        self._snapshots.add(snapshot_sha)

    def hop(self):
        if self._remaining_hops <= 0:
            raise AncestryHold('BOUND_EXCEEDED')
        self._remaining_hops -= 1


class _SelectedSnapshotReader:
    """Validate selected manifest/cipher modes, not an entire historical tree."""
    def __init__(self, repository, snapshot_sha, *, feed, budget):
        self._repository = repository
        self._snapshot = _io_commit(snapshot_sha)
        self._feed = feed
        _io_require(type(budget) is ReadBudget)
        self._budget = budget
        self.ref = 'state/boat-saved-view'
        self._saved_history_context = None

    def head(self):
        return self._snapshot

    def fetch(self, commit):
        if self._budget.remaining <= 0:
            raise AncestryHold('BOUND_EXCEEDED')
        return self._repository.fetch(_io_commit(commit))

    def exists(self, commit, path):
        if self._budget.remaining <= 0:
            raise AncestryHold('BOUND_EXCEEDED')
        return self._repository.exists(_io_commit(commit), path)

    def read(self, commit, path, limit):
        _io_commit(commit)
        _io_require(type(limit) is int and limit > 0)
        if self._budget.remaining <= 0:
            raise AncestryHold('BOUND_EXCEEDED')
        maximum = min(limit, self._budget.remaining, _SELECTED_WIRE_LIMIT)
        try:
            raw = self._repository.read(commit, path, maximum)
        except ValueError as error:
            # The unchanged Git reader reports this fixed size-bound class.
            # Never expose or classify arbitrary exception text.
            if type(error) is ValueError and error.args == ('STATE_GIT_BLOB_BOUND_EXCEEDED',):
                raise AncestryHold('BOUND_EXCEEDED') from None
            raise
        _io_require(type(raw) is bytes and 0 < len(raw) <= maximum)
        self._budget.consume(raw)
        return raw

    def _selected_mode(self, commit, path):
        rows = self._repository._run(['ls-tree', commit, '--', path])
        _io_require(type(rows) is bytes and 0 < len(rows) <= 4096)
        expected = r'100644 blob [a-f0-9]{40}\t' + _io_re.escape(path) + r'\n?'
        _io_require(_io_re.fullmatch(expected, rows.decode('utf-8')) is not None)

    def validate_tree(self, commit):
        _io_require(commit == self._snapshot)
        self._selected_mode(commit, 'latest.json')
        manifest = self._feed._json(self.read(commit, 'latest.json', 4096), 4096)
        _io_require(type(manifest) is dict and set(manifest) == {'header', 'cipher_sha256'})
        self._feed._header(manifest['header'])
        ident = manifest['cipher_sha256']
        _io_require(type(ident) is str and _io_re.fullmatch(r'[a-f0-9]{64}', ident) is not None)
        self._selected_mode(commit, 'views/' + ident + '.json')

    def commit(self, *args, **kwargs):
        raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')

    def commit_snapshot(self, *args, **kwargs):
        raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')

    def push(self, *args, **kwargs):
        raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')


def _read_verified_snapshot(repository, bootstrap, snapshot_sha, *, feed, guard, budget, day=None):
    budget.enter(snapshot_sha)
    selected = _SelectedSnapshotReader(repository, snapshot_sha, feed=feed, budget=budget)
    # This unchanged reader owns manifest equality, cipher SHA, AEAD, V5 routing,
    # chunk inventories and the original forecast anchor.
    parent, ident, generation, view = feed.current_view(selected, bootstrap, day=day)
    _io_require(parent == snapshot_sha and type(generation) is int and type(view) is dict)
    manifest = feed._json(selected.read(snapshot_sha, 'latest.json', 4096), 4096)
    _io_require(type(manifest) is dict and set(manifest) == {'header', 'cipher_sha256'})
    header = feed._header(manifest['header'])
    _io_require(type(header) is dict and type(header.get('generation')) is int
        and header['generation'] == generation and manifest['cipher_sha256'] == ident
        and type(ident) is str and _io_re.fullmatch(r'[a-f0-9]{64}', ident) is not None)
    raw = selected.read(snapshot_sha, 'views/' + ident + '.json', feed.MAX_WIRE)
    _io_require(_io_hashlib.sha256(raw).hexdigest() == ident)
    guard._tree(view)
    if day is not None:
        _io_require(view.get('event_date_jst') == day)
        _io_require(all(type(row) is dict and row.get('event_date_jst') == day
            for row in view.get('records', [])))
    return _verified_snapshot(view, header=header, manifest_cipher_sha256=ident,
        snapshot_sha=snapshot_sha, ciphertext=raw)


_IO_BOUNDARY = None


def _io_boundary():
    global _IO_BOUNDARY
    if _IO_BOUNDARY is None:
        source = _IOPath(__file__).resolve().with_name('boat_saved_reason_binding_audit.py')
        _io_require(source.is_file() and not source.is_symlink())
        raw = source.read_bytes()
        _io_require(0 < len(raw) <= 128 * 1024)
        digest = _io_hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
        _io_require(digest == '307e83bd20f19cb473323dbef003d2abd518fcf4')
        spec = _io_importlib.spec_from_file_location('anchor_existing_main_boundary', source)
        module = _io_importlib.module_from_spec(spec)
        spec.loader.exec_module(module)
        _IO_BOUNDARY = module
    return _IO_BOUNDARY


def _io_hold(reason):
    if reason not in _IO_REASONS:
        reason = 'PUBLIC_REPORT_INVALID'
    return dict(schema=SCHEMA, status='HOLD', reason=reason, counts=None,
        snapshots=[], **_IO_EFFECTS)


def _io_safe_summary(report):
    _io_require(type(report) is dict and report.get('schema') == SCHEMA)
    status = report.get('status')
    _io_require(status in ('ALL_ORPHAN_ANCHORS_PROVEN', 'NO_ORPHAN_ANCHORS', 'HOLD'))
    fields = {'schema', 'status', 'counts', 'snapshots', *_IO_EFFECTS}
    if status == 'HOLD':
        fields.add('reason')
    _io_require(set(report) == fields)
    _io_require(all(type(report.get(name)) is type(value) and report[name] == value
        for name, value in _IO_EFFECTS.items()))
    if status == 'HOLD':
        _io_require(report.get('reason') in _IO_REASONS
            and report.get('counts') is None and report.get('snapshots') == [])
        return _io_hold(report['reason'])
    counts, snapshots = report['counts'], report['snapshots']
    _io_require(type(counts) is dict and set(counts) == set(_IO_COUNT_NAMES)
        and all(type(counts[name]) is int and 0 <= counts[name] <= 2147483647
                for name in _IO_COUNT_NAMES))
    _io_require(type(snapshots) is list and 1 <= len(snapshots) <= 32
        and counts['snapshots_checked'] == len(snapshots))
    public_snapshots, seen = [], set()
    for snapshot in snapshots:
        _io_require(type(snapshot) is dict and set(snapshot) == {'snapshot_sha', 'cipher_sha256'})
        commit, cipher = snapshot['snapshot_sha'], snapshot['cipher_sha256']
        _io_commit(commit)
        _io_require(type(cipher) is str and _io_re.fullmatch(r'[a-f0-9]{64}', cipher) is not None
            and commit not in seen)
        seen.add(commit)
        public_snapshots.append(dict(snapshot_sha=commit, cipher_sha256=cipher))
    _io_require(counts['proved_groups'] == counts['planned_active_originals'])
    if status == 'ALL_ORPHAN_ANCHORS_PROVEN':
        _io_require(counts['orphan_groups'] > 0
            and counts['proved_groups'] == counts['orphan_groups'])
    else:
        _io_require(counts['orphan_groups'] == counts['proved_groups'] == 0)
    return dict(schema=SCHEMA, status=status,
        counts={name: counts[name] for name in _IO_COUNT_NAMES},
        snapshots=public_snapshots, **_IO_EFFECTS)


def run_audit(environment, event, *, load_pair):
    try:
        with _io_stdout(_io_stream.StringIO()), _io_stderr(_io_stream.StringIO()):
            trusted = _io_boundary()._io_trusted(environment, event)
        if trusted is not True:
            return _io_hold('TRUSTED_MAIN_REQUIRED')
    except Exception:
        return _io_hold('TRUSTED_MAIN_REQUIRED')
    try:
        with _io_stdout(_io_stream.StringIO()), _io_stderr(_io_stream.StringIO()):
            pair = load_pair()
            _io_require(type(pair) is tuple and len(pair) == 3)
            current, older, guard = pair
            _io_require(type(current) is VerifiedSnapshot and type(older) is tuple
                and all(type(item) is VerifiedSnapshot for item in older)
                and isinstance(guard, _IOModule))
    except AncestryHold as error:
        return _io_hold(error.reason)
    except Exception:
        return _io_hold('AUTHENTICATED_PAIR_UNAVAILABLE')
    try:
        with _io_stdout(_io_stream.StringIO()), _io_stderr(_io_stream.StringIO()):
            decision = match_rejection_anchor_proofs(current, older, guard=guard)
            report = decision.public_summary()
        return _io_safe_summary(report)
    except Exception:
        return _io_hold('PUBLIC_REPORT_INVALID')


def main(argv=None):
    arguments = _io_sys.argv[1:] if argv is None else argv
    if type(arguments) not in (list, tuple) or arguments:
        report = _io_hold('CLI_ARGUMENTS_REJECTED')
    else:
        try:
            path_value = os.environ.get('GITHUB_EVENT_PATH')
            _io_require(type(path_value) is str and bool(path_value))
            path = _IOPath(path_value)
            _io_require(path.is_file() and not path.is_symlink()
                and 0 < path.stat().st_size <= 1024 * 1024)
            raw = path.read_bytes()
            _io_require(0 < len(raw) <= 1024 * 1024)
            boundary = _io_boundary()
            event = _io_json.loads(raw.decode('utf-8'), object_pairs_hook=boundary._io_unique,
                parse_constant=boundary._io_nonfinite)
            _io_require(type(event) is dict)
        except Exception:
            report = _io_hold('TRUSTED_MAIN_REQUIRED')
        else:
            report = run_audit(os.environ, event, load_pair=_load_authenticated_pair)
    print(_io_json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report['status'] == 'HOLD' else 0



def _load_authenticated_pair():
    boundary = _io_boundary()
    root = _IOPath.cwd().resolve()
    workspace = os.environ.get('GITHUB_WORKSPACE')
    _io_require(type(workspace) is str and bool(workspace)
        and root.name == 'owner-source' and root.parent == _IOPath(workspace).resolve()
        and _IOPath(__file__).resolve().parent.parent == root.parent)

    def git_head(folder):
        return _io_subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder,
            timeout=10, stderr=_io_subprocess.DEVNULL).decode().strip()

    def clean(folder, paths):
        _io_subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *paths],
            cwd=folder, check=True, timeout=10,
            stdout=_io_subprocess.DEVNULL, stderr=_io_subprocess.DEVNULL)

    _io_require(git_head(root) == '86b029ae5bddd5d4956497d8b32b2c92b8eec521'
        and git_head(root.parent) == os.environ.get('GITHUB_SHA'))
    clean(root, ['race_ai', 'scripts', 'audit/state/boat-saved-view-input.json'])
    clean(root.parent, ['scripts/boat_saved_rejection_anchor_audit.py',
        'scripts/boat_saved_reason_binding_audit.py'])
    pins = (
        ('race_ai/boat_saved_model_view.py', 'e6db8d720aa151940e01f377831a5884eb4b2ba9'),
        ('race_ai/saved_view_feed.py', '9bb3bf0d1e48c9b3e3ba8e42030d5a05b681f900'),
        ('race_ai/saved_view_history.py', '3587debeeb4024dc768cac69f1a8aca9014d6f3e'),
        ('race_ai/racer_daily_handoff.py', '497c1a6c00bdf6d9512a174f6c4b7b2f914c3f47'),
        ('scripts/boat_saved_view_feed.py', '87f4f374fab19d9e45043116040dbfecd35bf8af'),
    )
    for relative, expected in pins:
        boundary._io_source_blob(root / relative, expected)
    import race_ai
    _io_require(_IOPath(race_ai.__file__).resolve() == root / 'race_ai/__init__.py')
    for folder, expected in (
            ('pr64-reference', '761247bee0209e37b1af6b8885e92cad3e9260a5'),
            ('pr72-reference', '7a432e5acc4d3495a0e82bd79726929e2f8085fe')):
        package = root / folder / 'race_ai'
        _io_require(package.is_dir() and not package.is_symlink()
            and git_head(package.parent) == expected)
        clean(package.parent, ['race_ai'])
        if str(package) not in race_ai.__path__:
            race_ai.__path__.append(str(package))
    from race_ai import boat_saved_model_view as guard
    from race_ai import saved_view_feed as feed
    from race_ai import saved_view_history as history
    from race_ai.racer_daily_handoff import _DailyFilteredFetch
    from scripts import boat_saved_view_feed as publisher
    for module, relative in (
            (guard, 'race_ai/boat_saved_model_view.py'),
            (feed, 'race_ai/saved_view_feed.py'),
            (history, 'race_ai/saved_view_history.py'),
            (publisher, 'scripts/boat_saved_view_feed.py')):
        _io_require(_IOPath(module.__file__).resolve() == root / relative)
    _io_require(_DailyFilteredFetch.__module__ == 'race_ai.racer_daily_handoff')
    config_path = root / 'audit/state/boat-saved-view-input.json'
    _io_require(config_path.is_file() and not config_path.is_symlink()
        and 0 < config_path.stat().st_size <= 8192)
    config = publisher._json(config_path.read_bytes(), 8192)
    _io_require(type(config) is dict
        and set(config) == {'schema', 'bootstrap', 'bootstrap_sha256', 'catchup_artifact_id', 'catchup_sha256'}
        and config.get('schema') == 'RACE_AI_SAVED_VIEW_INPUT_V1'
        and type(config.get('bootstrap')) is str)
    raw = _io_base64.b64decode(config['bootstrap'], validate=True)
    _io_require(_io_hashlib.sha256(raw).hexdigest() == config['bootstrap_sha256'])
    publisher.git_auth()
    bootstrap = feed.open_bootstrap(raw)

    class ReadOnlyRepository(_DailyFilteredFetch, feed.FeedRepository):
        def commit(self, *args, **kwargs):
            raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')
        def commit_snapshot(self, *args, **kwargs):
            raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')
        def push(self, *args, **kwargs):
            raise ValueError('READ_ONLY_SELECTED_SNAPSHOT')

    repository = ReadOnlyRepository(root)
    budget = ReadBudget()
    current = _read_verified_snapshot(repository, bootstrap, _CURRENT_SNAPSHOT,
        feed=feed, guard=guard, budget=budget)
    _io_require(current._header['schema'] == 'RACE_AI_SAVED_WEB_HISTORY_V5'
        and current._header['generation'] == 424)
    day = current._view.get('event_date_jst')
    guard._day(day)
    _io_require(all(type(row) is dict and row.get('event_date_jst') == day
        for row in current._view['records']))
    older = _read_verified_snapshot(repository, bootstrap, _OLDER_SNAPSHOT,
        feed=feed, guard=guard, budget=budget, day=day)
    _io_require(older._header['schema'] == 'RACE_AI_SAVED_WEB_HISTORY_V5'
        and older._header['generation'] == 423)
    older_chain = _extend_authenticated_chain(repository, bootstrap, current, (older,),
        feed=feed, guard=guard, budget=budget)
    return current, older_chain, guard


def _ancestry_require(condition):
    if not condition:
        raise AncestryHold('INPUT_OR_CHAIN_INVALID')


def _ancestry_parent_header(raw):
    """Read only the Git header section; message/signature text is not ancestry."""
    _ancestry_require(type(raw) is bytes and bool(raw) and b'\0' not in raw and b'\r' not in raw)
    head, separator, _ = raw.partition(b'\n\n')
    _ancestry_require(bool(separator) and bool(head))
    lines = head.split(b'\n')
    _ancestry_require(_io_re.fullmatch(rb'tree [a-f0-9]{40}', lines[0]) is not None)
    seen = {b'tree'}
    parent = None
    previous = b'tree'
    for line in lines[1:]:
        if line.startswith(b' '):
            _ancestry_require(previous not in (b'tree', b'parent', b'author', b'committer', b'encoding')
                and len(line) > 1)
            continue
        key, space, value = line.partition(b' ')
        _ancestry_require(bool(space) and bool(value)
            and _io_re.fullmatch(rb'[a-z][a-z0-9-]{0,63}', key) is not None
            and key not in seen)
        if key == b'parent':
            _ancestry_require(b'author' not in seen and b'committer' not in seen
                and _io_re.fullmatch(rb'[a-f0-9]{40}', value) is not None)
            parent = value.decode('ascii')
        elif key in (b'author', b'committer'):
            _ancestry_require(parent is not None
                and _io_re.fullmatch(rb'.+ <[^<>\n]+> -?[0-9]+ [+-][0-9]{4}', value) is not None)
            if key == b'committer':
                _ancestry_require(b'author' in seen)
            else:
                _ancestry_require(b'committer' not in seen)
        seen.add(key)
        previous = key
    _ancestry_require(parent is not None and {b'tree', b'parent', b'author', b'committer'} <= seen)
    return parent


def _ancestry_parent(repository, commit, budget):
    """Size before payload, including when Git marks the commit shallow."""
    _io_commit(commit)
    # Reserve bounded type/size metadata before asking Git for a payload.
    if budget.remaining < 40:
        raise AncestryHold('BOUND_EXCEEDED')
    kind = repository._run(['cat-file', '-t', commit])
    _ancestry_require(type(kind) is bytes and 0 < len(kind) <= 8)
    budget.consume(kind)
    _ancestry_require(kind == b'commit\n')
    size_raw = repository._run(['cat-file', '-s', commit])
    _ancestry_require(type(size_raw) is bytes and 0 < len(size_raw) <= 32)
    budget.consume(size_raw)
    _ancestry_require(_io_re.fullmatch(rb'[1-9][0-9]{0,19}\n?', size_raw) is not None)
    size = int(size_raw)
    if size > 64 * 1024 or size > budget.remaining:
        raise AncestryHold('BOUND_EXCEEDED')
    raw = repository._run(['cat-file', '-p', commit])
    _ancestry_require(type(raw) is bytes and len(raw) == size)
    budget.consume(raw)
    return _ancestry_parent_header(raw)


def _find_predecessor_commit(repository, newerReceipt, *, feed, budget, max_hops=128):
    """Select the first distinct immediate-ancestry manifest, never a side branch."""
    try:
        _ancestry_require(type(max_hops) is int and 1 <= max_hops <= 128
            and type(budget) is ReadBudget)
        _proof_verify_receipt(newerReceipt)
        _ancestry_require(newerReceipt._header['generation'] > 1)
        cursor = newerReceipt._snapshot_sha
        visited = {cursor}
        local_hops = 0
        while True:
            if local_hops >= max_hops or budget.remaining_hops <= 0:
                raise AncestryHold('BOUND_EXCEEDED')
            parent = _ancestry_parent(repository, cursor, budget)
            _ancestry_require(parent not in visited)
            # No fetch is useful after metadata exhausts the shared bytes.
            if budget.remaining <= 0:
                raise AncestryHold('BOUND_EXCEEDED')
            # Charge the transition before any fetch of its parent.
            budget.hop()
            local_hops += 1
            repository.fetch(parent)
            selected = _SelectedSnapshotReader(repository, parent, feed=feed, budget=budget)
            selected._selected_mode(parent, 'latest.json')
            manifest = feed._json(selected.read(parent, 'latest.json', 4096), 4096)
            _ancestry_require(type(manifest) is dict and set(manifest) == {'header', 'cipher_sha256'})
            candidate_header = feed._header(manifest['header'])
            _proof_header(candidate_header)
            cipher = manifest['cipher_sha256']
            _ancestry_require(_proof_sha(cipher))
            if (candidate_header == newerReceipt._header
                    and cipher == newerReceipt._cipher_sha256):
                visited.add(parent)
                cursor = parent
                continue
            _ancestry_require(candidate_header['generation'] == newerReceipt._header['generation'] - 1
                and cipher == newerReceipt._header['previous_cipher_sha256'])
            return parent
    except AncestryHold:
        raise
    except Exception:
        raise AncestryHold('INPUT_OR_CHAIN_INVALID') from None


def _extend_authenticated_chain(repository, bootstrap, current, older_chain, *, feed, guard, budget):
    """Extend only an explicitly missing proof, using the unchanged authenticated reader."""
    try:
        _ancestry_require(type(current) is VerifiedSnapshot and type(older_chain) is tuple
            and bool(older_chain) and all(type(item) is VerifiedSnapshot for item in older_chain)
            and type(budget) is ReadBudget)
        chain = older_chain
        day = None
        while True:
            # The existing matcher checks receipt count/byte bounds before
            # hashing bodies. Non-missing decisions never start an ancestry read.
            decision = match_rejection_anchor_proofs(current, chain, guard=guard)
            summary = _io_safe_summary(decision.public_summary())
            if summary['status'] != 'HOLD' or summary['reason'] != 'ACTIVE_PROOF_MISSING':
                return chain
            if day is None:
                day = current._view.get('event_date_jst')
                guard._day(day)
            for receipt in (current, *chain):
                _ancestry_require(receipt._view.get('event_date_jst') == day
                    and all(type(row) is dict and row.get('event_date_jst') == day
                            for row in receipt._view['records']))
            if (1 + len(chain) >= MAX_SNAPSHOTS
                    or budget.remaining <= 0 or budget.remaining_hops <= 0):
                raise AncestryHold('BOUND_EXCEEDED')
            candidate = _find_predecessor_commit(repository, chain[-1],
                feed=feed, budget=budget, max_hops=128)
            _ancestry_require(candidate not in {item._snapshot_sha for item in (current, *chain)})
            older = _read_verified_snapshot(repository, bootstrap, candidate,
                feed=feed, guard=guard, budget=budget, day=day)
            chain = (*chain, older)
    except AncestryHold:
        raise
    except Exception:
        raise AncestryHold('INPUT_OR_CHAIN_INVALID') from None


if __name__ == '__main__':
    raise SystemExit(main())
