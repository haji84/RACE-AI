"""Read-only counts for reason-sidecar bindings in one authenticated AES base.

The supplied pinned guard remains the authority for every binding rejection.
This module returns fixed metadata and counts without repairing any evidence.
"""

SCHEMA = 'RACE_AI_SAVED_REASON_BINDING_COUNTS_V1'
_BINDING_REASON = 'SAVED_MODEL_VIEW_RESULT_REASON_VARIANT_BINDING'
_COUNTERS = (
    'active_count', 'history_count', 'missing_active_anchor',
    'invalid_active_reason_metadata', 'invalid_history_reason_metadata',
    'source_sha_absent_active', 'source_sha_absent_history', 'source_sha_different',
    'non_reason_body_mismatch', 'clock_text_mismatch',
    'compared_active_history_pairs', 'other_guard_failures',
)
_SIDES = (
    ('observation', 'result_observations', 'saved_result_observation_reason_variants', False),
    ('rejection', 'result_observation_rejections', 'saved_result_rejection_reason_variants', True),
)


def _need_shape(condition):
    if not condition:
        raise ValueError('INPUT_OR_GUARD_INVALID')


def _empty_counts():
    return {name: 0 for name in _COUNTERS}


def _base_report(status, counts):
    return dict(schema=SCHEMA, origin='AES_BASE', status=status, counts=counts,
        originals_changed=False, observations_reconciled=0, source_requests=0,
        publication_performed=False, forecast_generated=False, broader_goals_proven=False)


def _identity(item, row, guard, rejection):
    _need_shape(type(item) is dict)
    captured = guard._clock(item.get('captured_at'))
    source = item.get('source_sha256')
    if source is not None:
        guard._sha(source)
    if not rejection:
        _need_shape(item.get('race_id') == row['race_id'])
    return (captured, source) if rejection else captured


def _count_side(row, field, history_field, guard, rejection):
    values = row.get(field, [])
    history = row.get(history_field, [])
    _need_shape(type(values) is list and len(values) <= 10000
        and type(history) is list and len(history) <= 10000)
    counts = _empty_counts()
    counts['active_count'] = len(values)
    counts['history_count'] = len(history)
    active = {}
    sources_by_capture = {}
    for item in values:
        key = _identity(item, row, guard, rejection)
        active.setdefault(key, item)
        captured = key[0] if rejection else key
        source = item.get('source_sha256')
        if source is None:
            counts['source_sha_absent_active'] += 1
        else:
            sources_by_capture.setdefault(captured, set()).add(source)
        if not guard._reason_metadata(item, rejection=rejection):
            counts['invalid_active_reason_metadata'] += 1
    for item in history:
        key = _identity(item, row, guard, rejection)
        source = item.get('source_sha256')
        if source is None:
            counts['source_sha_absent_history'] += 1
        if not guard._reason_metadata(item, rejection=rejection):
            counts['invalid_history_reason_metadata'] += 1
        if key not in active:
            counts['missing_active_anchor'] += 1
            if rejection and source is not None:
                # Count a present same-instant source disagreement only.
                # No orphan body is selected, reconstructed or compared.
                known = sources_by_capture.get(key[0], set())
                if any(previous != source for previous in known):
                    counts['source_sha_different'] += 1
            continue
        previous = active[key]
        counts['compared_active_history_pairs'] += 1
        previous_source = previous.get('source_sha256')
        if previous_source is not None and source is not None and previous_source != source:
            counts['source_sha_different'] += 1
        previous_body = {name: value for name, value in previous.items() if name != 'reason'}
        history_body = {name: value for name, value in item.items() if name != 'reason'}
        if guard._wire(previous_body) != guard._wire(history_body):
            counts['non_reason_body_mismatch'] += 1
        if previous.get('captured_at') != item.get('captured_at'):
            # An exact identity match already establishes equal instants.
            counts['clock_text_mismatch'] += 1
    return counts


