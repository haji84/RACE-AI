"""Private display of exact existing native outputs; all inputs are fictional."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import json
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.existing_model_coverage import catalog
from race_ai import existing_model_dispatch as dispatch
from tests.test_existing_model_dispatch import (
    schedule, inputs, slot, ab_fixture, full_fixture, observed_fixture,
    shared_fixture, auto_fixture, clite_fixture, tactical_fixture, FORECAST_AT,
)

try:
    M = importlib.import_module("race_ai.dispatch_product_projection")
except ModuleNotFoundError:
    M = None


def shared_report(sport="horse", size=10, stages=("P0",), scope="SYNTHETIC_ONLY"):
    snap = shared_fixture(sport, size=size if sport in ("horse", "autorace") else None, scope=scope)
    race = snap["race"]
    rows = [schedule(race["race_id"], race["sales_cutoff_at"], stage, sport)[0] for stage in stages]
    report = dispatch.dispatch(rows, {race["race_id"]: {stage: {"shared": {"snapshot": snap}} for stage in stages}}, now=race["as_of"], allow_source=lambda *_: True)
    report["schedule"] = deepcopy(rows)
    return report


def predictions(view):
    return [p for row in view["records"] for p in [row["prediction"], *row["comparison_predictions"]] if p]


@patch("race_ai.existing_model_coverage.RETIRED_MODEL_IDS", frozenset())
def seller_report():
    """Invented pre-retirement originals must remain readable without new execution."""
    cards, waku = {}, {}
    for n in range(1, 9):
        rid = f"2030011518{n:02d}"; card = {"レースコード": rid}; w = {"レースコード": rid}
        for lane in range(1, 7):
            prefix = f"艇{lane}_"
            card[prefix + "全国勝率"] = str(6.5 if lane == 1 else 5.8 - .35 * (lane - 2))
            card[prefix + "級別"] = "A1" if lane == 1 else "B1"
            w[prefix + "枠番別勝率"] = str(8 + n * .1 if lane == 1 else 6.8 - .5 * (lane - 2))
        cards[rid] = card; waku[rid] = w
    rows = [schedule(rid, "2030-01-15T10:00:00+09:00", "P0")[0] for rid in cards]
    raw = {rid: {"P0": {"seller": {"scope": "SYNTHETIC_ONLY", "cards": cards, "waku": waku, "day": "2030-01-15"}}} for rid in cards}
    report = dispatch.dispatch(rows, raw, now="2030-01-15T06:30:00+09:00")
    report["schedule"] = rows
    return report


def pdca_report():
    facts = {"schema": "RACE_AI_BOAT_OBSERVATION_V1", "phase": "post_exhibition", "race_id": "20301103-18-05",
             "cutoff_at": "2030-11-03T10:30:00+09:00", "captured_at": "2030-11-03T10:14:50+09:00",
             "source_url": "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=5&jcd=18&hd=20301103",
             "source_sha256": "a" * 64, "program_sha256": "b" * 64, "rights_verified": True, "license_purpose": "private_analysis",
             "racers": [{"lane": n, "registration_no": str(4200 + n), "national_win_rate": 5.2 + (n - 1) * .2, "exhibition_time_seconds": 6.8 + (n - 1) * .01} for n in range(1, 7)]}
    history = []
    for n in range(24):
        day = f"{1 + n // 12:02d}"; event = "2030-11-" + day
        outcome = {"race_id": f"203011{day}-18-{1+n%12:02d}", "official_top3": [1 if n < 18 else 2, 3, 4],
                   "captured_at": event + "T11:00:00+09:00", "source_sha256": hashlib.sha256(str(n).encode()).hexdigest()}
        wire = json.dumps(outcome, separators=(",", ":"))
        history.append({"report_json": wire, "report_sha256": hashlib.sha256(wire.encode()).hexdigest(), "db_saved_at": event + "T11:05:00+09:00"})
    rid = facts["race_id"]
    return dispatch.dispatch(schedule(rid, facts["cutoff_at"]), inputs(rid, "P1", boat_pdca={"scope": "SYNTHETIC_ONLY", "facts": facts, "rows": history}), now="2030-11-03T10:15:00+09:00")


def learned_report():
    from race_ai.four_sport_learning import fit_training_only
    training = []
    for n in range(1, 7):
        day = f"2030-01-{n:02d}"
        snap = json.loads(json.dumps(shared_fixture("boat")).replace("2030-01-15", day))
        training.append({"snapshot": snap, "result": {"race_id": snap["race"]["race_id"], "status": "settled", "ordered_top3": [1, 2, 3],
                         "published_at": day + "T11:00:00+09:00", "captured_at": day + "T11:05:00+09:00", "source_ref": "synthetic://official-fixture", "source_rights_ref": "synthetic-result-v1"}})
    model = fit_training_only(training, sport="boat", train_end_at="2030-01-07T23:59:00+09:00", epochs=1, now=lambda: datetime.fromisoformat("2030-01-08T00:00:00+09:00"))
    snap = shared_fixture("boat"); race = snap["race"]
    return dispatch.dispatch(schedule(race["race_id"], race["sales_cutoff_at"], "P0"), inputs(race["race_id"], "P0", shared={"snapshot": snap, "learned_model": model}), now=race["as_of"])


def all_native_reports():
    """Fifteen raw fictional dispatches exercising every existing model family."""
    reports = [learned_report(), pdca_report(), seller_report()]
    source = ab_fixture(); rid = source["race_id"]
    reports.append(dispatch.dispatch(schedule(rid, source["cutoff_at"]), inputs(rid, "P1", boat_ab={"scope": "SYNTHETIC_ONLY", "source": source}), now="2030-11-03T13:18:00+09:00"))
    source, extra, at = clite_fixture(); rid = source["race_id"]
    reports.append(dispatch.dispatch(schedule(rid, source["cutoff_at"]), inputs(rid, "P1", boat_clite={"scope": "SYNTHETIC_ONLY", "base_source": source, "extra": extra}), now=at))
    source, profiles, venue = tactical_fixture(); rid = source["race_id"]
    reports.append(dispatch.dispatch(schedule(rid, source["cutoff_at"]), inputs(rid, "P1", boat_tactical={"scope": "SYNTHETIC_ONLY", "source": source, "histories": profiles, "venue": venue}), now=FORECAST_AT))
    for group, snap in (("boat_full", full_fixture()), ("boat_observed", observed_fixture("P1")), ("boat_observed", observed_fixture("P0"))):
        stage = snap.get("stage", "P1"); rid = snap["race_id"]
        reports.append(dispatch.dispatch(schedule(rid, snap["sales_cutoff_at"], stage), inputs(rid, stage, **{group: {"snapshot": snap}}), now=snap["as_of"]))
    for sport in ("boat", "keirin", "autorace", "horse"):
        reports.append(shared_report(sport, size=10 if sport == "horse" else 8))
    for phase in ("A_PRE_TRIAL", "B_POST_TRIAL"):
        snap = auto_fixture(phase); race = snap["race"]
        reports.append(dispatch.dispatch(schedule(race["race_id"], race["sales_cutoff_at"], phase, "autorace"), inputs(race["race_id"], phase, autorace_personal={"scope": "SYNTHETIC_ONLY", "snapshot": snap}), now="2030-01-15T09:22:00+09:00"))
    return reports


class DispatchProductProjectionTests(unittest.TestCase):
    def project(self, report, status="SYNTHETIC_ONLY"):
        self.assertIsNotNone(M, "pure native dispatch-to-product projection is missing")
        return M.project_dispatch(report, dataset_status=status)

    def test_native_horse_top8_and_all_720_candidates_survive_without_mutation_or_io(self):
        report = shared_report()
        before = deepcopy(report)
        with patch("builtins.open", side_effect=AssertionError("file I/O forbidden")), patch("socket.create_connection", side_effect=AssertionError("network forbidden")), patch.object(dispatch, "run_suite", side_effect=AssertionError("model call forbidden")):
            view = self.project(report)
        self.assertEqual(report, before)
        self.assertEqual(view["schema"], "RACE_AI_PRIVATE_CYCLE_VIEW_V1")
        self.assertEqual(len(view["records"]), 1)
        row = view["records"][0]
        self.assertEqual(row["scheduled_stages"], ["P0"])
        self.assertEqual(len(row["dispatch_slots"]), 15)
        self.assertIsNone(row["participants"], "ranking tickets do not prove participant metadata")
        for p in predictions(view):
            original = slot(report, p["model_id"])
            native = original["prediction"]
            self.assertEqual(p["ordered_top8"], native["ordered_top8"])
            self.assertEqual(p["candidates"], native["candidates"])
            self.assertEqual(len(p["candidates"]), 720)
            self.assertNotIn("native_prediction", p)
            self.assertNotIn("native_context", p)
            self.assertEqual(p["native_source_reference"]["output_sha256"], original["output_sha256"])
            self.assertEqual(p["prediction_sha256"], original["prediction_sha256"])
            self.assertEqual(p["output_sha256"], original["output_sha256"])
            self.assertIsNone(p["generated_at"])
            self.assertIsNone(p["persisted_at"])
            self.assertIsNone(p["source_sha256"])
            self.assertFalse(p["external_receipt_verified"])
            self.assertFalse(p["official_metrics_eligible"])
        self.assertEqual(len(predictions(view)), 4)

    def test_schedule_only_missing_race_and_each_stage_are_visible(self):
        report = shared_report("boat", stages=("P0", "P1"))
        extra = {"race_id": "horse:2030-01-15:actual-supplied-track:2", "sport": "horse", "stage": "P0", "cutoff_at": "2030-01-15T11:00:00+09:00", "participants": [{"number": 12, "name": "fictional supplied horse"}]}
        report["schedule"].append(extra)
        row, missing = self.project(report)["records"]
        self.assertEqual(row["scheduled_stages"], ["P0", "P1"])
        self.assertEqual(len(row["comparison_predictions"]), 7)
        self.assertEqual(len(row["dispatch_slots"]), 30)
        self.assertEqual(missing["race_id"], extra["race_id"])
        self.assertEqual(missing["participants"], extra["participants"])
        self.assertIsNone(missing["prediction"])
        self.assertEqual(len(missing["dispatch_slots"]), 15)
        self.assertIn("NO_SAVED_PREDICTION", missing["missing_reasons"])
        self.assertTrue(all(s["reason"] == "DISPATCH_SLOT_MISSING" for s in missing["dispatch_slots"]))

    def test_bare_report_and_saved_operation_wrapper_have_identical_projection(self):
        report = shared_report("keirin")
        self.assertEqual(self.project(report), self.project({"dispatch": report, "independent_receipts_verified": True}))

    def test_flags_and_report_or_slot_identity_tampering_fail_closed(self):
        report = shared_report()
        for field, value in (("new_model_created", True), ("source_requests", 1), ("research_only", False), ("originals_overwritten", True)):
            bad = deepcopy(report); bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.project(bad)
        for field, value in (("sport", "boat"), ("stage", "P1"), ("model_id", "invented-model"), ("cutoff_at", "2030-01-15T11:00:00+09:00"), ("output_sha256", "a" * 64)):
            bad = deepcopy(report); next(s for s in bad["slots"] if s["prediction"])[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.project(bad)
        bad = deepcopy(report); next(s for s in bad["slots"] if s["prediction"])["prediction"]["ordered_top8"][0] = [99, 98, 97]
        with self.assertRaises(ValueError):
            self.project(bad)

    def test_conflicting_cutoff_and_duplicate_slot_fail_closed(self):
        report = shared_report("boat", stages=("P0", "P1"))
        bad = deepcopy(report); bad["schedule"][1]["cutoff_at"] = "2030-01-15T11:00:00+09:00"
        with self.assertRaises(ValueError):
            self.project(bad)
        bad = deepcopy(report); bad["slots"].append(deepcopy(bad["slots"][0]))
        with self.assertRaises(ValueError):
            self.project(bad)

    def test_research_scope_and_independent_flags_cannot_be_upgraded(self):
        view = self.project(shared_report("boat", scope="OPERATOR_SUPPLIED_RESEARCH"), "REAL_REPORTED")
        self.assertEqual(view["records"][0]["scope"], "research")
        for key in ("independent_receipts_verified", "schedule_completeness_proven", "all_models_operational", "official_metrics_eligible"):
            self.assertIs(view[key], False)
        with self.assertRaises(ValueError):
            self.project(shared_report(), "official")

    def test_known_synthetic_and_research_scopes_cannot_be_relabelled(self):
        with self.assertRaisesRegex(ValueError, "scope"):
            self.project(shared_report("boat"), "REAL_REPORTED")
        with self.assertRaisesRegex(ValueError, "scope"):
            self.project(shared_report("boat", scope="OPERATOR_SUPPLIED_RESEARCH"))

    def test_unknown_schedule_metadata_stays_null_without_losing_an_actual_missing_race(self):
        rows = schedule("supplied-race-42", "2030-01-15T11:00:00+09:00", "P0", "horse")
        report = dispatch.dispatch(rows, {}, now="2030-01-15T09:00:00+09:00")
        row = self.project(report)["records"][0]
        self.assertEqual(row["race_id"], "supplied-race-42")
        self.assertIsNone(row["venue"])
        self.assertIsNone(row["race_no"])
        self.assertIsNone(row["participants"])
        self.assertTrue(row["native_dispatch_view"])
        self.assertIn("SAVED_RACE_METADATA_MISSING", row["missing_reasons"])

    def test_invalid_offering_status_is_rejected_before_emitting_an_invalid_web_view(self):
        report = shared_report("boat")
        report["schedule"][0]["offering_status"] = "CORRUPTED"
        with self.assertRaisesRegex(ValueError, "offering"):
            self.project(report)

    def test_later_saved_race_metadata_fills_null_without_overwriting_a_known_identity(self):
        rows = schedule("supplied-race-42", "2030-01-15T11:00:00+09:00", "P0", "horse")
        rows.append({**rows[0], "stage": "P1", "venue": "supplied-track", "race_no": 2})
        report = dispatch.dispatch(rows, {}, now="2030-01-15T09:00:00+09:00"); report["schedule"] = rows
        row = self.project(report)["records"][0]
        self.assertEqual(row["venue"], "supplied-track")
        self.assertEqual(row["race_no"], 2)
        self.assertEqual(row["scheduled_stages"], ["P0", "P1"])
        bad = deepcopy(report); bad["schedule"][0]["venue"] = "conflicting-track"
        with self.assertRaisesRegex(ValueError, "conflicting race metadata"):
            self.project(bad)

    def test_seller_daily_batch_selects_exact_target_row_preserving_three_and_five_plans(self):
        report = seller_report(); before = deepcopy(report)
        view = self.project(report)
        self.assertEqual(len(view["records"]), 8)
        self.assertEqual(len(predictions(view)), 5)
        for row in view["records"]:
            original = next(s for s in report["slots"] if s["race_id"] == row["race_id"] and s["model_id"] == "seller-shadow-v1-20261104")
            if original["prediction"] is None:
                self.assertIsNone(row["prediction"])
                self.assertEqual(next(s for s in row["dispatch_slots"] if s["model_id"] == original["model_id"])["status"], "RULE_FILTERED")
                continue
            target = next(r for r in original["prediction"]["rows"] if r["race_id"] == row["race_id"])
            p = row["prediction"]
            self.assertEqual(p["native_ticket_plans"], target["tickets"])
            self.assertEqual(p["ordered_top8"], [[int(n) for n in t["ticket"].split("-")] for t in target["tickets"]["five"]])
            self.assertEqual(len(p["ordered_top8"]), 5)
            self.assertFalse(p["native_top8_available"])
            self.assertEqual(p["candidate_order_scope"], "SAVED_FIVE_TICKET_PLAN_ONLY")
            self.assertNotIn("native_prediction", p)
            self.assertIsNone(p["prediction_sha256"])
            self.assertEqual(p["output_sha256"], original["output_sha256"])
            self.assertEqual(p["hash_basis"], "NATIVE_OUTPUT_CONTENT")
            self.assertIn("NATIVE_PREDICTION_SHA_NOT_SAVED", p["missing_reasons"])
        self.assertEqual(report, before)

    def test_all_sixteen_original_native_algorithms_are_representable(self):
        represented = set()
        for report in all_native_reports():
            with self.subTest(generated=[s["model_id"] for s in report["slots"] if s["prediction"]]):
                before = deepcopy(report); view = self.project(report)
                expected = [s for s in report["slots"] if s["prediction"] is not None]
                self.assertEqual(len(predictions(view)), len(expected))
                for row in view["records"]:
                    for p in predictions({"records": [row]}):
                        original = next(s for s in expected if s["model_id"] == p["model_id"] and s["race_id"] == row["race_id"])
                        represented.add(p["model_id"])
                        self.assertEqual(p["native_source_reference"]["output_sha256"], original["output_sha256"])
                        self.assertEqual(p["prediction_sha256"], original["prediction_sha256"])
                        self.assertEqual(p["output_sha256"], original["output_sha256"])
                        self.assertEqual(p["stage"], original["stage"])
                        if p["model_id"] == dispatch.LEARNED_ID:
                            self.assertNotEqual(p["model_sha256"], p["prediction_sha256"])
                self.assertEqual(report, before)
        self.assertEqual(represented, {s["model_id"] for s in catalog()})

    def test_unrepresentable_native_ranking_keeps_its_slot_without_inventing_prediction(self):
        report = shared_report("boat")
        original = next(s for s in report["slots"] if s["prediction"])
        del original["prediction"]["candidates"]
        p = original["prediction"]
        p["prediction_sha256"] = digest({k: v for k, v in p.items() if k != "prediction_sha256"})
        original["prediction_sha256"] = p["prediction_sha256"]; original["output_sha256"] = digest(p)
        row = self.project(report)["records"][0]
        self.assertEqual(len(predictions({"records": [row]})), 3)
        coverage = next(s for s in row["dispatch_slots"] if s["model_id"] == original["model_id"])
        self.assertEqual(coverage["status"], "GENERATED_UNATTESTED")
        self.assertEqual(coverage["projection_status"], "UNREPRESENTABLE")
        self.assertEqual(coverage["projection_reason"], "NATIVE_RANKING_UNREPRESENTABLE")

    def test_unknown_candidate_shapes_fail_closed_as_an_explicit_slot_reason(self):
        report = shared_report("boat")
        original = next(s for s in report["slots"] if s["prediction"])
        p = original["prediction"]
        p["candidates"][0]["unrecognized_market_odds"] = 10
        p["prediction_sha256"] = digest({k: v for k, v in p.items() if k != "prediction_sha256"})
        original["prediction_sha256"] = p["prediction_sha256"]; original["output_sha256"] = digest(p)
        row = self.project(report)["records"][0]
        self.assertEqual(next(s for s in row["dispatch_slots"] if s["model_id"] == original["model_id"])["projection_status"], "UNREPRESENTABLE")

    def test_native_hash_absence_is_preserved_and_never_filled_with_output_hash(self):
        report = pdca_report()
        p = predictions(self.project(report))[0]
        native = slot(report, p["model_id"])["prediction"]
        self.assertIsNone(p["prediction_sha256"])
        self.assertEqual(p["hash_basis"], "NATIVE_OUTPUT_CONTENT")
        self.assertEqual(p["candidates"], [r["ticket"] for r in native["all120"]])
        self.assertEqual(p["native_stage"], "post_exhibition")
        self.assertIsNone(p["model_version"])
        self.assertIsNone(p["generated_at"])
        self.assertIsNone(p["persisted_at"])

    def test_ab_parent_metadata_is_bound_to_native_model_without_borrowing_its_hash(self):
        source = ab_fixture(); rid = source["race_id"]
        report = dispatch.dispatch(schedule(rid, source["cutoff_at"]), inputs(rid, "P1", boat_ab={"scope": "SYNTHETIC_ONLY", "source": source}), now="2030-11-03T13:18:00+09:00")
        before = deepcopy(report)
        for p in predictions(self.project(report)):
            original = slot(report, p["model_id"])
            self.assertEqual(p["prediction_sha256"], original["prediction"]["model_sha256"])
            self.assertEqual(p["generated_at"], original["native_context"]["generated_at"])
            self.assertEqual(p["source_sha256"], original["native_context"]["source_sha256"])
            self.assertEqual(p["native_source_reference"]["parent_context_sha256"], original["native_context"]["bundle_sha256"])
            self.assertNotEqual(p["prediction_sha256"], p["native_source_reference"]["parent_context_sha256"])
        self.assertEqual(report, before)
        original = next(s for s in report["slots"] if s["prediction"])
        original["native_context"]["race_id"] = "20301103-17-06"
        context = original["native_context"]
        context["bundle_sha256"] = digest({k: v for k, v in context.items() if k != "bundle_sha256"})
        with self.assertRaises(ValueError):
            self.project(report)

    def test_native_runtime_failure_is_visible_without_fabricated_forecast(self):
        report=shared_report("boat")
        slot=next(s for s in report["slots"] if s["status"]=="GENERATED_UNATTESTED")
        slot.update(status="EXECUTION_FAILED",reason="NATIVE_EXECUTION_EXCEPTION",
                    prediction=None,prediction_sha256=None,output_sha256=None,model_version=None,
                    dispatch_generated_at=None)
        report["status_counts"]=dict(Counter(s["status"] for s in report["slots"]))
        view=self.project(report)
        coverage=next(s for s in view["records"][0]["dispatch_slots"] if s["model_id"]==slot["model_id"])
        self.assertEqual(coverage["status"],"EXECUTION_FAILED")
        self.assertEqual(coverage["projection_status"],"NO_PREDICTION")
        self.assertEqual(coverage["projection_reason"],"NATIVE_EXECUTION_EXCEPTION")
        self.assertIsNone(coverage["output_sha256"])

    def test_report_counts_and_explicit_model_version_pins_are_validated(self):
        report = shared_report("boat")
        bad = deepcopy(report); bad["status_counts"]["GENERATED_UNATTESTED"] += 1
        with self.assertRaises(ValueError):
            self.project(bad)
        bad = deepcopy(report)
        p = next(s for s in bad["slots"] if s["prediction"])
        bad["schedule"][0]["model_versions"] = {p["model_id"]: "different-saved-version"}
        with self.assertRaises(ValueError):
            self.project(bad)

    def test_retained_original_is_counted_but_cannot_fill_a_different_requested_version(self):
        first = shared_report("boat")
        original = next(s for s in first["slots"] if s["prediction"])
        rows = deepcopy(first["schedule"])
        rows[0]["model_versions"] = {original["model_id"]: "unavailable-v2"}
        report = dispatch.dispatch(rows, {}, now="2030-01-15T09:20:00+09:00", originals=[original])
        report["schedule"] = rows
        view = self.project(report)
        self.assertEqual(view["retained_original_count"], 1)
        self.assertIsNone(view["records"][0]["prediction"])
        target = next(s for s in view["records"][0]["dispatch_slots"] if s["model_id"] == original["model_id"])
        self.assertEqual(target["status"], "INPUT_MISSING")

    def test_comparison_limit_fails_explicitly_without_silently_dropping_models_or_versions(self):
        report = shared_report("horse")
        template = next(s for s in report["slots"] if s["prediction"])
        report["slots"] = [s for s in report["slots"] if s["model_id"] != template["model_id"]]
        for n in range(63):
            saved = deepcopy(template); saved["model_version"] = "saved-v" + str(n)
            p = saved["prediction"]; p["model_version"] = saved["model_version"]
            p["prediction_sha256"] = digest({k: v for k, v in p.items() if k != "prediction_sha256"})
            saved["prediction_sha256"] = p["prediction_sha256"]; saved["output_sha256"] = digest(p)
            report["slots"].append(saved)
        from collections import Counter
        report["status_counts"] = dict(Counter(s["status"] for s in report["slots"]))
        with self.assertRaisesRegex(ValueError, "comparison prediction limit"):
            self.project(report)


if __name__ == "__main__":
    unittest.main()
