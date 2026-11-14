"""Fictional sources exercise observed-only native adapters and sparse models."""
from copy import deepcopy
from datetime import datetime
import importlib
import json
import unittest

from race_ai import comprehensive_four_sport_models as common
from race_ai import four_sport_learning as learning
from race_ai.existing_model_dispatch import dispatch
from race_ai.four_sport_model_suite import run_suite, ALL_MODELS
from tests.test_comprehensive_four_sport_models import sample

try:
    adapter = importlib.import_module("race_ai.boat_all_model_inputs")
except ModuleNotFoundError:
    adapter = None

SPARSE = "RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_SPARSE_V1"
ASOF = "2030-01-15T09:10:00+09:00"


def sparse_snapshot(lanes=(1, 3, 6)):
    snap = sample("boat")
    snap["schema"] = SPARSE
    available = set(common.COMMON_REQUIRED + common.SPORT_REQUIRED["boat"] + common.SPORT_OPTIONAL["boat"])
    snap["participants"] = [p for p in snap["participants"] if p["number"] in lanes]
    for p in snap["participants"]:
        p["features"] = {k: v for k, v in p["features"].items() if k in ("ability", "motor_form")}
        p["missing"] = {k: "NOT_AVAILABLE" for k in available - p["features"].keys()}
        for obs in p["features"].values():
            obs["source_sha256"] = "a" * 64
            obs["published_at"] = None
    snap["environment"] = {"wind_mps": snap["environment"]["wind_mps"]}
    snap["environment"]["wind_mps"]["source_sha256"] = "b" * 64
    snap["environment"]["wind_mps"]["published_at"] = None
    snap["environment_missing"] = {k: "NOT_AVAILABLE" for k in common.ENV_COMMON + common.ENV_SPORT["boat"] if k != "wind_mps"}
    return snap


def official_inputs(lanes=(1, 3, 6)):
    rid = "20300115-17-01"
    program = dict(race_id=rid, closed_at="2030-01-15T10:00:00+09:00",
                   source_url="https://www.boatrace.jp/owpc/pc/race/racelist?hd=20300115&jcd=17&rno=1",
                   source_sha256="a" * 64, captured_at="2030-01-15T08:50:00+09:00", distance_m=1800,
                   boats=[dict(lane=n, racer_registration_id=str(4000+n), entry_status="listed",
                               national_win_rate=5+n/10, local_win_rate=None,
                               average_st=.15+n/100, motor_top2_rate=30+n) for n in lanes])
    before = dict(race_id=rid, closed_at=program["closed_at"], status="AVAILABLE",
                  source_url="https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20300115&jcd=17&rno=1",
                  source_sha256="b" * 64, captured_at="2030-01-15T09:00:00+09:00",
                  data=dict(boats=[dict(lane=n, racer_registration_id=str(4000+n), display_time=6.7+n/100,
                                        preview_st=.10+n/100, preview_st_status="OK") for n in lanes]))
    return program, before


def labeled_rows():
    rows = []
    for i in range(10):
        day = f"2030-01-{i+1:02d}"
        snap = json.loads(json.dumps(sparse_snapshot()).replace("2030-01-15", day))
        result = dict(race_id=snap["race"]["race_id"], status="settled", ordered_top3=[3, 1, 6],
                      published_at=day+"T11:00:00+09:00", captured_at=day+"T11:01:00+09:00",
                      source_ref="synthetic://result", source_rights_ref="synthetic-result")
        rows.append(dict(snapshot=snap, result=result))
    return rows


