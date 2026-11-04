"""Synthetic saved originals only; these tests establish no live accuracy."""
from copy import deepcopy
import hashlib
import importlib
import json
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.frozen_day_cycle import read_p1
from tests.test_frozen_day_cycle import observation
from tests.test_private_cycle_projection import saved_learned_archive, seal

try:
    M = importlib.import_module("race_ai.private_saved_comparison")
except ModuleNotFoundError:
    M = None


def wrapper(artifact_id, member, document):
    raw = json.dumps(document, ensure_ascii=False).encode()
    return dict(artifact_id=artifact_id, member_name=member,
                member_sha256=hashlib.sha256(raw).hexdigest(), document=deepcopy(document))


class PrivateSavedComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document, raw, cls.receipt = saved_learned_archive()
        _, cls.rows = read_p1(raw, cls.receipt)

    def setUp(self):
        self.assertIsNotNone(M, "saved-original comparison evaluator is missing")
        doc = deepcopy(self.document)
        learned = doc["learned_pairwise_shadows"][0]
        self.baseline = next(r for r in self.rows if r["model_id"] == learned["model_id"])
        native = doc["observed_pairwise_p1_bundles"][0]["suite"]["models"][learned["model_id"]]
        self.comparison = dict(comparison_id="observed-fixed-version", sport="boat", stage="P1",
            starts_at="2030-04-01T08:05:00Z", ends_at="2030-04-01T09:00:00Z",
            baseline=dict(model_id=learned["model_id"], model_version=native["model_version"]),
            learned=dict(model_id=learned["model_id"], model_version=learned["model_version"],
                         training_sha256=learned["training_sha256"]))
        self.schedule = [dict(race_id=self.baseline["race_id"], sport="boat",
                              cutoff_at=self.baseline["cutoff_at"], trifecta_offered=True)]
        result = observation(self.baseline)
        result["captured_at"] = "2030-04-01T08:31:00Z"
        training = wrapper(700, "trained_observed_models.json", learned["training"])
        self.state = dict(schema="RACE_AI_PRIVATE_ARTIFACT_READBACK_V1", day_jst="2030-04-01",
            rows=deepcopy(self.rows), observations=[result], receipts=[deepcopy(self.receipt),
                deepcopy(learned["training_receipt"]), self.result_receipt()], complete=False,
            coverage_scope="EXPLICIT_ARTIFACTS_ONLY", original_documents=[
                dict(artifact_id=self.receipt["id"], member_name="national.json",
                     member_sha256=self.rows[0]["original_json_sha256"], document=doc),
                training, wrapper(701, "official-result-observations.json", [result])])
        seal(self.state)

    def result_receipt(self, artifact_id=701, at="2030-04-01T08:40:00Z"):
        return dict(id=artifact_id, name="race-existing-cycle-99", expired=False,
                    created_at=at, digest="sha256:"+"b"*64,
                    workflow_run=dict(id=99, head_repository_id=1416489937))

    def evaluate(self, **changes):
        seal(self.state)
        args = dict(schedule=self.schedule, comparison=self.comparison,
                    evaluated_at="2030-04-01T08:45:00Z", dataset_status="SYNTHETIC_ONLY")
        args.update(changes)
        return M.evaluate_saved_comparison(self.state, **args)

    def replace_results(self, events):
        self.state["observations"] = deepcopy(events)
        self.state["original_documents"] = [d for d in self.state["original_documents"]
            if d["member_name"] != "official-result-observations.json"]
        self.state["original_documents"].append(wrapper(701, "official-result-observations.json", events))

    def test_saved_native_top8_and_separate_lineage_produce_descriptive_comparison(self):
        report = self.evaluate()
        self.assertEqual(report["denominator"]["normal_final_eligible"], 1)
        self.assertEqual(report["paired"]["races"], 1)
        race = report["races"][0]
        self.assertEqual(race["result_state"], "FINAL_NORMAL")
        self.assertEqual(race["baseline"]["prediction"]["ordered_top8"], self.baseline["top8"])
        learned = self.document["learned_pairwise_shadows"][0]
        self.assertEqual(race["learned"]["prediction"]["prediction_sha256"], learned["prediction_sha256"])
        self.assertEqual(race["learned"]["prediction"]["ordered_top8"], learned["ordered_top8"])
        self.assertEqual(race["learned"]["training_state"], "SEPARATE_SAVED_TRAINING_CONSISTENT")
        self.assertTrue(race["same_conditions"])
        self.assertEqual(race["captures"][0]["original"], self.state["observations"][0])
        self.assertEqual(race["captures"][0]["references"][0]["artifact_id"], 701)

    def test_missing_models_remain_in_the_same_eligible_race_denominator(self):
        extra = dict(race_id="20300401-24-11", sport="boat", cutoff_at="2030-04-01T08:32:00Z", trifecta_offered=True)
        self.schedule.append(extra)
        event = deepcopy(self.state["observations"][0])
        event.update(race_id=extra["race_id"], closed_at=extra["cutoff_at"], captured_at="2030-04-01T08:33:00Z")
        self.replace_results(self.state["observations"]+[event])
        report = self.evaluate()
        self.assertEqual(report["denominator"]["normal_final_eligible"], 2)
        self.assertEqual(report["models"]["baseline"]["descriptive_hit_at_8_all"], .5)
        missing = next(r for r in report["races"] if r["race_id"] == extra["race_id"])
        for role in ("baseline", "learned"):
            self.assertEqual(missing[role]["state"], "NO_SAVED_PINNED_ORIGINAL")
            self.assertEqual(missing[role]["counted_hit"], 0)

    def test_missing_learned_does_not_remove_a_saved_baseline_or_the_race(self):
        self.state["original_documents"][0]["document"]["learned_pairwise_shadows"] = []
        report = self.evaluate()
        self.assertEqual(report["denominator"]["normal_final_eligible"], 1)
        self.assertEqual(report["models"]["baseline"]["hits"], 1)
        self.assertEqual(report["models"]["learned"]["hits"], 0)
        self.assertEqual(report["paired"]["races"], 0)

    def test_version_pins_are_applied_before_any_outcome_is_examined(self):
        self.comparison["learned"]["training_sha256"] = "f"*64
        first = self.evaluate()
        changed = deepcopy(self.state["observations"][0])
        changed["data"]["top3"] = [1, 2, 3]
        changed["data"]["payouts"][0]["combination"] = [1, 2, 3]
        self.replace_results([changed])
        second = self.evaluate()
        for out in (first, second):
            self.assertEqual(out["races"][0]["learned"]["state"], "NO_SAVED_PINNED_ORIGINAL")
            self.assertEqual(out["models"]["learned"]["hits"], 0)

    def test_only_first_saved_matching_original_is_used(self):
        later = deepcopy(self.state["rows"])
        for row in later:
            row.update(artifact_id=900, server_saved_at="2030-04-01T08:12:00Z")
        self.state["rows"] = later + self.state["rows"]
        meta = deepcopy(self.receipt); meta.update(id=900, created_at="2030-04-01T08:12:00Z")
        self.state["receipts"].append(meta)
        doc = deepcopy(self.state["original_documents"][0]); doc["artifact_id"] = 900
        self.state["original_documents"].insert(0, doc)
        out = self.evaluate()
        self.assertEqual(out["races"][0]["baseline"]["prediction"]["artifact_id"], self.receipt["id"])
        self.assertEqual(out["races"][0]["learned"]["prediction"]["artifact_id"], self.receipt["id"])

    def test_first_saved_order_compares_instants_across_timezones(self):
        earlier = deepcopy(self.state["rows"])
        at = "2030-04-01T17:10:30+09:00"
        for row in earlier: row.update(artifact_id=900, server_saved_at=at)
        self.state["rows"] += earlier
        meta = deepcopy(self.receipt); meta.update(id=900, created_at=at)
        self.state["receipts"].append(meta)
        doc = deepcopy(self.state["original_documents"][0]); doc["artifact_id"] = 900
        self.state["original_documents"].append(doc)
        out = self.evaluate()
        for role in ("baseline", "learned"):
            self.assertEqual(out["races"][0][role]["prediction"]["artifact_id"], 900)

    def test_conflicting_pins_for_one_artifact_member_are_rejected(self):
        conflict = deepcopy(self.state["original_documents"][0])
        conflict["member_sha256"] = "f"*64
        self.state["original_documents"].append(conflict)
        with self.assertRaises(ValueError): self.evaluate()

    def test_native_document_cannot_claim_another_archive_member_name(self):
        self.state["original_documents"][0]["member_name"] = "forecasts.json"
        with self.assertRaises(ValueError): self.evaluate()

    def test_malformed_receipt_digest_remains_unbound_without_claiming_a_result(self):
        self.state["receipts"][-1]["digest"] = None
        out = self.evaluate()
        self.assertEqual(out["races"][0]["result_state"], "RESULT_UNBOUND")

    def test_a_candidate_cannot_substitute_its_later_baseline_for_the_first_pinned_original(self):
        changed = deepcopy(self.state["original_documents"][0])
        changed["artifact_id"] = 900
        changed["document"]["learned_pairwise_shadows"] = []
        bundle = changed["document"]["observed_pairwise_p1_bundles"][0]
        model = bundle["suite"]["models"][self.comparison["baseline"]["model_id"]]
        model["candidates"] = model["candidates"][1:] + model["candidates"][:1]
        model["ordered_top8"] = [r["combination"] for r in model["candidates"][:8]]
        model["prediction_sha256"] = digest({k:v for k,v in model.items() if k != "prediction_sha256"})
        bundle["suite"]["suite_sha256"] = digest({k:v for k,v in bundle["suite"].items() if k != "suite_sha256"})
        bundle["bundle_sha256"] = digest({k:v for k,v in bundle.items() if k != "bundle_sha256"})
        changed["member_sha256"] = digest(changed["document"])
        row = deepcopy(self.baseline)
        row.update(artifact_id=900, server_saved_at="2030-04-01T08:10:30Z",
                   model_sha256=model["prediction_sha256"], original_json_sha256=changed["member_sha256"],
                   top8=deepcopy(model["ordered_top8"]), ranked=[r["combination"] for r in model["candidates"]])
        self.state["rows"].append(row); self.state["original_documents"].append(changed)
        meta = deepcopy(self.receipt); meta.update(id=900, created_at=row["server_saved_at"])
        self.state["receipts"].append(meta)
        out = self.evaluate()
        self.assertEqual(out["races"][0]["baseline"]["prediction"]["prediction_sha256"], row["model_sha256"])
        self.assertFalse(out["races"][0]["same_conditions"])
        self.assertEqual(out["paired"]["races"], 0)

    def test_missing_separate_training_original_is_unverified_not_inferred_from_embedded_copy(self):
        self.state["original_documents"] = [d for d in self.state["original_documents"]
            if d["member_name"] != "trained_observed_models.json"]
        out = self.evaluate()
        self.assertEqual(out["races"][0]["learned"]["training_state"], "UNVERIFIED")
        self.assertEqual(out["races"][0]["learned"]["state"], "TRAINING_UNVERIFIED")
        self.assertEqual(out["models"]["learned"]["hits"], 0)
        self.assertEqual(out["paired"]["races"], 0)

    def test_later_result_capture_does_not_leak_past_the_evaluation_boundary(self):
        old = self.state["observations"][0]
        late = deepcopy(old); late.update(captured_at="2030-04-01T08:50:00Z", source_sha256="c"*64)
        late["data"]["top3"] = [1, 2, 3]; late["data"]["payouts"][0]["combination"] = [1, 2, 3]
        self.replace_results([old, late]); self.state["receipts"][-1]["created_at"] = "2030-04-01T08:51:00Z"
        out = self.evaluate()
        self.assertEqual(out["races"][0]["result_state"], "RESULT_PENDING")
        self.assertEqual(len(out["races"][0]["captures"]), 2)
        # A result archive saved only after the boundary cannot retroactively attest its older event.
        self.assertEqual(out["denominator"]["normal_final_eligible"], 0)

    def test_latest_available_bound_capture_is_used_and_all_events_survive(self):
        old = self.state["observations"][0]
        new = deepcopy(old); new.update(captured_at="2030-04-01T08:35:00Z", source_sha256="c"*64)
        new["data"]["top3"] = [1, 2, 3]; new["data"]["payouts"][0]["combination"] = [1, 2, 3]
        self.replace_results([old, new])
        out = self.evaluate()
        self.assertEqual(len(out["races"][0]["captures"]), 2)
        self.assertEqual(out["races"][0]["selected_result"]["captured_at"], new["captured_at"])

    def test_unbound_or_conflicting_capture_is_unresolved(self):
        self.state["original_documents"] = [d for d in self.state["original_documents"]
            if d["member_name"] != "official-result-observations.json"]
        out = self.evaluate()
        self.assertEqual(out["races"][0]["result_state"], "RESULT_UNBOUND")
        self.assertEqual(out["denominator"]["normal_final_eligible"], 0)
        event = self.state["observations"][0]
        conflict = deepcopy(event); conflict["source_sha256"] = "c"*64
        self.replace_results([event, conflict])
        out = self.evaluate()
        self.assertEqual(out["races"][0]["result_state"], "RESULT_CAPTURE_CONFLICT")
        self.assertEqual(len(out["races"][0]["captures"]), 2)

    def test_refund_cancel_abnormal_pending_and_rejected_are_not_misses(self):
        original = deepcopy(self.state["observations"][0])
        cases = [("REFUND_REVIEW_REQUIRED", lambda e:e["data"].update(refund_boats=[6])),
                 ("CANCELLED", lambda e:e["data"].update(status="cancelled")),
                 ("ABNORMAL_FINISH_REVIEW_REQUIRED", lambda e:e["data"]["results"][0].update(finish_status="F")),
                 ("RESULT_PENDING", lambda e:e.update(status="PENDING")),
                 ("RESULT_REJECTED", lambda e:e["data"]["results"][0].update(racer_registration_id="9999"))]
        for expected, edit in cases:
            event = deepcopy(original); edit(event); self.replace_results([event])
            out = self.evaluate()
            with self.subTest(expected=expected):
                self.assertEqual(out["races"][0]["result_state"], expected)
                self.assertEqual(out["denominator"]["normal_final_eligible"], 0)
                self.assertIsNone(out["races"][0]["baseline"]["counted_hit"])

    def test_duplicated_missing_or_contradictory_finish_positions_are_not_normal_results(self):
        original = deepcopy(self.state["observations"][0])
        cases = [("SPECIAL_SETTLEMENT_REVIEW_REQUIRED", lambda e:[r.update(finish=1) for r in e["data"]["results"]]),
                 ("RESULT_REJECTED", lambda e:e["data"]["results"][0].pop("finish")),
                 ("RESULT_REJECTED", lambda e:e["data"]["results"][0].update(finish=True)),
                 ("RESULT_REJECTED", lambda e:e["data"].update(top3=[1, 2, 3],
                    payouts=[dict(bet_type="trifecta", combination=[1, 2, 3], payout_per_100_yen=1230)]))]
        for expected, edit in cases:
            event = deepcopy(original); edit(event); self.replace_results([event])
            out = self.evaluate()
            with self.subTest(expected=expected):
                self.assertEqual(out["races"][0]["result_state"], expected)
                self.assertEqual(out["denominator"]["normal_final_eligible"], 0)

    def test_same_input_and_exact_saved_baseline_reference_are_required(self):
        model = self.state["original_documents"][0]["document"]["learned_pairwise_shadows"][0]
        model["input_sha256"] = "f"*64
        model["prediction_sha256"] = digest({k:v for k,v in model.items() if k != "prediction_sha256"})
        with self.assertRaises(ValueError): self.evaluate()

    def test_metadata_cannot_assert_official_results_or_improvement(self):
        self.state.update(independent_receipts_verified=True, official_results_authenticated=True,
                          external_time_attested=True, source_rights_verified=True, complete=True)
        out = self.evaluate(dataset_status="REAL_REPORTED")
        for flag in ("independent_receipts_verified", "official_results_authenticated",
                     "schedule_completeness_proven", "accuracy_improvement_proven", "auto_promoted"):
            self.assertFalse(out[flag], flag)
        self.assertIsNone(out["official_hit_at_8_all"])
        self.assertIsNone(out["official_recovery_rate"])
        self.assertTrue(out["research_only"])

    def test_unsupported_sport_does_not_invent_a_learned_forecast(self):
        self.comparison["sport"] = "keirin"
        out = self.evaluate()
        self.assertEqual(out["status"], "UNSUPPORTED_SAVED_SPORT")
        self.assertEqual(out["paired"]["races"], 0)

    def test_invalid_window_duplicate_schedule_or_state_seal_is_rejected(self):
        with self.assertRaises(ValueError): self.evaluate(schedule=self.schedule*2)
        invalid = dict(self.comparison, ends_at=self.comparison["starts_at"])
        with self.assertRaises(ValueError): self.evaluate(comparison=invalid)
        seal(self.state); self.state["state_sha256"] = "f"*64
        with self.assertRaises(ValueError):
            M.evaluate_saved_comparison(self.state, schedule=self.schedule, comparison=self.comparison,
                evaluated_at="2030-04-01T08:45:00Z", dataset_status="SYNTHETIC_ONLY")

    def test_evaluation_is_deterministic_without_replay_training_settlement_network_or_writes(self):
        before = deepcopy((self.state, self.schedule, self.comparison))
        with patch("race_ai.observed_weight_learning.make_shadows", side_effect=AssertionError("replay")), \
             patch("race_ai.observed_weight_learning.fit_from_verified", side_effect=AssertionError("train")), \
             patch("race_ai.observed_weight_learning.read_shadow_rows", side_effect=AssertionError("replay reader")), \
             patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("predict")), \
             patch("race_ai.frozen_day_cycle.settle", side_effect=AssertionError("settle")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
             patch("pathlib.Path.write_text", side_effect=AssertionError("write")), \
             patch("pathlib.Path.write_bytes", side_effect=AssertionError("write")):
            one = self.evaluate(); two = self.evaluate()
        self.assertEqual(one, two)
        self.assertEqual((self.state, self.schedule, self.comparison), before)


if __name__ == "__main__":
    unittest.main()