def diagnose_view(view, *, guard, origin='AES_BASE'):
    """Audit all rows without changing inputs or weakening the supplied guard."""
    try:
        _need_shape(type(origin) is str and origin == 'AES_BASE')
        _need_shape(type(view) is dict and view.get('schema') == 'RACE_AI_PRIVATE_CYCLE_VIEW_V1'
            and type(view.get('records')) is list and len(view['records']) <= 10000)
        guard._tree(view)
        _need_shape(len(guard._wire(view).encode('utf-8')) <= guard.MAX_BYTES)
        counts = {name: _empty_counts() for name, _, _, _ in _SIDES}
        found = False
        races = set()
        for row in view['records']:
            _need_shape(type(row) is dict and type(row.get('race_id')) is str
                and 0 < len(row['race_id']) <= 250 and row['race_id'] not in races)
            races.add(row['race_id'])
            for name, field, history_field, rejection in _SIDES:
                try:
                    guard._observations([row], field, rejection=rejection)
                except guard.SavedModelViewError as error:
                    if getattr(error, 'reason_code', None) != _BINDING_REASON:
                        raise
                    found = True
                local = _count_side(row, field, history_field, guard, rejection)
                for counter in _COUNTERS:
                    counts[name][counter] += local[counter]
        status = 'BINDING_INCONSISTENCY_FOUND' if found else 'NO_BINDING_INCONSISTENCY_IN_THIS_VIEW'
        return _base_report(status, counts)
    except Exception:
        report = _base_report('HOLD', None)
        report['reason'] = 'INPUT_OR_GUARD_INVALID'
        return report


# The private reader is available only to the existing trusted main Actions job.
# No private object, source value, credential or exception is a report field.
import base64
from collections.abc import Mapping
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType

_IO_PREFIX = 'boat-owner-release: single-real-session-20261111'
_IO_SOURCE = '86b029ae5bddd5d4956497d8b32b2c92b8eec521'
_IO_GUARD_BLOB = 'e6db8d720aa151940e01f377831a5884eb4b2ba9'
_IO_FEED_BLOB = '9bb3bf0d1e48c9b3e3ba8e42030d5a05b681f900'
_IO_FLAGS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    publication_performed=False, forecast_generated=False, broader_goals_proven=False)


def _io_hold(reason, *, authenticated=False, metadata=None):
    report = dict(schema=SCHEMA, origin='AES_BASE', status='HOLD', reason=reason,
        counts=None, authenticated_base=authenticated, **_IO_FLAGS)
    if authenticated and metadata is not None:
        report.update(metadata)
    return report


def _io_trusted(environment, event):
    try:
        if not isinstance(environment, Mapping) or type(event) is not dict:
            return False
        head = environment.get('GITHUB_SHA')
        repo = event.get('repository')
        commit = event.get('head_commit')
        return bool(type(head) is str and re.fullmatch(r'[a-f0-9]{40}', head)
            and environment.get('GITHUB_ACTIONS') == 'true'
            and environment.get('GITHUB_EVENT_NAME') == 'push'
            and environment.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI'
            and environment.get('GITHUB_REPOSITORY_ID') == '1416489937'
            and environment.get('GITHUB_REF') == 'refs/heads/main'
            and environment.get('GITHUB_WORKFLOW_REF') ==
                'haji84/RACE-AI/.github/workflows/boat-owner-national-p1-matrix.yml@refs/heads/main'
            and type(repo) is dict and type(repo.get('id')) is int
            and repo['id'] == 1416489937 and repo.get('full_name') == 'haji84/RACE-AI'
            and repo.get('private') is False and event.get('ref') == 'refs/heads/main'
            and event.get('after') == head and type(commit) is dict
            and commit.get('id') == head and type(commit.get('message')) is str
            and commit['message'].startswith(_IO_PREFIX))
    except Exception:
        return False


