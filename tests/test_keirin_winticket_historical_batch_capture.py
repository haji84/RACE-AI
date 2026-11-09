"""Offline no-network regression tests for fixed historical replay capture batch."""
import unittest

from scripts.keirin_winticket_historical_batch_capture import (
    SOURCES, AOMORI_20261109_1R_REVIEW, identity_ok, admission_manifest
)

class FourCandidateHistoricBatchTests(unittest.TestCase):
    def test_explicit_distinct_sources_and_reserved_holdout(self):
        self.assertEqual(len(SOURCES),4)
        self.assertEqual(len({x["race_id"] for x in SOURCES}),4)
        self.assertEqual(sum(x["cohort"]=="UNSEEN_RESERVED" for x in SOURCES),1)
        self.assertEqual(sum(x["cohort"]=="TRAIN_CANDIDATE" for x in SOURCES),3)
        self.assertTrue(all(x["url"].startswith("https://www.winticket.jp/keirin/")
                            for x in SOURCES))

    def test_page_title_and_url_must_match_exact_race(self):
        for s in SOURCES:
            correct=f'{s["date"]} {s["venue"]}競輪 {s["race_no"]}レース 結果'
            self.assertTrue(identity_ok(s,s["url"],correct,200))
            self.assertFalse(identity_ok(s,s["url"],correct,403))
            self.assertFalse(identity_ok(s,s["url"]+"/wrong",correct,200))
            self.assertFalse(identity_ok(s,s["url"],correct.replace(
                 str(s["race_no"])+"レース","9レース"),200))

    def test_existing_one_shot_aomori_review_does_not_contaminate_training(self):
        race=AOMORI_20261109_1R_REVIEW
        self.assertNotIn(race["race_id"],{x["race_id"] for x in SOURCES})
        self.assertEqual(race["cohort"],"POST_RESULT_PREDICTION_AUDIT_ONLY")
        self.assertEqual(race["url"],
                         "https://www.winticket.jp/keirin/aomori/raceresult/2026110812/2/1")
        title="2026年11月9日 青森競輪 1レース 結果"
        self.assertTrue(identity_ok(race,race["url"],title,200))
        self.assertFalse(identity_ok(race,race["url"],title.replace(
            "1レース","2レース"),200))
        self.assertFalse(identity_ok(race,race["url"]+"/other",title,200))
        state=admission_manifest(race)
        self.assertFalse(state["training_eligible"])
        self.assertFalse(state["forecasts_modified"])
        self.assertFalse(state["full_four_laps_confirmed"])

    def test_ciphertext_is_not_automatic_training_license(self):
        for item in SOURCES:
            m=admission_manifest(item,technical={"exists":True})
            self.assertFalse(m["training_eligible"])
            self.assertFalse(m["independent_tactical_labels_confirmed"])
            self.assertFalse(m["full_four_laps_confirmed"])
            self.assertTrue(m["encrypted_video_verified"])
            self.assertFalse(m["permission_scope_independently_documented"])

if __name__=="__main__":
    unittest.main()
