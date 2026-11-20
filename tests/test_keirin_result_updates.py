"""Result-only display packets use real parsers with invented public documents."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from hashlib import sha256

from race_ai import keirin_official_public_source as official
from race_ai import keirin_note_feed as feed
from tests.test_keirin_official_public_source import fixtures, transport, DAY, RACE, NOW


class ResultUpdatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        from race_ai import keirin_nationwide_auto_storage as storage
        active = patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin)
        active.start(); self.addCleanup(active.stop)

    def api(self):
        return importlib.import_module('race_ai.keirin_result_updates')

    def record(self):
        get = transport(fixtures())
        schedule = official.fetch_day_schedule(DAY, fetcher=get, clock=lambda: NOW)
        return official.fetch_race_result(RACE, schedule=schedule, fetcher=get, clock=lambda: NOW)

    def updates(self):
        return self.api().from_official_records({RACE: self.record()}, {})

    def test_official_order_requires_source_reparse_and_never_invents_arm_scores(self):
        doc = self.updates()
        row = doc['races'][0]
        self.assertEqual(row['authority'], 'official')
        self.assertEqual(row['winning_triples'], ['1-2-3'])
        self.assertEqual(row['payouts_100yen'], {'1-2-3': 1230})
        self.assertEqual(row['order_status'], 'confirmed')
        self.assertEqual(row['payout_status'], 'confirmed')
        self.assertEqual(row['arms']['A']['state'], 'unverifiable')
        self.assertEqual(row['arms']['C']['state'], 'pending')
        self.assertNotIn('ranked_tickets', json.dumps(doc))

    def test_a_claimed_official_flag_or_changed_normalized_result_cannot_pass(self):
        forged = self.record()
        forged['result']['winning_triples'] = [[3, 2, 1]]
        forged['official_primary_result_authenticated'] = True
        with self.assertRaises(ValueError):
            self.api().from_official_records({RACE: forged}, {})

    def test_secondary_consensus_cannot_receive_official_money_or_hit_status(self):
        doc = self.updates()
        doc['races'][0]['authority'] = 'secondary'
        with self.assertRaises(ValueError): self.api().checked_updates(doc)
        row = doc['races'][0]
        row['payout_status'] = 'held'; row['payouts_100yen'] = {}
        row['arms']['A']['state'] = 'hit'
        with self.assertRaises(ValueError): self.api().checked_updates(doc)

    def test_order_only_has_no_money_and_cannot_hide_a_or_b(self):
        doc = self.updates(); row = doc['races'][0]
        row['payout_status'] = 'pending'; row['payouts_100yen'] = {}
        row['arms']['A'] = dict(state='hit', points=4, stake_yen=None, return_yen=None)
        row['arms']['B'] = dict(state='miss', points=6, stake_yen=None, return_yen=None)
        self.api().checked_updates(doc)
        self.assertEqual(row['arms']['C']['state'], 'pending')
        row['arms']['A']['return_yen'] = 1230
        with self.assertRaises(ValueError): self.api().checked_updates(doc)

    def test_public_score_receipt_must_bind_result_revision_and_source(self):
        doc = self.updates(); record = self.record()
        report = {'result_receipts': [{
            'race_id': RACE, 'state': 'AB_SETTLED_FROM_INDEPENDENT_RECEIPTS',
            'source_sha256': '0' * 64, 'result_revision_sha256': '0' * 64,
            'A_existing': dict(hit_at_all=True, stake_yen=400, payout_yen=1230),
            'B_six_phase': dict(hit_at_all=False, stake_yen=600, payout_yen=0)}]}
        out = self.api().from_official_records({RACE: record}, report)
        self.assertEqual(out['races'][0]['arms']['A']['state'], 'unverifiable')

    def test_diagnostics_reject_query_cookie_key_or_arbitrary_error_text(self):
        doc = self.updates()
        doc['races'][0]['diagnostics'] = [{'url': 'https://keirin.jp/sp/race?encp=secret'}]
        with self.assertRaises(ValueError): self.api().checked_updates(doc)

    def test_result_packet_contains_only_result_updates_and_no_provider_urls(self):
        note = self.api().note_packet(self.updates(), source_commit='a' * 40)
        self.assertEqual(list(note['files']), ['data/' + DAY + '/result_updates.json'])
        self.assertFalse(note['formal_model_admission'])
        self.assertFalse(note['production_weight_switch'])
        self.assertNotIn('source_url', json.dumps(note))

    def test_encrypted_publication_is_idempotent_and_preserves_input_stop(self):
        from tests.test_keirin_saved_source_comparison import archive_record
        retained = patch('race_ai.keirin_saved_source_comparison.read_retained_records',
                         return_value={RACE: [archive_record()]})
        reader = retained.start(); self.addCleanup(retained.stop)
        with TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o700)
            repo, remote = root/'repo', root/'remote.git'
            def git(*args, cwd=None):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL)
            git('init', '--bare', str(remote)); git('init', str(repo))
            git('remote', 'add', 'origin', str(remote), cwd=repo)
            class LocalStore(feed.NoteFeedGit):
                def _remote(self): return 'origin'
            store = LocalStore(repo)
            recipient = feed.create_recipient(root/'owner')['public']
            seed = dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1',dates=[DAY],files={},
                formal_model_admission=False,production_weight_switch=False,
                imported_at=NOW.isoformat(),source_commit='a'*40)
            first = feed.publish_snapshot(store, recipient,
                feed.seal_snapshot(seed, recipient, kind='import'), expected_parent=None, denied=True)
            old = store.read(first['source_commit'], 'index.json')
            updates = self.updates()
            with patch.object(feed, 'seal_snapshot', wraps=feed.seal_snapshot) as sealing:
                result = self.api().publish_updates(repo, updates, source_commit='a'*40,
                    owner_private_pem=self.private, clock=lambda: NOW, store=store, recipient=recipient)
            reader.assert_called_once_with(repo, [RACE])
            note = sealing.call_args.args[0]
            displayed = json.loads(next(iter(note['files'].values()))['text'])['races'][0]
            self.assertEqual(displayed['source_comparison'], [
                dict(source_id='official_json',state='matched'),
                dict(source_id='kdreams',state='matched'),
                dict(source_id='netkeirin',state='matched')])
            self.assertEqual(displayed['arms'], updates['races'][0]['arms'])
            self.assertEqual(displayed['authority'], 'official')
            self.assertEqual(len(updates['races'][0]['source_comparison']), 1)
            head = store.head()
            index = feed.load_index(store, recipient, head)
            self.assertTrue(index['provider_denied'])
            self.assertEqual(index['entries'][0], json.loads(old)['entries'][0])
            self.assertEqual(index['entries'][-1]['kind'], 'result')
            self.assertNotEqual(index['entries'][-1]['result_revisions'][RACE], updates['races'][0]['revision'])
            self.assertNotIn(updates['races'][0]['revision'], json.dumps(index))
            self.assertEqual(index['covered_race_ids'], [])
            self.assertEqual(result['published_races'], 1)
            self.assertNotIn(b'winning_triples', store.read(head, 'views/'+index['entries'][-1]['cipher_sha256']+'.json'))
            again = self.api().publish_updates(repo, updates, source_commit='a'*40,
                owner_private_pem=self.private, clock=lambda: NOW, store=store, recipient=recipient)
            self.assertEqual(store.head(), head)
            self.assertEqual(again['state'], 'EXISTING_RESULT_DISPLAY_REUSED')
            later = deepcopy(updates)
            later['observed_at'] = '2026-10-02T09:00:00+00:00'
            later['races'][0]['observed_at'] = later['observed_at']
            repeated = self.api().publish_updates(repo, later, source_commit='b'*40,
                owner_private_pem=self.private, clock=lambda: NOW, store=store, recipient=recipient)
            self.assertEqual(repeated['state'], 'EXISTING_RESULT_DISPLAY_REUSED')
            self.assertEqual(store.head(), head)
            reformatted = self.api().publish_updates(repo, later, source_commit='b'*40,
                owner_private_pem=self.private.replace(b'\n', b'\r\n'),
                clock=lambda: NOW, store=store, recipient=recipient)
            self.assertEqual(reformatted['state'], 'EXISTING_RESULT_DISPLAY_REUSED')
            self.assertEqual(store.head(), head)

    def test_secondary_comparison_distinguishes_one_matching_and_one_different_source(self):
        row = self.updates()['races'][0]
        observations = [dict(race_id=RACE, provider=name, winning_triple=triple,
            payout_per_100yen=amount, official_organizer_result=False,
            source_bytes_sha256='b'*64, observed_at=NOW.isoformat(), source_url='unused')
            for name,triple,amount in [('Kdreams',[1,2,3],1230),('netkeirin',[3,2,1],3000)]]
        compared = self.api().compare_saved_sources(row, observations)
        self.assertEqual(compared, [dict(source_id='kdreams',state='matched'),
                                    dict(source_id='netkeirin',state='different')])


if __name__ == '__main__': unittest.main()
