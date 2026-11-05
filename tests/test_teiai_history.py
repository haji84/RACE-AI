"""Synthetic fixtures only. Real downloads are never committed here."""
import csv
import io
import json
import unittest
from copy import deepcopy
from race_ai.teiai_history import parse_history_csv, parse_race_json, parse_racer_json
from race_ai.teiai_official_reconciliation import reconcile_rows

COLS=['日付','場','R','レース','開催','グレード(推定)','艇番','コース','ST','ST記号','着','結果記号','決まり手','展示','モーター','ボート','タイム']
URL='https://boatrace-db.jp/api/racer/4001/results/'

def csv_bytes(rows=None, columns=COLS):
    out=io.StringIO(); w=csv.writer(out); w.writerow(columns)
    w.writerows(rows if rows is not None else [['2030-03-30','桐生','1','予選','架空杯','一般','1','2','0.12','','2','02','','6.80','11','22','1.50.0']])
    return out.getvalue().encode('utf-8-sig')

def race_json():
    rid=203003300101
    return dict(source='synthetic',race=dict(race_id=rid,date='2030-03-30',pid=1,rno=1,kimarite='逃げ'),
                day=dict(date='2030-03-30',pid=1,grade='一般'),
                entries=[dict(race_id=rid,boat=i,regno=4000+i,course=i,st=.1,st_flag=None,
                              rank=i,result_code=f'{i:02}',exhibit=6.8,motor_no=i,boat_no=i) for i in range(1,7)],
                payouts=[dict(race_id=rid,bet_type='trifecta',combo='1-2-3',amount=1000,popularity=1)])

