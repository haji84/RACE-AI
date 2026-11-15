"""Offline bounds and authentication for legacy nested continuity checkpoints."""
import copy
import hashlib
import io
import json
import struct
import unittest
import zipfile

from race_ai import cycle_recovery as recovery
from race_ai.frozen_day_cycle import archive_json


class ContinuityArchiveSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_id = 42047977632
        state = dict(schema='RACE_AI_CONTINUOUS_REPEAT_V2', day_jst='2026-11-06',
                     run_id=cls.run_id, requests_used=196, completed_round=4,
                     prepared_round=None, source_wait=None, halted_reason='WORKER_HANDOFF',
                     lifetime_requests_base=616, lifetime_requests=812,
                     lifetime_completed_rounds_base=43, lifetime_completed_rounds=47)
        state['session_sha256'] = hashlib.sha256(json.dumps(
            state, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
            allow_nan=False).encode()).hexdigest()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr('repeat-session.json', json.dumps(state))
            archive.writestr('legacy/nested-checkpoint.zip', b'x' * (33 * 1024 * 1024))
        cls.raw = stream.getvalue()
        cls.meta = dict(id=13427340610, name=f'race-cycle-continuity-{cls.run_id}',
                        expired=False, created_at='2026-11-05T15:00:28Z',
                        digest='sha256:' + hashlib.sha256(cls.raw).hexdigest(),
                        workflow_run=dict(id=cls.run_id, head_repository_id=1416489937))

    def test_authenticated_legacy_checkpoint_above_32_mib_preserves_counters(self):
        self.assertGreater(len(self.raw), 32 * 1024 * 1024)
        control = recovery.authenticated_source_control(
            self.raw, self.meta, expected_run=self.run_id)
        self.assertEqual(control['previous_run_id'], self.run_id)
        self.assertEqual(control['previous_session_requests'], 196)
        self.assertEqual(control['completed_round'], 4)
        self.assertEqual(control['lifetime_requests'], 812)
        self.assertEqual(control['lifetime_completed_rounds'], 47)
        self.assertIsNone(control['prepared_round'])
        self.assertIsNone(control['source_wait'])
        self.assertEqual(control['previous_stop_reason'], 'WORKER_HANDOFF')
        self.assertEqual(control['receipt']['digest'], self.meta['digest'])

    def test_larger_checkpoint_still_requires_digest_repository_and_run(self):
        bad_digest = copy.deepcopy(self.meta)
        bad_digest['digest'] = 'sha256:' + '0' * 64
        bad_repository = copy.deepcopy(self.meta)
        bad_repository['workflow_run']['head_repository_id'] += 1
        for meta, run, reason in (
                (bad_digest, self.run_id, 'continuity archive hash mismatch'),
                (bad_repository, self.run_id, 'foreign/expired continuity archive'),
                (self.meta, self.run_id + 1, 'continuity run identity mismatch')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                recovery.authenticated_source_control(self.raw, meta, expected_run=run)

    def test_larger_checkpoint_with_matching_digest_still_requires_member_crc(self):
        with zipfile.ZipFile(io.BytesIO(self.raw)) as archive:
            info = archive.getinfo('legacy/nested-checkpoint.zip')
        changed = bytearray(self.raw)
        name_size, extra_size = struct.unpack_from('<HH', changed, info.header_offset + 26)
        changed[info.header_offset + 30 + name_size + extra_size] ^= 1
        raw = bytes(changed)
        meta = dict(self.meta, digest='sha256:' + hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError, 'continuity member CRC mismatch'):
            recovery.authenticated_source_control(raw, meta, expected_run=self.run_id)

    def test_expanded_members_above_512_mib_remain_rejected(self):
        changed = bytearray(self.raw)
        # Forge only the central-directory size: the guard must run before reads.
        central = changed.index(b'PK\x01\x02')
        struct.pack_into('<I', changed, central + 24, 512 * 1024 * 1024 + 1)
        raw = bytes(changed)
        meta = dict(self.meta, digest='sha256:' + hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError, 'oversized continuity members'):
            recovery.authenticated_source_control(raw, meta, expected_run=self.run_id)

    def test_continuity_intake_remains_bounded_at_128_mib(self):
        self.assertEqual(recovery.CONTINUITY_ARCHIVE_MAX_BYTES, 128 * 1024 * 1024)

        class OversizedBytes(bytes):
            def __len__(self):
                return 128 * 1024 * 1024 + 1

        # Exercise the early byte-length guard without allocating a 128 MiB ZIP.
        with self.assertRaisesRegex(ValueError, 'bounded cycle archive'):
            recovery.authenticated_source_control(
                OversizedBytes(b'not loaded'), self.meta, expected_run=self.run_id)

    def test_forecast_and_result_archive_limits_remain_32_mib(self):
        with self.assertRaisesRegex(ValueError, 'bounded archive required'):
            archive_json(self.raw, self.meta, 'forecasts.json', f'boat-p0-existing-{self.run_id}')
        with self.assertRaisesRegex(ValueError, 'bounded result archive'):
            recovery.result_archive(self.raw, self.meta, '2026-11-06')
        with self.assertRaisesRegex(ValueError, 'cycle archive identity'):
            recovery._result_day(self.raw, self.meta)
