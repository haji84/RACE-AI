"""Invented official structures, genuine tiny fitted fixtures, no source I/O."""
from copy import deepcopy
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import stat
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from race_ai.actions_contract import digest
from race_ai.boat_active_exhibition import parse_active_beforeinfo
from race_ai.boat_all_model_inputs import build_native_inputs
from race_ai.boat_history_store import HistoryStore
from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.observed_p1_connection import build_bundle
from race_ai.four_sport_learning import fit_training_only, LEARNED_ID
from race_ai.four_sport_model_suite import ALL_MODELS
from tests.test_boat_active_exhibition import program, main_table, start_table
from tests.test_boat_observation_context import frame, url
from tests.test_boat_history_store import archives, DAY

try:
    cycle = importlib.import_module("race_ai.boat_all_model_cycle")
except ModuleNotFoundError:
    cycle = None

ASOF = "2030-04-01T18:00:00+09:00"
NOW = datetime.fromisoformat("2030-04-01T18:00:10+09:00")
HEAD = "a" * 40


def source_context():
    card = program(withdrawn=(6,))
    raw = frame(main_table(missing=(6,)) + start_table(lanes=(1, 2, 3, 4, 5)))
    before = parse_active_beforeinfo(raw, program=card, source_url=url(), captured_at=ASOF)
    return dict(program=card, beforeinfo=before, as_of=ASOF)


def receipt(document, *, artifact=100, saved="2030-04-01T18:00:20+09:00"):
    return dict(repository_id="1416489937", repository="haji84/RACE-AI", run_id="42", head_sha=HEAD,
                artifact_id=artifact, created_at=saved, payload_sha256=digest(document), independently_verified=True)


def native_baseline(context):
    card, before, at = context["program"], context["beforeinfo"], context["as_of"]
    native = build_native_inputs(card, before, as_of=at)["native_inputs"]
    base, extra = native["boat_ab"]["source"], native["boat_clite"]["extra"]
    pair = build_pair(base, at)
    clite = build_live_feature_shadow(base, extra, at)
    observed = build_bundle(base, extra, at, program_url=card["source_url"], preview_url=before["source_url"],
                            program_captured_at=card["captured_at"], preview_captured_at=before["captured_at"],
                            owner_reviewed=True)
    return dict(schema="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1", paired_forecasts=[pair],
                additional_official_feature_shadows=[clite], observed_pairwise_p1_bundles=[observed])


def fitted_ranker():
    rows = []
    for number in range(1, 7):
        ctx = json.loads(json.dumps(source_context(), ensure_ascii=False)
                         .replace("2030-04-01", f"2030-03-{number:02d}")
                         .replace("20300401", f"203003{number:02d}"))
        snap = build_native_inputs(ctx["program"], ctx["beforeinfo"], as_of=ctx["as_of"])["native_inputs"]["shared"]["snapshot"]
        rows.append(dict(snapshot=snap, result=dict(race_id=ctx["program"]["race_id"], status="settled",
            ordered_top3=[3, 1, 5], published_at=None, captured_at=f"2030-03-{number:02d}T21:00:00+09:00",
            source_sha256="f" * 64, source_ref="synthetic://result", source_rights_ref="fixture-result")))
    return fit_training_only(rows, sport="boat", train_end_at="2030-03-06T23:59:00+09:00", epochs=1,
                             allow_source=lambda ref, rights, purpose: purpose == "analysis",
                             allow_result=lambda ref, rights, purpose: purpose == "result_evaluation",
                             now=lambda: datetime.fromisoformat("2030-03-07T00:00:00+09:00"))


class AllModelCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fitted = fitted_ranker()

    def setUp(self):
        self.assertIsNotNone(cycle, "all-model cycle engine is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def runtime(self, *, fitted=False):
        root = self.root / ("runtime-fit" if fitted else "runtime")
        root.mkdir(mode=0o700, exist_ok=True)
        path = root / "history.sqlite"
        store = HistoryStore(path)
        raw, proofs = archives()
        store.ingest_day(DAY, raw["B"], raw["K"], proofs["B"], proofs["K"])
        store.close()
        metadata = root / "metadata.json"
        metadata.write_text(json.dumps(dict(schema="SYNTHETIC_RUNTIME_METADATA", source_code_commit=HEAD)))
        metadata.chmod(0o600)
        model = root / "ranker.json"
        model.write_text(json.dumps(self.fitted if fitted else None))
        model.chmod(0o600)
        return {"history.sqlite": str(path), "ranker.json": str(model), "metadata.json": str(metadata),
                "verified_runtime": True, "history_identity_verified": True, "owner_reviewed": True,
                "source_code_commit": HEAD, "run_id": "42"}

    def run_round(self, context=None, **kwargs):
        return cycle.forecast_round([source_context() if context is None else context],
                                    self.runtime(fitted=kwargs.pop("fitted", False)), now=kwargs.pop("now", NOW), **kwargs)

    def predictions(self, view):
        return [p for row in view["records"] for p in ([row["prediction"]] if row["prediction"] else []) + row["comparison_predictions"]]

    def test_existing_encrypted_p1_round_keeps_missing_B_in_hold(self):
        payload = self.run_round(research_ab_inputs={})
        self.assertEqual(payload["post_exhibition_research_ab"]["candidate_pairs"], 0)
        self.assertEqual(payload["post_exhibition_research_ab"]["held_races"], 1)
        self.assertEqual(payload["post_exhibition_research_ab"]["source_provider_requests"], 0)
        self.assertEqual(payload["summary"]["research_ab_candidates"], 0)
        self.assertEqual(payload["summary"]["research_ab_holds"], 1)
        self.assertFalse(payload["originals_overwritten"])
        saved = receipt(payload, saved="2030-04-01T18:00:20+09:00")
        view = cycle.project_round(payload, saved)
        study = view["post_exhibition_ab_readback"]
        self.assertEqual(study["b_saved_before_cutoff"], 0)
        self.assertEqual(study["held_races"], 1)
        self.assertEqual(study["source_provider_requests"], 0)
        coverage = view["post_exhibition_ab_coverage"]
        self.assertEqual(coverage["scheduled_races"], 1)
        self.assertEqual(coverage["b_physically_saved_before_cutoff"], 0)
        self.assertEqual(coverage["schedule_scope"], "P1_CURRENT_CONTEXT_SUBSET")
        self.assertIsNone(self.run_round().get("post_exhibition_research_ab"))

    def test_current_input_is_private_immutable_and_all_bindings_are_checked(self):
        ctx = source_context()
        path = cycle.retain_current_input(**ctx, folder=self.root / "inputs")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["program"], ctx["program"])
        self.assertEqual(saved["as_of"], ASOF)
        self.assertFalse(saved["physical_save_time_attested"])
        self.assertEqual(cycle.retain_current_input(**ctx, folder=path.parent), path)
        changed = deepcopy(ctx)
        changed["as_of"] = "2030-04-01T18:00:01+09:00"
        with self.assertRaises(ValueError):
            cycle.retain_current_input(**changed, folder=path.parent)
        for mutate in (lambda x: x["beforeinfo"].update(source_sha256="b" * 64),
                       lambda x: x["program"]["source"].update(sha256="c" * 64),
                       lambda x: x["beforeinfo"]["data"]["boats"][0].update(racer_registration_id="9999"),
                       lambda x: x["beforeinfo"]["context"]["participants"].append(deepcopy(x["beforeinfo"]["context"]["participants"][0])),
                       lambda x: x["beforeinfo"]["data"]["boats"][0].update(name="別の合成選手"),
                       lambda x: x["beforeinfo"].update(closed_at="2030-04-01T20:31:00+09:00"),
                       lambda x: x["beforeinfo"]["data"]["boats"][0].update(display_time=None)):
            bad = deepcopy(ctx)
            mutate(bad)
            with self.assertRaises(ValueError):
                cycle.retain_current_input(**bad, folder=self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_ready_families_execute_with_missing_learned_while_seller_and_auto_keep_rules(self):
        payload = self.run_round()
        self.assertEqual(payload["schema"], "RACE_AI_BOAT_ALL_MODEL_ROUND_V1")
        report = payload["dispatch_reports"][0]
        slots = {s["model_id"]: s for s in report["slots"]}
        self.assertTrue(all(slots[mid]["status"] == "GENERATED_UNATTESTED" for mid in ALL_MODELS))
        self.assertEqual(slots[LEARNED_ID]["status"], "TRAINED_ARTIFACT_MISSING")
        self.assertNotIn("seller-shadow-v1-20261104", slots)
        self.assertEqual(sum(s["status"] == "NOT_APPLICABLE" for s in slots.values()), 1)
        row = report["schedule"][0]
        self.assertEqual([p["number"] for p in row["participants"]], [1, 2, 3, 4, 5])
        self.assertTrue(all(p["active"] for p in row["participants"]))
        self.assertEqual(row["withdrawn_participants"][0]["number"], 6)
        self.assertGreater(payload["summary"]["generated_forecasts"], 4)
        from race_ai.boat_all_model_store import seal_forecasts, open_forecasts
        key = os.urandom(32)
        self.assertEqual(open_forecasts(seal_forecasts(payload, run_id="42", round_no=0, key=key), key=key), payload)

    def test_genuinely_fitted_ranker_executes_and_unverified_runtime_is_rejected(self):
        payload = self.run_round(fitted=True)
        slot = next(s for s in payload["dispatch_reports"][0]["slots"] if s["model_id"] == LEARNED_ID)
        self.assertEqual(slot["status"], "GENERATED_UNATTESTED")
        self.assertTrue(slot["prediction"]["trained"])
        self.assertEqual(slot["prediction"]["model_sha256"], self.fitted["model_sha256"])
        runtime = self.runtime()
        runtime["verified_runtime"] = False
        with self.assertRaises(ValueError):
            cycle.forecast_round([source_context()], runtime, now=NOW)

    def test_restored_history_bytes_remain_unchanged_during_forecasting(self):
        runtime = self.runtime()
        path = Path(runtime["history.sqlite"])
        original = path.read_bytes()
        cycle.forecast_round([source_context()], runtime, now=NOW)
        self.assertEqual(path.read_bytes(), original)

    def test_known_unversioned_history_is_read_only_and_payload_bindings_are_checked(self):
        runtime = self.runtime()
        path = Path(runtime["history.sqlite"])
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=0")
        original = path.read_bytes()
        cycle.forecast_round([source_context()], runtime, now=NOW)
        self.assertEqual(path.read_bytes(), original)
        with sqlite3.connect(path) as db:
            row = db.execute("SELECT id,payload FROM imports").fetchone()
            payload = json.loads(row[1])
            payload["history"]["source_proofs"]["K"]["source_sha256"] = "f" * 64
            db.execute("UPDATE imports SET payload=? WHERE id=?", (json.dumps(payload), row[0]))
        with self.assertRaises(ValueError):
            cycle.forecast_round([source_context()], runtime, now=NOW)

    def test_baseline_five_are_reused_exactly_and_keep_their_actual_older_receipt(self):
        ctx = source_context()
        baseline = native_baseline(ctx)
        prior = receipt(baseline, artifact=99, saved="2030-04-01T18:00:02+09:00")
        with patch("race_ai.existing_model_dispatch.build_pair", side_effect=AssertionError("baseline A/B regenerated")), \
             patch("race_ai.existing_model_dispatch.build_live_feature_shadow", side_effect=AssertionError("baseline C regenerated")), \
             patch("race_ai.existing_model_dispatch.predict_pair", side_effect=AssertionError("observed originals regenerated")):
            payload = self.run_round(ctx, baseline_document=baseline, baseline_receipt=prior)
        reused = [s for s in payload["dispatch_reports"][0]["slots"] if s["status"] == "ORIGINAL_REUSED"]
        self.assertEqual(len(reused), 5)
        current = receipt(payload)
        view = cycle.project_round(payload, current)
        self.assertNotIn("INDEPENDENT_RECEIPT_NOT_VERIFIED", view["records"][0]["missing_reasons"])
        for p in self.predictions(view):
            if p["dispatch_status"] == "ORIGINAL_REUSED":
                self.assertEqual(p["artifact_id"], 99)
                self.assertEqual(p["persisted_at"], prior["created_at"])
                self.assertEqual(p["original_json_sha256"], digest(baseline))
            else:
                self.assertEqual(p["artifact_id"], 100)
                self.assertEqual(p["persisted_at"], current["created_at"])
            self.assertEqual(p["source_code_commit"], HEAD)
            self.assertTrue(p["eligible_pre_cutoff"])

    def test_baseline_observed_http_provenance_cannot_conflict_with_saved_source(self):
        ctx = source_context()
        baseline = native_baseline(ctx)
        bundle = baseline["observed_pairwise_p1_bundles"][0]
        bundle["http_provenance"][0]["source_sha256"] = "f" * 64
        bundle["bundle_sha256"] = digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
        proof = receipt(baseline, saved="2030-04-01T18:00:02+09:00")
        with self.assertRaises(ValueError):
            self.run_round(ctx, baseline_document=baseline, baseline_receipt=proof)

    def test_issued_model_partial_groups_are_filtered_and_fully_issued_groups_are_pruned(self):
        rid = source_context()["program"]["race_id"]
        issued = {rid: list(ALL_MODELS[:2])}
        payload = self.run_round(issued_models=issued)
        slots = {s["model_id"]: s for s in payload["dispatch_reports"][0]["slots"]}
        for mid in ALL_MODELS[:2]:
            self.assertEqual(slots[mid]["status"], "RULE_FILTERED")
            self.assertEqual(slots[mid]["reason"], "SAVED_ORIGINAL_RETAINED_IN_OWNER_FEED")
            self.assertIsNone(slots[mid]["prediction"])
        self.assertTrue(all(slots[mid]["status"] == "GENERATED_UNATTESTED" for mid in ALL_MODELS[2:]))
        from race_ai.autorace_personal_baseline import MODEL_ID as AUTO
        with patch("race_ai.existing_model_dispatch.run_suite", side_effect=AssertionError("issued group regenerated")):
            complete = self.run_round(issued_models={rid: list(ALL_MODELS) + [AUTO]})
        self.assertFalse(any(i["native_group"] == "shared" for i in complete["dispatch_reports"][0]["native_invocations"]))
        self.assertEqual(next(s for s in complete["dispatch_reports"][0]["slots"] if s["model_id"] == AUTO)["status"], "NOT_APPLICABLE")

    def test_late_generation_is_skipped_and_late_external_save_is_never_backdated(self):
        late = self.run_round(now=datetime.fromisoformat("2030-04-01T20:31:00+09:00"))
        self.assertEqual(late["summary"]["generated_forecasts"], 0)
        self.assertEqual(late["skipped_contexts"][0]["reason"], "AT_OR_AFTER_CUTOFF")
        payload = self.run_round()
        saved = receipt(payload, saved="2030-04-01T20:31:00+09:00")
        view = cycle.project_round(payload, saved)
        for p in self.predictions(view):
            self.assertFalse(p["eligible_pre_cutoff"])
            self.assertEqual(p["persisted_at"], saved["created_at"])
            self.assertIn("SAVED_AFTER_CUTOFF", p["missing_reasons"])
        for change in ({"head_sha": "b" * 40}, {"payload_sha256": "c" * 64}, {"repository_id": "1"},
                       {"run_id": "43"}, {"independently_verified": False}):
            with self.subTest(change=next(iter(change))), self.assertRaises(ValueError):
                cycle.project_round(payload, dict(saved, **change))

    def test_saved_p0_inputs_run_only_new_families_at_actual_new_asof(self):
        from tests.test_frozen_day_cycle import sample
        document, _, _ = sample()
        original = deepcopy(document)
        prior = receipt(document, artifact=99, saved="2030-04-01T01:43:00Z")
        now = datetime.fromisoformat("2030-04-01T01:44:00+00:00")
        payload = cycle.forecast_saved_p0(document, prior, self.runtime(fitted=True), now=now)
        self.assertEqual(document, original)
        self.assertEqual(payload["stage"], "P0")
        report = payload["dispatch_reports"][0]
        slots = {s["model_id"]: s for s in report["slots"]}
        self.assertEqual(slots[LEARNED_ID]["status"], "GENERATED_UNATTESTED")
        self.assertEqual(slots[LEARNED_ID]["prediction"]["as_of"], now.isoformat())
        self.assertTrue(slots[LEARNED_ID]["prediction"]["trained"])
        for p in report["slots"]:
            if p["status"] == "GENERATED_UNATTESTED":
                self.assertEqual(p["dispatch_generated_at"], now.isoformat())
        origin = payload["input_origins"]["20300401-01-01"]
        self.assertEqual(origin["original_as_of"], document["predictions"][0]["as_of"])
        self.assertEqual(origin["original_snapshot_sha256"], document["predictions"][0]["snapshot_sha256"])
        self.assertEqual(origin["original_receipt"], prior)
        self.assertEqual(slots["boat-observed-pairwise-factor-v1"]["status"], "RULE_FILTERED")
        self.assertTrue(any(s["reason"] == "WAITING_EXHIBITION" for s in slots.values()))
        current = receipt(payload, saved="2030-04-01T01:44:05Z")
        view = cycle.project_round(payload, current)
        self.assertTrue(all(p["stage"] == "P0" and p["eligible_pre_cutoff"] for p in self.predictions(view)))
        self.assertTrue(all(p["persisted_at"] == current["created_at"] for p in self.predictions(view)))

    def test_saved_p0_does_not_fit_or_generate_after_cutoff_or_for_issued_models(self):
        from tests.test_frozen_day_cycle import sample
        doc, _, _ = sample()
        prior = receipt(doc, artifact=99, saved="2030-04-01T01:43:00Z")
        late = cycle.forecast_saved_p0(doc, prior, self.runtime(fitted=True),
                                     now=datetime.fromisoformat("2030-04-01T02:00:00+00:00"))
        self.assertEqual(late["summary"]["generated_forecasts"], 0)
        with patch("race_ai.existing_model_dispatch.run_suite", side_effect=AssertionError("issued P0 regenerated")):
            issued = cycle.forecast_saved_p0(doc, prior, self.runtime(), now=datetime.fromisoformat("2030-04-01T01:44:00+00:00"),
                                            issued_models={"20300401-01-01": list(ALL_MODELS)})
        self.assertTrue(all(s["status"] == "RULE_FILTERED" for s in issued["dispatch_reports"][0]["slots"] if s["model_id"] in ALL_MODELS))


if __name__ == "__main__":
    unittest.main()