class HistoryTests(unittest.TestCase):
    def test_csv_schema_and_no_inferred_winner_or_registration_proof(self):
        x=parse_history_csv(csv_bytes(),racer_id='4001',source_url=URL)
        self.assertEqual(x['rows'][0]['race_id'],'20300330-01-01')
        self.assertEqual(x['rows'][0]['racer_id'],'4001')
        self.assertIsNone(x['rows'][0]['winner_method'])
        self.assertFalse(x['registration_independently_verified'])
        self.assertEqual(x['rows'][0]['grade_basis'],'PROVIDER_INFERRED')

    def test_empty_malformed_schema_and_url(self):
        for raw in (b'',b'{}',b'\xff',csv_bytes(columns=COLS[:-1])):
            with self.subTest(raw=raw[:12]),self.assertRaises(ValueError):
                parse_history_csv(raw,racer_id='4001',source_url=URL)
        with self.assertRaises(ValueError):parse_history_csv(csv_bytes(),racer_id='4002',source_url=URL)

    def test_duplicate_identical_dedup_conflicting_quarantine(self):
        row=['2030-03-30','桐生','1','予選','架空杯','一般','1','2','0.12','','2','02','','6.80','11','22','1.50.0']
        x=parse_history_csv(csv_bytes([row,row]),racer_id='4001',source_url=URL)
        self.assertEqual(x['duplicate_count'],1);self.assertEqual(len(x['rows']),1)
        changed=row.copy();changed[8]='0.13'
        x=parse_history_csv(csv_bytes([row,changed]),racer_id='4001',source_url=URL)
        self.assertEqual(x['rows'],[]);self.assertEqual(len(x['quarantine']),1)

    def test_abnormal_codes_preserved_not_numeric_losses(self):
        for code in ('F','L0','L1','K0','K1','S0','S1','S2'):
            row=['2030-03-30','桐生','1','予選','架空杯','一般','1','','','','',code,'','','','', '']
            x=parse_history_csv(csv_bytes([row]),racer_id='4001',source_url=URL)['rows'][0]
            self.assertIsNone(x['finish']);self.assertEqual(x['result_code'],code)
        row[11]='転覆'
        with self.assertRaises(ValueError):parse_history_csv(csv_bytes([row]),racer_id='4001',source_url=URL)

    def test_racer_and_race_identity_and_schema_change(self):
        raw=json.dumps(dict(source='synthetic',racer={'regno':4001},stats={})).encode()
        self.assertEqual(parse_racer_json(raw,racer_id='4001')['regno'],4001)
        with self.assertRaises(ValueError):parse_racer_json(raw,racer_id='4002')
        for field,value in [('date','2030-03-29'),('pid',2),('rno',2),('race_id',1)]:
            x=race_json();x['race'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):parse_race_json(json.dumps(x).encode(),race_id='20300330-01-01')
        for raw in (b'',b'[]',b'{',b'{"a":NaN}',b'{"race":1,"race":2}'):
            with self.assertRaises(ValueError):parse_race_json(raw,race_id='20300330-01-01')

    def test_tie_retained_as_special_and_unknown_not_guessed(self):
        x=race_json();x['entries'][1].update(rank=1,result_code='01')
        r=parse_race_json(json.dumps(x).encode(),race_id='20300330-01-01')
        self.assertTrue(r['special_result']);self.assertEqual(r['rows'][1]['finish'],1)
        x['entries'][1]['course']=1
        with self.assertRaises(ValueError):parse_race_json(json.dumps(x).encode(),race_id='20300330-01-01')

    def test_reconciliation_counts_missing_mismatch_and_duplicate_official(self):
        p=parse_race_json(json.dumps(race_json()).encode(),race_id='20300330-01-01')
        result=reconcile_rows(p['rows'],deepcopy(p['rows']))
        self.assertEqual(result['matched_rows'],6);self.assertEqual(result['compared_rows'],6)
        self.assertEqual(result['mismatch_rate'],0);self.assertEqual(len(result['accepted']),6)
        official=deepcopy(p['rows']);official[0]['st']=.11;official[1]['course']=None
        result=reconcile_rows(p['rows'],official)
        self.assertEqual(result['mismatched_rows'],1);self.assertEqual(result['missing_rows'],1)
        self.assertEqual(len(result['accepted']),4);self.assertEqual(len(result['quarantine']),2)
        with self.assertRaises(ValueError):reconcile_rows(p['rows'],official+official[:1])
        self.assertIsNone(reconcile_rows([],[])['mismatch_rate'])

    def test_negative_f_start_preserved_but_excluded_from_ok_st(self):
        row=['2030-03-30','桐生','1','予選','架空杯','一般','1','1','-0.03','F','','F','','6.80','11','22','']
        x=parse_history_csv(csv_bytes([row]),racer_id='4001',source_url=URL)['rows'][0]
        self.assertIsNone(x['st']);self.assertEqual(x['raw_st'],-.03);self.assertEqual(x['st_status'],'F')
        row[9]=''
        with self.assertRaises(ValueError):parse_history_csv(csv_bytes([row]),racer_id='4001',source_url=URL)

    def test_official_all_payout_types_and_missing_is_not_success(self):
        from race_ai.teiai_official_reconciliation import official_day,reconcile_payouts
        k=['STARTK','01KBGN','2030/03/30',' 1R TEST H1800m',' 逃げ']
        for i in range(1,7):k.append(f' {i:02} {i} {4000+i} TEST 11 22 6.80 {i} 0.10 1.50.0')
        k+=[' 単勝 1 110',' 複勝 1 100 2 140',' 2連単 1-2 500 人気 3',' 2連複 1-2 440 人気 2',
            ' 拡連複 1-2 150 人気 1','       1-3 190 人気 4','       2-3 350 人気 6',
            ' 3連単 1-2-3 1920 人気 11',' 3連複 1-2-3 610 人気 5','01KEND']
        p=official_day('\n'.join(k).encode('cp932'),day='2030-03-30')['payouts']['20300330-01-01']
        self.assertEqual(len(p),10)
        self.assertEqual(reconcile_payouts(p,p),dict(requested=10,matched=10,missing=0,mismatched=0))
        self.assertEqual(reconcile_payouts(p,[])['missing'],10)

    def test_unknown_winner_method_is_missing_and_known_f_is_an_opportunity(self):
        p=parse_race_json(json.dumps(race_json()).encode(),race_id='20300330-01-01')
        official=deepcopy(p['rows']);p['rows'][0]['winner_method']=None
        x=reconcile_rows(p['rows'],official)
        self.assertEqual(x['missing_rows'],1)
        row=deepcopy(official[0]);row.update(finish=None,st=None,st_status='F',result_code='F',winner_method=None)
        x=reconcile_rows([row],[deepcopy(row)])
        self.assertEqual(x['matched_rows'],1);self.assertEqual(x['abnormal_rows'],1)

    def test_provider_special_note_is_retained_without_inferred_cause(self):
        x=race_json();x['race']['note']='返還あり（架空の注記）'
        y=parse_race_json(json.dumps(x).encode(),race_id='20300330-01-01')
        self.assertEqual(y['provider_note'],x['race']['note'])
