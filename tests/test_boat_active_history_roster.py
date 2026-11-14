"""Confirmed smaller present rosters retain genuine prior result evidence."""
from copy import deepcopy
import unittest

from race_ai.actions_contract import digest
from race_ai.observed_result_history import context_from_result_archive, prepare_history, verify_history_evidence
from race_ai.observed_p1_connection import build_bundle, verified_rows
from tests.test_observed_result_history import archived, observation, roster
from tests.test_observed_p1_connection import inputs, AT


class ActiveHistoryRosterTests(unittest.TestCase):
    def context(self, lanes=None):
        prior = observation()
        if lanes is not None:
            prior['data']['results'] = [r for r in prior['data']['results'] if r['lane'] in lanes]
        return context_from_result_archive(*archived([prior]), verified_at='2030-03-31T04:01:00Z')

    def test_active_current_roster_keeps_prior_samples_and_evidence_membership(self):
        lanes = (1, 3, 6)
        rows = [r for r in roster() if r['lane'] in lanes]
        prepared = prepare_history(self.context(), race_id='20300401-01-01', participants=rows, as_of=AT)
        self.assertEqual([r['lane'] for r in prepared['participants']], list(lanes))
        self.assertEqual([r['features']['recent_mean_finish']['value'] for r in prepared['participants']], [1., 3., 6.])
        self.assertEqual(prepared, verify_history_evidence(prepared['evidence'],
            race_id='20300401-01-01', participants=rows, as_of=AT))
        with self.assertRaises(ValueError):
            verify_history_evidence(prepared['evidence'], race_id='20300401-01-01',
                                    participants=roster(), as_of=AT)

    def test_smaller_verified_historical_result_supplies_only_its_actual_samples(self):
        prepared = prepare_history(self.context((1, 3, 6)), race_id='20300401-01-01',
                                   participants=roster(), as_of=AT)
        for row in prepared['participants']:
            if row['lane'] in (1, 3, 6):
                self.assertEqual(row['features']['recent_mean_finish']['sample_n'], 1)
            else:
                self.assertEqual(row['features'], {})
                self.assertEqual(row['missing']['recent_mean_finish'], 'NO_PRIOR_SAMPLES')

    def test_active_bundle_freezes_verified_history_without_padding_roster(self):
        base, extra, proof = inputs()
        base['boats'] = [r for r in base['boats'] if r['lane'] in (1, 3, 6)]
        extra['participants'] = [r for r in extra['participants'] if r['lane'] in (1, 3, 6)]
        bundle = build_bundle(base, extra, AT, **proof, owner_reviewed=True, history_context=self.context())
        rows = verified_rows(bundle, dict(id=99, created_at='2030-04-01T01:41:00Z'), 'd'*64)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(set(r['roster']) == {'1', '3', '6'} for r in rows))
        self.assertTrue(all(len(r['top8']) == 6 for r in rows))

    def test_complete_six_original_history_is_unchanged(self):
        prepared = prepare_history(self.context(), race_id='20300401-01-01', participants=roster(), as_of=AT)
        self.assertEqual(digest(prepared), '2376713b37bb0d24958c5fbcefe4f12dfed8883cf1000fff0f6b27f272c3d88c')


if __name__ == '__main__':
    unittest.main()
