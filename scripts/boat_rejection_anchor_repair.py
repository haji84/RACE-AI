"""One Actions-only V5 rejection-anchor repair orchestration.

The fixed caller owns source pins, authenticated context and existing handles.
This prefix neither loads keys/files nor implements transport, cryptography,
CLI arguments, a private loader, retries or protocol activation.
"""
from contextlib import redirect_stdout as _repair_stdout, redirect_stderr as _repair_stderr
from copy import deepcopy as _repair_copy
import hashlib as _repair_hashlib
import json as _repair_json
import re as _repair_re
from types import ModuleType as _RepairModule


SCHEMA = 'RACE_AI_REJECTION_ANCHOR_REPAIR_V1'
COUNTS = ('snapshots_checked', 'orphan_groups', 'current_active_rejections',
    'candidate_active_rejections', 'retained_history_originals',
    'restored_active_originals', 'rows_changed')
EFFECTS = dict(originals_changed=False, observations_reconciled=0,
    source_requests=0, forecast_generated=False, broader_goals_proven=False)
HASHES = ('current_view_sha256', 'candidate_view_sha256', 'published_snapshot_sha',
    'published_cipher_sha256', 'published_generation')
_REPAIR_REASONS = frozenset((
    'CLI_ARGUMENTS_REJECTED', 'TRUSTED_MAIN_REQUIRED', 'AUTHENTICATED_CONTEXT_UNAVAILABLE',
    'V5_CURRENT_REQUIRED', 'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED',
    'CURRENT_HISTORY_INVALID', 'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING',
    'CANDIDATE_GUARD_REJECTED', 'PUBLIC_CANDIDATE_INVALID', 'PREDECESSOR_CHANGED',
    'PUBLICATION_OUTCOME_UNKNOWN', 'AUTHENTICATED_READBACK_UNAVAILABLE', 'READBACK_MISMATCH',
))
_REPAIR_PROOF_REASONS = frozenset((
    'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED', 'CURRENT_HISTORY_INVALID',
    'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING', 'CANDIDATE_GUARD_REJECTED',
))
_REPAIR_V5 = 'RACE_AI_SAVED_WEB_HISTORY_V5'
_REPAIR_ACTIVE = 'result_observation_rejections'
_REPAIR_HISTORY = 'saved_result_rejection_reason_variants'


class _RepairSilentStream:
    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


def _repair_require(condition):
    if not condition:
        raise ValueError('REPAIR_REPORT_OR_CONTEXT_INVALID')


def _repair_sha(value, length=64):
    return type(value) is str and _repair_re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def _repair_wire(value):
    return _repair_json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')


def _repair_digest(value):
    return _repair_hashlib.sha256(_repair_wire(value)).hexdigest()


def _hold(reason, *, attempted=False, performed=False):
    attempted = attempted if type(attempted) is bool else True
    performed = (True if performed is True else None) if attempted else False
    safe = reason if type(reason) is str and reason in _REPAIR_REASONS else (
        'PUBLICATION_OUTCOME_UNKNOWN' if attempted else 'PUBLIC_CANDIDATE_INVALID')
    return dict(schema=SCHEMA, status='HOLD', reason=safe, counts=None,
        **{name: None for name in HASHES}, **EFFECTS,
        publication_attempted=attempted, publication_performed=performed,
        readback_verified=False)


def _repair_counts(counts):
    _repair_require(type(counts) is dict and set(counts) == set(COUNTS)
        and all(type(counts[name]) is int and 0 <= counts[name] <= 2147483647 for name in COUNTS))
    _repair_require(1 <= counts['snapshots_checked'] <= 32
        and counts['orphan_groups'] == counts['restored_active_originals']
        and counts['candidate_active_rejections'] == counts['current_active_rejections'] + counts['restored_active_originals']
        and counts['rows_changed'] <= counts['restored_active_originals'])
    return {name: counts[name] for name in COUNTS}


