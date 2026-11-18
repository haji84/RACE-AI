"""Offline repair CLI boundary: strict event parsing, trust, safe output only."""
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import inspect
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import boat_rejection_anchor_repair as R


SCHEMA = 'RACE_AI_REJECTION_ANCHOR_REPAIR_V1'
HEAD = '1' * 40
PREFIX = 'boat-owner-release: single-real-session-20261111'
COUNTS = ('snapshots_checked', 'orphan_groups', 'current_active_rejections',
    'candidate_active_rejections', 'retained_history_originals',
    'restored_active_originals', 'rows_changed')
HASHES = ('current_view_sha256', 'candidate_view_sha256', 'published_snapshot_sha',
          'published_cipher_sha256', 'published_generation')
EFFECTS = dict(originals_changed=False, observations_reconciled=0, source_requests=0,
    forecast_generated=False, broader_goals_proven=False)
REASONS = frozenset((
    'CLI_ARGUMENTS_REJECTED', 'TRUSTED_MAIN_REQUIRED', 'AUTHENTICATED_CONTEXT_UNAVAILABLE',
    'V5_CURRENT_REQUIRED', 'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED',
    'CURRENT_HISTORY_INVALID', 'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING',
    'CANDIDATE_GUARD_REJECTED', 'PUBLIC_CANDIDATE_INVALID', 'PREDECESSOR_CHANGED',
    'PUBLICATION_OUTCOME_UNKNOWN', 'AUTHENTICATED_READBACK_UNAVAILABLE', 'READBACK_MISMATCH',
))


def event():
    return dict(ref='refs/heads/main', after=HEAD, deleted=False,
        head_commit=dict(id=HEAD, message=PREFIX + ': reviewed repair candidate'),
        repository=dict(full_name='haji84/RACE-AI', id=1416489937, private=False, fork=False),
        private_extra=dict(url='https://private-sentinel.invalid', owner_key='private-sentinel-event'))


class CLIEnvironment(Mapping):
    allowed = frozenset(('GITHUB_ACTIONS', 'GITHUB_EVENT_NAME', 'GITHUB_REF', 'GITHUB_SHA',
        'GITHUB_REPOSITORY', 'GITHUB_REPOSITORY_ID', 'GITHUB_WORKFLOW_REF', 'GITHUB_JOB',
        'GITHUB_RUN_ATTEMPT', 'GITHUB_EVENT_PATH'))

    def __init__(self, values):
        self._values = values

    def __getitem__(self, key):
        if key not in self.allowed:
            raise AssertionError('NO_KEY_OR_UNRELATED_ENVIRONMENT_READ')
        return self._values[key]

    def get(self, key, default=None):
        if key not in self.allowed:
            raise AssertionError('NO_KEY_OR_UNRELATED_ENVIRONMENT_READ')
        return self._values.get(key, default)

    def __iter__(self):
        raise AssertionError('NO_ENVIRONMENT_ENUMERATION')

    def __len__(self):
        return len(self._values)

    def copy(self):
        raise AssertionError('NO_ENVIRONMENT_COPY')


class NoEnvironment(CLIEnvironment):
    allowed = frozenset()


def environment(path=None, **changes):
    values = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/main',
        GITHUB_SHA=HEAD, GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
        GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main',
        GITHUB_JOB='owner_p0_p1_dispatch', GITHUB_RUN_ATTEMPT='1',
        RACE_AI_STATE_KEY='private-sentinel-owner-key', GH_TOKEN='private-sentinel-token',
        PRIVATE_EXTRA='private-sentinel-environment')
    if path is not None:
        values['GITHUB_EVENT_PATH'] = str(path)
    values.update(changes)
    return CLIEnvironment(values)


def hold(reason, *, attempted=False, performed=False):
    return dict(schema=SCHEMA, status='HOLD', reason=reason, counts=None,
        **{name: None for name in HASHES}, **EFFECTS,
        publication_attempted=attempted, publication_performed=performed, readback_verified=False)


