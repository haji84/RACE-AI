"""Offline invocation boundary tests; no legacy collector, key or provider executes."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.request

from scripts import boat_legacy_reason_anchor_entry as A


ROOT = Path(__file__).resolve().parents[1]
MODULE = 'scripts.racer_intraday_refresh'
HEAD = '1' * 40
GUARD_BLOB = 'e6db8d720aa151940e01f377831a5884eb4b2ba9'
LEGACY_BLOBS = frozenset((
    'ffb39325d9d045b962e379e53be4577fc014bd20',
    '3295add3abdacb88ee23e38875c6af47e8f33979',
))
SAFE_HOLD = dict(status='HOLD', reason='LEGACY_REASON_ANCHOR_ENTRY_HOLD')
FEED_SOURCE = """events = []
_installed_guard = None
source_get_cap = 12
parser = object()
scorer = object()
def ensure_append_only(previous, current):
    return current
def publish_view(*args, **kwargs):
    return {'legacy': True}
def current_view(*args, **kwargs):
    raise AssertionError('WRAPPER_MUST_NOT_READ_VIEW')
def open_bootstrap(*args, **kwargs):
    raise AssertionError('WRAPPER_MUST_NOT_READ_KEY')
def decrypt_view(*args, **kwargs):
    raise AssertionError('WRAPPER_MUST_NOT_DECRYPT')
class FeedRepository:
    pass
"""
ADAPTER_SOURCE = """def install_guard(feed, *, guard):
    if feed._installed_guard is guard:
        return feed
    original_ensure = feed.ensure_append_only
    original_publish = feed.publish_view
    def ensure(*args, **kwargs):
        return original_ensure(*args, **kwargs)
    def publish(*args, **kwargs):
        return original_publish(*args, **kwargs)
    feed.ensure_append_only = ensure
    feed.publish_view = publish
    feed._installed_guard = guard
    feed.events.append('installed')
    return feed
"""
TARGET_SOURCE = """import sys
from race_ai import saved_view_feed as F
if F._installed_guard is None:
    raise AssertionError('TARGET_IMPORTED_BEFORE_GUARD')
F.events.append(('target-import', list(sys.argv), __name__))
if __name__ == '__main__':
    F.events.append(('target-run', list(sys.argv)))
    raise SystemExit(7)
