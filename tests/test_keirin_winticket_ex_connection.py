"""Synthetic EX observations; no actual provider rights, forecast or purchase."""
from copy import deepcopy
import importlib
import importlib.util
import unittest

MODULE = 'race_ai.keirin_winticket_ex_connection'


class ObservedAttackCountsTests(unittest.TestCase):
    def method(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE))
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
        self.assertIsNone(self.method()({'exSpurt': {
            'succeeded': 3, 'total': 4, 'percentage': 75}})['value'])

    def test_reported_percentage_checked_not_used_as_fabricated_denominator(self):
        f = self.method()
        good = {'exSpurt': {'succeeded': 1, 'total': 3, 'percentage': 33.3},
                'exThrust': {'succeeded': 1, 'total': 3, 'percentage': '33.3'}}
        self.assertAlmostEqual(f(good)['value'], 1/3)
        good['exSpurt']['percentage'] = 90
        self.assertIsNone(f(good)['value'])

    def test_integer_display_rounding_uses_integer_precision(self):
        f = self.method()
        row = {'exSpurt': {'succeeded': 1, 'total': 3, 'percentage': 33},
               'exThrust': {'succeeded': 2, 'total': 3, 'percentage': 67}}
        self.assertAlmostEqual(f(row)['value'], .5)
        row['exSpurt']['percentage'] = 34
        self.assertIsNone(f(row)['value'])

    def test_bad_counts_and_nonfinite_rate_do_not_close_model_gaps(self):
        baseline = {'exSpurt': {'succeeded': 1, 'total': 2, 'percentage': 50},
                    'exThrust': {'succeeded': 0, 'total': 0, 'percentage': 0}}
        f = self.method()
        for field, value in [('total', True), ('total', -1), ('succeeded', 3),
                             ('succeeded', '1'), ('percentage', float('nan')),
                             ('percentage', None), ('percentage', 1e-100)]:
            case = deepcopy(baseline)
            case['exSpurt'][field] = value
            with self.subTest(field=field, value=str(value)):
                self.assertIsNone(f(case)['value'])


