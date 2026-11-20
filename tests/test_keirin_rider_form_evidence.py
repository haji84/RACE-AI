"""Only invented historical results, not evidence of actual injury/recovery."""
from copy import deepcopy
import unittest

from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_rider_form_evidence as form
from race_ai import keirin_form_fall_shadow as shadow
from tests.test_keirin_nationwide_auto_generator import fixture

ASOF = "2026-11-18T09:00:00+09:00"
AT = "2026-11-18T09:01:00+09:00"


def result(n, place, *, status="FINISHED"):
    return {"race_id":f"202611{n:02d}2601","race_date":f"2026-11-{n:02d}",
            "status":status, "place":place if status=="FINISHED" else None,
            "field_size":7,"published_at":"2026-11-18T08:00:00+09:00",
            "source_sha256":"e"*64}


def pack(*, results=None, absences=None, comments=None):
    return {"schema":shadow.SUPPLEMENT_SCHEMA, "race_id":"202611182601",
            "source_pages":[{
                "kind":"PROGRAM","url":"https://example.org/synthetic-history",
                "bytes_sha256":"e"*64,"captured_at":ASOF}],
            "condition_evidence":{
                "schema":form.SCHEMA,"as_of":ASOF,
                "riders":[{
                    "car":1, "results":results or [],
                    "absences":absences or [],"comments":comments or []}]}}


def compute(supp):
    snap=fixture()
    original=core.generate_A_B(snap,generated_at=AT)
    return snap,original,shadow.generate_shadow(
        snap,supp,baseline=original,generated_at=AT)


