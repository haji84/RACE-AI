import unittest
from datetime import date
from race_ai import program_race_isolation as p

def fixture(bad_race=None):
 text='STARTB\n18BBGN\n２０３０年４月１日\n'
 for n in range(1,13):
  text+=f'{n}Ｒ 予選 Ｈ１８００ｍ 電話投票締切予定１０：３０\n'
  for lane in range(1,7):
   field='11100.00' if n==bad_race and lane==1 else f'{10+lane} 50.00'
   text+=f'{lane} {4000+lane}選手名字42三重55A2 6.32 46.72 5.55 30.00 {field} {130+lane} 23.68\n'
 return (text+'18BEND\n').encode('cp932')

class RaceIsolationTest(unittest.TestCase):
 def parse(self,raw):
  return p.normalize_races(raw,day=date(2030,4,1),source_url='https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh',observed_at='2030-04-01T08:00:00+09:00',archive_sha256='a'*64)
 def test_all_fields_equal_unchanged_parser(self):
  from race_ai.official_b_snapshot_adapter import normalize_b_snapshot
  raw=fixture();x=self.parse(raw)
  y=normalize_b_snapshot(raw,day=date(2030,4,1),source_url=x['source_url'],observed_at=x['first_observed_at'],archive_sha256='a'*64,require_details=True)
  self.assertEqual(x['venues'],y['venues']);self.assertEqual(x['blocked_races'],[])
 def test_one_bad_race_does_not_destroy_eleven_valid_races(self):
  x=self.parse(fixture(3));self.assertEqual(x['races'],11);self.assertEqual(len(x['all_schedule']),12)
  self.assertEqual(x['blocked_races'][0]['race_id'],'20300401-18-03')
  self.assertEqual(x['blocked_races'][0]['reason'],'B program detail layout malformed')
  self.assertNotIn('20300401-18-03',[r['race_id'] for v in x['venues'] for r in v['races']])
 def test_wrong_date_and_duplicate_identity_fail_closed(self):
  with self.assertRaises(ValueError):self.parse(fixture().replace('２０３０年４月１日'.encode('cp932'),'２０３０年４月２日'.encode('cp932')))
  with self.assertRaises(ValueError):self.parse(fixture().replace(b'2 4002',b'2 4001',1))
