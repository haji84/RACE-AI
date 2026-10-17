"""Immutable cross-platform receipt replay, without source/network I/O."""
import copy
import json
import math
import platform
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from web import name_bound_prediction as prediction, race_contract as facts
from tests.test_name_bound_prediction import packet_fixture, NOW


class PlatformReplayTests(unittest.TestCase):
    @staticmethod
    def source_snapshot(neighbors):
        race, base, binding, inputs = packet_fixture()
        original_exp = math.exp
        def foreign_exp(value):
            result = original_exp(value)
            for _ in range(abs(neighbors)):
                result = math.nextafter(result, math.inf if neighbors > 0 else -math.inf)
            return result
        # Simulate only the external libm boundary; all packet construction and
        # validation remain the actual production code with real inputs.
        with patch.object(prediction.math, 'exp', foreign_exp):
            snapshot = prediction.build_name_bound_prediction(inputs, race, base, binding,
                runner_saved_at=NOW, parents_resolved_at=NOW, input_cloud_saved_at=NOW, now=NOW)
        return race, base, binding, inputs, snapshot

    @staticmethod
    def validate(parts):
        race, base, binding, inputs, snapshot = parts
        return prediction.validate_name_bound_prediction(snapshot, inputs, race, base, binding, now=NOW)

    def test_one_adjacent_libm_value_keeps_entire_source_snapshot(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                parts = self.source_snapshot(direction)
                original = facts.canonical(parts[-1])
                try:
                    checked = self.validate(parts)
                except ValueError as error:
                    self.fail('Internally consistent adjacent-libm snapshot was rejected: ' + str(error))
                self.assertEqual(facts.canonical(checked), original)
                checked['boats'][0]['original_times']['lap_s'] = 999
                self.assertEqual(facts.canonical(parts[-1]), original, 'returned snapshot must not alias immutable source')

    def test_two_adjacent_libm_steps_are_rejected(self):
        for direction in (-2, 2):
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                self.validate(self.source_snapshot(direction))

    def test_adjacent_probability_tamper_is_not_a_replay_allowance(self):
        parts = list(self.source_snapshot(1));bad = copy.deepcopy(parts[-1])
        bad['models'][1]['triples'][0]['probability'] = math.nextafter(
            bad['models'][1]['triples'][0]['probability'], math.inf)
        bad.pop('snapshot_id');bad['snapshot_id'] = prediction.digest(bad);parts[-1] = bad
        with self.assertRaises(ValueError):self.validate(parts)

    def test_strength_types_nonfinite_values_and_lane_swaps_are_rejected(self):
        good = self.source_snapshot(1)
        for value in (True, 1, '1.0', None, 0.0, -1.0, float('nan'), float('inf'), -float('inf')):
            parts = list(copy.deepcopy(good))
            parts[-1]['boats'][0]['original_adjusted_strength'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):self.validate(parts)
        parts = list(copy.deepcopy(good))
        parts[-1]['boats'][0], parts[-1]['boats'][1] = parts[-1]['boats'][1], parts[-1]['boats'][0]
        with self.assertRaises(ValueError):self.validate(parts)

    def test_delta_and_self_hash_tampering_are_rejected(self):
        for field in ('delta', 'snapshot_id'):
            parts = list(self.source_snapshot(1));bad = copy.deepcopy(parts[-1]);parts[-1] = bad
            if field == 'delta':
                item = bad['deltas'][0]['triples'][0]
                key = next(k for k, v in item.items() if type(v) is float)
                item[key] = math.nextafter(item[key], math.inf)
                bad.pop('snapshot_id');bad['snapshot_id'] = prediction.digest(bad)
            else:bad['snapshot_id'] = '0'*64
            with self.subTest(field=field), self.assertRaises(ValueError):self.validate(parts)

    def test_invalid_parent_never_enters_strength_replay(self):
        parts = list(self.source_snapshot(1))
        parts[2] = copy.deepcopy(parts[2]);parts[2]['receipt']['request_id'] = '999999-1'
        with self.assertRaises(ValueError):self.validate(parts)

    def test_adjacent_packet_still_rejects_identity_hash_and_clock_tamper(self):
        good = self.source_snapshot(1)
        mutations = [lambda s:s['boats'][0].update(program_name='OTHER'),
            lambda s:s.update(physical_exhibition_timing_verified=True),
            lambda s:s['input_link'].update(sha256='0'*64),
            lambda s:s.update(generated_at=facts.stamp(NOW+timedelta(seconds=1)))]
        for change in mutations:
            parts = list(copy.deepcopy(good));bad = parts[-1];change(bad)
            bad.pop('snapshot_id');bad['snapshot_id'] = prediction.digest(bad)
            with self.subTest(change=change), self.assertRaises(ValueError):self.validate(parts)

    def test_live_linux_receipt_is_portably_read_without_mutating_its_hash(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/name_bound_shimonoseki12_platform.json').read_bytes())
        envelope = fixture['envelope'];race = fixture['program'];snapshot = envelope['receipt']['snapshot']
        source = facts.canonical(envelope)
        self.assertEqual(len(source), 113946)
        self.assertEqual(prediction.digest(envelope), '5d8508da5ae2fa73bd1acf68e45968d61151e3e04a0111f7956367df824156eb')
        clock = datetime.fromisoformat(envelope['finalization']['receipt_confirmed_at'])+timedelta(seconds=1)
        local = prediction.build_name_bound_prediction(envelope['inputs'], race, envelope['baseline'], envelope['name_binding'],
            runner_saved_at=snapshot['input_link']['runner_saved_at'], parents_resolved_at=snapshot['parents_resolved_at'],
            input_cloud_saved_at=snapshot['input_link']['input_cloud_saved_at'], now=datetime.fromisoformat(snapshot['generated_at']))
        print('PLATFORM_REPLAY_EVIDENCE ' + json.dumps({'system':platform.system(),
            'strict_local_rebuild_matches':facts.canonical(local)==facts.canonical(snapshot),
            'source_strength_hex':snapshot['boats'][2]['original_adjusted_strength'].hex(),
            'local_strength_hex':local['boats'][2]['original_adjusted_strength'].hex()}))
        try:checked = prediction.validate_name_bound_envelope(envelope, race, now=clock)
        except ValueError as error:self.fail('Actual Linux-saved receipt failed portable read: '+str(error))
        self.assertEqual(facts.canonical(checked), source)


if __name__ == '__main__':unittest.main()
