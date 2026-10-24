"""Official case facts and synthetic edge cases. Not complete official HTML scraping E2E."""
from pathlib import Path
import unittest
from race_ai.official_motor_join import (
    parse_motor_history,parse_official_racer_profile,audit_previous_meet,
    rookie_proxy,load_join,OfficialSourceError
)

FIX=Path(__file__).parent/'fixtures'
MOTOR_URL='https://boatrace-hamanako.jp/modules/datafile/?motor_no=12&page=index_motor_hist&select=20'
RACER_URL='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?entry_period=138&toban=5466'
CAPTURE='2026-10-13T22:45:00+09:00'
PRIOR_START='2026-09-19'


class OfficialMotorJoinTests(unittest.TestCase):
    def history(self):
        return parse_motor_history((FIX/'hamanako_motor12_excerpt.txt').read_text(encoding='utf-8'),
           venue='06',motor_no=12,source_url=MOTOR_URL,captured_at=CAPTURE)

    def profile(self):
        return parse_official_racer_profile((FIX/'racer_5466_excerpt.txt').read_text(encoding='utf-8'),
             expected_name='成田華音',source_url=RACER_URL,captured_at=CAPTURE)

    def test_actual_motor_history_transcription_parses_with_final(self):
        h=self.history()
        self.assertEqual(len(h),4)
        self.assertEqual([r['racer_name'] for r in h[:3]],['柘植政浩','渋谷明憲','成田華音'])
        self.assertEqual(h[1]['finish_count'],11)
        self.assertEqual(h[1]['top2_count'],5)
        self.assertEqual(h[1]['ordinary_races'],10)
        self.assertEqual(h[2]['finish_count'],9)
        self.assertEqual(h[2]['top2_count'],0)
        self.assertEqual(h[2]['top2_rate'],0)

    def test_actual_official_profile_link(self):
        p=self.profile()
        self.assertEqual(p['racer_id'],'5466')
        self.assertEqual(p['registration_cohort'],138)
        self.assertEqual(p['racer_name'],'成田華音')

    def test_next_meet_prior_is_new_cohort(self):
        o=audit_previous_meet(self.history(),[self.profile()],
            target_meet_start=PRIOR_START,cohort_debut_months={138:'2026-05'})
        self.assertEqual(o['previous']['racer_name'],'成田華音')
        self.assertEqual(o['profile']['racer_id'],'5466')
        self.assertEqual(o['rookie_proxy']['status'],'RECENT_DEBUT_COHORT')
        self.assertEqual(o['rookie_proxy']['months_since_cohort_debut_month'],3)
        self.assertFalse(o['prediction_asof_supported'])

    def test_latest_meet_not_confused_with_past_example(self):
        p=self.profile()
        o=audit_previous_meet(self.history(),[p],
          target_meet_start='2026-09-30',cohort_debut_months={138:'2026-05'})
        self.assertEqual(o['previous']['racer_name'],'渋谷明憲')
        self.assertEqual(o['rookie_proxy']['status'],'UNKNOWN')
        self.assertFalse(o['prediction_asof_supported'])

    def test_case_run_and_hashes(self):
        res=load_join(FIX/'hamanako_motor12_excerpt.txt',[FIX/'racer_5466_excerpt.txt'],
             venue='06',motor_no=12,motor_source=MOTOR_URL,
             profile_sources=[RACER_URL],captured_at=CAPTURE,
             target_meet_start=PRIOR_START,cohort_debut_months={138:'2026-05'})
        self.assertEqual(res['result'],'HISTORICAL_JOINED_PROFILE_VERIFIED')
        self.assertEqual(len(res['motor_snapshot_sha256']),64)
        self.assertEqual(res['motor_rows_parsed'],4)

    def test_malformed_motor_header_safe_stop(self):
        txt=(FIX/'hamanako_motor12_excerpt.txt').read_text(encoding='utf-8')
        with self.assertRaises(OfficialSourceError):
            parse_motor_history(txt,venue='06',motor_no=13,
              source_url=MOTOR_URL,captured_at=CAPTURE)

    def test_no_invented_profile(self):
        outcome=audit_previous_meet(self.history(),[],
           target_meet_start=PRIOR_START,cohort_debut_months={138:'2026-05'})
        self.assertEqual(outcome['rookie_proxy']['status'],'UNKNOWN')

    def test_cohort_unknown_does_not_mean_not_rookie(self):
        out=rookie_proxy(self.profile(),'2026-08-21',cohort_debut_months={})
        self.assertEqual(out['status'],'UNKNOWN')

    def test_raises_on_unexpected_status(self):
        txt='12番モーターの節間成績\n2026/08/21～2026/08/26 | sample | 成田華音 | error'
        with self.assertRaises(OfficialSourceError):
            parse_motor_history(txt,venue='06',motor_no=12,
               source_url=MOTOR_URL,captured_at=CAPTURE)

    def test_saved_html_profile_requires_explicit_identity(self):
        html='<html><body><h2>成田 華音（出場予定）</h2><p>登録番号</p><span>5466</span><p>登録期</p><span>138期</span></body></html>'
        p=parse_official_racer_profile(html,expected_name='成田華音',
                source_url=RACER_URL,captured_at=CAPTURE)
        self.assertEqual(p['racer_id'],'5466')
        self.assertEqual(p['registration_cohort'],138)

    def test_official_profile_url_racer_id_must_match(self):
        with self.assertRaises(OfficialSourceError):
            parse_official_racer_profile((FIX/'racer_5466_excerpt.txt').read_text(encoding='utf-8'),
                  expected_name='成田華音',source_url='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=4436',captured_at=CAPTURE)

    def test_html_four_column_rows(self):
        html="""<h4>12番モーターの節間成績</h4><table><tr>
        <th>開催期間</th><th>競走タイトル</th><th>使用選手</th><th>節間成績</th></tr>
        <tr><td>2026/08/21～2026/08/26</td><td>デイリースポーツ杯</td>
        <td>成田　華音</td><td>６６３６４６５６４</td></tr></table>"""
        o=parse_motor_history(html,venue='06',motor_no=12,source_url=MOTOR_URL,captured_at=CAPTURE)
        self.assertEqual(o[0]['finish_count'],9)


if __name__=='__main__':
    unittest.main()
