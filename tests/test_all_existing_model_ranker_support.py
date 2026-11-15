"""Fictional ranker support, retrospective metrics and admitted-purpose routing."""
from copy import deepcopy
import math
import unittest

from race_ai.actions_contract import digest
from race_ai import all_existing_model_learning as learning
from race_ai.four_sport_learning import LEARNED_ID, forecast, _vectors
from race_ai.comprehensive_four_sport_models import HISTORICAL_HORSE_FEATURES, HISTORY_TRANSFORM, ModelInputError
from tests.test_all_existing_model_matrix import native_records, NOW
from tests.test_comprehensive_four_sport_models import obs


class AllExistingRankerSupportTests(unittest.TestCase):
    def fit(self, rows=None, sport="horse", **options):
        rows = native_records(LEARNED_ID, sport) if rows is None else rows
        training = learning.fit(rows, now=NOW, **options)
        self.assertTrue(learning.verify_training(training))
        return training, training["models"][sport+"/"+LEARNED_ID]

    def test_absent_neutral_history_and_constant_masks_have_zero_support_and_weights(self):
        training, model = self.fit()
        for feature in HISTORICAL_HORSE_FEATURES:
            for name in (feature, "observed_"+feature):
                with self.subTest(feature=name):
                    self.assertEqual(model["parameter_support_train"][name], 0)
                    self.assertEqual(model["parameters"][name], 0.)
        self.assertEqual(model["parameter_support_train"]["ability"], 6)
        self.assertEqual(model["native_training"]["parameter_support_train"], model["parameter_support_train"])
        self.assertEqual(model["native_training"]["minimum_supported_train_races"], 4)
        self.assertEqual(training["created_at"], NOW.isoformat())

    def test_three_discriminating_train_races_freeze_feature_throughout_optimizer(self):
        rows = native_records(LEARNED_ID, "horse")
        feature = HISTORICAL_HORSE_FEATURES[0]
        for row in rows[:3]+rows[6:]:
            for index, participant in enumerate(row["native_payload"]["snapshot"]["participants"]):
                observation = obs(.1+.35*index)
                observation["transform_id"] = HISTORY_TRANSFORM
                participant["features"][feature] = observation
            row["input_sha256"] = digest(row["native_payload"])
        before = deepcopy(rows)
        _, fitted = self.fit(rows)
        _, baseline = self.fit()
        self.assertEqual(fitted["parameter_support_train"][feature], 3)
        self.assertEqual(fitted["parameter_support_train"]["observed_"+feature], 0)
        self.assertEqual(fitted["parameters"][feature], 0.)
        # Unsupported weights must never influence the other gradient updates;
        # zeroing them only after an unrestricted fit would fail this check.
        self.assertEqual(fitted["parameters"], baseline["parameters"])
        self.assertEqual(rows, before)

    def test_four_sports_get_actual_six_two_native_likelihood_and_hit_metrics(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            rows = native_records(LEARNED_ID, sport)
            _, model = self.fit(rows, sport=sport)
            weights = model["native_training"]["weights"]
            for cohort, expected_n, source_rows in (("training", 6, rows[:6]), ("holdout", 2, rows[6:])):
                with self.subTest(sport=sport, cohort=cohort):
                    report = model[cohort]
                    self.assertEqual(report["races"], expected_n)
                    self.assertFalse(report["prospective"])
                    self.assertEqual(report["validation_type"], "RETROSPECTIVE_NATIVE_DISTRIBUTION")
                    losses = []
                    for row in source_rows:
                        vectors = _vectors(row["native_payload"]["snapshot"], sport)
                        utility = {number: math.fsum(w*x for w,x in zip(weights, vector)) for number,vector in vectors.items()}
                        remaining = sorted(vectors)
                        probability = 1.
                        for chosen in row["result"]["ordered_top3"]:
                            top = max(utility[number] for number in remaining)
                            denominator = math.fsum(math.exp(utility[number]-top) for number in remaining)
                            probability *= math.exp(utility[chosen]-top)/denominator
                            remaining.remove(chosen)
                        losses.append(-math.log(probability))
                    self.assertAlmostEqual(report["mean_log_loss"], math.fsum(losses)/expected_n, places=12)
                    self.assertEqual(report["hit_rate"], report["hits"]/expected_n)
                    self.assertEqual(report["selected_races"], expected_n)
            size = len(rows[0]["result"]["roster"])
            self.assertAlmostEqual(model["holdout_baseline"]["mean_log_loss"], math.log(size*(size-1)*(size-2)), places=12)
            with self.assertRaisesRegex(ModelInputError, "artifact creation"):
                forecast(rows[-1]["native_payload"]["snapshot"], model["native_training"])

    def test_holdout_labels_change_only_retrospective_metrics_not_native_artifact_or_support(self):
        rows = native_records(LEARNED_ID, "horse")
        changed = deepcopy(rows)
        for row in changed[6:]:
            row["result"]["ordered_top3"] = list(reversed(row["result"]["ordered_top3"]))
            row["result"]["source_sha256"] = digest(row["result"]["ordered_top3"])
        _, original = self.fit(rows)
        _, fitted = self.fit(changed)
        self.assertEqual(original["native_training"], fitted["native_training"])
        self.assertEqual(original["parameters"], fitted["parameters"])
        self.assertEqual(original["parameter_support_train"], fitted["parameter_support_train"])
        self.assertEqual(original["training"], fitted["training"])
        self.assertNotEqual(original["holdout"]["mean_log_loss"], fitted["holdout"]["mean_log_loss"])

    def test_four_rankers_use_genuine_artifacts_on_later_native_prediction_inputs(self):
        from tests import test_all_existing_model_matrix as matrix
        from race_ai import all_existing_model_registry as registry
        for sport in ("boat", "keirin", "autorace", "horse"):
            training, model = self.fit(sport=sport)
            # This is an actually fitted native artifact, not an invented zero
            # reference model. It existed before this later fictional input.
            native = matrix._shift_dates(matrix.native_payload(LEARNED_ID, sport), 800)
            native["learned_model"] = deepcopy(model["native_training"])
            at = learning.ts(registry.identity(LEARNED_ID, sport, native)["as_of"])
            pair = learning.forecast_pair(training, sport+"/"+LEARNED_ID, native, now=at)
            with self.subTest(sport=sport):
                self.assertEqual(pair["baseline"]["model_sha256"], pair["learned"]["model_sha256"])
                self.assertEqual(pair["baseline_normalized"]["roster"], pair["learned_normalized"]["roster"])
                self.assertEqual(pair["baseline_normalized"]["top"], pair["learned_normalized"]["top"])
                self.assertEqual(pair["training_sha256"], training["training_sha256"])
                self.assertFalse(pair["production_promoted"])

    def test_rehashed_native_support_metadata_cannot_disagree_with_outer_fit(self):
        training, _ = self.fit()
        for field, value in (("minimum_supported_train_races", 0), ("support_policy", "UNSUPPORTED"),
                             ("parameter_support_train", {})):
            changed = deepcopy(training)
            model = changed["models"]["horse/"+LEARNED_ID]
            model["native_training"][field] = value
            learning.seal(model["native_training"], "model_sha256")
            learning.seal(model, "model_sha256"); learning.seal(changed, "training_sha256")
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "NATIVE_TRAINING_BINDING"):
                learning.verify_training(changed)

    def test_real_ranker_uses_exact_already_admitted_result_pair_with_training_purpose(self):
        rows = native_records(LEARNED_ID, "horse")
        for row in rows:
            row["scope"] = "OPERATOR_SUPPLIED_RESEARCH"
            row["native_payload"]["scope"] = "OPERATOR_SUPPLIED_RESEARCH"
            row["native_payload"]["snapshot"]["scope"] = "OPERATOR_SUPPLIED_RESEARCH"
            row["input_sha256"] = digest(row["native_payload"])
        calls = []
        def training_allowed(source, rights, purpose):
            calls.append((source, rights, purpose))
            return purpose == "model_training"
        training, model = self.fit(rows, allow_source=lambda _source,_rights,purpose: purpose == "analysis",
                                   allow_training=training_allowed)
        self.assertEqual({purpose for _,_,purpose in calls}, {"model_training"})
        self.assertEqual(model["native_training"]["trained_scope"], "OPERATOR_SUPPLIED_RESEARCH")
        self.assertFalse(training["provider_permission_confirmed"])


if __name__ == "__main__":
    unittest.main()
