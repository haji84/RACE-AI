"""Invented 2030 historical races. No real athlete health inference or results."""
from copy import deepcopy
import unittest

from race_ai import keirin_rider_form_evidence as f
from race_ai import keirin_nationwide_auto_generator as m

ASOF = "2030-11-18T09:00:00+09:00"
AT = "2030-11-18T09:01:00+09:00"


def source():
    riders = []
    for car in range(1, 8):
        riders.append({
            "car": car, "athlete_id": f"{16000+car}",
            "mark_rank": car, "competition_points": 90-car,
            "recent_form_score": 0.45, "h_count": car, "b_count": car,
            "style": "MAKURI"})
    return {
        "schema": m.SCHEMA, "race_id": "203011182601",
        "as_of": ASOF, "published_cutoff_at": "2030-11-18T10:00:00+09:00",
        "cutoff_source": {"url": "https://example.org/cutoff",
                          "bytes_sha256": "a"*64, "captured_at": ASOF},
        "source_pages": [
            {"kind": k, "url": f"https://example.org/{k}",
             "bytes_sha256": sh*64, "captured_at": ASOF}
            for k, sh in (("RACECARD","b"),("MARKS","c"),("LINE","d"))],
        "competition": "A1_A2", "round_stage": "PRELIMINARY",
        "round_rule": None, "line_groups": [[1,2,3],[4,5],[6,7]],
        "riders": riders,
    }


def result(n, place, *, car=1, status="FINISHED"):
    # These are synthetic race identities and receipts, never real training.
    dt = f"2030-11-{n:02d}"
    return {"race_id": f"203011{n:02d}26{car:02d}",
            "race_date": dt, "status": status,
            "place": place if status == "FINISHED" else None,
            "field_size": 7, "published_at": "2030-11-18T08:00:00+09:00",
            "source_sha256": "e"*64}


def attach(snap, *, results, absences=None, comments=None):
    snap["source_pages"].append({
        "kind": "PROGRAM", "url": "https://example.org/history",
        "bytes_sha256": "e"*64, "captured_at": ASOF})
    snap["condition_evidence"] = {
        "schema": f.SCHEMA, "as_of": ASOF,
        "riders": [{"car": 1, "results": results,
                    "absences": [] if absences is None else absences,
                    "comments": [] if comments is None else comments}]}
    return snap


