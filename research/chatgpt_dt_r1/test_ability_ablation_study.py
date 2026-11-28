"""Synthetic boundaries for the five fixed DT-R1 coefficient diagnostics."""
import unittest
from unittest.mock import patch

import numpy as np

from research.chatgpt_dt_r1 import ability_ablation_study as study
from research.chatgpt_dt_r1.abilities import DISC_NAMES, DISC_PAIRS
from research.chatgpt_dt_r1.model import RankModel


class AbilityAblationTests(unittest.TestCase):
    def setUp(self):
        self.derived_agari = DISC_NAMES[DISC_PAIRS.index(('history_agari_venue_relative',
                                                         'history_agari_overall_relative'))]
        self.names = ('points', 'history_agari_venue_relative', self.derived_agari,
                      'line_known', 'history_dt_load_x_pressure', 'history_dt_motion_venue_attack_count_mean')
        self.frozen = RankModel.zero(self.names)
        self.frozen.weights[:, :] = 1.
        self.frozen.pair_weights[:, :] = 2.
        self.frozen.weights[:3, -1] = 0.

    def test_latent_mask_includes_selected_discovery_descendants_and_retains_shared_pair(self):
        cases, details = study.ablations(self.frozen)
        latent = cases['latent']
        self.assertEqual(details['latent']['effective_columns'], list(self.names[1:3]))
        np.testing.assert_array_equal(latent.weights[:3, 1:3], 0.)
        np.testing.assert_array_equal(latent.weights[3], self.frozen.weights[3])
        np.testing.assert_array_equal(latent.pair_weights, self.frozen.pair_weights)
        self.assertTrue(np.all(self.frozen.weights[:, 1:3] == 1.))

    def test_depletion_and_interaction_may_overlap_but_only_interaction_removes_pair_terms(self):
        cases, details = study.ablations(self.frozen)
        name = self.names[4]
        self.assertIn(name, details['depletion']['effective_columns'])
        self.assertIn(name, details['interaction']['effective_columns'])
        self.assertNotIn(self.names[-1], details['depletion']['effective_columns'])
        np.testing.assert_array_equal(cases['interaction'].pair_weights[1:3], 0.)
        np.testing.assert_array_equal(cases['interaction'].pair_weights[[0, 3]], 2.)
        np.testing.assert_array_equal(cases['depletion'].pair_weights, 2.)

    def test_failure_is_a_post_inference_no_feedback_control(self):
        cases, details = study.ablations(self.frozen)
        self.assertIs(cases['favorite_failure'], self.frozen)
        self.assertEqual(details['favorite_failure']['removed_pair_coefficients'], 0)
        self.assertEqual(details['favorite_failure']['effective_columns'], [])
        self.assertEqual(details['discovery']['effective_columns'], [self.derived_agari])

    def test_failure_control_records_same_hits_and_still_measures_favorite_loss(self):
        law = {(1, 2, 3): .35, (1, 3, 2): .15, (2, 1, 3): .20,
               (2, 3, 1): .10, (3, 2, 1): .15, (3, 1, 2): .05}
        with patch.object(study, '_joint', return_value=law) as read:
            arms, failure = study._score_day([{}], [(2, 1, 3)], {'favorite_failure': self.frozen}, self.frozen)
        self.assertEqual(arms['full'], arms['favorite_failure'])
        self.assertEqual(failure['losses'], 1)
        self.assertEqual(failure['brier_sum'], .25)
        read.assert_called_once()

    def test_calendar_bootstrap_respects_paired_counts_for_proper_score(self):
        days = {'2026-07-01': {'full': {'n': 1, 'tri_log_loss': 2.0}, 'masked': {'n': 1, 'tri_log_loss': 2.5}},
                '2026-07-02': {'full': {'n': 2, 'tri_log_loss': 4.0}, 'masked': {'n': 2, 'tri_log_loss': 4.0}}}
        actual = study.paired_difference(days, 'masked', 'full', metrics=('tri_log_loss',))
        self.assertAlmostEqual(actual['tri_log_loss']['delta'], .5 / 3.)
        self.assertEqual(actual['tri_log_loss']['ci95'], [0., .5])