class SourceToExistingModelSlotTests(unittest.TestCase):
    def source(self, mutation=None):
        from tests.test_keirin_winticket_embedded_racecard import fixture, RACE, URL, CAPTURE, CUTOFF
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

    def test_existing_private_capture_intake_persists_ex_lineage_without_generating_forecast(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from hashlib import sha256
        import json
        from race_ai.keirin_owner_captured_ssr_intake import stage_private_captured_winticket
        from tests.test_keirin_winticket_embedded_racecard import URL, CAPTURE
        packet, html = self.source()
        with TemporaryDirectory() as temp:
            root = Path(temp)
            capture = root / 'owner_public_capture'
            capture.mkdir()
            (capture / 'one.html').write_bytes(html)
            (capture / 'one.json').write_text(json.dumps({
                'schema': 'RACE_AI_KEIRIN_OWNER_PUBLIC_HTML_CAPTURE_V1',
                'source_url': URL, 'captured_at_utc': CAPTURE,
                'body_sha256': sha256(html).hexdigest(), 'body_size_bytes': len(html),
            }))
            first = stage_private_captured_winticket(root)
            self.assertEqual(first['private_partial_racecards_staged'], 1)
            files = list((root / 'winticket_racecard_partial').glob('*.json'))
            self.assertEqual(len(files), 1)
            saved = json.loads(files[0].read_text())
            self.assertEqual(len(saved.get('ex_action_ratio_evidence', {})), 7)
            self.assertEqual(saved['html_sha256'], packet['html_sha256'])
            self.assertEqual(first['forecasts_created'], 0)
            self.assertFalse(first['full_preflight_claimed'])
            self.assertEqual(stage_private_captured_winticket(root)[
                'private_partial_racecards_staged'], 0)

    def test_observed_following_retention_fills_only_the_existing_line_reliability_slots(self):
        from race_ai.keirin_winticket_ex_connection import attach_observed_attack_counts
        from race_ai.keirin_real_source_gap_report import inspect_source_gaps
        def add(data):
            for row in data['records']:
                row['exLeftBehind'] = {'succeeded': 2, 'total': 10, 'percentage': 20}
        packet, html = self.source(add)
        enriched = attach_observed_attack_counts(packet, html)
        self.assertEqual(len(enriched['ex_following_retention_evidence']), 7)
        for name in ('model_A_source_coverage', 'model_B_source_coverage'):
            coverage = inspect_source_gaps(enriched)[name]
            self.assertEqual(coverage['source_unobserved_required_slots'], 65)
            self.assertEqual(coverage['source_observed_required_slots'], 28)
        for no in range(1, 8):
            key = f'rider/{no}/start_or_line_reliability'
            self.assertEqual(enriched['direct_verified_fields'][key], .8)
            self.assertEqual(enriched['ex_following_retention_evidence'][key]['sample_n'], 10)
            self.assertFalse(enriched['ex_following_retention_evidence'][key]['measured_start_reaction'])
            self.assertNotIn(f'rider/{no}/teammate_pair_history', enriched['direct_verified_fields'])
            self.assertNotIn(f'rider/{no}/stamina_and_pace_resilience', enriched['direct_verified_fields'])

    def test_exact_ex_values_pass_existing_four_model_input_unchanged_in_fictional_complete_packet(self):
        from datetime import datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tests.test_keirin_allowed_delivery import fixture, assemble, ISSUED
        from race_ai.keirin_winticket_ex_connection import attack_success_from_record, line_retention_from_record
        from race_ai.keirin_owner_sqlite import PrivateKeirinStore
        from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
        from race_ai.four_sport_model_suite import ALL_MODELS
        data = fixture()
        record = {'exSpurt': {'succeeded': 3, 'total': 4, 'percentage': 75},
                  'exThrust': {'succeeded': 1, 'total': 2, 'percentage': 50},
                  'exLeftBehind': {'succeeded': 2, 'total': 10, 'percentage': 20}}
        values = {'lead_attempt_and_success': attack_success_from_record(record),
                  'start_or_line_reliability': line_retention_from_record(record)}
        for observation in data['observations']:
            field = observation['key'].split('/')[-1]
            if field in values:
                observation['value'] = values[field]['value']
                observation['sample_n'] = values[field]['sample_n']
        packet = assemble(data)['private_snapshot']
        self.assertIsNotNone(packet)
        for rider in packet['facts']['pr71_evidenced_snapshot']['participants']:
            self.assertAlmostEqual(rider['features']['attack_success']['value'], 4/6)
            self.assertEqual(rider['features']['start_reliability']['value'], .8)
        with TemporaryDirectory() as root:
            with PrivateKeirinStore(Path(root)/'fictional.sqlite3',
                                   clock=lambda: datetime.fromisoformat(ISSUED)) as store:
                ledger = FourModelRankLedger(store)
                self.assertEqual(ledger.freeze_once(packet, source_admission=lambda *_: True),
                                 'FOUR_MODELS_FROZEN_ONCE')
                saved = ledger.read_suite(packet['race_id'])['suite']
                self.assertEqual(set(saved['models']), set(ALL_MODELS))
                self.assertTrue(all(m['candidate_count'] == 210 for m in saved['models'].values()))


class LineRetentionTests(unittest.TestCase):
    def method(self):
        return importlib.import_module(MODULE).line_retention_from_record

    def test_exact_following_retention_not_a_start_reaction_measurement(self):
        row = self.method()({'exLeftBehind': {'succeeded': 2, 'total': 10, 'percentage': 20}})
        self.assertEqual(row['value'], .8)
        self.assertEqual(row['sample_n'], 10)
        self.assertEqual(row['retained_following'], 8)
        self.assertFalse(row['measured_start_reaction'])

    def test_zero_denominator_never_becomes_perfect_reliability(self):
        self.assertIsNone(self.method()({'exLeftBehind': {
            'succeeded': 0, 'total': 0, 'percentage': 0}})['value'])

    def test_known_zero_drops_is_real_retention(self):
        self.assertEqual(self.method()({'exLeftBehind': {
            'succeeded': 0, 'total': 10, 'percentage': 0}})['value'], 1)

    def test_no_observation_and_bad_counter_fail_closed(self):
        for row in ({}, {'exLeftBehind': {'succeeded': 11, 'total': 10, 'percentage': 100}},
                    {'exLeftBehind': {'succeeded': 2, 'total': 10, 'percentage': 10}},
                    {'exLeftBehind': {'succeeded': 1, 'total': 10, 'percentage': 1e-100}}):
            self.assertIsNone(self.method()(row)['value'])


if __name__ == '__main__':
    unittest.main()
