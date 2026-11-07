"""Sparse active native models retain bounded fitted-parameter effects."""
from copy import deepcopy
import math
import unittest

from race_ai import comprehensive_four_sport_models as factor
from race_ai import four_sport_matchup_models as matchup
from race_ai import existing_common_parameter_adapters as adapter
from tests.test_comprehensive_four_sport_models import sample

MODELS = factor.MODEL_IDS + matchup.MODEL_IDS
AT = "2030-01-15T09:10:00+09:00"


def sparse(lanes=(1, 3, 6), *, start=False, snapshot=None):
    snapshot = sample("boat") if snapshot is None else deepcopy(snapshot)
    snapshot["schema"] = factor.SCHEMA_SPARSE
    snapshot["participants"] = [p for p in snapshot["participants"] if p["number"] in lanes]
    allowed = set(factor.COMMON_REQUIRED + factor.SPORT_REQUIRED["boat"] + factor.SPORT_OPTIONAL["boat"])
    keep = {"ability", "motor_form"} | ({"start_reliability"} if start else set())
    for p in snapshot["participants"]:
        p["features"] = {k: v for k, v in p["features"].items() if k in keep}
        p["missing"] = {k: "NOT_AVAILABLE" for k in allowed - p["features"].keys()}
        for observation in p["features"].values():
            observation.update(source_sha256="a"*64, published_at=None)
    snapshot["environment"] = {}
    snapshot["environment_missing"] = {k: "NOT_AVAILABLE" for k in factor.ENV_COMMON + factor.ENV_SPORT["boat"]}
    return snapshot


class CommonSparseParameterMergeTests(unittest.TestCase):
    def test_available_parameter_changes_exact_native_terms_for_all_active_sizes(self):
        for lanes in ((1, 3, 6), (1, 2, 4, 6), (1, 3, 4, 5, 6), tuple(range(1, 7))):
            snapshot = sparse(lanes)
            original = deepcopy(snapshot)
            for mid in MODELS:
                with self.subTest(lanes=lanes, model=mid):
                    base = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
                    changed = adapter.predict(mid, {"snapshot": snapshot}, {"utility.ability": 0.}, at=AT)
                    self.assertNotEqual(changed["candidates"], base["candidates"])
                    zeroed = deepcopy(snapshot)
                    for p in zeroed["participants"]: p["features"]["ability"]["value"] = 0.
                    expected = adapter.predict(mid, {"snapshot": zeroed}, None, at=AT)
                    self.assertEqual(changed["candidates"], expected["candidates"])
                    self.assertEqual(changed["candidate_count"], math.perm(len(lanes), 3))
                    self.assertAlmostEqual(math.fsum(c["score"] for c in changed["candidates"]), 1., places=12)
                    self.assertEqual(changed["input_schema"], factor.SCHEMA_SPARSE)
                    self.assertIn("stamina", changed["missing_features_by_participant"][lanes[0]])
                    self.assertEqual(changed["research_parameters"]["utility.ability"], 0.)
                    self.assertFalse(changed["trained"])
            self.assertEqual(snapshot, original)

    def test_missing_parameters_contribute_nothing_and_observed_scenario_terms_apply(self):
        checks = ((factor.MODEL_IDS[1], "scenario.front_start"),
                  (matchup.MODEL_IDS[0], "slot.first_start"),
                  (matchup.MODEL_IDS[1], "trajectory.front_start"))
        for mid, name in checks:
            for observed in (False, True):
                with self.subTest(model=mid, observed=observed):
                    snapshot = sparse(start=observed)
                    base = adapter.predict(mid, {"snapshot": snapshot}, None, at=AT)
                    changed = adapter.predict(mid, {"snapshot": snapshot}, {name: 0.}, at=AT)
                    if observed: self.assertNotEqual(base["candidates"], changed["candidates"])
                    else: self.assertEqual(base["candidates"], changed["candidates"])

    def test_actual_native_optimizer_parameters_apply_to_sparse_observations(self):
        from race_ai import all_existing_model_learning as learning
        from tests.test_all_existing_model_matrix import native_records, NOW
        for mid in MODELS:
            rows = native_records(mid, "boat")
            for row in rows:
                snapshot = sparse(snapshot=row["native_payload"]["snapshot"])
                row["native_payload"]["snapshot"] = snapshot
                row["input_sha256"] = factor.digest(row["native_payload"])
                row["result"].update(ordered_top3=[6, 3, 1], roster={str(p["number"]): p["identity"] for p in snapshot["participants"]})
            training = learning.fit(rows, now=NOW)
            self.assertTrue(learning.verify_training(training))
            model = training["models"]["boat/"+mid]
            self.assertEqual((model["train_races"], model["validation_races"]), (6, 2))
            self.assertFalse(set(model["train_race_ids"]) & set(model["validation_race_ids"]))
            parameters, support = model["parameters"], model["parameter_support_train"]
            self.assertEqual(support["utility.ability"], 6)
            self.assertEqual(support["utility.stamina"], 0)
            self.assertEqual(parameters["utility.stamina"], adapter.specs(mid, "boat")["utility.stamina"][0])
            base = adapter.predict(mid, {"snapshot": snapshot}, None, at=rows[-1]["as_of"])
            fitted = adapter.predict(mid, {"snapshot": snapshot}, parameters, at=rows[-1]["as_of"])
            self.assertNotEqual(base["candidates"], fitted["candidates"])
            self.assertEqual(fitted["research_parameters"], parameters)
