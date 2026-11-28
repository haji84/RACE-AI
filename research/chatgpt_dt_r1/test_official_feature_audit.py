"""Synthetic aggregate boundary tests; no owner originals are used."""
import json
import unittest

import numpy as np

from research.chatgpt_dt_r1 import official_feature_audit as audit
from research.chatgpt_dt_r1.model import RankModel


class OfficialFeatureAuditTests(unittest.TestCase):
    def setUp(self):
        self.model = RankModel.zero(audit.NAMES)
        self.model.fit_meta['feature_mask'] = [True] * len(audit.NAMES)
        self.model.weights[0, audit.NAMES.index('points')] = 2.
        self.model.weights[3, audit.NAMES.index('win_rate')] = 5.
        self.private_name = 'PRIVATE_RIDER_REGISTRATION'

    def row(self, history_races=0):
        features = np.zeros((3, 462))
        features[:, audit.NAMES.index('points')] = [2., 4., 8.]
        features[:, audit.NAMES.index('points_missing')] = [0, 0, 1]
        features[:, audit.NAMES.index('win_rate')] = [1., 2., 3.]
        return dict(feature_names=list(audit.NAMES), features=features, cohort='prospective',
                    feature_status='READY', riders=[dict(car=i, official_registration_id=self.private_name)
                                                    for i in (1, 2, 3)],
                    history_evidence=dict(
                        official_support=dict(history_races=history_races,
                            status='INDEPENDENTLY_VERIFIED' if history_races else 'MISSING_HISTORY'),
                        rider_evidence={str(i): dict(official_identity_verified=True,
                            entries=int(bool(history_races) and i < 3)) for i in (1, 2, 3)}))

    def test_zero_report_has_known_groups_but_no_observed_effect(self):
        report = audit.OfficialFeatureAudit(self.model).report()
        self.assertEqual(report['audited_races'], 0)
        self.assertEqual(report['rider_rows'], 0)
        self.assertEqual(report['groups']['all']['columns'], 462)
        self.assertEqual([report['groups'][name]['columns'] for name in
                          ('base_and_history', 'external_context', 'agari', 'five_abilities')],
                         [106, 118, 91, 147])
        self.assertEqual(report['groups']['all']['within_race_varying_columns'], 0)
        self.assertEqual(report['groups']['all']['top3_logit_rms_sum'], 0.)

    def test_warm_and_cold_rows_count_history_without_disclosing_values_or_id(self):
        worker = audit.OfficialFeatureAudit(self.model)
        worker.add(self.row())
        worker.add(self.row(4))
        report = worker.report()
        self.assertEqual((report['audited_races'], report['rider_rows']), (2, 6))
        self.assertEqual((report['races_with_official_history'],
                          report['rider_rows_with_official_history'],
                          report['official_history_race_exposures']), (1, 2, 4))
        self.assertEqual(report['groups']['all']['within_race_varying_columns'], 3)
        self.assertEqual(report['groups']['all']['top3_linear_contributing_columns'], 1)
        self.assertGreater(report['groups']['all']['top3_logit_rms_sum'], 0.)
        self.assertEqual(report['groups']['base_and_history']['explicit_missing_value_count'], 2)
        raw = json.dumps(report)
        self.assertNotIn(self.private_name, raw)
        self.assertNotIn('win_rate', raw)
        self.assertNotIn('sha256', raw)
        self.assertNotIn('probability', raw)

    def test_invalid_history_shape_is_rejected_before_counters_change(self):
        worker = audit.OfficialFeatureAudit(self.model)
        row = self.row(4)
        row['history_evidence']['official_support']['status'] = 'MISSING_HISTORY'
        with self.assertRaises(ValueError):
            worker.add(row)
        self.assertEqual(worker.report()['audited_races'], 0)

    def test_profile_counts_require_a_prior_independently_authenticated_original(self):
        worker = audit.OfficialFeatureAudit(self.model)
        row = dict(self.row(), day='2026-11-28', context_as_of='2026-11-28T07:00:00+00:00')
        proof = {'state': 'GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED',
                 'latest_server_evidence_at': '2026-11-28T06:50:00+00:00'}
        finishes = [dict(race_date=d, status=status, published_at=at) for d, status, at in (
            ('2026-11-27', 'FINISHED', '2026-11-27T02:00:00+00:00'),
            ('2026-11-09', 'FINISHED', '2026-11-09T02:00:00+00:00'),
            ('2026-10-10', 'FINISHED', '2026-10-10T02:00:00+00:00'),
            ('2026-11-15', 'FALL_DNF', '2026-11-15T02:00:00+00:00'),
            ('2026-11-11', 'FINISHED', '2026-11-28T08:00:00+00:00'))]
        original = dict(condition_state='CONDITIONED_AUTHENTICATED_PRE_CUTOFF',
            origin_receipts={'condition_origin': proof}, supplement={'condition_evidence': {
                'as_of': '2026-11-28T06:45:00+00:00', 'riders': [{'results': finishes}]}})
        worker.add(row, original)
        worker.add(row, dict(original, condition_state='CONDITIONED_ARCHIVE_UNVERIFIED'))
        proof['latest_server_evidence_at'] = '2026-11-28T07:01:00+00:00'
        worker.add(row, original)
        report = worker.report()
        self.assertEqual(report['races_with_official_history'], 0)
        self.assertEqual(report['conditioned_profile_history_availability'], {
            'races': 1, 'rider_rows_with_finishes_days_8_to_30': 1,
            'finish_exposures_days_8_to_30': 1, 'finish_exposures_older_than_30_days': 1})
