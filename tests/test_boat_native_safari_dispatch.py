"""Invented GitHub metadata only; no dispatch, owner key, model or provider call."""
import ast
import base64
import copy
import hashlib
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

from scripts import boat_main_dispatch_gate as canonical
from scripts import boat_native_safari_dispatch as S


HEAD = '1' * 40
OTHER = '2' * 40
PARENT = '3' * 40
CANDIDATE = '4' * 40
OLD_CANDIDATE = '5' * 40
REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
PREFIX = 'boat-owner-release: single-real-session-20261111'
MAIN_PATH = '/repos/haji84/RACE-AI/git/ref/heads/main'
SOURCE_PATH = '/repos/haji84/RACE-AI/git/ref/heads/production/boat-p0-p1-20261111'
RUNS_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/runs'
POST_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/dispatches'
PAYLOAD = {'ref': 'main', 'inputs': {'browser': 'native-safari'}}
REPOSITORY_PATH = '/repos/haji84/RACE-AI'
WORKFLOW_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725'
NATIVE_WORKFLOW = '.github/workflows/boat-owner-formal-live-pages-proof.yml'
CANDIDATE_STEP = 'Checkout the exact reviewed UI candidate for synthetic capture only'
CANDIDATE_PATH = '.native-safari-ui-candidate'
COMMIT_PATH = '/repos/haji84/RACE-AI/commits/' + HEAD
CURRENT_CONTENTS_PATH = '/repos/haji84/RACE-AI/contents/' + NATIVE_WORKFLOW + '?ref=' + HEAD
PARENT_CONTENTS_PATH = '/repos/haji84/RACE-AI/contents/' + NATIVE_WORKFLOW + '?ref=' + PARENT
FIRST_HISTORY_PATH = RUNS_PATH + '?branch=main&event=workflow_dispatch&head_sha=' + HEAD + '&per_page=100&page=1'
FRESH_CALLS = (
    ('GET', MAIN_PATH, None), ('GET', SOURCE_PATH, None),
    ('GET', REPOSITORY_PATH, None), ('GET', WORKFLOW_PATH, None),
    ('GET', COMMIT_PATH, None), ('GET', CURRENT_CONTENTS_PATH, None),
    ('GET', PARENT_CONTENTS_PATH, None), ('GET', FIRST_HISTORY_PATH, None),
    ('GET', MAIN_PATH, None), ('GET', SOURCE_PATH, None),
    ('POST', POST_PATH, PAYLOAD),
)


def candidate_workflow(candidate=CANDIDATE):
    return (
        'name: Existing native Safari acceptance\n'
        'on:\n'
        '  workflow_dispatch:\n'
        '    inputs:\n'
        '      browser:\n'
        '        default: native-safari\n'
        'jobs:\n'
        '  acceptance:\n'
        '    runs-on: macos-latest\n'
        '    steps:\n'
        '      - name: ' + CANDIDATE_STEP + '\n'
        '        uses: actions/checkout@v4\n'
        '        with:\n'
        '          ref: ' + candidate + '\n'
        '          path: ' + CANDIDATE_PATH + '\n'
        '      - name: Existing synthetic evidence upload\n'
        '        uses: actions/upload-artifact@v4\n'
        '        with:\n'
        '          name: synthetic-native-safari-' + candidate[:8] + '\n'
        '          path: synthetic-native-safari\n'
    )


def contents_document(text):
    raw = text.encode('utf-8')
    return dict(type='file', path=NATIVE_WORKFLOW, encoding='base64',
        size=len(raw), sha=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
        content='\n'.join(textwrap.wrap(base64.b64encode(raw).decode('ascii'), 60)) + '\n')


def trusted():
    environment = dict(GITHUB_ACTIONS='true', GITHUB_EVENT_NAME='push',
        GITHUB_REPOSITORY=REPO, GITHUB_REF='refs/heads/main', GITHUB_SHA=HEAD,
        GITHUB_WORKFLOW_REF=REPO + '/.github/workflows/boat-racer-daily.yml@refs/heads/main',
        GITHUB_RUN_ATTEMPT='1')
    event = dict(ref='refs/heads/main', after=HEAD,
        repository=dict(id=REPO_ID, full_name=REPO, private=False),
        head_commit=dict(id=HEAD, message=PREFIX + ' | invented source-free acceptance'))
    return environment, event