def _safe_report(report):
    """Validate an entire public report, including publication uncertainty."""
    _repair_require(type(report) is dict and type(report.get('schema')) is str and report['schema'] == SCHEMA)
    status = report.get('status')
    _repair_require(type(status) is str and status in ('HOLD', 'NO_CHANGE', 'PUBLISHED_VERIFIED'))
    fields = {'schema', 'status', 'counts', *HASHES, *EFFECTS,
        'publication_attempted', 'publication_performed', 'readback_verified'}
    if status == 'HOLD':
        fields.add('reason')
    _repair_require(set(report) == fields)
    _repair_require(all(type(report[name]) is type(expected) and report[name] == expected
        for name, expected in EFFECTS.items()))
    attempted, performed, readback = (report[name] for name in
        ('publication_attempted', 'publication_performed', 'readback_verified'))
    _repair_require(type(attempted) is bool and type(readback) is bool
        and (performed is None or type(performed) is bool))
    if status == 'HOLD':
        _repair_require(type(report['reason']) is str and report['reason'] in _REPAIR_REASONS
            and report['counts'] is None and all(report[name] is None for name in HASHES)
            and readback is False
            and ((attempted is False and performed is False)
                 or (attempted is True and (performed is None or performed is True))))
    else:
        counts = _repair_counts(report['counts'])
        _repair_require(_repair_sha(report['current_view_sha256']))
        if status == 'NO_CHANGE':
            _repair_require(counts['orphan_groups'] == counts['restored_active_originals'] == counts['rows_changed'] == 0
                and attempted is False and performed is False and readback is False
                and all(report[name] is None for name in HASHES[1:]))
        else:
            _repair_require(counts['orphan_groups'] > 0 and counts['rows_changed'] > 0
                and counts['snapshots_checked'] >= 2
                and attempted is True and performed is True and readback is True
                and _repair_sha(report['candidate_view_sha256'])
                and _repair_sha(report['published_snapshot_sha'], 40)
                and _repair_sha(report['published_cipher_sha256'])
                and type(report['published_generation']) is int
                and 2 <= report['published_generation'] <= 999999)
    return _repair_copy(report)


def _repair_trusted(environment, event):
    expected = (
        ('GITHUB_ACTIONS', 'true'), ('GITHUB_EVENT_NAME', 'push'),
        ('GITHUB_REF', 'refs/heads/main'), ('GITHUB_REPOSITORY', 'haji84/RACE-AI'),
        ('GITHUB_REPOSITORY_ID', '1416489937'), ('GITHUB_RUN_ATTEMPT', '1'),
        ('GITHUB_JOB', 'owner_p0_p1_dispatch'),
        ('GITHUB_WORKFLOW_REF', 'haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main'),
    )
    if not all(type(environment.get(name)) is str and environment.get(name) == value
               for name, value in expected):
        return False
    head = environment.get('GITHUB_SHA')
    if not _repair_sha(head, 40) or type(event) is not dict:
        return False
    commit, repository = event.get('head_commit'), event.get('repository')
    return (type(commit) is dict and type(repository) is dict
        and type(event.get('ref')) is str and event['ref'] == 'refs/heads/main'
        and type(event.get('after')) is str and event['after'] == head
        and event.get('deleted') is False
        and type(commit.get('id')) is str and commit['id'] == head
        and type(commit.get('message')) is str
        and commit['message'].startswith('boat-owner-release: single-real-session-20261111')
        and type(repository.get('full_name')) is str and repository['full_name'] == 'haji84/RACE-AI'
        and type(repository.get('id')) is int and repository['id'] == 1416489937
        and repository.get('private') is False and repository.get('fork') is False)