def _io_safe_diagnostic(result):
    if type(result) is not dict or result.get('schema') != SCHEMA or result.get('origin') != 'AES_BASE':
        raise ValueError('DIAGNOSTIC_REPORT_INVALID')
    if any(type(result.get(name)) is not type(value) or result.get(name) != value
           for name, value in _IO_FLAGS.items()):
        raise ValueError('DIAGNOSTIC_REPORT_INVALID')
    status = result.get('status')
    if status == 'HOLD':
        if result.get('counts') is not None or result.get('reason') != 'INPUT_OR_GUARD_INVALID':
            raise ValueError('DIAGNOSTIC_REPORT_INVALID')
        return dict(schema=SCHEMA, origin='AES_BASE', status=status,
            reason='INPUT_OR_GUARD_INVALID', counts=None, **_IO_FLAGS)
    if status not in ('NO_BINDING_INCONSISTENCY_IN_THIS_VIEW', 'BINDING_INCONSISTENCY_FOUND'):
        raise ValueError('DIAGNOSTIC_REPORT_INVALID')
    source = result.get('counts')
    if type(source) is not dict or set(source) != {'observation', 'rejection'}:
        raise ValueError('DIAGNOSTIC_REPORT_INVALID')
    counts = {}
    for side in ('observation', 'rejection'):
        values = source[side]
        if type(values) is not dict or set(values) != set(_COUNTERS):
            raise ValueError('DIAGNOSTIC_REPORT_INVALID')
        if any(type(values[name]) is not int or values[name] < 0 for name in _COUNTERS):
            raise ValueError('DIAGNOSTIC_REPORT_INVALID')
        counts[side] = {name: values[name] for name in _COUNTERS}
    return dict(schema=SCHEMA, origin='AES_BASE', status=status, counts=counts, **_IO_FLAGS)


def run_audit(environment, event, *, load_base):
    if not _io_trusted(environment, event):
        return _io_hold('TRUSTED_MAIN_REQUIRED')
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            base = load_base()
        if (type(base) is not dict or type(base.get('generation')) is not int
                or not 1 <= base['generation'] <= 999999
                or type(base.get('snapshot_sha')) is not str
                or re.fullmatch(r'[a-f0-9]{40}', base['snapshot_sha']) is None
                or type(base.get('view')) is not dict
                or not isinstance(base.get('guard'), ModuleType)):
            raise ValueError('AUTHENTICATED_BASE_UNAVAILABLE')
        metadata = dict(generation=base['generation'], snapshot_sha=base['snapshot_sha'])
    except Exception:
        return _io_hold('AUTHENTICATED_BASE_UNAVAILABLE')
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = diagnose_view(base['view'], guard=base['guard'], origin='AES_BASE')
        report = _io_safe_diagnostic(result)
        report.update(authenticated_base=True, **metadata)
        return report
    except Exception:
        return _io_hold('INPUT_OR_GUARD_INVALID', authenticated=True, metadata=metadata)