"""


def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()


class ObservedEnvironment(dict):
    allowed = {'GITHUB_WORKSPACE', 'GITHUB_SHA'}

    def get(self, key, default=None):
        if key not in self.allowed:
            raise AssertionError('WRAPPER_ENVIRONMENT_SCOPE')
        return super().get(key, default)

    def __getitem__(self, key):
        if key not in self.allowed:
            raise AssertionError('WRAPPER_ENVIRONMENT_SCOPE')
        return super().__getitem__(key)

    def __iter__(self):
        raise AssertionError('WRAPPER_MUST_NOT_ENUMERATE_ENVIRONMENT')

    def items(self):
        raise AssertionError('WRAPPER_MUST_NOT_ENUMERATE_ENVIRONMENT')

    def keys(self):
        raise AssertionError('WRAPPER_MUST_NOT_ENUMERATE_ENVIRONMENT')

    def values(self):
        raise AssertionError('WRAPPER_MUST_NOT_ENUMERATE_ENVIRONMENT')

    def copy(self):
        raise AssertionError('WRAPPER_MUST_NOT_COPY_ENVIRONMENT')


@contextmanager
def runtime_layout():
    raw_guard = (ROOT / 'reason-binding-source/race_ai/boat_saved_model_view.py').read_bytes()
    if blob(raw_guard) != GUARD_BLOB:
        raise AssertionError('PINNED_GUARD_FIXTURE_REQUIRED')
    saved_modules = {name: module for name, module in sys.modules.copy().items()
                     if name == 'race_ai' or name.startswith('race_ai.')
                     or name == 'scripts' or name.startswith('scripts.')}
    original_path, original_argv, original_cwd = list(sys.path), sys.argv, Path.cwd()
    with tempfile.TemporaryDirectory() as folder:
        workspace = Path(folder)
        safety = workspace / 'legacy-publish-safety'
        runtime = workspace / 'legacy-runtime'
        scripts = safety / 'scripts'
        scripts.mkdir(parents=True)
        (safety / '.git').mkdir()
        (safety / '.git/HEAD').write_text(HEAD + '\n')
        entry = scripts / 'boat_legacy_reason_anchor_entry.py'
        entry.write_text('# synthetic public entry location only\n')
        adapter = scripts / 'boat_legacy_reason_anchor_guard.py'
        adapter.write_text(ADAPTER_SOURCE)
        guard_file = workspace / 'reason-binding-source/race_ai/boat_saved_model_view.py'
        guard_file.parent.mkdir(parents=True)
        guard_file.write_bytes(raw_guard)
        (runtime / 'race_ai').mkdir(parents=True)
        (runtime / 'race_ai/__init__.py').write_text('')
        feed_file = runtime / 'race_ai/saved_view_feed.py'
        feed_file.write_text(FEED_SOURCE)
        (runtime / 'scripts').mkdir()
        (runtime / 'scripts/__init__.py').write_text('')
        target = runtime / 'scripts/racer_intraday_refresh.py'
        target.write_text(TARGET_SOURCE)
        for name in list(sys.modules):
            if name in saved_modules:
                sys.modules.pop(name)
        # Reproduce an absolute script invoked outside CWD: only safety/scripts
        # is first. The entry may add the old CWD, never the safety package root.
        sys.path[:] = [str(scripts)] + [value for value in original_path
            if value not in ('', str(ROOT), str(ROOT / 'scripts'))]
        os.chdir(runtime)
        environment = ObservedEnvironment(GITHUB_WORKSPACE=str(workspace), GITHUB_SHA=HEAD,
            RACE_AI_STATE_KEY='private-sentinel-owner-key', GH_TOKEN='private-sentinel-token',
            PRIVATE_SENTINEL='private-sentinel-environment')
        try:
            with patch.object(A, '__file__', str(entry)), \
                    patch.object(A, '_ADAPTER_BLOB_SHA', blob(adapter.read_bytes())), \
                    patch.object(A, '_LEGACY_FEED_BLOBS', frozenset((blob(feed_file.read_bytes()),))), \
                    patch.object(os, 'environ', environment), \
                    patch.object(socket, 'create_connection', side_effect=AssertionError('NO_NETWORK')), \
                    patch.object(urllib.request, 'urlopen', side_effect=AssertionError('NO_NETWORK')), \
                    patch.object(subprocess, 'run', side_effect=AssertionError('NO_PROCESS')):
                yield dict(workspace=workspace, safety=safety, runtime=runtime, entry=entry,
                    adapter=adapter, guard=guard_file, feed=feed_file, target=target,
                    environment=environment)
        finally:
            os.chdir(original_cwd)
            sys.path[:] = original_path
            sys.argv = original_argv
            for name in list(sys.modules):
                if name == 'race_ai' or name.startswith('race_ai.') or name == 'scripts' or name.startswith('scripts.'):
                    sys.modules.pop(name)
            sys.modules.update(saved_modules)


class LegacyReasonAnchorEntryTests(unittest.TestCase):
    def invoke(self, argv):
        original = list(argv)
        original_sys_argv = sys.argv
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = A.main(argv)
        self.assertEqual(argv, original)
        self.assertIs(sys.argv, original_sys_argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def hold(self, argv):
        code, stdout, stderr = self.invoke(argv)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout), SAFE_HOLD)
        self.assertEqual(stderr, '')
        self.assertNotIn('sentinel', stdout)
        return stdout

    def test_fixed_policy_allows_only_actual_collector_and_two_existing_feed_blobs(self):
        self.assertEqual(frozenset(A.ALLOWED_MODULES), frozenset((MODULE,)))
        self.assertEqual(frozenset(A._LEGACY_FEED_BLOBS), LEGACY_BLOBS)
        self.assertEqual(A._GUARD_BLOB_SHA, GUARD_BLOB)
        self.assertEqual(A._ADAPTER_BLOB_SHA, 'b438b6ec63b5f8048755081ba1ce074a2d7a0823')

    def test_absolute_script_outside_cwd_installs_before_target_import_and_preserves_argv(self):
        with runtime_layout() as layout:
            args = ['--private-dir', 'private-sentinel/path with spaces',
                    '--verify-public', '--sync-results', '--sync-beforeinfo', '--initialize']
            code, stdout, stderr = self.invoke([MODULE, *args])
            self.assertEqual(code, 7)
            self.assertEqual((stdout, stderr), ('', ''))
            feed = sys.modules['race_ai.saved_view_feed']
            self.assertEqual(feed.events[0], 'installed')
            self.assertEqual(feed.events[1][0], 'target-import')
            self.assertEqual(feed.events[1][1][1:], args)
            self.assertEqual(Path(feed.events[1][1][0]).resolve(), layout['target'].resolve())
            self.assertEqual(feed.events[1][2], '__main__')
            self.assertEqual(feed.events[2], ('target-run', feed.events[1][1]))
            self.assertEqual(Path(feed.__file__).resolve(), layout['feed'].resolve())
            self.assertNotIn(str(layout['safety']), sys.path)
            self.assertEqual(feed.source_get_cap, 12)

    def test_inline_prepare_returns_identical_old_feed_and_preserves_every_reader(self):
        with runtime_layout() as layout:
            sys.path.insert(0, str(layout['runtime']))
            feed = importlib.import_module('race_ai.saved_view_feed')
            original = {name: getattr(feed, name) for name in
                ('current_view', 'open_bootstrap', 'decrypt_view', 'FeedRepository', 'parser', 'scorer')}
            original_ensure, original_publish = feed.ensure_append_only, feed.publish_view
            self.assertIs(A.prepare_legacy_feed(), feed)
            self.assertIsNot(feed.ensure_append_only, original_ensure)
            self.assertIsNot(feed.publish_view, original_publish)
            for name, value in original.items():
                self.assertIs(getattr(feed, name), value, name)
            self.assertEqual(feed.events, ['installed'])
            self.assertNotIn(str(layout['safety']), sys.path)

    def test_repeated_prepare_is_idempotent_and_rechecks_pinned_guard_bytes(self):
        with runtime_layout() as layout:
            first = A.prepare_legacy_feed()
            ensure, publish, guard = first.ensure_append_only, first.publish_view, first._installed_guard
            self.assertIs(A.prepare_legacy_feed(), first)
            self.assertIs(first.ensure_append_only, ensure)
            self.assertIs(first.publish_view, publish)
            self.assertIs(first._installed_guard, guard)
            self.assertEqual(first.events, ['installed'])
            layout['guard'].write_bytes(layout['guard'].read_bytes() + b'\n# private-sentinel-change\n')
            self.hold([MODULE, '--private-dir', 'private-sentinel'])

    def test_unapproved_module_and_missing_module_fail_before_runtime_import(self):
        with runtime_layout():
            for module in ('os', 'scripts.boat_saved_view_feed',
                           MODULE + '.private-sentinel', '', '--help'):
                with self.subTest(module=module):
                    self.hold([module, 'private-sentinel-argument'])
                    self.assertNotIn('race_ai.saved_view_feed', sys.modules)
            self.hold([])
            self.assertNotIn('race_ai.saved_view_feed', sys.modules)

    def test_wrong_or_cached_foreign_feed_path_is_rejected_before_install_or_target(self):
        with runtime_layout() as layout:
            sys.path.insert(0, str(layout['runtime']))
            package = importlib.import_module('race_ai')
            foreign = types.ModuleType('race_ai.saved_view_feed')
            foreign.__file__ = str(layout['workspace'] / 'private-sentinel/race_ai/saved_view_feed.py')
            foreign.events = []
            package.saved_view_feed = foreign
            sys.modules['race_ai.saved_view_feed'] = foreign
            self.hold([MODULE, '--sync-results'])
            self.assertEqual(foreign.events, [])

    def test_wrong_safety_head_or_location_never_runs_the_old_target(self):
        for mode in ('head', 'location'):
            with self.subTest(mode=mode), runtime_layout() as layout:
                if mode == 'head':
                    (layout['safety'] / '.git/HEAD').write_text('2'*40 + '\n')
                else:
                    layout['environment']['GITHUB_WORKSPACE'] = str(layout['workspace'] / 'private-sentinel-other')
                self.hold([MODULE, '--sync-results'])
                self.assertNotIn('race_ai.saved_view_feed', sys.modules)

    def test_all_three_source_byte_pins_are_checked_before_executing_changed_source(self):
        for kind in ('feed', 'guard', 'adapter'):
            with self.subTest(kind=kind), runtime_layout() as layout:
                marker = layout['workspace'] / 'private-sentinel-executed'
                prefix = "from pathlib import Path\nPath(%r).write_text('executed')\n" % str(marker)
                target = layout[kind]
                target.write_text(prefix + target.read_text())
                self.hold([MODULE, '--sync-results'])
                self.assertFalse(marker.exists())

    def test_target_exit_codes_are_preserved_and_private_exception_payloads_are_not_printed(self):
        for statement, expected in (
                ('raise SystemExit(0)', 0), ('raise SystemExit(3)', 3),
                ("raise SystemExit('private-sentinel-exit')", 2),
                ("raise RuntimeError('private-sentinel-error https://private-sentinel.invalid')", 2)):
            with self.subTest(expected=expected), runtime_layout() as layout:
                target = TARGET_SOURCE.split("if __name__ == '__main__':", 1)[0] + statement + '\n'
                layout['target'].write_text(target)
                code, stdout, stderr = self.invoke([MODULE, '--private-dir', 'private-sentinel'])
                self.assertEqual(code, expected)
                self.assertEqual(stderr, '')
                self.assertNotIn('sentinel', stdout)
                if expected == 2:
                    self.assertEqual(json.loads(stdout), SAFE_HOLD)
                else:
                    self.assertEqual(stdout, '')

    def test_no_wrapper_key_network_reader_parser_or_budget_access_and_safe_install_failure(self):
        with runtime_layout() as layout:
            # The guarded environment rejects key reads and enumeration. Fake
            # readers and the network/process traps reject accidental I/O.
            self.assertEqual(self.invoke([MODULE, '--replay-retained-results'])[0], 7)
            feed = sys.modules['race_ai.saved_view_feed']
            self.assertEqual(feed.source_get_cap, 12)
            self.assertEqual(feed.events[0], 'installed')
        with runtime_layout() as layout:
            poisoned = ADAPTER_SOURCE.replace("def install_guard(feed, *, guard):",
                "def install_guard(feed, *, guard):\n    raise RuntimeError('private-sentinel-install-error')")
            layout['adapter'].write_text(poisoned)
            with patch.object(A, '_ADAPTER_BLOB_SHA', blob(layout['adapter'].read_bytes())):
                self.hold([MODULE, '--sync-results'])
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(ValueError) as caught:
                        A.prepare_legacy_feed()
                self.assertEqual(str(caught.exception), 'LEGACY_REASON_ANCHOR_ENTRY_HOLD')
                self.assertIsNone(caught.exception.__cause__)
                if caught.exception.__context__ is not None:
                    self.assertTrue(caught.exception.__suppress_context__)
                self.assertEqual((stdout.getvalue(), stderr.getvalue()), ('', ''))


if __name__ == '__main__':
    unittest.main()