def _repair_context(context):
    names = {'proof', 'candidate', 'guard', 'feed', 'repository', 'bootstrap', 'current', 'older_chain'}
    _repair_require(type(context) is dict and set(context) == names)
    proof, candidate, guard, feed = (context[name] for name in ('proof', 'candidate', 'guard', 'feed'))
    _repair_require(all(type(module) is _RepairModule for module in (proof, candidate, guard, feed)))
    _repair_require(proof.SCHEMA == 'RACE_AI_SAVED_REJECTION_ANCHOR_PROOF_V1'
        and candidate.SCHEMA == 'RACE_AI_REJECTION_ANCHOR_RESTORATION_V1'
        and callable(proof._proof_verify_receipt) and callable(proof._read_verified_snapshot)
        and callable(proof.ReadBudget) and callable(candidate.build_rejection_anchor_restoration)
        and callable(guard._observations) and callable(feed.publish_view))
    _repair_require(type(context['current']) is proof.VerifiedSnapshot
        and type(context['older_chain']) is tuple
        and all(type(item) is proof.VerifiedSnapshot for item in context['older_chain']))
    repository, bootstrap = context['repository'], context['bootstrap']
    _repair_require(type(feed.REF) is str and feed.REF == 'state/boat-saved-view'
        and type(repository.ref) is str and repository.ref == feed.REF and callable(repository.head))
    _repair_require(type(bootstrap) is dict and type(bootstrap.get('key')) is bytes
        and len(bootstrap['key']) == 32)
    return proof, candidate, guard, feed, repository, bootstrap, context['current'], context['older_chain']


def _repair_bound_context(current, bootstrap, guard):
    header, view = current._header, current._view
    _repair_require(header['generation'] < 999999)
    for name, field in (('view_id', 'view_id'), ('forecast_sha256', 'forecast_sha256'),
                        ('cipher_sha256', 'source_content_sha256')):
        _repair_require(_repair_sha(bootstrap.get(name)) and bootstrap[name] == header[field])
    day = view.get('event_date_jst')
    guard._day(day)
    _repair_require(type(day) is str and all(type(row) is dict
        and row.get('event_date_jst') == day for row in view['records']))
    return day


def _repair_originals(before, after):
    """Compare every non-ACTIVE field and every existing ACTIVE body verbatim."""
    old = _repair_json.loads(_repair_wire(before))
    new = _repair_json.loads(_repair_wire(after))
    _repair_require(type(old) is dict and type(new) is dict
        and type(old.get('records')) is list and type(new.get('records')) is list
        and len(old['records']) == len(new['records']))
    restored = changed = current_active = history = 0
    for left, right in zip(old['records'], new['records']):
        _repair_require(type(left) is dict and type(right) is dict)
        left_present, right_present = _REPAIR_ACTIVE in left, _REPAIR_ACTIVE in right
        original = left.pop(_REPAIR_ACTIVE, [])
        proposed = right.pop(_REPAIR_ACTIVE, [])
        _repair_require(type(original) is list and type(proposed) is list
            and len(proposed) >= len(original)
            and _repair_wire(proposed[:len(original)]) == _repair_wire(original)
            and (not left_present or right_present)
            and (left_present == right_present or bool(proposed)))
        added = len(proposed) - len(original)
        current_active += len(original)
        history += len(left.get(_REPAIR_HISTORY, []))
        restored += added
        changed += int(added > 0)
    _repair_require(_repair_wire(old) == _repair_wire(new))
    return current_active, history, restored, changed


def _repair_guarded_view(view, guard):
    before = _repair_wire(view)
    guard._tree(view)
    for row in view['records']:
        guard._observations([row], 'result_observations')
        guard._observations([row], _REPAIR_ACTIVE, rejection=True)
    _repair_require(_repair_wire(view) == before)


