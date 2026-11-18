"""Invented Actions/event inputs and mocked AES reader; no private key or source I/O."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import ModuleType
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    audit = importlib.import_module('scripts.boat_saved_reason_binding_audit')
except ModuleNotFoundError as error:
    if error.name != 'scripts.boat_saved_reason_binding_audit':
        raise
    audit = None


class SavedReasonBindingIOTests(unittest.TestCase):
    SHA = 'e1c55723bcffb3941b7c6cef370cc42b1f4dcfb6'
    SNAPSHOT = 'a' * 40
    PREFIX = 'boat-owner-release: single-real-session-20261111'
    COUNTERS = ('active_count', 'history_count', 'missing_active_anchor',
        'invalid_active_reason_metadata', 'invalid_history_reason_metadata',
        'source_sha_absent_active', 'source_sha_absent_history', 'source_sha_different',
        'non_reason_body_mismatch', 'clock_text_mismatch',
        'compared_active_history_pairs', 'other_guard_failures')
    FLAGS = dict(originals_changed=False, observations_reconciled=0,
        source_requests=0, publication_performed=False, forecast_generated=False,
        broader_goals_proven=False)

    def setUp(self):
        self.assertIsNotNone(audit, 'saved reason-binding I/O audit module is missing')
        self.guard = ModuleType('invented_saved_guard')
        self.guard.private_url = 'https://private-guard-sentinel.invalid/'
        self.view = {'records': [], 'private_payload': 'private-view-sentinel'}

    def environment(self):
        return dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
            GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_SHA=self.SHA, GITHUB_REF='refs/heads/main',
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/'
                'boat-owner-national-p1-matrix.yml@refs/heads/main',
            UNLISTED_OWNER_CREDENTIAL='private-env-sentinel',
            RACE_AI_STATE_KEY='private-root-key-sentinel')

    def event(self):
        return dict(ref='refs/heads/main', after=self.SHA,
            repository=dict(id=1416489937, full_name='haji84/RACE-AI', private=False,
                            private_payload='private-repository-sentinel'),
            head_commit=dict(id=self.SHA, message=self.PREFIX+' | binding diagnostic',
                             private_payload='private-commit-sentinel'),
            private_payload='private-event-sentinel')

    def base(self, **changes):
        value=dict(generation=9, snapshot_sha=self.SNAPSHOT,
            view=deepcopy(self.view), guard=self.guard,
            private_url='https://private-owner-sentinel.invalid/',
            owner_key='private-key-sentinel', private_payload='private-base-sentinel')
        value.update(changes)
        return value

    def diagnostic(self, status='NO_BINDING_INCONSISTENCY_IN_THIS_VIEW'):
        report=dict(schema='RACE_AI_SAVED_REASON_BINDING_COUNTS_V1', origin='AES_BASE',
                    status=status, counts={name:{key:0 for key in self.COUNTERS}
                        for name in ('observation', 'rejection')}, **self.FLAGS)
        if status=='BINDING_INCONSISTENCY_FOUND':
            report['counts']['observation']['missing_active_anchor']=1
        if status=='HOLD':
            report.update(reason='INPUT_OR_GUARD_INVALID', counts=None)
        return report

    def assert_safe(self, report):
        self.assertIs(type(report), dict)
        self.assertEqual(report['schema'], 'RACE_AI_SAVED_REASON_BINDING_COUNTS_V1')
        self.assertEqual(report['origin'], 'AES_BASE')
        for key, value in self.FLAGS.items():
            self.assertIs(type(report[key]), type(value), key)
            self.assertEqual(report[key], value, key)
        rendered=json.dumps(report, allow_nan=False, sort_keys=True)
        for forbidden in ('private-', 'https://', 'Traceback', 'UNLISTED_OWNER_CREDENTIAL',
                          'RACE_AI_STATE_KEY', 'private_payload', 'owner_key', 'records'):
            self.assertNotIn(forbidden, rendered)
        self.assertFalse({'view', 'guard', 'environment', 'event', 'exception',
                          'traceback', 'url', 'key'} & set(report))

    def assert_hold(self, report, reason=None, authenticated=False):
        self.assert_safe(report)
        self.assertEqual(report['status'], 'HOLD')
        self.assertIsNone(report['counts'])
        self.assertIs(report['authenticated_base'], authenticated)
        if reason is not None:
            self.assertEqual(report['reason'], reason)
        else:
            self.assertRegex(report['reason'], r'^[A-Z][A-Z0-9_]{0,63}$')
        if not authenticated:
            self.assertIsNone(report.get('generation'))
            self.assertIsNone(report.get('snapshot_sha'))

    def invoke(self, environment=None, event=None, *, load_base=None, diagnostic=None):
        output, errors=io.StringIO(), io.StringIO()
        value=self.base()
        reader=load_base if load_base is not None else lambda:value
        result=self.diagnostic() if diagnostic is None else diagnostic
        with patch.object(audit, 'diagnose_view', return_value=result) as diagnose, \
                redirect_stdout(output), redirect_stderr(errors):
            report=audit.run_audit(self.environment() if environment is None else environment,
                self.event() if event is None else event, load_base=reader)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(errors.getvalue(), '')
        return report, diagnose

    def test_trusted_main_uses_only_no_argument_reader_and_exact_aes_base_diagnostic(self):
        for status in ('NO_BINDING_INCONSISTENCY_IN_THIS_VIEW', 'BINDING_INCONSISTENCY_FOUND'):
            with self.subTest(status=status):
                base=self.base(); original=deepcopy(base['view']); calls=[]
                def reader():
                    calls.append('reader')
                    return base
                expected=self.diagnostic(status)
                report, diagnose=self.invoke(load_base=reader, diagnostic=expected)
                self.assert_safe(report)
                self.assertEqual(report['status'], status)
                self.assertIs(report['authenticated_base'], True)
                self.assertEqual(report['generation'], 9)
                self.assertEqual(report['snapshot_sha'], self.SNAPSHOT)
                self.assertEqual(report['counts'], expected['counts'])
                self.assertEqual(calls, ['reader'])
                diagnose.assert_called_once_with(base['view'], guard=self.guard, origin='AES_BASE')
                self.assertEqual(base['view'], original)

    def test_each_untrusted_context_holds_before_reader_or_diagnostic(self):
        cases=[]
        for key, bad in (
                ('GITHUB_ACTIONS', True), ('GITHUB_ACTIONS', 'false'),
                ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                ('GITHUB_REPOSITORY', 'foreign/RACE-AI'), ('GITHUB_REPOSITORY_ID', '7'),
                ('GITHUB_REPOSITORY_ID', 1416489937), ('GITHUB_REF', 'refs/heads/feature'),
                ('GITHUB_SHA', 'A'*40), ('GITHUB_SHA', 'a'*39),
                ('GITHUB_WORKFLOW_REF', 'haji84/RACE-AI/.github/workflows/other.yml@refs/heads/main')):
            env=self.environment(); env[key]=bad; cases.append((env, self.event()))
        for key in ('GITHUB_ACTIONS', 'GITHUB_SHA', 'GITHUB_WORKFLOW_REF'):
            env=self.environment(); env.pop(key); cases.append((env, self.event()))
        for path, bad in (
                (('ref',), 'refs/heads/feature'), (('after',), 'b'*40),
                (('head_commit', 'id'), 'b'*40), (('head_commit', 'message'), 'untrusted-prefix'),
                (('head_commit', 'message'), None), (('repository', 'id'), True),
                (('repository', 'id'), '1416489937'), (('repository', 'full_name'), 'foreign/RACE-AI'),
                (('repository', 'private'), True), (('repository', 'private'), 0),
                (('repository', 'private'), None)):
            event=self.event(); target=event
            for key in path[:-1]:target=target[key]
            target[path[-1]]=bad; cases.append((self.environment(), event))
        cases.extend([(self.environment(), {}), (self.environment(), None), ({}, self.event())])
        for index, (environment, event) in enumerate(cases):
            with self.subTest(case=index):
                calls=[]
                def reader():
                    calls.append('forbidden')
                    raise AssertionError('private-reader-sentinel')
                # None is a deliberately invalid event, not invoke()'s default.
                output, errors=io.StringIO(), io.StringIO()
                with patch.object(audit, 'diagnose_view') as diagnose, \
                        redirect_stdout(output), redirect_stderr(errors):
                    report=audit.run_audit(environment, event, load_base=reader)
                self.assert_hold(report, 'TRUSTED_MAIN_REQUIRED')
                self.assertEqual(calls, [])
                diagnose.assert_not_called()
                self.assertEqual(output.getvalue()+errors.getvalue(), '')

    def test_reader_exceptions_are_static_private_holds_without_authentication_metadata(self):
        for failure in (RuntimeError('private-key-sentinel https://private-owner.invalid/'),
                        ValueError('private-cipher-sentinel'),
                        OSError('private-event-path-sentinel')):
            with self.subTest(error_type=type(failure).__name__):
                calls=[]
                def reader():
                    calls.append('reader')
                    raise failure
                report, diagnose=self.invoke(load_base=reader)
                self.assert_hold(report, 'AUTHENTICATED_BASE_UNAVAILABLE')
                self.assertEqual(calls, ['reader'])
                diagnose.assert_not_called()

    def test_malformed_authenticated_base_never_reaches_the_diagnostic(self):
        values=[None, [], self.base(generation=0), self.base(generation=-1),
            self.base(generation=True), self.base(generation=1.0), self.base(generation='9'),
            self.base(snapshot_sha='A'*40), self.base(snapshot_sha='a'*39),
            self.base(snapshot_sha='g'*40), self.base(snapshot_sha=None),
            self.base(view=[]), self.base(view=None), self.base(guard=None)]
        missing=self.base(); missing.pop('generation'); values.append(missing)
        for index, value in enumerate(values):
            with self.subTest(case=index):
                report, diagnose=self.invoke(load_base=lambda:value)
                self.assert_hold(report, 'AUTHENTICATED_BASE_UNAVAILABLE')
                diagnose.assert_not_called()

    def test_authenticated_base_remains_authenticated_when_pure_diagnostic_returns_hold(self):
        report, diagnose=self.invoke(diagnostic=self.diagnostic('HOLD'))
        self.assert_hold(report, 'INPUT_OR_GUARD_INVALID', authenticated=True)
        self.assertEqual(report['generation'], 9)
        self.assertEqual(report['snapshot_sha'], self.SNAPSHOT)
        diagnose.assert_called_once()

    def test_cli_overrides_stop_before_environment_event_or_reader_access_without_argparse_echo(self):
        class LockedEnvironment(dict):
            def __init__(self):
                super().__init__(); self.reads=[]
            def get(self, key, *args):
                self.reads.append(key); raise AssertionError('private-env-read-sentinel')
            def __getitem__(self, key):
                self.reads.append(key); raise AssertionError('private-env-read-sentinel')
            def __iter__(self):
                self.reads.append('iteration'); raise AssertionError('private-env-read-sentinel')
        for argv in (['--generation','999'], ['--snapshot-sha','f'*40],
                     ['--owner-key','private-key-sentinel'], None):
            with self.subTest(argv_kind='sys.argv' if argv is None else argv[0]):
                environment=LockedEnvironment(); output, errors=io.StringIO(), io.StringIO()
                with patch.object(audit.os, 'environ', environment), \
                        patch.object(sys, 'argv', ['audit','--private-cli-sentinel']), \
                        patch.object(audit, '_load_authenticated_base') as reader, \
                        patch.object(Path, 'read_text') as read_text, \
                        patch.object(Path, 'read_bytes') as read_bytes, \
                        patch('builtins.open') as opened, \
                        redirect_stdout(output), redirect_stderr(errors):
                    code=audit.main(argv)
                self.assertEqual(code, 2)
                self.assertEqual(errors.getvalue(), '')
                self.assertEqual(len(output.getvalue().splitlines()), 1)
                self.assert_hold(json.loads(output.getvalue()))
                self.assertEqual(environment.reads, [])
                reader.assert_not_called(); read_text.assert_not_called()
                read_bytes.assert_not_called(); opened.assert_not_called()

    def test_cli_empty_arguments_reads_only_event_context_and_mocked_authenticated_base(self):
        with tempfile.TemporaryDirectory() as folder:
            event_path=Path(folder)/'private-event-path-sentinel.json'
            event_path.write_text(json.dumps(self.event()), encoding='utf-8')
            for status in ('NO_BINDING_INCONSISTENCY_IN_THIS_VIEW',
                           'BINDING_INCONSISTENCY_FOUND', 'HOLD'):
                with self.subTest(status=status):
                    environment=self.environment(); environment['GITHUB_EVENT_PATH']=str(event_path)
                    output, errors=io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, environment, clear=True), \
                            patch.object(audit, '_load_authenticated_base', return_value=self.base()) as reader, \
                            patch.object(audit, 'diagnose_view', return_value=self.diagnostic(status)), \
                            redirect_stdout(output), redirect_stderr(errors):
                        code=audit.main([])
                    self.assertEqual(code, 2 if status=='HOLD' else 0)
                    self.assertEqual(errors.getvalue(), '')
                    self.assertEqual(len(output.getvalue().splitlines()), 1)
                    report=json.loads(output.getvalue()); self.assert_safe(report)
                    self.assertEqual(report['status'], status)
                    self.assertIs(report['authenticated_base'], True)
                    self.assertEqual(report['generation'], 9)
                    self.assertEqual(report['snapshot_sha'], self.SNAPSHOT)
                    if status=='HOLD':self.assertIsNone(report['counts'])
                    reader.assert_called_once_with()

    def test_unreadable_invalid_or_non_object_event_cannot_invoke_authenticated_reader(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); invalid=root/'private-invalid-event-sentinel.json'
            invalid.write_text('private-json-sentinel {', encoding='utf-8')
            non_object=root/'private-non-object-sentinel.json'
            non_object.write_text('[]', encoding='utf-8')
            for path in (root/'private-missing-event-sentinel.json', invalid, non_object):
                with self.subTest(case=path.name):
                    environment=self.environment(); environment['GITHUB_EVENT_PATH']=str(path)
                    output, errors=io.StringIO(), io.StringIO()
                    with patch.dict(os.environ, environment, clear=True), \
                            patch.object(audit, '_load_authenticated_base') as reader, \
                            patch.object(audit, 'diagnose_view') as diagnose, \
                            redirect_stdout(output), redirect_stderr(errors):
                        code=audit.main([])
                    self.assertEqual(code, 2)
                    self.assertEqual(errors.getvalue(), '')
                    self.assertEqual(len(output.getvalue().splitlines()), 1)
                    self.assert_hold(json.loads(output.getvalue()), 'TRUSTED_MAIN_REQUIRED')
                    reader.assert_not_called(); diagnose.assert_not_called()


if __name__ == '__main__':
    unittest.main()
