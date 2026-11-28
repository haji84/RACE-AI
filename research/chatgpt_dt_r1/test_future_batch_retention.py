"""Local bare Git, synthetic RSA/AES, and synthetic GitHub server metadata."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_run_history as codec
from research.chatgpt_dt_r1 import future_batch_retention as retention
from scripts import keirin_dt_r1_future_readback as reader
from scripts import keirin_dt_r1_future_shadow as shadow
from tests.test_keirin_dt_r1_future_readback import FixtureAPI, packet, zip_bytes
from tests import test_keirin_dt_r1_future_shadow as shadow_tests
from tests.test_keirin_nationwide_cipher_history import git


DAY = '2030-01-15'
SLOT = shadow.slot(DAY, '203001159801')
SLOT_2 = shadow.slot(DAY, '203001159802')
STEM = 'research/chatgpt-dt-r1/future/20300115/' + shadow.MODEL_SHA
POINTER = STEM + '/first-slots/' + SLOT + '.json'
LEGACY = STEM + '/first-accepted.json'


def batch_path(run, member):
    return STEM + f'/batches/{run}/{member}'


class FutureBatchRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        shadow_tests.FutureShadowTests.setUpClass()

    def setUp(self):
        key_pin = patch.object(codec.storage, 'PINNED_OWNER_SPKI_SHA256', shadow_tests.FutureShadowTests.pin)
        key_pin.start()
        self.addCleanup(key_pin.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote = self.root / 'authority.git'
        self.writer = self.root / 'writer'
        self.other = self.root / 'other'
        git(self.root, 'init', '--bare', '-b', archive.BRANCH, str(self.remote))
        git(self.root, 'clone', str(self.remote), str(self.writer))
        git(self.writer, 'config', 'user.name', 'Fixture')
        git(self.writer, 'config', 'user.email', 'fixtures@example.invalid')
        old = self.writer / LEGACY
        old.parent.mkdir(parents=True)
        old.write_bytes(b'original fixture stays unchanged\n')
        git(self.writer, 'add', LEGACY)
        git(self.writer, 'commit', '-m', 'fixture legacy pin')
        git(self.writer, 'push', 'origin', f'HEAD:refs/heads/{archive.BRANCH}')
        self.source_head = git(self.writer, 'rev-parse', 'HEAD')
        git(self.root, 'clone', str(self.remote), str(self.other))

    @contextmanager
    def verified_batch(self, run='456', *, read_run='789', late=False, source_head=None, two_slots=False):
        fixture = shadow_tests.FutureShadowTests()
        fixture.setUp()
        fixture.store.head = source_head or self.source_head
        if two_slots:
            payload, original = shadow_tests.second_race_original()
            rid = original['race_id']
            fixture.store.index['originals'][rid] = dict(fixture.original_meta, race_id=rid)
            read = fixture.store.read
            fixture.store.read = lambda meta, private: (
                deepcopy(payload) if meta.get('race_id') == rid else read(meta, private))
            fixture.admit.side_effect = lambda source, row, *a, **k: (
                deepcopy(original if row['race_id'] == rid else fixture.original), {'synthetic': True})
        try:
            with patch.dict(os.environ, {'GITHUB_RUN_ID': run}):
                summary = fixture.produce()
            producer = packet(run, report=summary, head='c' * 40)
            cipher = deepcopy(producer)
            cipher_id = int(run) + 3000
            artifact = cipher['artifact']
            url = producer['artifact']['url'].rsplit('/', 1)[0] + f'/{cipher_id}'
            zipped = zip_bytes({path.name: path.read_bytes() for path in fixture.output.iterdir()})
            artifact.update(id=cipher_id, name=f'keirin-dt-r1-future-cipher-{run}', url=url,
                            archive_download_url=url + '/zip', size_in_bytes=len(zipped),
                            digest='sha256:' + sha256(zipped).hexdigest())
            cipher['archive_bytes'] = zipped
            report = reader.readback(run, reader_run_id=read_run, reader_code_commit='d' * 40,
                client=FixtureAPI([producer, cipher]).client,
                clock=lambda: datetime.fromisoformat('2030-01-15T02:03:30+00:00'))
            read = packet(read_run, report=report, head='d' * 40, minute=3)
            if late:
                read['job']['completed_at'] = '2030-01-15T03:33:00Z'
            client = FixtureAPI([producer, cipher, read]).client
            with reader.verified_producer(run, client=client) as verified:
                yield verified, reader.verify_readback(verified, read_run, client=client)
        finally:
            fixture.doCleanups()

    def append(self, verified, origin, *, repo=None, legacy=(), **kwargs):
        return retention.append_verified_batch(
            repo or self.writer, verified, origin, legacy_accepted_slots=legacy, synthetic_local=True, **kwargs)

    def head(self, repo=None):
        return archive._refresh(repo or self.writer, blobless=True)

    def retained(self, repo=None):
        repo = repo or self.other
        return retention.retained_slots(repo, self.head(repo), DAY, shadow.MODEL_SHA, [SLOT])

    def test_first_winner_preserves_exact_manifest_cipher_and_readback(self):
        first_head = self.head()
        with self.verified_batch() as (verified, origin):
            observed = self.append(verified, origin)
            source = verified['directory']
            self.assertEqual(observed['state'], 'DT_R1_FUTURE_BATCH_APPENDED')
            self.assertEqual(observed['registered_races'], 78)
            self.assertEqual(observed['new_first_slots'], 1)
            self.assertEqual(observed['retained_files'], 4)
            commit = observed['archive_commit']
            self.assertEqual(git(self.writer, 'rev-parse', commit + '^'), first_head)
            for name in ('manifest.json', SLOT + '.sealed.json'):
                self.assertEqual(archive.read_blob_bytes(self.writer, commit, batch_path('456', name)),
                                 (source / name).read_bytes())
            self.assertEqual(archive.read_blob_bytes(self.writer, commit, batch_path('456', 'readback.json')),
                             codec._canonical(origin))
            self.assertEqual(archive.read_blob_bytes(self.writer, commit, LEGACY),
                             b'original fixture stays unchanged\n')
        self.assertEqual(self.retained(), {SLOT})

    def test_replay_reads_only_the_first_accepted_entry_from_its_verified_batch(self):
        with self.verified_batch(two_slots=True) as (verified, origin):
            self.append(verified, origin, legacy=[SLOT_2])
            authenticated = []
            head = self.head(self.other)
            saved = retention.read_retained_forecasts(self.other, head, DAY, shadow.MODEL_SHA,
                [SLOT, SLOT_2], authenticate_batch=lambda *args: authenticated.append(args))
            self.assertEqual(set(saved), {SLOT})
            manifest = verified['manifest']
            self.assertEqual(authenticated, [(manifest, origin, verified['manifest_sha256'])])
            self.assertEqual(saved[SLOT]['manifest'], manifest)
            self.assertEqual(saved[SLOT]['entry']['slot_sha256'], SLOT)
            self.assertEqual(saved[SLOT]['cipher_path'], batch_path('456', SLOT + '.sealed.json'))

    def test_day_replay_detects_a_removed_registry_slot_even_if_its_pointer_was_deleted(self):
        with self.verified_batch() as (verified, origin):
            self.append(verified, origin)
        for delete in (False, True):
            if delete:
                self.delete_archive_file(POINTER)
            with self.subTest(delete=delete), self.assertRaisesRegex(ValueError, 'POINTER_OUTSIDE_REGISTRY'):
                retention.read_retained_forecasts(self.other, self.head(self.other), DAY, shadow.MODEL_SHA,
                                                  [SLOT_2], verify_registry=True)

    def test_repeated_and_later_bundles_do_not_create_new_files_or_replace_pointer(self):
        with self.verified_batch() as (verified, origin):
            commit = self.append(verified, origin)['archive_commit']
            again = self.append(verified, origin)
            first_pointer = archive.read_blob_bytes(self.writer, commit, POINTER)
        with self.verified_batch(run='457', read_run='790') as (verified, origin):
            later = self.append(verified, origin, repo=self.other)
        for observed in (again, later):
            self.assertEqual(observed['state'], 'DT_R1_FUTURE_BATCH_NO_NEW_FIRST_SLOTS')
            self.assertEqual(observed['archive_commit'], commit)
            self.assertEqual(observed['already_accepted_slots'], 1)
            self.assertEqual(observed['retained_files'], 0)
        self.assertEqual(self.head(), commit)
        self.assertEqual(archive.read_blob_bytes(self.writer, commit, POINTER), first_pointer)
        self.assertIsNone(archive.read_blob_bytes(self.writer, commit, batch_path('457', 'manifest.json')))

    def test_late_receipt_or_verified_legacy_slot_does_not_create_pointer(self):
        start = self.head()
        with self.verified_batch(late=True) as (verified, origin):
            observed = self.append(verified, origin)
            self.assertEqual(observed['independently_timed_candidates'], 0)
            self.assertEqual(observed['state'], 'DT_R1_FUTURE_BATCH_NO_NEW_FIRST_SLOTS')
            overclaimed = dict(origin, eligible_slots=[SLOT], held_slots={})
            with self.assertRaisesRegex(ValueError, 'READBACK_SLOT_PARTITION'):
                self.append(verified, overclaimed)
        with self.verified_batch() as (verified, origin):
            observed = self.append(verified, origin, legacy=[SLOT])
            self.assertEqual(observed['independently_timed_candidates'], 1)
            self.assertEqual(observed['already_accepted_slots'], 1)
            self.assertEqual(observed['new_first_slots'], 0)
        self.assertEqual(self.head(), start)
        self.assertEqual(self.retained(), set())

    def test_malformed_pointer_and_damaged_cipher_fail_closed(self):
        with self.verified_batch() as (verified, origin):
            self.append(verified, origin)
        original_head = self.head()
        for damaged in (batch_path('456', SLOT + '.sealed.json'), batch_path('456', 'readback.json'), POINTER):
            with self.subTest(path=damaged):
                saved = archive.read_blob_bytes(self.writer, original_head, damaged)
                status, broken = archive._push_archive_files(
                    self.writer, self.head(), {damaged: b'{}\n'},
                    'synthetic archive damage', replace_path=damaged)
                self.assertEqual(status, 0)
                with self.assertRaises(ValueError):
                    self.retained()
                with self.verified_batch(run='457', read_run='790') as (verified, origin):
                    with self.assertRaises(ValueError):
                        self.append(verified, origin)
                self.assertEqual(self.head(), broken)
                restored, _ = archive._push_archive_files(
                    self.writer, broken, {damaged: saved}, 'restore synthetic fixture', replace_path=damaged)
                self.assertEqual(restored, 0)
                if damaged == POINTER:
                    with self.assertRaisesRegex(ValueError, 'ARCHIVE_POINTER_CHANGED'):
                        self.retained()
                else:
                    self.assertEqual(self.retained(), {SLOT})

    def delete_archive_file(self, path):
        head = self.head()
        with TemporaryDirectory() as temporary:
            index = Path(temporary) / 'index'
            archive._cmd(self.writer, 'read-tree', head, index_path=index)
            archive._cmd(self.writer, 'update-index', '--force-remove', '--', path, index_path=index)
            tree = archive._cmd(self.writer, 'write-tree', index_path=index)[1]
        commit = git(self.writer, 'commit-tree', tree, '-p', head, '-m', 'delete a synthetic archive path')
        git(self.writer, 'push', 'origin', f'{commit}:refs/heads/{archive.BRANCH}')
        return commit

    def test_deleted_pointer_in_ancestry_blocks_recreation(self):
        with self.verified_batch() as (verified, origin):
            self.append(verified, origin)
        deleted = self.delete_archive_file(POINTER)
        self.assertIsNone(archive.read_blob_bytes(self.writer, deleted, POINTER))
        with self.assertRaises(ValueError):
            self.retained()
        with self.verified_batch(run='457', read_run='790') as (verified, origin):
            with self.assertRaises(ValueError):
                self.append(verified, origin)
        self.assertEqual(self.head(), deleted)

    def test_coherent_replacement_with_new_valid_batch_is_refused(self):
        with self.verified_batch() as (verified, origin):
            first = self.append(verified, origin)['write_commit']
        with self.verified_batch(run='457', read_run='790') as (verified, origin):
            manifest = (verified['directory'] / 'manifest.json').read_bytes()
            receipt = codec._canonical(origin)
            cipher = (verified['directory'] / (SLOT + '.sealed.json')).read_bytes()
            pointer = codec._json(archive.read_blob_bytes(self.writer, first, POINTER))
            pointer.update(producer_run_id='457', manifest_sha256=sha256(manifest).hexdigest(),
                           readback_sha256=sha256(receipt).hexdigest(), cipher_sha256=sha256(cipher).hexdigest())
            status, replacement = archive._push_archive_files(self.writer, first, {
                POINTER: codec._canonical(pointer), batch_path('457', 'manifest.json'): manifest,
                batch_path('457', 'readback.json'): receipt, batch_path('457', SLOT + '.sealed.json'): cipher,
            }, 'synthetic coherent pointed-batch replacement', replace_path=POINTER)
            self.assertEqual(status, 0)
            with self.assertRaises(ValueError):
                self.retained()
            with self.assertRaises(ValueError):
                self.append(verified, origin)
        self.assertEqual(self.head(), replacement)

    def test_manifest_only_modification_breaks_identical_introduction(self):
        with self.verified_batch() as (verified, origin):
            first = self.append(verified, origin)['write_commit']
        manifest = batch_path('456', 'manifest.json')
        changed = codec._json(archive.read_blob_bytes(self.writer, first, manifest))
        changed['summary']['day_inventory_complete'] = False
        status, _ = archive._push_archive_files(
            self.writer, first, {manifest: codec._canonical(changed)}, 'synthetic manifest edit',
            replace_path=manifest)
        self.assertEqual(status, 0)
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_INTRODUCTION_MISMATCH'):
            self.retained()

    def test_shallow_state_history_cannot_hide_a_deleted_pointer(self):
        with self.verified_batch() as (verified, origin):
            self.append(verified, origin)
        deleted = self.delete_archive_file(POINTER)
        shallow = self.root / 'shallow-state'
        git(self.root, 'clone', '--depth=1', self.remote.as_uri(), str(shallow))
        with self.assertRaisesRegex(ValueError, 'ARCHIVE_ANCESTRY_TRUNCATED'):
            retention.retained_slots(shallow, deleted, DAY, shadow.MODEL_SHA, [SLOT])

    def test_shallow_unrelated_checkout_allows_complete_state_history(self):
        with self.verified_batch() as (verified, origin):
            head = self.append(verified, origin)['archive_commit']
        tree = git(self.writer, 'rev-parse', head + '^{tree}')
        main = git(self.writer, 'commit-tree', tree, '-m', 'fixture unrelated checkout')
        git(self.writer, 'push', 'origin', f'{main}:refs/heads/fixture-main')
        checkout = self.root / 'shallow-main'
        git(self.root, 'clone', '--depth=1', '--branch', 'fixture-main', self.remote.as_uri(), str(checkout))
        self.assertEqual(git(checkout, 'rev-parse', '--is-shallow-repository'), 'true')
        self.assertEqual(archive._refresh(checkout, blobless=True), head)
        self.assertEqual(retention.retained_slots(checkout, head, DAY, shadow.MODEL_SHA, [SLOT]), {SLOT})

    def test_batch_authentication_once_per_batch_and_required_for_no_op(self):
        with self.verified_batch(two_slots=True) as (verified, origin):
            saved = self.append(verified, origin)
            seen = []

            def authenticate(manifest, readback, manifest_sha):
                seen.append((manifest, readback, manifest_sha))

            self.assertEqual(retention.retained_slots(
                self.other, self.head(self.other), DAY, shadow.MODEL_SHA, [SLOT, SLOT_2],
                authenticate_batch=authenticate), {SLOT, SLOT_2})
            self.assertEqual(seen, [(verified['manifest'], origin, verified['manifest_sha256'])])
            seen.clear()
            replay = self.append(verified, origin, authenticate_batch=authenticate)
            self.assertEqual(replay['already_accepted_slots'], 2)
            self.assertEqual(len(seen), 1)

            def rejected(*args):
                raise ValueError('synthetic authenticated proof mismatch')

            with self.assertRaisesRegex(ValueError, 'authenticated proof mismatch'):
                self.append(verified, origin, authenticate_batch=rejected)
            self.assertEqual(self.head(), saved['archive_commit'])

    def test_verified_batch_from_unrelated_source_history_cannot_write(self):
        start = self.head()
        tree = git(self.writer, 'rev-parse', start + '^{tree}')
        unrelated = git(self.writer, 'commit-tree', tree, '-m', 'standalone archive history')
        with self.verified_batch(source_head=unrelated) as (verified, origin):
            with self.assertRaisesRegex(ValueError, 'INDEX_COMMIT_OUTSIDE_OFFICIAL_ARCHIVE'):
                self.append(verified, origin)
        self.assertEqual(self.head(), start)
        self.assertIsNone(archive.read_blob_bytes(self.writer, start, POINTER))

    def test_acknowledged_write_requires_same_files_at_the_observed_tip(self):
        real_push = archive._push_archive_files
        manifest = batch_path('456', 'manifest.json')

        def change_after_ack(repo, parent, files, message):
            status, commit = real_push(repo, parent, files, message)
            self.assertEqual(status, 0)
            changed = codec._json(files[manifest])
            changed['summary']['day_inventory_complete'] = False
            alter_status, _ = real_push(repo, commit, {manifest: codec._canonical(changed)},
                'synthetic later manifest edit', replace_path=manifest)
            self.assertEqual(alter_status, 0)
            return status, commit

        with self.verified_batch() as (verified, origin):
            with patch.object(archive, '_push_archive_files', side_effect=change_after_ack):
                with self.assertRaisesRegex(ValueError, 'ARCHIVE_READBACK_MISMATCH'):
                    self.append(verified, origin)

    def test_non_fast_forward_loser_replays_and_preserves_the_winning_slot(self):
        real_push = archive._push_archive_files
        with self.verified_batch() as (first, first_origin), self.verified_batch(run='457', read_run='790') as (
            winner, winner_origin
        ):
            def racing_push(repo, parent, files, message):
                if repo == self.writer:
                    competing = self.append(winner, winner_origin, repo=self.other)
                    self.assertEqual(competing['new_first_slots'], 1)
                return real_push(repo, parent, files, message)

            with patch.object(archive, '_push_archive_files', side_effect=racing_push):
                lost = self.append(first, first_origin)
        self.assertEqual(lost['state'], 'DT_R1_FUTURE_BATCH_NO_NEW_FIRST_SLOTS')
        self.assertEqual(lost['already_accepted_slots'], 1)
        head = self.head()
        self.assertIsNone(archive.read_blob_bytes(self.writer, head, batch_path('456', 'manifest.json')))
        self.assertIsNotNone(archive.read_blob_bytes(self.writer, head, batch_path('457', 'manifest.json')))
        self.assertEqual(self.retained(), {SLOT})


if __name__ == '__main__':
    unittest.main()