def no_change():
    return dict(schema=SCHEMA, status='NO_CHANGE', counts=dict(
        snapshots_checked=1, orphan_groups=0, current_active_rejections=3,
        candidate_active_rejections=3, retained_history_originals=4,
        restored_active_originals=0, rows_changed=0), current_view_sha256='a'*64,
        candidate_view_sha256=None, published_snapshot_sha=None, published_cipher_sha256=None,
        published_generation=None, **EFFECTS, publication_attempted=False,
        publication_performed=False, readback_verified=False)


def published():
    return dict(schema=SCHEMA, status='PUBLISHED_VERIFIED', counts=dict(
        snapshots_checked=2, orphan_groups=2, current_active_rejections=1,
        candidate_active_rejections=3, retained_history_originals=4,
        restored_active_originals=2, rows_changed=1), current_view_sha256='a'*64,
        candidate_view_sha256='b'*64, published_snapshot_sha='7'*40,
        published_cipher_sha256='c'*64, published_generation=425,
        **EFFECTS, publication_attempted=True, publication_performed=True, readback_verified=True)


class RejectionAnchorRepairCLITests(unittest.TestCase):
    def invoke(self, env, argv, *, runner=None, loader=None, use_sys_argv=False):
        output, errors = io.StringIO(), io.StringIO()
        load = loader or Mock(side_effect=AssertionError('PRIVATE_CONTEXT_MUST_NOT_LOAD'))
        patches = [patch.object(os, 'environ', env), patch.object(R, '_load_repair_context', load)]
        if runner is not None:
            patches.append(patch.object(R, 'run_repair', runner))
        for active in patches:
            active.start()
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                if use_sys_argv:
                    with patch.object(sys, 'argv', ['boat_rejection_anchor_repair.py', *argv]):
                        code = R.main()
                else:
                    code = R.main(argv)
        finally:
            for active in reversed(patches):
                active.stop()
        self.assertEqual(errors.getvalue(), '')
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        report = json.loads(output.getvalue())
        self.safe(report)
        return code, report, load

    def safe(self, report):
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], SCHEMA)
        self.assertIn(report['status'], ('HOLD', 'NO_CHANGE', 'PUBLISHED_VERIFIED'))
        fields = {'schema', 'status', 'counts', *HASHES, *EFFECTS,
                  'publication_attempted', 'publication_performed', 'readback_verified'}
        for name, value in EFFECTS.items():
            self.assertIs(type(report[name]), type(value))
            self.assertEqual(report[name], value)
        self.assertIs(type(report['publication_attempted']), bool)
        self.assertTrue(report['publication_performed'] is None or
                        type(report['publication_performed']) is bool)
        self.assertIs(type(report['readback_verified']), bool)
        if report['status'] == 'HOLD':
            fields.add('reason')
            self.assertIn(report['reason'], REASONS)
            self.assertIsNone(report['counts'])
            for name in HASHES:
                self.assertIsNone(report[name])
            self.assertFalse(report['readback_verified'])
        else:
            self.assertEqual(set(report['counts']), set(COUNTS))
            for number in report['counts'].values():
                self.assertIs(type(number), int)
                self.assertGreaterEqual(number, 0)
            self.assertRegex(report['current_view_sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(set(report), fields)
        text = json.dumps(report, sort_keys=True, allow_nan=False)
        for forbidden in ('sentinel', 'https:', 'owner_key', 'private_extra',
                          'Traceback', 'result_observations', 'RESULT_METADATA'):
            self.assertNotIn(forbidden, text)

    def test_any_argument_is_rejected_before_environment_event_or_private_context(self):
        self.assertEqual(tuple(inspect.signature(R.main).parameters), ('argv',))
        self.assertIs(inspect.signature(R.main).parameters['argv'].default, None)
        for args in (['--help'], ['--force'], ['--key=private-sentinel'],
                     ['--snapshot', 'private-sentinel'], ['--source', 'private-sentinel']):
            with self.subTest(flag=args[0]):
                runner = Mock(side_effect=AssertionError('NO_ORCHESTRATION'))
                code, report, loader = self.invoke(NoEnvironment({}), args, runner=runner)
                self.assertEqual(code, 2)
                self.assertEqual(report, hold('CLI_ARGUMENTS_REJECTED'))
                runner.assert_not_called()
                loader.assert_not_called()

    def test_valid_event_passes_exact_environment_and_only_the_fixed_loader_callback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'
            payload = event()
            path.write_text(json.dumps(payload))
            env = environment(path)
            private = object()
            loader = Mock(return_value=private)
            def orchestration(actual_env, actual_event, *, load_context):
                self.assertIs(actual_env, env)
                self.assertEqual(actual_event, payload)
                self.assertIs(load_context, loader)
                self.assertIs(load_context, R._load_repair_context)
                self.assertIs(load_context(), private)
                print('private-sentinel-orchestration-noise')
                print('private-sentinel-stderr', file=sys.stderr)
                return no_change()
            runner = Mock(side_effect=orchestration)
            code, report, loaded = self.invoke(env, [], runner=runner, loader=loader)
            self.assertEqual(code, 0)
            self.assertEqual(report, no_change())
            runner.assert_called_once()
            loaded.assert_called_once_with()

    def test_duplicate_nonfinite_malformed_and_nonobject_events_never_reach_orchestration(self):
        documents = (
            b'{"after":"one","after":"two"}',
            b'{"private_extra":{"x":1,"x":2}}',
            b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
            b'{"value":1e999}', b'{"value":-1e999}', b'{"value":"\xff"}',
            b'not-json-private-sentinel', b'[]', b'null', b'true',
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'
            for raw in documents:
                with self.subTest(raw_kind=raw[:12]):
                    path.write_bytes(raw)
                    runner = Mock(side_effect=AssertionError('NO_ORCHESTRATION'))
                    code, report, loader = self.invoke(environment(path), [], runner=runner)
                    self.assertEqual(code, 2)
                    self.assertEqual(report, hold('INPUT_OR_CHAIN_INVALID'))
                    runner.assert_not_called()
                    loader.assert_not_called()

    def test_event_path_requires_bounded_nonempty_regular_file_without_symlinks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'target.json'; target.write_text(json.dumps(event()))
            link = root / 'event-link.json'; link.symlink_to(target)
            empty = root / 'empty.json'; empty.write_bytes(b'')
            huge = root / 'huge.json'
            payload = event(); payload['private_padding'] = 'private-sentinel' + 'x'*(1024*1024)
            huge.write_text(json.dumps(payload))
            for path in (None, root / 'missing.json', root, link, empty, huge):
                with self.subTest(path_kind='missing-env' if path is None else path.name):
                    runner = Mock(side_effect=AssertionError('NO_ORCHESTRATION'))
                    code, report, loader = self.invoke(environment(path), [], runner=runner)
                    self.assertEqual(code, 2)
                    self.assertEqual(report, hold('INPUT_OR_CHAIN_INVALID'))
                    runner.assert_not_called()
                    loader.assert_not_called()

    def test_real_orchestrator_refuses_untrusted_first_attempt_context_before_private_loader(self):
        changes = (
            dict(GITHUB_EVENT_NAME='workflow_dispatch'), dict(GITHUB_REF='refs/heads/other'),
            dict(GITHUB_JOB='other_job'), dict(GITHUB_RUN_ATTEMPT='2'),
            dict(GITHUB_RUN_ATTEMPT='01'), dict(GITHUB_RUN_ATTEMPT=1),
            dict(GITHUB_REPOSITORY_ID='1'), dict(GITHUB_SHA='A'*40),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'; path.write_text(json.dumps(event()))
            for changed in changes:
                with self.subTest(field=tuple(changed)):
                    code, report, loader = self.invoke(environment(path, **changed), [])
                    self.assertEqual(code, 2)
                    self.assertEqual(report, hold('TRUSTED_MAIN_REQUIRED'))
                    loader.assert_not_called()
            for change in (
                    dict(deleted=True), dict(after='2'*40),
                    dict(repository=dict(full_name='haji84/RACE-AI', id=True, private=False, fork=False)),
                    dict(repository=dict(full_name='haji84/RACE-AI', id=1416489937, private=True, fork=False)),
                    dict(repository=dict(full_name='haji84/RACE-AI', id=1416489937, private=False, fork=True)),
                    dict(head_commit=dict(id=HEAD, message='private-sentinel-unreviewed'))):
                payload = event(); payload.update(change)
                path.write_text(json.dumps(payload))
                code, report, loader = self.invoke(environment(path), [])
                self.assertEqual(code, 2)
                self.assertEqual(report, hold('TRUSTED_MAIN_REQUIRED'))
                loader.assert_not_called()

    def test_valid_hold_reports_preserve_false_unknown_and_acknowledged_publication_states(self):
        reports = (
            hold('PREDECESSOR_CHANGED'),
            hold('PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None),
            hold('AUTHENTICATED_READBACK_UNAVAILABLE', attempted=True, performed=True),
            hold('READBACK_MISMATCH', attempted=True, performed=True),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'; path.write_text(json.dumps(event()))
            for expected in reports:
                with self.subTest(performed=expected['publication_performed'], reason=expected['reason']):
                    runner = Mock(return_value=deepcopy(expected))
                    code, report, loader = self.invoke(environment(path), [], runner=runner)
                    self.assertEqual(code, 2)
                    self.assertEqual(report, expected)
                    runner.assert_called_once()
                    loader.assert_not_called()

    def test_private_exceptions_noise_or_invalid_results_remain_unknown_without_retry(self):
        bad = []
        value = no_change(); value['private_extra'] = 'private-sentinel-result'; bad.append(value)
        value = no_change(); value['source_requests'] = 1; bad.append(value)
        value = published(); value['counts']['restored_active_originals'] = True; bad.append(value)
        value = published(); value['published_generation'] = True; bad.append(value)
        value = published(); value['candidate_view_sha256'] = 'private-sentinel-hash'; bad.append(value)
        value = published(); value['publication_performed'] = False; bad.append(value)
        value = hold('READBACK_MISMATCH', attempted=True, performed=True)
        value['readback_verified'] = True; bad.append(value)
        bad.extend((True, [], None, hold('PRIVATE_SENTINEL_UNKNOWN_REASON')))
        expected = hold('PUBLICATION_OUTCOME_UNKNOWN', attempted=True, performed=None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'; path.write_text(json.dumps(event()))
            def failing(*args, **kwargs):
                print('private-sentinel-stdout')
                print('private-sentinel-stderr', file=sys.stderr)
                raise RuntimeError('private-sentinel-failure https://private-sentinel.invalid')
            runners = [Mock(side_effect=failing)] + [Mock(return_value=value) for value in bad]
            for runner in runners:
                code, report, loader = self.invoke(environment(path), [], runner=runner)
                self.assertEqual(code, 2)
                self.assertEqual(report, expected)
                runner.assert_called_once()
                loader.assert_not_called()

    def test_no_change_and_verified_publication_emit_one_exact_safe_json_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'; path.write_text(json.dumps(event()))
            for expected in (no_change(), published()):
                with self.subTest(status=expected['status']):
                    runner = Mock(return_value=deepcopy(expected))
                    code, report, loader = self.invoke(environment(path), [], runner=runner,
                                                        use_sys_argv=True)
                    self.assertEqual(code, 0)
                    self.assertEqual(report, expected)
                    runner.assert_called_once()
                    loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
