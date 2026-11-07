"""Offline publisher compatibility checks; no official source or live GitHub."""
from contextlib import redirect_stdout
from copy import deepcopy
import base64
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import boat_saved_view_feed as cli

try:
    A = importlib.import_module('race_ai.saved_history_activation')
except ModuleNotFoundError:
    A = None

BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
PREFIX = ('actions/workflows/405276784/runs?branch='
          'feat%2Ffour-sport-forecast-audit-view-20261022&status=')
STATUSES = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
NEW = b'"""Pinned reader source, never executed by the guard."""\nHISTORY_READER_PROTOCOL = 5\n'
OLD = b'APPEND_FEED = "RACE_AI_SAVED_WEB_VIEW_V4"\n'


def run_row(ident=7, head='a'*40, status='in_progress'):
    return dict(id=ident, workflow_id=405276784, head_branch=BRANCH,
                head_sha=head, status=status, conclusion=None, event='push',
                repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'))


def pages(rows=()):
    return {PREFIX+status+'&per_page=100&page=1':
            json.dumps(dict(total_count=sum(row['status'] == status for row in rows),
                            workflow_runs=[row for row in rows if row['status'] == status])).encode()
            for status in STATUSES}


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(A, 'saved history publisher compatibility guard is missing')

    def inspect(self, rows=(), *, documents=None, responses=None, **identity):
        responses = pages(rows) if responses is None else responses
        requested, heads = [], []

        def get(path):
            requested.append(path)
            return responses[path]

        def read(head):
            heads.append(head)
            return NEW if documents is None else documents[head]

        result = A.inspect_publishers(get, read, current_run_id=identity.get('current_run_id', 99),
                                      current_head=identity.get('current_head', 'f'*40))
        return result, requested, heads

    def test_old_collecting_and_pending_pinned_publishers_keep_v4(self):
        rows = [run_row(head='a'*40), run_row(8, 'b'*40, 'pending')]
        result, requested, heads = self.inspect(rows, documents={'a'*40: OLD, 'b'*40: OLD})
        self.assertEqual(result, dict(compatible=False, active_publishers=2,
                                      compatible_publishers=0, legacy_publishers=2))
        self.assertEqual(len(requested), 5)
        self.assertEqual(set(heads), {'a'*40, 'b'*40})

    def test_every_verified_publisher_supports_v5_before_activation(self):
        result, _, _ = self.inspect([run_row(), run_row(8, 'b'*40, 'waiting')])
        self.assertEqual(result, dict(compatible=True, active_publishers=2,
                                      compatible_publishers=2, legacy_publishers=0))
        self.assertEqual(self.inspect()[0]['compatible'], True)

    def test_only_the_exact_current_run_id_and_head_are_excluded(self):
        current = run_row(99, 'f'*40)
        result, _, heads = self.inspect([current, run_row(8, 'f'*40, 'queued')],
                                        documents={'f'*40: OLD})
        self.assertEqual(result['legacy_publishers'], 1)
        self.assertEqual(heads, ['f'*40])
        with self.assertRaisesRegex(ValueError, 'HISTORY_.*IDENTITY'):
            self.inspect([run_row(99, 'e'*40)])
        for identity in (dict(current_run_id=None), dict(current_head='main')):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, 'HISTORY_.*IDENTITY'):
                self.inspect(**identity)

    def test_run_moving_between_status_pages_is_counted_once(self):
        result, _, heads = self.inspect([run_row(7, 'a'*40, 'queued'), run_row()])
        self.assertEqual(result['active_publishers'], 1)
        self.assertEqual(heads, ['a'*40])
        with self.assertRaisesRegex(ValueError, 'HISTORY_.*IDENTITY'):
            self.inspect([run_row(7, 'b'*40, 'queued'), run_row()])

    def test_same_pinned_head_is_read_once_for_separate_runs(self):
        result, _, heads = self.inspect([run_row(7), run_row(8)])
        self.assertEqual(result['compatible_publishers'], 2)
        self.assertEqual(heads, ['a'*40])

    def test_incomplete_malformed_or_oversized_pages_hold(self):
        key = PREFIX+'queued&per_page=100&page=1'
        invalid = [dict(total_count=1, workflow_runs=[]),
                   dict(total_count=101, workflow_runs=[]),
                   dict(total_count=True, workflow_runs=[]),
                   dict(total_count=-1, workflow_runs=[]),
                   dict(workflow_runs=[]), dict(total_count=0, workflow_runs={}),
                   dict(total_count=2, workflow_runs=[run_row(status='queued')]*2)]
        for value in invalid:
            response = pages(); response[key] = json.dumps(value).encode()
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'HISTORY_'):
                self.inspect(responses=response)
        for raw in (b'not json', b'{"total_count":0,"total_count":0,"workflow_runs":[]}'):
            response = pages(); response[key] = raw
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'HISTORY_'):
                self.inspect(responses=response)

    def test_wrong_repository_workflow_branch_head_or_status_holds(self):
        invalid = []
        for key, value in (('id', True), ('workflow_id', 1), ('head_branch', 'main'),
                           ('head_sha', '../main'), ('status', 'completed')):
            row = run_row(); row[key] = value; invalid.append(row)
        for field in ('repository', 'head_repository'):
            for key, value in (('id', 1), ('full_name', 'someone/RACE-AI')):
                row = run_row(); row[field][key] = value; invalid.append(row)
        key = PREFIX+'in_progress&per_page=100&page=1'
        for row in invalid:
            response = pages(); response[key] = json.dumps(dict(total_count=1, workflow_runs=[row])).encode()
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'HISTORY_.*IDENTITY'):
                self.inspect(responses=response)

    def test_more_than_sixteen_distinct_active_runs_holds_instead_of_truncating(self):
        with self.assertRaisesRegex(ValueError, 'HISTORY_.*BOUND'):
            self.inspect([run_row(ident) for ident in range(1, 18)])

    def test_only_a_literal_module_protocol_declaration_is_compatible(self):
        unsupported = [OLD, b'# HISTORY_READER_PROTOCOL = 5\n',
                       b'"HISTORY_READER_PROTOCOL = 5"\n',
                       b'def f():\n HISTORY_READER_PROTOCOL = 5\n',
                       b'if True:\n HISTORY_READER_PROTOCOL = 5\n',
                       b'HISTORY_READER_PROTOCOL = int("5")\n',
                       b'HISTORY_READER_PROTOCOL = True\n',
                       b'HISTORY_READER_PROTOCOL = 5\nHISTORY_READER_PROTOCOL = 4\n',
                       b'HISTORY_READER_PROTOCOL = 5\ndel HISTORY_READER_PROTOCOL\n',
                       b'HISTORY_READER_PROTOCOL = 5\nfrom elsewhere import HISTORY_READER_PROTOCOL\n']
        for source in unsupported:
            with self.subTest(source=source):
                self.assertEqual(self.inspect([run_row()], documents={'a'*40: source})[0]['compatible'], False)
        with self.assertRaisesRegex(ValueError, 'HISTORY_.*SOURCE'):
            self.inspect([run_row()], documents={'a'*40: b'broken python (\n'})

    def test_transport_and_pinned_object_errors_never_become_legacy_fallback(self):
        def failed(_):
            raise RuntimeError('sensitive transport failure')
        for get, read in ((failed, lambda _: NEW), (lambda path: pages([run_row()])[path], failed)):
            with self.subTest(get=get), self.assertRaisesRegex((ValueError, RuntimeError), 'HISTORY_') as caught:
                A.inspect_publishers(get, read, current_run_id=99, current_head='f'*40)
            self.assertNotIn('sensitive', str(caught.exception))


class ActivationTransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(A, 'saved history publisher compatibility guard is missing')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git = SimpleNamespace(repo=self.root, fetch_url='https://github.com/haji84/RACE-AI.git')
        self.environment = dict(GITHUB_RUN_ID='99', GITHUB_SHA='f'*40)

    def completed(self, command, stdout=b'', code=0, stderr=b''):
        return subprocess.CompletedProcess(command, code, stdout=stdout, stderr=stderr)

    def test_reads_pinned_git_object_instead_of_the_working_tree_and_never_executes_source(self):
        def git(*args):
            return subprocess.run(['git', *args], cwd=self.root, capture_output=True, check=True).stdout

        git('init', '--quiet')
        source = self.root/'race_ai/saved_view_feed.py'; source.parent.mkdir()
        source.write_bytes(NEW+b'raise RuntimeError("this pinned module must never execute")\n')
        git('add', 'race_ai/saved_view_feed.py')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgSign=false', 'commit', '--quiet', '-m', 'fictional reader')
        head = git('rev-parse', 'HEAD').decode().strip()
        source.write_bytes(OLD)
        responses = pages([run_row(head=head)])
        commands = []

        def runner(command, **options):
            commands.append(command)
            self.assertGreater(options['timeout'], 0)
            self.assertLessEqual(options['timeout'], 120)
            if command[0] == 'gh':
                self.assertEqual(command[:6], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET'])
                path = command[-1].removeprefix('repos/haji84/RACE-AI/')
                return self.completed(command, responses[path])
            self.assertNotIn('fetch', command, 'existing objects must not cause a network read')
            return subprocess.run(command, **options)

        result = A.check_history_activation(self.git, environment=self.environment, runner=runner)
        self.assertEqual(result['compatible'], True)
        self.assertEqual(source.read_bytes(), OLD)
        self.assertEqual(len([command for command in commands if command[0] == 'gh']), 5)

    def test_missing_exact_head_is_fetched_once_within_the_shared_deadline(self):
        fetched = False
        commands = []
        responses = pages([run_row()])

        def runner(command, **options):
            nonlocal fetched
            commands.append((command, options['timeout']))
            if command[0] == 'gh':
                return self.completed(command, responses[command[-1].removeprefix('repos/haji84/RACE-AI/')])
            if command[1:3] == ['cat-file', '-t']:
                return self.completed(command, b'commit\n' if fetched else b'', 0 if fetched else 128)
            if command[1] == 'config':
                return self.completed(command, code=1)
            if command[1] == 'fetch':
                self.assertEqual(command, ['git', 'fetch', '--no-tags', '--no-write-fetch-head', '--depth=1',
                                           'https://github.com/haji84/RACE-AI.git', 'a'*40])
                self.assertLessEqual(options['timeout'], 30)
                fetched = True
                return self.completed(command)
            if command[1:3] == ['cat-file', '-s']:
                return self.completed(command, str(len(NEW)).encode()+b'\n')
            if command[1] == 'show':
                self.assertEqual(command[-1], 'a'*40+':race_ai/saved_view_feed.py')
                return self.completed(command, NEW)
            self.fail('unexpected external command')

        self.assertEqual(A.check_history_activation(self.git, environment=self.environment,
                                                   runner=runner)['compatible'], True)
        self.assertEqual(sum(command[1] == 'fetch' for command, _ in commands), 1)

    def test_one_deadline_stops_inspection_instead_of_giving_every_call_two_minutes(self):
        now = 0
        calls = 0

        def runner(command, **options):
            nonlocal now, calls
            calls += 1
            self.assertLessEqual(options['timeout'], 15)
            now += 31
            return self.completed(command, json.dumps(dict(total_count=0, workflow_runs=[])).encode())

        with self.assertRaisesRegex(ValueError, 'HISTORY_'):
            A.check_history_activation(self.git, environment=self.environment, runner=runner, clock=lambda: now)
        self.assertEqual(calls, 4)

    def test_github_or_git_failures_and_timeouts_do_not_echo_private_stderr(self):
        responses = pages([run_row()])
        for failure in ('github', 'git', 'timeout'):
            def runner(command, **_):
                if failure == 'timeout':
                    raise subprocess.TimeoutExpired(command, 1, stderr=b'private-token-fixture')
                if command[0] == 'gh' and failure == 'git':
                    return self.completed(command, responses[command[-1].removeprefix('repos/haji84/RACE-AI/')])
                return self.completed(command, code=2, stderr=b'private-token-fixture')

            with self.subTest(failure=failure), self.assertRaisesRegex(ValueError, 'HISTORY_') as caught:
                A.check_history_activation(self.git, environment=self.environment, runner=runner)
            self.assertNotIn('private-token-fixture', str(caught.exception))

    def test_foreign_remote_and_invalid_current_environment_hold_before_requests(self):
        calls = []
        def runner(command, **_):
            calls.append(command)
            self.fail('invalid identity must stop before external reads')

        for env in ({}, dict(GITHUB_RUN_ID='99', GITHUB_SHA='main')):
            with self.subTest(env=env), self.assertRaisesRegex(ValueError, 'HISTORY_.*IDENTITY'):
                A.check_history_activation(self.git, environment=env, runner=runner)
        self.git.fetch_url = 'https://example.invalid/foreign.git'
        with self.assertRaisesRegex(ValueError, 'HISTORY_GIT_REPOSITORY_REJECTED'):
            A.check_history_activation(self.git, environment=self.environment, runner=runner)
        self.assertEqual(calls, [])


class ActivationCLITests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(A, 'saved history publisher compatibility guard is missing')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        raw = b'invented bootstrap'
        state = self.root/'audit/state'; state.mkdir(parents=True)
        (state/'boat-saved-view-input.json').write_text(json.dumps(dict(
            schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(raw).decode(),
            bootstrap_sha256=hashlib.sha256(raw).hexdigest(), catchup_artifact_id=1,
            catchup_sha256='a'*64)))
        self.view = dict(records=[dict(race_id='20261106-22-01', event_date_jst='2026-11-06', result=dict(status='pending'))])
        self.git = SimpleNamespace(_saved_history_context=None)

    def execute(self, args, *, compatible=True, failure=None, history=False, settled=False):
        if history: self.git._saved_history_context = dict(selected_day='2026-11-06', index={})
        if settled: self.view['records'][0]['result']['status'] = 'final'
        report = dict(compatible=compatible, active_publishers=1,
                      compatible_publishers=int(compatible), legacy_publishers=int(not compatible))
        published = []

        def publish(*_, **options):
            published.append(options)
            return dict(status='V5' if options['history'] or history else 'V4')

        output = io.StringIO()
        with patch.object(cli, 'ROOT', self.root), patch.object(cli, 'git_auth'), \
             patch.object(cli.F, 'open_bootstrap', return_value={}), \
             patch.object(cli.F, 'FeedRepository', return_value=self.git), \
             patch.object(cli.F, 'current_view', return_value=('b'*40, 'c'*64, 1, self.view)), \
             patch.object(cli, 'intake_saved_models', side_effect=lambda value, **_: deepcopy(value)), \
             patch.object(cli, 'observations', return_value=[dict(race_id='20261106-22-01')]) as observations, \
             patch.object(cli.F, 'load_captures', return_value=[]), \
             patch.object(cli.F, 'update_view', side_effect=lambda value, *_, **__: value), \
             patch.object(cli.F, 'publish_view', side_effect=publish), \
             patch.object(A, 'check_history_activation', return_value=report, side_effect=failure) as guard, \
             patch.dict('os.environ', {'RUNNER_TEMP': str(self.root)}), redirect_stdout(output):
            status = cli.main(args)
        return status, [json.loads(line) for line in output.getvalue().splitlines()], published, guard, observations

    def test_automatic_legacy_wait_continues_v4_with_aggregate_counts_only(self):
        status, output, published, _, _ = self.execute(['--history-when-compatible'], compatible=False)
        self.assertEqual(status, 0)
        self.assertEqual(output[0]['status'], 'HISTORY_WAIT_LEGACY_PUBLISHERS')
        self.assertEqual(output[-1]['status'], 'V4')
        self.assertEqual(published[0]['history'], False)
        self.assertNotIn('head', json.dumps(output))
        self.assertNotIn('run_id', json.dumps(output))

    def test_explicit_history_holds_when_a_legacy_publisher_remains(self):
        status, output, published, _, _ = self.execute(['--history'], compatible=False)
        self.assertEqual(status, 2)
        self.assertEqual(published, [])
        self.assertEqual(output[-1]['reason'], 'HISTORY_LEGACY_PUBLISHERS_ACTIVE')

    def test_compatible_settled_v4_migrates_without_fetching_result_artifacts(self):
        status, output, published, _, observations = self.execute(['--history-when-compatible'], settled=True)
        self.assertEqual(status, 0)
        self.assertEqual(output[-1]['status'], 'V5')
        self.assertEqual(published[0]['history'], True)
        observations.assert_not_called()

    def test_inspection_failure_holds_all_publication(self):
        status, output, published, _, observations = self.execute(
            ['--history-when-compatible'], failure=ValueError('HISTORY_RUN_PAGE_INVALID'))
        self.assertEqual(status, 2)
        self.assertEqual(published, [])
        self.assertEqual(output[-1]['reason'], 'HISTORY_RUN_PAGE_INVALID')
        observations.assert_not_called()

    def test_existing_v5_does_not_recheck_initial_activation(self):
        status, output, _, guard, _ = self.execute(['--history-when-compatible'], history=True)
        self.assertEqual(status, 0)
        self.assertEqual(output[-1]['status'], 'V5')
        guard.assert_not_called()

    def test_ordinary_v4_publisher_never_requests_activation(self):
        status, output, published, guard, _ = self.execute([])
        self.assertEqual(status, 0)
        self.assertEqual(output[-1]['status'], 'V4')
        self.assertEqual(published[0]['history'], False)
        guard.assert_not_called()


if __name__ == '__main__':
    unittest.main()
