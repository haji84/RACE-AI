"""Real fixture AES and bounded immutable research batches, without networking."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import os
import subprocess
import unittest
from unittest.mock import patch

from race_ai import boat_venue_learning_handoff as H
from race_ai.boat_venue_learning import fit_venue_rows, seal_candidate, read_candidate
from race_ai.boat_venue_history_handoff import TRANSFER_REF
from tests.test_boat_venue_history_handoff import MemoryGit
from tests.test_boat_venue_learning import venue_data, POINTER
from tests.test_observed_weight_learning import NOW


class CountingGit(MemoryGit):
    def __init__(self, repo, *, shared=None):
        super().__init__()
        self.repo, self.ref = repo, TRANSFER_REF
        self.fetches, self.commits, self.pushes = [], [], []
        if shared is not None:
            self.trees = shared.trees

    def fetch(self, commit):
        self.fetches.append(commit)

    def commit(self, files, parent):
        self.commits.append((set(files), parent))
        return super().commit(files, parent)

    def push(self, commit, parent):
        self.pushes.append((commit, parent))
        return super().push(commit, parent)


class ResearchBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, observations = venue_data(8)
        cls.payload = fit_venue_rows(rows, observations, dataset_pointer=POINTER,
                                    now=NOW, allow_training=lambda *args: True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict('os.environ', RACE_AI_STATE_KEY=base64.b64encode(bytes(range(32))).decode())
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.folders, self.payloads = [], []
        for index in range(3):
            payload = deepcopy(self.payload)
            payload['excluded'].append({'reason': 'SYNTHETIC_ONLY_' + str(index)})
            folder = self.root / str(index)
            seal_candidate(payload, folder)
            self.folders.append(folder)
            self.payloads.append(payload)
        self.writer = CountingGit(self.root / 'writer')
        self.reader = CountingGit(self.root / 'independent-reader', shared=self.writer)

    def publish(self, folders=None, **options):
        function = getattr(H, 'publish_learning_candidates', None)
        self.assertTrue(callable(function), 'immutable partitions still publish one Git commit at a time')
        return function(self.folders if folders is None else folders, self.root,
                        transport=self.writer, readback_transport=self.reader, **options)

    def test_three_authenticated_candidates_share_one_append_and_independent_readback(self):
        pointers = self.publish()
        self.assertEqual(len(pointers), 3)
        self.assertEqual(len(self.writer.commits), 1)
        self.assertEqual(len(self.writer.pushes), 1)
        self.assertEqual(self.writer.fetches, ['a' * 40])
        self.assertEqual(self.reader.fetches, [self.writer.current])
        self.assertEqual(len(self.writer.trees[self.writer.current]), 10)
        self.assertEqual(self.writer.trees[self.writer.current]['unrelated.enc'], b'preserve')
        for index, pointer in enumerate(pointers):
            self.assertEqual(pointer['source_commit'], self.writer.current)
            output = self.root / ('restored-' + str(index))
            H.restore_learning_candidate(pointer, output, self.root, transport=self.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])
            for name in H.FILES:
                self.assertEqual((output / name).read_bytes(), (self.folders[index] / name).read_bytes())

    def test_every_candidate_authenticates_before_any_git_or_partial_publication(self):
        summary = self.folders[-1] / 'summary.json'
        summary.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.writer.fetches + self.writer.commits + self.writer.pushes, [])

    def test_existing_immutable_bytes_and_corrupt_independent_readback_fail_closed(self):
        pointers = self.publish()
        path = pointers[0]['manifest_path'].removesuffix('learning.json') + 'learning.enc'
        original = self.writer.trees[self.writer.current][path]
        self.writer.trees[self.writer.current][path] = original + b'changed'
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(len(self.writer.commits), 1)
        self.writer.trees[self.writer.current][path] = original
        with patch.object(self.reader, 'read', return_value=b'corrupt'):
            with self.assertRaises(ValueError):
                self.publish()
        self.assertEqual(len(self.writer.commits), 1)

    def test_republish_is_idempotent_but_rechecks_independent_bytes(self):
        first = self.publish()
        again = self.publish()
        self.assertEqual(again, first)
        self.assertEqual(len(self.writer.commits), 1)
        self.assertEqual(self.reader.fetches, [self.writer.current] * 2)

    def test_memory_bound_splits_batches_without_dropping_any_candidate(self):
        sizes = [sum((folder / name).stat().st_size for name in H.FILES) for folder in self.folders]
        self.assertTrue(hasattr(H, 'MAX_RESEARCH_BATCH_BYTES'))
        with patch.object(H, 'MAX_RESEARCH_BATCH_BYTES', max(sizes)):
            pointers = self.publish()
        self.assertEqual(len(pointers), 3)
        self.assertEqual(len(self.writer.commits), 3)
        self.assertEqual(len(self.writer.pushes), 3)
        self.assertEqual(len(self.writer.trees[self.writer.current]), 10)
        for index, pointer in enumerate(pointers):
            output = self.root / ('chunk-restored-' + str(index))
            H.restore_learning_candidate(pointer, output, self.root, transport=self.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])

    def test_same_object_database_cannot_be_called_independent(self):
        function = getattr(H, 'publish_learning_candidates', None)
        self.assertTrue(callable(function))
        with self.assertRaises(ValueError):
            function(self.folders, self.root, transport=self.writer, readback_transport=self.writer)
        self.assertEqual(self.writer.commits, [])

    def test_fresh_research_transfer_restores_only_requested_blobs_and_preserves_unrelated_oid(self):
        from tests.test_boat_private_original_vault import VaultTests
        fixture = VaultTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)

        class LocalResearchRepository(H.GitStateRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(['remote', 'get-url', 'origin']).decode().strip()

        root = fixture.root / 'fresh-research-writer'
        subprocess.run(['git', 'init', str(root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(root), 'remote', 'add', 'origin', str(fixture.remote)],
                       check=True, capture_output=True)
        writer = LocalResearchRepository(root, ref=TRANSFER_REF)
        oid = fixture.writer._run(['rev-parse', fixture.parent + ':unrelated/retained.enc']).decode().strip()
        writer.fetch(fixture.parent)
        present = lambda: subprocess.run(['git', '-C', str(root), 'cat-file', '-e', oid],
            env=dict(os.environ, GIT_NO_LAZY_FETCH='1'), capture_output=True).returncode == 0
        self.assertFalse(present(), 'research transfer fetched unrelated ciphertext before using any candidate')
        pointers = H.publish_learning_candidates(self.folders, root, transport=writer,
                                                readback_transport=fixture.reader)
        self.assertFalse(present(), 'research append hydrated the inherited ciphertext tree')
        retained = writer._run(['rev-parse', pointers[-1]['source_commit'] + ':unrelated/retained.enc']).decode().strip()
        self.assertEqual(retained, oid)
        for index, pointer in enumerate(pointers):
            output = self.root / ('sparse-restored-' + str(index))
            H.restore_learning_candidate(pointer, output, root, transport=fixture.reader)
            self.assertEqual(read_candidate(output), self.payloads[index])

    def local_git(self):
        from tests.test_boat_private_original_vault import VaultTests
        fixture = VaultTests('runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def selected_files(self, pointers):
        return {pointer['manifest_path'].removesuffix('learning.json') + name:
                (folder / name).read_bytes()
                for folder, pointer in zip(self.folders, pointers) for name in H.FILES}

    def selected_fetch_count(self, trace):
        if not trace.exists():
            return 0
        rows = (json.loads(line) for line in trace.read_text().splitlines())
        return sum(row.get('event') == 'start' and 'fetch' in row.get('argv', []) and
                   '--stdin' in row['argv'] for row in rows)

    def prefetch(self, reader, commit, files):
        method = getattr(reader, 'prefetch_selected', None)
        self.assertTrue(callable(method), 'selected blob reads still fetch one object at a time')
        result = method(commit, files, maximum_bytes=H.MAX_RESEARCH_BATCH_BYTES)
        self.assertTrue(callable(result))
        return result

    def test_actual_git_no_lazy_fetch_refuses_missing_promised_blob_without_network(self):
        fixture = self.local_git()
        reader = fixture.git('missing-local-object-reader')
        reader.fetch(fixture.parent)
        oid = fixture.writer._run(['rev-parse', fixture.parent + ':unrelated/retained.enc']).decode().strip()
        trace = self.root / 'no-lazy-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), self.assertRaises(ValueError):
            reader._run(['--no-lazy-fetch', 'cat-file', '-s', oid])
        self.assertEqual(self.selected_fetch_count(trace), 0)
        # The same real object is available remotely: the ordinary reader must
        # fetch it, proving that the previous refusal was genuinely local-only.
        ordinary = self.root / 'ordinary-lazy-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(ordinary)):
            self.assertEqual(reader.read(fixture.parent, 'unrelated/retained.enc', 100), b'existing ciphertext')
        self.assertEqual(self.selected_fetch_count(ordinary), 1)

    def test_real_git_selected_fetch_is_one_per_group_even_on_fresh_idempotent_retry(self):
        fixture = self.local_git()
        first = None
        inherited = fixture.writer._run(['rev-parse', fixture.parent + ':unrelated/retained.enc']).decode().strip()
        for number in (1, 2):
            reader = fixture.git('selected-reader-' + str(number))
            trace = self.root / ('selected-trace-' + str(number) + '.jsonl')
            with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)):
                pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
                    transport=fixture.writer, readback_transport=reader)
            self.assertEqual(len(pointers), len(self.folders))
            if first is None: first = pointers
            else: self.assertEqual(pointers, first)
            for path, body in self.selected_files(pointers).items():
                self.assertEqual(reader.read(pointers[0]['source_commit'], path, H.MAX_RESEARCH_BATCH_BYTES), body)
            missing = subprocess.run(['git', '--no-lazy-fetch', '-C', str(reader.repo), 'cat-file', '-e', inherited],
                                     capture_output=True).returncode != 0
            self.assertTrue(missing, 'selected readback hydrated an unrelated inherited ciphertext')
            self.assertEqual(self.selected_fetch_count(trace), 1)

    def test_real_git_multiple_groups_read_every_file_with_one_selected_fetch_each(self):
        fixture = self.local_git()
        reader = fixture.git('multi-group-reader')
        sizes = [sum((folder / name).stat().st_size for name in H.FILES) for folder in self.folders]
        trace = self.root / 'multi-group-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), patch.object(H, 'MAX_RESEARCH_BATCH_BYTES', max(sizes)):
            pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
                transport=fixture.writer, readback_transport=reader)
        self.assertEqual(len(pointers), 3)
        self.assertEqual(len({pointer['source_commit'] for pointer in pointers}), 3)
        self.assertEqual(self.selected_fetch_count(trace), 3)
        for folder, pointer in zip(self.folders, pointers):
            prefix = pointer['manifest_path'].removesuffix('learning.json')
            for name, limit in H.FILES.items():
                self.assertEqual(reader.read(pointer['source_commit'], prefix + name, limit), (folder / name).read_bytes())

    def test_suppressed_bulk_fetch_success_cannot_fall_back_to_lazy_network_reads(self):
        from tests.test_boat_private_original_vault import LocalGit
        fixture = self.local_git()
        class SuppressedFetch(LocalGit):
            suppressed = 0
            partial = False
            def _run(self, args, **options):
                if 'fetch' in args and '--stdin' in args:
                    self.suppressed += 1
                    if self.partial:
                        options['body'] = options['body'].splitlines()[0] + b'\n'
                        return super()._run(args, **options)
                    return b''
                return super()._run(args, **options)
        for partial in (False, True):
            original = fixture.git('suppressed-fetch-reader-' + str(partial))
            reader = SuppressedFetch(original.repo, ref=TRANSFER_REF); reader.partial = partial
            trace = self.root / ('suppressed-trace-' + str(partial) + '.jsonl')
            with self.subTest(partial=partial), patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), self.assertRaises(ValueError):
                H.publish_learning_candidates(self.folders, fixture.writer.repo,
                    transport=fixture.writer, readback_transport=reader)
            self.assertEqual(reader.suppressed, 1)
            self.assertEqual(self.selected_fetch_count(trace), int(partial), 'missing prefetched objects silently fetched themselves')
        retry = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.git('retry-after-suppression'))
        self.assertEqual(len(retry), 3)

    def test_bulk_timeout_refuses_acknowledgement_without_a_lazy_fallback(self):
        fixture = self.local_git()
        reader = fixture.git('timeout-reader'); trace = self.root / 'timeout-trace.jsonl'
        original = subprocess.run
        def timeout(args, **options):
            if 'fetch' in args and '--stdin' in args:
                raise subprocess.TimeoutExpired(args, 180)
            return original(args, **options)
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), patch('subprocess.run', side_effect=timeout), \
                self.assertRaisesRegex(ValueError, '^VAULT_GIT_FETCH_TIMEOUT$'):
            H.publish_learning_candidates(self.folders, fixture.writer.repo,
                transport=fixture.writer, readback_transport=reader)
        self.assertEqual(self.selected_fetch_count(trace), 0)

    def test_corrupt_remote_selected_object_is_fatal_and_exact_restored_retry_is_idempotent(self):
        fixture = self.local_git()
        pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.reader)
        commit = pointers[0]['source_commit']
        path = pointers[0]['manifest_path'].removesuffix('learning.json') + 'learning.enc'
        oid = fixture.writer._run(['rev-parse', commit + ':' + path]).decode().strip()
        target = fixture.remote / 'objects' / oid[:2] / oid[2:]
        old = target.read_bytes() if target.exists() else None
        mode = target.stat().st_mode & 0o777 if old is not None else None
        target.parent.mkdir(exist_ok=True)
        if old is not None: target.chmod(0o600)
        target.write_bytes(b'corrupt fixture Git object')
        try:
            with self.assertRaises(ValueError):
                H.publish_learning_candidates(self.folders, fixture.writer.repo,
                    transport=fixture.writer, readback_transport=fixture.git('corrupt-remote-reader'))
        finally:
            if old is None: target.unlink()
            else:
                target.write_bytes(old); target.chmod(mode)
        self.assertEqual(fixture.writer.head(), commit)
        retry = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.git('restored-remote-reader'))
        self.assertEqual(retry, pointers)

    def test_selected_blob_disappearing_after_prefetch_still_cannot_lazy_fetch(self):
        fixture = self.local_git()
        pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.reader)
        commit = pointers[0]['source_commit']; files = self.selected_files(pointers)
        reader = fixture.git('disappearing-object-reader'); reader.fetch(commit)
        read = self.prefetch(reader, commit, files)
        path = next(path for path in files if path.endswith('/learning.enc'))
        oid = reader._run(['rev-parse', commit + ':' + path]).decode().strip()
        loose = reader.repo / '.git' / 'objects' / oid[:2] / oid[2:]
        if loose.exists():
            loose.unlink()
        else:
            packs = list((reader.repo / '.git' / 'objects' / 'pack').glob('*.idx'))
            matched = []
            for index in packs:
                inventory = reader._run(['verify-pack', '-v', str(index)])
                if any(line.startswith(oid.encode() + b' ') for line in inventory.splitlines()):
                    matched.append(index)
            self.assertEqual(len(matched), 1)
            for suffix in ('.pack', '.idx', '.promisor'):
                matched[0].with_suffix(suffix).unlink(missing_ok=True)
        self.assertEqual(reader._run(['--no-lazy-fetch', 'cat-file', '-t', commit]).strip(), b'commit')
        trace = self.root / 'disappeared-object-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), self.assertRaises(ValueError):
            read(commit, path, H.MAX_RESEARCH_BATCH_BYTES)
        self.assertEqual(self.selected_fetch_count(trace), 0)
        ordinary = self.root / 'disappeared-ordinary-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(ordinary)):
            self.assertEqual(reader.read(commit, path, H.MAX_RESEARCH_BATCH_BYTES), files[path])
        self.assertEqual(self.selected_fetch_count(ordinary), 1)

    def test_selected_tree_rows_and_local_blob_metadata_are_strict(self):
        fixture = self.local_git()
        pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.reader)
        files = self.selected_files(pointers); commit = pointers[0]['source_commit']
        reader = fixture.git('tree-guards-reader'); reader.fetch(commit)
        original = reader._run
        method = getattr(reader, 'prefetch_selected', None)
        self.assertTrue(callable(method), 'selected tree binding is missing')
        for case in ('missing', 'duplicate', 'extra_path', 'nonascii_path', 'mode', 'type', 'oid', 'local_type', 'local_size'):
            def altered(args, **options):
                raw = original(args, **options)
                if 'ls-tree' in args:
                    if case == 'missing': return b''
                    if case == 'duplicate': return raw + raw.split(b'\0')[0] + b'\0'
                    if case == 'extra_path': return raw + raw.split(b'\t')[0] + b'\tunselected/path\0'
                    if case == 'nonascii_path': return raw.split(b'\t')[0] + b'\t\xff\0'
                    if case == 'mode': return raw.replace(b'100644 ', b'100755 ', 1)
                    if case == 'type': return raw.replace(b' blob ', b' tree ', 1)
                    if case == 'oid':
                        first = raw.split(b'\t')[0].split(b' ')[-1]
                        return raw.replace(first, b'f' * 40, 1)
                if any(arg.startswith('--batch-check') for arg in args):
                    if case == 'local_type': return raw.replace(b' blob ', b' commit ', 1)
                    if case == 'local_size':
                        line = raw.splitlines()[0]; changed = line.rsplit(b' ', 1)[0] + b' 999999999'
                        return raw.replace(line, changed, 1)
                return raw
            with self.subTest(case=case), patch.object(reader, '_run', side_effect=altered), \
                    self.assertRaisesRegex(ValueError, '^VAULT_SELECTED_[A-Z_]+$'):
                method(commit, files, maximum_bytes=H.MAX_RESEARCH_BATCH_BYTES)

    def test_remote_url_changes_are_refused_before_the_selected_fetch(self):
        fixture = self.local_git()
        pointers = H.publish_learning_candidates(self.folders, fixture.writer.repo,
            transport=fixture.writer, readback_transport=fixture.reader)
        reader = fixture.git('remote-change-reader'); commit = pointers[0]['source_commit']; reader.fetch(commit)
        other = fixture.root / 'other-remote.git'
        subprocess.run(['git', 'init', '--bare', str(other)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(reader.repo), 'remote', 'set-url', 'origin', str(other)], check=True, capture_output=True)
        method = getattr(reader, 'prefetch_selected', None); self.assertTrue(callable(method))
        trace = self.root / 'changed-remote-trace.jsonl'
        with patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)), self.assertRaises(ValueError):
            method(commit, self.selected_files(pointers), maximum_bytes=H.MAX_RESEARCH_BATCH_BYTES)
        self.assertEqual(self.selected_fetch_count(trace), 0)

    def test_ten_thousand_folder_selections_use_bounded_arguments_without_truncation(self):
        fixture = self.local_git(); reader = fixture.reader; reader.fetch(fixture.parent)
        body = b'bounded selected bytes'
        oid = reader._run(['hash-object', '-w', '--stdin'], body=body).strip()
        files = {f'state/boat-venue-history/v1/learning/{number:064x}/{name}': body
                 for number in range(10000) for name in H.FILES}
        seen = []; original = reader._run; counts = []
        def tree(args, **options):
            if 'ls-tree' in args:
                paths = args[args.index('--') + 1:]; seen.extend(paths)
                counts.append(sum(len(arg.encode()) + 1 for arg in args))
                return b''.join(b'100644 blob ' + oid + b'\t' + path.encode() + b'\0' for path in paths)
            return original(args, **options)
        with patch.object(reader, '_run', side_effect=tree):
            self.prefetch(reader, fixture.parent, files)
        self.assertEqual(len(seen), 30000)
        self.assertEqual(set(seen), set(files))
        self.assertLessEqual(max(counts), 32 * 1024)


if __name__ == '__main__':
    unittest.main()
