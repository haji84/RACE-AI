"""Fictional weather JSON exercises the existing forecast parser, no network."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import importlib
import importlib.util
import json
import os
import unittest

from tests.test_keirin_prior_private_stage import partial_card
from tests.test_keirin_winticket_prior_events import CAPTURE
from race_ai.keirin_real_source_gap_report import inspect_source_gaps
from race_ai.keirin_preflight import expected_keys

MODULE = 'race_ai.keirin_weather_input_connection'


def source_card():
    card = partial_card(['fiction-' + str(n) for n in range(1, 8)], 'a' * 64)
    card['direct_verified_fields']['race/start_time'] = '2030-01-15T09:30:00+09:00'
    keys = set(card['direct_verified_fields'])
    registry = set(expected_keys(list(range(1, 8))))
    card.update(verified_registry_keys=sorted(keys), unavailable_registry_keys=sorted(registry-keys),
                registry_verified_count=len(keys), registry_unavailable_count=len(registry-keys))
    return card


def weather_bytes():
    return json.dumps({
        'latitude': 40.8, 'longitude': 140.66, 'timezone': 'Asia/Tokyo',
        'hourly_units': {'time': 'iso8601', 'temperature_2m': '°C',
            'relative_humidity_2m': '%', 'precipitation': 'mm',
            'wind_speed_10m': 'm/s', 'wind_direction_10m': '°'},
        'hourly': {'time': ['2030-01-15T09:00', '2030-01-15T10:00'],
            'temperature_2m': [3, 4], 'relative_humidity_2m': [80, 81],
            'precipitation': [0.5, 0], 'wind_speed_10m': [2.1, 2.4],
            'wind_direction_10m': [280, 285]},
    }, ensure_ascii=False).encode()


class ModelledWeatherConnectionTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec(MODULE))
        return importlib.import_module(MODULE)

    def test_four_required_fields_use_modelled_forecast_not_on_site_claim(self):
        mod = self.module()
        card = source_card()
        original = deepcopy(card)
        enriched = mod.attach_modelled_weather_input(card, weather_bytes(), captured_at=CAPTURE)
        for profile in ('model_A_source_coverage', 'model_B_source_coverage'):
            self.assertEqual(inspect_source_gaps(enriched)[profile]['source_unobserved_required_slots'], 75)
        self.assertEqual(card, original)
        self.assertEqual(len(enriched['modelled_weather_input_evidence']), 5)
        self.assertEqual(enriched['direct_verified_fields']['race/wind_speed'], 2.1)
        self.assertNotIn('race/surface_wetness', enriched['direct_verified_fields'])
        self.assertNotIn('race/track_surface_and_condition', enriched['direct_verified_fields'])
        for evidence in enriched['modelled_weather_input_evidence'].values():
            self.assertEqual(evidence['value_kind'], 'MODELLED_NUMERICAL_GRID_FORECAST_NOT_ON_SITE_MEASUREMENT')
            self.assertFalse(evidence['approved_for_pr71_input'])
            self.assertFalse(evidence['on_site_measurement'])
            self.assertEqual(evidence['original_weather_sha256'], sha256(weather_bytes()).hexdigest())
            self.assertIn('aomorikeirin.com/access/', evidence['coordinate_source_url'])

    def test_wrong_units_or_grid_missing_field_never_becomes_zero(self):
        mod = self.module()
        for mutation in ('units', 'grid', 'missing', 'nan'):
            doc = json.loads(weather_bytes())
            if mutation == 'units':
                doc['hourly_units']['wind_speed_10m'] = 'km/h'
            elif mutation == 'grid':
                doc['latitude'] = 35.6
            elif mutation == 'missing':
                doc['hourly'].pop('precipitation')
            else:
                doc['hourly']['temperature_2m'][0] = float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                mod.attach_modelled_weather_input(source_card(), json.dumps(doc).encode(), captured_at=CAPTURE)

    def test_unknown_venue_and_unapproved_commercial_mode_do_not_fetch(self):
        mod = self.module()
        calls = []
        card = source_card()
        card['race_id'] = '203001152503'
        with self.assertRaises(ValueError):
            mod.collect_modelled_weather(card, owner_noncommercial=True,
                fetch=lambda url: calls.append(url) or weather_bytes(),
                clock=lambda: datetime.fromisoformat(CAPTURE))
        with self.assertRaises(ValueError):
            mod.collect_modelled_weather(source_card(), owner_noncommercial=False,
                fetch=lambda url: calls.append(url) or weather_bytes(),
                clock=lambda: datetime.fromisoformat(CAPTURE))
        self.assertEqual(calls, [])

    def test_slow_get_crossing_cutoff_cannot_reuse_the_earlier_clock(self):
        mod = self.module()
        times = iter([datetime.fromisoformat(CAPTURE),
                      datetime.fromisoformat('2030-01-15T09:26:00+09:00')])
        calls = []
        with self.assertRaises(ValueError):
            mod.collect_modelled_weather(source_card(), owner_noncommercial=True,
                fetch=lambda url: calls.append(url) or weather_bytes(), clock=lambda: next(times))
        self.assertEqual(len(calls), 1)

    def test_already_observed_wind_is_preserved_and_no_rain_to_wetness_guess(self):
        mod = self.module()
        card = source_card()
        card['direct_verified_fields']['race/wind_speed'] = 6
        registry = set(expected_keys(list(range(1, 8))))
        keys = set(card['direct_verified_fields'])
        card.update(verified_registry_keys=sorted(keys), unavailable_registry_keys=sorted(registry-keys),
                    registry_verified_count=len(keys), registry_unavailable_count=len(registry-keys))
        enriched = mod.attach_modelled_weather_input(card, weather_bytes(), captured_at=CAPTURE)
        self.assertEqual(enriched['direct_verified_fields']['race/wind_speed'], 6)
        self.assertNotIn('race/wind_speed', enriched['modelled_weather_input_evidence'])
        self.assertNotIn('race/surface_wetness', enriched['direct_verified_fields'])

    def test_private_input_and_raw_weather_sha_replay_without_public_artifact(self):
        mod = self.module()
        card = source_card()
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'GITHUB_WORKSPACE': ''}):
            one = mod.stage_modelled_weather_input(Path(temp), card, weather_bytes(), captured_at=CAPTURE)
            two = mod.stage_modelled_weather_input(Path(temp), card, weather_bytes(), captured_at=CAPTURE)
            self.assertTrue(one['new_partial_input'])
            self.assertFalse(two['new_partial_input'])
            self.assertEqual(one['weather_required_slots_connected'], 4)
            self.assertFalse(one['production_aes_archived'])
            self.assertFalse(one['live_model_invoked'])
            out = Path(temp) / 'winticket_racecard_partial' / (one['connected_input_sha256'] + '.json')
            self.assertEqual(sha256(out.read_bytes()).hexdigest(), one['connected_input_sha256'])
            self.assertNotIn('fiction-', str(one))
            self.assertFalse((Path(temp) / 'pre').exists())


if __name__ == '__main__':
    unittest.main()
