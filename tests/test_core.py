import sqlite3
import tempfile
import unittest
from pathlib import Path
from race_ai.core import (connect, parse_k, parse_b, import_official, histories,
                          save_exhibition, exhibition_asof, record_entry_evidence,
                          pair_summary, SourceError)


def k_file(day='2020-07-14', racer='4171', course=1, st='0.17'):
    # This is a fixture recreating the published structural example, NOT actual official bytes.
    rows = []
    for rank,boat in enumerate([6,1,2,4,3,5],1):
        rid=racer if boat==1 else str(4000+boat)
        c=course if boat==1 else {6:5,2:2,4:4,3:3,5:6}[boat]
        status=st if boat==1 else '0.09'
        rows.append(f' {rank:02d}  {boat} {rid} 仮　名　例 56 47 6.82   {c}   {status}    1.50.3')
    return ('STARTK\n23KBGN\n第 1日          2020/ 7/14  ボートレース唐津\n'
            '1R       予　選        H1800m 雨\n'+'\n'.join(rows)+'\n23KEND\n').encode('cp932')


def b_file():
    rows='\n'.join(f'{n} {4000+n}仮名 37福岡50A1' for n in range(1,7))
    return ('STARTB\n23BBGN\n第 1日          2020/ 7/14\n'
            '1R 予選 H1800m\n'+rows+'\n23BEND\n').encode('cp932')


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connect(Path(self.temp.name)/'test.db')
        self.published='2020-07-15T10:00:00+09:00'
        self.captured='2020-07-15T10:05:00+09:00'

    def tearDown(self):
        self.db.close();self.temp.cleanup()

    def write(self,name,raw):
        p=Path(self.temp.name)/name;p.write_bytes(raw);return p

    def test_parse_k_actual_course_not_lane(self):
        rows=parse_k(k_file(), '2020-07-14')
        self.assertEqual(len(rows),6)
        lane6=next(r for r in rows if r['lane']==6)
        self.assertEqual(lane6['course'],5)
        self.assertEqual(next(r for r in rows if r['lane']==1)['racer_id'],'4171')

    def test_b_program(self):
        self.assertEqual(len(parse_b(b_file(),'2020-07-14')),6)
        r=import_official(self.db,self.write('B200714.TXT',b_file()),'B','2020-07-14',self.published,self.captured)
        self.assertEqual(r['rows'],6)

    def test_wrong_header_or_date_safe_stop(self):
        with self.assertRaises(SourceError): parse_k(b_file(),'2020-07-14')
        with self.assertRaises(SourceError): parse_k(k_file(),'2020-07-15')
        with self.assertRaises(SourceError): parse_k(k_file()[:-18],'2020-07-14')

    def test_import_and_asof_leakage(self):
        self.assertEqual(import_official(self.db,self.write('K200714.TXT',k_file()),'K',
            '2020-07-14',self.published,self.captured)['rows'],6)
        earlier=histories(self.db,'4171',1,1,'2020-07-15T09:59:59+09:00')
        self.assertEqual(earlier['by_lane_10']['n'],0)
        later=histories(self.db,'4171',1,1,'2020-07-16T00:00:00+09:00')
        self.assertEqual(later['by_lane_10']['n'],1)
        self.assertAlmostEqual(later['by_lane_10']['mean_st'],0.17)
        self.assertEqual(later['by_course_10']['n'],1)
        self.assertEqual(later['overall_10']['n'],1)

    def test_course_and_lane_are_independent(self):
        # Explicit database inserts for cross-race case, with distinct racer history.
        with self.db:
            self.db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?)',
              ('a'*64,'K','fixture',self.published,self.captured,self.captured,0))
            for i,lane,course,st,status,finish in [(1,6,2,.08,'OK',1),(2,6,3,.14,'OK',3),
                            (3,2,2,.22,'OK',2),(4,6,2,None,'F',None)]:
                self.db.execute('INSERT INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)',(
                    f'2020071{i}-23-01',lane,'4001',course,st,status,finish,
                    f'2020-07-1{i}T00:00:00Z',self.published,self.captured,'a'*64))
        s=histories(self.db,'4001',6,2,'2020-07-16T12:00:00Z')
        self.assertEqual(s['by_lane_10']['n'],3)
        self.assertEqual(s['by_course_10']['n'],3)
        self.assertEqual(s['overall_10']['n'],4)
        self.assertEqual(s['by_lane_10']['valid_st'],2)
        self.assertEqual(s['by_course_10']['valid_st'],2)
        self.assertEqual(s['by_course_10']['starts'][0]['st_status'],'F')

    def test_exhibition_immutable_and_asof(self):
        source=dict(race_id='20261013-19-09',published_at='2026-10-13T21:00:00+09:00',
                    captured_at='2026-10-13T21:01:00+09:00',rights_confirmed=True,
                    metrics=[dict(lane=1,metric='turn',value=5.22)])
        save_exhibition(self.db,source)
        self.assertEqual(exhibition_asof(self.db,source['race_id'],'2026-10-13T21:00:30+09:00'),[])
        self.assertEqual(exhibition_asof(self.db,source['race_id'],'2026-10-13T21:02:00+09:00')[0]['value'],5.22)
        source['captured_at']='2026-10-13T21:09:00+09:00'
        source['metrics'][0]['value']=5.55
        save_exhibition(self.db,source)
        self.assertEqual(exhibition_asof(self.db,source['race_id'],'2026-10-13T21:02:00+09:00')[0]['value'],5.22)
        self.assertEqual(exhibition_asof(self.db,source['race_id'],'2026-10-13T21:10:00+09:00')[0]['value'],5.55)

    def test_missing_publication_excluded_and_rights_checked(self):
        p=dict(race_id='r',captured_at=self.captured,rights_confirmed=False,
               metrics=[dict(lane=1,metric='lap',value=None,missing_reason='not published')])
        with self.assertRaises(SourceError):save_exhibition(self.db,p)
        p['rights_confirmed']=True
        save_exhibition(self.db,p)
        self.assertEqual(exhibition_asof(self.db,'r','2030-01-01T00:00:00Z'),[])

    def test_pair_success_requires_separate_observed_event(self):
        p=dict(race_id='r2',challenger='4001',defender='4002',
               outcome='yes',evidence_level='HUMAN_REVIEWED',rights_confirmed=True,
               clip_ref='local:clip#t=04',reviewer='human',
               published_at=self.published,captured_at=self.captured)
        record_entry_evidence(self.db,dict(p,event_id='a',event_type='attempt'))
        record_entry_evidence(self.db,dict(p,event_id='b',event_type='success'))
        record_entry_evidence(self.db,dict(p,event_id='c',event_type='resistance'))
        s=pair_summary(self.db,'4001','4002','2020-07-16T00:00:00Z')
        self.assertEqual(s['confirmed_successes'],1)
        self.assertEqual(s['resistances'],1)
        self.assertEqual(s['confirmed_defenses'],0)
        self.assertAlmostEqual(s['success_given_attempt'],2/3)

    def test_pair_no_unsourced_inference_and_small_sample(self):
        p=dict(event_id='clip1',race_id='r',challenger='4001',defender='4002',
               event_type='attempt',outcome='yes',evidence_level='ESTIMATED',
               rights_confirmed=True,clip_ref='local:clip#t=04',reviewer='human',
               published_at=self.published,captured_at=self.captured)
        with self.assertRaises(SourceError):record_entry_evidence(self.db,p)
        p['evidence_level']='HUMAN_REVIEWED'
        record_entry_evidence(self.db,p)
        s=pair_summary(self.db,'4001','4002','2020-07-16T00:00:00+09:00')
        self.assertEqual(s['reviewed_encounters'],1)
        self.assertEqual(s['attempts'],1)
        self.assertEqual(s['confirmed_successes'],0)
        self.assertAlmostEqual(s['attack_frequency'],2/3)
        self.assertAlmostEqual(s['success_given_attempt'],1/3)
        self.assertTrue(s['exploratory'])
        self.assertEqual(pair_summary(self.db,'4002','4001','2020-07-16T00:00:00+09:00')['attempts'],0)

if __name__=='__main__':unittest.main()