class SparseSharedModelsTests(unittest.TestCase):
    def test_sparse_suite_enumerates_physical_active_lanes_without_imputation(self):
        snap = sparse_snapshot()
        before = deepcopy(snap)
        suite = run_suite(snap)
        self.assertEqual(snap, before)
        for mid in ALL_MODELS:
            result = suite["models"][mid]
            self.assertEqual(result["candidate_count"], 6)
            self.assertEqual(len(result["ordered_top8"]), 6)
            self.assertEqual({n for t in result["ordered_top8"] for n in t}, {1, 3, 6})
            self.assertAlmostEqual(sum(x["score"] for x in result["candidates"]), 1)
            self.assertEqual(result["input_schema"], SPARSE)
            self.assertIn("stamina", result["missing_features_by_participant"][1])
            self.assertIn("humidity_pct", result["missing_environment"])
            self.assertFalse(result["trained"])

    def test_sparse_missing_partition_and_future_capture_are_enforced(self):
        for mutation in ("partition", "overlap", "future", "hash"):
            snap = sparse_snapshot()
            if mutation == "partition": del snap["participants"][0]["missing"]["stamina"]
            if mutation == "overlap": snap["participants"][0]["missing"]["ability"] = "NOT_AVAILABLE"
            if mutation == "future": snap["participants"][0]["features"]["ability"]["captured_at"] = "2030-01-15T09:11:00+09:00"
            if mutation == "hash": snap["environment"]["wind_mps"]["source_sha256"] = "invalid"
            with self.subTest(mutation=mutation), self.assertRaises(common.ModelInputError):
                run_suite(snap)

    def test_sparse_model_is_fit_from_outcomes_and_uses_separate_observation_masks(self):
        rows = labeled_rows()
        kwargs = dict(sport="boat", train_end_at="2030-01-06T23:59:00+09:00",
                      validation_end_at="2030-01-08T23:59:00+09:00", test_end_at="2030-01-10T23:59:00+09:00", epochs=2,
                      now=lambda: datetime.fromisoformat("2030-01-11T00:00:00+09:00"))
        model = learning.fit_chronological(rows, **kwargs)
        self.assertEqual(model["trained_examples"], 6)
        self.assertIn("observed_stamina", model["vector_schema"])
        self.assertIn("observed_env_humidity_pct", model["vector_schema"])
        self.assertTrue(any(w != 0 for w in model["weights"]))
        changed = deepcopy(rows)
        for row in changed[6:]: row["result"]["ordered_top3"] = [6, 1, 3]
        self.assertEqual(learning.fit_chronological(changed, **kwargs)["weights"], model["weights"])
        pred = learning.forecast(sparse_snapshot(), model)
        self.assertEqual(pred["candidate_count"], 6)
        self.assertTrue(pred["trained"])
        with self.assertRaises(common.ModelInputError):
            learning.forecast(sample("boat"), model)

    def test_sparse_captured_only_labels_train_without_inventing_publication_time(self):
        rows = labeled_rows()[:6]
        for row in rows:
            row["result"]["published_at"] = None
            row["result"]["source_sha256"] = "c"*64
        before = deepcopy(rows)
        opts = dict(sport="boat", train_end_at="2030-01-06T23:59:00+09:00", epochs=2,
                    now=lambda: datetime.fromisoformat("2030-01-07T00:00:00+09:00"))
        model = learning.fit_training_only(rows, **opts)
        self.assertEqual(rows, before)
        self.assertEqual(model["trained_examples"], 6)
        self.assertEqual(model["trained_data_until"], "2030-01-06T02:01:00+00:00")
        self.assertEqual(model["result_time_semantics"], "CAPTURED_AVAILABILITY_BOUND_PUBLICATION_MAY_BE_UNKNOWN")
        for capture in ("2030-01-01T09:59:00+09:00", "2030-01-07T00:00:00+09:00"):
            bad = deepcopy(rows); bad[0]["result"]["captured_at"] = capture
            with self.subTest(capture=capture), self.assertRaises(common.ModelInputError):
                learning.fit_training_only(bad, **opts)

    def test_sparse_chronological_artifact_omits_outside_test_rows_and_lists_disjoint_cohorts(self):
        opts = dict(sport="boat", train_end_at="2030-01-06T23:59:00+09:00",
                    validation_end_at="2030-01-08T23:59:00+09:00", test_end_at="2030-01-10T23:59:00+09:00", epochs=1,
                    now=lambda: datetime.fromisoformat("2030-01-11T00:00:00+09:00"))
        rows = labeled_rows()
        model = learning.fit_chronological(rows, **opts)
        extra = json.loads(json.dumps(rows[-1]).replace("2030-01-10", "2030-01-14"))
        extended = learning.fit_chronological(rows+[extra], **opts)
        self.assertEqual(model["training_data_sha256"], extended["training_data_sha256"])
        self.assertEqual(extended["trained_data_until"], "2030-01-10T02:01:00+00:00")
        cohorts = [set(model[k]) for k in ("train_example_ids", "validation_example_ids", "test_example_ids")]
        self.assertEqual([len(s) for s in cohorts], [6, 2, 2])
        self.assertFalse(cohorts[0]&cohorts[1] or cohorts[0]&cohorts[2] or cohorts[1]&cohorts[2])


