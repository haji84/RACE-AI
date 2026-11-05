"""Synthetic six-racer integration into existing models, never live accuracy."""
from copy import deepcopy
import hashlib
import unittest
from race_ai.teiai_feature_adapter import enrich_observed_snapshot, descriptive_summary
from race_ai.boat_observed_pairwise_models import predict_pair
from tests.test_boat_observed_pairwise_models import fixture
from tests.test_teiai_history import csv_bytes
from tests.test_boat_entry_observations import uncompressed_lzh

CAPTURE='2030-03-31T00:00:00Z'

def inputs():
    k=['STARTK','01KBGN','2030/03/30',' 1R TEST H1800m',' 逃げ']
    histories={}
    for i in range(1,7):
        k.append(f' {i:02} {i} {4000+i} TEST 11 22 6.80 {i} 0.12 1.50.0')
        raw=csv_bytes([['2030-03-30','桐生','1','予選','架空杯','一般',str(i),str(i),'0.12','',str(i),f'{i:02}','逃げ' if i==1 else '', '6.80','11','22','1.50.0']])
        histories[str(4000+i)]=dict(raw=raw,source_url=f'https://boatrace-db.jp/api/racer/{4000+i}/results/',
            source_sha256=hashlib.sha256(raw).hexdigest(),captured_at=CAPTURE,stored_at=CAPTURE,published_at=None)
    k.append('01KEND');raw=uncompressed_lzh('\n'.join(k).encode('cp932'),'K300330.TXT')
    official={'2030-03-30':dict(raw=raw,source_sha256=hashlib.sha256(raw).hexdigest(),captured_at=CAPTURE,
                              source_url='https://www1.mbrace.or.jp/od2/K/203003/k300330.lzh')}
    snap=fixture(all_missing=True,research=True)
    return snap,histories,official

def run(s,h,o,**kw):
    return enrich_observed_snapshot(s,h,o,verified_at=CAPTURE,allow_source=lambda u,r,p:True,
                                    authenticate_official=lambda proof:True,**kw)