class FormEvidenceContract(unittest.TestCase):
    def test_no_form_keeps_exact_old_a_b_model_results(self):
        snap = source()
        before = deepcopy(snap)
        old = m.generate_A_B(snap, generated_at=AT)
        self.assertEqual(old, m.generate_A_B(snap, generated_at=AT))
        self.assertEqual(snap, before)
        self.assertNotIn("condition_research_notes", old)
        self.assertNotIn("pre_cutoff_form_fall_trace", old["A"])

    def test_observed_decline_changes_research_weights_and_explanation(self):
        baseline = source()
        original = m.generate_A_B(baseline, generated_at=AT)
        snap = attach(source(), results=[
            result(1, 1), result(2, 1), result(3, 1),
            result(5, 7), result(6, 7), result(7, 7)])
        before = deepcopy(snap)
        outcome = m.generate_A_B(snap, generated_at=AT)
        rec = outcome["A"]["pre_cutoff_form_fall_trace"][0]
        self.assertEqual(rec["trend"], "DECLINING")
        self.assertLess(rec["score_adjustment"], 0)
        self.assertEqual(rec["fall_on_record"], False)
        self.assertEqual(outcome["B"]["pre_cutoff_form_fall_trace"][0], rec)
        self.assertEqual(outcome["prediction_sha256"],
                         m.digest({k: v for k, v in outcome.items()
                                   if k != "prediction_sha256"}))
        self.assertNotEqual(original["B"]["six_phase_scenarios"][0]["relative_research_weight"],
                            outcome["B"]["six_phase_scenarios"][0]["relative_research_weight"])
        self.assertEqual(snap, before)

    def test_fall_without_recovery_data_does_not_penalize(self):
        snap = attach(source(), results=[result(4, None, status="FALL_DNF")])
        report = f.assess(snap["condition_evidence"],
                          starters={x["car"] for x in snap["riders"]},
                          source_pages=snap["source_pages"],
                          as_of=snap["as_of"], target_race_id=snap["race_id"])
        self.assertTrue(report[1]["fall_on_record"])
        self.assertEqual(report[1]["trend"], "INSUFFICIENT_DATA")
        self.assertEqual(report[1]["post_fall_trend"], "INSUFFICIENT_DATA")
        self.assertEqual(report[1]["score_adjustment"], 0)
        self.assertIsNone(report[1]["documented_absence_days"])

    def test_post_fall_finish_delta_not_mistaken_for_medical_causality(self):
        snap = attach(source(), results=[
            result(1,1), result(2,1), result(3,1),
            result(4,None,status="FALL_DNF"),
            result(5,7), result(6,7), result(7,7)],
            absences=[{"start":"2030-11-04","end":"2030-11-04",
                       "published_at":"2030-11-18T08:00:00+09:00",
                       "source_sha256":"e"*64}],
            comments=[{"speaker":"RIDER",
                       "text":"体の状態は分からない。走り方を考える。",
                       "published_at":"2030-11-18T08:00:00+09:00",
                       "source_sha256":"e"*64}])
        forecast = m.generate_A_B(snap, generated_at=AT)
        report = forecast["A"]["pre_cutoff_form_fall_trace"][0]
        self.assertEqual(report["post_fall_trend"], "DECLINING")
        self.assertEqual(report["documented_absence_days"], 1)
        self.assertEqual(report["return_after_absence_results"], 3)
        self.assertEqual(report["comments_count"], 1)
        self.assertFalse(forecast["condition_research_notes"]["personal_medical_recovery_claimed"])
        self.assertNotIn("体の状態は分からない", str(forecast))  # quote retained in private input

    def test_absence_gap_not_invented_as_rest(self):
        snap = attach(source(), results=[result(1,1),result(16,1)])
        report = f.assess(snap["condition_evidence"],
                          starters={x["car"] for x in snap["riders"]},
                          source_pages=snap["source_pages"],
                          as_of=snap["as_of"], target_race_id=snap["race_id"])
        self.assertIsNone(report[1]["documented_absence_days"])
        self.assertIsNone(report[1]["return_after_absence_results"])

    def test_late_or_unproven_or_result_day_mismatch_all_hold(self):
        for modification, code in (
            (lambda x: x["riders"][0]["results"][0].update(
                published_at="2030-11-18T09:30:00+09:00"),
             "FORM_PUBLISHED_AFTER_INPUT_CUTOFF"),
            (lambda x: x["riders"][0]["results"][0].update(
                source_sha256="0"*64), "FORM_SOURCE_SHA_UNMATCHED"),
            (lambda x: x["riders"][0]["results"][0].update(
                race_date="2030-11-19"), "FORM_FUTURE_DUPLICATE_OR_WRONG_RACE"),
            (lambda x: x["riders"][0]["results"][0].update(
                place=10), "FORM_FINISH_POSITION_INVALID"),
        ):
            with self.subTest(code=code):
                snap = attach(source(), results=[result(1,1)])
                modification(snap["condition_evidence"])
                with self.assertRaisesRegex(m.AutomaticForecastError, code):
                    m.generate_A_B(snap, generated_at=AT)

    def test_missing_history_is_unknown_not_zero_win_rate_or_accident(self):
        snap = attach(source(), results=[])
        report = m.generate_A_B(snap, generated_at=AT)
        values = report["B"]["pre_cutoff_form_fall_trace"]
        self.assertEqual(len(values), 7)
        self.assertTrue(all(v["score_adjustment"] == 0 for v in values))
        self.assertTrue(all(v["trend"] == "INSUFFICIENT_DATA" for v in values))

    def test_unsupported_comment_semantic_is_rejected(self):
        snap = attach(source(), results=[], comments=[{
            "speaker": "INFERRED_INJURY", "text": "予想しただけ",
            "published_at": "2030-11-18T08:00:00+09:00",
            "source_sha256": "e"*64}])
        with self.assertRaisesRegex(m.AutomaticForecastError,
                                    "FORM_COMMENT_INVALID"):
            m.generate_A_B(snap, generated_at=AT)


if __name__ == "__main__":
    unittest.main()
