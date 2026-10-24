"""Synthetic official-source shapes only: no network, odds or trial claims."""
from datetime import datetime,timezone
import unittest
from scripts.p0_nonboat_official_format_probe_20261024 import (
    analyze_content,audit,TARGETS,BRANCH,TOKEN
)
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":BRANCH,
     "RACE_AI_NONBOAT_ONE_SHOT":TOKEN,"GITHUB_SHA":"a"*40}
NOW=datetime(2026,10,24,6,tzinfo=timezone.utc)
class Resp:
    status=200
    headers={"Content-Type":"text/html; charset=utf-8"}
    def __init__(self,url):self.url=url
    def geturl(self):return self.url
    def read(self,n):
        return {"autorace":b"<html>2026/10/24 <div>trial info sample</div></html>",
                "horse":"<html>2026年10月24日 京都 12R 出馬表 馬体重 発表済</html>".encode(),
                "keirin":"<html>開催日程 2026年10月</html>".encode()}[
                 "autorace" if "autorace.jp" in self.url else
                 "horse" if "jra.jp" in self.url else "keirin"]
    def __enter__(self):return self
    def __exit__(self,*_):return False
class Transport:
    def __init__(self):self.urls=[]
    def open(self,req,timeout):
        self.urls.append(req.full_url)
        assert timeout==8
        return Resp(req.full_url)
class OtherSportRealFormatContract(unittest.TestCase):
    def test_all_three_one_shot_only_no_source_rows(self):
        client=Transport()
        r=audit(env=ENV,opener=client,clock=lambda:NOW)
        self.assertEqual(r["provider_GET_attempts"],3)
        self.assertEqual(len(client.urls),3)
        self.assertEqual(len(set(client.urls)),3)
        self.assertEqual(len(r["sport_checks"]),3)
        self.assertTrue(all(x["source_sha256"] for x in r["sport_checks"]))
        self.assertFalse(r["source_license_for_model_features_verified"])
        self.assertFalse(r["prediction_executed"])
        self.assertFalse(r["raw_provider_html_persisted"])
    def test_autorace_cancellation_even_if_help_mentions_trial(self):
        r=analyze_content("autorace",
            "2026/10/24 該当レースの開催は中止となりました。 試走T:試走タイム".encode("utf-8"))
        self.assertEqual(r["status"],"AUTO_GENERIC_PAGE_RACE_STATUS_UNVERIFIED")
        self.assertFalse(r["presentation_available"])
        self.assertTrue(r["cancel_marker_present"])
        self.assertTrue(r["cancel_template_not_evidence_for_current_race"])
        self.assertFalse(r["race_scoped_cancel_verified"])
        self.assertTrue(r["generic_trial_help_present"])
    def test_actual_meet_can_contain_same_cancellation_template(self):
        # The official meeting took place; template text exists globally.
        raw="2026/10/24 伊勢崎 ＧⅡオートレースメモリアル 12R 試走T 3.31 該当レースの開催は中止となりました。".encode()
        # Generic content analysis cannot certify either trial or cancellation.
        report=analyze_content("autorace",raw)
        self.assertEqual(report["status"],"AUTO_GENERIC_PAGE_RACE_STATUS_UNVERIFIED")
        self.assertFalse(report["race_scoped_cancel_verified"])
        self.assertFalse(report["current_race_trial_numeric_verified"])

    def test_autorace_generic_help_is_not_actual_trial(self):
        r=analyze_content("autorace",
            "2026/10/24 試走T:試走タイム".encode())
        self.assertFalse(r["current_race_trial_numeric_verified"])
        self.assertFalse(r["presentation_available"])
    def test_jra_announced_word_not_identity_matched_data(self):
        r=analyze_content("horse",
            "2026年10月24日 京都 12R 発表済 馬体重".encode())
        self.assertTrue(r["explicit_announced_word_present"])
        self.assertFalse(r["bodyweight_rows_with_horse_ids_verified"])
        self.assertFalse(r["presentation_available"])
        self.assertFalse(r["paddock_video_observed"])
    def test_keirin_schedule_is_not_introduction(self):
        r=analyze_content("keirin",
            "開催日程 2026年10月24日 選手紹介".encode())
        self.assertEqual(r["status"],"KEIRIN_SCHEDULE_ONLY_NOT_RIDER_PRESENTATION")
        self.assertFalse(r["rider_introduction_record_present"])
        self.assertFalse(r["presentation_available"])
    def test_strips_fabricated_markers_in_scripts(self):
        raw=("<html><script>開催は中止となりました</script>"
             "<style>試走T</style>2026/10/24</html>").encode()
        r=analyze_content("autorace",raw)
        self.assertFalse(r["cancel_marker_present"])
        self.assertFalse(r["generic_trial_help_present"])
    def test_ref_gate_cannot_make_external_get(self):
        c=Transport()
        with self.assertRaises(RuntimeError):
            audit(env=dict(ENV,GITHUB_REF="refs/heads/main"),opener=c,clock=lambda:NOW)
        self.assertEqual(c.urls,[])
    def test_no_raw_horse_body_or_keirin_video_leaks(self):
        c=Transport()
        result=audit(env=ENV,opener=c,clock=lambda:NOW)
        self.assertNotIn("馬体重 発表済",str(result))
        self.assertFalse(result["video_or_photo_requested"])
        self.assertEqual(result["sport_checks"][2]["status"],
                         "KEIRIN_SCHEDULE_ONLY_NOT_RIDER_PRESENTATION")
if __name__=="__main__":unittest.main()
