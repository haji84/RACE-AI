"""Synthetic tests are contract checks, not real-race accuracy proof."""
import copy
import json
import unittest
import numpy as np
from research.chatgpt_dt_r1.abilities import (augment_abilities,discover_features,phase_state_features,
    favorite_failure,reviewed_motion_record,split_sidecars,ABILITY_NAMES,DISC_NAMES,MOTION_SCHEMA)
from research.chatgpt_dt_r1.features import build_features
from research.chatgpt_dt_r1.agari import augment_agari
from research.chatgpt_dt_r1.context import augment_features
from research.chatgpt_dt_r1.model import RankModel,fit_ranker,digest
from research.chatgpt_dt_r1.test_agari import records,CLOCK,venue
from research.chatgpt_dt_r1.phases import _state_row

def extended(rows,sidecars=()):
    features=build_features(rows)
    return augment_abilities(augment_agari(augment_features(features,venue_store=venue(),
        timing_records=sidecars,as_of=CLOCK)))[-1]

def val(row,name):
    return row['features'][:,row['feature_names'].index(name)]


def motion_fixture(**overrides):
    measurements={'measured_motion_segments':2,'measured_speed_uncertainty_m_s':.1,
        'measured_speed_mean_m_s':15.,'measured_speed_max_m_s':17.,
        'measured_acceleration_mean_m_s2':1.,'measured_acceleration_uncertainty_m_s2':.2}
    provenance={'kind':'reviewed_video','source_url':'urn:synthetic:motion','source_sha256':'a'*64,
        'retrieved_at':'2026-07-02T00:00:00Z','reviewer_id':'synthetic-review',
        'reviewed_at':'2026-07-02T01:00:00Z','available_at':'2026-07-02T01:00:00Z'}
    args=dict(race_id='old',rider_id='1',registration_id='1',venue_id='v',
        event_at='2026-07-01T05:00:00Z',event_day='2026-07-01',provenance=provenance,
        identity_receipt_sha256='b'*64,measurement_receipt_sha256='c'*64)
    measurements=overrides.pop('measurements',measurements)
    return reviewed_motion_record(measurements,**dict(args,**overrides))


