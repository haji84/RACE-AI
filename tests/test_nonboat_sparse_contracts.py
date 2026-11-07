"""Invented observations verify native sparse contracts; no real-data claim."""
from copy import deepcopy
from datetime import datetime
import math
import unittest

from race_ai import comprehensive_four_sport_models as native
from race_ai import four_sport_learning as ranker
from race_ai import all_existing_model_registry as registry
from race_ai import existing_common_parameter_adapters as adapter
from race_ai.four_sport_model_suite import ALL_MODELS, run_suite
from tests.test_comprehensive_four_sport_models import sample
from tests.test_common_sparse_parameter_merge import sparse as boat_sparse


SIZES = {"keirin": 9, "autorace": 8, "horse": 18}
AT = "2030-01-15T09:10:00+09:00"


def sparse_snapshot(sport, *, slots=None):
    snapshot = sample(sport, size=SIZES[sport])
    snapshot["schema"] = native.SCHEMA_SPARSE
    if slots is not None:
        snapshot["participants"] = [p for p in snapshot["participants"] if p["number"] in slots]
    allowed = set(native.COMMON_REQUIRED + native.SPORT_REQUIRED[sport] + native.SPORT_OPTIONAL[sport])
    for p in snapshot["participants"]:
        p["features"] = {"ability": p["features"]["ability"]}
        p["features"]["ability"].update(source_sha256="a"*64, published_at=None, sample_n=None)
        p["missing"] = {k: "NOT_AVAILABLE" for k in allowed - p["features"].keys()}
        p["style"] = "unknown"
        p["group_id"] = None
    snapshot["environment"] = {}
    snapshot["environment_missing"] = {k: "NOT_AVAILABLE" for k in native.ENV_COMMON + native.ENV_SPORT[sport]}
    return snapshot


def training_rows(sport, count=6):
    rows = []
    for i in range(count):
        day = f"2030-01-{i+1:02d}"
        snapshot = sparse_snapshot(sport)
        snapshot["race"].update(race_id=f"{sport}:{day}:fictional:1", event_date_jst=day,
                                as_of=day+"T09:10:00+09:00", sales_cutoff_at=day+"T10:00:00+09:00")
        for p in snapshot["participants"]:
            p["features"]["ability"]["captured_at"] = day+"T08:01:00+09:00"
        rows.append(dict(snapshot=snapshot, result=dict(race_id=snapshot["race"]["race_id"],
            status="settled", ordered_top3=[3, 2, 1], published_at=None,
            captured_at=day+"T11:00:00+09:00", source_ref="synthetic://settled",
            source_rights_ref="synthetic-results", source_sha256="b"*64)))
    return rows


