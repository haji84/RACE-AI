"""Original four algorithms; invented evidence, never this weekend's picks."""
import copy
import importlib.util
import unittest
from race_ai.horse_history_features import (
    derive, fit_reference, build_snapshot, run_existing_four, summarize_suite,
    ENVIRONMENT, MODEL_IDS, digest,
)
from test_horse_history_features import row, refs, target, AT

AVAILABLE=importlib.util.find_spec('race_ai.four_sport_model_suite') is not None

@unittest.skipUnless(AVAILABLE,'Native repository suite is not present in the isolated local workspace')
class HorseHistoryNativeIntegration(unittest.TestCase):
    def make_snapshot(self):
        ref=fit_reference(refs(),fitted_at='2029-12-01T00:00:00+09:00',
            data_captured_at='2029-11-30T00:00:00+09:00',scope='SYNTHETIC_ONLY')
        entrants=[]
        for i in range(1,5):
            hid=f'H{i}'
            rows=[row(1,horse_id=hid,finish_position=i),
                  row(2,horse_id=hid,first_corner_position=9,finish_position=i+1)]
            report=derive(rows,target(horse_id=hid),as_of=AT,reference=ref,scope='SYNTHETIC_ONLY')
            entrants.append({'horse_id':hid,'number':i,'draw':i,'style':'unknown','report':report})
        race={'race_id':'synthetic-horse-history-20301002','sport':'horse','venue':'Tokyo',
              'event_date_jst':'2030-10-02','sales_cutoff_at':'2030-10-02T15:00:00+09:00',
              'distance_m':1400,'surface':'turf','race_kind':'fictional-flat','race_revision':1,'discipline':'flat'}
        values={'wind_mps':5,'rain_mm_h':0,'humidity_pct':50,'air_temp_c':20,
                'surface_wetness':.1,'going_wetness':.1,'course_cushion':.5,'rail_position':.2,'pace_pressure':.4}
        env={k:{'value':values[k],'published_at':AT,'captured_at':AT,'source_ref':'fixture://environment',
                'source_rights_ref':'fixture-only','sample_n':1,'transform_id':'fictional-test-v1'} for k in ENVIRONMENT}
        return build_snapshot(race,entrants,env,as_of=AT,scope='SYNTHETIC_ONLY')

    def test_raw_history_to_all_four_original_models_and_score_marginals(self):
        snapshot=self.make_snapshot(); before=copy.deepcopy(snapshot)
        result=run_existing_four(snapshot)
        self.assertEqual(snapshot,before)
        self.assertEqual(tuple(result['native_suite']['models']),MODEL_IDS)
        for model,summary in result['summary']['models'].items():
            self.assertEqual(summary['ordered_top8'],result['native_suite']['models'][model]['ordered_top8'])
            self.assertEqual(len(summary['ordered_top8']),8)
            self.assertAlmostEqual(sum(summary['win_score_by_horse'].values()),1)
            self.assertAlmostEqual(sum(summary['top3_score_by_horse'].values()),3)
            self.assertIsNone(summary['calibrated_win_probability'])
        self.assertIsNone(result['summary']['confidence'])
        self.assertIsNone(result['summary']['expected_value'])

    def test_research_source_authorization_is_not_silently_bypassed(self):
        snapshot=self.make_snapshot();snapshot['scope']='OPERATOR_SUPPLIED_RESEARCH'
        with self.assertRaisesRegex(ValueError,'rights|authoriz|admitted'):
            run_existing_four(snapshot)

    def test_wrong_original_hash_cannot_be_reported(self):
        out=run_existing_four(self.make_snapshot())['native_suite']
        out['models'][MODEL_IDS[0]]['ordered_top8'][0]=[4,3,2]
        with self.assertRaisesRegex(ValueError,'hash'):
            summarize_suite(out)

    def test_dirt_cushion_is_not_fabricated(self):
        s=self.make_snapshot();r=s['race'];r['surface']='dirt';r['discipline']='flat'
        with self.assertRaisesRegex(ValueError,'cushion'):
            build_snapshot(r,[],s['environment'],as_of=AT)
