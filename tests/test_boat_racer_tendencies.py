import unittest
from copy import deepcopy
from race_ai.boat_racer_tendencies import profile_before

AS_OF="2026-11-03T11:20:00+09:00"
def race(rno, courses, finishes, method, captured="2026-11-02T13:00:00+09:00"):
    return {"race_id":f"20261102-17-{rno:02d}","cutoff_at":f"2026-11-02T12:{rno:02d}:00+09:00",
            "result_captured_at":captured,"winner_method":method,
            "source_sha256":"a"*64,
            "entries":[{"frame":i,"course":courses[i-1],"racer_id":str(4000+i),
                        "finish":finishes[i-1]} for i in range(1,7)]}

class BoatRacerTendenciesTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            race(1,[1,2,3,4,5,6],[2,3,4,1,5,6],"makuri"),
            race(2,[2,3,4,5,6,1],[2,3,4,5,6,1],"nige")]

    def test_course_and_outer_frame_crossing_counts(self):
        p=profile_before(self.records,as_of=AS_OF,racer_id="4001")
        self.assertEqual(p["sample_races"],2)
        self.assertEqual(p["actual_entry_course_history"]["1"]["starts"],1)
        self.assertEqual(p["actual_entry_course_history"]["1"]["wins"],0)
        self.assertEqual(p["actual_entry_course_history"]["2"]["top3"],1)
        self.assertEqual(p["tendencies"]["in1_losses_by_winner_method"]["makuri"],1)
        self.assertEqual(p["tendencies"]["displaced_outward"],1)
        self.assertEqual(p["tendencies"]["crossed_by_outer_frame"],1)
        self.assertEqual(p["tendencies"]["crossed_by_outer_frame_top3"],1)
        self.assertIsNone(p["model_score_or_personality_label"])

    def test_outer_frame_inward_entry_and_small_sample_no_invention(self):
        p=profile_before(self.records,as_of=AS_OF,racer_id="4006")
        self.assertEqual(p["tendencies"]["entered_inward"],1)
        self.assertEqual(p["tendencies"]["entered_from_outer_to_1_3"],1)
        self.assertEqual(p["actual_entry_course_history"]["1"]["win_rate"],1.0)
        self.assertEqual(p["actual_entry_course_history"]["2"]["win_rate"],None)
        self.assertEqual(p["actual_entry_course_history"]["1"]["starts"],1)

    def test_no_future_results_no_f_l_or_incomplete(self):
        changed=deepcopy(self.records)
        changed[0]["result_captured_at"]="2026-11-03T11:20:01+09:00"
        with self.assertRaises(ValueError):
            profile_before(changed,as_of=AS_OF,racer_id="4001")
        changed=deepcopy(self.records)
        changed[0]["entries"][0]["finish"]="F"
        with self.assertRaises(ValueError):
            profile_before(changed,as_of=AS_OF,racer_id="4001")
        changed=deepcopy(self.records)
        changed[0]["entries"][0]["course"]=2
        with self.assertRaises(ValueError):
            profile_before(changed,as_of=AS_OF,racer_id="4001")

    def test_empty_racer_history(self):
        p=profile_before(self.records,as_of=AS_OF,racer_id="4999")
        self.assertEqual(p["sample_races"],0)
        self.assertIsNone(p["actual_entry_course_history"]["1"]["win_rate"])

if __name__ == "__main__":
    unittest.main()