class NonboatSparseContractsTests(unittest.TestCase):
    def test_all_fixed_native_families_accept_only_observed_features_without_imputation(self):
        for sport in SIZES:
            snapshot = sparse_snapshot(sport)
            original = deepcopy(snapshot)
            for mid in ALL_MODELS:
                with self.subTest(sport=sport, model=mid):
                    prediction = adapter.predict(mid, {"snapshot": snapshot}, at=AT)
                    altered = adapter.predict(mid, {"snapshot": snapshot}, {"utility.ability": 0.}, at=AT)
                    self.assertNotEqual(prediction["candidates"], altered["candidates"])
                    self.assertEqual(len(prediction["candidates"]), math.perm(SIZES[sport], 3))
                    self.assertAlmostEqual(math.fsum(p["score"] for p in prediction["candidates"]), 1., places=12)
                    self.assertEqual(prediction["input_schema"], native.SCHEMA_SPARSE)
                    self.assertIn("stamina", prediction["missing_features_by_participant"][1])
            self.assertEqual(snapshot, original)

    def test_sparse_physical_slots_and_draw_survive_withdrawal_gaps_without_renumbering(self):
        cases = (("keirin", (1, 2, 3, 5, 6, 8, 9)), ("autorace", (1, 3, 8)), ("horse", (1, 7, 18)))
        for sport, slots in cases:
            snapshot = sparse_snapshot(sport, slots=slots)
            with self.subTest(sport=sport):
                self.assertEqual([p["number"] for p in native.validate(snapshot)["participants"]], list(slots))
                vectors = ranker._vectors(snapshot, sport)
                self.assertEqual(vectors[slots[-1]][-7], 1-(slots[-1]-1)/(len(slots)-1))
                prediction = adapter.predict(ALL_MODELS[0], {"snapshot": snapshot}, at=AT)
                numbers = {n for p in prediction["candidates"] for n in p["combination"]}
                self.assertEqual(numbers, set(slots))
                self.assertEqual(snapshot["participants"][-1]["draw"], slots[-1])

    def test_sparse_number_draw_and_field_size_follow_each_sport_contract(self):
        for sport, maximum in SIZES.items():
            for field in ("number", "draw"):
                bad = sparse_snapshot(sport); bad["participants"][-1][field] = maximum+1
                with self.subTest(sport=sport, field=field), self.assertRaises(ValueError):
                    native.validate(bad)
            bad = sparse_snapshot(sport); bad["participants"][0]["draw"] = True
            with self.subTest(sport=sport), self.assertRaises(ValueError): native.validate(bad)
        for size in (6, 8):
            bad = sparse_snapshot("keirin", slots=tuple(range(1, size+1)))
            with self.subTest(size=size), self.assertRaises(ValueError): native.validate(bad)

    def test_sparse_missing_source_evidence_and_future_capture_still_reject(self):
        for sport in SIZES:
            for field, value in (("source_sha256", "bad"), ("captured_at", "2030-01-15T09:30:00+09:00"), ("value", True)):
                bad = sparse_snapshot(sport); bad["participants"][0]["features"]["ability"][field] = value
                with self.subTest(sport=sport, field=field), self.assertRaises(ValueError): native.validate(bad)
            bad = sparse_snapshot(sport); bad["participants"][0]["missing"].pop("stamina")
            with self.subTest(sport=sport), self.assertRaises(ValueError): native.validate(bad)
            real = sparse_snapshot(sport); real["scope"] = native.RESEARCH
            with self.subTest(sport=sport), self.assertRaises(ValueError): native.validate(real)
            self.assertEqual(native.validate(real, allow_source=lambda *args: args[-1] == "analysis")["sport"], sport)

    def test_registry_exposes_explicit_nonboat_sparse_contract_without_changing_dense_pin(self):
        self.assertEqual(registry.registry_sha256(), "07da538c97be334845f268a10fb0d7676d3b2cdcd7a3a922b0f7d7d798aaf3f6")
        for sport, length in (("keirin", 93), ("autorace", 89), ("horse", 121)):
            with self.subTest(sport=sport):
                spec = registry.specs(ranker.LEARNED_ID, sport, input_schema=native.SCHEMA_SPARSE)
                self.assertEqual(len(spec), length)
                self.assertEqual(tuple(spec), ranker.vector_schema(sport, sparse=True))
                contract = registry.parameter_contract(ranker.LEARNED_ID, sport, input_schema=native.SCHEMA_SPARSE)
                self.assertEqual(set(contract["parameters"]), set(spec))
                for mid in ALL_MODELS:
                    fixed = registry.parameter_contract(mid, sport, input_schema=native.SCHEMA_SPARSE)
                    self.assertEqual(set(fixed["parameters"]), set(registry.specs(mid, sport)))

    def test_public_sparse_version_helper_preserves_boat_and_separates_other_sports(self):
        helper = getattr(ranker, "sparse_versions", None)
        self.assertTrue(callable(helper), "sport-specific sparse version helper is required")
        self.assertEqual(helper("boat"), dict(vector_version=ranker.SPARSE_VECTOR_VERSION,
            train_only_version=ranker.SPARSE_TRAIN_ONLY_VERSION, chronological_version=ranker.SPARSE_CHRONOLOGICAL_VERSION))
        for sport in SIZES:
            self.assertEqual(helper(sport), dict(vector_version=f"{sport}-observed-feature-environment-and-mask-v1",
                train_only_version=f"0.4-train-only-sparse-{sport}", chronological_version=f"0.4-chronological-sparse-{sport}"))
        for bad in (None, [], True, "unknown"):
            with self.subTest(bad=bad), self.assertRaises(ValueError): helper(bad)

    def test_native_ranker_train_only_unknown_publication_and_actual_future_prediction(self):
        for sport in SIZES:
            with self.subTest(sport=sport):
                model = ranker.fit_training_only(training_rows(sport), sport=sport,
                    train_end_at="2030-01-06T12:00:00+09:00", epochs=2,
                    now=lambda: datetime.fromisoformat("2030-01-06T12:10:00+09:00"))
                versions = ranker.sparse_versions(sport)
                self.assertEqual(model["model_version"], versions["train_only_version"])
                self.assertEqual(model["vector_version"], versions["vector_version"])
                prediction = ranker.forecast(sparse_snapshot(sport), model)
                self.assertEqual(len(prediction["candidates"]), math.perm(SIZES[sport], 3))
                self.assertAlmostEqual(math.fsum(p["score"] for p in prediction["candidates"]), 1., places=12)
                late = deepcopy(model); late["created_at"] = "2031-01-01T00:00:00+00:00"
                late["model_sha256"] = native.digest({k:v for k,v in late.items() if k != "model_sha256"})
                with self.assertRaisesRegex(ValueError, "creation"): ranker.forecast(sparse_snapshot(sport), late)

    def test_native_ranker_chronological_version_and_frozen_holdout_diagnostics(self):
        for sport in SIZES:
            with self.subTest(sport=sport):
                rows = training_rows(sport, 10)
                opts = dict(sport=sport, train_end_at="2030-01-06T12:00:00+09:00",
                    validation_end_at="2030-01-08T12:00:00+09:00", test_end_at="2030-01-10T12:00:00+09:00",
                    epochs=2, now=lambda: datetime.fromisoformat("2030-01-11T00:00:00+09:00"))
                model = ranker.fit_chronological(rows, **opts)
                self.assertEqual(model["model_version"], ranker.sparse_versions(sport)["chronological_version"])
                self.assertEqual((model["trained_examples"], model["validation_diagnostics"]["n"], model["holdout_diagnostics"]["n"]), (6, 2, 2))
                self.assertTrue(ranker.forecast(sparse_snapshot(sport), model)["trained"])
                changed = deepcopy(rows)
                for row in changed[6:]: row["result"]["ordered_top3"] = [1, 2, 3]
                self.assertEqual(model["weights"], ranker.fit_chronological(changed, **opts)["weights"])

    def test_dense_all_sports_and_existing_boat_sparse_bytes_remain_exact(self):
        pins = {"boat": "e739679e3b625aea5d125aef25c1e2ea0365be7065729559cd0cec598b1a5ea3",
                "keirin": "b9e48c7d946b8fa42aa148a16451723731e55332d2b5a8ecda800dbd9303e77a",
                "autorace": "2ef1175248b0712da7d15c605e9d0a46cb6e4837535c249296e74e624e31e06f",
                "horse": "cc74164f67c100b68e387d35862a2e74f496dda0feeddd1aa5ec004615ba829a"}
        for sport, size in (("boat", 6), ("keirin", 7), ("autorace", 8), ("horse", 18)):
            with self.subTest(sport=sport): self.assertEqual(native.digest(run_suite(sample(sport, size=size))), pins[sport])
        for slots, expected in (((1, 3, 6), "5e814f45a66d6546e1bb75cc67fe2fcf2a2a3639f6c9c7941e94b03a6833ea52"),
                                (tuple(range(1, 7)), "6da5e690475b9a2e6079de93efd83cf4edfa85562b7e11c167cbd3ecbf8156e0")):
            self.assertEqual(native.digest(run_suite(boat_sparse(slots))), expected)


if __name__ == "__main__": unittest.main()
