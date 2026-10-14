from pathlib import Path
import unittest

from race_ai.official_motor_join import (
    parse_motor_history,parse_official_racer_profile,audit_previous_meet,OfficialSourceError
)
from race_ai.official_racer_form import parse_racer_recent_meets,attach_prior_player_form

FIX=Path(__file__).parent/'fixtures'
MOTOR_URL='https://boatrace-hamanako.jp/modules/datafile/?motor_no=12&page=index_motor_hist&select=20'
PROFILE_URL='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=5466'
FORM_URL='https://www.boatrace.jp/owpc/pc/data/racersearch/back3?entry_period=138&toban=5466'
STAMP='2026-10-13T23:00:00+09:00'


class RacerPriorFormTests(unittest.TestCase):
    def make(self):
        motor=parse_motor_history((FIX/'hamanako_motor12_excerpt.txt').read_text(encoding='utf-8'),
             venue='06',motor_no=12,source_url=MOTOR_URL,captured_at=STAMP)
        p=parse_official_racer_profile((FIX/'racer_5466_excerpt.txt').read_text(encoding='utf-8'),
             expected_name='成田華音',source_url=PROFILE_URL,captured_at=STAMP)
        join=audit_previous_meet(motor,[p],target_meet_start='2026-09-19',
                                 cohort_debut_months={138:'2026-05'})
        form=parse_racer_recent_meets((FIX/'racer_5466_recent3_excerpt.txt').read_text(encoding='utf-8'),
             racer_name='成田華音',racer_id='5466',source_url=FORM_URL,captured_at=STAMP)
        return join,form

    def test_three_previous_meets_from_official_facts(self):
        a,r=self.make()
        self.assertEqual(len(r),3)
        self.assertEqual(sum(x['finish_count'] for x in r),22)
        self.assertEqual(sum(x['top2_count'] for x in r),1)
        combined=attach_prior_player_form(a,r)
        self.assertEqual(combined['preceding_player_form']['finish_count'],22)
        self.assertEqual(combined['preceding_player_form']['top2_count'],1)
        self.assertAlmostEqual(combined['preceding_player_form']['historical_top2_rate'],1/22,places=6)
        self.assertFalse(combined['preceding_player_form']['predictive_use_confirmed'])

    def test_future_meet_not_used_as_prior_form(self):
        a,r=self.make()
        future=dict(r[0],start='2026-09-30',end='2026-10-04',finish_count=100,top2_count=100)
        combined=attach_prior_player_form(a,r+[future])
        self.assertEqual(combined['preceding_player_form']['finish_count'],22)

    def test_different_racer_is_rejected(self):
        a,r=self.make()
        with self.assertRaises(OfficialSourceError):
            attach_prior_player_form(a,[dict(r[0],racer_id='4436')])

if __name__=='__main__':
    unittest.main()
