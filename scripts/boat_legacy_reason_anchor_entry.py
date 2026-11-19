"""Install the fixed publication guard before one existing legacy collector.

Only verified public source and checkout metadata are read here. Existing
collector readers, parsers, credentials, arguments and source budgets remain
owned by the pinned legacy runtime.
"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import sys
import types


ALLOWED_MODULES = frozenset(('scripts.racer_intraday_refresh',))
_ADAPTER_BLOB_SHA = 'b438b6ec63b5f8048755081ba1ce074a2d7a0823'
_GUARD_BLOB_SHA = 'e6db8d720aa151940e01f377831a5884eb4b2ba9'
_LEGACY_FEED_BLOBS = frozenset((
    'ffb39325d9d045b962e379e53be4577fc014bd20',
    '3295add3abdacb88ee23e38875c6af47e8f33979',
))
_HOLD_REASON = 'LEGACY_REASON_ANCHOR_ENTRY_HOLD'
_MAX_SOURCE_BYTES = 256 * 1024
_SOURCE_MODULES = {}


class _SilentPreparation:
    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def isatty(self):
        return False


def _require(condition):
    if not condition:
        raise ValueError(_HOLD_REASON)


def _git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


def _pinned_source(path, allowed):
    _require(not path.is_symlink() and path.is_file()
        and 0 < path.stat().st_size <= _MAX_SOURCE_BYTES)
    raw = path.read_bytes()
    _require(0 < len(raw) <= _MAX_SOURCE_BYTES and _git_blob(raw) in allowed)
    return raw


def _checked_layout():
    workspace_text = os.environ.get('GITHUB_WORKSPACE')
    expected_head = os.environ.get('GITHUB_SHA')
    _require(type(workspace_text) is str and bool(workspace_text)
        and Path(workspace_text).is_absolute()
        and type(expected_head) is str and re.fullmatch('[a-f0-9]{40}', expected_head))
    workspace = Path(workspace_text).resolve()
    safety = (workspace / 'legacy-publish-safety').resolve()
    entry = Path(__file__).resolve()
    _require(workspace.is_dir() and safety.parent == workspace
        and entry == safety / 'scripts/boat_legacy_reason_anchor_entry.py'
        and entry.is_file())
    head_file = safety / '.git/HEAD'
    _require(not head_file.is_symlink() and head_file.is_file()
        and 0 < head_file.stat().st_size <= 128)
    actual_head = head_file.read_bytes().decode('ascii').strip()
    _require(re.fullmatch('[a-f0-9]{40}', actual_head) and actual_head == expected_head)
    runtime = Path.cwd().resolve()
    _require((runtime == workspace or workspace in runtime.parents)
        and runtime != safety and safety not in runtime.parents)
    feed_path = runtime / 'race_ai/saved_view_feed.py'
    adapter_path = safety / 'scripts/boat_legacy_reason_anchor_guard.py'
    guard_path = workspace / 'reason-binding-source/race_ai/boat_saved_model_view.py'
    # Read and check every source before executing any of these sources.
    feed_raw = _pinned_source(feed_path, _LEGACY_FEED_BLOBS)
    adapter_raw = _pinned_source(adapter_path, (_ADAPTER_BLOB_SHA,))
    guard_raw = _pinned_source(guard_path, (_GUARD_BLOB_SHA,))
    return runtime, feed_path, adapter_path, adapter_raw, guard_path, guard_raw, feed_raw


def _source_module(path, raw, *, guard=False):
    digest = _git_blob(raw)
    key = (str(path.resolve()), digest)
    if key in _SOURCE_MODULES:
        return _SOURCE_MODULES[key]
    name = ('race_ai._legacy_reason_anchor_current_' if guard
            else '_legacy_reason_anchor_adapter_') + digest
    module = types.ModuleType(name)
    module.__file__ = str(path.resolve())
    module.__package__ = 'race_ai' if guard else ''
    # Execute the exact checked bytes, without accepting a bytecode-cache file.
    exec(compile(raw, module.__file__, 'exec'), module.__dict__)
    _SOURCE_MODULES[key] = module
    return module


def _actual_legacy_feed(runtime, feed_path):
    root = str(runtime)
    if root not in sys.path:
        sys.path.insert(0, root)
    package = importlib.import_module('race_ai')
    _require(type(getattr(package, '__file__', None)) is str
        and Path(package.__file__).resolve() == runtime / 'race_ai/__init__.py')
    feed = importlib.import_module('race_ai.saved_view_feed')
    _require(type(getattr(feed, '__file__', None)) is str
        and Path(feed.__file__).resolve() == feed_path.resolve())
    # A cached module does not excuse a changed on-disk source.
    _pinned_source(feed_path, _LEGACY_FEED_BLOBS)
    return feed


def _prepare_legacy_feed():
    runtime, feed_path, adapter_path, adapter_raw, guard_path, guard_raw, _ = _checked_layout()
    feed = _actual_legacy_feed(runtime, feed_path)
    guard = _source_module(guard_path, guard_raw, guard=True)
    adapter = _source_module(adapter_path, adapter_raw)
    _require(callable(getattr(adapter, 'install_guard', None)))
    installed = adapter.install_guard(feed, guard=guard)
    _require(installed is feed)
    return feed


def prepare_legacy_feed():
    """Return the same legacy feed with only its publication checks installed."""
    try:
        with redirect_stdout(_SilentPreparation()), redirect_stderr(_SilentPreparation()):
            return _prepare_legacy_feed()
    except (Exception, SystemExit):
        pass
    # Raise outside the handler so no private loader/installer error is chained.
    raise ValueError(_HOLD_REASON) from None


def _target_origin(module, runtime):
    # Only the existing legacy scripts package may supply the whitelisted CLI.
    package = sys.modules.get('scripts')
    if package is not None:
        path = getattr(package, '__file__', None)
        if path is not None:
            _require(type(path) is str and Path(path).resolve() == runtime / 'scripts/__init__.py')
        else:
            paths = getattr(package, '__path__', ())
            _require(bool(paths) and all(Path(value).resolve() == runtime / 'scripts' for value in paths))
    spec = importlib.util.find_spec(module)
    _require(spec is not None and type(spec.origin) is str
        and Path(spec.origin).resolve() == runtime / 'scripts/racer_intraday_refresh.py')


def _safe_hold():
    print(json.dumps(dict(status='HOLD', reason=_HOLD_REASON), sort_keys=True))
    return 2


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    original_argv = sys.argv
    try:
        _require(type(arguments) in (list, tuple) and bool(arguments)
            and all(type(value) is str and '\0' not in value for value in arguments)
            and arguments[0] in ALLOWED_MODULES)
        module, target_argv = arguments[0], list(arguments[1:])
        prepare_legacy_feed()
        runtime = Path.cwd().resolve()
        _target_origin(module, runtime)
        sys.argv = [module, *target_argv]
        try:
            runpy.run_module(module, run_name='__main__', alter_sys=True)
        except SystemExit as stopped:
            if stopped.code is None:
                return 0
            if type(stopped.code) in (int, bool):
                return int(stopped.code)
            return _safe_hold()
        return 0
    except Exception:
        return _safe_hold()
    finally:
        sys.argv = original_argv


if __name__ == '__main__':
    raise SystemExit(main())
