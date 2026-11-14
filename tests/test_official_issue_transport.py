"""Synthetic GitHub Git storage; never invoke gh or a provider."""
import base64
from copy import deepcopy
from hashlib import sha1, sha256
import importlib
import json
import subprocess
import unittest
from unittest.mock import patch


PATH = 'recovery/official-results/' + '1' * 64 + '/' + '2' * 40 + '/77/2.enc'
PARENT = 'a' * 40


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def blob_id(raw):
    return sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.ref = PARENT
        self.snapshots = {PARENT: {'keep/original.enc': b'unchanged'}}
        self.commits = {}
        self.trees = {}
        self.blobs = {}
        self.extra = {}
        self.cas_race = False
        self._commit(PARENT, self.snapshots[PARENT])

    def _tree(self, files):
        grouped = {}
        for path, raw in files.items():
            first, _, rest = path.partition('/')
            grouped.setdefault(first, {})[rest] = raw
        rows = []
        for name, children in sorted(grouped.items()):
            if '' in children:
                raw = children['']
                ident = blob_id(raw)
                self.blobs[ident] = raw
                rows.append(dict(path=name, type='blob', mode='100644', sha=ident, size=len(raw)))
            else:
                ident = self._tree(children)
                rows.append(dict(path=name, type='tree', mode='040000', sha=ident))
        ident = sha1(wire(rows)).hexdigest()
        self.trees[ident] = rows
        return ident

    def _commit(self, ident, files):
        self.commits[ident] = {'sha': ident, 'tree': {'sha': self._tree(files)}}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if (method, path) in self.extra:
            return self.extra[(method, path)]
        if method == 'GET' and path == 'git/ref/heads/state/boat-pdca-transfer':
            return wire(dict(ref='refs/heads/state/boat-pdca-transfer', object=dict(type='commit', sha=self.ref)))
        if method == 'GET' and path.startswith('git/commits/'):
            return wire(self.commits[path.rsplit('/', 1)[1]])
        if method == 'GET' and path.startswith('git/trees/'):
            ident = path.rsplit('/', 1)[1]
            return wire(dict(sha=ident, truncated=False, tree=self.trees[ident]))
        if method == 'GET' and path.startswith('git/blobs/'):
            ident = path.rsplit('/', 1)[1]
            raw = self.blobs[ident]
            return wire(dict(sha=ident, encoding='base64', size=len(raw), content=base64.b64encode(raw).decode()))
        if method == 'POST' and path == 'git/blobs':
            raw = base64.b64decode(body['content'], validate=True)
            ident = blob_id(raw)
            self.blobs[ident] = raw
            return wire(dict(sha=ident))
        if method == 'POST' and path == 'git/trees':
            old = next(c for c, value in self.commits.items() if value['tree']['sha'] == body['base_tree'])
            files = dict(self.snapshots[old])
            for row in body['tree']:
                files[row['path']] = self.blobs[row['sha']]
            ident = self._tree(files)
            self.pending = files
            return wire(dict(sha=ident, truncated=False, tree=self.trees[ident]))
        if method == 'POST' and path == 'git/commits':
            ident = sha1(wire(body)).hexdigest()
            self.snapshots[ident] = self.pending
            self._commit(ident, self.pending)
            return wire(self.commits[ident])
        if method == 'PATCH' and path == 'git/refs/heads/state/boat-pdca-transfer':
            if self.cas_race:
                self.ref = 'f' * 40
                raise ValueError('server private failure must not escape')
            self.ref = body['sha']
            return wire(dict(ref='refs/heads/state/boat-pdca-transfer', object=dict(type='commit', sha=self.ref)))
        raise AssertionError((method, path))


class TransportTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module('race_ai.all_existing_model_official_issue_transport')
        except ModuleNotFoundError:
            self.fail('source-free GitHub issuance transport is missing')

    def test_create_only_publication_preserves_existing_tree_and_independent_readback(self):
        api = FakeGitHub()
        transport = self.module().GithubIssueTransport(api)
        commit = transport.publish_capsule(PATH, b'opaque-owner-ciphertext', PARENT)
        self.assertEqual(api.snapshots[commit], {
            'keep/original.enc': b'unchanged', PATH: b'opaque-owner-ciphertext'})
        reader = self.module().GithubIssueTransport(api)
        self.assertEqual(reader.read_file(commit, PATH, 1024), b'opaque-owner-ciphertext')
        patches = [body for method, _, body in api.calls if method == 'PATCH']
        self.assertEqual(patches, [dict(sha=commit, force=False)])
        self.assertEqual(transport.head(), commit)

    def test_existing_path_stale_parent_and_absent_ref_cannot_mutate(self):
        for variant in ('existing', 'stale', 'absent'):
            with self.subTest(variant=variant):
                api = FakeGitHub()
                if variant == 'existing':
                    api.snapshots[PARENT][PATH] = b'prior-ciphertext'
                    api._commit(PARENT, api.snapshots[PARENT])
                elif variant == 'stale':
                    api.ref = 'e' * 40
                else:
                    api.extra[('GET', 'git/ref/heads/state/boat-pdca-transfer')] = b'{}'
                transport = self.module().GithubIssueTransport(api)
                with self.assertRaises(ValueError):
                    transport.publish_capsule(PATH, b'new', PARENT)
                self.assertTrue(all(method == 'GET' for method, _, _ in api.calls))

    def test_route_guard_blocks_external_source_dispatch_and_unbounded_queries(self):
        api = FakeGitHub()
        transport = self.module().GithubIssueTransport(api)
        for route in ('https://example.test/', 'repos/other/repo/actions/runs/1',
                      'actions/runs/77/rerun', 'actions/workflows/392270247/dispatches',
                      'pulls/72', 'actions/runs/77/artifacts?per_page=100&page=999'):
            with self.subTest(route=route), self.assertRaises(ValueError):
                transport.json(route)
        self.assertEqual(api.calls, [])

    def test_json_rejects_duplicate_keys_nonfinite_and_wrong_top_level(self):
        for raw in (b'{"id":1,"id":2}', b'{"count":NaN}', b'[]', b''):
            with self.subTest(raw=raw):
                api = FakeGitHub()
                api.extra[('GET', 'pulls/71')] = raw
                with self.assertRaises(ValueError):
                    self.module().GithubIssueTransport(api).json('pulls/71')

    def test_immutable_reader_rejects_bad_blob_hash_size_mode_and_ambiguous_path(self):
        for variant in ('hash', 'size', 'mode', 'duplicate', 'truncated'):
            with self.subTest(variant=variant):
                api = FakeGitHub()
                api.snapshots[PARENT][PATH] = b'cipher'
                api._commit(PARENT, api.snapshots[PARENT])
                transport = self.module().GithubIssueTransport(api)
                if variant == 'hash':
                    ident = blob_id(b'cipher')
                    api.extra[('GET', 'git/blobs/' + ident)] = wire(dict(sha=ident, encoding='base64', size=6,
                        content=base64.b64encode(b'tamper').decode()))
                else:
                    tree = api.commits[PARENT]['tree']['sha']
                    rows = api.trees[tree]
                    if variant == 'truncated':
                        api.extra[('GET', 'git/trees/' + tree)] = wire(dict(sha=tree, tree=rows, truncated=True))
                    elif variant == 'duplicate':
                        rows.append(dict(rows[1]))
                    else:
                        parts = PATH.split('/')
                        for part in parts[:-1]:
                            tree = next(row['sha'] for row in api.trees[tree] if row['path'] == part)
                        row = api.trees[tree][0]
                        row['size' if variant == 'size' else 'mode'] = 99 if variant == 'size' else '120000'
                with self.assertRaises(ValueError):
                    transport.read_file(PARENT, PATH, 1024)

    def test_missing_path_returns_none_but_invalid_path_or_limit_never_reads(self):
        api = FakeGitHub()
        transport = self.module().GithubIssueTransport(api)
        self.assertIsNone(transport.read_file(PARENT, PATH, 1024))
        before = len(api.calls)
        for path, limit in (('../secret', 1024), (PATH, 0), (PATH, True)):
            with self.subTest(path=path, limit=limit), self.assertRaises(ValueError):
                transport.read_file(PARENT, path, limit)
        self.assertEqual(len(api.calls), before)

    def test_archive_download_requires_exact_fresh_metadata_and_bytes(self):
        raw = b'PK\x03\x04fictional-archive'
        pin = dict(id=10, run_id=20, head_sha='3' * 40, digest='sha256:' + sha256(raw).hexdigest())
        metadata = dict(id=10, digest=pin['digest'], size_in_bytes=len(raw), expired=False,
            workflow_run=dict(id=20, head_sha='3' * 40, repository_id=1416489937, head_repository_id=1416489937))
        for variant in ('valid', 'digest', 'size', 'expired', 'repository', 'run', 'head'):
            with self.subTest(variant=variant):
                api = FakeGitHub()
                altered = deepcopy(metadata)
                if variant in ('digest', 'size', 'expired'):
                    altered[{'digest': 'digest', 'size': 'size_in_bytes', 'expired': 'expired'}[variant]] = {
                        'digest': 'sha256:' + '0' * 64, 'size': len(raw) + 1, 'expired': True}[variant]
                elif variant in ('repository', 'run', 'head'):
                    altered['workflow_run'][{'repository': 'head_repository_id', 'run': 'id', 'head': 'head_sha'}[variant]] = {
                        'repository': 42, 'run': 21, 'head': '4' * 40}[variant]
                api.extra[('GET', 'actions/artifacts/10')] = wire(altered)
                api.extra[('GET', 'actions/artifacts/10/zip')] = raw
                transport = self.module().GithubIssueTransport(api)
                if variant == 'valid':
                    self.assertEqual(transport.archive(pin), dict(raw=raw, metadata=metadata))
                else:
                    with self.assertRaises(ValueError):
                        transport.archive(pin)

    def test_cas_failure_is_not_retried_and_private_transport_error_is_sanitized(self):
        api = FakeGitHub()
        api.cas_race = True
        with self.assertRaisesRegex(ValueError, '^OFFICIAL_ISSUE_TRANSPORT_') as caught:
            self.module().GithubIssueTransport(api).publish_capsule(PATH, b'cipher', PARENT)
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(sum(method == 'PATCH' for method, _, _ in api.calls), 1)

    def test_default_gh_transport_pins_hostname_and_sends_ciphertext_on_stdin(self):
        module = self.module()
        body = dict(content='opaque-base64-ciphertext', encoding='base64')
        result = subprocess.CompletedProcess([], 0, b'{"sha":"' + b'a' * 40 + b'"}', b'')
        with patch.object(module.subprocess, 'run', return_value=result) as run:
            self.assertEqual(module._gh('POST', 'git/blobs', body), result.stdout)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ['gh', 'api', '--hostname', 'github.com',
            'repos/haji84/RACE-AI/git/blobs', '--method', 'POST', '--input', '-'])
        self.assertEqual(json.loads(kwargs['input']), body)
        self.assertNotIn('opaque-base64-ciphertext', args[0])

    def test_default_gh_error_does_not_expose_stderr_or_attempt_another_call(self):
        module = self.module()
        result = subprocess.CompletedProcess([], 1, b'private output', b'private token')
        with patch.object(module.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, '^OFFICIAL_ISSUE_TRANSPORT_GITHUB_REQUEST$'):
                module.GithubIssueTransport().head()
        self.assertEqual(run.call_count, 1)

    def test_default_gh_denial_statuses_stop_without_exposing_private_stderr(self):
        module = self.module()
        for status in (401, 403, 429):
            with self.subTest(status=status):
                result = subprocess.CompletedProcess([], 1, b'private output',
                    ('private token (HTTP ' + str(status) + ')').encode())
                with patch.object(module.subprocess, 'run', return_value=result) as run:
                    with self.assertRaisesRegex(ValueError, '^OFFICIAL_ISSUE_TRANSPORT_GITHUB_DENIED$'):
                        module.GithubIssueTransport().head()
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
