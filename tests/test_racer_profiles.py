"""Public athlete reference data; fabricated HTML/term rows for boundary tests."""
import unittest
import json
from pathlib import Path
from race_ai import racer_profiles as m
from race_ai.boat_racer_term import parse_term
from tests.test_boat_racer_term import record

def basic(reg='4002',name='架空選手二'):
    return ('<p class="racer1_bodyName">'+name+'</p><dl class="list3"><dt>登録番号</dt><dd>'+reg+'</dd>'
            '<dt>生年月日</dt><dd>2005/01/02</dd><dt>支部</dt><dd>東京</dd><dt>級別</dt><dd>B2級</dd>'
            '<dt>登録期</dt><dd>120期</dd><dt>身長</dt><dd>170cm</dd><dt>体重</dt><dd>52kg</dd></dl>').encode()

class ProfileTests(unittest.TestCase):
    def test_published_reference_has_real_course_counts_and_all_illustration_identities(self):
        web=Path(__file__).resolve().parents[1]/'web';doc=json.loads((web/'data/racer-profiles.json').read_text())
        portraits=json.loads((web/'data/racer-portraits.json').read_text())
        self.assertEqual({p['registration'] for p in doc['people']},{p['registration'] for p in portraits['people']})
        self.assertEqual(len(doc['people']),1669);self.assertEqual(sum(p['term'] is not None for p in doc['people']),1643)
        peak=next(p for p in doc['people'] if p['registration']=='4320')['term']
        self.assertEqual(peak['win_rate'],8.05);self.assertEqual(peak['starts'],105)
        self.assertEqual(peak['courses'][3]['starts'],19)
        self.assertAlmostEqual(peak['courses'][3]['top3_percent'],16/19*100)
        self.assertTrue(all(p['basic']['branch'] and p['basic']['grade'] in ('A1','A2','B1','B2') for p in doc['people']))

    def catalogue(self):
        rows=parse_term(record(),term='2026-2')
        people={'people':[{'registration':'4001','name':'架空選手','aliases':['架空選手']},
                          {'registration':'4002','name':'架空選手二','aliases':['架空選手二']}]}
        new=m.parse_basic_profile(basic(),registration='4002',expected_name='架空選手二')
        return rows,people,{'4002':new}

    def test_sparse_race_can_use_a_complete_catalogue_with_basic_only_newcomers(self):
        rows,people,new=self.catalogue()
        doc=m.build_catalogue(rows,people,new,{'4001':{'name':'架空選手','grade':'A2'}},
                              {'captured_at':'2026-11-07T00:00:00+00:00','url':'https://www.boatrace.jp/source','sha256':'a'*64})
        self.assertEqual(len(doc['people']),2)
        first,rookie=doc['people'];self.assertEqual(first['basic']['grade'],'A2')
        self.assertEqual(first['term']['win_rate'],7.56);self.assertEqual(first['term']['starts'],100)
        self.assertEqual(len(first['term']['courses']),6)
        self.assertEqual(rookie['basic']['branch'],'東京');self.assertIsNone(rookie['term'])
        self.assertEqual(doc['period']['end'],'2026-04-30')

    def test_course_percentages_use_starts_including_non_numeric_finishes(self):
        rows,people,new=self.catalogue();rows[0]['courses'][0]['finish_counts']=[2,3,1,0,0,0]
        doc=m.build_catalogue(rows,people,new,{}, {'captured_at':'2026-11-07T00:00:00+00:00'})
        course=doc['people'][0]['term']['courses'][0]
        self.assertEqual(course['starts'],10);self.assertEqual(course['win_percent'],20)
        self.assertEqual(course['top3_percent'],60);self.assertEqual(course['top2_percent'],50)
        self.assertEqual(doc['cohort_top2_percent'][0],50)
        rows[0]['courses'][0]['entry_n']=0;rows[0]['courses'][0]['finish_counts']=[0]*6
        doc=m.build_catalogue(rows,people,new,{}, {'captured_at':'2026-11-07T00:00:00+00:00'})
        self.assertIsNone(doc['people'][0]['term']['courses'][0]['top2_percent'])
        self.assertIsNone(doc['people'][0]['term']['courses'][0]['average_st'])

    def test_basic_source_identity_and_grade_must_be_exact(self):
        self.assertEqual(m.parse_basic_profile(basic(),registration='4002',expected_name='架空 選手二')['registration'],'4002')
        for raw in [basic(reg='4003'),basic(name='違う選手'),basic().replace(b'B2',b'X9')]:
            with self.subTest(raw=raw),self.assertRaises(ValueError):m.parse_basic_profile(raw,registration='4002',expected_name='架空選手二')

    def test_grade_identity_mismatch_and_missing_basic_records_are_rejected(self):
        rows,people,new=self.catalogue()
        with self.assertRaises(ValueError):m.build_catalogue(rows,people,new,{'4001':{'name':'違う人','grade':'A1'}},{})
        with self.assertRaises(ValueError):m.build_catalogue(rows,people,{}, {},{})

if __name__=='__main__':unittest.main()
