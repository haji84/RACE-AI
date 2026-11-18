"""Synthetic fixed-pair reader boundaries; no owner key, source HTTP or live artifacts."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

try:
    S = importlib.import_module('scripts.boat_saved_rejection_anchor_audit')
except ModuleNotFoundError as error:
    if error.name != 'scripts.boat_saved_rejection_anchor_audit':
        raise
    S = None

ROOT = Path(__file__).resolve().parents[1]
HEAD = '1' * 40
CURRENT = '2' * 40
OLDER = '3' * 40
SCHEMA = 'RACE_AI_SAVED_REJECTION_ANCHOR_PROOF_V1'
PREFIX = 'boat-owner-release: single-real-session-20261111'
COUNTERS = (
    'snapshots_checked', 'current_active_rejections', 'retained_history_originals',
    'orphan_groups', 'proved_groups', 'older_active_bodies_checked',
    'planned_active_originals',
)
FLAGS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    publication_performed=False, forecast_generated=False, broader_goals_proven=False)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')


def load_guard():
    path = ROOT / 'reason-binding-source/race_ai/boat_saved_model_view.py'
    raw = path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual != 'e6db8d720aa151940e01f377831a5884eb4b2ba9':
        raise AssertionError('PINNED_OWNER_SOURCE_GUARD_REQUIRED')
    spec = importlib.util.spec_from_file_location('race_ai._anchor_reader_test_guard', path)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    return guard


def view():
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',
        dataset_status='SYNTHETIC_ONLY', event_date_jst='2030-04-01', records=[],
        private_payload='private-view-sentinel')


def header(generation, previous):
    return dict(schema='RACE_AI_SAVED_WEB_VIEW_V4', source_content_sha256='a' * 64,
        view_id='b' * 64, forecast_sha256='c' * 64,
        forecast_inventory_sha256='d' * 64, generation=generation,
        previous_cipher_sha256=previous)


def reader_feed(current_view=None):
    def bounded_json(raw, maximum):
        if type(raw) is not bytes or not 0 < len(raw) <= maximum:
            raise ValueError('INVENTED_JSON_BOUND')
        return json.loads(raw)
    return SimpleNamespace(current_view=current_view, _json=bounded_json,
        _header=lambda value: value, MAX_WIRE=12 * 1024 * 1024,
        REF='state/boat-saved-view',
        sha=lambda raw: hashlib.sha256(raw).hexdigest())


def receipt(value, generation, previous, snapshot, ciphertext):
    return S._verified_snapshot(value, header=header(generation, previous),
        manifest_cipher_sha256=hashlib.sha256(ciphertext).hexdigest(),
        snapshot_sha=snapshot, ciphertext=ciphertext)


def pair(guard):
    old_raw = b'private-older-cipher-sentinel'
    current_raw = b'private-current-cipher-sentinel'
    old = receipt(view(), 423, '0' * 64, OLDER, old_raw)
    current = receipt(view(), 424, hashlib.sha256(old_raw).hexdigest(), CURRENT, current_raw)
    return current, (old,), guard


def trusted_environment():
    return dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
        GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
        GITHUB_SHA=HEAD, GITHUB_REF='refs/heads/main',
        GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/'
            'boat-owner-national-p1-matrix.yml@refs/heads/main')


def trusted_event():
    return dict(ref='refs/heads/main', after=HEAD,
        repository=dict(id=1416489937, full_name='haji84/RACE-AI', private=False),
        head_commit=dict(id=HEAD, message=PREFIX + ' | private-event-sentinel'))


class PublicDecision:
    def __init__(self, summary):
        self.summary = summary

    def public_summary(self):
        return deepcopy(self.summary)


class FixedPairBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(S, 'fixed-pair rejection-anchor reader is missing')
        self.guard = load_guard()

    def assert_safe(self, report):
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], SCHEMA)
        self.assertIn(report['status'],
            ('ALL_ORPHAN_ANCHORS_PROVEN', 'NO_ORPHAN_ANCHORS', 'HOLD'))
        expected = {'schema', 'status', 'counts', 'snapshots', *FLAGS}
        if report['status'] == 'HOLD':
            expected.add('reason')
            self.assertRegex(report['reason'], r'^[A-Z][A-Z0-9_]{0,63}$')
            self.assertIsNone(report['counts'])
            self.assertEqual(report['snapshots'], [])
        else:
            self.assertEqual(set(report['counts']), set(COUNTERS))
            for value in report['counts'].values():
                self.assertIs(type(value), int)
                self.assertGreaterEqual(value, 0)
            self.assertIs(type(report['snapshots']), list)
            for snapshot in report['snapshots']:
                self.assertEqual(set(snapshot), {'snapshot_sha', 'cipher_sha256'})
                self.assertRegex(snapshot['snapshot_sha'], r'^[a-f0-9]{40}$')
                self.assertRegex(snapshot['cipher_sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(set(report), expected)
        for name, value in FLAGS.items():
            self.assertIs(type(report[name]), type(value))
            self.assertEqual(report[name], value)
        rendered = json.dumps(report, sort_keys=True, allow_nan=False)
        for private in ('private-', 'https://', 'Traceback', 'RACE_AI_STATE_KEY',
                        'private_payload', 'owner_key', 'records', 'guard'):
            self.assertNotIn(private, rendered)

    def run_pair(self, *, environment=None, event=None, load_pair=None):
        output, errors = io.StringIO(), io.StringIO()
        actual_pair = pair(self.guard)
        reader = load_pair if load_pair is not None else lambda: actual_pair
        with redirect_stdout(output), redirect_stderr(errors):
            report = S.run_audit(
                trusted_environment() if environment is None else environment,
                trusted_event() if event is None else event, load_pair=reader)
        self.assertEqual(output.getvalue() + errors.getvalue(), '')
        self.assert_safe(report)
        return report

    def test_trusted_pair_uses_real_matcher_without_changing_views(self):
        current_view, old_view = view(), view()
        before = deepcopy((current_view, old_view))
        old_raw, current_raw = b'older-invented-cipher', b'current-invented-cipher'
        old = receipt(old_view, 423, '0' * 64, OLDER, old_raw)
        current = receipt(current_view, 424, hashlib.sha256(old_raw).hexdigest(),
            CURRENT, current_raw)
        calls = []
        def reader():
            calls.append(())
            return current, (old,), self.guard
        report = self.run_pair(load_pair=reader)
        self.assertEqual(calls, [()])
        self.assertEqual(report['status'], 'NO_ORPHAN_ANCHORS')
        self.assertEqual(report['counts'], dict(snapshots_checked=2,
            current_active_rejections=0, retained_history_originals=0,
            orphan_groups=0, proved_groups=0, older_active_bodies_checked=0,
            planned_active_originals=0))
        self.assertEqual(report['snapshots'], [
            dict(snapshot_sha=CURRENT, cipher_sha256=hashlib.sha256(current_raw).hexdigest()),
            dict(snapshot_sha=OLDER, cipher_sha256=hashlib.sha256(old_raw).hexdigest())])
        self.assertEqual((current_view, old_view), before)

    def test_untrusted_context_cannot_open_the_private_pair_or_invoke_matcher(self):
        cases = []
        for name, bad in (
                ('GITHUB_ACTIONS', True), ('GITHUB_ACTIONS', 'false'),
                ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'workflow_run'),
                ('GITHUB_EVENT_NAME', 'workflow_dispatch'), ('GITHUB_REPOSITORY', 'foreign/repo'),
                ('GITHUB_REPOSITORY_ID', '7'), ('GITHUB_REPOSITORY_ID', 1416489937),
                ('GITHUB_REF', 'refs/heads/other'), ('GITHUB_SHA', 'A' * 40),
                ('GITHUB_WORKFLOW_REF', 'haji84/RACE-AI/.github/workflows/other.yml@refs/heads/main')):
            environment = trusted_environment(); environment[name] = bad
            cases.append((environment, trusted_event()))
        for name in ('GITHUB_ACTIONS', 'GITHUB_SHA', 'GITHUB_REPOSITORY_ID', 'GITHUB_WORKFLOW_REF'):
            environment = trusted_environment(); environment.pop(name)
            cases.append((environment, trusted_event()))
        for path, bad in (
                (('ref',), 'refs/heads/other'), (('after',), 'f' * 40),
                (('head_commit', 'id'), 'f' * 40),
                (('head_commit', 'message'), 'ordinary-private-message'),
                (('repository', 'id'), True), (('repository', 'private'), 0),
                (('repository', 'private'), True),
                (('repository', 'full_name'), 'foreign/repo')):
            event = trusted_event(); target = event
            for name in path[:-1]:
                target = target[name]
            target[path[-1]] = bad
            cases.append((trusted_environment(), event))
        cases.extend([({}, trusted_event()), (trusted_environment(), None)])
        for index, (environment, event) in enumerate(cases):
            calls = []
            def forbidden():
                calls.append('private-reader')
                raise AssertionError('private-reader-sentinel')
            with self.subTest(case=index), \
                    patch.object(S, 'match_rejection_anchor_proofs',
                        side_effect=AssertionError('private-matcher-sentinel')) as matcher:
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    report = S.run_audit(environment, event, load_pair=forbidden)
                self.assert_safe(report)
                self.assertEqual(report['status'], 'HOLD')
                self.assertEqual(calls, [])
                matcher.assert_not_called()
                self.assertEqual(output.getvalue() + errors.getvalue(), '')

    def test_reader_noise_and_exceptions_become_one_private_hold(self):
        for error in (ValueError('private-cipher-sentinel'),
                      RuntimeError('private-key-sentinel https://private.invalid/')):
            def reader():
                print('private-reader-stdout-sentinel')
                print('private-reader-stderr-sentinel', file=sys.stderr)
                raise error
            report = self.run_pair(load_pair=reader)
            self.assertEqual(report['status'], 'HOLD')

    def test_malformed_pair_contract_is_never_reported_as_a_proof(self):
        current, older, guard = pair(self.guard)
        cases = (None, [], [current, older, guard], (current, older),
            (None, older, guard), (current, list(older), guard),
            (current, older, object()))
        for value in cases:
            with self.subTest(shape=type(value).__name__):
                report = self.run_pair(load_pair=lambda: value)
                self.assertEqual(report['status'], 'HOLD')

    def test_matcher_noise_and_exception_cannot_escape_the_boundary(self):
        original = S.match_rejection_anchor_proofs
        def noisy(current, older, *, guard):
            print('private-matcher-stdout-sentinel')
            print('private-matcher-stderr-sentinel', file=sys.stderr)
            return original(current, older, guard=guard)
        with patch.object(S, 'match_rejection_anchor_proofs', side_effect=noisy):
            self.assertEqual(self.run_pair()['status'], 'NO_ORPHAN_ANCHORS')
        def broken(*args, **kwargs):
            print('private-matcher-stdout-sentinel')
            raise ValueError('private-matcher-error-sentinel')
        with patch.object(S, 'match_rejection_anchor_proofs', side_effect=broken):
            self.assertEqual(self.run_pair()['status'], 'HOLD')

    def test_public_summary_is_validated_instead_of_forwarding_arbitrary_fields(self):
        valid = dict(schema=SCHEMA, status='NO_ORPHAN_ANCHORS',
            counts=dict(snapshots_checked=2, current_active_rejections=0,
                retained_history_originals=0, orphan_groups=0, proved_groups=0,
                older_active_bodies_checked=0, planned_active_originals=0),
            snapshots=[], **FLAGS)
        cases = []
        for change in (dict(private_payload='private-report-sentinel'),
                dict(publication_performed=True), dict(source_requests=True),
                dict(status='private-status-sentinel'), dict(schema='private-schema-sentinel'),
                dict(snapshots=[dict(snapshot_sha='private-snapshot-sentinel', cipher_sha256='f' * 64)])):
            bad = deepcopy(valid); bad.update(change); cases.append(bad)
        for value in (-1, True, 'private-count-sentinel'):
            bad = deepcopy(valid); bad['counts']['proved_groups'] = value; cases.append(bad)
        bad = deepcopy(valid); bad['counts']['private-counter-sentinel'] = 1; cases.append(bad)
        bad = dict(valid, status='HOLD', counts=None, snapshots=[],
            reason='private-error-sentinel'); cases.append(bad)
        for index, summary in enumerate(cases):
            with self.subTest(case=index), patch.object(S, 'match_rejection_anchor_proofs',
                    return_value=PublicDecision(summary)):
                self.assertEqual(self.run_pair()['status'], 'HOLD')

    def test_cli_arguments_refuse_before_environment_event_or_private_reader(self):
        class LockedEnvironment(dict):
            def __init__(self):
                super().__init__(); self.reads = []
            def get(self, name, *args):
                self.reads.append(name); raise AssertionError('private-environment-sentinel')
            def __getitem__(self, name):
                self.reads.append(name); raise AssertionError('private-environment-sentinel')
            def __iter__(self):
                self.reads.append('iteration'); raise AssertionError('private-environment-sentinel')
        for argv in (['--day', '2030-04-01'], ['--snapshot-sha', CURRENT],
                     ['--owner-key', 'private-key-sentinel'], None):
            environment = LockedEnvironment(); output, errors = io.StringIO(), io.StringIO()
            with self.subTest(argv=bool(argv)), patch.object(S.os, 'environ', environment), \
                    patch.object(sys, 'argv', ['audit', '--private-cli-sentinel']), \
                    patch.object(S, '_load_authenticated_pair') as reader, \
                    patch.object(Path, 'read_bytes') as read_bytes, \
                    redirect_stdout(output), redirect_stderr(errors):
                code = S.main(argv)
            self.assertEqual(code, 2)
            self.assertEqual(environment.reads, [])
            reader.assert_not_called(); read_bytes.assert_not_called()
            self.assertEqual(errors.getvalue(), '')
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            report = json.loads(output.getvalue()); self.assert_safe(report)
            self.assertEqual(report['status'], 'HOLD')

    def test_cli_empty_arguments_uses_only_trusted_event_and_fixed_private_callback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'private-event-file-sentinel.json'
            path.write_bytes(wire(trusted_event()))
            environment = trusted_environment(); environment['GITHUB_EVENT_PATH'] = str(path)
            output, errors = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(S, '_load_authenticated_pair', return_value=pair(self.guard)) as reader, \
                    redirect_stdout(output), redirect_stderr(errors):
                code = S.main([])
            self.assertEqual(code, 0)
            self.assertEqual(errors.getvalue(), '')
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            report = json.loads(output.getvalue()); self.assert_safe(report)
            self.assertEqual(report['status'], 'NO_ORPHAN_ANCHORS')
            reader.assert_called_once_with()

    def test_invalid_duplicate_nonfinite_symlink_and_oversized_event_never_open_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); event = wire(trusted_event())
            cases = [root / 'missing']
            for index, raw in enumerate((b'private-json-sentinel {', b'[]',
                    b'{"ref":"refs/heads/main","ref":"private-duplicate-sentinel"}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'x' * (1024 * 1024 + 1))):
                path = root / ('bad-' + str(index)); path.write_bytes(raw); cases.append(path)
            valid = root / 'valid'; valid.write_bytes(event)
            link = root / 'linked'; link.symlink_to(valid); cases.append(link)
            for path in cases:
                environment = trusted_environment(); environment['GITHUB_EVENT_PATH'] = str(path)
                output, errors = io.StringIO(), io.StringIO()
                with self.subTest(path=path.name), patch.dict(os.environ, environment, clear=True), \
                        patch.object(S, '_load_authenticated_pair') as reader, \
                        redirect_stdout(output), redirect_stderr(errors):
                    code = S.main([])
                self.assertEqual(code, 2)
                reader.assert_not_called()
                self.assertEqual(errors.getvalue(), '')
                report = json.loads(output.getvalue()); self.assert_safe(report)
                self.assertEqual(report['status'], 'HOLD')


class InventedRepository:
    """Git/read boundary double; unrelated legacy symlink must stay outside scope."""
    def __init__(self, snapshot=CURRENT, generation=424):
        self.snapshot = snapshot
        self.ciphertext = b'private-reader-cipher-sentinel'
        self.ident = hashlib.sha256(self.ciphertext).hexdigest()
        self.header = header(generation, '0' * 64)
        self.raws = {'latest.json': wire(dict(header=self.header, cipher_sha256=self.ident)),
            'views/' + self.ident + '.json': self.ciphertext}
        self.modes = {name: ('100644', 'blob', 'a' * 40) for name in self.raws}
        self.modes['legacy-link'] = ('120000', 'blob', 'b' * 40)
        self.calls = []

    def head(self):
        self.calls.append(('mutable-head',))
        return 'f' * 40

    def fetch(self, commit):
        self.calls.append(('fetch', commit))
        if commit != self.snapshot:
            raise AssertionError('fixed-snapshot-required')

    def exists(self, commit, path):
        self.calls.append(('exists', commit, path))
        return commit == self.snapshot and path in self.raws

    def read(self, commit, path, limit):
        self.calls.append(('read', commit, path, limit))
        if commit != self.snapshot:
            raise AssertionError('fixed-snapshot-required')
        raw = self.raws[path]
        if len(raw) > limit:
            raise ValueError('INVENTED_READ_BOUND')
        return raw

    def _run(self, args, **kwargs):
        self.calls.append(('git', tuple(args)))
        if not args or args[0] != 'ls-tree' or self.snapshot not in args:
            raise AssertionError('only-selected-ls-tree-is-allowed')
        selected = [name for name in self.modes if name in args]
        names = selected if selected else list(self.modes)
        format_arg = next((value for value in args if value.startswith('--format=')), None)
        rows = []
        for name in names:
            mode, kind, ident = self.modes[name]
            if format_arg:
                row = format_arg.split('=', 1)[1]
                for token, value in (('%(objectmode)', mode), ('%(objecttype)', kind),
                        ('%(objectname)', ident), ('%(path)', name)):
                    row = row.replace(token, value)
            else:
                row = mode + ' ' + kind + ' ' + ident + '\t' + name
            rows.append(row)
        ending = '\0' if '-z' in args else '\n'
        return (ending.join(rows) + ending).encode('utf-8')

    def commit(self, *args, **kwargs):
        raise AssertionError('private-commit-sentinel')

    def commit_snapshot(self, *args, **kwargs):
        raise AssertionError('private-commit-snapshot-sentinel')

    def push(self, *args, **kwargs):
        raise AssertionError('private-push-sentinel')


class FixedSnapshotReaderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(S, 'fixed-pair rejection-anchor reader is missing')
        self.guard = load_guard()

    def wrapper(self, repository=None, budget=None):
        repository = InventedRepository() if repository is None else repository
        budget = S.ReadBudget(limit=65536, snapshot_limit=32) if budget is None else budget
        return S._SelectedSnapshotReader(repository, CURRENT, feed=reader_feed(), budget=budget)

    def test_byte_and_snapshot_budgets_are_strict_and_actual_bytes_are_charged(self):
        budget = S.ReadBudget(limit=5, snapshot_limit=2)
        self.assertEqual(budget.remaining, 5)
        budget.consume(b'ab'); self.assertEqual(budget.remaining, 3)
        budget.consume(b'cde'); self.assertEqual(budget.remaining, 0)
        with self.assertRaises(ValueError):
            budget.consume(b'f')
        self.assertEqual(budget.remaining, 0)
        for invalid in ('x', bytearray(b'x'), None):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises((TypeError, ValueError)):
                S.ReadBudget(limit=5, snapshot_limit=2).consume(invalid)
        budget = S.ReadBudget(limit=5, snapshot_limit=2)
        budget.enter(CURRENT); budget.enter(OLDER)
        with self.assertRaises(ValueError):
            budget.enter('4' * 40)
        for options in (dict(limit=0), dict(limit=True), dict(snapshot_limit=0),
                        dict(snapshot_limit=True)):
            with self.subTest(options=options), self.assertRaises((TypeError, ValueError)):
                S.ReadBudget(**options)

    def test_snapshot_wrapper_never_consults_mutable_head_and_blocks_all_writers(self):
        repository = InventedRepository()
        reader = self.wrapper(repository)
        self.assertEqual(reader.head(), CURRENT)
        self.assertNotIn(('mutable-head',), repository.calls)
        reader.fetch(CURRENT)
        self.assertTrue(reader.exists(CURRENT, 'latest.json'))
        self.assertIn(('fetch', CURRENT), repository.calls)
        for name in ('commit', 'commit_snapshot', 'push'):
            with self.subTest(method=name), self.assertRaises(ValueError):
                getattr(reader, name)({}, None)
        self.assertFalse(any(call[0] in ('commit', 'commit_snapshot', 'push')
            for call in repository.calls))

    def test_validate_tree_checks_only_selected_manifest_and_cipher_not_legacy_entries(self):
        repository = InventedRepository()
        reader = self.wrapper(repository)
        reader.validate_tree(CURRENT)
        trees = [call[1] for call in repository.calls if call[0] == 'git']
        self.assertTrue(trees)
        requested = [name for args in trees for name in args
            if name in ('latest.json', 'views/' + repository.ident + '.json')]
        self.assertIn('latest.json', requested)
        self.assertIn('views/' + repository.ident + '.json', requested)
        self.assertTrue(all('latest.json' in args or
            'views/' + repository.ident + '.json' in args for args in trees))

    def test_selected_manifest_and_cipher_wrong_modes_or_missing_paths_refuse(self):
        for target in ('latest.json', 'cipher'):
            for mode, kind in (('120000', 'blob'), ('040000', 'tree'), ('100755', 'blob')):
                repository = InventedRepository()
                path = 'views/' + repository.ident + '.json' if target == 'cipher' else target
                repository.modes[path] = (mode, kind, 'a' * 40)
                with self.subTest(target=target, mode=mode), self.assertRaises(ValueError):
                    self.wrapper(repository).validate_tree(CURRENT)
        for target in ('latest.json', 'cipher'):
            repository = InventedRepository()
            path = 'views/' + repository.ident + '.json' if target == 'cipher' else target
            del repository.modes[path]
            with self.subTest(missing=target), self.assertRaises(ValueError):
                self.wrapper(repository).validate_tree(CURRENT)

    def test_read_caps_underlying_request_to_remaining_bytes_and_never_reads_after_exhaustion(self):
        repository = InventedRepository()
        repository.raws['tiny'] = b'abcd'
        budget = S.ReadBudget(limit=4, snapshot_limit=32)
        reader = self.wrapper(repository, budget)
        self.assertEqual(reader.read(CURRENT, 'tiny', 999999), b'abcd')
        self.assertIn(('read', CURRENT, 'tiny', 4), repository.calls)
        self.assertEqual(budget.remaining, 0)
        before = list(repository.calls)
        with self.assertRaises(ValueError):
            reader.read(CURRENT, 'tiny', 999999)
        self.assertEqual(repository.calls, before)

    def test_read_rejects_a_dependency_returning_more_than_its_requested_limit(self):
        repository = InventedRepository()
        def oversized(commit, path, limit):
            return b'x' * (limit + 1)
        repository.read = oversized
        reader = self.wrapper(repository, S.ReadBudget(limit=100, snapshot_limit=32))
        with self.assertRaises(ValueError):
            reader.read(CURRENT, 'tiny', 4)

    def test_verified_snapshot_delegates_normal_current_view_and_keeps_private_body_unchanged(self):
        repository = InventedRepository()
        original_view = view(); before = deepcopy(original_view); calls = []
        bootstrap = {'key': b'invented-only-display-key'}
        def current_view(reader, actual_bootstrap, *, day=None):
            self.assertIs(actual_bootstrap, bootstrap)
            self.assertEqual(reader.head(), CURRENT)
            reader.validate_tree(CURRENT)
            self.assertFalse(any(call[0] == 'mutable-head' for call in repository.calls))
            calls.append(day)
            return CURRENT, repository.ident, 424, original_view
        budget = S.ReadBudget(limit=65536, snapshot_limit=32)
        snapshot = S._read_verified_snapshot(repository, bootstrap, CURRENT,
            feed=reader_feed(current_view), guard=self.guard, budget=budget)
        self.assertEqual(calls, [None])
        self.assertIsInstance(snapshot, S.VerifiedSnapshot)
        self.assertEqual(original_view, before)
        self.assertLess(budget.remaining, 65536)

    def test_explicit_selected_day_is_forwarded_to_existing_reader(self):
        repository = InventedRepository()
        calls = []
        def current_view(reader, bootstrap, *, day=None):
            calls.append(day)
            return CURRENT, repository.ident, 424, view()
        S._read_verified_snapshot(repository, {}, CURRENT,
            feed=reader_feed(current_view), guard=self.guard,
            budget=S.ReadBudget(limit=65536, snapshot_limit=32), day='2030-04-01')
        self.assertEqual(calls, ['2030-04-01'])

    def test_returned_parent_or_generation_mismatch_never_mints_a_snapshot(self):
        for returned in ((OLDER, 424), (CURRENT, 423), (CURRENT, True)):
            repository = InventedRepository()
            parent, generation = returned
            def current_view(reader, bootstrap, *, day=None):
                return parent, repository.ident, generation, view()
            with self.subTest(parent=parent, generation=generation), self.assertRaises(ValueError):
                S._read_verified_snapshot(repository, {}, CURRENT,
                    feed=reader_feed(current_view), guard=self.guard,
                    budget=S.ReadBudget(limit=65536, snapshot_limit=32))

    def test_one_shared_budget_limits_aggregate_reads_across_snapshot_wrappers(self):
        first, second = InventedRepository(CURRENT), InventedRepository(OLDER, 423)
        first.raws['tiny'] = b'abc'; second.raws['tiny'] = b'def'
        budget = S.ReadBudget(limit=5, snapshot_limit=32)
        current = S._SelectedSnapshotReader(first, CURRENT, feed=reader_feed(), budget=budget)
        older = S._SelectedSnapshotReader(second, OLDER, feed=reader_feed(), budget=budget)
        self.assertEqual(current.read(CURRENT, 'tiny', 50), b'abc')
        with self.assertRaises(ValueError):
            older.read(OLDER, 'tiny', 50)
        self.assertIn(('read', OLDER, 'tiny', 2), second.calls)


if __name__ == '__main__':
    unittest.main()