class AbilityTests(unittest.TestCase):
    def test_extra_cannot_bypass_calibrated_metric_quality_checks(self):
        measurements={'measured_motion_segments':2,'measured_speed_uncertainty_m_s':.1,
            'measured_speed_mean_m_s':15.,'measured_speed_max_m_s':17.}
        with self.assertRaisesRegex(ValueError,'MOTION_METRIC_REQUIRES_MEASUREMENT'):
            motion_fixture(measurements=measurements,extra={'mean_acceleration_m_s2':10.})

    def test_serialized_measurements_keep_quality_evidence_and_reject_invalid_reload(self):
        record=motion_fixture(extra={'attack_count':2})
        expected={'measured_motion_segments':2,'measured_speed_uncertainty_m_s':.1,
            'measured_speed_mean_m_s':15.,'measured_speed_max_m_s':17.,
            'measured_acceleration_mean_m_s2':1.,'measured_acceleration_uncertainty_m_s2':.2}
        self.assertEqual(record.get('measurement_evidence'),expected)
        self.assertEqual(split_sidecars(json.loads(json.dumps([record])))[1],[record])
        changes=(('measured_motion_segments',0),('measured_speed_uncertainty_m_s',6.),
                 ('measured_acceleration_uncertainty_m_s2',6.),('measured_speed_max_m_s',14.))
        for field,value in changes:
            with self.subTest(field=field):
                bad=copy.deepcopy(record);bad['measurement_evidence'][field]=value
                bad['observation_id']=digest({k:v for k,v in bad.items() if k!='observation_id'})
                with self.assertRaises(ValueError):split_sidecars([bad])
        bad=copy.deepcopy(record);bad['metrics']['mean_acceleration_m_s2']=10.
        bad['observation_id']=digest({k:v for k,v in bad.items() if k!='observation_id'})
        with self.assertRaisesRegex(ValueError,'MOTION_MEASUREMENT_MISMATCH'):split_sidecars([bad])

    def test_legacy_motion_without_quality_evidence_requires_review(self):
        legacy=motion_fixture()
        legacy.pop('measurement_evidence',None)
        legacy['schema']='dt-reviewed-motion-v1'
        legacy['observation_id']=digest({k:v for k,v in legacy.items() if k!='observation_id'})
        with self.assertRaisesRegex(ValueError,'LEGACY_MOTION_REVIEW_REQUIRED'):split_sidecars([legacy])

    def test_unadmitted_motion_does_not_change_features_or_binding(self):
        rows=records()
        for row in rows:
            for rider in row['riders']:rider['official_registration_id']=str(rider['car'])
        baseline=extended(rows)
        for record in (motion_fixture(rider_id='9',registration_id='9'),
                       motion_fixture(registration_id='9')):
            with self.subTest(rider=record['rider_id'],registration=record['registration_id']):
                actual=extended(rows,[record])
                np.testing.assert_array_equal(actual['features'],baseline['features'])
                self.assertEqual(actual['feature_input_sha256'],baseline['feature_input_sha256'])

    def test_reviewed_motion_only_and_clock(self):
        rows=records()
        for row in rows:
            for rider in row['riders']:rider['official_registration_id']=str(rider['car'])
        p={'kind':'reviewed_video','source_url':'urn:synthetic:motion','source_sha256':'a'*64,
           'retrieved_at':'2026-07-02T00:00:00Z','reviewer_id':'synthetic-review',
           'reviewed_at':'2026-07-02T01:00:00Z','available_at':'2026-07-02T01:00:00Z'}
        args=dict(race_id='old',rider_id=rows[-1]['riders'][0]['identity_key'],registration_id='1',
            venue_id='v',event_at='2026-07-01T05:00:00Z',event_day='2026-07-01',
            provenance=p,identity_receipt_sha256='b'*64,measurement_receipt_sha256='c'*64)
        m={'measured_motion_segments':2,'measured_speed_uncertainty_m_s':.1,
            'measured_speed_mean_m_s':15.,'measured_speed_max_m_s':17.}
        rec=reviewed_motion_record(m,**args)
        row=extended(rows,[rec])
        self.assertAlmostEqual(val(row,'history_dt_motion_venue_mean_speed_m_s_mean')[0],.75)
        self.assertEqual(val(row,'history_dt_motion_venue_mean_speed_m_s_missing')[1],1.)
        tampered=copy.deepcopy(rec);tampered['metrics']['mean_speed_m_s']=30.
        with self.assertRaises(ValueError):split_sidecars([tampered])
        with self.assertRaises(ValueError):split_sidecars([rec,rec])
        with self.assertRaises(ValueError):reviewed_motion_record({'measured_motion_segments':0},**args)
        p2=dict(p,retrieved_at='2026-07-13T00:00:00Z',reviewed_at='2026-07-13T01:00:00Z',available_at='2026-07-13T01:00:00Z')
        late=reviewed_motion_record(m,**dict(args,provenance=p2))
        self.assertEqual(val(extended(rows,[late]),'history_dt_motion_venue_mean_speed_m_s_missing')[0],1.)
    def test_pressure_and_dynamic_state_have_no_future_input(self):
        rows=records()
        rows[-1]['line_groups']=[[1],[2],[3]]
        for o in rows[0]['result_rows']:o['sb_mark']='B'
        row=extended(rows)
        np.testing.assert_allclose(val(row,'history_dt_rival_pressure'),[2,2,2])
        self.assertTrue(np.all(val(row,'history_dt_third_line_opportunity')>0))
        state=phase_state_features(row,[[1,2,3],[2,1,3]])
        self.assertGreater(state[0,0],0.);self.assertGreater(state[1,1],0.)
        self.assertTrue(np.all(phase_state_features(row,[])==0))
        s=_state_row(row,[2,1,3],'sampled_predictive_state',past_orders=[[1,2,3],[2,1,3]])
        self.assertEqual(s['features'].shape[1],len(row['feature_names'])+2+7)
        rows[-1]['result_rows']=[{'car':3,'rank':1,'half_lap_seconds':1.}]
        self.assertEqual(extended(rows)['feature_input_sha256'],row['feature_input_sha256'])
    def test_discovery_boundary_and_learned_model(self):
        fit=[]
        for i in range(36):
            pair=records()
            pair[-1]['day']='2026-07-10' if i<18 else '2026-07-11'
            pair[-1]['race_id']=f'target{i}'
            pair[0]['race_id']=f'old{i}'
            winner=1+i%3
            for o in pair[0]['result_rows']:o['half_lap_seconds']=10.+(o['car']!=winner)*3.
            order=[winner]+[c for c in (1,2,3) if c!=winner]
            pair[-1].update(top3=order,finish=order)
            fit.append(extended(pair))
        discovery=discover_features(fit,before='2026-07-12',min_races=2)
        self.assertTrue(discovery['selected'])
        self.assertTrue(set(discovery['selected'])<=set(DISC_NAMES))
        self.assertLessEqual(len(discovery['selected']),12)
        with self.assertRaisesRegex(ValueError,'BOUNDARY'):discover_features(fit,before='2026-07-11',min_races=2)
        model=fit_ranker(fit,before='2026-07-12',max_iter=12)
        self.assertTrue(any(abs(model.weights[:,model.feature_names.index(n)]).max()>0 for n in ABILITY_NAMES))
        report=favorite_failure(model,fit[0])
        self.assertAlmostEqual(report['favorite_loss_probability']+report['favorite_win_probability'],1.)
        self.assertEqual(report['status'],'MODEL_SENSITIVITY_NOT_CAUSAL')
        self.assertTrue(report['weight_group_sensitivity'])
    def test_legacy_input_and_missing_motion(self):
        row=extended(records())
        self.assertEqual(val(row,'history_dt_motion_overall_mean_speed_m_s_missing').tolist(),[1.,1.,1.])
        self.assertEqual(len(row['feature_names']),315+len(ABILITY_NAMES))
        with self.assertRaisesRegex(ValueError,'ALREADY_ATTACHED'):augment_abilities([row])

if __name__=='__main__':unittest.main()
