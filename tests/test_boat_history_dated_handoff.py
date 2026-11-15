"""Synthetic dated inventories: owner AES, immutable handoff and grid extension."""
import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

from tests.test_boat_history_catalog import index
from tests.test_boat_venue_history import archive
from tests.test_boat_venue_history_handoff import HandoffTests, MemoryGit


class DatedHandoffTests(HandoffTests):
    def collection(self, raw=None, day='2026-11-04'):
        from scripts import boat_venue_history as cli
        root = self.root / 'source'
        root.mkdir(mode=0o700)
        menu = b'<script>var dir="/od2/K/";</script><option value="202611">x</option>'
        with patch.object(cli, '_now', return_value='2026-11-05T00:00:02Z'), patch.object(cli, '_http', side_effect=[
            (menu, '2026-11-04T10:00:00Z'), (index(days=(day[-2:],)), '2026-11-04T10:00:00Z'),
            (archive(day=day) if raw is None else raw, '2026-11-05T00:00:01Z')]):
            report = cli.capture_month(root / '202611/attempt-000001', month='202611', not_after=day)
        cli._store_progress(root, dict(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V1', months=['202611'],
            menu_sha256=hashlib.sha256(menu).hexdigest(), captured_at='2026-11-04T10:00:00Z', not_after=day,
            heads={'202611': dict(kind='ENCRYPTED', folder='202611/attempt-000001',
                ciphertext_sha256=report['ciphertext_sha256'], attempt=1, generation=1,
                month_complete=report['catalog']['month_complete'])}))
        return root

    def test_v2_structure_is_recognized_without_granting_missing_inventory(self):
        from race_ai.boat_venue_history_handoff import _signed, publish_collection
        from scripts.boat_venue_history import _manifest_mac, _scope
        source = self.collection()
        parent = (source / 'collection.json').read_bytes()
        record = json.loads(parent)
        record['state'].update(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V2', inventory_captured_at='2026-11-05T10:00:00Z', inventory_lineage=[dict(
            folder='dated-inventory/' + 'b' * 64, parent_manifest_sha256=hashlib.sha256(parent).hexdigest(),
            inventory_captured_at='2026-11-05T10:00:00Z', not_after='2026-11-04',
            month_indices={'202611': dict(sha256='c' * 64, captured_at='2026-11-05T10:00:00Z')},
            ciphertext_sha256='d' * 64, sqlite_sha256='e' * 64, scope=_scope())])
        record['mac'] = _manifest_mac(record['state'])
        raw = json.dumps(record).encode()
        self.assertEqual(_signed(raw)['state'], record['state'])
        (source / 'collection.json').write_bytes(raw)
        with self.assertRaises((ValueError, OSError)):
            publish_collection(source, self.root, transport=MemoryGit())

    def extended(self, source, name='dated', new_day_at=None):
        from scripts import boat_venue_history as cli
        from race_ai.boat_history_dated_inventory import extend_collection
        calls = []

        def fetch(url):
            calls.append(url)
            at = '2026-11-05T10:00:00Z'
            if url == cli.MENU:
                return b'<script>var dir="/od2/K/";</script><option value="202611">x</option>', at
            if url.endswith('/202611/mday.html'):
                return index(days=('04', '05')), at
            if url.endswith('/k261105.lzh'):
                return archive(day='2026-11-05'), new_day_at or at
            raise AssertionError('old or unlisted source requested')

        output = self.root / name
        with patch.object(cli, '_http', side_effect=fetch), patch.object(cli, '_now', return_value='2026-11-05T10:00:01Z'):
            extend_collection(source, output, not_after='2026-11-05', max_files=31)
        self.assertEqual(sum(url.endswith('.lzh') for url in calls), 1)
        return output

    def test_new_archive_clock_is_bound_to_actual_listing_and_collection_clocks(self):
        source = self.collection()
        for name, captured in [('before-listing', '2026-11-04T23:00:00Z'), ('future-capture', '2050-01-01T00:00:00Z')]:
            with self.subTest(captured=captured), self.assertRaises(ValueError):
                self.extended(source, name=name, new_day_at=captured)

    def test_dated_parent_and_original_bytes_survive_publish_readback_and_extended_grid(self):
        from race_ai.boat_venue_history_handoff import publish_collection, readback_collection
        from race_ai.boat_venue_dataset import build_dataset, verify_dataset
        from scripts.boat_venue_history import restore_month
        source = self.collection()
        original = (source / 'collection.json').read_bytes()
        old = json.loads(original)['state']['heads']['202611']
        old_cipher = (source / old['folder'] / 'history.checkpoint').read_bytes()
        git = MemoryGit()
        first = publish_collection(source, self.root, transport=git)
        dated = self.extended(source)
        second = publish_collection(dated, self.root, transport=git)
        self.assertNotEqual(first['manifest_sha256'], second['manifest_sha256'])
        restored = self.root / 'restored-dated'
        report = readback_collection(second, restored, self.root, transport=git)
        self.assertEqual(report['parsed_days'], 2)
        self.assertEqual((source / 'collection.json').read_bytes(), original)
        self.assertEqual((restored / old['folder'] / 'history.checkpoint').read_bytes(), old_cipher)
        state = json.loads((restored / 'collection.json').read_bytes())['state']
        catalog, _ = restore_month(restored / state['heads']['202611']['folder'], expected_month='202611')
        self.assertEqual([row[0] for row in catalog._heads()], ['2026-11-04', '2026-11-05'])
        self.assertEqual(catalog._heads()[0][2], '2026-11-05T00:00:01Z')
        catalog.db.close()
        with patch('race_ai.boat_venue_dataset._now', return_value='2026-11-06T10:00:00Z'):
            build_dataset(restored, self.root / 'dated-grid', roster=['4999'], end='2026-11-05')
        self.assertEqual(verify_dataset(self.root / 'dated-grid')['verified_cells'], 7 * 24)
        self.assertEqual(git.trees[git.current]['unrelated.enc'], b'preserve')

    def test_dated_cipher_mutation_is_rejected_before_publish_or_grid(self):
        from race_ai.boat_history_dated_inventory import inventory_files
        from race_ai.boat_venue_history_handoff import publish_collection
        from race_ai.boat_venue_dataset import build_dataset
        dated = self.extended(self.collection())
        state = json.loads((dated / 'collection.json').read_bytes())['state']
        cipher_path = next(path for path, _ in inventory_files(state) if path.endswith('inventory.checkpoint'))
        path = dated / cipher_path
        path.write_bytes(path.read_bytes() + b'tampered')
        git = MemoryGit()
        with self.assertRaises(ValueError):
            publish_collection(dated, self.root, transport=git)
        self.assertEqual(len(git.trees), 1)
        with self.assertRaises(ValueError):
            build_dataset(dated, self.root / 'bad-grid', end='2026-11-05')

    def test_dated_child_cannot_overwrite_independently_advanced_parent(self):
        from race_ai.boat_venue_history_handoff import publish_collection
        from scripts import boat_venue_history as cli
        source = self.collection()
        git = MemoryGit()
        publish_collection(source, self.root, transport=git)
        dated = self.extended(source)
        sibling = self.root / 'sibling'
        shutil.copytree(source, sibling)
        record = json.loads((sibling / 'collection.json').read_bytes())
        old = record['state']['heads']['202611']
        relative = '202611/attempt-000002'
        with patch.object(cli, '_http', side_effect=AssertionError('no source GET')):
            report = cli.capture_month(sibling / relative, month='202611', resume=sibling / old['folder'], reparse_only=True)
        record['state']['heads']['202611'] = dict(old, folder=relative, generation=2, attempt=2,
            ciphertext_sha256=report['ciphertext_sha256'])
        cli._store_progress(sibling, record['state'])
        publish_collection(sibling, self.root, transport=git)
        current = git.current
        with self.assertRaises(ValueError):
            publish_collection(dated, self.root, transport=git)
        self.assertEqual(git.current, current)

    def test_v2_claim_without_authenticated_inventory_cannot_extend_dataset(self):
        from race_ai.boat_venue_history_handoff import publish_collection
        from scripts.boat_venue_history import _manifest_mac
        source = self.collection()
        record = json.loads((source / 'collection.json').read_bytes())
        record['state'].update(schema='RACE_AI_ALL_PUBLISHED_HISTORY_PROGRESS_V2', not_after='2026-11-05', inventory_lineage=[])
        record['mac'] = _manifest_mac(record['state'])
        (source / 'collection.json').write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            publish_collection(source, self.root, transport=MemoryGit())
