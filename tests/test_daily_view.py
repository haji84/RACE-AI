import unittest
from race_ai.daily_view import render_daily_html


class DailyViewTests(unittest.TestCase):
    def test_escapes_untrusted_race_and_meeting_labels(self):
        report=dict(status='<script>alert(1)</script>',report_date_jst='2026-10-14',
            inventory_count=1,history_count=1,current_exhibition_motor_count=0,
            previous_meet_known_count=1,original_exhibition_complete_motor_count=0,
            motors=[dict(venue='19',motor_no=11,motor_cycle='A',historical_observations=2,
                prior_meet=dict(meeting_id='<svg onload=alert(1)>',rookie_starts=2),
                rider_adjusted_motor_residual=None,rider_adjustment_status='NOT_VALIDATED',
                current_exhibition=[],needs=['UNKNOWN'])])
        html=render_daily_html(report)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertNotIn('<svg onload=alert(1)>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('19',html)
        self.assertIn('未計算',html)

    def test_missing_sources_rendered_without_fake_motor_data(self):
        html=render_daily_html(dict(status='SAFE_STOP_MISSING_OR_INVALID_SOURCE',
                                   motors=[]))
        self.assertIn('検証停止',html)
        self.assertIn('SAFE_STOP_MISSING_OR_INVALID_SOURCE',html)


if __name__=='__main__':
    unittest.main()
