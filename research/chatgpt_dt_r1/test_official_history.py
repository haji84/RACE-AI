"""Synthetic encrypted-archive boundaries for DT-R1's official prior form."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_official_nationwide_records as records
from race_ai.keirin_nationwide_cipher_history import GitCipherFetchTimeout
from research.chatgpt_dt_r1 import official_history, official_inputs
from research.chatgpt_dt_r1.features import FEATURE_INDEX
from research.chatgpt_dt_r1.policy import digest
from tests.test_keirin_learned_official_inputs import _original


DAY, AT = '2030-01-15', '2030-01-15T02:01:00+00:00'
PRIOR = '2030-01-14'
HEAD = 'a' * 40


def stamp(day, time):
    return day + 'T' + time + ':00+00:00'


def prior_race(target, day=PRIOR, number='01'):
    original = deepcopy(target)
    race_id = day.replace('-', '') + target['race_id'][8:10] + number
    original.update(race_id=race_id, day_jst=day, producer_run_id='1', producer_commit='b' * 40)
    # Move the native profile/card evidence clocks together onto the prior date.
    snapshot = original['snapshot']
    snapshot.update(race_id=race_id, as_of=stamp(day, '02:00'), published_cutoff_at=stamp(day, '03:00'))
    for page in [*snapshot['source_pages'], snapshot['cutoff_source']]:
        page['captured_at'] = stamp(day, '02:00')
    original['baseline']['published_cutoff_at'] = snapshot['published_cutoff_at']
    field = [dict(car=r['car'], registration_id=r['athlete_id']) for r in snapshot['riders']]
    proof = original['origin_receipts']['baseline_origin']
    proof.update(race_id=race_id, official_cutoff_at=snapshot['published_cutoff_at'],
                 latest_server_evidence_at=stamp(day, '02:01'), minimum_margin_seconds=65)
    for i, role in enumerate(('producer', 'readback'), 1):
        proof.update({role + '_archive_sha256': str(i) * 64, role + '_commit': 'b' * 40,
                      role + '_run_id': i, role + '_job_id': i, role + '_artifact_id': i})
    proof['evidence_sha256'] = digest({k: v for k, v in proof.items() if k != 'evidence_sha256'})
    meta = dict(race_id=race_id, cutoff_at=snapshot['published_cutoff_at'], observed_at=stamp(day, '02:02'),
                producer_run_id='1', producer_commit='b' * 40, baseline_cipher_sha256='a' * 64,
                evidence_sha256='2' * 64)
    result = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1', race_id=race_id, status='FINAL_NORMAL',
                  refund_status='NONE', official_cutoff_at=snapshot['published_cutoff_at'],
                  source_updated_at=stamp(day, '04:00'), observed_at=stamp(day, '04:01'), source_sha256='3' * 64,
                  starters=field, finishes=[dict(r, status='FINISHED', place=i) for i, r in enumerate(field, 1)])
    replay = dict(official_result=result, origin_receipts=original.pop('origin_receipts'),
                  arms={'rival-private': 'must not be included'})
    first = dict(race_id=race_id, observed_at=stamp(day, '04:02'), evidence_sha256='4' * 64)
    return race_id, original, meta, replay, first


class OfficialHistoryTests(unittest.TestCase):
    def setUp(self):
        self.payload, self.target = _original()
        self.scope = SimpleNamespace(head=HEAD, day=DAY, repo='existing-authorized-reader')
        self.indexes, self.replays = {}, {}
        self.stub_archive = patch.object(records, 'RecordStore', side_effect=self.read_day).start()
        self.stub_replay = patch.object(records, '_replay_saved_result', side_effect=self.replay).start()
        self.addCleanup(patch.stopall)
        self.history = official_history.OfficialHistory(self.scope, b'fixture-only')

    def read_day(self, repo, day, *, index_commit):
        self.assertEqual((repo, index_commit), (self.scope.repo, HEAD))
        self.assertLess(day, DAY)
        return SimpleNamespace(head=index_commit, day=day, index_commit=index_commit,
                               index=self.indexes.get(day, dict(originals={}, results={})))

    def replay(self, store, original_meta, revision, pem):
        self.assertEqual(pem, b'fixture-only')
        original, replay = self.replays[revision['race_id'], revision['evidence_sha256']]
        self.assertEqual(original_meta['race_id'], original['race_id'])
        return deepcopy(original), deepcopy(replay), {}

    def add(self, race, *, versions=()):
        rid, original, meta, replay, first = race
        index = self.indexes.setdefault(original['day_jst'], dict(originals={}, results={}))
        index['originals'][rid] = meta
        index['results'][rid] = [first, *(version for version, _ in versions)]
        self.replays[rid, first['evidence_sha256']] = original, replay
        for version, corrected in versions:
            self.replays[rid, version['evidence_sha256']] = original, corrected

    def test_correction_after_input_clock_is_not_read_and_reproduction_is_deterministic(self):
        race = prior_race(self.target)
        late = dict(race[-1], observed_at=stamp(DAY, '02:02'), evidence_sha256='5' * 64)
        self.add(race, versions=[(late, None)])
        args = self.history.arguments(self.payload, self.target, AT)
        rows = args['history_records']
        self.assertEqual(len(rows), 1)
        row, = rows
        self.assertEqual((row['available_at'], row['source_verified_at'], row['result_at']),
                         (stamp(PRIOR, '02:00'), stamp(PRIOR, '02:01'), stamp(PRIOR, '04:02')))
        self.assertTrue(all(r['half_lap_seconds'] is None and r['sb_mark'] is None for r in row['result_rows']))
        forecast_input = official_inputs.prepare(self.payload, self.target, prediction_at=AT, **args,
            source_verifier=lambda packet: dict(verified=True, independent=True, verifier='synthetic',
                payload_sha256=digest(packet), receipt_sha256='6' * 64))
        self.assertEqual(forecast_input['features'][0, FEATURE_INDEX['history_missing']], 0)
        self.assertNotIn('rival-private', str(rows))
        self.assertEqual(self.history.arguments(self.payload, self.target, AT)['history_records'], rows)
        self.stub_replay.assert_called_once()

    def test_invalid_latest_admissible_revision_cannot_fall_back(self):
        race = prior_race(self.target)
        revision = dict(race[-1], observed_at=stamp(PRIOR, '04:05'), evidence_sha256='5' * 64)
        broken = deepcopy(race[-2])
        broken['official_result']['finishes'][0]['registration_id'] = '000001'
        self.add(race, versions=[(revision, broken)])
        self.assertEqual(self.history.arguments(self.payload, self.target, AT)['history_records'], [])
        self.assertEqual(self.stub_replay.call_count, 2)
        self.assertEqual(self.history.arguments(self.payload, self.target, AT)['history_records'], [])
        self.assertEqual(self.stub_replay.call_count, 2)

    def test_correction_must_advance_official_update_and_use_different_bytes(self):
        race = prior_race(self.target)
        revision = dict(race[-1], observed_at=stamp(PRIOR, '04:05'), evidence_sha256='5' * 64)
        corrected = deepcopy(race[-2])
        final = corrected['official_result']
        final.update(source_updated_at=stamp(PRIOR, '04:02'),
                     observed_at=stamp(PRIOR, '04:03'), source_sha256='7' * 64)
        final['finishes'][0]['place'], final['finishes'][1]['place'] = 2, 1
        self.add(race, versions=[(revision, corrected)])
        row, = self.history.arguments(self.payload, self.target, AT)['history_records']
        self.assertEqual(row['result_revision_evidence_sha256'], revision['evidence_sha256'])
        self.assertEqual(row['result_rows'][0]['rank'], 2)
        final['source_sha256'] = race[-2]['official_result']['source_sha256']
        self.history = official_history.OfficialHistory(self.scope, b'fixture-only')
        self.assertEqual(self.history.arguments(self.payload, self.target, AT)['history_records'], [])

    def test_archive_timeout_does_not_admit_a_smaller_snapshot(self):
        self.add(prior_race(self.target))
        self.stub_replay.side_effect = GitCipherFetchTimeout('fixture timeout')
        with self.assertRaises(GitCipherFetchTimeout):
            self.history.arguments(self.payload, self.target, AT)

    def test_packet_rejects_changed_target_and_changed_result_even_when_input_sha_is_same(self):
        self.add(prior_race(self.target))
        args = self.history.arguments(self.payload, self.target, AT)
        projected = official_inputs.verification_payload(self.payload, self.target, prediction_at=AT)['normalized_input']
        packet = dict(schema=official_inputs.HISTORY_SCHEMA, prediction_at=AT, target_race_id=projected['race_id'],
                      target_input_sha256=projected['input_sha256'], identity_namespace=official_inputs.IDENTITY_NAMESPACE,
                      history_records=args['history_records'])
        check = args['history_verifier']
        self.assertEqual(check(packet)['payload_sha256'], digest(packet))
        altered = deepcopy(packet)
        altered['history_records'][0]['result_rows'][0]['rank'] = 9
        with self.assertRaises(ValueError):
            check(altered)
        with self.assertRaises(ValueError):
            check(dict(packet, target_race_id=packet['target_race_id'][:-2] + '02'))
        with self.assertRaises(ValueError):
            check(dict(packet, prediction_at=datetime.fromisoformat(AT).replace(second=1).isoformat()))
