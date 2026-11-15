"""Synthetic contracts only: never use real private predictions as fixtures."""
import copy
import hashlib
import itertools
import json
import unittest
from race_ai.boat_shadow_result_audit import compare_frozen_current_shadows

A='boat-display-rating-PL-reference-v1-UNVALIDATED'
B='boat-course-motor-shadow-v0.1-UNTRAINED'
C='boat-local-start-course-shadow-v0.1-UNTRAINED'
SAVED='2026-11-03T06:00:01Z'

def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def seal(obj,key):
    obj[key]=digest({k:v for k,v in obj.items() if k!=key})
    return obj

def fixture():
    rows=[{'ticket':'-'.join(map(str,t)),'score':1/120} for t in itertools.permutations(range(1,7),3)]
    rows.sort(key=lambda x:x['ticket'])
    models=[seal({'model_id':m,'trained':False,'calibrated':False,'odds_independent':True,'purchase_decision':'NO_BET','full_120':copy.deepcopy(rows),'top8':copy.deepcopy(rows[:8])},'model_sha256') for m in (A,B)]
    pair=seal({'schema':'RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1','race_id':'20261103-04-11','cutoff_at':'2026-11-03T15:10:00+09:00','generated_at':'2026-11-03T06:00:00.200000Z','source_captured_at':'2026-11-03T06:00:00Z','source_sha256':'a'*64,'actual_result_at_forecast_time':None,'models':models},'bundle_sha256')
    shadow=seal({'schema':'RACE_AI_BOAT_CURRENT_FEATURE_SHADOW_V1','model_id':C,'race_id':pair['race_id'],'cutoff_at':pair['cutoff_at'],'as_of':'2026-11-03T06:00:00.900000Z','source_snapshot_sha256':pair['source_sha256'],'extra_source_sha256':'b'*64,'full_120':copy.deepcopy(rows),'top8':copy.deepcopy(rows[:8]),'untrained':True,'calibrated':False,'odds_used':False,'auto_promoted':False,'betting_decision':'NO_BET'},'bundle_sha256')
    frozen={'schema':'RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1','paired_forecasts':[pair],'additional_official_feature_shadows':[shadow]}
    result={'race_id':pair['race_id'],'state':'INDEPENDENT_AB_RESULT_VERIFIED','official_top3':'1-2-3','payout_per_100_yen':1000,'result_captured_at':'2026-11-03T06:20:00Z','paired_comparison':{'pair_bundle_sha256':pair['bundle_sha256'],'forecast_server_saved_at':SAVED,'race_id':pair['race_id'],'cutoff_at':pair['cutoff_at'],'official_top3':'1-2-3'}}
    return frozen,{'official_results':[result]}

class FrozenShadowTests(unittest.TestCase):
    def test_same_original_scored_without_mutation(self):
        f,a=fixture(); before=copy.deepcopy((f,a)); got=compare_frozen_current_shadows(f,a,SAVED)
        row=got['comparisons'][0]; self.assertEqual(row['state'],'ABC_SAME_FROZEN_INPUT_SCORED')
        self.assertEqual([m['hit_at_8'] for m in row['models']],[1,1,1]); self.assertEqual(row['models'][2]['virtual_payout_yen'],1000)
        self.assertEqual((f,a),before); self.assertFalse(got['auto_promoted']); self.assertIsNone(got['all_national_hit8'])
    def test_missing_c_not_zero_hit(self):
        f,a=fixture(); f['additional_official_feature_shadows']=[]
        row=compare_frozen_current_shadows(f,a,SAVED)['comparisons'][0]
        self.assertEqual(row['state'],'C_LITE_NOT_FROZEN'); self.assertNotIn('models',row)
    def test_pending_not_scored(self):
        f,a=fixture(); a['official_results'][0]={'race_id':f['paired_forecasts'][0]['race_id'],'state':'OFFICIAL_RESULT_NOT_FINAL'}
        self.assertEqual(compare_frozen_current_shadows(f,a,SAVED)['comparisons'][0]['state'],'OFFICIAL_RESULT_NOT_FINAL')
    def test_special_separate_not_ordinary_miss(self):
        for state in ('OFFICIAL_RESULT_REFUND_OR_SPECIAL','OFFICIAL_RESULT_ABNORMAL_FINISH_SEPARATE','EXCLUDE_REPEAT_USE_EARLIER_RECEIPT'):
            f,a=fixture(); a['official_results'][0]['state']=state
            r=compare_frozen_current_shadows(f,a,SAVED)['comparisons'][0]
            self.assertEqual(r['state'],state); self.assertNotIn('models',r)
    def test_shadow_tamper_rejected(self):
        f,a=fixture(); f['additional_official_feature_shadows'][0]['top8'][0]['ticket']='6-5-4'
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_pair_tamper_rejected(self):
        f,a=fixture(); f['paired_forecasts'][0]['models'][0]['top8'].reverse()
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_late_receipt_rejected(self):
        f,a=fixture()
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,'2026-11-03T06:10:00Z')
    def test_same_second_server_truncation(self):
        f,a=fixture(); a['official_results'][0]['paired_comparison']['forecast_server_saved_at']='2026-11-03T06:00:00Z'
        self.assertEqual(compare_frozen_current_shadows(f,a,'2026-11-03T06:00:00Z')['scored_comparison_count'],1)
    def test_result_before_cutoff_rejected(self):
        f,a=fixture(); a['official_results'][0]['result_captured_at']='2026-11-03T06:09:59Z'
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_wrong_source_even_with_new_hash_rejected(self):
        f,a=fixture(); s=f['additional_official_feature_shadows'][0]; s['source_snapshot_sha256']='f'*64;seal(s,'bundle_sha256')
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_duplicate_c_rejected(self):
        f,a=fixture();f['additional_official_feature_shadows']*=2
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_duplicate_result_rejected(self):
        f,a=fixture();a['official_results']*=2
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_resealed_invalid_ranking_rejected(self):
        f,a=fixture(); s=f['additional_official_feature_shadows'][0];s['top8'].reverse();seal(s,'bundle_sha256')
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_false_calibration_claim_rejected(self):
        f,a=fixture();s=f['additional_official_feature_shadows'][0];s['calibrated']=True;seal(s,'bundle_sha256')
        with self.assertRaises(ValueError):compare_frozen_current_shadows(f,a,SAVED)
    def test_no_targeted_third_place_excuse(self):
        f,a=fixture();r=a['official_results'][0];r['official_top3']='6-5-4';r['paired_comparison']['official_top3']='6-5-4'
        got=compare_frozen_current_shadows(f,a,SAVED)['comparisons'][0]['models'][2]
        self.assertEqual(got['hit_at_8'],0);self.assertIn('FIRST_SLOT_NOT_COVERED',got['observed_miss_flags']); self.assertEqual(got['virtual_payout_yen'],0)

if __name__=='__main__':unittest.main()
