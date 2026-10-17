import copy
import importlib
import itertools
import math
import unittest
from datetime import timedelta
from tests.test_name_bound_inputs import fixture, sources, NOW
from web.name_bound_inputs import build_name_bound_inputs
from web import race_contract as facts


def packet_fixture():
    race, base, binding = fixture()
    record, original = sources(race, binding)
    packet = build_name_bound_inputs(record, original, race, base, binding,
        parents_read_at=NOW-timedelta(seconds=60), generated_at=NOW-timedelta(seconds=1), now=NOW)
    return race, base, binding, packet


class PredictionTests(unittest.TestCase):
    def setUp(self):
        try: self.c = importlib.import_module('web.name_bound_prediction')
        except ModuleNotFoundError: self.c = None
        self.assertIsNotNone(self.c, 'name-bound pure prediction module required')
        self.race, self.base, self.binding, self.inputs = packet_fixture()

    def build(self, **changes):
        clocks = dict(runner_saved_at=NOW, parents_resolved_at=NOW,
            input_cloud_saved_at=NOW, now=NOW)
        return self.c.build_name_bound_prediction(self.inputs, self.race, self.base, self.binding, **{**clocks, **changes})

    def test_independent_720_complete_orders_match_both_models(self):
        snapshot = self.build()
        base = next(m for m in self.base['snapshot']['models'] if m['model_id'] == snapshot['baseline_link']['model_id'])
        strengths = [row['strength'] for row in base['strengths']]
        rows = self.inputs['original_observation']['boats']
        values = [[r['display_time_s'], *[r['original_times'][k] for k in ('lap_s','turn_s','straight_s')]] for r in rows]
        means = [sum(v[i] for v in values)/6 for i in range(4)]
        for index, model in enumerate(snapshot['models']):
            scores = [math.exp(max(-20,min(20,math.log(strengths[lane])+sum((means[k]-values[lane][k])*coef for k,coef in enumerate((1,.05,.2,.2)) if index or k==0)))) for lane in range(6)]
            outcomes = []
            for order in itertools.permutations(range(6)):
                probability = 1
                for rank, lane in enumerate(order):
                    probability *= scores[lane]/sum(scores[x] for x in order[rank:])
                outcomes.append((order, probability))
            self.assertEqual(len(outcomes),720)
            self.assertEqual(len(model['triples']),120)
            for row in model['triples']:
                prefix = tuple(x-1 for x in row['combination'])
                self.assertAlmostEqual(row['probability'],sum(p for o,p in outcomes if o[:3]==prefix),places=14)
            for row in model['marginals']:
                for rank, label in enumerate(('first','second','third','fourth','fifth','sixth')):
                    self.assertAlmostEqual(row[label+'_probability'],sum(p for o,p in outcomes if o[rank]==row['lane']-1),places=14)
        self.assertNotEqual(snapshot['program_identity_sha256'],snapshot['validation_program_identity_sha256'])
        self.assertEqual(snapshot['boats'][0]['program_name'],'松田大志')
        self.assertEqual(snapshot['boats'][0]['verified_full_name'],'松田 大志郎')
        self.assertEqual(self.c.validate_name_bound_prediction(snapshot,self.inputs,self.race,self.base,self.binding,now=facts._time(self.race['closed_at'])+timedelta(seconds=1)),snapshot)

    def test_strict_replay_rejects_types_fields_hashes_and_clocks(self):
        snapshot=self.build()
        for field,value in [('schema_version',True),('research_only',1),('physical_exhibition_timing_verified',0),('purchase_recommendations',{}),('extra',True),('snapshot_id','0'*64)]:
            bad=copy.deepcopy(snapshot);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.c.validate_name_bound_prediction(bad,self.inputs,self.race,self.base,self.binding,now=NOW)
        for changes in [dict(runner_saved_at=NOW-timedelta(seconds=2)),dict(parents_resolved_at=NOW-timedelta(seconds=1)),dict(input_cloud_saved_at=NOW-timedelta(seconds=1)),dict(now=facts._time(self.race['closed_at']))]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.build(**changes)
        bad=copy.deepcopy(snapshot);bad['models'][0]['triples'][0]['probability']+=.01
        with self.assertRaises(ValueError):self.c.validate_name_bound_prediction(bad,self.inputs,self.race,self.base,self.binding,now=NOW)


if __name__=='__main__':unittest.main()
