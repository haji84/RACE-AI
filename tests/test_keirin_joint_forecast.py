"""Serialization of one coherent law; synthetic riders only."""
from copy import deepcopy
from itertools import permutations
import json
import unittest

from race_ai.keirin_joint_finish import JointFinish
from race_ai import keirin_joint_forecast as wire


def law(n=5):
    cars=list(range(1,n+1))
    orders=list(permutations(cars,3))
    return JointFinish(cars,{order:1/len(orders) for order in orders},tail=(.3,-.1))


def serialize(n=5, **changes):
    meta=dict(race_id='209901016201',generated_at='2099-01-01T10:00:00+09:00',
              cutoff_at='2099-01-01T12:00:00+09:00',source_as_of='2099-01-01T08:00:00+09:00',
              source_forecast_generated_at='2099-01-01T09:00:00+09:00',model_id='comparison-B',
              model_version='synthetic-v1',input_sha256='a'*64,source_packet_sha256='b'*64,
              riders=[dict(car=c,name=f'Synthetic {c}',registration=None) for c in range(1,n+1)])
    meta.update(changes)
    return wire.build_forecast(law(n),**meta)


class JointForecastSerializationTests(unittest.TestCase):
    def test_single_joint_law_yields_all_places_and_both_markets(self):
        record=serialize()
        self.assertEqual(record['schema'],'RACE_AI_KEIRIN_JOINT_FORECAST_V1')
        self.assertEqual(record['scope'],'PROSPECTIVE_RESEARCH')
        self.assertEqual(record['calibration_status'],'UNVALIDATED')
        self.assertEqual(len(record['trifectas']),60)
        self.assertEqual(len(record['exactas']),20)
        wire.validate_forecast(record)
        for rider in record['riders']:
            self.assertAlmostEqual(rider['top2_probability'],.4)
            self.assertAlmostEqual(rider['top3_probability'],.6)
            self.assertEqual(len(rider['rank_probabilities']),5)
        self.assertEqual(json.loads(json.dumps(record)),record)

    def test_public_projection_does_not_reveal_the_full_private_law(self):
        record=serialize()
        projection=wire.public_projection(record)
        self.assertEqual(projection['schema'],'RACE_AI_KEIRIN_JOINT_PROJECTION_V1')
        self.assertNotIn('trifectas',projection)
        self.assertNotIn('exactas',projection)
        self.assertEqual(len(projection['ranked_markets']['3t']),8)
        self.assertEqual(len(projection['ranked_markets']['2t']),4)
        self.assertLess(sum(x['probability'] for x in projection['ranked_markets']['3t']),.14)
        self.assertRegex(projection['source_joint_sha256'],r'^[0-9a-f]{64}$')
        self.assertEqual(projection['riders'],record['riders'])

    def test_race_source_and_time_do_not_silently_become_an_original(self):
        retro=serialize(generated_at='2099-01-01T13:00:00+09:00')
        self.assertEqual(retro['scope'],'RETROSPECTIVE_RESEARCH')
        for changed in (dict(source_as_of='2099-01-02T00:00:00Z'),dict(input_sha256='bad'),
                        dict(race_id='bad'),dict(generated_at='2099-01-01T10:00:00'),
                        dict(source_forecast_generated_at='2099-01-02T00:00:00Z')):
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                serialize(**changed)

    def test_a_complete_field_and_unique_official_identity_are_required(self):
        for riders in ([dict(car=1,name='Synthetic')],
                       [dict(car=c,name=f'Synthetic {c}',registration='015444') for c in range(1,6)]):
            with self.subTest(riders=riders),self.assertRaises(ValueError):
                serialize(riders=riders)

    def test_payload_mutations_cannot_break_joint_consistency_or_probability_bounds(self):
        original=serialize()
        for mutate in (lambda r:r['exactas'][0].update(probability=.99),
                       lambda r:r['riders'][0]['rank_probabilities'].__setitem__(0,.9),
                       lambda r:r['riders'][0].update(top3_probability=.99),
                       lambda r:r['trifectas'].pop(),
                       lambda r:r['riders'][0]['rank_probabilities'].__setitem__(3,float('nan'))):
            row=deepcopy(original);mutate(row)
            with self.assertRaises(ValueError):wire.validate_forecast(row)
            with self.assertRaises(ValueError):wire.public_projection(row)

    def test_nine_car_payload_preserves_all_rank_column_sums(self):
        record=serialize(9)
        wire.validate_forecast(record)
        self.assertEqual(len(record['trifectas']),504)
        for rank in range(9):
            self.assertAlmostEqual(sum(r['rank_probabilities'][rank] for r in record['riders']),1.)

    def test_public_projection_never_copies_private_extensions(self):
        record=serialize()
        record['private_source']={'secret':'top-level-canary'}
        record['riders'][0]['private_history']='rider-canary'
        before=deepcopy(record)
        projected=wire.public_projection(record)
        self.assertNotIn('private_source',projected)
        self.assertNotIn('private_history',projected['riders'][0])
        self.assertNotIn('canary',str(projected))
        self.assertEqual(record,before)


if __name__=='__main__':unittest.main()