def _io_source_blob(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError('PINNED_READER_REQUIRED')
    raw = path.read_bytes()
    if not 0 < len(raw) <= 128 * 1024:
        raise ValueError('PINNED_READER_REQUIRED')
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual != expected:
        raise ValueError('PINNED_READER_REQUIRED')


def _load_authenticated_base():
    # The current push audit already selects M2/86 for its existing read-only
    # source checkout. Neither the target file nor that checkout is changed.
    root = Path.cwd().resolve()
    workspace = os.environ.get('GITHUB_WORKSPACE')
    if (type(workspace) is not str or not workspace
            or root.name != 'owner-source'
            or root.parent != Path(workspace).resolve()):
        raise ValueError('PINNED_READER_REQUIRED')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
        timeout=10, stderr=subprocess.DEVNULL).decode().strip()
    if actual != _IO_SOURCE:
        raise ValueError('PINNED_READER_REQUIRED')
    subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'race_ai', 'scripts',
        'audit/state/boat-saved-view-input.json'], cwd=root, check=True, timeout=10,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _io_source_blob(root / 'race_ai/boat_saved_model_view.py', _IO_GUARD_BLOB)
    _io_source_blob(root / 'race_ai/saved_view_feed.py', _IO_FEED_BLOB)
    import race_ai
    if Path(race_ai.__file__).resolve() != root / 'race_ai/__init__.py':
        raise ValueError('PINNED_READER_REQUIRED')
    for folder, expected in (('pr64-reference', '761247bee0209e37b1af6b8885e92cad3e9260a5'),
            ('pr72-reference', '7a432e5acc4d3495a0e82bd79726929e2f8085fe')):
        package = root / folder / 'race_ai'
        if not package.is_dir() or package.is_symlink():
            raise ValueError('PINNED_READER_REQUIRED')
        actual = subprocess.check_output(['git', '-C', str(package.parent), 'rev-parse', 'HEAD'],
            timeout=10, stderr=subprocess.DEVNULL).decode().strip()
        if actual != expected:
            raise ValueError('PINNED_READER_REQUIRED')
        if str(package) not in race_ai.__path__:
            race_ai.__path__.append(str(package))
    from race_ai import boat_saved_model_view as guard
    from race_ai import saved_view_feed as feed
    from scripts import boat_saved_view_feed as publisher
    for module, relative in ((guard, 'race_ai/boat_saved_model_view.py'),
            (feed, 'race_ai/saved_view_feed.py'), (publisher, 'scripts/boat_saved_view_feed.py')):
        if Path(module.__file__).resolve() != root / relative:
            raise ValueError('PINNED_READER_REQUIRED')
    config_path = root / 'audit/state/boat-saved-view-input.json'
    if config_path.is_symlink() or not config_path.is_file() or not 0 < config_path.stat().st_size <= 8192:
        raise ValueError('PINNED_READER_REQUIRED')
    config = publisher._json(config_path.read_bytes(), 8192)
    if (type(config) is not dict
            or set(config) != {'schema', 'bootstrap', 'bootstrap_sha256', 'catchup_artifact_id', 'catchup_sha256'}
            or config['schema'] != 'RACE_AI_SAVED_VIEW_INPUT_V1'
            or type(config.get('bootstrap')) is not str):
        raise ValueError('PINNED_READER_REQUIRED')
    raw = base64.b64decode(config['bootstrap'], validate=True)
    if hashlib.sha256(raw).hexdigest() != config['bootstrap_sha256']:
        raise ValueError('PINNED_READER_REQUIRED')
    publisher.git_auth()  # Existing process-scoped, repository-only GH credential.
    bootstrap = feed.open_bootstrap(raw)  # Existing Actions-only recipient key.

    class ReadOnlyFeed(feed.FeedRepository):
        def commit(self, *args, **kwargs):
            raise ValueError('READ_ONLY_DIAGNOSTIC')
        def commit_snapshot(self, *args, **kwargs):
            raise ValueError('READ_ONLY_DIAGNOSTIC')
        def push(self, *args, **kwargs):
            raise ValueError('READ_ONLY_DIAGNOSTIC')

    repository = ReadOnlyFeed(root)
    parent, _, generation, view = feed.current_view(repository, bootstrap)
    return dict(generation=generation, snapshot_sha=parent, view=view, guard=guard)


def _io_unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('EVENT_INVALID')
        result[name] = value
    return result


def _io_nonfinite(value):
    raise ValueError('EVENT_INVALID')


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        report = _io_hold('CLI_ARGUMENTS_REJECTED')
    else:
        try:
            name = os.environ.get('GITHUB_EVENT_PATH')
            if type(name) is not str or not name:
                raise ValueError('EVENT_INVALID')
            path = Path(name)
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 1024 * 1024:
                raise ValueError('EVENT_INVALID')
            raw = path.read_bytes()
            if not 0 < len(raw) <= 1024 * 1024:
                raise ValueError('EVENT_INVALID')
            event = json.loads(raw.decode('utf-8'), object_pairs_hook=_io_unique,
                parse_constant=_io_nonfinite)
            if type(event) is not dict:
                raise ValueError('EVENT_INVALID')
        except Exception:
            report = _io_hold('TRUSTED_MAIN_REQUIRED')
        else:
            report = run_audit(os.environ, event, load_base=_load_authenticated_base)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report['status'] == 'HOLD' else 0


if __name__ == '__main__':
    raise SystemExit(main())
