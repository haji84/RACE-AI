"""Historical official result roster must match pre-cutoff sealed C-lite roster."""
import hashlib
import json
import unittest
from race_ai.boat_historical_result_roster import validate_historical_result_roster


def seal(d):
    return hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def fixtures():
    cutoff='2026-11-03T13:35:00+09:00'
    rid='20261103-17-08'
    pair={'schema':'RACE_AI_BOAT_PRE_CUTOFF_AB_PAIR_V1','race_id':rid,
          'cutoff_at':cutoff,'source_captured_at':'2026-11-03T04:20:00+00:00',
          'generated_at':'2026-11-03T04:20:30+00:00','source_sha256':'a'*64}
    pair['bundle_sha256']=seal(pair)
    shadow={'schema':'RACE_AI_BOAT_CURRENT_FEATURE_SHADOW_V1',
            'model_id':'boat-local-start-course-shadow-v0.1-UNTRAINED',
            'race_id':rid,'cutoff_at':cutoff,'as_of':'2026-11-03T04:20:31+00:00',
            'source_snapshot_sha256':pair['source_sha256'],
            'extra_source_sha256':'b'*64,'untrained':True,'calibrated':False,
            'odds_used':False,'auto_promoted':False,'betting_decision':'NO_BET',
            'features':[{'lane':i,'racer_id':f'{5000+i}'} for i in range(1,7)]}
    shadow['bundle_sha256']=seal(shadow)
    observed={'race_id':rid,'kind':'raceresult','body_identity_verified':True,
              'closed_at':cutoff,'captured_at':'2026-11-04T02:10:00+09:00',
              'status':'AVAILABLE','data':{'finish_confirmed':True,
              'results':[{'lane':i,'racer_registration_id':f'{5000+i}'} for i in range(1,7)]}}
    return pair,shadow,observed


class HistoricalResultRosterTests(unittest.TestCase):
    def setUp(self):
        self.p,self.s,self.o=fixtures()

    def valid(self):
        return validate_historical_result_roster(self.p,self.s,self.o,'2026-11-03T04:24:58Z')

    def test_historic_result_uses_actual_next_day_timestamp(self):
        verified=self.valid()
        self.assertEqual(verified['race_id'],'20261103-17-08')
        self.assertEqual(verified['roster_source'],'SEALED_PRE_CUTOFF_C_LITE')
        self.assertEqual(verified['official_result_captured_at'],'2026-11-04T02:10:00+09:00')

    def test_wrong_or_missing_roster_not_admitted(self):
        for mutation in (lambda: self.s['features'][0].update(racer_id='9999'),
                         lambda: self.o['data']['results'][0].update(racer_registration_id='9999'),
                         lambda: self.o['data']['results'].pop(),
                         lambda: self.s.update(features=[]),
                         lambda: self.s.update(source_snapshot_sha256='f'*64)):
            with self.subTest(mutation=mutation):
                self.p,self.s,self.o=fixtures();mutation()
                with self.assertRaises(ValueError):self.valid()

    def test_identity_date_and_context_fail_closed(self):
        for key,val in (('race_id','20261103-18-11'),('kind','odds3t'),
                        ('closed_at','2026-11-03T13:36:00+09:00'),
                        ('body_identity_verified',False),('captured_at','2026-11-03T13:33:00+09:00')):
            with self.subTest(key=key):
                self.p,self.s,self.o=fixtures();self.o[key]=val
                with self.assertRaises(ValueError):self.valid()

    def test_no_late_receipt_or_mismatched_model(self):
        for value in ('2026-11-03T04:35:00Z','2026-11-03T04:19:00Z'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_historical_result_roster(self.p,self.s,self.o,value)
        self.s['model_id']='unknown';self.s['bundle_sha256']=seal({k:v for k,v in self.s.items() if k!='bundle_sha256'})
        with self.assertRaises(ValueError):self.valid()

    def test_pending_or_unverified_not_scored(self):
        for key,val in (('status','PENDING'),('data',None),('data',{'finish_confirmed':False,'results':[]})):
            with self.subTest(key=key):
                self.p,self.s,self.o=fixtures();self.o[key]=val
                with self.assertRaises(ValueError):self.valid()

if __name__=='__main__': unittest.main()
