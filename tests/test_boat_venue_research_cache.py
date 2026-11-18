"""Synthetic cache contracts: no providers, real keys, model rows or live Git.

Legacy controls compile hash-bound A74 function bodies. Git tests use a local
fixture origin while the runtime still sees its fixed canonical origin URL.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import zlib

from race_ai import boat_private_original_vault as V
from race_ai import boat_research_batch as B
from race_ai import boat_venue_research_retention as R

try:
    cache = importlib.import_module('race_ai.boat_venue_research_cache')
except ModuleNotFoundError as error:
    if error.name != 'race_ai.boat_venue_research_cache':
        raise
    cache = None

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/boat_venue_research_repeated_work.py'
FIXTURE_BLOB = '8e63856c2ed2f42d2ad74e2c6ec6a0c18fa14f65'
ORIGIN = 'https://github.com/haji84/RACE-AI'
REF = 'state/boat-pdca-transfer'
NOW = datetime(2030, 4, 1, 3, tzinfo=timezone.utc)
RACE = '20300401-01-01'
HEAD = 'a' * 40
MAXIMUM = R.ARCHIVE_FILES['archive.zip']
OVERRIDES = ('GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES',
    'GIT_COMMON_DIR', 'GIT_DIR', 'GIT_WORK_TREE')


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def fixture_tree():
    raw = FIXTURE.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
    if actual != FIXTURE_BLOB:
        raise AssertionError('PINNED_A74_CONTROL_FIXTURE_REQUIRED')
    return ast.parse(raw, filename=str(FIXTURE))


def function_node(tree, name):
    return next(node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name)


def function(name, namespace, *, production=False):
    path = ROOT / 'scripts/github_existing_cycle.py' if production else FIXTURE
    tree = ast.parse(path.read_bytes(), filename=str(path)) if production else fixture_tree()
    scope = dict(namespace, __name__='race_ai._synthetic_research_cache_control',
        __package__='race_ai')
    exec(compile(ast.Module(body=[function_node(tree, name)], type_ignores=[]),
        str(path), 'exec'), scope)
    return scope[name]


def private_root(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save(path, raw):
    path = Path(path)
    private_root(path.parent)
    path.write_bytes(raw)
    path.chmod(0o600)


def artifact(ident=101, *, expired=False):
    raw = b'PK\x03\x04SYNTHETIC_OWNER_CIPHERTEXT_' + str(ident).encode() + b'_NO_MODEL_DATA'
    metadata = dict(id=ident, name='all-existing-model-pairs-9001-1',
        digest='sha256:' + sha(raw), size_in_bytes=len(raw), expired=expired,
        created_at='2030-04-01T01:00:00Z', expires_at='2030-04-08T01:00:00Z',
        workflow_run=dict(id=9001, head_sha=HEAD))
    reference = dict(artifact_id=ident, run_id=9001, head_sha=HEAD,
        digest=metadata['digest'])
    return raw, metadata, reference


@contextmanager
def pdca_environment(*, production=False, labels=('pending', 'final', 'revised'), expired_last=False):
    with tempfile.TemporaryDirectory(prefix='synthetic-research-pdca-') as temporary:
        root = private_root(Path(temporary) / 'project')
        temp = private_root(Path(temporary) / 'private')
        output = private_root(root / 'existing_cycle_output')
        (output / 'official-result-observations.json').write_bytes(wire([]))
        raw, metadata, reference = artifact()
        network = []
        current = {'label': labels[0], 'metadata': metadata}
        def gh(path):
            network.append(path)
            if path == 'actions/artifacts/101':
                return wire(current['metadata'])
            if path == 'actions/artifacts/101/zip':
                return raw
            raise AssertionError('ONLY_SYNTHETIC_GITHUB_ARTIFACT_READS_ALLOWED')
        codec = Mock()
        scored = []
        def verify(body, meta, *, now, expected_run_id, expected_head_sha):
            codec(body, deepcopy(meta), now=now, expected_run_id=expected_run_id,
                expected_head_sha=expected_head_sha)
            need(body == raw and meta['digest'] == 'sha256:' + sha(body), 'FIXTURE_DIGEST_CHANGED')
            need(meta.get('expired') is False and now < datetime.fromisoformat(
                meta['expires_at'].replace('Z', '+00:00')), 'FIXTURE_RECEIPT_EXPIRED')
            return {'synthetic_admission': True}, [
                {'pair': {'sport': 'boat', 'race_id': RACE}}]
        def score(admission, records, fresh_labels, destination, *, now):
            scored.append(dict(records=deepcopy(records), labels=deepcopy(fresh_labels), now=now))
            return {'paired_forecasts': len(fresh_labels)}
        modules = {}
        def module(name, **values):
            item = ModuleType(name)
            item.__dict__.update(values)
            modules[name] = item
        module('race_ai.boat_venue_research_receipt',
            validate_research_refs=lambda refs: deepcopy(refs), MAX_ARCHIVE_BYTES=MAXIMUM)
        module('race_ai.boat_venue_research_pdca',
            score_private_p1_artifact=Mock(side_effect=AssertionError('WRONG_CODEC_BRANCH')))
        module('race_ai.boat_pdca_state', state_key=lambda purpose: b'SYNTHETIC_KEY_ONLY')
        module('scripts.boat_history_collect', private_root=private_root, save=save)
        module('race_ai.all_existing_model_receipt', _verified_private_pairs_artifact=verify)
        module('race_ai.all_existing_model_pdca',
            _score_verified_private_pairs=score, RESULT_FIELDS=('sport', 'race_id', 'status', 'revision'))
        module('race_ai.all_existing_model_intake', _results=lambda latest, now: (
            {('boat', RACE): {'result': dict(sport='boat', race_id=RACE,
                status='pending' if current['label'] == 'pending' else 'final',
                revision=2 if current['label'] == 'revised' else 1)}}, []))
        module('race_ai.existing_model_dispatch', _race_key=lambda rid, sport: rid)
        namespace = dict(ROOT=root, os=os, json=json, need=need, gh=gh,
            load_state=lambda path, day: {'venue_research_artifact_refs': [reference]},
            latest_result_observations=lambda observations: ([], []),
            datetime=type('FixedClock', (), {'now': staticmethod(lambda zone: NOW)}),
            timezone=timezone)
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {'RUNNER_TEMP': str(temp)}):
            run = function('venue_research_pdca', namespace, production=production)
            def rounds():
                reports = []
                for index, label in enumerate(labels, 1):
                    current['label'] = label
                    current['metadata'] = dict(metadata, expired=expired_last and index == len(labels))
                    reports.append(run('2030-04-01', index))
                return reports
            yield dict(rounds=rounds, network=network, codec=codec, scored=scored,
                raw=raw, metadata=metadata, reference=reference, root=root, temp=temp)


class LocalGit:
    """Separate writer/remote/reader databases; all network is replaced locally."""
    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='synthetic-research-git-')
        self.root = private_root(Path(self.temporary.name))
        self.repo = self.root / 'writer'
        self.remote = self.root / 'remote.git'
        self.cache_root = self.root / 'readback'
        self.calls = []
        empty = self.root / 'empty-global-config'
        empty.write_bytes(b'')
        self.environment = patch.dict(os.environ, {
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(empty),
            'GIT_TERMINAL_PROMPT': '0'})
        self.environment.__enter__()
        self.real_run = subprocess.run
        def run(args, *positional, **options):
            args = list(args)
            if args and args[0] == 'git':
                index = 1
                while index < len(args) and args[index].startswith('-'):
                    index += 2 if args[index] in ('-c', '-C', '--git-dir', '--work-tree') else 1
                command = args[index] if index < len(args) else ''
                self.calls.append(dict(command=command, selected='--stdin' in args,
                    cwd=str(options.get('cwd', ''))))
                if command in ('fetch', 'push', 'ls-remote'):
                    args = [str(self.remote) if value == ORIGIN else value for value in args]
            return self.real_run(args, *positional, **options)
        self.runner = patch.object(subprocess, 'run', side_effect=run)
        self.runner.__enter__()
        self.git('init', '--bare', str(self.remote))
        self.git('-C', str(self.remote), 'config', 'uploadpack.allowFilter', 'true')
        self.git('-C', str(self.remote), 'config', 'uploadpack.allowAnySHA1InWant', 'true')
        self.git('init', str(self.repo))
        self.git('-C', str(self.repo), 'remote', 'add', 'origin', ORIGIN)
        tree = self.git('-C', str(self.repo), 'mktree', body=b'').strip().decode()
        commit = self.git('-C', str(self.repo), '-c', 'user.name=Synthetic',
            '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgSign=false',
            'commit-tree', tree, body=b'Synthetic empty root\n').strip().decode()
        self.git('-C', str(self.repo), 'push', ORIGIN, commit + ':refs/heads/' + REF)
        self.writer = V.VaultGitRepository(self.repo, ref=REF)
        self.intakes = Mock()
        self.batch = function('publish_immutable_items', B.__dict__)
        batch_module = ModuleType('race_ai.boat_research_batch')
        batch_module.publish_immutable_items = self.batch
        self.batch_patch = patch.dict(sys.modules, {'race_ai.boat_research_batch': batch_module})
        self.batch_patch.__enter__()
        namespace = dict(R.__dict__)
        namespace.update(state_key=lambda purpose: b'SYNTHETIC_KEY_ONLY',
            _source_intake=self.intake)
        self.retain = function('retain_private_source_archives', namespace)
        return self

    def __exit__(self, *error):
        self.batch_patch.__exit__(*error)
        self.runner.__exit__(*error)
        self.environment.__exit__(*error)
        self.temporary.cleanup()

    def git(self, *args, body=None):
        result = subprocess.run(['git', *args], input=body, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=True)
        return result.stdout

    def source(self, ident=101):
        raw, metadata, _ = artifact(ident)
        folder = private_root(self.root / 'archives' / str(ident))
        save(folder / 'archive.zip', raw)
        save(folder / 'metadata.json', wire(metadata))
        return folder

    def intake(self, folder, now, key):
        self.intakes(folder, now, key)
        raw = (folder / 'archive.zip').read_bytes()
        metadata_raw = (folder / 'metadata.json').read_bytes()
        metadata = json.loads(metadata_raw)
        return dict(root=folder, archive_sha256=sha(raw), metadata_sha256=sha(metadata_raw),
            archive_size_bytes=len(raw), metadata_size_bytes=len(metadata_raw),
            manifest=wire({'synthetic_verified_admission': metadata['id']}),
            artifact_id=metadata['id'])

    def retain_once(self, folders, reader=None):
        return self.retain(folders, self.repo, token='synthetic_token_12345678901234567890',
            now=NOW, readback_transport=reader)

    def selected_fetches(self):
        return sum(call['command'] == 'fetch' and call['selected'] for call in self.calls)

    def shows(self, repo):
        return sum(call['command'] == 'show' and
            Path(call['cwd']).resolve() == Path(repo).resolve() for call in self.calls)


class LegacyResearchCacheControls(unittest.TestCase):
    def test_original_pdca_reloads_zip_and_reruns_codec_and_score_each_round(self):
        with pdca_environment() as state:
            reports = state['rounds']()
            self.assertEqual(state['network'].count('actions/artifacts/101'), 3)
            self.assertEqual(state['network'].count('actions/artifacts/101/zip'), 3)
            self.assertEqual(state['codec'].call_count, 3)
            self.assertEqual(len(state['scored']), 3)
            self.assertEqual([item['paired_forecasts'] for item in reports], [0, 1, 1])
            self.assertEqual(state['scored'][-1]['labels'][0]['revision'], 2)

    def test_original_retention_repeats_intake_and_selected_blob_download_in_fresh_databases(self):
        with LocalGit() as git:
            folder = git.source()
            first = git.retain_once([folder])
            after_first = git.selected_fetches()
            second = git.retain_once([folder])
            self.assertEqual(git.intakes.call_count, 2)
            self.assertGreater(after_first, 0)
            self.assertGreater(git.selected_fetches(), after_first)
            self.assertEqual(first, second)


class ResearchZipReuseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cache, 'research cache helper module is missing')
        self.temporary = tempfile.TemporaryDirectory(prefix='synthetic-zip-cache-')
        self.addCleanup(self.temporary.cleanup)
        self.root = private_root(Path(self.temporary.name) / 'archives')
        self.raw, self.metadata, self.reference = artifact()
        self.gh = Mock(side_effect=self.response)

    def response(self, path):
        if path == 'actions/artifacts/101':
            return wire(self.metadata)
        if path == 'actions/artifacts/101/zip':
            return self.raw
        raise AssertionError('ONLY_SYNTHETIC_ARTIFACT_READS_ALLOWED')

    def read(self, reference=None):
        return cache.read_research_archive(self.reference if reference is None else reference,
            gh=self.gh, cache_root=self.root, maximum_bytes=MAXIMUM)

    def cached(self, raw=None):
        path = self.root / '101' / 'archive.zip'
        save(path, self.raw if raw is None else raw)
        return path

    def test_exact_zip_hit_still_reads_fresh_metadata_and_hashes_all_bytes(self):
        path = self.cached()
        raw, metadata = self.read()
        self.assertEqual(raw, self.raw)
        self.assertEqual(metadata, self.metadata)
        self.gh.assert_called_once_with('actions/artifacts/101')
        self.assertEqual(path.read_bytes(), self.raw)

    def test_metadata_is_never_reused_from_disk_or_a_previous_call(self):
        self.cached()
        self.read()
        self.metadata['opaque_fresh_field'] = 'synthetic-current-response'
        raw, metadata = self.read()
        self.assertEqual(metadata['opaque_fresh_field'], 'synthetic-current-response')
        self.assertEqual(self.gh.call_args_list[0].args, ('actions/artifacts/101',))
        self.assertEqual(self.gh.call_args_list[1].args, ('actions/artifacts/101',))

    def test_missing_or_tampered_zip_uses_full_existing_zip_read(self):
        for stored in (None, b'NOT_THE_EXPECTED_IMMUTABLE_ZIP'):
            with self.subTest(stored=stored is not None):
                if stored is not None:
                    self.cached(stored)
                raw, metadata = self.read()
                self.assertEqual(raw, self.raw)
                self.assertEqual(metadata, self.metadata)
                self.assertIn(unittest.mock.call('actions/artifacts/101/zip'), self.gh.call_args_list)
                self.gh.reset_mock()

    def test_changed_metadata_or_ref_never_falls_back_to_stale_zip(self):
        self.cached()
        for change in ({'id': 102}, {'digest': 'sha256:' + '0' * 64},
                {'workflow_run': {'id': 9002, 'head_sha': HEAD}},
                {'workflow_run': {'id': 9001, 'head_sha': 'b' * 40}}):
            with self.subTest(change=tuple(change)):
                original = deepcopy(self.metadata)
                self.metadata.update(change)
                with self.assertRaises(ValueError):
                    self.read()
                self.assertNotIn(unittest.mock.call('actions/artifacts/101/zip'),
                    self.gh.call_args_list)
                self.metadata = original
                self.gh.reset_mock()

    def test_remote_zip_digest_or_existing_size_bound_failure_holds(self):
        expected = deepcopy(self.reference)
        for body in (b'wrong remote bytes', self.raw + b'extra'):
            with self.subTest(size=len(body)):
                self.raw = body
                with self.assertRaises(ValueError):
                    cache.read_research_archive(expected, gh=self.gh,
                        cache_root=self.root, maximum_bytes=MAXIMUM)
        raw, metadata, reference = artifact()
        self.raw, self.metadata = raw, metadata
        with self.assertRaises(ValueError):
            cache.read_research_archive(reference, gh=self.gh,
                cache_root=self.root, maximum_bytes=len(raw) - 1)

    def test_symlink_or_shared_readable_cache_holds_without_following_it(self):
        outside = Path(self.temporary.name) / 'outside.zip'
        outside.write_bytes(self.raw)
        path = self.root / '101' / 'archive.zip'
        private_root(path.parent)
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.read()
        self.assertEqual(outside.read_bytes(), self.raw)
        path.unlink()
        self.cached()
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.read()

    def test_cached_zip_does_not_cache_scores_pending_labels_or_revisions(self):
        with pdca_environment(production=False) as old:
            old_reports = old['rounds']()
            old_records = deepcopy(old['scored'])
        with pdca_environment(production=True) as new:
            new_reports = new['rounds']()
            self.assertEqual(new_reports, old_reports)
            self.assertEqual(new['scored'], old_records)
            self.assertEqual(new['network'].count('actions/artifacts/101'), 3)
            self.assertEqual(new['network'].count('actions/artifacts/101/zip'), 1)
            self.assertEqual(new['codec'].call_count, 3)

    def test_fresh_expired_metadata_still_reaches_existing_verifier_and_holds_scoring(self):
        with pdca_environment(production=True, labels=('final', 'final'),
                expired_last=True) as state:
            reports = state['rounds']()
            self.assertEqual(state['codec'].call_count, 2)
            self.assertEqual(len(state['scored']), 1)
            self.assertEqual(reports[-1]['rejected_archives'], 1)
            self.assertEqual(reports[-1]['paired_forecasts'], 0)


class ResearchReadbackReuseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cache, 'research cache helper module is missing')

    def test_persistent_reader_keeps_both_databases_and_full_intake_every_time(self):
        with LocalGit() as git:
            folder = git.source()
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            self.assertEqual(reader.ref, REF)
            self.assertNotEqual(Path(reader.repo).resolve(), git.repo.resolve())
            first = git.retain_once([folder], reader)
            selected = git.selected_fetches()
            shown = git.shows(reader.repo)
            second = git.retain_once([folder], reader)
            self.assertEqual(git.intakes.call_count, 2)
            self.assertEqual(first, second)
            self.assertGreater(selected, 0)
            self.assertEqual(git.selected_fetches(), selected)
            self.assertGreaterEqual(git.shows(reader.repo) - shown, 3)
            self.assertGreaterEqual(git.shows(git.repo), 3)
            metadata_fetches = [call for call in git.calls if call['command'] == 'fetch'
                and not call['selected'] and Path(call['cwd']).resolve() == Path(reader.repo).resolve()]
            self.assertEqual(len(metadata_fetches), 2)

    def test_reopening_keeps_disk_objects_and_fetches_each_commit_again(self):
        with LocalGit() as git:
            folder = git.source()
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            first = git.retain_once([folder], reader)
            selected = git.selected_fetches()
            reopened = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            self.assertEqual(Path(reopened.repo).resolve(), Path(reader.repo).resolve())
            second = git.retain_once([folder], reopened)
            self.assertEqual(first, second)
            self.assertEqual(git.selected_fetches(), selected)
            self.assertEqual(git.intakes.call_count, 2)

    def test_new_items_fetch_missing_objects_without_skipping_old_byte_readbacks(self):
        with LocalGit() as git:
            one, two = git.source(101), git.source(102)
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            first = git.retain_once([one], reader)
            selected, shown = git.selected_fetches(), git.shows(reader.repo)
            second = git.retain_once([one, two], reader)
            self.assertGreater(git.selected_fetches(), selected)
            self.assertGreaterEqual(git.shows(reader.repo) - shown, 6)
            self.assertEqual(git.intakes.call_count, 3)
            self.assertEqual(second['retained_archives'], 2)
            self.assertEqual(second['pointers'][0]['archive_sha256'],
                first['pointers'][0]['archive_sha256'])
            self.assertEqual((one / 'archive.zip').read_bytes(), artifact(101)[0])

    def test_reader_is_bare_fixed_origin_and_physically_separate(self):
        with LocalGit() as git:
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            self.assertEqual(git.git('-C', str(reader.repo),
                'rev-parse', '--is-bare-repository').strip(), b'true')
            self.assertEqual(git.git('-C', str(reader.repo),
                'remote', 'get-url', 'origin').strip().decode(), ORIGIN)
            common = Path(git.git('-C', str(reader.repo), 'rev-parse',
                '--path-format=absolute', '--git-common-dir').strip().decode()).resolve()
            writer_common = Path(git.git('-C', str(git.repo), 'rev-parse',
                '--path-format=absolute', '--git-common-dir').strip().decode()).resolve()
            self.assertNotEqual(common, writer_common)
            self.assertFalse(os.path.samefile(common / 'objects', writer_common / 'objects'))
            self.assertFalse((common / 'objects/info/alternates').exists())

    def test_writer_methods_and_direct_writer_commands_are_blocked(self):
        with LocalGit() as git:
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            for action in (lambda: reader.commit({}, 'a' * 40),
                    lambda: reader.commit_snapshot({}, 'a' * 40),
                    lambda: reader.push('a' * 40, 'b' * 40),
                    lambda: reader._write_tree(env={}),
                    lambda: reader._run(['push', ORIGIN, 'a' * 40 + ':refs/heads/' + REF]),
                    lambda: reader._run(['hash-object', '-w', '--stdin'], body=b'bad')):
                with self.subTest(action=action.__code__.co_firstlineno), self.assertRaises(ValueError):
                    action()

    def test_git_object_override_environment_cannot_merge_reader_and_writer_storage(self):
        with LocalGit() as git:
            for name in OVERRIDES:
                with self.subTest(name=name), patch.dict(os.environ, {name: str(git.repo / '.git')}):
                    with self.assertRaises(ValueError):
                        cache.research_readback_transport(git.repo, cache_root=git.cache_root)

    def test_writer_paths_symlinks_nonbare_or_wrong_origin_are_not_reinitialized(self):
        with LocalGit() as git:
            for path in (git.repo, git.repo / '.git'):
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    cache.research_readback_transport(git.repo, cache_root=path)
            link = git.root / 'linked-reader'
            link.symlink_to(git.repo / '.git', target_is_directory=True)
            with self.assertRaises(ValueError):
                cache.research_readback_transport(git.repo, cache_root=link)
            wrong = git.root / 'wrong-origin'
            git.git('init', '--bare', str(wrong))
            git.git('-C', str(wrong), 'remote', 'add', 'origin', 'https://example.invalid/wrong')
            with self.assertRaises(ValueError):
                cache.research_readback_transport(git.repo, cache_root=wrong)
            self.assertEqual(git.git('-C', str(wrong), 'remote', 'get-url', 'origin').strip(),
                b'https://example.invalid/wrong')

    def test_local_alternates_or_common_directory_cannot_supply_writer_objects(self):
        with LocalGit() as git:
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            alternates = Path(reader.repo) / 'objects/info/alternates'
            alternates.write_text(str(git.repo / '.git/objects') + '\n')
            with self.assertRaises(ValueError):
                cache.research_readback_transport(git.repo, cache_root=git.cache_root)

    def test_tampered_cached_blob_never_passes_full_byte_comparison(self):
        with LocalGit() as git:
            folder = git.source()
            reader = cache.research_readback_transport(git.repo, cache_root=git.cache_root)
            result = git.retain_once([folder], reader)
            raw = (folder / 'archive.zip').read_bytes()
            oid = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            target = Path(reader.repo) / 'objects' / oid[:2] / oid[2:]
            target.parent.mkdir(parents=True, exist_ok=True)
            bad = bytes([raw[0] ^ 1]) + raw[1:]
            target.write_bytes(zlib.compress(b'blob ' + str(len(bad)).encode() + b'\0' + bad))
            with self.assertRaises(ValueError):
                git.retain_once([folder], reader)
            self.assertEqual(git.intakes.call_count, 2)
            self.assertEqual(result['retained_archives'], 1)


class ResearchCacheIntegrationContractTests(unittest.TestCase):
    def test_pdca_uses_ref_aware_reader_but_keeps_verifier_scorer_and_fresh_labels(self):
        path = ROOT / 'scripts/github_existing_cycle.py'
        node = function_node(ast.parse(path.read_bytes()), 'venue_research_pdca')
        calls = [item for item in ast.walk(node) if isinstance(item, ast.Call)]
        cache_calls = [item for item in calls if isinstance(item.func, ast.Name)
            and item.func.id == 'read_research_archive']
        self.assertEqual(len(cache_calls), 1)
        self.assertEqual(ast.dump(cache_calls[0].args[0]), ast.dump(ast.Name(id='reference', ctx=ast.Load())))
        self.assertEqual({item.arg for item in cache_calls[0].keywords},
            {'gh', 'cache_root', 'maximum_bytes'})
        old = function_node(fixture_tree(), 'venue_research_pdca')
        names = ('_verified_private_pairs_artifact', '_score_verified_private_pairs',
            'score_private_p1_artifact', 'latest_result_observations', '_results')
        def selected(function, name):
            return [ast.dump(item, include_attributes=False) for item in ast.walk(function)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == name]
        for name in names:
            self.assertEqual(selected(node, name), selected(old, name), name)

    def test_only_source_archive_retention_receives_the_independent_cache_transport(self):
        path = ROOT / 'scripts/github_existing_cycle.py'
        node = function_node(ast.parse(path.read_bytes()), 'venue_research_retain')
        calls = [item for item in ast.walk(node) if isinstance(item, ast.Call)]
        readers = [item for item in calls if isinstance(item.func, ast.Name)
            and item.func.id == 'research_readback_transport']
        self.assertEqual(len(readers), 1)
        source = [item for item in calls if isinstance(item.func, ast.Name)
            and item.func.id == 'retain_private_source_archives']
        self.assertEqual(len(source), 1)
        self.assertEqual({item.arg for item in source[0].keywords}, {'readback_transport'})
        learning = [item for item in calls if isinstance(item.func, ast.Name)
            and item.func.id == 'retain_private_research']
        self.assertEqual(len(learning), 1)
        self.assertEqual(learning[0].keywords, [])

    def test_existing_intake_learning_and_two_database_publisher_are_byte_unchanged(self):
        for relative, expected in (
                ('race_ai/boat_venue_research_retention.py', '6caf3fbc2cef217736df775e04e344f1bc823c15'),
                ('race_ai/boat_research_batch.py', '2f2cd3cde621ff051ca29cc6fa7d00b6be52c3f5')):
            with self.subTest(path=relative):
                raw = (ROOT / relative).read_bytes()
                actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
