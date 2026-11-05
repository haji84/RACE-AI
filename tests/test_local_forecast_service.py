"""Generate through the existing native models; every source here is fictional."""
from copy import deepcopy
from datetime import datetime
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from race_ai import existing_model_dispatch as native
from race_ai.private_dispatch_operation import PrivateDispatchJournal, run_saved_inputs
from tests.test_private_dispatch_operation import fixture, generated
from tests.test_permissioned_source_delivery import AT

try:
    service_module = importlib.import_module("race_ai.local_forecast_service")
except ModuleNotFoundError:
    service_module = None


class Provider:
    capabilities = {sport: {"P0": True, "P1": True}
                    for sport in ("boat", "keirin", "autorace", "horse")}

    def collect(self, stage="P0", *, sport="boat", due_only=False, automatic_stop_at=None,
                refresh_discovery=False, preferred_window=False, automatic_guard=None):
        self.due_only = due_only
        self.automatic_options = dict(refresh_discovery=refresh_discovery,
            preferred_window=preferred_window, automatic_guard=automatic_guard)
        rows, inputs = fixture(sport, real=True)
        self.rows, self.inputs = deepcopy(rows), deepcopy(inputs)
        snap = inputs[rows[0]["race_id"]]["P0"]["shared"]["snapshot"]
        refs = set()
        def walk(value):
            if isinstance(value, dict):
                if "source_ref" in value and "source_rights_ref" in value:
                    refs.add((value["source_ref"], value["source_rights_ref"]))
                for v in value.values(): walk(v)
            elif isinstance(value, list):
                for v in value: walk(v)
        walk(snap)
        return dict(schedule=rows, inputs=inputs,
            source_references=[dict(source_ref=r, source_rights_ref=p) for r,p in refs],
            source_report={"source_requests": 0}, blocked_races=[])

    def status(self, day_jst=None):
        return {"day_jst": day_jst or "2030-01-15", "requests_used": 0, "halted_reason": None}


class LocalForecastServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(service_module, "local new-forecast service is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.fromisoformat(AT)
        self.provider = Provider()
        self.service = service_module.LocalForecastService(
            self.root, provider=self.provider, clock=lambda: self.now)

    def test_source_status_accepts_counts_past_old_limit_without_resetting(self):
        self.provider.status = lambda: {"day_jst": "2030-01-15", "requests_used": 365,
                                        "halted_reason": None, "request_limit": None}
        self.assertEqual(self.service.automatic_source_status()["requests_used"], 365)
        for invalid in (-1, True, 1.5, "365", None):
            self.provider.status = lambda value=invalid: {
                "day_jst": "2030-01-15", "requests_used": value, "halted_reason": None}
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.service.automatic_source_status()

    def test_continuous_clock_and_discovery_options_have_no_session_expiry(self):
        class Continuous:
            def status(self):return {"state":"RUNNING", "stop_at":None, "continuous":True}
        self.service.automation = Continuous()
        self.assertEqual(self.service._automatic_clock(), self.now)
        self.service.generate_auto("boat", "P0")
        self.assertTrue(self.provider.automatic_options["refresh_discovery"])
        self.assertTrue(self.provider.automatic_options["preferred_window"])
        self.assertTrue(callable(self.provider.automatic_options["automatic_guard"]))
        self.assertEqual(self.service.automatic_source_status("2030-01-14")["day_jst"],"2030-01-14")

    def test_delivery_status_uses_recorded_evidence_and_never_fetches_inputs(self):
        self.service.generate("boat", "P0")
        with patch.object(self.provider,"collect",side_effect=AssertionError("status fetched input")):
            status = self.service.status()
        self.assertIn("delivery", status)
        delivery = status["delivery"]["boat"]["P0"]
        self.assertIsNone(delivery["visible_at"])
        self.assertIn(delivery["window_status"], ("EARLY","ON_TIME","LATE","UNKNOWN"))
        self.assertFalse(delivery["independent_user_visibility_time_verified"])

    def test_workflow_mode_rejects_native_generation_before_provider_access(self):
        self.service.workflow_projection_root = self.root / "supervisor"
        with patch.object(self.provider, "collect", side_effect=AssertionError("control plane collected inputs")), \
             patch.object(native, "run_suite", side_effect=AssertionError("control plane inferred")):
            for generate in (self.service.generate, self.service.generate_auto):
                with self.assertRaisesRegex(ValueError, "EXTERNAL_WORKFLOW_MANAGED"):
                    generate("boat", "P0")
        self.assertEqual(self.service.journal.originals(), [])

    def test_workflow_service_does_not_construct_a_native_input_provider(self):
        with patch("race_ai.current_boat_inputs.CurrentBoatInputs", side_effect=AssertionError("native provider created")):
            service = service_module.LocalForecastService(self.root,
                workflow_projection_root=self.root / "supervisor", clock=lambda: self.now)
        self.assertFalse(service.automatic_supported)
        self.assertIsNone(service.provider)

    def test_delivery_uses_saved_source_timestamp_without_inventing_missing_evidence(self):
        self.now = datetime.fromisoformat("2030-01-15T11:52:00+09:00")
        prediction = dict(model_id="saved-model", stage="P0", prediction_sha256="a"*64,
            output_sha256="b"*64, source_captured_at="2030-01-15T11:46:00+09:00",
            generated_at="2030-01-15T11:47:00+09:00", persisted_at="2030-01-15T11:49:00+09:00")
        latest = {"view":{"records":[dict(race_id="20300115-01-01",
            cutoff_at="2030-01-15T12:00:00+09:00", prediction=prediction)]}}
        measured = self.service._delivery(latest, "boat", "P0", {})
        self.assertEqual(measured["source_captured_at"], prediction["source_captured_at"])
        self.assertEqual(measured["window_status"], "ON_TIME")
        del prediction["source_captured_at"]
        prediction["as_of"] = "2030-01-15T11:46:00+09:00"
        missing = self.service._delivery(latest, "boat", "P0", {})
        self.assertIsNone(missing["source_captured_at"])
        self.assertEqual(missing["window_status"], "UNKNOWN")

    def test_all_four_sports_generate_real_native_outputs_and_reuse_after_restart(self):
        for sport in ("boat", "keirin", "autorace", "horse"):
            out = self.service.generate(sport, "P0")
            self.assertEqual(out["summary"]["generated"], 4)
            self.assertEqual(len(out["view"]["records"]), 1)
            self.assertEqual(out["view"]["dataset_status"], "REAL_REPORTED")
            row = out["view"]["records"][0]
            self.assertEqual(row["sport"], sport)
            self.assertEqual(len([row["prediction"], *row["comparison_predictions"]]), 4)
            self.assertFalse(out["view"]["official_metrics_eligible"])
        before = self.service.journal.originals()
        reopened = service_module.LocalForecastService(self.root, provider=self.provider, clock=lambda: self.now)
        with patch.object(native, "run_suite", side_effect=AssertionError("original regenerated")):
            out = reopened.generate("horse", "P0")
        self.assertEqual(out["summary"]["generated"], 0)
        self.assertEqual(out["summary"]["reused"], 4)
        self.assertEqual(reopened.journal.originals(), before)
        self.assertNotIn(str(self.root), str(reopened.status()))

    def test_sources_without_server_authorization_do_not_generate(self):
        original = self.provider.collect
        def denied(*args, **kwargs):
            collected = original(*args, **kwargs)
            collected["source_references"] = []
            return collected
        self.provider.collect = denied
        out = self.service.generate("boat", "P0")
        self.assertEqual(out["summary"]["generated"], 0)
        self.assertGreater(out["summary"]["missing"], 0)
        self.assertEqual(self.service.journal.originals(), [])

    def test_previous_day_and_forged_stage_are_rejected_without_inference(self):
        with self.assertRaises(ValueError): self.service.generate("boat", "HISTORICAL")
        self.now = datetime.fromisoformat("2030-01-16T09:00:00+09:00")
        with patch.object(native, "run_suite", side_effect=AssertionError("historical generation")):
            with self.assertRaises(ValueError): self.service.generate("boat", "P0")
        self.assertEqual(self.service.journal.originals(), [])

    def test_deadline_crossed_during_inference_rolls_back_every_new_original(self):
        original = native.run_suite
        def crossed(*args, **kwargs):
            answer = original(*args, **kwargs)
            self.now = datetime.fromisoformat("2030-01-15T12:00:00+09:00")
            return answer
        with patch.object(native, "run_suite", side_effect=crossed):
            with self.assertRaises(ValueError): self.service.generate("boat", "P0")
        self.assertEqual(self.service.journal.originals(), [])

    def test_post_commit_late_save_stays_rejected_on_retry_without_regeneration(self):
        before = datetime.fromisoformat(AT)
        after = datetime.fromisoformat("2030-01-15T12:00:00+09:00")
        calls = iter([before, before, after])
        self.service.clock = lambda: next(calls)
        with self.assertRaises(ValueError): self.service.generate("boat", "P0")
        originals = self.service.journal.originals()
        self.assertEqual(len(originals), 4)
        self.service.clock = lambda: after
        with patch.object(native, "run_suite", side_effect=AssertionError("late original regenerated")):
            with self.assertRaises(ValueError): self.service.generate("boat", "P0")
        self.assertEqual(self.service.journal.originals(), originals)

    def test_reversed_post_commit_clock_is_never_admitted_on_retry(self):
        before = datetime.fromisoformat(AT)
        earlier = datetime.fromisoformat("2030-01-15T08:59:00+09:00")
        calls = iter([before, before, earlier])
        self.service.clock = lambda: next(calls)
        with self.assertRaises(ValueError): self.service.generate("boat", "P0")
        self.service.clock = lambda: before
        with patch.object(native, "run_suite", side_effect=AssertionError("original regenerated")):
            with self.assertRaises(ValueError): self.service.generate("boat", "P0")

    def test_latest_restores_checked_originals_without_fetching_or_generating(self):
        self.assertTrue(callable(getattr(self.service, "latest", None)), "readonly latest is missing")
        first = self.service.generate("boat", "P0")
        # Derived display JSON is not the native original or a trusted index.
        (self.root / "operation-1-view.json").write_text('{"tampered":true}')
        reloaded = service_module.LocalForecastService(self.root, provider=self.provider, clock=lambda: self.now)
        with patch.object(self.provider, "collect", side_effect=AssertionError("GET fetched inputs")), \
             patch.object(native, "run_suite", side_effect=AssertionError("GET inferred")):
            latest = reloaded.latest("boat", "P0")
            with patch.object(reloaded.journal, "read_operation", side_effect=AssertionError("unchanged GET rebuilt native output")):
                same = reloaded.latest("boat", "P0")
        self.assertTrue(latest["available"])
        self.assertEqual(latest["revision"], same["revision"])
        self.assertEqual(latest["view"]["records"], first["view"]["records"])
        with reloaded.journal.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dispatch_operations").fetchone()[0], 1)

    def test_automatic_generation_requests_due_window_without_browser_control(self):
        self.assertTrue(callable(getattr(self.service, "generate_auto", None)), "automatic seam is missing")
        out = self.service.generate_auto("boat", "P0")
        self.assertTrue(self.provider.due_only)
        self.assertEqual(out["summary"]["generated"], 4)
        self.assertEqual(self.service.automatic_source_status()["requests_used"], 0)

    def test_automatic_repeat_reuses_operation_when_every_supplied_model_is_saved(self):
        first = self.service.generate_auto("boat", "P0")
        with patch.object(native,"run_suite",side_effect=AssertionError("saved model inferred")):
            again = self.service.generate_auto("boat", "P0")
        with self.service.journal.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM dispatch_operations").fetchone()[0]
        self.assertEqual(count,1)
        self.assertEqual(again["revision"],first["revision"])
        self.assertEqual(again["summary"]["generated"],0)
        self.assertEqual(again["summary"]["reused"],4)
        self.assertTrue(again["summary"]["operation_reused"])

    def test_new_supplied_model_after_automatic_save_is_not_skipped(self):
        self.service.generate_auto("boat", "P0")
        original = self.provider.collect
        def newly_connected(*args,**kwargs):
            collected = original(*args,**kwargs)
            rid=collected["schedule"][0]["race_id"]
            collected["inputs"][rid]["P0"]["boat_observed"] = {"snapshot":{}}
            return collected
        self.provider.collect = newly_connected
        # Missing real fields remain rejected; their new model must still be
        # evaluated, rather than silently hidden by a previous shared save.
        with patch.object(service_module,"run_saved_inputs",wraps=run_saved_inputs) as dispatch:
            answer = self.service.generate_auto("boat", "P0")
        dispatch.assert_called_once()
        self.assertGreater(answer["summary"]["missing"],0)
        with self.service.journal.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dispatch_operations").fetchone()[0],2)

    def test_new_or_still_ineligible_learning_inside_shared_is_not_skipped(self):
        self.service.generate_auto("boat", "P0")
        original = self.provider.collect
        def newly_connected(*args,**kwargs):
            collected=original(*args,**kwargs)
            rid=collected["schedule"][0]["race_id"]
            collected["inputs"][rid]["P0"]["shared"]["learned_model"] = {}
            return collected
        self.provider.collect=newly_connected
        # The learned family aliases the shared group. A newly arrived or
        # still incomplete artifact must reach its own eligibility checks.
        for _ in range(2):
            with patch.object(service_module,"run_saved_inputs",wraps=run_saved_inputs) as dispatch:
                answer=self.service.generate_auto("boat","P0")
            dispatch.assert_called_once()
            self.assertGreater(answer["summary"]["missing"],0)

    def test_pending_p1_does_not_replace_p0_latest_and_late_receipts_fail_closed(self):
        self.assertTrue(callable(getattr(self.service, "latest", None)), "readonly latest is missing")
        self.service.generate("boat", "P0")
        first = self.service.latest("boat", "P0")
        collect = self.provider.collect
        def pending(*args, **kwargs):
            d = collect(*args, **kwargs)
            for r in d["schedule"]: r["stage"] = "P1"
            d["inputs"] = {}
            return d
        self.provider.collect = pending
        self.service.generate("boat", "P1")
        self.assertFalse(self.service.latest("boat", "P1")["available"])
        self.assertEqual(self.service.latest("boat", "P0")["revision"], first["revision"])
        receipt = self.root / "operation-1-receipt.json"
        import json
        d = json.loads(receipt.read_text()); d["local_commit_completed_at"] = "2030-01-15T12:00:00+09:00"
        receipt.write_text(json.dumps(d))
        restarted = service_module.LocalForecastService(self.root, provider=self.provider, clock=lambda: self.now)
        self.assertFalse(restarted.latest("boat", "P0")["available"])

    def test_automatic_session_end_blocks_collection_and_rolls_back_late_inference(self):
        from types import SimpleNamespace
        from datetime import timedelta
        before = self.now
        state = {"enabled": True, "state": "RUNNING", "stop_at": before.isoformat()}
        self.service.automation = SimpleNamespace(status=lambda: dict(state))
        with patch.object(self.provider, "collect", side_effect=AssertionError("source after session end")):
            with self.assertRaises(ValueError): self.service.generate_auto("boat", "P0")
        state["stop_at"] = (before + timedelta(seconds=1)).isoformat()
        original = native.run_suite
        def crossed(*args, **kwargs):
            answer = original(*args, **kwargs)
            self.now = before + timedelta(seconds=2)
            return answer
        with patch.object(native, "run_suite", side_effect=crossed):
            with self.assertRaises(ValueError): self.service.generate_auto("boat", "P0")
        self.assertEqual(self.service.journal.originals(), [])


class ActualSaveBoundaryTests(unittest.TestCase):
    def test_optional_actual_clock_rejects_batch_after_native_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = PrivateDispatchJournal(Path(tmp) / "journal.sqlite")
            rows, inputs = fixture()
            with self.assertRaises(ValueError):
                run_saved_inputs(journal, rows, inputs, at=AT,
                    commit_clock=lambda: datetime.fromisoformat("2030-01-15T12:00:00+09:00"),
                    cutoff_buffer_seconds=210)
            self.assertEqual(journal.originals(), [])
