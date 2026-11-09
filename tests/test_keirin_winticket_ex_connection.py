"""Synthetic EX observations; no actual provider rights, forecast or purchase."""
from copy import deepcopy
import importlib
import importlib.util
import unittest

MODULE = 'race_ai.keirin_winticket_ex_connection'


class ObservedAttackCountsTests(unittest.TestCase):
    def method(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE),
                             'existing EX attack counts have no model-source connection')
        return importlib.import_module(MODULE).attack_success_from_record

    def test_observed_actions_use_their_actual_combined_denominator(self):
        out = self.method()({'exSpurt': {'succeeded': 3, 'total': 4, 'percentage': 75},
                             'exThrust': {'succeeded': 1, 'total': 2, 'percentage': 50}})
        self.assertEqual(out['sample_n'], 6)
        self.assertEqual(out['successful_actions'], 4)
        self.assertAlmostEqual(out['value'], 4/6)
        self.assertEqual(out['status'], 'OBSERVED_ACTION_RATIO')
        self.assertFalse(out['calibrated_race_win_probability'])

    def test_observed_zero_attempt_component_is_not_a_zero_success_prior(self):
        out = self.method()({'exSpurt': {'succeeded': 0, 'total': 0, 'percentage': 0},
                             'exThrust': {'succeeded': 1, 'total': 2, 'percentage': 50}})
        self.assertEqual(out['sample_n'], 2)
        self.assertEqual(out['value'], .5)

    def test_both_zero_attempts_remain_unavailable(self):
        out = self.method()({'exSpurt': {'succeeded': 0, 'total': 0, 'percentage': 0},
                             'exThrust': {'succeeded': 0, 'total': 0, 'percentage': 0}})
        self.assertIsNone(out['value'])
        self.assertEqual(out['sample_n'], 0)

    def test_unobserved_component_cannot_be_assumed_zero(self):
        out = self.method()({'exSpurt': {'succeeded': 3, 'total': 4, 'percentage': 75}})
        self.assertIsNone(out['value'])

    def test_reported_percentage_checked_not_used_as_fabricated_denominator(self):
        f = self.method()
        good = {'exSpurt': {'succeeded': 1, 'total': 3, 'percentage': 33.3},
                'exThrust': {'succeeded': 1, 'total': 3, 'percentage': '33.3'}}
        self.assertAlmostEqual(f(good)['value'], 1/3)
        good['exSpurt']['percentage'] = 90
        self.assertIsNone(f(good)['value'])

    def test_bad_counts_and_nonfinite_rate_do_not_close_model_gaps(self):
        baseline = {'exSpurt': {'succeeded': 1, 'total': 2, 'percentage': 50},
                    'exThrust': {'succeeded': 0, 'total': 0, 'percentage': 0}}
        f = self.method()
        for field, value in [('total', True), ('total', -1), ('succeeded', 3),
                             ('succeeded', '1'), ('percentage', float('nan')),
                             ('percentage', None)]:
            case = deepcopy(baseline)
            case['exSpurt'][field] = value
            with self.subTest(field=field, value=str(value)):
                self.assertIsNone(f(case)['value'])


class SourceToExistingModelSlotTests(unittest.TestCase):
    def source(self, mutation=None):
        from tests.test_keirin_winticket_embedded_racecard import (
            fixture, RACE, URL, CAPTURE, CUTOFF,
        )
        from race_ai.keirin_winticket_embedded_racecard import racecard_from_public_html
        def add(data):
            for row in data['records']:
                row.update(exSpurt={'succeeded': 3, 'total': 4, 'percentage': 75},
                           exThrust={'succeeded': 1, 'total': 2, 'percentage': 50})
            if mutation:
                mutation(data)
        html = fixture(mutation=add)
        packet = racecard_from_public_html(html, url=URL, race_id=RACE,
                                          captured_at=CAPTURE, expected_cutoff_at=CUTOFF)
        return packet, html

    def test_checked_source_closes_seven_attack_slots_not_acceleration_or_other_features(self):
        from race_ai.keirin_winticket_ex_connection import attach_observed_attack_counts
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        packet, html = self.source()
        baseline = deepcopy(packet)
        before = inspect_source_gaps(packet)
        enriched = attach_observed_attack_counts(packet, html)
        after = inspect_source_gaps(enriched)
        self.assertEqual(packet, baseline)
        for name in ('model_A_source_coverage', 'model_B_source_coverage'):
            self.assertEqual(before[name]['source_unobserved_required_slots'], 79)
            self.assertEqual(after[name]['source_unobserved_required_slots'], 72)
            self.assertEqual(after[name]['source_observed_required_slots'], 21)
        for no in range(1, 8):
            key = f'rider/{no}/lead_attempt_and_success'
            self.assertAlmostEqual(enriched['direct_verified_fields'][key], 4/6)
            lineage = enriched['ex_action_ratio_evidence'][key]
            self.assertEqual(lineage['sample_n'], 6)
            self.assertEqual(lineage['original_html_sha256'], packet['html_sha256'])
            self.assertFalse(lineage['approved_for_pr71_input'])
            self.assertIsNone(lineage['source_published_at'])
            self.assertNotIn(f'rider/{no}/last_lap_acceleration', enriched['direct_verified_fields'])
        self.assertFalse(enriched['forecasts_created'])
        self.assertFalse(enriched['full_347_or_437_verified'])
        self.assertNotIn('fictional-rider', str(after))

    def test_zero_attempt_and_missing_rider_component_stay_missing(self):
        from race_ai.keirin_winticket_ex_connection import attach_observed_attack_counts
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        def alter(data):
            for name in ('exSpurt', 'exThrust'):
                data['records'][0][name] = {'succeeded': 0, 'total': 0, 'percentage': 0}
            data['records'][1].pop('exSpurt')
        packet, html = self.source(alter)
        enriched = attach_observed_attack_counts(packet, html)
        self.assertEqual(len(enriched['ex_action_ratio_evidence']), 5)
        self.assertEqual(inspect_source_gaps(enriched)['model_A_source_coverage'][
            'source_unobserved_required_slots'], 74)

    def test_original_html_and_roster_cannot_be_swapped(self):
        from race_ai.keirin_winticket_ex_connection import attach_observed_attack_counts, ExSourceError
        packet, html = self.source()
        with self.assertRaises(ExSourceError):
            attach_observed_attack_counts(packet, html + b' ')
        changed = deepcopy(packet)
        changed['riders'][0]['source_player_id'] = 'UNRELATED'
        with self.assertRaises(ExSourceError):
            attach_observed_attack_counts(changed, html)

    def test_existing_parser_without_ex_still_has_original_missing_count(self):
        from tests.test_keirin_winticket_embedded_racecard import fixture, RACE, URL, CAPTURE
        from race_ai.keirin_winticket_ex_connection import racecard_with_observed_ex
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        packet = racecard_with_observed_ex(fixture(), url=URL, race_id=RACE, captured_at=CAPTURE)
        self.assertEqual(len(packet['ex_action_ratio_evidence']), 0)
        self.assertEqual(inspect_source_gaps(packet)['model_A_source_coverage'][
            'source_unobserved_required_slots'], 79)


if __name__ == '__main__':
    unittest.main()