class PreCutoffFormFallResearch(unittest.TestCase):
    def test_old_generator_is_not_modified_or_conditioned_by_default(self):
        snap=fixture()
        before=deepcopy(snap)
        original=core.generate_A_B(snap,generated_at=AT)
        self.assertEqual(original,core.generate_A_B(snap,generated_at=AT))
        self.assertEqual(snap,before)
        self.assertNotIn("condition",original["A"])
        self.assertEqual(original["prediction_sha256"],core.digest({
            k:v for k,v in original.items() if k!="prediction_sha256"}))

    def test_negative_recent_results_create_traceable_shadow_and_preserve_original(self):
        supplement=pack(results=[
            result(1,1), result(2,1), result(3,1),
            result(5,7), result(6,7), result(7,7)])
        before=deepcopy(supplement)
        snap,base,out=compute(supplement)
        self.assertEqual(out["schema"],shadow.SCHEMA)
        self.assertEqual(out["baseline_prediction_sha256"],base["prediction_sha256"])
        self.assertEqual(out["baseline_source_sha256"],core.digest(snap))
        self.assertEqual(out["sha256"],core.digest({
            k:v for k,v in out.items() if k!="sha256"}))
        rider=out["rider_assessments"][0]
        self.assertEqual(rider["trend"],"DECLINING")
        self.assertLess(rider["score_adjustment"],0)
        self.assertEqual(out["B_research"]["model"],"six-phase-plus-documented-form-v1")
        self.assertEqual(len(out["B_research"]["branch_condition_factors"]),
                         len(base["B"]["six_phase_scenarios"]))
        self.assertFalse(out["historical_originals_mutated"])
        self.assertEqual(supplement,before)

    def test_separate_official_result_pages_fit_complete_roster_history(self):
        supplement = pack(results=[result(n, n) for n in range(1,7)])
        page = supplement["source_pages"][0]
        # Seven riders need six individually identified historical results;
        # one official result document per historical race is normal input.
        supplement["source_pages"] = [dict(page, bytes_sha256=f"{n:064x}")
                                      for n in range(42)]
        supplement["source_pages"].append(page)
        try:
            _, base, out = compute(supplement)
        except shadow.ConditionShadowError as exc:
            self.fail(f"Complete bounded history was rejected: {exc}")
        self.assertEqual(out["verified_source_receipt_count"], 43)
        self.assertEqual(out["baseline_prediction_sha256"],
                         base["prediction_sha256"])

    def test_excessive_condition_source_page_list_is_rejected(self):
        supplement = pack()
        supplement["source_pages"] *= 129
        with self.assertRaisesRegex(shadow.ConditionShadowError,
                                    "FORM_SUPPLEMENT_SCHEMA_OR_RACE_INVALID"):
            compute(supplement)

    def test_a_fall_without_post_return_evidence_is_not_automatic_penalty(self):
        snap,base,out=compute(pack(results=[result(4,None,status="FALL_DNF")]))
        rider=out["rider_assessments"][0]
        self.assertTrue(rider["fall_on_record"])
        self.assertEqual(rider["trend"],"INSUFFICIENT_DATA")
        self.assertEqual(rider["post_fall_trend"],"INSUFFICIENT_DATA")
        self.assertEqual(rider["score_adjustment"],0)
        self.assertIsNone(rider["documented_absence_days"])
        self.assertEqual(out["A_research"]["ranked_tickets"],
                         base["A"]["ranked_tickets"])
        self.assertEqual(out["B_research"]["ranked_tickets"],
                         base["B"]["ranked_tickets"])

    def test_fall_finish_is_not_normal_recent_form(self):
        for normal_count in (5, 6):
            with self.subTest(normal_count=normal_count):
                rows = [result(n, 1) for n in range(1, normal_count+1)]
                fall = result(normal_count+1, 7)
                fall["status"] = "FALL_FINISHED"
                rows.append(fall)
                _, base, out = compute(pack(results=rows))
                rider = out["rider_assessments"][0]
                self.assertTrue(rider["fall_on_record"])
                self.assertEqual(rider["score_adjustment"], 0)
                self.assertIsNone(rider["post_fall_change"])
                self.assertEqual(rider["recent_result_change"],
                                 None if normal_count == 5 else 0)
                self.assertEqual(out["A_research"]["ranked_tickets"],
                                 base["A"]["ranked_tickets"])

    def test_publication_must_precede_its_own_source_capture(self):
        supp = pack(results=[result(1, 1)])
        supp["source_pages"][0]["captured_at"] = "2026-11-18T08:00:00+09:00"
        supp["condition_evidence"]["riders"][0]["results"][0]["published_at"] = (
            "2026-11-18T08:30:00+09:00")
        supp["source_pages"].append({
            "kind":"PROGRAM", "url":"https://example.org/later-other-source",
            "bytes_sha256":"f"*64, "captured_at":ASOF})
        with self.assertRaisesRegex(shadow.ConditionShadowError,
                                    "FORM_PUBLISHED_AFTER_SOURCE_CAPTURE"):
            compute(supp)

    def test_documented_absence_return_and_comments_are_traced_but_not_diagnosed(self):
        supp=pack(
            results=[result(1,1),result(2,1),result(3,1),
                     result(4,None,status="FALL_DNF"),
                     result(5,7),result(6,7),result(7,7)],
            absences=[{"start":"2026-11-04","end":"2026-11-04",
                       "published_at":"2026-11-18T08:00:00+09:00",
                       "source_sha256":"e"*64}],
            comments=[{"speaker":"RIDER","text":"今日は前々に踏む",
                       "published_at":"2026-11-18T08:00:00+09:00",
                       "source_sha256":"e"*64}])
        _,_,out=compute(supp)
        row=out["rider_assessments"][0]
        self.assertEqual(row["post_fall_trend"],"DECLINING")
        self.assertEqual(row["documented_absence_days"],1)
        self.assertEqual(row["return_after_absence_results"],3)
        self.assertEqual(row["comments_count"],1)
        self.assertFalse(out["medical_recovery_or_crash_causality_inferred"])
        self.assertNotIn("今日は前々に踏む",str(out))
        self.assertEqual(out["condition_supplement_sha256"],core.digest(supp))

    def test_gaps_are_not_silently_labeled_as_rest(self):
        _,_,out=compute(pack(results=[result(1,1),result(16,2)]))
        row=out["rider_assessments"][0]
        self.assertIsNone(row["documented_absence_days"])
        self.assertIsNone(row["return_after_absence_results"])
        self.assertEqual(row["score_adjustment"],0)

    def test_unmatched_source_or_future_results_fail_closed(self):
        for mod, expected in (
            (lambda x:x["condition_evidence"]["riders"][0]["results"][0].update(
                source_sha256="f"*64),"FORM_SOURCE_SHA_UNMATCHED"),
            (lambda x:x["condition_evidence"]["riders"][0]["results"][0].update(
                published_at="2026-11-18T09:30:00+09:00"),"FORM_PUBLISHED_AFTER_INPUT_CUTOFF"),
            (lambda x:x["condition_evidence"]["riders"][0]["results"][0].update(
                race_date="2026-11-19"),"FORM_FUTURE_DUPLICATE_OR_WRONG_RACE"),
            (lambda x:x["condition_evidence"]["riders"][0]["results"][0].update(
                place=11),"FORM_FINISH_POSITION_INVALID"),
        ):
            with self.subTest(expected=expected):
                supp=pack(results=[result(1,1)])
                mod(supp)
                snap=fixture()
                base=core.generate_A_B(snap,generated_at=AT)
                with self.assertRaisesRegex(shadow.ConditionShadowError,expected):
                    shadow.generate_shadow(snap,supp,baseline=base,generated_at=AT)

    def test_incomplete_published_data_stays_unknown(self):
        _,_,out=compute(pack())
        self.assertEqual(len(out["rider_assessments"]),7)
        self.assertTrue(all(r["trend"]=="INSUFFICIENT_DATA" and
                            r["score_adjustment"]==0
                            for r in out["rider_assessments"]))

    def test_late_supplement_and_fabricated_comment_category_are_blocked(self):
        supp=pack(results=[])
        supp["source_pages"][0]["captured_at"]="2026-11-18T09:03:00+09:00"
        snap=fixture()
        base=core.generate_A_B(snap,generated_at=AT)
        with self.assertRaisesRegex(shadow.ConditionShadowError,
                                    "FORM_SOURCE_AFTER_PREDICTION_OR_CUTOFF"):
            shadow.generate_shadow(snap,supp,baseline=base,generated_at=AT)
        supp=pack(comments=[{
            "speaker":"INFERRED_INJURY","text":"とりあえず推測",
            "published_at":"2026-11-18T08:00:00+09:00",
            "source_sha256":"e"*64}])
        with self.assertRaisesRegex(shadow.ConditionShadowError,
                                    "FORM_COMMENT_INVALID"):
            shadow.generate_shadow(snap,supp,baseline=base,generated_at=AT)


if __name__=="__main__":
    unittest.main()
