"""Pure synthetic daily race selection; does not record any real video."""
from hashlib import sha256
import unittest
from race_ai.keirin_daily_public_catalog import (
    SOURCE_RACECARD,SOURCE_RESULTS,combine
)
from race_ai.keirin_daily_clip_batch import (
    PROGRESS_SCHEMA,BatchError,readback_ids,select
)
def h(s):return sha256(s.encode()).hexdigest()
def fixture():
    meet="2026110812"
    links=lambda kind:[{
       "href":f"https://www.winticket.jp/keirin/aomori/{kind}/{meet}/2/{i}",
       "text":f"{i}R"} for i in (1,2,3,4,5)]
    return combine("2026-11-09",[
      {"source_url":SOURCE_RACECARD,
       "heading":"本日 2026年11月9日 出走表一覧",
       "links":links("racecard")},
      {"source_url":SOURCE_RESULTS,
       "heading":"本日 2026年11月9日 結果一覧",
       "links":links("raceresult")[:4]}])
def progress():
    return {"schema":PROGRESS_SCHEMA,"date_jst":"2026-11-09",
       "receipts":[{
        "race_id":"202611091201",
        "recording_sha256":h("source"),
        "library_artifact_path":
          "/RACE-AI/KeirinVideo/2026-11-09/wave01.zip",
        "library_byte_readback_verified":True}]}
class DailyBatchTests(unittest.TestCase):
    def test_public_results_page_only_and_durable_dedup(self):
        m=fixture()
        batch=select(m,progress=progress(),max_races=2)
        self.assertEqual(batch["races_visible_on_result_index"],4)
        self.assertEqual(batch["durably_archived_with_attested_readback"],1)
        self.assertEqual(batch["candidates_waiting_after_result_page"],3)
        self.assertEqual(batch["not_selected_due_to_wave_cap"],1)
        self.assertEqual([x["race_id"] for x in batch["selected"]],
                        ["202611091202","202611091203"])
        self.assertEqual(batch["selected"][0]["venue"],"青森")
        self.assertEqual(batch["selected"][0]["date"],"2026年11月9日")
        self.assertFalse(batch["eligible_for_learning_from_video_button_alone"])
    def test_no_readback_means_no_automatic_skip(self):
        m=fixture();p=progress()
        p["receipts"][0]["library_byte_readback_verified"]=False
        with self.assertRaisesRegex(BatchError,
                                   "RETENTION_NOT_INDEPENDENTLY_READ_BACK"):
            select(m,progress=p)
        self.assertEqual(select(m,progress=None)["selected"][0]["race_id"],
                         "202611091201")
    def test_bounded_wave_never_claims_all(self):
        m=fixture()
        with self.assertRaisesRegex(BatchError,"UNBOUNDED_RECORDING_BATCH"):
            select(m,max_races=1000)
        a=select(m,max_races=2)
        self.assertEqual(len(a["selected"]),2)
        self.assertEqual(a["not_selected_due_to_wave_cap"],2)
    def test_changed_manifest_or_result_page_rejected(self):
        m=fixture()
        m["races"][0]["video_captured"]=True
        with self.assertRaisesRegex(Exception,"MANIFEST_DIGEST_MISMATCH"):
            select(m)
    def test_unexpired_github_artifact_skips_retry_but_is_not_durable(self):
        m=fixture()
        results=select(
            m,progress=None,max_races=4,
            temporary_captured_race_ids={"202611091201","202611091202"})
        self.assertEqual(results["durably_archived_with_attested_readback"],0)
        self.assertEqual(results["temporarily_captured_unexpired_artifact_races"],2)
        self.assertEqual([x["race_id"] for x in results["selected"]],
                         ["202611091203","202611091204"])
        with self.assertRaisesRegex(BatchError,"INVALID_TEMPORARY_ARTIFACT_RACES"):
            select(m,temporary_captured_race_ids={"202611081201"})

    def test_no_previous_day_carryover_counts(self):
        p=progress()
        self.assertEqual(readback_ids(p,day_jst="2026-11-10"),set())
if __name__=="__main__":unittest.main()
