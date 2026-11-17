"""Invented GitHub metadata only; no dispatch, owner key, model or provider call."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
from urllib.parse import parse_qs, urlsplit

from scripts import boat_main_dispatch_gate as canonical
from scripts import boat_native_safari_dispatch as S


HEAD = '1' * 40
OTHER = '2' * 40
REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
PREFIX = 'boat-owner-release: single-real-session-20261111'
MAIN_PATH = '/repos/haji84/RACE-AI/git/ref/heads/main'
SOURCE_PATH = '/repos/haji84/RACE-AI/git/ref/heads/production/boat-p0-p1-20261111'
RUNS_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/runs'
POST_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/dispatches'
PAYLOAD = {'ref': 'main', 'inputs': {'browser': 'native-safari'}}


def trusted():
    environment = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
        GITHUB_REPOSITORY=REPO, GITHUB_REF='refs/heads/main', GITHUB_SHA=HEAD,
        GITHUB_WORKFLOW_REF=REPO + '/.github/workflows/boat-racer-daily.yml@refs/heads/main')
    event = dict(ref='refs/heads/main', after=HEAD,
        repository=dict(id=REPO_ID, full_name=REPO),
        head_commit=dict(id=HEAD, message=PREFIX + ' | invented source-free acceptance'))
    return environment, event


def row(ident=1, **changes):
    value = dict(id=ident, workflow_id=416758725, event='workflow_dispatch',
        head_sha=HEAD, head_branch='main', status='completed', conclusion='failure',
        repository=dict(id=REPO_ID, full_name=REPO),
        head_repository=dict(id=REPO_ID, full_name=REPO))
    value.update(changes)
    return value


class MetadataAPI:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
        self.pages = {}
        self.fail_at = None
        self.main_reads = self.source_reads = 0
        self.stale_main = self.stale_source = False
        self.main_ref = {'ref': 'refs/heads/main', 'object': {'sha': HEAD}}
        self.source_ref = {'ref': 'refs/heads/production/boat-p0-p1-20261111',
                           'object': {'sha': S.RELEASE_SHA}}
        self.post_result = None

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, copy.deepcopy(body)))
        if self.fail_at == len(self.calls):
            raise TimeoutError('private-sentinel-network-or-response')
        if method == 'GET' and path == MAIN_PATH:
            self.main_reads += 1
            if self.stale_main and self.main_reads > 1:
                return dict(self.main_ref, object={'sha': OTHER})
            return copy.deepcopy(self.main_ref)
        if method == 'GET' and path == SOURCE_PATH:
            self.source_reads += 1
            if self.stale_source and self.source_reads > 1:
                return dict(self.source_ref, object={'sha': OTHER})
            return copy.deepcopy(self.source_ref)
        if method == 'GET' and path.startswith(RUNS_PATH + '?'):
            query = parse_qs(urlsplit(path).query, strict_parsing=True)
            assert set(query) == {'branch', 'event', 'head_sha', 'per_page', 'page'}
            assert query['branch'] == ['main'] and query['event'] == ['workflow_dispatch']
            assert query['head_sha'] == [HEAD] and query['per_page'] == ['100']
            page = int(query['page'][0])
            assert 1 <= page <= 10
            if page in self.pages:
                return copy.deepcopy(self.pages[page])
            return {'total_count': len(self.rows),
                    'workflow_runs': copy.deepcopy(self.rows[(page - 1) * 100:page * 100])}
        if method == 'POST' and path == POST_PATH:
            assert body == PAYLOAD
            return self.post_result
        raise AssertionError('Only fixed GitHub ref/history reads and the fixed dispatch are allowed')

    def posts(self):
        return [call for call in self.calls if call[0] == 'POST']


class NativeSafariDispatchTests(unittest.TestCase):
    def run_caller(self, api=None, environment=None, event=None):
        original_environment, original_event = trusted()
        return S.execute(original_environment if environment is None else environment,
                         original_event if event is None else event,
                         request=api if api is not None else MetadataAPI())

    def hold(self, api, environment=None, event=None, attempted=False):
        with self.assertRaises(S.DispatchHold) as caught:
            self.run_caller(api, environment, event)
        report = S.failure_report(caught.exception)
        self.assertIs(report['dispatch_requested'], None if attempted else False)
        self.assertIs(report['request_attempted'], attempted)
        self.assertFalse(report['request_acknowledged'])
        self.assertFalse(report['native_verification_proven'])
        self.assertEqual(report['official_provider_gets'], 0)
        self.assertFalse(report['owner_key_read'])
        self.assertNotIn('sentinel', json.dumps(report))
        return report

    def test_fresh_trusted_main_requests_exact_existing_native_workflow_once(self):
        self.assertEqual(S.RELEASE_SHA, canonical.RELEASE_SHA)
        api = MetadataAPI()
        report = self.run_caller(api)
        self.assertEqual(api.posts(), [('POST', POST_PATH, PAYLOAD)])
        self.assertEqual(api.main_reads, 2)
        self.assertEqual(api.source_reads, 2)
        self.assertEqual(report['status'], 'NATIVE_SAFARI_DISPATCH_REQUESTED')
        self.assertTrue(report['dispatch_requested'])
        self.assertTrue(report['request_attempted'])
        self.assertTrue(report['request_acknowledged'])
        self.assertFalse(report['native_verification_proven'])
        self.assertEqual(report['existing_runs_count'], 0)
        self.assertEqual(report['official_provider_gets'], 0)
        self.assertFalse(report['owner_key_read'])

    def test_wrong_context_prefix_repository_and_head_refuse_before_any_request(self):
        environment, event = trusted()
        bad_environments = [dict(environment, **change) for change in (
            {'GITHUB_ACTIONS': 'false'}, {'GITHUB_EVENT_NAME': 'schedule'},
            {'GITHUB_EVENT_NAME': 'workflow_run'}, {'GITHUB_EVENT_NAME': 'pull_request'},
            {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'GITHUB_REPOSITORY': 'foreign/repo'},
            {'GITHUB_REF': 'refs/heads/other'}, {'GITHUB_SHA': 'private-sentinel'},
            {'GITHUB_WORKFLOW_REF': 'foreign/private-sentinel'})]
        for changed in bad_environments:
            with self.subTest(context=tuple(k for k in changed if changed[k] != environment.get(k))):
                api = MetadataAPI()
                self.hold(api, changed, event)
                self.assertEqual(api.calls, [])
        bad_events = [[], {}, dict(event, ref='refs/heads/other'),
            dict(event, after=OTHER), dict(event, repository={'id': REPO_ID, 'full_name': 'foreign/repo'}),
            dict(event, repository={'id': True, 'full_name': REPO}),
            dict(event, head_commit=dict(id=OTHER, message=PREFIX)),
            dict(event, head_commit=dict(id=HEAD, message='ordinary private-sentinel')),
            dict(event, head_commit=dict(id=HEAD, message='x ' + PREFIX)),
            dict(event, head_commit=dict(id=HEAD, message=None))]
        for changed in bad_events:
            with self.subTest(event_type=type(changed).__name__):
                api = MetadataAPI()
                self.hold(api, environment, changed)
                self.assertEqual(api.calls, [])

    def test_current_main_or_canonical_source_mismatch_never_posts(self):
        for field, changed in (
            ('main_ref', {'ref': 'refs/heads/main', 'object': {'sha': OTHER}}),
            ('main_ref', {'ref': 'refs/heads/other', 'object': {'sha': HEAD}}),
            ('main_ref', {'object': {'sha': HEAD}}),
            ('source_ref', {'ref': 'refs/heads/production/boat-p0-p1-20261111', 'object': {'sha': OTHER}}),
            ('source_ref', {'ref': 'refs/heads/other', 'object': {'sha': S.RELEASE_SHA}}),
            ('source_ref', {'ref': 'refs/heads/production/boat-p0-p1-20261111', 'object': None})):
            api = MetadataAPI()
            setattr(api, field, changed)
            self.hold(api)
            self.assertEqual(api.posts(), [])
        for field in ('stale_main', 'stale_source'):
            api = MetadataAPI()
            setattr(api, field, True)
            self.hold(api)
            self.assertEqual(api.posts(), [])

    def test_every_existing_status_and_conclusion_blocks_another_request(self):
        for status in ('queued', 'in_progress', 'waiting', 'pending', 'requested', 'completed', 'future_status'):
            for conclusion in (None, 'success', 'failure', 'cancelled', 'timed_out', 'skipped', 'action_required', 'neutral'):
                with self.subTest(status=status, conclusion=conclusion):
                    api = MetadataAPI([row(status=status, conclusion=conclusion)])
                    report = self.run_caller(api)
                    self.assertFalse(report['dispatch_requested'])
                    self.assertFalse(report['request_attempted'])
                    self.assertFalse(report['request_acknowledged'])
                    self.assertEqual(report['status'], 'NATIVE_SAFARI_ALREADY_REQUESTED_FOR_HEAD')
                    self.assertEqual(report['existing_runs_count'], 1)
                    self.assertEqual(api.posts(), [])

    def test_history_is_complete_across_pages_and_never_filters_by_status(self):
        api = MetadataAPI([row(i) for i in range(1, 202)])
        report = self.run_caller(api)
        self.assertEqual(report['existing_runs_count'], 201)
        self.assertEqual(api.posts(), [])
        histories = [path for method, path, _ in api.calls if path.startswith(RUNS_PATH + '?')]
        self.assertEqual(len(histories), 3)
        self.assertEqual([parse_qs(urlsplit(path).query)['page'][0] for path in histories], ['1', '2', '3'])
        self.assertTrue(all('status=' not in path for path in histories))

    def test_partial_counts_duplicate_ids_changed_totals_and_bad_metadata_hold(self):
        for document in ({}, [], {'total_count': True, 'workflow_runs': []},
                {'total_count': -1, 'workflow_runs': []}, {'total_count': 1001, 'workflow_runs': []},
                {'total_count': 1, 'workflow_runs': []},
                {'total_count': 0, 'workflow_runs': [row()]},
                {'total_count': 2, 'workflow_runs': [row(), row()]}):
            api = MetadataAPI()
            api.pages[1] = document
            self.hold(api)
            self.assertEqual(api.posts(), [])
        for changed in ({'id': True}, {'workflow_id': 999}, {'event': 'push'},
                {'head_sha': OTHER}, {'head_branch': 'other'},
                {'repository': {'id': REPO_ID, 'full_name': 'foreign/repo'}},
                {'head_repository': {'id': True, 'full_name': REPO}},
                {'status': []}, {'conclusion': {}}):
            api = MetadataAPI([row(**changed)])
            self.hold(api)
            self.assertEqual(api.posts(), [])
        for second in ({'total_count': 101, 'workflow_runs': []},
                       {'total_count': 100, 'workflow_runs': [row(101)]}):
            api = MetadataAPI([row(i) for i in range(1, 102)])
            api.pages[2] = second
            self.hold(api)
            self.assertEqual(api.posts(), [])

    def test_network_failure_never_retries_including_an_ambiguous_post(self):
        for failing_call in range(1, 7):
            api = MetadataAPI()
            api.fail_at = failing_call
            self.hold(api, attempted=failing_call == 6)
            self.assertEqual(len(api.calls), failing_call)
            self.assertLessEqual(len(api.posts()), 1)
        api = MetadataAPI()
        api.post_result = {'private-sentinel': 'not an empty acknowledged response'}
        self.hold(api, attempted=True)
        self.assertEqual(len(api.posts()), 1)

    def test_unknown_environment_values_owner_keys_and_event_message_are_never_exported(self):
        environment, event = trusted()
        environment.update(HOME='private-sentinel-home', PATH='private-sentinel-path',
            RACE_AI_STATE_KEY='private-sentinel-owner', GH_TOKEN='private-sentinel-token',
            RACE_AI_VIEWER_KEY='private-sentinel-viewer', PRIVATE_SENTINEL_UNKNOWN='private-sentinel')
        forbidden = {'RACE_AI_STATE_KEY', 'RACE_AI_VIEWER_KEY', 'PRIVATE_SENTINEL_UNKNOWN'}
        class ObservedEnvironment(dict):
            def get(self, key, default=None):
                if key in forbidden:
                    raise AssertionError('owner/viewer/unknown values must not be read')
                return super().get(key, default)
            def __getitem__(self, key):
                if key in forbidden:
                    raise AssertionError('owner/viewer/unknown values must not be read')
                return super().__getitem__(key)
        event['head_commit']['message'] = PREFIX + ' | private-sentinel-message'
        api = MetadataAPI()
        report = self.run_caller(api, ObservedEnvironment(environment), event)
        self.assertNotIn('sentinel', json.dumps(report))
        self.assertNotIn('sentinel', json.dumps(api.calls))
        self.assertNotIn('sentinel', json.dumps(S.failure_report(RuntimeError('private-sentinel'))))
        self.assertNotIn('sentinel', json.dumps(S.failure_report(S.DispatchHold('private-sentinel'))))

    def test_http_boundary_rejects_bad_json_nonfinite_duplicates_oversize_and_unacknowledged_post(self):
        class Response:
            status = 200
            def __init__(self, raw, status=200):
                self.raw, self.status = raw, status
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, limit):
                return self.raw[:limit]
        api = S.GitHubAPI('private-sentinel-token')
        for raw in (b'not-json-private-sentinel', b'{"x":1,"x":2}', b'{"x":NaN}',
                    b'{"x":Infinity}', b'x' * (S.MAX_RESPONSE_BYTES + 1)):
            with patch.object(api.opener, 'open', return_value=Response(raw)) as opened:
                with self.assertRaises(S.DispatchHold):
                    api('GET', MAIN_PATH)
                self.assertEqual(opened.call_count, 1)
        for raw, status in ((b'', 200), (b'private-sentinel', 204), (b'', 202)):
            with patch.object(api.opener, 'open', return_value=Response(raw, status)) as opened:
                with self.assertRaises(S.DispatchHold):
                    api('POST', POST_PATH, PAYLOAD)
                self.assertEqual(opened.call_count, 1)
        with patch.object(api.opener, 'open', return_value=Response(b'', 204)) as opened:
            self.assertIsNone(api('POST', POST_PATH, PAYLOAD))
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.github.com' + POST_PATH)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(json.loads(request.data), PAYLOAD)

    def test_http_errors_redirects_and_nonfixed_destinations_never_retry_or_leak(self):
        api = S.GitHubAPI('private-sentinel-token')
        for method, path, body in (('GET', MAIN_PATH, None), ('POST', POST_PATH, PAYLOAD)):
            for status in (400, 403, 404, 409, 429, 500):
                error = urllib.error.HTTPError('https://private-sentinel.invalid', status,
                    'private-sentinel', {}, io.BytesIO(b'private-sentinel'))
                with patch.object(api.opener, 'open', side_effect=error) as opened:
                    with self.assertRaises(S.DispatchHold) as caught:
                        api(method, path, body)
                    self.assertEqual(opened.call_count, 1)
                    report = S.failure_report(caught.exception)
                    self.assertIs(report['dispatch_requested'], None if method == 'POST' else False)
                    self.assertIs(report['request_attempted'], method == 'POST')
                    self.assertFalse(report['request_acknowledged'])
                    self.assertNotIn('sentinel', json.dumps(report))
            with patch.object(api.opener, 'open', side_effect=TimeoutError('private-sentinel')) as opened:
                with self.assertRaises(S.DispatchHold):
                    api(method, path, body)
                self.assertEqual(opened.call_count, 1)
        for method, path, body in (('POST', POST_PATH, {'ref': 'other', 'inputs': {'browser': 'native-safari'}}),
                ('POST', '/repos/foreign/repo/actions/workflows/416758725/dispatches', PAYLOAD),
                ('GET', 'https://private-sentinel.invalid', None),
                ('GET', '/repos/haji84/RACE-AI/actions/secrets', None)):
            with patch.object(api.opener, 'open') as opened, self.assertRaises(S.DispatchHold):
                api(method, path, body)
            opened.assert_not_called()
        redirect = S.NoRedirect()
        with self.assertRaises(S.DispatchHold):
            redirect.redirect_request(None, None, 302, 'private-sentinel', {}, 'https://private-sentinel.invalid')

    def test_main_emits_only_safe_report_on_real_input_path_and_uncertain_post(self):
        environment, event = trusted()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'event.json'
            path.write_text(json.dumps(event))
            environment.update(GITHUB_EVENT_PATH=str(path), GH_TOKEN='private-sentinel-token',
                RACE_AI_STATE_KEY='private-sentinel-owner', HOME='private-sentinel-home')
            api = MetadataAPI()
            api.fail_at = 6
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(S, 'GitHubAPI', return_value=api) as client, \
                    redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(S.main([]), 2)
            client.assert_called_once_with('private-sentinel-token')
            report = json.loads(output.getvalue())
            self.assertIsNone(report['dispatch_requested'])
            self.assertTrue(report['request_attempted'])
            self.assertFalse(report['request_acknowledged'])
            self.assertNotIn('sentinel', output.getvalue())
            self.assertNotIn(str(path), output.getvalue())
            self.assertEqual(len(api.posts()), 1)

    def test_existing_workflow_registers_only_additive_trusted_push_step_after_owner_gate(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/boat-racer-daily.yml').read_text()
        owner = text.split('\n  owner_p0_p1_dispatch:\n', 1)[1]
        name = 'Request native Safari acceptance once for the exact main head'
        self.assertEqual(owner.count(name), 1)
        before, native = owner.split('      - name: ' + name + '\n', 1)
        native, after = native.split('      - name: Install original parser only when a failed owner needs recovery\n', 1)
        self.assertIn('id: owner_gate', before)
        self.assertIn("success() && steps.owner_gate.outcome == 'success'", native)
        for required in ("github.event_name == 'push'", "github.ref == 'refs/heads/main'",
                         "startsWith(github.event.head_commit.message, '" + PREFIX + "')"):
            self.assertIn(required, native)
        self.assertIn('run: python -m scripts.boat_native_safari_dispatch', native)
        self.assertIn('GH_TOKEN: $' + '{{ github.token }}', native)
        self.assertIn('continue-on-error: true', native)
        self.assertEqual(owner.count('continue-on-error: true'), 1)
        self.assertNotIn('RACE_AI_STATE_KEY', native)
        self.assertNotIn('steps.owner_gate.outputs.ready', native)
        self.assertNotIn('always()', native)
        self.assertIn('recovery_required', after)
        self.assertIn("if: steps.owner_gate.outputs.ready == 'true' || steps.recovered_gate.outputs.ready == 'true'", after)
        self.assertIn('scripts/boat_native_safari_dispatch.py', text.split('\n  push:\n', 1)[0])
        self.assertIn('tests/test_boat_native_safari_dispatch.py', text.split('\n  push:\n', 1)[0])
        self.assertIn('tests.test_boat_native_safari_acceptance tests.test_boat_native_safari_dispatch -v', text)


if __name__ == '__main__':
    unittest.main()
