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

    def collect(self, stage="P0", *, sport="boat"):
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
