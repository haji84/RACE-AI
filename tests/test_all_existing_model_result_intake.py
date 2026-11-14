"""Invented journals, real AES envelopes and actual receipt checks; no provider."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import base64
import io
import json
import os
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from race_ai import all_existing_model_result_intake as intake
from race_ai.boat_private_original_archive import seal_original_zip
from tests.test_frozen_day_cycle import observation


KEY = bytes(range(32))  # Public key exclusively for invented test records.
HEAD = 'a'*40
NOW = datetime(2030, 4, 1, 2, 30, tzinfo=timezone.utc)
SAVED = '2030-04-01T02:11:00Z'


def packed(members):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in members:
            archive.writestr(name, body)
    return raw.getvalue()


def settled():
    row = dict(race_id='20300401-01-01', cutoff_at='2030-04-01T11:00:00+09:00',
        top8=[[1, 2, 3]], roster={str(n):str(4000+n) for n in range(1, 7)})
    value = observation(row)
    value.update(kind='raceresult', information_phase='official_result',
        available_at=value['captured_at'], upstream_published_at=None)
    return value


def fixture(observations=None, *, mutate_report=None, journal_bytes=None, extra=(), kind='RESULT'):
    observations = [settled()] if observations is None else deepcopy(observations)
    report = dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1', day_jst='2030-04-01',
        run_id='99', code_sha=HEAD, updated_at='2030-04-01T02:10:30Z',
        result_observation_versions=len(observations), actual_purchases=False,
        schedule=[dict(race_id='20300401-01-01', cutoff_at='2030-04-01T11:00:00+09:00')])
    if mutate_report is not None:
        mutate_report(report)
    report['report_sha256'] = digest(report)
    members = [('official-result-observations.json', json.dumps(observations) if journal_bytes is None else journal_bytes),
               ('status.json', json.dumps(report)), *extra]
    plain = packed(members)
    cipher = seal_original_zip(plain, run_id=99, head_sha=HEAD, kind=kind, key=KEY)
    raw = packed([('private-original.enc', cipher)])
    meta = dict(id=701, name='race-existing-cycle-99-cycle-02', expired=False,
        created_at=SAVED, expires_at='2030-04-08T02:11:00Z', size_in_bytes=len(raw),
        digest='sha256:'+sha256(raw).hexdigest(),
        workflow_run=dict(id=99, head_sha=HEAD, repository_id=1416489937, head_repository_id=1416489937))
    return raw, meta, plain, report


class AllExistingModelResultIntakeTests(unittest.TestCase):
    def setUp(self):
        setting = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        setting.start(); self.addCleanup(setting.stop)

    def admit(self, raw=None, metadata=None, **options):
        if raw is None:
            raw, metadata, _, _ = fixture(**options)
        return intake.observations_from_result_artifact(raw, metadata, now=NOW,
            expected_run_id=99, expected_head_sha=HEAD)

    def test_actual_encrypted_wrapper_binds_original_journal_report_and_receipt(self):
        raw, metadata, plain, report = fixture(extra=[('other-private-event.txt', b'invented private source')])
        before = deepcopy(metadata)
        result = self.admit(raw, metadata)
        self.assertEqual(result['observations'], [settled()])
        self.assertIsNone(result['observations'][0]['upstream_published_at'])
        self.assertNotIn('published_at', result['observations'][0])
        self.assertEqual(result['summary']['ordinary_settled_result_count'], 1)
        self.assertEqual(result['receipt']['artifact_metadata'], metadata)
        self.assertEqual(result['receipt']['report_sha256'], report['report_sha256'])
        self.assertEqual(result['receipt']['original_journal_sha256'], digest([settled()]))
        self.assertEqual(result['receipt']['journal_index'][0]['observation_sha256'], digest(settled()))
        with zipfile.ZipFile(io.BytesIO(plain)) as archive:
            self.assertEqual(result['receipt']['original_journal_body_sha256'],
                sha256(archive.read('official-result-observations.json')).hexdigest())
        self.assertEqual(metadata, before)
        for private in ('source_url', 'roster', 'ordered_top3', 'top3', 'captured_at', 'journal_index'):
            self.assertNotIn(private, json.dumps(result['summary']))
        self.assertFalse(result['summary']['plaintext_published'])
        result['observations'][0]['data']['results'][0]['racer_registration_id'] = '9999'
        self.assertEqual(self.admit(raw, metadata)['observations'], [settled()])

    def test_all_revisions_are_verified_and_newest_pending_does_not_fall_back_to_win(self):
        old = settled(); pending = deepcopy(old)
        pending.update(status='PENDING', captured_at='2030-04-01T02:10:20Z', data=None)
        result = self.admit(observations=[pending, old, deepcopy(old)])
        self.assertEqual(result['observations'], [pending])
        self.assertEqual(result['summary']['original_observation_count'], 3)
        self.assertEqual(result['summary']['unique_revision_count'], 2)
        self.assertEqual(result['summary']['duplicate_revision_count'], 1)
        self.assertEqual(result['summary']['ordinary_settled_result_count'], 0)
        self.assertEqual(result['summary']['pending_result_count'], 1)
        self.assertEqual(len(result['receipt']['journal_index']), 2)
        corrupt_old = deepcopy(old); corrupt_old['source_sha256'] = 'invalid'
        with self.assertRaises(ValueError):
            self.admit(observations=[corrupt_old, pending])
        conflict = deepcopy(old); conflict['source_sha256'] = 'c'*64
        with self.assertRaisesRegex(ValueError, '(?i)conflicting'):
            self.admit(observations=[old, conflict])
        conflict['captured_at'] = '2030-04-01T11:10:00+09:00'
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_RESULT_CAPTURE'):
            self.admit(observations=[old, conflict])

    def test_special_refund_and_unpublished_captures_stay_out_of_ordinary_labels(self):
        for special in ('cancelled', 'no_contest', 'special', 'dead_heat', 'refund', 'abnormal'):
            value = settled()
            if special in ('cancelled', 'no_contest'):
                value['data'].update(status=special, finish_confirmed=False, results=[], top3=None, payouts=[])
            elif special in ('special', 'dead_heat'):
                value['data'].update(status=special, top3=None)
            elif special == 'refund':
                value['data']['refund_boats'] = [6]
            else:
                value['data']['results'][5].update(finish=None, finish_status='F')
            with self.subTest(special=special):
                result = self.admit(observations=[value])
                self.assertEqual(result['observations'], [value])
                self.assertEqual(result['summary']['ordinary_settled_result_count'], 0)
                self.assertEqual(result['summary']['special_result_count'], 1)
                self.assertTrue(result['summary']['missing_results_are_not_losses'])
        pending = settled()
        pending.update(status='PENDING', body_identity_verified=False, data=None)
        pending.pop('closed_at')
        self.assertEqual(self.admit(observations=[pending])['summary']['pending_result_count'], 1)
        self.assertEqual(self.admit(observations=[])['observations'], [])

    def test_key_missing_precedes_metadata_and_archive_inspection_and_wrong_key_fails(self):
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), \
             patch.object(intake, '_metadata', side_effect=AssertionError('metadata before key')) as read:
            with self.assertRaises(ValueError):
                intake.observations_from_result_artifact(object(), object(), now=object(),
                    expected_run_id=object(), expected_head_sha=object())
            self.assertEqual(read.call_count, 0)
        raw, meta, _, _ = fixture()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(bytes(reversed(KEY))).decode()):
            with self.assertRaisesRegex(ValueError, 'AUTHENTICATION_FAILED'):
                self.admit(raw, meta)

    def test_actual_metadata_identity_digest_size_expiry_and_clock_are_required(self):
        raw, original, _, _ = fixture()
        mutations = [lambda m:m.update(id=True), lambda m:m.update(expired=True),
            lambda m:m.update(name='race-existing-cycle-100'),
            lambda m:m.update(name='race-existing-cycle-99-cycle-01'),
            lambda m:m['workflow_run'].update(id=100), lambda m:m['workflow_run'].update(id=True),
            lambda m:m['workflow_run'].update(head_sha='b'*40),
            lambda m:m['workflow_run'].update(repository_id=1),
            lambda m:m['workflow_run'].update(head_repository_id=1),
            lambda m:m.update(size_in_bytes=len(raw)+1), lambda m:m.update(size_in_bytes=True),
            lambda m:m.update(digest='sha256:'+'0'*64),
            lambda m:m.update(created_at='2030-04-01T03:00:00Z'),
            lambda m:m.update(expires_at=NOW.isoformat()),
            lambda m:m.update(created_at='2030-04-01T02:11:00')]
        for mutation in mutations:
            meta = deepcopy(original); mutation(meta)
            with self.subTest(metadata=meta), self.assertRaises(ValueError):
                self.admit(raw, meta)
        with self.assertRaises(ValueError):
            intake.observations_from_result_artifact(raw, original, now=NOW.replace(tzinfo=None),
                expected_run_id=99, expected_head_sha=HEAD)
        with self.assertRaises(ValueError):
            intake.observations_from_result_artifact(raw, original, now=NOW,
                expected_run_id=True, expected_head_sha=HEAD)

    def test_plaintext_other_envelope_kind_and_cipher_corruption_are_rejected(self):
        raw, meta, plain, _ = fixture()
        clear_meta = dict(meta, digest='sha256:'+sha256(plain).hexdigest(), size_in_bytes=len(plain))
        with self.assertRaisesRegex(ValueError, 'ENCRYPTED_RESULT_REQUIRED'):
            self.admit(plain, clear_meta)
        other, other_meta, _, _ = fixture(kind='P1')
        with self.assertRaises(ValueError):
            self.admit(other, other_meta)
        bad = bytearray(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            cipher = bytearray(archive.read('private-original.enc'))
        cipher[-1] ^= 1
        bad = packed([('private-original.enc', bytes(cipher))])
        bad_meta = dict(meta, digest='sha256:'+sha256(bad).hexdigest(), size_in_bytes=len(bad))
        with self.assertRaises(ValueError):
            self.admit(bad, bad_meta)

    def test_report_identity_hash_day_count_and_clocks_bind_the_journal(self):
        changes = [lambda r:r.update(schema='wrong'), lambda r:r.update(run_id='100'),
            lambda r:r.update(code_sha='b'*40), lambda r:r.update(day_jst='2030-04-02'),
            lambda r:r.update(result_observation_versions=0),
            lambda r:r.update(result_observation_versions=True),
            lambda r:r.update(updated_at='2030-04-01T02:09:00Z'),
            lambda r:r.update(updated_at='2030-04-01T02:11:01Z')]
        for mutation in changes:
            with self.subTest(change=mutation), self.assertRaises(ValueError):
                self.admit(mutate_report=mutation)
        raw, meta, _, report = fixture()
        report['actual_purchases'] = True  # Break the inner canonical report seal.
        inner = packed([('official-result-observations.json', json.dumps([settled()])),
                        ('status.json', json.dumps(report))])
        cipher = seal_original_zip(inner, run_id=99, head_sha=HEAD, kind='RESULT', key=KEY)
        bad = packed([('private-original.enc', cipher)])
        meta.update(digest='sha256:'+sha256(bad).hexdigest(), size_in_bytes=len(bad))
        with self.assertRaisesRegex(ValueError, 'REPORT_HASH'):
            self.admit(bad, meta)

    def test_normal_result_source_cutoff_registered_roster_and_payout_guards(self):
        changes = [lambda v:v.update(race_id='20300401-01-13'),
            lambda v:v.update(source_url=v['source_url'].replace('jcd=01', 'jcd=02')),
            lambda v:v.update(source_url=v['source_url']+'#fragment'),
            lambda v:v.update(source_url=v['source_url'].replace('www.boatrace.jp', 'foreign.example')),
            lambda v:v.update(source_sha256='not-a-hash'), lambda v:v.update(kind='beforeinfo'),
            lambda v:v.update(body_identity_verified=False),
            lambda v:v.update(captured_at='2030-04-01T01:59:59Z', available_at='2030-04-01T01:59:59Z'),
            lambda v:v.update(captured_at='2030-04-01T02:11:01Z'),
            lambda v:v.update(upstream_published_at='2030-04-01T02:10:01Z'),
            lambda v:v['data']['results'][0].update(racer_registration_id='fiction'),
            lambda v:v['data']['results'][0].update(racer_registration_id='4002'),
            lambda v:v['data']['results'][0].update(lane=2),
            lambda v:v['data']['results'][0].update(race_id='20300401-02-01'),
            lambda v:v['data']['results'][0].update(verified_official=False),
            lambda v:v['data'].update(top3=[3, 2, 1]),
            lambda v:v['data']['payouts'][0].update(payout_per_100_yen=-1)]
        for mutation in changes:
            value = settled(); mutation(value)
            with self.subTest(change=mutation), self.assertRaises(ValueError):
                self.admit(observations=[value])

    def test_whole_second_save_precision_is_bounded_without_inventing_publication(self):
        value = settled()
        value.update(captured_at='2030-04-01T02:11:00.100000Z', available_at='2030-04-01T02:11:00.100000Z')
        result = self.admit(observations=[value], mutate_report=lambda r:r.update(updated_at='2030-04-01T02:11:00.200000Z'))
        self.assertEqual(result['observations'], [value])
        self.assertIsNone(result['observations'][0]['upstream_published_at'])
        value['captured_at'] = '2030-04-01T02:11:01Z'
        with self.assertRaises(ValueError):
            self.admit(observations=[value], mutate_report=lambda r:r.update(updated_at='2030-04-01T02:11:01Z'))

    def test_duplicate_json_keys_nonfinite_values_missing_members_and_oversize_stop(self):
        for journal in ('[{"race_id":"x","race_id":"y"}]', '[NaN]', '{}'):
            with self.subTest(journal=journal), self.assertRaises(ValueError):
                self.admit(journal_bytes=journal)
        with self.assertRaises(ValueError):
            self.admit(journal_bytes=' '*intake.MAX_MEMBER_BYTES+'[]')
        raw, meta, _, _ = fixture()
        plain = packed([('status.json', '{}')])
        cipher = seal_original_zip(plain, run_id=99, head_sha=HEAD, kind='RESULT', key=KEY)
        missing = packed([('private-original.enc', cipher)])
        meta.update(digest='sha256:'+sha256(missing).hexdigest(), size_in_bytes=len(missing))
        with self.assertRaisesRegex(ValueError, 'MEMBER_INVALID'):
            self.admit(missing, meta)


if __name__ == '__main__':
    unittest.main()
