"""Previous-JST-day recovery is not a license to fabricate old forecasts."""
from datetime import datetime
from hashlib import sha256
import unittest
from race_ai.keirin_daily_public_catalog import (
  combine,SOURCE_RACECARD,SOURCE_RESULTS
)
from race_ai.keirin_daily_night_backfill import select_night_backfill
from race_ai.keirin_daily_clip_batch import BatchError,PROGRESS_SCHEMA

def manifest():
    a=lambda k,n:{
      "href":f"https://www.winticket.jp/keirin/aomori/{k}/2026110812/2/{n}",
      "text":f"{n}R"}
    return combine("2026-11-09",[
       {"source_url":SOURCE_RACECARD,
        "heading":"本日 2026年11月9日 出走表一覧",
        "links":[a("racecard",i) for i in range(1,5)]},
       {"source_url":SOURCE_RESULTS,
        "heading":"本日 2026年11月9日 結果一覧",
        "links":[a("raceresult",1)]}])

class MidnightRecoveryTests(unittest.TestCase):
    def test_missing_results_links_in_previous_index_do_not_lose_last_races(self):
        snap=manifest()
        at=datetime.fromisoformat("2026-11-10T00:45:00+09:00")
        batch=select_night_backfill(snap,now=at,max_races=24)
        self.assertEqual(batch["total_prior_day_races"],4)
        self.assertEqual(batch["unresolved_races"],4)
        self.assertEqual(len(batch["attempt_candidates"]),4)
        self.assertEqual(batch["attempt_candidates"][-1]["url"],
         "https://www.winticket.jp/keirin/aomori/raceresult/2026110812/2/4")
        self.assertFalse(batch["retroactive_forecast_claim"])
    def test_private_readback_skips_only_confirmed_archive(self):
        at=datetime.fromisoformat("2026-11-10T00:45:00+09:00")
        p={"schema":PROGRESS_SCHEMA,"date_jst":"2026-11-09",
           "receipts":[{
            "race_id":"202611091201",
            "recording_sha256":sha256(b"fake").hexdigest(),
            "library_artifact_path":
                "/RACE-AI/KeirinVideo/2026-11-09/private.zip",
            "library_byte_readback_verified":True}]}
        batch=select_night_backfill(manifest(),now=at,progress=p)
        self.assertEqual(batch["private_readback_confirmed"],1)
        self.assertEqual(batch["unresolved_races"],3)
        self.assertNotIn("202611091201",
          {x["race_id"] for x in batch["attempt_candidates"]})
    def test_no_user_forged_backdate_or_daytime_retry(self):
        day=datetime.fromisoformat("2026-11-10T12:00:00+09:00")
        with self.assertRaisesRegex(BatchError,"OUTSIDE_MIDNIGHT_BACKFILL_WINDOW"):
            select_night_backfill(manifest(),now=day)
        wrong=datetime.fromisoformat("2026-11-11T00:20:00+09:00")
        with self.assertRaisesRegex(Exception,"WRONG_DAY_MANIFEST"):
            select_night_backfill(manifest(),now=wrong)
if __name__=="__main__":unittest.main()
