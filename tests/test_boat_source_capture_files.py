"""Private descriptor preflight; original clocks/bytes are never rewritten."""
from datetime import timedelta, timezone
from hashlib import sha256
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import boat_private_original_vault as V
from tests.test_boat_private_original_vault import NOW
from tests.test_boat_source_capture_batching import capture

try:
    from race_ai.boat_source_capture_files import CaptureInventory
except ImportError:
    CaptureInventory = None


class CaptureInventoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(CaptureInventory, 'Bounded, fully preflighted capture inventory is absent.')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.folder = self.root/'captures'
        self.repo = self.root/'repo'; self.repo.mkdir(mode=0o700)

    def inventory(self, **kwargs):
        return CaptureInventory(self.folder, repo=self.repo, now=NOW, **kwargs)

    def test_no_logical_count_cap_and_private_spool_has_indexed_bounded_cache(self):
        originals = [capture(self.folder, n) for n in range(481)]
        with self.inventory() as inventory:
            self.assertEqual(inventory.count, 481)
            spool = inventory.spool_path
            self.assertEqual(spool.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(spool.stat().st_mode & 0o777, 0o600)
            self.assertLessEqual(abs(inventory._db.execute('PRAGMA cache_size').fetchone()[0]), 2048)
            plan = inventory._db.execute('EXPLAIN QUERY PLAN '+inventory._ordered_sql).fetchall()
            self.assertFalse(any('TEMP B-TREE' in row[-1] for row in plan))
            groups = list(inventory.groups())
            self.assertEqual([len(group) for group in groups], [240, 240, 1])
            self.assertCountEqual([pair for group in groups for pair in inventory.materialize(group)], originals)
            self.assertTrue(all(not p.stat().st_mode & 0o077 for p in spool.parent.iterdir()))
        self.assertFalse(spool.parent.exists())

    def test_utc_ordering_retains_original_offset_receipt_bytes_and_legacy_inner_order(self):
        late = capture(self.folder, 1, captured_at='2030-04-01T12:00:00+01:00')
        early = capture(self.folder, 2, captured_at='2030-04-01T11:30:00+02:00')
        with self.inventory() as inventory:
            groups = list(inventory.groups(count_limit=1))
            self.assertEqual([inventory.materialize(g)[0] for g in groups], [early, late])
            legacy = inventory.materialize(next(inventory.groups()))
            self.assertEqual(legacy, sorted([late, early], key=lambda pair:V._sha(V._wire(V._json(pair[1])))))

    def test_byte_bound_splits_without_changing_the_vault_primitive_bound(self):
        pairs = [capture(self.folder, n) for n in range(3)]
        size = max(sum(map(len, pair)) for pair in pairs)
        with self.inventory() as inventory:
            self.assertEqual([len(g) for g in inventory.groups(byte_limit=2*size)], [2, 1])
            with self.assertRaises(ValueError):list(inventory.groups(byte_limit=1))
            with self.assertRaises(ValueError):list(inventory.groups(count_limit=241))

    def test_cross_boundary_duplicate_instant_with_another_offset_is_rejected(self):
        for n in range(240):capture(self.folder, n)
        capture(self.folder, 240, captured_at=(NOW-timedelta(hours=1)).astimezone(
            timezone(timedelta(hours=9))).isoformat())
        with self.assertRaisesRegex(ValueError, 'CAPTURE_DUPLICATE'):
            with self.inventory():pass

    def test_late_bad_url_hash_clock_or_canonical_filename_prevents_inventory(self):
        for change in ({'source_url':'https://example.invalid/private'}, {'http_status':True},
                       {'captured_at':(NOW+timedelta(seconds=1)).isoformat()}):
            with self.subTest(change=tuple(change)):
                capture(self.folder, 1, **change)
                with self.assertRaises(ValueError):
                    with self.inventory():pass
                for p in self.folder.iterdir():p.unlink()
        raw, metadata = capture(self.folder, 1)
        body = self.folder/(sha256(raw).hexdigest()+'.html'); body.write_bytes(raw+b'tampered')
        with self.assertRaises(ValueError):
            with self.inventory():pass
        body.write_bytes(raw)
        receipt = next(self.folder.glob('*.json')); receipt.rename(receipt.with_name('0'*64+'.json'))
        with self.assertRaises(ValueError):
            with self.inventory():pass

    def test_symlinks_hardlinks_public_modes_and_nonowner_fail_closed(self):
        raw, _ = capture(self.folder, 1)
        body = self.folder/(sha256(raw).hexdigest()+'.html')
        for defect in ('symlink','hardlink','mode','owner'):
            with self.subTest(defect=defect):
                original = body.read_bytes()
                if defect in ('symlink','hardlink'):
                    retained = self.root/'retained'; retained.write_bytes(original); retained.chmod(0o600)
                    body.unlink()
                    (body.symlink_to if defect=='symlink' else lambda target:os.link(target, body))(retained)
                elif defect=='mode':body.chmod(0o644)
                else:
                    with patch('os.geteuid', return_value=os.geteuid()+1), self.assertRaises(ValueError):
                        with self.inventory():pass
                    continue
                with self.assertRaises(ValueError):
                    with self.inventory():pass
                body.unlink(); body.write_bytes(original); body.chmod(0o600)
                if (self.root/'retained').exists():(self.root/'retained').unlink()

    def test_mutation_after_global_preflight_or_replacement_stat_is_refused(self):
        raw, _ = capture(self.folder, 1)
        body = self.folder/(sha256(raw).hexdigest()+'.html')
        with self.inventory() as inventory:
            group = next(inventory.groups())
            original_stat = body.stat(); body.write_bytes(raw[::-1])
            os.utime(body, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            with self.assertRaises(ValueError):inventory.materialize(group)
        body.write_bytes(raw)
        with self.inventory() as inventory:
            group = next(inventory.groups())
            copy = self.root/'copy'; copy.write_bytes(raw); copy.chmod(0o600); copy.replace(body)
            with self.assertRaises(ValueError):inventory.materialize(group)

    def test_added_receipt_after_preflight_and_repository_root_are_refused(self):
        capture(self.folder, 1)
        with self.inventory() as inventory:
            group = next(inventory.groups()); capture(self.folder, 2)
            with self.assertRaises(ValueError):inventory.materialize(group)
        with self.assertRaises(ValueError):
            with CaptureInventory(self.folder, repo=self.root, now=NOW):pass

    def test_canonical_github_query_identity_and_metadata_whitespace_remain_exact(self):
        first = capture(self.folder,1,source_url='https://api.github.com/repos/haji84/RACE-AI/actions/runs/3/artifacts?page=1&per_page=100')
        path = next(self.folder.glob('*.json')); path.write_bytes(b'  '+first[1]+b'\n')
        with self.inventory() as inventory:
            restored = inventory.materialize(next(inventory.groups()))
            self.assertEqual(restored[0][1], b'  '+first[1]+b'\n')
        capture(self.folder,2,source_url='https://api.github.com/repos/haji84/RACE-AI/actions/runs/3/artifacts?per_page=100&page=1',
                captured_at=V._json(first[1])['captured_at'])
        with self.assertRaisesRegex(ValueError,'CAPTURE_DUPLICATE'):
            with self.inventory():pass

    def test_legacy_loader_preserves_small_return_and_stream_handles_241(self):
        from race_ai import saved_view_feed as F
        pairs = [capture(self.folder, n) for n in range(241)]
        with F.capture_inventory(self.folder, repo=self.repo, now=NOW) as inventory:
            actual = list(inventory.iter_captures())
        self.assertEqual(actual, [(raw,V._json(meta)) for raw,meta in sorted(pairs,
            key=lambda pair:V._sha(V._wire(V._json(pair[1]))))])
        self.assertEqual(F.load_captures(self.root/'missing'), [])


if __name__ == '__main__':
    unittest.main()
