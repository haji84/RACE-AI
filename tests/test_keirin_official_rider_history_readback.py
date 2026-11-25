"""Invented source projections verify private output and aggregate-only failures."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class OfficialRiderReadbackTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = import_module('scripts.keirin_official_rider_history_readback')
        except ModuleNotFoundError:
            self.fail('The protected official-to-dossier readback is missing.')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.folder.chmod(0o700)
        self.receipt = dict(schema='KEIRIN_OFFICIAL_RIDER_HISTORY_SOURCE_V1',
            source_day='2026-11-25', target_day='2026-11-26', archive_commit='a'*40,
            knowledge_as_of='2026-11-25T15:00:00Z',
            index_sha256='b'*64, expected_originals=2, expected_result_races=1)
        self.store = SimpleNamespace(index_commit='a'*40, head='a'*40)
        self.projection = SimpleNamespace(receipt=dict(admitted_races=1, held_races=0,
            originals_by_as_of=2, no_result_by_as_of=1, numeric_finishes=1),
            private_races={'202611252601':dict(finishes=[dict(registration_id='012345',
                car=1, status='FINISHED', place=1)], revisions=[dict(source_sha256='c'*64)])},
            finish_history=lambda registration: dict(registration=registration,
                periods={'all':dict(observed_count=1)}))

    def run_readback(self, **changes):
        options = dict(store=self.store, receipt=self.receipt, owner_private_pem=b'PRIVATE_KEY_CANARY',
            output_dir=self.folder/'private', clock=lambda:datetime(2026,11,25,16,tzinfo=timezone.utc))
        options.update(changes)
        with patch.object(self.module, 'project_day_for_dossier', return_value=self.projection):
            return self.module.restore(**options)

    def test_actual_histories_remain_private_with_aggregate_receipt(self):
        report = self.run_readback()
        self.assertEqual(report['numeric_histories_restored'], 1)
        self.assertIs(report['private_projection_written'], True)
        self.assertNotIn('012345', json.dumps(report))
        self.assertNotIn('PRIVATE_KEY_CANARY', json.dumps(report))
        path = self.folder/'private'/'official-rider-histories.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        saved = json.loads(path.read_bytes())
        self.assertEqual(saved['histories'][0]['registration'], '012345')
        self.assertEqual(report['private_projection_sha256'], sha256(path.read_bytes()).hexdigest())
        self.assertIs(report['forecast_original_authenticated'], False)

    def test_partial_empty_or_moving_result_projection_is_held(self):
        for field, value in [('admitted_races',0), ('held_races',1), ('originals_by_as_of',3),
                              ('no_result_by_as_of',0), ('numeric_finishes',0)]:
            before = deepcopy(self.projection.receipt)
            self.projection.receipt[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_COUNTS'):
                self.run_readback()
            self.projection.receipt = before
        self.store.head = 'd'*40
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_PIN'):
            self.run_readback()

    def test_original_private_projection_is_never_overwritten(self):
        self.run_readback()
        with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_OUTPUT_EXISTS'):
            self.run_readback()

    def test_unknown_or_extra_receipt_fields_are_rejected(self):
        for bad in [dict(self.receipt, expected_result_races=True),
                    dict(self.receipt, archive_commit='main'), dict(self.receipt, future=True),
                    dict(self.receipt, target_day='2026-11-25')]:
            with self.subTest(bad=list(bad)), self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_RECEIPT'):
                self.run_readback(receipt=bad)

    def test_later_replay_keeps_the_pinned_knowledge_clock(self):
        with patch.object(self.module, 'project_day_for_dossier', return_value=self.projection) as project:
            self.module.restore(store=self.store, receipt=self.receipt, owner_private_pem=b'synthetic',
                output_dir=self.folder/'late', clock=lambda:datetime(2026,11,27,tzinfo=timezone.utc))
        self.assertEqual(project.call_args.kwargs['knowledge_as_of'], self.receipt['knowledge_as_of'])

    def test_cli_pops_key_and_emits_no_private_exception(self):
        stream = StringIO()
        with patch.dict(os.environ, {self.module.KEY_ENV:'PRIVATE_KEY_CANARY'}), redirect_stdout(stream):
            code = self.module.main(['--unexpected=PRIVATE_ARGUMENT_CANARY'])
            self.assertNotIn(self.module.KEY_ENV, os.environ)
        self.assertEqual(code, 2)
        self.assertNotIn('CANARY', stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())['state'], 'OFFICIAL_HISTORY_ARGUMENTS_INVALID')

    def test_committed_receipt_is_accepted_by_the_exact_cli_parser(self):
        root = Path(__file__).resolve().parents[1]
        raw = (root/'docs/evidence/keirin-live-accuracy-closure-20261125/official-rider-history-source.json').read_bytes()
        receipt = self.module.checked_receipt(self.module.records.history._json(raw))
        self.assertEqual(receipt['expected_originals'], 4)
        self.assertEqual(receipt['expected_result_races'], 2)

    def test_prekey_pin_and_counts_are_checked_from_actual_index_bytes(self):
        raw = b'{"synthetic":"index"}\n'
        receipt = dict(self.receipt, index_sha256=sha256(raw).hexdigest())
        store = SimpleNamespace(head='a'*40, index_commit='a'*40, day='2026-11-25', path='index',
            index=dict(originals={'one':{},'two':{}}, results={'one':[{}]}), repo=self.folder)
        with patch.object(self.module.records, 'RecordStore', return_value=store), \
                patch.object(self.module.archive, 'read_blob_bytes', return_value=raw):
            self.assertIs(self.module.prepare_store(self.folder, receipt), store)
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_PIN'):
                self.module.prepare_store(self.folder, dict(receipt, index_sha256='f'*64))

    def test_prekey_ciphertext_substitution_stops_before_any_decryption(self):
        raw = b'ciphertext'
        meta = dict(cipher_sha256=sha256(raw).hexdigest(), evidence_sha256='e'*64,
                    observed_at='2026-11-25T10:00:00Z')
        store = SimpleNamespace(repo=self.folder, head='a'*40, day='2026-11-25',
            index=dict(registry=None, originals={'race':meta}, results={}))
        envelope = dict(day_jst=store.day, evidence_plaintext_sha256=meta['evidence_sha256'],
                        observed_at=meta['observed_at'])
        with patch.object(self.module.archive, 'read_blob_bytes', return_value=raw), \
                patch.object(self.module.records.history, '_checked_cipher', return_value=envelope):
            self.assertEqual(self.module.verify_envelopes(store), 1)
            envelope['observed_at'] = '2026-11-25T11:00:00Z'
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_CIPHER'):
                self.module.verify_envelopes(store)
        with patch.object(self.module.archive, 'read_blob_bytes', return_value=b'changed'):
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_HISTORY_CIPHER'):
                self.module.verify_envelopes(store)