class FeatureTests(unittest.TestCase):
    def test_six_racers_identical_contract_and_both_existing_models(self):
        s,h,o=inputs();before=deepcopy(s);x=run(s,h,o)
        self.assertEqual(s,before)
        for i,row in enumerate(x['snapshot']['participants'],1):
            self.assertEqual(row['features']['recent_mean_finish']['value'],i)
            self.assertEqual(row['features']['recent_mean_finish']['sample_n'],1)
            self.assertNotIn('recent_mean_finish',row['missing'])
            self.assertEqual(row['features']['course_mean_st']['value'],.12)
            self.assertIn('motor_top2_rate',row['missing'])
        out=predict_pair(x['snapshot'],allow_source=lambda *a:True)
        self.assertEqual(len(out['models']),2)
        self.assertEqual(len({x['snapshot']['as_of']}),1)
        self.assertEqual(x['coverage']['matched_rows'],6)
    def test_future_capture_storage_verification_and_post_cutoff_stop(self):
        for key in ('captured_at','stored_at'):
            s,h,o=inputs();h['4001'][key]='2030-04-02T00:00:00Z'
            with self.subTest(key=key),self.assertRaises(ValueError):run(s,h,o)
        s,h,o=inputs();s['as_of']='2030-03-29T00:00:00Z'
        with self.assertRaises(ValueError):run(s,h,o)
        s,h,o=inputs();s['as_of']=s['sales_cutoff_at']
        with self.assertRaises(ValueError):run(s,h,o)
    def test_hash_tamper_identity_and_missing_permission(self):
        s,h,o=inputs();h['4001']['raw']+=b'tamper'
        with self.assertRaises(ValueError):run(s,h,o)
        s,h,o=inputs()
        with self.assertRaises(ValueError):enrich_observed_snapshot(s,h,o,verified_at=CAPTURE)
        h['4999']=h.pop('4001')
        with self.assertRaises(ValueError):run(s,h,o)
    def test_official_mismatch_quarantine_and_no_invention(self):
        s,h,o=inputs();from race_ai.official_lzh_extract import extract_daily_lzh
        text=extract_daily_lzh(o['2030-03-30']['raw'],'K300330.TXT').replace(b'4001',b'4999')
        o['2030-03-30']['raw']=uncompressed_lzh(text,'K300330.TXT')
        o['2030-03-30']['source_sha256']=hashlib.sha256(o['2030-03-30']['raw']).hexdigest()
        x=run(s,h,o);row=x['snapshot']['participants'][0]
        self.assertNotIn('recent_mean_finish',row['features'])
        self.assertEqual(x['coverage']['mismatched_rows'],1)
        self.assertEqual(row['missing']['recent_mean_finish'],'UNRESOLVED_DISPOSITION')
    def test_no_history_stays_missing_and_no_motor_cycle_inference(self):
        s,h,o=inputs();x=run(s,{},o)
        self.assertEqual(x['snapshot'],s)
        self.assertEqual(x['coverage']['matched_rows'],0)
        self.assertIn('motor_exchange_cycle',x['not_provided'])
    def test_summary_denominators_and_st_std_and_unknown_grade(self):
        from race_ai.teiai_history import parse_history_csv
        s,h,o=inputs();rows=parse_history_csv(h['4001']['raw'],racer_id='4001',source_url=h['4001']['source_url'])['rows']
        p=descriptive_summary(rows)
        self.assertEqual(p['courses']['1']['numeric_finish_n'],1)
        self.assertEqual(p['courses']['1']['top3_rate'],1)
        self.assertEqual(p['st']['n'],1);self.assertEqual(p['st']['std_population'],0)
        self.assertIsNone(p['courses']['2']['win_rate'])
        self.assertEqual(p['recent_10']['starts'],1)
        self.assertEqual(p['grade_basis'],'PROVIDER_INFERRED')

    def test_shared_real_shaped_race_json_reused_for_six_histories(self):
        import json
        from tests.test_teiai_history import race_json
        s,h,o=inputs();raw=json.dumps(race_json()).encode()
        doc=dict(raw=raw,source_url='https://boatrace-db.jp/api/race/20300330/01/1/',source_sha256=hashlib.sha256(raw).hexdigest(),
                 captured_at=CAPTURE,stored_at=CAPTURE,published_at=None)
        # JSON fixture ST differs from CSV fixture, use matching official bytes.
        from race_ai.official_lzh_extract import extract_daily_lzh
        text=extract_daily_lzh(o['2030-03-30']['raw'],'K300330.TXT').replace(b'0.12',b'0.10')
        o['2030-03-30']['raw']=uncompressed_lzh(text,'K300330.TXT')
        o['2030-03-30']['source_sha256']=hashlib.sha256(o['2030-03-30']['raw']).hexdigest()
        x=run(s,{pid:doc for pid in h},o)
        self.assertEqual(x['coverage']['matched_rows'],6)
        self.assertEqual(len(x['snapshot']['sources']),3) # original, K, shared JSON
        self.assertEqual(len(predict_pair(x['snapshot'],allow_source=lambda *a:True)['models']),2)

    def test_tied_race_cannot_enter_as_ordinary_finish(self):
        import json
        from tests.test_teiai_history import race_json
        s,h,o=inputs();r=race_json();r['entries'][1].update(rank=1,result_code='01')
        raw=json.dumps(r).encode();doc=dict(raw=raw,source_url='https://boatrace-db.jp/api/race/20300330/01/1/',
            source_sha256=hashlib.sha256(raw).hexdigest(),captured_at=CAPTURE,stored_at=CAPTURE,published_at=None)
        from race_ai.official_lzh_extract import extract_daily_lzh
        text=extract_daily_lzh(o['2030-03-30']['raw'],'K300330.TXT').replace(b'0.12',b'0.10').replace(b' 02 2',b' 01 2')
        o['2030-03-30']['raw']=uncompressed_lzh(text,'K300330.TXT');o['2030-03-30']['source_sha256']=hashlib.sha256(o['2030-03-30']['raw']).hexdigest()
        x=run(s,{pid:doc for pid in h},o)
        self.assertNotIn('recent_mean_finish',x['snapshot']['participants'][0]['features'])
        self.assertGreater(x['coverage']['special_result_rows'],0)

    def test_unmatched_recent_opportunity_does_not_backfill_older_win(self):
        s,h,o=inputs();raw=csv_bytes([
            ['2030-03-30','桐生','1','予選','杯','一般','1','1','0.12','','1','01','逃げ','6.80','11','22',''],
            ['2030-03-31','桐生','1','予選','杯','一般','1','1','-0.02','F','','F','','6.80','11','22','']])
        h={'4001':dict(h['4001'],raw=raw,source_sha256=hashlib.sha256(raw).hexdigest())}
        x=run(s,h,o);row=x['snapshot']['participants'][0]
        self.assertNotIn('recent_mean_finish',row['features'])

    def test_verified_f_stays_in_counts_instead_of_older_normal_backfill(self):
        s,h,o=inputs()
        raw=csv_bytes([
            ['2030-03-30','桐生','1','予選','杯','一般','1','1','0.12','','1','01','逃げ','6.80','11','22',''],
            ['2030-03-30','桐生','2','予選','杯','一般','1','1','-0.02','F','','F','','6.80','11','22','']])
        from race_ai.official_lzh_extract import extract_daily_lzh
        text=extract_daily_lzh(o['2030-03-30']['raw'],'K300330.TXT').decode('cp932').replace('01KEND','')
        text+='\n 2R TEST H1800m\n 差し\n F 1 4001 TEST 11 22 6.80 1 F0.02 0.00.0\n'
        for i in range(2,7):text+=f' {i-1:02} {i} {4000+i} TEST 11 22 6.80 {i} 0.12 1.50.0\n'
        text+='01KEND\n';o['2030-03-30']['raw']=uncompressed_lzh(text.encode('cp932'),'K300330.TXT')
        o['2030-03-30']['source_sha256']=hashlib.sha256(o['2030-03-30']['raw']).hexdigest()
        h={'4001':dict(h['4001'],raw=raw,source_sha256=hashlib.sha256(raw).hexdigest())}
        x=run(s,h,o);r=x['snapshot']['participants'][0]
        self.assertNotIn('recent_mean_finish',r['features'])
        self.assertEqual(r['features']['recent_mean_st']['history']['f_n'],1)
        self.assertEqual(r['features']['recent_mean_st']['history']['total_n'],2)
        self.assertEqual(x['reports']['4001']['summary']['total']['starts'],2)
        self.assertEqual(x['reports']['4001']['summary']['total']['abnormal_or_missing_n'],1)
