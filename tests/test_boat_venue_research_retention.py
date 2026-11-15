"""Credential lifetime and private-folder preflight; publishing is already tested."""
import base64
import contextlib
import importlib
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_boat_venue_history_handoff import MemoryGit
from tests import test_boat_venue_research_receipt as receipt_tests


TOKEN = 'synthetic-retention-token-no-real-access'
POINTER = dict(schema='RACE_AI_BOAT_VENUE_LEARNING_INPUT_V1', status='READY',
               repository_id='1416489937', source_commit='a'*40,
               manifest_path='state/boat-venue-history/v1/learning/'+'b'*64+'/learning.json',
               manifest_sha256='b'*64, training_sha256='c'*64)


class PrivateResearchRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='venue-retention-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root/'repo'; self.repo.mkdir(mode=0o700)
        self.forecast = self.folder('forecast'); self.pdca = self.folder('pdca')
        self.environment = patch.dict(os.environ, dict(
            RACE_AI_STATE_KEY=base64.b64encode(os.urandom(32)).decode(), GH_TOKEN=TOKEN), clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def folder(self, name):
        root = self.root/name; root.mkdir(mode=0o700)
        for file in ('learning.enc', 'learning.json', 'summary.json'):
            path = root/file; path.write_bytes(b'synthetic-publisher-boundary'); path.chmod(0o600)
        return root

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_research_retention')
        except ModuleNotFoundError:
            self.fail('private research retention credential wrapper is missing')

    def assert_auth(self, token, index=0):
        self.assertEqual(os.environ['GIT_CONFIG_COUNT'], str(index+1))
        self.assertEqual(os.environ['GIT_CONFIG_KEY_'+str(index)], 'http.https://github.com/.extraheader')
        header = os.environ['GIT_CONFIG_VALUE_'+str(index)]
        scheme, encoded = header.split(' ', 2)[1:]
        self.assertEqual(scheme, 'basic')
        self.assertEqual(base64.b64decode(encoded), ('x-access-token:'+token).encode())
        self.assertEqual(os.environ['GIT_TERMINAL_PROMPT'], '0')

    def test_forecast_and_pdca_publish_once_each_with_temporary_auth_and_no_stdout(self):
        api = self.api(); before = dict(os.environ); seen = []
        def publish(folder, repo):
            self.assert_auth(TOKEN)
            self.assertEqual(repo, self.repo)
            seen.append(folder)
            return dict(POINTER)
        output = io.StringIO()
        with patch.object(api, 'publish_learning_candidate', side_effect=publish), contextlib.redirect_stdout(output):
            result = api.retain_private_research([self.forecast, self.pdca, self.forecast], self.repo)
        self.assertEqual(seen, [self.forecast, self.pdca])
        self.assertEqual(result['status'], 'OWNER_PRIVATE_RESEARCH_RETENTION_VERIFIED')
        self.assertEqual(result['requested_folders'], 3)
        self.assertEqual(result['retained_folders'], 2)
        self.assertEqual(result['pointers'], [POINTER, POINTER])
        self.assertIs(result['plaintext_published'], False)
        self.assertIs(result['production_promoted'], False)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(dict(os.environ), before)
        self.assertNotIn(TOKEN, str(result)); self.assertNotIn('Authorization', str(result))

    def test_existing_git_configuration_and_overlapped_slots_restore_after_error(self):
        api = self.api()
        os.environ.update(GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='safe.first', GIT_CONFIG_VALUE_0='first',
                          GIT_CONFIG_KEY_1='safe.second', GIT_CONFIG_VALUE_1='second',
                          GIT_CONFIG_KEY_2='old.unused', GIT_CONFIG_VALUE_2='old-value',
                          GIT_TERMINAL_PROMPT='1', GCM_INTERACTIVE='old-choice')
        before = dict(os.environ)
        def fail(folder, repo):
            self.assert_auth(TOKEN, index=2)
            self.assertEqual(os.environ['GIT_CONFIG_VALUE_0'], 'first')
            self.assertEqual(os.environ['GIT_CONFIG_VALUE_1'], 'second')
            raise ValueError('synthetic publish failure')
        with patch.object(api, 'publish_learning_candidate', side_effect=fail), \
             self.assertRaisesRegex(ValueError, 'synthetic publish failure'):
            api.retain_private_research([self.forecast], self.repo)
        self.assertEqual(dict(os.environ), before)

    def test_explicit_token_overrides_gh_token_only_for_scoped_git_auth(self):
        api = self.api(); token = 'different-synthetic-retention-token'
        before = dict(os.environ)
        def publish(folder, repo):
            self.assert_auth(token)
            self.assertEqual(os.environ['GH_TOKEN'], TOKEN)
            return dict(POINTER)
        with patch.object(api, 'publish_learning_candidate', side_effect=publish):
            api.retain_private_research([self.forecast], self.repo, token=token)
        self.assertEqual(dict(os.environ), before)

    def test_invalid_key_token_and_git_count_stop_before_any_publisher(self):
        api = self.api(); before = dict(os.environ)
        with patch.object(api, 'publish_learning_candidate', side_effect=AssertionError('preflight must finish first')):
            for key in ('', 'not-base64'):
                with self.subTest(key='missing-or-malformed'), patch.dict(os.environ, RACE_AI_STATE_KEY=key), self.assertRaises(ValueError):
                    api.retain_private_research([self.forecast], self.repo)
            for token in ('', 'short', 'x'*513, 'x'*30+'\n', 'x'*20+' space', 'x'*20+':bad', b'bytes-not-text'):
                with self.subTest(token_kind=type(token).__name__), self.assertRaises(ValueError):
                    api.retain_private_research([self.forecast], self.repo, token=token)
            with patch.dict(os.environ, GH_TOKEN=''), self.assertRaises(ValueError):
                api.retain_private_research([self.forecast], self.repo)
            for count in ('invalid', '-1', '10001'):
                with self.subTest(count=count), patch.dict(os.environ, GIT_CONFIG_COUNT=count), self.assertRaises(ValueError):
                    api.retain_private_research([self.forecast], self.repo)
        self.assertEqual(dict(os.environ), before)

    def test_preflights_every_folder_and_private_parent_before_any_publication(self):
        api = self.api()
        public_parent = self.root/'public-parent'; public_parent.mkdir(mode=0o755); public_parent.chmod(0o755)
        inside = public_parent/'private-child'; inside.mkdir(mode=0o700)
        for name in ('learning.enc', 'learning.json', 'summary.json'):
            path = inside/name; path.write_bytes(b'x'); path.chmod(0o600)
        in_git = self.root/'git-work'; in_git.mkdir(mode=0o700); (in_git/'.git').mkdir()
        candidate = in_git/'candidate'; candidate.mkdir(mode=0o700)
        symlink = self.root/'alias'; symlink.symlink_to(self.forecast, target_is_directory=True)
        missing_file = self.folder('missing-file'); (missing_file/'learning.enc').unlink()
        public_file = self.folder('public-file'); (public_file/'learning.enc').chmod(0o644)
        invalid = [self.root/'missing', inside, candidate, symlink, missing_file, public_file,
                   self.forecast/'..'/'forecast']
        with patch.object(api, 'publish_learning_candidate', side_effect=AssertionError('no partial publication')):
            for root in invalid:
                with self.subTest(path=root.name), self.assertRaises(ValueError):
                    api.retain_private_research([self.forecast, root], self.repo)
        self.assertEqual((public_parent.stat().st_mode & 0o777), 0o755)

    def test_requires_bounded_explicit_list_and_empty_list_performs_no_git(self):
        api = self.api()
        with patch.object(api, 'publish_learning_candidate', side_effect=AssertionError('no publisher call')):
            for folders in (None, str(self.forecast), (self.forecast,), [self.forecast]*10001):
                with self.subTest(kind=type(folders).__name__), self.assertRaises(ValueError):
                    api.retain_private_research(folders, self.repo)
            result = api.retain_private_research([], self.repo)
        self.assertEqual(result['retained_folders'], 0)
        self.assertEqual(result['pointers'], [])


class PrivateSourceArchiveRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        receipt_tests.PrivateP1ReceiptTests.setUpClass()
        cls.addClassCleanup(receipt_tests.PrivateP1ReceiptTests.doClassCleanups)
        fixture = receipt_tests.PrivateP1ReceiptTests()
        cls.raw, _ = fixture.archive()
        cls.metadata = fixture.metadata(cls.raw)
        cls.now = receipt_tests.NOW+receipt_tests.timedelta(minutes=12)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='venue-archive-retention-test-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.archive_folder = self.root/'800'; self.archive_folder.mkdir(mode=0o700)
        self.metadata_raw = json.dumps(self.metadata, indent=2).encode()+b'\n'
        for name, body in (('archive.zip', self.raw), ('metadata.json', self.metadata_raw)):
            path = self.archive_folder/name; path.write_bytes(body); path.chmod(0o600)
        self.environment = patch.dict(os.environ, GH_TOKEN=TOKEN, GIT_CONFIG_COUNT='0')
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.git = MemoryGit()
        from race_ai.boat_venue_history_handoff import TRANSFER_REF
        self.git.ref = TRANSFER_REF

    def api(self):
        api = importlib.import_module('race_ai.boat_venue_research_retention')
        self.assertTrue(hasattr(api, 'retain_private_source_archives'),
                        'exact encrypted source ZIPs have no append-only retention')
        return api

    def retain(self, api, folders=None, **changes):
        arguments = dict(now=self.now); arguments.update(changes)
        with patch.object(api, 'GitStateRepository', return_value=self.git):
            return api.retain_private_source_archives(
                [self.archive_folder] if folders is None else folders, self.root, **arguments)

    def test_original_cipher_zip_and_exact_metadata_are_retained_idempotently(self):
        api = self.api(); before = dict(os.environ)
        def connect(repo, *, ref):
            self.assertEqual(ref, self.git.ref)
            header = os.environ['GIT_CONFIG_VALUE_0']
            self.assertEqual(base64.b64decode(header.split(' ', 2)[2]), ('x-access-token:'+TOKEN).encode())
            return self.git
        with patch.object(api, 'GitStateRepository', side_effect=connect), contextlib.redirect_stdout(io.StringIO()) as output:
            result = api.retain_private_source_archives([self.archive_folder, self.archive_folder], self.root, now=self.now)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(result['status'], 'OWNER_PRIVATE_SOURCE_ARCHIVES_RETENTION_VERIFIED')
        self.assertEqual(result['retained_archives'], 1)
        pointer = result['pointers'][0]
        sha = hashlib.sha256(self.raw).hexdigest()
        prefix = 'state/boat-venue-history/v1/research-archives/'+sha+'/'
        self.assertEqual(pointer['archive_path'], prefix+'archive.zip')
        self.assertEqual(pointer['archive_sha256'], sha)
        self.assertEqual(pointer['metadata_sha256'], hashlib.sha256(self.metadata_raw).hexdigest())
        tree = self.git.trees[pointer['source_commit']]
        self.assertEqual(set(tree), {'unrelated.enc', prefix+'archive.zip', prefix+'metadata.json', prefix+'manifest.json'})
        self.assertEqual(tree[prefix+'archive.zip'], self.raw)
        self.assertEqual(tree[prefix+'metadata.json'], self.metadata_raw)
        self.assertEqual(hashlib.sha256(tree[prefix+'manifest.json']).hexdigest(), pointer['manifest_sha256'])
        manifest = json.loads(tree[prefix+'manifest.json'])
        self.assertEqual(set(manifest), {'state', 'mac'})
        self.assertRegex(manifest['mac'], '^[a-f0-9]{64}$')
        self.assertEqual(manifest['state']['archive_sha256'], sha)
        first_head = self.git.current
        again = self.retain(api)
        self.assertEqual(again['pointers'], [pointer]); self.assertEqual(self.git.current, first_head)
        self.assertIs(result['plaintext_published'], False)
        self.assertIs(result['production_promoted'], False)
        self.assertNotIn(TOKEN, str(result)); self.assertNotIn('weights', str(result))

    def test_invalid_or_plaintext_archive_and_expired_metadata_never_reach_git(self):
        api = self.api()
        variants = []
        plain = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(plain, 'w') as archive:
            archive.writestr('forecasts.json', '{"plaintext":true}')
        for raw in (b'not a ZIP', plain.getvalue(), self.raw+b'changed'):
            metadata = dict(self.metadata, size_in_bytes=len(raw), digest='sha256:'+hashlib.sha256(raw).hexdigest())
            variants.append((raw, metadata))
        variants.append((self.raw, dict(self.metadata, expired=True)))
        variants.append((self.raw, dict(self.metadata, size_in_bytes=len(self.raw)+1)))
        variants.append((self.raw, dict(self.metadata, expires_at=self.now.isoformat())))
        with patch.object(api, 'GitStateRepository', side_effect=AssertionError('invalid archive must not use Git')):
            for index, (raw, metadata) in enumerate(variants):
                (self.archive_folder/'archive.zip').write_bytes(raw)
                (self.archive_folder/'metadata.json').write_text(json.dumps(metadata))
                with self.subTest(case=index), self.assertRaises(ValueError):
                    api.retain_private_source_archives([self.archive_folder], self.root, now=self.now)

    def test_all_archives_authenticate_before_any_git_and_paths_are_private(self):
        api = self.api(); bad = self.root/'bad'; bad.mkdir(mode=0o700)
        for name, body in (('archive.zip', b'bad'), ('metadata.json', self.metadata_raw)):
            path = bad/name; path.write_bytes(body); path.chmod(0o600)
        with patch.object(api, 'GitStateRepository', side_effect=AssertionError('preflight every source first')):
            with self.assertRaises(ValueError):
                api.retain_private_source_archives([self.archive_folder, bad], self.root, now=self.now)
            (bad/'archive.zip').unlink(); (bad/'archive.zip').symlink_to(self.archive_folder/'archive.zip')
            with self.assertRaises(ValueError):
                api.retain_private_source_archives([bad], self.root, now=self.now)
            (bad/'archive.zip').unlink(); (bad/'archive.zip').write_bytes(self.raw)
            (bad/'archive.zip').chmod(0o644)
            with self.assertRaises(ValueError):
                api.retain_private_source_archives([bad], self.root, now=self.now)
            with self.assertRaises(ValueError):
                api.retain_private_source_archives([self.archive_folder]*10001, self.root, now=self.now)

    def test_source_file_bounds_and_owner_key_token_fail_before_git(self):
        api = self.api()
        with patch.object(api, 'GitStateRepository', side_effect=AssertionError('no Git before bounded auth')):
            for name, limit in (('metadata.json', 32*1024), ('archive.zip', 64*1024*1024)):
                original = (self.archive_folder/name).read_bytes()
                with (self.archive_folder/name).open('wb') as stream: stream.truncate(limit+1)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    api.retain_private_source_archives([self.archive_folder], self.root, now=self.now)
                (self.archive_folder/name).write_bytes(original)
            with patch.dict(os.environ, RACE_AI_STATE_KEY=''), self.assertRaises(ValueError):
                api.retain_private_source_archives([self.archive_folder], self.root, now=self.now)
            with self.assertRaises(ValueError):
                api.retain_private_source_archives([self.archive_folder], self.root, now=self.now, token='')

    def test_remote_immutability_and_exact_readback_fail_closed_and_restore_auth(self):
        api = self.api(); result = self.retain(api); before = dict(os.environ)
        pointer = result['pointers'][0]
        path = pointer['metadata_path']
        original = self.git.trees[self.git.current][path]
        self.git.trees[self.git.current][path] = b'changed'
        with self.assertRaises(ValueError): self.retain(api)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(self.git.trees[self.git.current][path], b'changed')
        self.git.trees[self.git.current][path] = original
        class CorruptReadback(MemoryGit):
            def push(self, commit, parent):
                super().push(commit, parent)
                archive_path = next(name for name in self.trees[commit] if name.endswith('/archive.zip'))
                self.trees[commit][archive_path] += b'bad'
        self.git = CorruptReadback(); self.git.ref = 'state/boat-pdca-transfer'
        with self.assertRaises(ValueError): self.retain(api)
        self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main()
