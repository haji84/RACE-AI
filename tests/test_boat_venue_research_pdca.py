"""Synthetic owner-encrypted private P1 pairs and independently saved metadata."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_observed_pairwise_models import MODEL_IDS, WEIGHTS
from race_ai.boat_venue_learning import read_candidate
from race_ai.observed_weight_learning import make_shadows, seal
from tests import test_boat_venue_research_receipt as receipt_tests
from tests.test_frozen_day_cycle import observation


NOW = receipt_tests.NOW


class PrivateVenuePdcaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_class = receipt_tests.PrivateP1ReceiptTests
        fixture_class.setUpClass()
        cls.addClassCleanup(fixture_class.doClassCleanups)
        cls.fixture = fixture_class()
        cls.fixture.prepare()
        cls.raw, _ = cls.fixture.archive()
        cls.metadata = cls.fixture.metadata(cls.raw)
        cls.private = deepcopy(cls.fixture.payloads[0])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='private-venue-pdca-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root/'pdca'

    def api(self):
        try:
            return importlib.import_module('race_ai.boat_venue_research_pdca')
        except ModuleNotFoundError:
            self.fail('authenticated private venue P1 forecasts have no encrypted PDCA scorer')

    def outcome(self, payload=None):
        payload = self.private if payload is None else payload
        snapshot = payload['snapshot']
        row = dict(race_id=payload['original_bundle']['race_id'],
                   cutoff_at=snapshot['sales_cutoff_at'],
                   roster={str(p['lane']): p['registration_no'] for p in snapshot['participants']},
                   top8=payload['shadows'][0]['ordered_top8'])
        result = observation(row)
        result['captured_at'] = (NOW+timedelta(minutes=40)).isoformat()
        day, venue, number = row['race_id'].split('-')
        result['source_url'] = ('https://www.boatrace.jp/owpc/pc/race/raceresult?'
                                f'hd={day}&jcd={venue}&rno={int(number)}')
        return result

    def score(self, api, observations, **changes):
        args = dict(now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
                    expected_head_sha=receipt_tests.HEAD)
        args.update(changes)
        return api.score_private_p1_artifact(self.raw, self.metadata, observations, self.output, **args)

    def partition(self, payload=None):
        payload = self.private if payload is None else payload
        return self.output/payload['original_bundle']['race_id']

    def test_actual_private_pairs_score_same_input_per_model_and_roundtrip_only_encrypted(self):
        api = self.api(); outcome = self.outcome()
        before = deepcopy((outcome, self.private, WEIGHTS))
        summary = self.score(api, [outcome])
        self.assertEqual(summary['state'], 'PRIVATE_VENUE_PDCA_SCORED')
        self.assertEqual((summary['unique_races'], summary['baseline_forecast_count'],
                          summary['saved_shadow_forecasts'], summary['paired_forecasts']), (1, 2, 2, 2))
        self.assertEqual(summary['paired_unique_races'], 1)
        self.assertTrue(summary['independent_pre_cutoff_receipt_verified'])
        self.assertTrue(summary['encrypted_readback_verified'])
        self.assertEqual({row['model_id'] for row in summary['scoreboard']}, set(MODEL_IDS))
        winner = outcome['data']['top3']
        for row in summary['scoreboard']:
            model = row['model_id']
            shadow = next(s for s in self.private['shadows'] if s['model_id'] == model)
            baseline = self.private['baseline_suite']['models'][model]
            self.assertEqual(row['paired_races'], 1)
            self.assertEqual(row['candidate_hits'], int(winner in shadow['ordered_top8']))
            self.assertEqual(row['baseline_hits'], int(winner in baseline['ordered_top8']))
            self.assertFalse(row['promotion_allowed'])
        restored = read_candidate(self.partition())
        self.assertEqual(restored['private_forecasts'], [self.private])
        self.assertEqual(restored['observations'], [outcome])
        self.assertEqual(restored['training'], self.private['training'])
        self.assertNotIn('source_artifact_zip_b64', restored)
        self.assertEqual(restored['source_artifact_zip_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual('sha256:'+restored['source_artifact_zip_sha256'], self.metadata['digest'])
        self.assertEqual(restored['source_artifact_metadata'], self.metadata)
        self.assertEqual(restored['score']['paired_forecasts'], 2)
        self.assertEqual(len(restored['score']['per_forecast']), 2)
        bases = {row['model_id']: row for row in restored['baseline_rows']}
        for row in restored['shadow_rows']:
            baseline = bases[row['model_id']]
            for field in ('race_id', 'stage', 'as_of', 'cutoff_at', 'server_saved_at', 'artifact_id', 'roster'):
                self.assertEqual(row[field], baseline[field])
            self.assertEqual(row['baseline_model_sha256'], baseline['model_sha256'])
            self.assertEqual(row['artifact_id'], self.metadata['id'])
        for name in ('production_promoted', 'actual_purchases', 'accuracy_improvement_proven',
                     'baseline_coefficients_changed', 'provider_permission_confirmed', 'plaintext_published'):
            self.assertIs(summary[name], False)
        public = json.dumps(summary).encode()+(self.output/'summary.json').read_bytes()
        for secret in (b'top8', b'ordered_top8', b'weights', b'participants', b'source_url',
                       b'roster', b'per_forecast', b'source_artifact_zip_b64', b'"4001"'):
            self.assertNotIn(secret, public)
        self.assertEqual({p.name for p in self.partition().iterdir()}, {'learning.json', 'learning.enc', 'summary.json'})
        self.assertEqual({p.name for p in self.output.iterdir()}, {'20300401-17-01', 'summary.json'})
        self.assertEqual((outcome, self.private, WEIGHTS), before)

    def test_missing_result_remains_pending_and_retains_both_authenticated_forecasts(self):
        api = self.api(); summary = self.score(api, [])
        self.assertEqual(summary['state'], 'PRIVATE_VENUE_PDCA_PENDING')
        self.assertEqual(summary['paired_forecasts'], 0)
        self.assertEqual(summary['scoreboard'], [])
        self.assertEqual(summary['result_state_counts'], {'RESULT_PENDING': 2})
        self.assertEqual(len(read_candidate(self.partition())['score']['per_forecast']), 2)
        self.assertTrue(summary['independent_pre_cutoff_receipt_verified'])

    def test_multiple_races_keep_one_same_input_pair_per_model_and_race(self):
        api = self.api(); forecasts = self.fixture.payloads[:3]
        raw, _ = self.fixture.archive(forecasts)
        observations = [self.outcome(payload) for payload in forecasts]
        summary = api.score_private_p1_artifact(raw, self.fixture.metadata(raw), observations,
            self.output, now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
            expected_head_sha=receipt_tests.HEAD)
        self.assertEqual(summary['unique_races'], 3)
        self.assertEqual(summary['baseline_forecast_count'], 6)
        self.assertEqual(summary['saved_shadow_forecasts'], 6)
        self.assertEqual(summary['paired_forecasts'], 6)
        self.assertEqual(summary['paired_unique_races'], 3)
        self.assertEqual(len(summary['scoreboard']), 2)
        self.assertTrue(all(row['paired_races'] == 3 for row in summary['scoreboard']))
        self.assertEqual(summary['partition_count'], 3)
        for payload, expected_observation in zip(forecasts, observations):
            restored = read_candidate(self.partition(payload))
            self.assertEqual(restored['private_forecasts'], [payload])
            self.assertEqual(restored['observations'], [expected_observation])
            self.assertEqual(len(restored['baseline_rows']), 2)
            self.assertEqual(len(restored['shadow_rows']), 2)
            self.assertEqual(len(restored['score']['per_forecast']), 2)
            self.assertEqual(restored['summary']['paired_forecasts'], 2)
            self.assertTrue(all(row['paired_races'] == 1 for row in restored['summary']['scoreboard']))
        self.assertEqual(json.loads((self.output/'summary.json').read_bytes()), summary)

    def test_authenticated_boundary_keeps_large_archive_out_of_existing_codec_partitions(self):
        api = self.api(); forecasts = self.fixture.payloads[:3]
        # This is a post-admission capacity test, not proof that opaque bytes
        # are a valid artifact. Admission/replay has independent real ZIP tests.
        raw = b'opaque authenticated-boundary placeholder'*(256*1024)
        self.assertGreater(len(raw), 8*1024*1024)
        metadata = self.fixture.metadata(raw)
        admission = dict(independent_pre_cutoff_receipt_verified=True,
                         artifact_id=metadata['id'], artifact_digest=metadata['digest'],
                         workflow_run_id=receipt_tests.RUN_ID, head_sha=receipt_tests.HEAD)
        with patch.object(api, '_verified_private_p1_artifact', return_value=(admission, deepcopy(forecasts))):
            summary = api.score_private_p1_artifact(raw, metadata, [], self.output,
                now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
                expected_head_sha=receipt_tests.HEAD)
        self.assertEqual((summary['unique_races'], summary['partition_count']), (3, 3))
        for forecast in forecasts:
            folder = self.partition(forecast); restored = read_candidate(folder)
            self.assertEqual(restored['source_artifact_zip_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertNotIn('source_artifact_zip_b64', restored)
            self.assertEqual(len(restored['private_forecasts']), 1)
            self.assertLess((folder/'learning.enc').stat().st_size, 2*1024*1024)

    def test_partial_failure_preserves_earlier_race_and_refuses_reset(self):
        api = self.api(); forecasts = self.fixture.payloads[:3]
        raw, _ = self.fixture.archive(forecasts); metadata = self.fixture.metadata(raw)
        original_seal = api.seal_candidate; sealed = []
        def seal_first_only(payload, output):
            if sealed:
                raise ValueError('synthetic second-partition failure')
            result = original_seal(payload, output); sealed.append(Path(output))
            return result
        with patch.object(api, 'seal_candidate', side_effect=seal_first_only):
            with self.assertRaisesRegex(ValueError, 'second-partition failure'):
                api.score_private_p1_artifact(raw, metadata, [], self.output,
                    now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
                    expected_head_sha=receipt_tests.HEAD)
        self.assertEqual(sealed, [self.partition(forecasts[0])])
        first = {path.name: path.read_bytes() for path in sealed[0].iterdir()}
        self.assertFalse((self.output/'summary.json').exists())
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            api.score_private_p1_artifact(raw, metadata, [], self.output,
                now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
                expected_head_sha=receipt_tests.HEAD)
        self.assertEqual({path.name: path.read_bytes() for path in sealed[0].iterdir()}, first)

    def test_foreign_roster_cutoff_and_unverified_identity_never_become_scored_pairs(self):
        api = self.api(); good = self.outcome()
        wrong_roster = deepcopy(good); wrong_roster['data']['results'][0]['racer_registration_id'] = '9999'
        wrong_cutoff = deepcopy(good); wrong_cutoff['closed_at'] = (NOW+timedelta(minutes=31)).isoformat()
        unverified = deepcopy(good); unverified['body_identity_verified'] = False
        foreign = deepcopy(good); foreign['race_id'] = '20300401-18-01'
        for index, (result, state) in enumerate(((wrong_roster, 'RESULT_REJECTED'),
                (wrong_cutoff, 'RESULT_REJECTED'), (unverified, 'RESULT_REJECTED'),
                (foreign, 'RESULT_PENDING'))):
            with self.subTest(case=index):
                self.output = self.root/str(index)
                summary = self.score(api, [result])
                self.assertEqual(summary['state'], 'PRIVATE_VENUE_PDCA_PENDING')
                self.assertEqual(summary['paired_forecasts'], 0)
                self.assertEqual(summary['result_state_counts'], {state: 2})

    def test_special_dispositions_stay_visible_and_unscored(self):
        api = self.api(); good = self.outcome()
        refund = deepcopy(good); refund['data']['refund_boats'] = [1]
        abnormal = deepcopy(good); abnormal['data']['results'][0]['finish_status'] = 'DISQUALIFIED'
        for index, (result, state) in enumerate(((refund, 'REFUND_REVIEW_REQUIRED'),
                                                (abnormal, 'ABNORMAL_FINISH_REVIEW_REQUIRED'))):
            with self.subTest(state=state):
                self.output = self.root/str(index)
                summary = self.score(api, [result])
                self.assertEqual(summary['paired_forecasts'], 0)
                self.assertEqual(summary['result_state_counts'], {state: 2})

    def test_duplicate_and_future_observations_reject_before_scoring_or_output(self):
        api = self.api(); outcome = self.outcome()
        future = deepcopy(outcome); future['captured_at'] = (NOW+timedelta(hours=1, microseconds=1)).isoformat()
        for observations, reason in (([outcome, deepcopy(outcome)], 'DUPLICATE_OBSERVATION'),
                                      ([future], 'FUTURE_OBSERVATION')):
            with self.subTest(reason=reason), patch.object(
                    api, 'score_shadows', side_effect=AssertionError('invalid observations must not score')):
                with self.assertRaisesRegex(ValueError, reason):
                    self.score(api, observations)
                self.assertFalse(self.output.exists())

    def test_result_capture_exactly_now_is_available_and_naive_clocks_reject(self):
        api = self.api(); outcome = self.outcome()
        outcome['captured_at'] = (NOW+timedelta(hours=1)).isoformat()
        self.assertEqual(self.score(api, [outcome])['paired_forecasts'], 2)
        self.output = self.root/'naive'
        with self.assertRaises(ValueError):
            self.score(api, [], now=NOW.replace(tzinfo=None))
        self.assertFalse(self.output.exists())

    def test_wrong_or_late_artifact_is_rejected_before_official_scoring(self):
        api = self.api()
        for change in (dict(digest='sha256:'+'f'*64),
                       dict(created_at=(NOW+timedelta(minutes=31)).isoformat()),
                       dict(workflow_run=dict(self.metadata['workflow_run'], head_sha='f'*40))):
            with self.subTest(change=change), patch.object(
                    api, 'score_shadows', side_effect=AssertionError('unauthenticated archive must not score')):
                with self.assertRaises(ValueError):
                    api.score_private_p1_artifact(self.raw, dict(self.metadata, **change),
                        [self.outcome()], self.output, now=NOW+timedelta(hours=1),
                        expected_run_id=receipt_tests.RUN_ID, expected_head_sha=receipt_tests.HEAD)
                self.assertFalse(self.output.exists())

    def test_mixed_training_versions_are_not_combined_into_one_pdca_candidate(self):
        api = self.api(); payloads = deepcopy(self.fixture.payloads[:2])
        changed = payloads[1]; training = changed['training']
        training['models'][MODEL_IDS[0]]['weights'][0] += .001
        seal(training, 'training_sha256')
        changed['summary']['training_sha256'] = training['training_sha256']
        changed['shadows'] = make_shadows(changed['snapshot'], changed['baseline_suite'],
            dict(training=training, receipt=changed['training_receipt']))
        raw, _ = self.fixture.archive(payloads)
        with patch.object(api, 'score_shadows', side_effect=AssertionError('mixed candidates must not score')):
            with self.assertRaisesRegex(ValueError, 'TRAINING|MIXED_CANDIDATE_CONTEXTS'):
                api.score_private_p1_artifact(raw, self.fixture.metadata(raw), [], self.output,
                    now=NOW+timedelta(hours=1), expected_run_id=receipt_tests.RUN_ID,
                    expected_head_sha=receipt_tests.HEAD)
        self.assertFalse(self.output.exists())

    def test_missing_owner_key_rejects_before_reader_and_output(self):
        api = self.api()
        with patch.dict(os.environ, RACE_AI_STATE_KEY=''), patch.object(
                api, '_verified_private_p1_artifact', side_effect=AssertionError('owner key first')):
            with self.assertRaises(ValueError):
                self.score(api, [])
        self.assertFalse(self.output.exists())

    def test_existing_empty_nonempty_symlink_and_git_outputs_are_never_reset(self):
        api = self.api(); self.output.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            self.score(api, [])
        self.assertEqual(list(self.output.iterdir()), [])
        marker = self.output/'original'; marker.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'DO_NOT_RESET'):
            self.score(api, [])
        self.assertEqual(marker.read_text(), 'keep')
        self.output = self.root/'linked'; self.output.symlink_to(marker.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.score(api, [])
        self.output = self.root/'repository'/'pdca'
        self.output.parent.mkdir(mode=0o700); (self.output.parent/'.git').mkdir()
        with self.assertRaises(ValueError):
            self.score(api, [])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
