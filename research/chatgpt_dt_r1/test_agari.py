"""Synthetic feature, chronology, missingness and actual ranker-fit contracts."""
import copy
import unittest
import numpy as np
from research.chatgpt_dt_r1.features import build_features
from research.chatgpt_dt_r1.context import augment_features
from research.chatgpt_dt_r1.agari import augment_agari, AGARI_NAMES
from research.chatgpt_dt_r1.model import RankModel, fit_ranker
from research.chatgpt_dt_r1.venues import VenueStore
from research.chatgpt_dt_r1.test_context import card

CLOCK = '2026-07-12T00:00:00Z'

def records():
    target = card()
    target.update(lines_known=True, line_groups=[[1,2],[3]], lines_applicable=True)
    previous = copy.deepcopy(target)
    previous.update(race_id='old', day='2026-07-01', result_rows=[
        {'car':1,'rank':1,'half_lap_seconds':10.,'final_lap_seconds':24.},
        {'car':2,'rank':2,'half_lap_seconds':12.},
        {'car':3,'rank':3,'half_lap_seconds':14.}])
    return [previous, target]

def venue():
    return VenueStore.from_records([{'venue_code':'v','name':'Synthetic',
        'source_url':'https://example.test/venue','source_sha256':'b'*64,
        'retrieved_at':'2026-07-01T00:00:00Z','geometry_scope':'dated','effective_from':'2026-01-01',
        'circumference_m':400.,'straight_m':60.,'cant_deg':30.}])

def row_for(rows, context=True):
    row = build_features(rows)[-1]
    if context:
        row = augment_features([row], venue_store=venue(), as_of=CLOCK)[0]
    return augment_agari([row])[0]

def feature(row,key):
    return row['features'][:,row['feature_names'].index(key)]

class AgariTests(unittest.TestCase):
    def test_bank_style_line_and_weather_products(self):
        rows=records()
        rows[-1]['weather_observation']={'kind':'forecast','source_sha256':'c'*64,
            'issued_at':'2026-07-09T00:00:00Z','available_at':'2026-07-09T00:00:00Z','wind_speed_m_s':5.}
        r=row_for(rows)
        self.assertEqual(len(r['feature_names']),224+len(AGARI_NAMES))
        np.testing.assert_allclose(feature(r,'history_agari_venue_relative'),[.1,0.,-.1],atol=1e-12)
        np.testing.assert_allclose(feature(r,'history_agari_venue_relative_x_role_leader'),[.1,0.,0.],atol=1e-12)
        np.testing.assert_allclose(feature(r,'history_agari_venue_relative_x_role_solo'),[0.,0.,-.1],atol=1e-12)
        self.assertAlmostEqual(feature(r,'history_agari_context_venue_relative_x_bank_straight_m_x_style_nige')[0],.06)
        self.assertAlmostEqual(feature(r,'history_agari_context_venue_relative_x_weather_wind_speed_m_s_x_role_leader')[0],.05)
        self.assertAlmostEqual(feature(r,'history_agari_context_venue_relative_x_weather_back_headwind')[0],0.)
    def test_future_weather_target_agari_and_full_lap_do_not_leak(self):
        rows=records()
        a=row_for(rows)
        rows[-1]['result_rows']=[{'car':1,'rank':1,'half_lap_seconds':1.}]
        rows[0]['result_rows'][0]['final_lap_seconds']=99.
        rows[-1]['weather_observation']={'kind':'forecast','source_sha256':'c'*64,'issued_at':CLOCK,'available_at':CLOCK,'wind_speed_m_s':20.}
        b=row_for(rows)
        np.testing.assert_array_equal(a['features'],b['features'])
        self.assertEqual(a['feature_input_sha256'],b['feature_input_sha256'])
    def test_no_context_and_missing_same_venue(self):
        rows=records(); rows[0]['venue_code']='other'
        r=row_for(rows,False)
        self.assertEqual(len(r['feature_names']),106+len(AGARI_NAMES))
        self.assertAlmostEqual(feature(r,'history_agari_overall_relative')[0],.1)
        self.assertFalse(np.any(feature(r,'history_agari_venue_relative')))
        self.assertFalse(np.any(feature(r,'history_agari_context_venue_relative_x_bank_straight_m')))
        self.assertFalse(np.any(feature(r,'history_agari_venue_relative_available')))
        with self.assertRaisesRegex(ValueError,'ALREADY_ATTACHED'):
            augment_agari([r])
    def test_training_uses_real_matrix_columns_and_legacy_schema_unchanged(self):
        rows=records(); original=build_features(rows)[-1]
        r=row_for(rows,False)
        self.assertEqual(tuple(r['feature_names'][:106]),tuple(original['feature_names']))
        self.assertEqual(len(original['feature_names']),106)
        # Fit actual ranking coefficients against varied synthetic agari signals;
        # this is a smoke test, not evidence of race accuracy.
        fit=[]
        for i in range(30):
            pair=records()
            pair[0]['race_id']=f'old{i}'
            pair[1]['race_id']=f'target{i}'
            winner=1+(i%3)
            for o in pair[0]['result_rows']:
                o['half_lap_seconds']=10.+(o['car']!=winner)*2.
            order=[winner]+[c for c in (1,2,3) if c!=winner]
            pair[1].update(top3=order,finish=order)
            fit.append(row_for(pair,False))
        ranker=fit_ranker(fit,before='2026-07-11',max_iter=12)
        ix=ranker.feature_names.index('history_agari_venue_relative')
        self.assertTrue(np.any(np.abs(ranker.weights[:,ix])>1e-8))
        frozen=RankModel.from_dict(ranker.to_dict())
        self.assertEqual(frozen.distribution(fit[0]),ranker.distribution(fit[0]))

if __name__=='__main__':unittest.main()