def row(ident=1, **changes):
    value = dict(id=ident, workflow_id=416758725, event='workflow_dispatch',
        head_sha=HEAD, head_branch='main', status='completed', conclusion='failure',
        repository=dict(id=REPO_ID, full_name=REPO, private=False),
        head_repository=dict(id=REPO_ID, full_name=REPO, private=False))
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
        self.repository_metadata = dict(id=REPO_ID, full_name=REPO, private=False)
        self.workflow_metadata = dict(id=416758725, path=NATIVE_WORKFLOW, state='active')
        self.commit_metadata = dict(sha=HEAD, parents=[{'sha': PARENT}, {'sha': OTHER}])
        self.current_contents = contents_document(candidate_workflow())
        self.parent_contents = contents_document(candidate_workflow(OLD_CANDIDATE))
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
        if method == 'GET' and path in (REPOSITORY_PATH, WORKFLOW_PATH, COMMIT_PATH,
                                        CURRENT_CONTENTS_PATH, PARENT_CONTENTS_PATH):
            field = {REPOSITORY_PATH: 'repository_metadata', WORKFLOW_PATH: 'workflow_metadata',
                COMMIT_PATH: 'commit_metadata', CURRENT_CONTENTS_PATH: 'current_contents',
                PARENT_CONTENTS_PATH: 'parent_contents'}[path]
            return copy.deepcopy(getattr(self, field))
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
        raise AssertionError('Only fixed GitHub metadata/ref/history reads and the fixed dispatch are allowed')

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
        self.assertEqual(api.calls, list(FRESH_CALLS))
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
        api = MetadataAPI([row(i) for i in range(1, 1001)])
        report = self.run_caller(api)
        self.assertEqual(report['existing_runs_count'], 1000)
        self.assertEqual(api.posts(), [])
        histories = [path for method, path, _ in api.calls if path.startswith(RUNS_PATH + '?')]
        self.assertEqual(len(histories), 10)
        self.assertEqual(parse_qs(urlsplit(histories[-1]).query)['page'], ['10'])

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
        for changed in ({'id': True}, {'id': 0}, {'id': -1}, {'id': 2**63},
                {'workflow_id': True}, {'workflow_id': 999}, {'event': 'push'},
                {'head_sha': OTHER}, {'head_branch': 'other'},
                {'repository': {'id': REPO_ID, 'full_name': 'foreign/repo'}},
                {'head_repository': {'id': True, 'full_name': REPO}},
                {'status': []}, {'conclusion': {}}):
            api = MetadataAPI([row(**changed)])
            self.hold(api)
            self.assertEqual(api.posts(), [])
        for second in ({'total_count': 101, 'workflow_runs': []},
                       {'total_count': 100, 'workflow_runs': [row(101)]},
                       {'total_count': 101, 'workflow_runs': [row(1)]}):
            api = MetadataAPI([row(i) for i in range(1, 102)])
            api.pages[2] = second
            self.hold(api)
            self.assertEqual(api.posts(), [])

    def test_network_failure_never_retries_including_an_ambiguous_post(self):
        for failing_call in range(1, len(FRESH_CALLS) + 1):
            api = MetadataAPI()
            api.fail_at = failing_call
            self.hold(api, attempted=failing_call == len(FRESH_CALLS))
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
                    b'{"x":Infinity}', b'{"x":1e999}', b'x' * (S.MAX_RESPONSE_BYTES + 1)):
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
            api.fail_at = len(FRESH_CALLS)
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

    def test_existing_workflow_registers_only_additive_trusted_push_step_after_owner_dispatch(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/boat-racer-daily.yml').read_text()
        owner = text.split('\n  owner_p0_p1_dispatch:\n', 1)[1]
        name = 'Request native Safari acceptance once for the exact main head'
        self.assertEqual(owner.count(name), 1)
        before, native = owner.split('      - name: ' + name + '\n', 1)
        self.assertIn('name: Dispatch only the existing owner P0/P1 workflow', before)
        self.assertIn("echo 'DISPATCH_REQUESTED_REAL_P0_P1_NOT_YET_PROVEN'", before)
        self.assertNotIn('\n      - name:', native)
        self.assertFalse(any(line.startswith('  ') and not line.startswith('    ')
                             for line in native.splitlines()))
        self.assertIn('id: owner_gate', before)
        self.assertIn("success() && steps.owner_gate.outcome == 'success'", native)
        for required in ("github.event_name == 'push'", "github.ref == 'refs/heads/main'",
                         "startsWith(github.event.head_commit.message, '" + PREFIX + "')"):
            self.assertIn(required, native)
        self.assertRegex(native, r"github\.run_attempt == (?:1|'1')")
        self.assertIn('from scripts.boat_native_safari_dispatch import main', native)
        self.assertIn('main([])', native)
        self.assertNotIn('SystemExit', native)
        self.assertIn('GH_TOKEN: $' + '{{ github.token }}', native)
        self.assertIn('continue-on-error: true', native)
        self.assertEqual(owner.count('continue-on-error: true'), 1)
        self.assertNotIn('RACE_AI_STATE_KEY', native)
        self.assertNotIn('steps.owner_gate.outputs.ready', native)
        self.assertNotIn('always()', native)
        self.assertIn('recovery_required', before)
        self.assertIn("if: steps.owner_gate.outputs.ready == 'true' || steps.recovered_gate.outputs.ready == 'true'", before)
        recovery = (Path(__file__).resolve().parents[1] /
                    '.github/workflows/boat-main-recovery-contract.yml').read_text()
        pull_request = re.search(r'^  pull_request:\n((?:    [^\n]*\n|\n)*)',
                                 recovery, re.MULTILINE)
        self.assertIsNotNone(pull_request)
        for path in ('scripts/boat_native_safari_dispatch.py',
                     'tests/test_boat_native_safari_dispatch.py'):
            self.assertEqual(pull_request.group(1).count(path), 1)
            self.assertNotIn(path, text.split('\njobs:\n', 1)[0])
        commands = [line for line in recovery.splitlines() if 'python -m unittest ' in line]
        self.assertEqual(len(commands), 1)
        self.assertIn('tests.test_boat_native_safari_dispatch', commands[0])
        self.assertTrue(commands[0].endswith(' -v'))


    def test_rerun_or_missing_attempt_refuses_before_any_metadata_read(self):
        environment, event = trusted()
        for attempt in ('2', '01', '0', '', None, 1, True, 'private-sentinel'):
            api = MetadataAPI()
            changed = dict(environment, GITHUB_RUN_ATTEMPT=attempt)
            report = self.hold(api, changed, event)
            self.assertEqual(report['reason'], 'TRUSTED_RELEASE_PUSH_REQUIRED')
            self.assertEqual(api.calls, [])
        api = MetadataAPI()
        del environment['GITHUB_RUN_ATTEMPT']
        self.hold(api, environment, event)
        self.assertEqual(api.calls, [])

    def test_existing_public_repository_and_active_fixed_native_workflow_required(self):
        for document in ({}, [], dict(id=True, full_name=REPO, private=False),
                dict(id=REPO_ID, full_name='foreign/repo', private=False),
                dict(id=REPO_ID, full_name=REPO, private=True),
                dict(id=REPO_ID, full_name=REPO, private=0),
                dict(id=REPO_ID, full_name=REPO)):
            api = MetadataAPI()
            api.repository_metadata = document
            report = self.hold(api)
            self.assertEqual(report['reason'], 'EXISTING_NATIVE_WORKFLOW_REQUIRED')
            self.assertEqual(api.posts(), [])
        for document in ({}, [], dict(id=True, path=NATIVE_WORKFLOW, state='active'),
                dict(id=416758725, path='.github/workflows/foreign.yml', state='active'),
                dict(id=416758725, path=NATIVE_WORKFLOW, state='disabled_manually'),
                dict(id=416758725, path=NATIVE_WORKFLOW, state='private-sentinel'),
                dict(id=416758725, path=NATIVE_WORKFLOW)):
            api = MetadataAPI()
            api.workflow_metadata = document
            report = self.hold(api)
            self.assertEqual(report['reason'], 'EXISTING_NATIVE_WORKFLOW_REQUIRED')
            self.assertEqual(api.posts(), [])

    def test_commit_proof_requires_exact_head_and_complete_unique_parent_metadata(self):
        for document in ({}, [], dict(sha=OTHER, parents=[{'sha': PARENT}]),
                dict(sha=HEAD, parents=[]), dict(sha=HEAD, parents=None),
                dict(sha=HEAD, parents=[None]), dict(sha=HEAD, parents=[{}]),
                dict(sha=HEAD, parents=[{'sha': 'main'}]),
                dict(sha=HEAD, parents=[{'sha': True}]),
                dict(sha=HEAD, parents=[{'sha': 'A' * 40}]),
                dict(sha=HEAD, parents=[{'sha': PARENT}, {'sha': PARENT}]),
                dict(sha=HEAD, parents=[{'sha': PARENT}, {'sha': 'private-sentinel'}]),
                dict(sha=HEAD, parents=[{'sha': PARENT}, {'sha': OTHER}, {'sha': '6' * 40}])):
            api = MetadataAPI()
            api.commit_metadata = document
            report = self.hold(api)
            self.assertEqual(report['reason'], 'CANDIDATE_CHANGE_PROOF_INVALID')
            self.assertEqual(api.posts(), [])
        for parents in ([{'sha': PARENT}], [{'sha': PARENT}, {'sha': OTHER}]):
            api = MetadataAPI()
            api.commit_metadata['parents'] = parents
            self.assertTrue(self.run_caller(api)['request_acknowledged'])
            contents = [path for method, path, _ in api.calls if '/contents/' in path]
            self.assertEqual(contents, [CURRENT_CONTENTS_PATH, PARENT_CONTENTS_PATH])
            self.assertEqual(len(api.posts()), 1)

    def test_candidate_contents_require_complete_verified_fixed_path_file_metadata(self):
        original = contents_document(candidate_workflow())
        documents = [{}, [], dict(original, type='symlink'),
            dict(original, path='.github/workflows/foreign.yml'),
            dict(original, encoding='utf-8'), dict(original, content='private-sentinel-not-base64'),
            dict(original, content='!!!!'), dict(original, content=123), dict(original, content=''),
            dict(original, sha='0' * 40), dict(original, sha=True),
            dict(original, sha='private-sentinel'), dict(original, size=True),
            dict(original, size=original['size'] + 1)]
        for field in ('type', 'path', 'encoding', 'content', 'sha', 'size'):
            missing = dict(original)
            del missing[field]
            documents.append(missing)
        for target in ('current_contents', 'parent_contents'):
            for document in documents:
                api = MetadataAPI()
                setattr(api, target, document)
                report = self.hold(api)
                self.assertEqual(report['reason'], 'CANDIDATE_CHANGE_PROOF_INVALID')
                self.assertEqual(api.posts(), [])
        for raw in (b'\xff', b'', b'x' * (S.MAX_RESPONSE_BYTES + 1)):
            document = dict(original, size=len(raw),
                content=base64.b64encode(raw).decode('ascii'),
                sha=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())
            api = MetadataAPI()
            api.current_contents = document
            self.hold(api)
            self.assertEqual(api.posts(), [])

    def test_candidate_checkout_requires_one_exact_label_path_and_immutable_sha(self):
        valid = candidate_workflow()
        documents = [
            valid.replace(CANDIDATE_STEP, 'private-sentinel-unrelated-step'),
            valid + valid[valid.index('      - name: ' + CANDIDATE_STEP):],
            valid.replace('          path: ' + CANDIDATE_PATH, '          path: unrelated'),
            valid.replace('          path: ' + CANDIDATE_PATH, '          path: ../private-sentinel'),
            valid.replace('          ref: ' + CANDIDATE, '          ref: main'),
            valid.replace('          ref: ' + CANDIDATE, '          ref: ' + CANDIDATE[:8]),
            valid.replace('          ref: ' + CANDIDATE, '          ref: ' + 'A' * 40),
            valid.replace('          ref: ' + CANDIDATE, '          ref: 
    unittest.main()
 + '{{ github.sha }}'),
            valid.replace('          ref: ' + CANDIDATE, '          ref: ' + CANDIDATE + '\n          ref: ' + OLD_CANDIDATE),
            valid.replace('          path: ' + CANDIDATE_PATH, '          path: ' + CANDIDATE_PATH + '\n          path: unrelated'),
            valid.replace('        uses: actions/checkout@v4', '        uses: foreign/private-sentinel@v4'),
            valid.replace('          ref: ' + CANDIDATE + '\n', ''),
        ]
        for target in ('current_contents', 'parent_contents'):
            for document in documents:
                api = MetadataAPI()
                setattr(api, target, contents_document(document))
                report = self.hold(api)
                self.assertEqual(report['reason'], 'CANDIDATE_CHANGE_PROOF_INVALID')
                self.assertEqual(api.posts(), [])

    def test_only_candidate_sha_and_its_artifact_prefix_may_change(self):
        # The two valid fixtures differ in the reviewed 40-SHA and its 8-prefix.
        api = MetadataAPI()
        self.assertTrue(self.run_caller(api)['request_acknowledged'])
        original = candidate_workflow()
        changed_workflows = [
            original.replace('runs-on: macos-latest', 'runs-on: macos-14'),
            original.replace('    runs-on: macos-latest\n', '    runs-on: macos-latest\n    timeout-minutes: 60\n'),
            original.replace('jobs:\n', 'permissions:\n  actions: write\njobs:\n'),
            original.replace('  workflow_dispatch:\n', "  push:\n  workflow_dispatch:\n"),
            original.replace('      browser:\n', '      extra-input:\n        default: private-sentinel\n      browser:\n'),
            original.replace('jobs:\n', 'jobs:\n  extra:\n    runs-on: ubuntu-latest\n    steps: []\n'),
            original.replace('        default: native-safari', '        default: chromium'),
            original.replace('        uses: actions/upload-artifact@v4', '        uses: actions/upload-artifact@v3'),
            original + '# private-sentinel-unrelated-change\n',
        ]
        for changed in changed_workflows:
            api = MetadataAPI()
            api.current_contents = contents_document(changed)
            report = self.hold(api)
            self.assertEqual(report['reason'], 'CANDIDATE_CHANGE_PROOF_INVALID')
            self.assertEqual(api.posts(), [])

    def test_unchanged_candidate_is_static_skip_without_history_or_post(self):
        api = MetadataAPI()
        api.parent_contents = contents_document(candidate_workflow())
        report = self.run_caller(api)
        self.assertEqual(report, {
            'status': 'NATIVE_SAFARI_CANDIDATE_UNCHANGED',
            'dispatch_requested': False, 'request_attempted': False,
            'request_acknowledged': False, 'existing_runs_count': None,
            'native_verification_proven': False, 'official_provider_gets': 0,
            'owner_key_read': False})
        self.assertEqual(api.calls, list(FRESH_CALLS[:7]))
        self.assertEqual(api.posts(), [])

    def test_unchanged_candidate_cannot_hide_invalid_metadata_or_other_workflow_changes(self):
        for document in (dict(contents_document(candidate_workflow()), sha='0' * 40),
                contents_document(candidate_workflow().replace('runs-on: macos-latest', 'runs-on: macos-14'))):
            api = MetadataAPI()
            api.parent_contents = document
            report = self.hold(api)
            self.assertEqual(report['reason'], 'CANDIDATE_CHANGE_PROOF_INVALID')
            self.assertEqual(api.posts(), [])

    def test_http_metadata_reads_are_authenticated_and_only_fixed_paths(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, limit):
                return b'{}'
        api = S.GitHubAPI('private-sentinel-token')
        for path in (REPOSITORY_PATH, WORKFLOW_PATH, COMMIT_PATH,
                     CURRENT_CONTENTS_PATH, PARENT_CONTENTS_PATH):
            with patch.object(api.opener, 'open', return_value=Response()) as opened:
                self.assertEqual(api('GET', path), {})
            request = opened.call_args.args[0]
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.full_url, 'https://api.github.com' + path)
            self.assertIsNone(request.data)
            self.assertEqual(request.get_header('Authorization'), 'Bearer private-sentinel-token')
            self.assertEqual(request.get_header('Accept'), 'application/vnd.github+json')
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(opened.call_args.kwargs, {'timeout': 5})
        for path in (
                '/repos/foreign/repo', WORKFLOW_PATH + '/dispatches',
                '/repos/haji84/RACE-AI/actions/workflows/416758726',
                '/repos/haji84/RACE-AI/commits/main',
                '/repos/haji84/RACE-AI/contents/.github/workflows/foreign.yml?ref=' + HEAD,
                '/repos/haji84/RACE-AI/contents/' + NATIVE_WORKFLOW + '?ref=main',
                CURRENT_CONTENTS_PATH + '&private-sentinel=1',
                CURRENT_CONTENTS_PATH.replace(HEAD, 'A' * 40),
                '/repos/haji84/RACE-AI/contents/' + NATIVE_WORKFLOW + '?ref=' + HEAD + '%0a'):
            with patch.object(api.opener, 'open') as opened, self.assertRaises(S.DispatchHold):
                api('GET', path)
            opened.assert_not_called()
        for body in (dict(PAYLOAD, extra='private-sentinel'),
                {'ref': 'main', 'inputs': {'browser': 'native-safari', 'extra': 'private-sentinel'}},
                {'ref': HEAD, 'inputs': {'browser': 'native-safari'}},
                {'ref': 'main', 'inputs': {'browser': 'chromium'}}):
            with patch.object(api.opener, 'open') as opened, self.assertRaises(S.DispatchHold):
                api('POST', POST_PATH, body)
            opened.assert_not_called()

    def test_default_proxy_policy_is_preserved_with_redirect_rejection(self):
        environment = {'https_proxy': 'http://private-sentinel-proxy.invalid:8123',
                       'no_proxy': 'localhost,127.0.0.1'}
        with patch.dict(os.environ, environment, clear=True):
            api = S.GitHubAPI('private-sentinel-token')
        proxy_handlers = [handler for handler in api.opener.handlers
                          if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies.get('https'),
                         'http://private-sentinel-proxy.invalid:8123')
        self.assertEqual(proxy_handlers[0].proxies.get('no'), 'localhost,127.0.0.1')
        redirects = [handler for handler in api.opener.handlers if isinstance(handler, S.NoRedirect)]
        self.assertEqual(len(redirects), 1)
        with self.assertRaises(S.DispatchHold):
            redirects[0].redirect_request(None, None, 307, 'private-sentinel', {},
                'https://private-sentinel.invalid')

    def test_post_response_read_status_or_close_failures_never_retry_or_claim_ack(self):
        class Response:
            status = 204
            def __init__(self, failure):
                self.failure = failure
            def __enter__(self):
                if self.failure == 'enter':
                    raise TimeoutError('private-sentinel')
                return self
            def __exit__(self, *args):
                if self.failure == 'exit':
                    raise TimeoutError('private-sentinel')
            def read(self, limit):
                if self.failure == 'read':
                    raise TimeoutError('private-sentinel')
                return b''
        class BrokenStatus(Response):
            @property
            def status(self):
                raise ValueError('private-sentinel')
        api = S.GitHubAPI('private-sentinel-token')
        for response in (Response('enter'), Response('read'), Response('exit'), BrokenStatus(None)):
            with patch.object(api.opener, 'open', return_value=response) as opened:
                with self.assertRaises(S.DispatchHold) as caught:
                    api('POST', POST_PATH, PAYLOAD)
            self.assertEqual(opened.call_count, 1)
            report = S.failure_report(caught.exception)
            self.assertIsNone(report['dispatch_requested'])
            self.assertTrue(report['request_attempted'])
            self.assertFalse(report['request_acknowledged'])
            self.assertEqual(report['reason'], 'DISPATCH_ACK_UNCERTAIN')
            self.assertNotIn('sentinel', json.dumps(report))

    def test_optional_wrapper_preserves_hold_without_exiting_successful_core(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/boat-racer-daily.yml').read_text()
        native = text.split('      - name: Request native Safari acceptance once for the exact main head\n', 1)[1]
        run_lines = native.split('        run: |\n', 1)[1].splitlines()
        block = []
        for line in run_lines:
            if line and not line.startswith('          '):
                break
            block.append(line)
        lines = textwrap.dedent('\n'.join(block)).strip().splitlines()
        self.assertEqual(lines[0], "python - <<'PY'")
        self.assertEqual(lines[-1], 'PY')
        script = '\n'.join(lines[1:-1]) + '\n'
        parsed = ast.parse(script)
        self.assertEqual(len(parsed.body), 2)
        self.assertIsInstance(parsed.body[0], ast.ImportFrom)
        self.assertEqual(parsed.body[0].module, 'scripts.boat_native_safari_dispatch')
        self.assertEqual([alias.name for alias in parsed.body[0].names], ['main'])
        self.assertIsInstance(parsed.body[1], ast.Expr)
        self.assertIsInstance(parsed.body[1].value, ast.Call)
        self.assertIsInstance(parsed.body[1].value.func, ast.Name)
        self.assertEqual(parsed.body[1].value.func.id, 'main')
        for return_code in (0, 2):
            output = io.StringIO()
            def invoke(argv):
                self.assertEqual(argv, [])
                print('{"status":"NATIVE_SAFARI_DISPATCH_HOLD"}')
                return return_code
            with patch.object(S, 'main', side_effect=invoke) as caller, \
                    redirect_stdout(output), redirect_stderr(output):
                exec(compile(script, '<existing-optional-native-wrapper>', 'exec'), {})
            caller.assert_called_once_with([])
            self.assertEqual(json.loads(output.getvalue()), {'status': 'NATIVE_SAFARI_DISPATCH_HOLD'})

    def test_untrusted_metadata_and_errors_never_appear_in_reports(self):
        environment, event = trusted()
        event['head_commit']['message'] = PREFIX + ' | private-sentinel-event'
        api = MetadataAPI()
        for document in (api.repository_metadata, api.workflow_metadata, api.commit_metadata,
                         api.current_contents, api.parent_contents):
            document['html_url'] = 'https://private-sentinel.invalid'
            document['private-sentinel-unknown'] = 'private-sentinel-body'
        reports = [self.run_caller(api, environment, event)]
        api = MetadataAPI()
        api.parent_contents = contents_document(candidate_workflow())
        reports.append(self.run_caller(api, environment, event))
        reports.append(S.failure_report(RuntimeError('private-sentinel https://private-sentinel.invalid')))
        allowed = {'NATIVE_SAFARI_DISPATCH_REQUESTED', 'NATIVE_SAFARI_CANDIDATE_UNCHANGED',
                   'NATIVE_SAFARI_DISPATCH_HOLD', 'SAFARI_DISPATCH_FAILED'}
        for report in reports:
            for value in report.values():
                if type(value) is str:
                    self.assertTrue(value in allowed or re.fullmatch('[a-f0-9]{40}', value))
                else:
                    self.assertTrue(value is None or type(value) is bool or
                                    type(value) is int and value >= 0)
            rendered = json.dumps(report)
            self.assertNotIn('sentinel', rendered)
            self.assertNotIn('https:', rendered)
            self.assertNotIn(NATIVE_WORKFLOW, rendered)
            self.assertFalse(report['native_verification_proven'])
            self.assertFalse(report['owner_key_read'])
            self.assertEqual(report['official_provider_gets'], 0)

    def test_main_rejects_cli_overrides_before_reading_event_or_requesting(self):
        output = io.StringIO()
        with patch.object(S, 'GitHubAPI') as client, \
                patch.object(S.Path, 'read_bytes') as read_bytes, \
                redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(S.main(['--ref=private-sentinel']), 2)
        client.assert_not_called()
        read_bytes.assert_not_called()
        report = json.loads(output.getvalue())
        self.assertEqual(report['reason'], 'INPUT_INVALID')
        self.assertFalse(report['request_attempted'])
        self.assertFalse(report['request_acknowledged'])
        self.assertNotIn('sentinel', output.getvalue())


if __name__ == '__main__':
    unittest.main()