class NativeInputBuilderTests(unittest.TestCase):
    def test_genuinely_fitted_sparse_artifact_dispatches_but_bad_artifact_only_blocks_learned(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        program, before = official_inputs()
        rows = []
        for n in range(1, 7):
            date = f"2030-01-{n:02d}"
            p = json.loads(json.dumps(program).replace("2030-01-15", date).replace("20300115", date.replace("-", "")))
            b = json.loads(json.dumps(before).replace("2030-01-15", date).replace("20300115", date.replace("-", "")))
            snap = adapter.build_native_inputs(p, b, as_of=date+"T09:10:00+09:00")["native_inputs"]["shared"]["snapshot"]
            rows.append(dict(snapshot=snap, result=dict(race_id=p["race_id"], status="settled", ordered_top3=[3, 1, 6],
                published_at=None, captured_at=date+"T11:00:00+09:00", source_sha256="c"*64,
                source_ref="synthetic://official-result", source_rights_ref="fixture-result")))
        model = learning.fit_training_only(rows, sport="boat", train_end_at="2030-01-06T23:59:00+09:00", epochs=2,
            allow_source=lambda ref, rights, purpose: purpose == "analysis",
            allow_result=lambda ref, rights, purpose: purpose == "result_evaluation",
            now=lambda: datetime.fromisoformat("2030-01-07T00:00:00+09:00"))
        result = adapter.build_native_inputs(program, before, as_of=ASOF, fitted_model=model)
        native = result["native_inputs"]
        report = dispatch([dict(race_id=program["race_id"], sport="boat", cutoff_at=program["closed_at"], stage="P1")],
                          {program["race_id"]: {"P1": native}}, now=ASOF,
                          allow_source=lambda ref, rights, purpose: purpose == "analysis")
        learned = next(s for s in report["slots"] if s["model_id"] == learning.LEARNED_ID)
        self.assertEqual(learned["status"], "GENERATED_UNATTESTED")
        self.assertTrue(learned["prediction"]["trained"])
        self.assertEqual(learned["prediction"]["model_sha256"], model["model_sha256"])
        model["weights"][0] += 1
        bad = adapter.build_native_inputs(program, before, as_of=ASOF, fitted_model=model)
        self.assertEqual(bad["readiness"]["shared_learned"]["state"], "TRAINED_ARTIFACT_MISSING")
        self.assertEqual(bad["readiness"]["shared"]["state"], "READY")

    def test_observed_sparse_weather_keeps_source_binding_and_missing_humidity(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        program, before = official_inputs()
        before["data"]["weather"] = dict(wind_speed_mps=4, wave_height_cm=10, air_temperature_c=18)
        result = adapter.build_native_inputs(program, before, as_of=ASOF)
        snap = result["native_inputs"]["shared"]["snapshot"]
        self.assertEqual(snap["environment"]["wind_mps"]["value"], 4)
        self.assertIsNone(snap["environment"]["wind_mps"]["published_at"])
        self.assertIn("humidity_pct", snap["environment_missing"])
        full = result["native_inputs"]["boat_full"]
        full["source_evidence"] = [e for e in full["source_evidence"] if e["source_ref"] != before["source_url"]]
        report = dispatch([dict(race_id=program["race_id"], sport="boat", cutoff_at=program["closed_at"], stage="P1")],
                          {program["race_id"]: {"P1": {"boat_full": full}}}, now=ASOF,
                          allow_source=lambda ref, rights, purpose: purpose == "analysis")
        from race_ai.boat_multi_feature_models import MODEL_IDS
        for row in report["slots"]:
            if row["model_id"] in MODEL_IDS: self.assertEqual(row["status"], "SOURCE_NOT_AUTHORIZED")

    def test_pdca_native_prerequisites_do_not_block_ready_sparse_families(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        program, before = official_inputs()
        result = adapter.build_native_inputs(program, before, as_of=ASOF,
            history_context=dict(pdca=dict(facts=dict(race_id=program["race_id"]), rows=[])))
        self.assertEqual(result["readiness"]["boat_pdca"]["state"], "INPUT_MISSING")
        self.assertIn("PDCA_REQUIRES_24_EARLIER_SAME_VENUE_RESULTS", result["readiness"]["boat_pdca"]["reasons"])
        self.assertIn("shared", result["native_inputs"])
        result = adapter.build_native_inputs(program, before, as_of=ASOF,
            history_context=dict(pdca=dict(facts=dict(race_id="20300115-18-01"), rows=[])))
        self.assertEqual(result["readiness"]["boat_pdca"]["state"], "INPUT_REJECTED")
        self.assertIn("boat_full", result["native_inputs"])

    def test_saved_observed_conversion_uses_original_source_clock_and_numeric_transforms(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        self.assertTrue(hasattr(adapter, "shared_snapshot_from_observed"), "saved-original conversion is absent")
        from tests.test_boat_observed_pairwise_models import fixture
        observed = fixture()
        before = deepcopy(observed)
        snap = adapter.shared_snapshot_from_observed(observed)
        self.assertEqual(observed, before)
        common.validate(snap)
        first = snap["participants"][0]
        original = observed["participants"][0]
        national = original["features"]["national_win_rate"]
        source = next(s for s in observed["sources"] if s["source_id"] == national["source_id"])
        self.assertEqual(first["features"]["ability"]["value"], national["value"]/10)
        self.assertEqual(first["features"]["ability"]["captured_at"], source["captured_at"])
        self.assertEqual(first["features"]["ability"]["source_sha256"], source["source_sha256"])
        self.assertNotIn("stamina", first["features"])
        self.assertEqual(snap["environment"], {})
        mutated = deepcopy(observed)
        mutated["sources"][0]["captured_at"] = "2030-11-03T15:00:00+09:00"
        with self.assertRaises(ValueError):
            adapter.shared_snapshot_from_observed(mutated)

    def test_verified_historical_counts_enable_tactical_and_actual_recent_features(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        from pathlib import Path
        import tempfile
        from race_ai.boat_history_store import HistoryStore
        from tests.test_boat_history_store import archives, DAY
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp)/"history.sqlite")
            self.addCleanup(store.close)
            raw, proofs = archives()
            store.ingest_day(DAY, raw["B"], raw["K"], proofs["B"], proofs["K"])
            program, before = official_inputs()
            result = adapter.build_native_inputs(program, before, as_of=ASOF,
                history_context=dict(history_store=store, history_identity_verified=True))
            self.assertEqual(result["readiness"]["boat_tactical"]["state"], "READY")
            first = result["native_inputs"]["shared"]["snapshot"]["participants"][0]
            self.assertAlmostEqual(first["features"]["recent_form"]["value"], 11/15)
            self.assertEqual(first["features"]["recent_form"]["sample_n"], 3)
            self.assertEqual(first["features"]["recent_form"]["captured_at"], "2026-11-05T18:00:00+09:00")
            report = dispatch([dict(race_id=program["race_id"], sport="boat", cutoff_at=program["closed_at"], stage="P1")],
                {program["race_id"]: {"P1": result["native_inputs"]}}, now=ASOF,
                allow_source=lambda ref, rights, purpose: purpose == "analysis")
            from race_ai.boat_tactical_scenarios import MODEL_ID
            tactical = next(s for s in report["slots"] if s["model_id"] == MODEL_ID)
            self.assertEqual(tactical["status"], "GENERATED_UNATTESTED")

    def test_official_rows_build_real_sparse_features_and_readiness_independently(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        program, before = official_inputs()
        result = adapter.build_native_inputs(program, before, as_of=ASOF)
        native = result["native_inputs"]
        self.assertIn("shared", native)
        self.assertIn("boat_full", native)
        snap = native["shared"]["snapshot"]
        self.assertEqual([p["number"] for p in snap["participants"]], [1, 3, 6])
        self.assertEqual(snap["participants"][0]["features"]["ability"]["value"], .51)
        obs = snap["participants"][0]["features"]["ability"]
        self.assertEqual(obs["source_sha256"], "a"*64)
        self.assertEqual(obs["captured_at"], program["captured_at"])
        self.assertIsNone(obs["published_at"])
        self.assertNotIn("stamina", snap["participants"][0]["features"])
        self.assertNotIn("humidity_pct", snap["environment"])
        self.assertNotIn("tide_activity", snap["environment"])
        self.assertEqual(result["readiness"]["shared_learned"]["state"], "TRAINED_ARTIFACT_MISSING")
        self.assertEqual(result["readiness"]["boat_tactical"]["state"], "INPUT_MISSING")
        report = dispatch([dict(race_id=program["race_id"], sport="boat", cutoff_at=program["closed_at"], stage="P1")],
                          {program["race_id"]: {"P1": native}}, now=ASOF,
                          allow_source=lambda ref, rights, purpose: purpose == "analysis")
        by_model = {p["model_id"]: p for p in report["slots"]}
        from race_ai.boat_multi_feature_models import MODEL_IDS as full_ids
        from race_ai.boat_ab_shadow import MODEL_IDS as ab_ids
        from race_ai.boat_live_feature_shadow import MODEL_ID as clite_id
        for mid in (*ALL_MODELS, *full_ids, *ab_ids, clite_id):
            self.assertEqual(by_model[mid]["status"], "GENERATED_UNATTESTED", (mid, by_model[mid].get("reason")))

    def test_absent_active_exhibition_does_not_infer_withdrawal_or_suppress_other_inputs(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        program, before = official_inputs()
        before["data"]["boats"] = before["data"]["boats"][:-1]
        result = adapter.build_native_inputs(program, before, as_of=ASOF)
        self.assertNotIn("boat_ab", result["native_inputs"])
        self.assertIn("shared", result["native_inputs"])
        snap = result["native_inputs"]["shared"]["snapshot"]
        self.assertEqual([p["number"] for p in snap["participants"]], [1, 3, 6])
        self.assertIn("exhibition_performance", snap["participants"][-1]["missing"])

    def test_identity_future_source_and_unconfirmed_roster_fail_closed(self):
        self.assertIsNotNone(adapter, "source-backed all-model builder is absent")
        for case in ("identity", "future", "status"):
            program, before = official_inputs()
            if case == "identity": before["data"]["boats"][0]["racer_registration_id"] = "9999"
            if case == "future": before["captured_at"] = "2030-01-15T09:11:00+09:00"
            if case == "status": program["boats"][0]["entry_status"] = "unknown"
            with self.subTest(case=case), self.assertRaises(ValueError):
                adapter.build_native_inputs(program, before, as_of=ASOF)