def _repair_candidate_result(value, module, current, older, guard):
    _repair_require(type(value) is tuple and len(value) == 2)
    candidate, report = value
    _repair_require(type(report) is dict and type(report.get('schema')) is str
        and report['schema'] == 'RACE_AI_REJECTION_ANCHOR_RESTORATION_V1')
    status = report.get('status')
    _repair_require(type(status) is str and status in ('HOLD', 'NO_CHANGE', 'READY'))
    effects = dict(EFFECTS, publication_performed=False)
    fields = {'schema', 'status', 'counts', 'current_view_sha256', 'candidate_view_sha256', *effects}
    if status == 'HOLD':
        fields.add('reason')
    _repair_require(set(report) == fields and all(type(report[name]) is type(expected)
        and report[name] == expected for name, expected in effects.items()))
    if status == 'HOLD':
        _repair_require(candidate is None and report['counts'] is None
            and report['current_view_sha256'] is None and report['candidate_view_sha256'] is None
            and type(report['reason']) is str and report['reason'] in _REPAIR_PROOF_REASONS)
        return status, report, None
    counts = _repair_counts(report['counts'])
    _repair_require(counts['snapshots_checked'] == len(older) + 1
        and report['current_view_sha256'] == current._view_sha256
        and report['current_view_sha256'] == _repair_digest(current._view))
    if status == 'NO_CHANGE':
        _repair_require(candidate is None and report['candidate_view_sha256'] is None
            and counts['restored_active_originals'] == counts['orphan_groups'] == counts['rows_changed'] == 0)
        view = _repair_json.loads(_repair_wire(current._view))
    else:
        _repair_require(type(candidate) is module.RejectionAnchorRestorationCandidate
            and counts['restored_active_originals'] > 0)
        view = candidate._copy_view()
        _repair_require(_repair_sha(report['candidate_view_sha256'])
            and report['candidate_view_sha256'] == _repair_digest(view))
    active, history, restored, rows = _repair_originals(current._view, view)
    _repair_require(counts['current_active_rejections'] == active
        and counts['retained_history_originals'] == history
        and counts['restored_active_originals'] == restored and counts['rows_changed'] == rows)
    _repair_guarded_view(view, guard)
    return status, report, view


def _repair_ack(ack, generation):
    _repair_require(type(ack) is dict and set(ack) == {
        'status', 'generation', 'commit', 'cipher_sha256', 'updated_dates', 'head_files'})
    _repair_require(type(ack['status']) is str and ack['status'] == 'ENCRYPTED_HISTORY_VIEW_PUBLISHED'
        and type(ack['generation']) is int and ack['generation'] == generation + 1
        and _repair_sha(ack['commit'], 40) and _repair_sha(ack['cipher_sha256'])
        and type(ack['updated_dates']) is int and ack['updated_dates'] == 1
        and type(ack['head_files']) is int and ack['head_files'] == 2)
    return _repair_copy(ack)


def _repair_readback(receipt, *, proof, current, candidate_view, ack, guard, day):
    _repair_require(type(receipt) is proof.VerifiedSnapshot)
    proof._proof_verify_receipt(receipt)
    header = receipt._header
    _repair_require(receipt._snapshot_sha == ack['commit']
        and receipt._cipher_sha256 == ack['cipher_sha256']
        and header['schema'] == _REPAIR_V5 and header['generation'] == ack['generation']
        and header['previous_cipher_sha256'] == current._cipher_sha256
        and all(header[name] == current._header[name] for name in
            ('view_id', 'source_content_sha256', 'forecast_sha256'))
        and receipt._view.get('event_date_jst') == day
        and all(row.get('event_date_jst') == day for row in receipt._view['records'])
        and _repair_wire(receipt._view) == _repair_wire(candidate_view))
    _repair_originals(current._view, receipt._view)
    _repair_guarded_view(receipt._view, guard)


def _repair_success(status, candidate_report, ack=None):
    published = status == 'PUBLISHED_VERIFIED'
    return _safe_report(dict(schema=SCHEMA, status=status,
        counts=_repair_copy(candidate_report['counts']),
        current_view_sha256=candidate_report['current_view_sha256'],
        candidate_view_sha256=candidate_report['candidate_view_sha256'],
        published_snapshot_sha=ack['commit'] if published else None,
        published_cipher_sha256=ack['cipher_sha256'] if published else None,
        published_generation=ack['generation'] if published else None, **EFFECTS,
        publication_attempted=published, publication_performed=published,
        readback_verified=published))


