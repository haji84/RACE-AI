"""Run a same-race prospective model roster on fictional evidence only."""
import copy
import hashlib
import itertools
import json
import math
import unittest
from unittest.mock import patch

from test_comprehensive_four_sport_models import sample
from race_ai import four_sport_model_suite as suite
from race_ai.four_sport_model_suite import run_suite, verify_suite, ALL_MODELS
from race_ai.comprehensive_four_sport_models import ModelInputError, digest

SIZES={"boat":6,"keirin":7,"autorace":8,"horse":18}


class ModelSuiteTest(unittest.TestCase):
    def test_three_entrant_autorace_and_horse_preserve_all_six_original_predictions(self):
        universe = set(itertools.permutations((1, 2, 3), 3))
        for sport in ("autorace", "horse"):
            with self.subTest(sport=sport):
                snapshot = sample(sport, size=3)
                before = copy.deepcopy(snapshot)
                originals = {}
                def record(producer):
                    def original_predictions(*args, **kwargs):
                        predictions = producer(*args, **kwargs)
                        originals.update(copy.deepcopy(predictions))
                        return predictions
                    return original_predictions
                with patch.object(suite, "factor_predict", side_effect=record(suite.factor_predict)), \
                     patch.object(suite, "matchup_predict", side_effect=record(suite.matchup_predict)):
                    try:
                        batch = run_suite(snapshot)
                    except ValueError as error:
                        self.fail("valid three-entrant universe was rejected: " + str(error))
                self.assertEqual(snapshot, before)
                self.assertEqual(tuple(batch["models"]), ALL_MODELS)
                self.assertEqual(batch["models"], originals)
                self.assertEqual(batch["input_sha256"], digest(before))
                self.assertTrue(verify_suite(batch))
                self.assertEqual(batch["suite_sha256"], digest({k: v for k, v in batch.items() if k != "suite_sha256"}))
                for model in batch["models"].values():
                    self.assertEqual(model["model_version"], "0.1.0-UNTRAINED")
                    self.assertEqual(model["candidate_count"], 6)
                    self.assertEqual(len(model["candidates"]), 6)
                    self.assertEqual(len(model["ordered_top8"]), 6)
                    self.assertEqual({tuple(ticket) for ticket in model["ordered_top8"]}, universe)
                    self.assertEqual(model["ordered_top8"], [row["combination"] for row in model["candidates"]])
                    self.assertAlmostEqual(math.fsum(row["score"] for row in model["candidates"]), 1.0)
                    self.assertEqual(model["snapshot_sha256"], batch["input_sha256"])
                    self.assertEqual(model["race_id"], before["race"]["race_id"])
                    self.assertEqual(model["as_of"], before["race"]["as_of"])
                    self.assertEqual(model["cutoff_at"], before["race"]["sales_cutoff_at"])
                    self.assertEqual(model["prediction_sha256"], digest({k: v for k, v in model.items() if k != "prediction_sha256"}))
                    self.assertTrue(model["odds_independent"])
                    self.assertFalse(model["trained"])
                    self.assertFalse(model["official_prediction"])
                    self.assertIsNone(model["external_pre_cutoff_receipt"])

    def test_maximum_eight_still_requires_exact_available_count_for_every_model(self):
        for sport, size, invalid_counts in (("autorace", 3, (5, 7)), ("horse", 3, (5, 7)),
                                             ("autorace", 4, (7, 9))):
            snapshot = sample(sport, size=size)
            original = {**suite.factor_predict(snapshot), **suite.matchup_predict(snapshot)}
            for name in ALL_MODELS:
                for count in invalid_counts:
                    with self.subTest(sport=sport, size=size, model=name, count=count):
                        malformed = copy.deepcopy(original)
                        picks = malformed[name]["ordered_top8"]
                        picks[:] = picks[:count]
                        while len(picks) < count:
                            picks.append(copy.deepcopy(picks[0]))
                        factors = {key: malformed[key] for key in suite.FACTOR_MODEL_IDS}
                        matchups = {key: malformed[key] for key in suite.MATCHUP_MODEL_IDS}
                        with patch.object(suite, "factor_predict", return_value=factors), \
                             patch.object(suite, "matchup_predict", return_value=matchups):
                            with self.assertRaisesRegex(ValueError, "research model contract unsafe"):
                                run_suite(snapshot)

    def test_three_entrant_support_does_not_relax_sport_size_or_real_source_rights(self):
        for sport, size in (("autorace", 2), ("horse", 2), ("boat", 5), ("boat", 7),
                            ("keirin", 6), ("keirin", 8), ("autorace", 9), ("horse", 19)):
            with self.subTest(sport=sport, size=size):
                with self.assertRaisesRegex(ModelInputError, "sport field size"):
                    run_suite(sample(sport, size=size))
        for sport in ("autorace", "horse"):
            with self.subTest(sport=sport, unadmitted=True):
                with self.assertRaisesRegex(ModelInputError, "rights not externally admitted"):
                    run_suite(sample(sport, size=3, scope="OPERATOR_SUPPLIED_RESEARCH"))

    def test_three_entrant_permissioned_delivery_typed_roundtrip_preserves_original_hashes(self):
        from tests.test_permissioned_source_delivery import AT, gate, snapshot
        from race_ai.permissioned_source_delivery import FEED_SCHEMA, deliver
        from race_ai.private_delivery_codec import serialize_private_delivery, deserialize_private_delivery
        for sport in ("autorace", "horse"):
            with self.subTest(sport=sport):
                source_snapshot = snapshot(sport)
                source_snapshot["participants"] = source_snapshot["participants"][:3]
                raw = json.dumps({"schema": FEED_SCHEMA, "snapshot": source_snapshot},
                                 sort_keys=True, separators=(",", ":")).encode("utf-8")
                before = copy.deepcopy(source_snapshot)
                policy = gate()  # Fictional purposes only; no real authority or transport.
                try:
                    original = deliver(raw, policy, at=AT, persist=False)
                except ValueError as error:
                    self.fail("valid three-entrant delivery was rejected: " + str(error))
                unchanged = copy.deepcopy(original)
                wire = serialize_private_delivery(original)
                restored = deserialize_private_delivery(wire, expected_delivery_sha256=original["delivery_sha256"])
                self.assertEqual(source_snapshot, before)
                self.assertEqual(original, unchanged)
                self.assertEqual(restored, unchanged)
                self.assertEqual(wire, serialize_private_delivery(restored))
                self.assertLessEqual(len(wire), 4 * 1024 * 1024)
                self.assertEqual(restored["source_payload_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(restored["policy_record_sha256"], policy.document_sha256)
                self.assertEqual(restored["feature_snapshot_sha256"], digest(before))
                self.assertTrue(verify_suite(restored["research_suite"]))
                for name, model in restored["research_suite"]["models"].items():
                    self.assertEqual(model, unchanged["research_suite"]["models"][name])
                    self.assertEqual(model["candidate_count"], 6)
                    self.assertEqual(len(model["ordered_top8"]), 6)
                self.assertFalse(restored["official_prediction"])
                self.assertFalse(restored["source_terms_independently_verified_by_code"])
                self.assertFalse(restored["can_count_in_hit_at_8"])
                self.assertIsNone(restored["external_receipt"])

    def test_all_models_on_every_sport_exact_same_snapshot_and_cutoff(self):
        for sport,n in SIZES.items():
            with self.subTest(sport=sport):
                s=sample(sport,size=n)
                batch=run_suite(s)
                self.assertTrue(verify_suite(batch))
                self.assertEqual(batch["ranked_model_ids"],list(ALL_MODELS))
                self.assertEqual(batch["model_count"],4)
                self.assertEqual(batch["official_prediction"],False)
                self.assertIsNone(batch["external_timestamp_receipts"])
                for m in batch["models"].values():
                    self.assertEqual(m["snapshot_sha256"],batch["input_sha256"])
                    self.assertEqual(m["candidate_count"],n*(n-1)*(n-2))
                    self.assertEqual(len(m["ordered_top8"]),8)
                    self.assertEqual(m["cutoff_at"],batch["sales_cutoff_at"])

    def test_real_scope_has_no_implicit_permission(self):
        s=sample("keirin",scope="OPERATOR_SUPPLIED_RESEARCH")
        with self.assertRaisesRegex(ModelInputError,"rights not externally admitted"):
            run_suite(s)

    def test_mutation_of_one_model_cannot_pass_suite_integrity(self):
        batch=run_suite(sample("boat"))
        bad=copy.deepcopy(batch)
        bad["models"][ALL_MODELS[0]]["ordered_top8"][0]=[6,5,4]
        self.assertFalse(verify_suite(bad))
        missing=copy.deepcopy(batch)
        del missing["models"][ALL_MODELS[-1]]
        self.assertFalse(verify_suite(missing))

    def test_repeatable_same_features_and_weather_change(self):
        s=sample("horse",size=12)
        x=run_suite(s)
        self.assertEqual(x,run_suite(copy.deepcopy(s)))
        updated=copy.deepcopy(s)
        updated["environment"]["rain_mm_h"]["value"]=90
        updated["environment"]["surface_wetness"]["value"]=.9
        y=run_suite(updated)
        self.assertNotEqual(x["input_sha256"],y["input_sha256"])
        self.assertNotEqual(x["models"][ALL_MODELS[-1]]["scenario_weights"],
                            y["models"][ALL_MODELS[-1]]["scenario_weights"])


    def test_train_only_learned_model_is_optional_fifth_model(self):
        from test_four_sport_learning import fit_rows, dataset, future
        from race_ai.four_sport_learning import LEARNED_ID
        model=fit_rows(dataset("boat"),sport="boat")
        batch=run_suite(future("boat"),learned_model=model)
        self.assertTrue(verify_suite(batch))
        self.assertEqual(batch["model_count"],5)
        self.assertEqual(batch["ranked_model_ids"][-1],LEARNED_ID)
        self.assertTrue(batch["models"][LEARNED_ID]["trained"])
        self.assertFalse(batch["models"][LEARNED_ID]["calibrated"])
        self.assertIsNone(batch["external_timestamp_receipts"])
        assert batch["models"][LEARNED_ID]["official_prediction"] is False

    def test_wrong_sport_learned_model_rejected_instead_of_retrained(self):
        from test_four_sport_learning import fit_rows, dataset, future
        from race_ai.comprehensive_four_sport_models import ModelInputError
        model=fit_rows(dataset("boat"),sport="boat")
        with self.assertRaisesRegex(ModelInputError,"version/sport"):
            run_suite(future("horse"),learned_model=model)

    def test_no_results_odds_money_or_official_picks_produced(self):
        x=run_suite(sample("boat"))
        self.assertEqual(x["purchase_decision"],"NO_BET")
        self.assertIsNone(x["official_result"])
        for model in x["models"].values():
            self.assertNotIn("market_odds",model)
            self.assertNotIn("payout_yen",model)
            self.assertFalse(model["official_prediction"])
            self.assertIsNone(model["external_pre_cutoff_receipt"])


if __name__=="__main__":
    unittest.main()
