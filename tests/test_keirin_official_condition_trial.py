"""Synthetic checks for the paired model. Real races are scored after settlement."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_dossier_conditions as dossier
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_official_condition_trial as trial
from race_ai import keirin_official_nationwide_records as records
from tests.test_keirin_nationwide_auto_generator import AT, ASOF, fixture


class ConditionTrialTests(unittest.TestCase):
    def inputs(self, *, depth=12, published_at=ASOF):
        snapshot = fixture()
        snapshot['round_stage'] = 'A級予選'
        baseline = model.generate_A_B(snapshot, generated_at=AT)
        race_id = snapshot['race_id']
        condition = dict(race_id=race_id, meeting_grade='F1', round_stage='PRELIMINARY',
                         round_label='A級予選', list_sha256='b' * 64, source_at=ASOF)
        observations = []
        for n in range(min(depth, 12)):
            observations.append((snapshot['riders'][0]['athlete_id'], 'F1', 'PRELIMINARY',
                                 1 if n < 4 else 4))
        part = dossier.result_slice('2026-11-17', '1' * 64, observations)
        card = dossier.build_day(day='2026-11-18', published_at=model.when(published_at), registered_races=1,
                                 calendar_sha256='f' * 64, races={race_id: condition}, past_results=[part])
        frozen = trial.HistoryPacket.read('e' * 40, json.dumps(card).encode())
        names = [dict(car=r['car'], name=f'試験選手{r["car"]}', registration=r['athlete_id'])
                 for r in snapshot['riders']]
        return snapshot, baseline, condition, names, frozen

    def test_bound_condition_changes_joint_and_keeps_baseline_frozen(self):
        inputs = self.inputs()
        previous = deepcopy(inputs[1])
        pair = trial.build_pair(*inputs)
        self.assertEqual(inputs[1], previous)
        self.assertEqual(pair['baseline_prediction_sha256'], previous['prediction_sha256'])
        self.assertEqual(pair['historical_packet_sha256'], inputs[-1].sha256)
        self.assertEqual(pair['historical_release'], 'e' * 40)
        self.assertEqual(pair['covered_riders'], 1)
        self.assertEqual(pair, trial.build_pair(*inputs))
        for market in ('trifectas', 'exactas'):
            self.assertNotEqual(pair['baseline'][market], pair['challenger'][market])
            for arm in ('baseline', 'challenger'):
                self.assertAlmostEqual(sum(row['probability'] for row in pair[arm][market]), 1)
                self.assertTrue(all(row['probability'] > 0 for row in pair[arm][market]))

    def test_hold_when_support_or_publication_is_late(self):
        self.assertIsNone(trial.build_pair(*self.inputs(depth=9)))
        self.assertIsNone(trial.build_pair(*self.inputs(published_at='2026-11-18T09:02:00+09:00')))

    def test_source_grade_and_registration_must_reconcile(self):
        snapshot, baseline, condition, names, source = self.inputs()
        wrong_grade = dict(condition, meeting_grade='F2')
        self.assertIsNone(trial.build_pair(snapshot, baseline, wrong_grade, names, source))
        names[0]['registration'] = '999999'
        with self.assertRaisesRegex(ValueError, 'ROSTER'):
            trial.build_pair(snapshot, baseline, condition, names, source)

    def test_same_original_requires_two_matching_pre_cutoff_receipts(self):
        snapshot, baseline, condition, names, source = self.inputs()
        pair = trial.build_pair(snapshot, baseline, condition, names, source)
        race_id = pair['race_id']
        meta = dict(evidence_sha256='a' * 64, cipher_sha256='b' * 64,
                    baseline_cipher_sha256='c' * 64, observed_at='2026-11-18T09:02:00+09:00')
        row = dict(race_id=race_id, condition_trial_sha256=model.digest(pair), evidence_sha256='a' * 64,
                   evidence_cipher_sha256='b' * 64, cipher_sha256='c' * 64)
        reader = SimpleNamespace(index={'originals':{race_id: meta}}, read_cipher=lambda _: b'checked')
        checked = records.verify_condition_trial_cipher(row, reader)
        with self.assertRaisesRegex(ValueError, 'CIPHER_BINDING'):
            records.verify_condition_trial_cipher(dict(row, evidence_cipher_sha256='d' * 64), reader)
        packet = dict(condition_trial=pair, race_id=race_id, baseline=baseline, snapshot=snapshot,
                      baseline_arguments={'card_arguments':{}})
        result = dict(original_evidence_sha256='a' * 64, origin_packets={'producer':1,'readback':2})
        reader.read = lambda which, _: packet if which is meta else result
        official = {'latest_server_evidence_at':'2026-11-18T09:04:00+09:00'}
        packets = [{'report':{'new_encrypted_originals':[row]}},
                   {'report':{'records':[dict(checked, race_id=race_id)]}}]
        with (patch.object(records, 'archived_original', return_value=(b'checked', None)),
              patch.object(records, 'verify_origins', return_value=(official, None)),
              patch.object(records.origin, '_bundle', side_effect=packets),
              patch.object(trial, 'build_from_official_card', return_value=pair)):
            self.assertEqual(records.admit_saved_pair(reader, meta, object(), b'private key',
                history_cache={source.commit:source})[0], pair)
        with (patch.object(records, 'archived_original', return_value=(b'checked', None)),
              patch.object(records, 'verify_origins', return_value=({'latest_server_evidence_at':
                           '2026-11-18T11:45:01+09:00'}, None))):
            with self.assertRaisesRegex(ValueError, 'CONDITION_TRIAL_T15'):
                records.admit_saved_pair(reader, meta, object(), b'private key', history_cache={})


if __name__ == '__main__':
    unittest.main()
