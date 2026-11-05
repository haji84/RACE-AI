"""Invented official-layout fixtures, never actual racer data."""
import unittest
from race_ai.boat_racer_term import parse_term, extract_term

# Exact byte layout from official layout.html, 2014 second term onwards.
HEAD=[4,16,15,4,2,1,6,1,2,3,2,2,4,4,3,3,3,2,2,3]
COURSE=[3,4,3,3]
TAIL=[2,2,2,4,4,4,1,8,8,3]
DISPOSITIONS=[3]*6+[2]*8

def record(reg='4001',*,zero=False):
    values=[reg,'架空 選手','ｶｸｳ ｾﾝｼｭ','東京','A1','S','550101','1','46','170','52','A','0756','0459','010','009','100','01','00','016']
    fields=list(zip(values,HEAD))
    for i in range(6):fields+=list(zip(['000' if zero else '010','0000' if zero else '0500','000' if zero else '016','000' if zero else '240'],COURSE))
    fields+=list(zip(['A1','A1','A1','7400','7500','2026','2','20251101','20260430','085'],TAIL))
    for i in range(6):fields+=list(zip((['000']*6 if zero else ['002','003','001','001','001','002'])+['00']*8,DISPOSITIONS))
    fields+=list(zip(['00']*4,[2]*4));fields+=[('東京',6)]
    return b''.join(str(v).encode('cp932').ljust(n,b' ') for v,n in fields)

class TermTests(unittest.TestCase):
    def test_all_players_and_courses_byte_offsets_scales_and_period(self):
        out=parse_term(record()+b'\r\n'+record('4002')+b'\r\n',term='2026-2')
        self.assertEqual(len(out),2);p=out[0]
        self.assertEqual(p['racer_id'],'4001');self.assertEqual(p['name'],'架空 選手')
        self.assertEqual(p['national_win_rate'],7.56);self.assertEqual(p['national_top2_percent'],45.9)
        self.assertEqual(p['period_start'],'2025-11-01');self.assertEqual(p['period_end'],'2026-04-30')
        self.assertEqual(len(p['courses']),6)
        self.assertEqual(p['courses'][0]['numeric_finishes'],10)
        self.assertEqual(p['courses'][0]['top3_rate_numeric'],.6)
        self.assertEqual(p['courses'][0]['mean_st'],.16)
        self.assertEqual(p['age_basis'],'TERM_RECORDED_NOT_CURRENT')
    def test_zero_sample_is_null_not_fictional_zero_rate(self):
        p=parse_term(record(zero=True),term='2026-2')[0]
        self.assertIsNone(p['courses'][0]['mean_st']);self.assertIsNone(p['courses'][0]['top3_rate_numeric'])
        self.assertEqual(p['courses'][0]['entry_n'],0)
    def test_rejects_empty_truncated_encoding_duplicates_and_wrong_term(self):
        for raw in (b'',record()[:-1],record()+b'\n'+record(),b'x'*len(record()),record().replace(b'20260430',b'20261340')):
            with self.subTest(size=len(raw)),self.assertRaises(ValueError):parse_term(raw,term='2026-2')
        with self.assertRaises(ValueError):parse_term(record(),term='2026-1')
    def test_course_count_conflict_is_rejected(self):
        raw=record();offset=sum(HEAD)
        raw=raw[:offset]+b'005'+raw[offset+3:]
        with self.assertRaises(ValueError):parse_term(raw,term='2026-2')
    def test_archive_name_and_traversal_rejected(self):
        with self.assertRaises(ValueError):extract_term(b'bad',term='2026-2')

    def test_no_national_samples_are_missing_not_measured_zero(self):
        raw=record(zero=True)
        for key in ('win_rate','top2','wins','seconds','starts','st'):
            offset=0
            from race_ai.boat_racer_term import HEAD
            for name,width in HEAD:
                if name==key:raw=raw[:offset]+b'0'*width+raw[offset+width:];break
                offset+=width
        p=parse_term(raw,term='2026-2')[0]
        self.assertIsNone(p['national_win_rate']);self.assertIsNone(p['national_top2_percent']);self.assertIsNone(p['mean_st'])
        self.assertEqual(p['missing']['national_win_rate'],'NO_PRIOR_SAMPLES')
