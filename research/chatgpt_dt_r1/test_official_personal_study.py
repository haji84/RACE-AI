"""One-rider observations can update form without creating a fictitious field."""
from datetime import date
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

from research.chatgpt_dt_r1.features import FeatureBuilder
from research.chatgpt_dt_r1.model import RankModel
from research.chatgpt_dt_r1 import official_personal_study as study
from research.chatgpt_dt_r1.test_official_personal_history import AT, RID, fixture
from research.chatgpt_dt_r1.official_feature_audit import NAMES
from research.chatgpt_dt_r1.policy import digest
from research.chatgpt_dt_r1.venues import VenueStore


class PersonalFinishFeaturesTests(unittest.TestCase):
    def test_rank_uses_the_actual_field_size_and_unknown_measurements_stay_missing(self):
        rider = 'a' * 64
        event = dict(identity_key=rider, race_id='202611112401', rank=3, field_size=9,
                     source_sha256='b' * 64, published_at='2026-11-11T05:00:00+00:00')
        builder = FeatureBuilder()
        study.add_to_builder(builder, [event])
        saved, = builder.history[rider]
        self.assertEqual((saved['date'], saved['venue_code'], saved['race_class']), (date(2026, 11, 11), '24', None))
        self.assertEqual((saved['rank'], saved['form'], saved['started']), (3, .75, True))
        self.assertTrue(all(saved[k] is None for k in ('half_lap_seconds', 'final_lap_seconds', 'sb_mark')))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_PERSONAL_HISTORY_FINISH'):
            study.add_to_builder(builder, [event])
        self.assertEqual(list(builder.history), [rider])

    def test_equal_input_and_verified_history_can_score_only_common_verified_results(self):
        original, target = fixture()
        trained = RankModel.zero(NAMES)
        comparison = study.OfficialPersonalStudy(trained, VenueStore.from_records(()))
        support = dict(history_races=1)
        row = dict(target, source_attestation_sha256='a' * 64, source_verified_at=AT,
            source_available_at_verified=True, source_admission_status='ADMITTED',
            pre_cutoff_authenticated=True, source_proof={}, history_evidence={'official_support': support},
            features=np.ones((len(target['riders']), len(NAMES))))
        prior = SimpleNamespace(arguments=lambda *_: dict(history_records=[], history_verifier=None))
        with (patch.object(study.official_inputs, 'verification_payload', return_value={'normalized_input': target}),
              patch.object(study.official_inputs, '_history', return_value=([], support)),
              patch.object(trained, 'distribution', wraps=trained.distribution) as distribution):
            comparison.add(payload={}, original=original, baseline=row, prior=prior, prediction_at=AT)
        distribution.assert_called_once()
        extended = distribution.call_args.args[0]
        np.testing.assert_equal(extended['features'][:, study.BASELINE_ONLY], row['features'][:, study.BASELINE_ONLY])
        self.assertEqual(extended['history_evidence']['rider_evidence']['1']['numeric_finishes'], 2)
        result = dict(race_id=RID, input_sha256=target['input_sha256'], result_status='VERIFIED_NORMAL',
                      top3=[1, 2, 3])
        # Use an identical complete law to test scoring independently from the frozen weights.
        admitted = {RID: comparison._candidates[RID]}
        report = comparison.report(admitted, [result])
        self.assertEqual((report['replayed_pairs'], report['official_scorable_pairs'],
                          report['official_prior_personal_finish_exposures']), (1, 1, 2))
        self.assertFalse(report['prospectively_sealed'])
        self.assertNotIn('proper_scores', report['archive_seven'])
        self.assertNotIn(RID, str(report))


class PersonalTrialTests(unittest.TestCase):
    def setUp(self):
        self.original, self.target = fixture()
        self.support = dict(history_races=1)
        self.baseline = dict(self.target, source_attestation_sha256='a' * 64, source_verified_at=AT,
            source_available_at_verified=True, source_admission_status='ADMITTED',
            pre_cutoff_authenticated=True, source_proof={}, history_evidence={'official_support': self.support},
            features=np.ones((len(self.target['riders']), len(NAMES))))
        self.opts = dict(trained=RankModel.zero(NAMES), venues=VenueStore.from_records(()), payload={},
            original=self.original, baseline=self.baseline, prediction_at=AT,
            prior=SimpleNamespace(arguments=lambda *_: dict(history_records=[], history_verifier=None)))

    def test_exports_exact_legacy_feature_digest_and_both_markets(self):
        with (patch.object(study.official_inputs, 'verification_payload',
                           return_value={'normalized_input': self.target}),
              patch.object(study.official_inputs, '_history', return_value=([], self.support))):
            computed, hold = study.personal_trial(**self.opts)
        self.assertIsNone(hold)
        self.assertEqual(set(computed), {'row', 'forecast', 'used_finishes'})
        self.assertEqual(computed['row']['feature_input_sha256'],
                         'ac3556b3cfa6755e21974ed2474798de5e81c630cedab3300463e9af010dd450')
        self.assertEqual(digest(computed['forecast']),
                         'c3eba2792c02319bc6b21970e4540ae2ab6cdfc99b829348b099b065f574b55d')
        self.assertEqual(computed['used_finishes'], 2)

    def test_distinguishes_unavailable_baseline_missing_profile_and_invalid_replay(self):
        self.assertEqual(study.personal_trial(**dict(self.opts, prior=None)),
                         (None, 'NO_REPLAYED_SEVEN_DAY_HISTORY'))
        with (patch.object(study.official_inputs, 'verification_payload',
                           return_value={'normalized_input': self.target}),
              patch.object(study.official_inputs, '_history', return_value=([], dict(history_races=2)))):
            self.assertEqual(study.personal_trial(**self.opts),
                             (None, 'PROFILE_EVIDENCE_OR_FEATURE_REPLAY_UNVERIFIED'))
            self.original.update(condition_state='NO_CONDITIONED_ORIGINAL', conditioned=None, supplement=None,
                                 conditioned_cipher_sha256=None, conditioned_sealed_at=None)
            self.original['origin_receipts']['condition_origin'] = None
            self.assertEqual(study.personal_trial(**self.opts), (None, 'NO_AUTHENTICATED_PROFILE'))


if __name__ == '__main__':
    unittest.main()