def run_repair(environment, event, *, load_context):
    """Attempt at most one unchanged publisher call after complete fresh proof."""
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            trusted = _repair_trusted(environment, event)
        if trusted is not True:
            return _hold('TRUSTED_MAIN_REQUIRED')
    except (Exception, SystemExit):
        return _hold('TRUSTED_MAIN_REQUIRED')
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            proof, module, guard, feed, repository, bootstrap, current, older = _repair_context(load_context())
    except (Exception, SystemExit):
        return _hold('AUTHENTICATED_CONTEXT_UNAVAILABLE')
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            proof._proof_verify_receipt(current)
    except (Exception, SystemExit):
        return _hold('INPUT_OR_CHAIN_INVALID')
    if current._header['schema'] != _REPAIR_V5:
        return _hold('V5_CURRENT_REQUIRED')
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            day = _repair_bound_context(current, bootstrap, guard)
    except (Exception, SystemExit):
        return _hold('AUTHENTICATED_CONTEXT_UNAVAILABLE')
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            result = module.build_rejection_anchor_restoration(current, older, guard=guard, proof=proof)
            status, report, candidate_view = _repair_candidate_result(result, module, current, older, guard)
        if status == 'HOLD':
            return _hold(report['reason'])
        if status == 'NO_CHANGE':
            return _repair_success('NO_CHANGE', report)
        # The publisher owns a detached copy; readback uses the authorized body.
        publication_view = _repair_copy(candidate_view)
    except (Exception, SystemExit):
        return _hold('PUBLIC_CANDIDATE_INVALID')
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            _repair_require(repository.head() == current._snapshot_sha)
    except (Exception, SystemExit):
        return _hold('PREDECESSOR_CHANGED')

    # The attempt starts here. Nothing after this point may report a definite
    # absence of publication, retry the call, or use a later mutable head.
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            ack = feed.publish_view(repository, bootstrap, publication_view,
                parent=current._snapshot_sha, previous=current._cipher_sha256,
                generation=current._header['generation'])
            ack = _repair_ack(ack, current._header['generation'])
    except (Exception, SystemExit):
        return _hold('PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None)
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            receipt = proof._read_verified_snapshot(repository, bootstrap, ack['commit'],
                feed=feed, guard=guard, budget=proof.ReadBudget(), day=day)
    except (Exception, SystemExit):
        return _hold('AUTHENTICATED_READBACK_UNAVAILABLE', attempted=True, performed=True)
    try:
        with _repair_stdout(_RepairSilentStream()), _repair_stderr(_RepairSilentStream()):
            _repair_readback(receipt, proof=proof, current=current,
                candidate_view=candidate_view, ack=ack, guard=guard, day=day)
            return _repair_success('PUBLISHED_VERIFIED', report, ack)
    except (Exception, SystemExit):
        return _hold('READBACK_MISMATCH', attempted=True, performed=True)

# CLI fragment: event input and public output only. Private context is provided
# by the separately reviewed _load_repair_context callback after trusted checks.
from contextlib import redirect_stderr as _cli_redirect_stderr
from contextlib import redirect_stdout as _cli_redirect_stdout
import json as _cli_json
import math as _cli_math
import os as _cli_os
import stat as _cli_stat
import sys as _cli_sys


_CLI_MAX_EVENT_BYTES = 1024 * 1024


class _cli_Quiet:
    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


def _cli_require(condition):
    if not condition:
        raise ValueError('INPUT_OR_CHAIN_INVALID')


def _cli_unique_object(pairs):
    result = {}
    for name, value in pairs:
        _cli_require(name not in result)
        result[name] = value
    return result


def _cli_reject_constant(value):
    raise ValueError('INPUT_OR_CHAIN_INVALID')


def _cli_finite_float(value):
    number = float(value)
    _cli_require(_cli_math.isfinite(number))
    return number


def _cli_event():
    name = _cli_os.environ.get('GITHUB_EVENT_PATH')
    _cli_require(type(name) is str and 0 < len(name) <= 8192 and '\0' not in name)
    before = _cli_os.lstat(name)
    _cli_require(_cli_stat.S_ISREG(before.st_mode)
        and 0 < before.st_size <= _CLI_MAX_EVENT_BYTES)
    flags = _cli_os.O_RDONLY | getattr(_cli_os, 'O_NOFOLLOW', 0)
    flags |= getattr(_cli_os, 'O_NONBLOCK', 0) | getattr(_cli_os, 'O_CLOEXEC', 0)
    descriptor = _cli_os.open(name, flags)
    try:
        opened = _cli_os.fstat(descriptor)
        _cli_require(_cli_stat.S_ISREG(opened.st_mode)
            and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
            and 0 < opened.st_size <= _CLI_MAX_EVENT_BYTES)
        with _cli_os.fdopen(descriptor, 'rb', closefd=False) as stream:
            raw = stream.read(_CLI_MAX_EVENT_BYTES + 1)
        after = _cli_os.fstat(descriptor)
        _cli_require(0 < len(raw) <= _CLI_MAX_EVENT_BYTES
            and len(raw) == opened.st_size == after.st_size)
    finally:
        _cli_os.close(descriptor)
    event = _cli_json.loads(raw.decode('utf-8'), object_pairs_hook=_cli_unique_object,
        parse_constant=_cli_reject_constant, parse_float=_cli_finite_float)
    _cli_require(type(event) is dict)
    return event


def _cli_emit(report):
    print(_cli_json.dumps(report, sort_keys=True, allow_nan=False, separators=(',', ':')))
    return 2 if report['status'] == 'HOLD' else 0


def main(argv=None):
    arguments = _cli_sys.argv[1:] if argv is None else argv
    # No environment, event path or private callback is touched before this.
    if type(arguments) not in (list, tuple) or arguments:
        return _cli_emit(_hold('CLI_ARGUMENTS_REJECTED'))
    try:
        event = _cli_event()
    except Exception:
        return _cli_emit(_hold('INPUT_OR_CHAIN_INVALID'))
    try:
        with _cli_redirect_stdout(_cli_Quiet()), _cli_redirect_stderr(_cli_Quiet()):
            report = run_repair(_cli_os.environ, event, load_context=_load_repair_context)
            report = _safe_report(report)
    except (Exception, SystemExit):
        # Orchestration may already have entered the existing publisher. An
        # unexpected failure must never invent a known no-publication outcome.
        report = _hold('PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None)
    return _cli_emit(report)


# The fixed Actions loader supplies actual authenticated objects to run_repair.
# It uses the existing source86 bootstrap, F/H readers and CAS publisher.
import base64 as _live_base64
import hashlib as _live_hashlib
import os as _live_os
from pathlib import Path as _LivePath
import re as _live_re
import subprocess as _live_subprocess
from types import ModuleType as _LiveModule

_LIVE_EXPECTED_MAIN_PARENT = '09b65329692389fe260e4aa0430e94f341b255dc'
_LIVE_SOURCE = '86b029ae5bddd5d4956497d8b32b2c92b8eec521'
_LIVE_PROOF = '9030da131741eca9dbb86ad977ad5aec476095bb'
_LIVE_CANDIDATE = '254aa942559c5c04efd79e2a1e0dbac8bda69b04'
_LIVE_BOUNDARY = '307e83bd20f19cb473323dbef003d2abd518fcf4'


def _live_require(condition):
    if not condition:
        raise ValueError('AUTHENTICATED_CONTEXT_UNAVAILABLE')


def _live_source_bytes(path, expected):
    _live_require(path.is_file() and not path.is_symlink()
        and 0 < path.stat().st_size <= 128 * 1024)
    raw = path.read_bytes()
    _live_require(0 < len(raw) <= 128 * 1024)
    digest = _live_hashlib.sha1(
        b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    _live_require(digest == expected)
    return raw


def _live_module(path, expected, name):
    raw = _live_source_bytes(path, expected)
    module = _LiveModule(name)
    module.__file__ = str(path.resolve())
    module.__package__ = ''
    # Execute exactly the checked source bytes, not a pre-existing bytecode cache.
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    return module


def _live_git_head(folder):
    return _live_subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=folder,
        timeout=10, stderr=_live_subprocess.DEVNULL).decode().strip()


def _live_clean(folder, paths):
    _live_subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', *paths],
        cwd=folder, check=True, timeout=10,
        stdout=_live_subprocess.DEVNULL, stderr=_live_subprocess.DEVNULL)


def _live_first_parent(folder, commit):
    # checkout is shallow; raw commit headers still bind the reviewed first parent.
    size_raw = _live_subprocess.check_output(['git', 'cat-file', '-s', commit], cwd=folder,
        timeout=10, stderr=_live_subprocess.DEVNULL)
    _live_require(_live_re.fullmatch(rb'[1-9][0-9]{0,5}\n?', size_raw) is not None)
    size = int(size_raw)
    _live_require(0 < size <= 64 * 1024)
    raw = _live_subprocess.check_output(['git', 'cat-file', '-p', commit], cwd=folder,
        timeout=10, stderr=_live_subprocess.DEVNULL)
    _live_require(len(raw) == size and b'\0' not in raw and b'\r' not in raw)
    header, separator, _ = raw.partition(b'\n\n')
    _live_require(bool(separator))
    lines = header.split(b'\n')
    _live_require(bool(lines) and _live_re.fullmatch(rb'tree [a-f0-9]{40}', lines[0]) is not None)
    parents = []
    for line in lines[1:]:
        if line.startswith(b'parent '):
            _live_require(_live_re.fullmatch(rb'parent [a-f0-9]{40}', line) is not None)
            parents.append(line[7:].decode('ascii'))
    _live_require(len(parents) == 2 and parents[0] != parents[1])
    return parents[0]


def _load_repair_context():
    root = _LivePath.cwd().resolve()
    workspace_text = _live_os.environ.get('GITHUB_WORKSPACE')
    main_sha = _live_os.environ.get('GITHUB_SHA')
    _live_require(type(workspace_text) is str and bool(workspace_text)
        and _LivePath(workspace_text).is_absolute()
        and root.name == 'owner-source'
        and root.parent == _LivePath(workspace_text).resolve()
        and _LivePath(__file__).resolve().parent.parent == root.parent
        and type(main_sha) is str
        and _live_re.fullmatch(r'[a-f0-9]{40}', main_sha) is not None)
    main = root.parent
    _live_require(_live_git_head(main) == main_sha
        and _live_first_parent(main, main_sha) == _LIVE_EXPECTED_MAIN_PARENT
        and _live_git_head(root) == _LIVE_SOURCE)
    _live_clean(main, [
        'scripts/boat_rejection_anchor_repair.py',
        'scripts/boat_saved_rejection_anchor_audit.py',
        'scripts/boat_rejection_anchor_restoration.py',
        'scripts/boat_saved_reason_binding_audit.py',
    ])
    _live_clean(root, ['race_ai', 'scripts', 'audit/state/boat-saved-view-input.json'])
    _live_source_bytes(main / 'scripts/boat_saved_reason_binding_audit.py', _LIVE_BOUNDARY)
    proof = _live_module(main / 'scripts/boat_saved_rejection_anchor_audit.py',
        _LIVE_PROOF, '_live_existing_anchor_proof')
    candidate = _live_module(main / 'scripts/boat_rejection_anchor_restoration.py',
        _LIVE_CANDIDATE, '_live_existing_anchor_candidate')
    pins = (
        ('race_ai/boat_saved_model_view.py', 'e6db8d720aa151940e01f377831a5884eb4b2ba9'),
        ('race_ai/saved_view_feed.py', '9bb3bf0d1e48c9b3e3ba8e42030d5a05b681f900'),
        ('race_ai/saved_view_history.py', '3587debeeb4024dc768cac69f1a8aca9014d6f3e'),
        ('race_ai/racer_daily_handoff.py', '497c1a6c00bdf6d9512a174f6c4b7b2f914c3f47'),
        ('scripts/boat_saved_view_feed.py', '87f4f374fab19d9e45043116040dbfecd35bf8af'),
    )
    for relative, expected in pins:
        _live_source_bytes(root / relative, expected)
    import race_ai
    _live_require(_LivePath(race_ai.__file__).resolve() == root / 'race_ai/__init__.py')
    for folder, expected in (
            ('pr64-reference', '761247bee0209e37b1af6b8885e92cad3e9260a5'),
            ('pr72-reference', '7a432e5acc4d3495a0e82bd79726929e2f8085fe')):
        package = root / folder / 'race_ai'
        _live_require(package.is_dir() and not package.is_symlink()
            and _live_git_head(package.parent) == expected)
        _live_clean(package.parent, ['race_ai'])
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
        _live_require(_LivePath(module.__file__).resolve() == root / relative)
    _live_require(_DailyFilteredFetch.__module__ == 'race_ai.racer_daily_handoff')

    config_path = root / 'audit/state/boat-saved-view-input.json'
    _live_require(config_path.is_file() and not config_path.is_symlink()
        and 0 < config_path.stat().st_size <= 8192)
    config = publisher._json(config_path.read_bytes(), 8192)
    _live_require(type(config) is dict and set(config) == {
        'schema', 'bootstrap', 'bootstrap_sha256', 'catchup_artifact_id', 'catchup_sha256'}
        and config.get('schema') == 'RACE_AI_SAVED_VIEW_INPUT_V1'
        and type(config.get('bootstrap')) is str)
    raw = _live_base64.b64decode(config['bootstrap'], validate=True)
    _live_require(0 < len(raw) <= 4096
        and _live_hashlib.sha256(raw).hexdigest() == config['bootstrap_sha256'])
    publisher.git_auth()
    bootstrap = feed.open_bootstrap(raw)

    class ExistingFilteredWriter(_DailyFilteredFetch, feed.FeedRepository):
        pass

    repository = ExistingFilteredWriter(root)
    _live_require(repository.ref == feed.REF == 'state/boat-saved-view')
    parent = repository.head()
    proof._io_commit(parent)  # Missing state is HOLD; never seed or reset.
    budget = proof.ReadBudget()
    current = proof._read_verified_snapshot(repository, bootstrap, parent,
        feed=feed, guard=guard, budget=budget)
    older_chain = ()
    if current._header.get('schema') == 'RACE_AI_SAVED_WEB_HISTORY_V5':
        first_decision = proof.match_rejection_anchor_proofs(
            current, older_chain, guard=guard).public_summary()
        if (first_decision['status'] == 'HOLD'
                and first_decision['reason'] == 'ACTIVE_PROOF_MISSING'):
            day = current._view.get('event_date_jst')
            guard._day(day)
            predecessor = proof._find_predecessor_commit(repository, current,
                feed=feed, budget=budget)
            first = proof._read_verified_snapshot(repository, bootstrap, predecessor,
                feed=feed, guard=guard, budget=budget, day=day)
            older_chain = proof._extend_authenticated_chain(
                repository, bootstrap, current, (first,),
                feed=feed, guard=guard, budget=budget)
    # The orchestrator recomputes the complete proof using this exact module
    # instance, then invokes only the unchanged F.publish_view CAS API.
    return dict(proof=proof, candidate=candidate, guard=guard, feed=feed,
        repository=repository, bootstrap=bootstrap, current=current,
        older_chain=older_chain)


if __name__ == '__main__':
    raise SystemExit(main())
