"""Regression against the whitelisted *real* 2026-11-13 owner audit counts.

The full AES original is deliberately NOT committed to the public repository.
These tests validate count consistency; they cannot authenticate the underlying
GitHub ZIP again and cannot claim a newly saved national P1 forecast.
"""
import json
import re
import unittest
from pathlib import Path

FILE=Path(__file__).parent/'fixtures/boat_20261113_authenticated_count_summary.json'
SOURCE_JSON_SHA256='64922c4d6b5355e30b8d2316558d2b4e9beb73ee7e93c805291298b4b99bee53'

class ActualOwnerAuditSummaryTests(unittest.TestCase):
    def test_156_real_official_races_and_p1_denominator(self):
        a=json.loads(FILE.read_text(encoding='utf-8'))
        self.assertEqual(a['schema'],'RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1')
        self.assertEqual(a['day_jst'],'2026-11-13')
        self.assertEqual(a['owner_run_id'],43348227701)
        self.assertEqual((a['scheduled_venues'],a['scheduled_races']),(13,156))
        self.assertEqual((a['baseline_p0_races'],a['baseline_p1_races']),(136,9))
        self.assertEqual(a['scheduled_without_baseline_p1'],
                         a['scheduled_races']-a['baseline_p1_races'])
        self.assertEqual(a['scheduled_without_baseline_p1'],147)
        self.assertEqual(sum(a['missing_p1_last_observation'].values()),147)
        self.assertEqual(a['missing_p1_last_observation'],
                         {'ALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE':21,
                          'NO_RETAINED_OBSERVATION':126})
        self.assertEqual(a['p1_eligibility_unknown'],147)
        self.assertEqual(a['p1_schedule_cutoff_conflict_races'],1)
        self.assertEqual((a['baseline_p0_unique_model_slots'],
                          a['baseline_p1_unique_model_slots']),(272,45))
        self.assertEqual(set(a['p1_models']),{
            'boat-course-motor-shadow-v0.1-UNTRAINED',
            'boat-display-rating-PL-reference-v1-UNVALIDATED',
            'boat-local-start-course-shadow-v0.1-UNTRAINED',
            'boat-observed-pairwise-factor-v1',
            'boat-observed-pairwise-start-v1'})
        self.assertEqual(sum(a['p1_models'].values()),45)
        self.assertEqual(sum(a['p0_models'].values()),272)

    def test_raw_original_has_sha_reference_but_is_not_in_public_fixture(self):
        a=json.loads(FILE.read_text(encoding='utf-8'))
        self.assertEqual(a['source_json_sha256'],SOURCE_JSON_SHA256)
        self.assertRegex(a['source_json_sha256'],r'^[a-f0-9]{64}$')
        self.assertEqual(a['evidence_type'],'RETAINED_COUNT_SUMMARY_NOT_INDEPENDENT_AUDIT')
        self.assertIs(a['exact_aes_originals_included'],False)
        self.assertIs(a['official_program_verified'],True)
        self.assertIs(a['live_recovery_to_new_p1_proven'],False)
        self.assertIs(a['all_models_complete_proven'],False)
        self.assertEqual((a['verified_video_prediction_rows'],
                          a['verified_video_prediction_races']),(0,0))
        self.assertEqual((a['new_forecasts'],a['official_source_requests']),(0,0))
        self.assertIs(a['originals_changed'],False)

if __name__=='__main__':
    unittest.main()
