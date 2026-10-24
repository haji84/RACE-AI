"""Offline AUTORACE table extraction requires same-race visible numeric cells."""
import unittest
from race_ai.autorace_official_trial_adapter import parse_official_trial,TrialContractError
URL="https://autorace.jp/race_info/Program/isesaki/2026-10-24_11"
CAP="2026-10-24T19:20:00+09:00"
CUTOFF="2026-10-24T19:48:00+09:00"
def html(numeric=8):
    rows=[]
    for n in range(1,9):
        value=f"3.{20+n:02d}" if n<=numeric else "--"
        rows.append(f"<tr><td>{n}</td><td>選手{n}</td><td>{(n-1)*10}</td><td>{value}</td></tr>")
    return ("<html><body>2026/10/24 伊勢崎 11R 予選"
            "該当レースの開催は中止となりました。"
            "ここから表の見方「試走T」"
            "<table><tr><th>車</th><th>選手</th><th>ハンデ</th><th>試走T</th></tr>"
            +"".join(rows)+"</table></body></html>").encode("utf-8")
def check(raw,url=URL):
    return parse_official_trial(raw,source_url=url,race_day="2026-10-24",
          venue="isesaki",race_no=11,captured_at=CAP,scheduled_cutoff_at=CUTOFF)
class TestRaceScopedAutorace(unittest.TestCase):
    def test_held_8car_trial_not_cancelled_due_to_generic_notice(self):
        result=check(html())
        self.assertTrue(result["race_identity_structurally_sufficient"])
        self.assertEqual(result["official_trial_header_tables"],1)
        self.assertEqual(result["numeric_trial_car_count"],8)
        self.assertEqual(result["status"],"TRIAL_NUMERIC_ALL_REGISTERED")
        self.assertTrue(result["generic_cancel_notice_ignored"])
        self.assertFalse(result["official_race_cancellation_verified"])
        self.assertFalse(result["official_prediction"])
    def test_partial_trials_are_missing_not_zero(self):
        result=check(html(numeric=5))
        self.assertEqual(result["numeric_trial_car_count"],5)
        self.assertEqual(result["status"],"TRIAL_PUBLISHED_PARTIAL")
        self.assertFalse(result["model_prediction_executed"])
    def test_unrelated_race_url_refused(self):
        with self.assertRaisesRegex(TrialContractError,"identity mismatch"):
            check(html(),url="https://autorace.jp/race_info/Program/isesaki/2026-10-24_10")
    def test_generic_cancel_only_without_table_is_not_cancellation(self):
        r=check(b"<html>2026/10/24 11R 該当レースの開催は中止となりました 試走T</html>")
        self.assertEqual(r["status"],"TRIAL_RACE_BOUND_TABLE_NOT_FOUND")
        self.assertFalse(r["official_race_cancellation_verified"])
    def test_conflicting_car_slot_fails(self):
        t=html().replace(b"<td>8</td><td>",b"<td>7</td><td>")
        with self.assertRaisesRegex(TrialContractError,"duplicate"):
            check(t)
    def test_captured_after_cutoff_cannot_claim_pre_race(self):
        with self.assertRaisesRegex(TrialContractError,"cutoff"):
            parse_official_trial(html(),source_url=URL,race_day="2026-10-24",
               venue="isesaki",race_no=11,captured_at="2026-10-24T19:49:00+09:00",
               scheduled_cutoff_at=CUTOFF)
if __name__=="__main__":unittest.main()
