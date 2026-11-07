"""Encrypted saved originals retain actual outer receipts and native bytes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import base64
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import cycle_recovery, frozen_day_cycle, observed_result_history, observed_weight_learning
from race_ai.actions_contract import digest
from race_ai.private_cycle_capture import capture_artifacts
from race_ai.private_cycle_restore import restore_manifest
from scripts import first_p0_bootstrap, github_existing_cycle, boat_all_model_cycle
from tests.test_frozen_day_cycle import sample
from tests.test_continuity_checkpoint import session

try:
    private = importlib.import_module("race_ai.boat_private_original_archive")
except ModuleNotFoundError:
    private = None

KEY = bytes(range(32))
HEAD = "a" * 40


def packed(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, body in members.items(): archive.writestr(name, body)
    return out.getvalue()


def encrypted(raw, metadata, kind):
    meta = deepcopy(metadata)
    meta["workflow_run"].update(repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD)
    cipher = private.seal_original_zip(raw, run_id=meta["workflow_run"]["id"], head_sha=HEAD, kind=kind, key=KEY)
    outer = packed({"private-original.enc": cipher})
    meta.update(digest="sha256:"+sha256(outer).hexdigest(), size_in_bytes=len(outer))
    return outer, meta


class PrivateOriginalReaderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(private, "private original archive helper is absent")
        setting = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        setting.start(); self.addCleanup(setting.stop)

    def test_encrypted_p0_keeps_native_body_hash_first_index_and_restore_bytes(self):
        document, original, receipt = sample()
        with zipfile.ZipFile(io.BytesIO(original)) as archive: body = archive.read("forecasts.json")
        outer, meta = encrypted(original, receipt, "P0")
        parsed, rows = frozen_day_cycle.read_p0(outer, meta, expected_day="2030-04-01")
        self.assertEqual(parsed, json.loads(body))
        self.assertTrue(all(r["original_json_sha256"] == sha256(body).hexdigest() for r in rows))
        index = first_p0_bootstrap.receipt_index(outer, meta, "2030-04-01")
        self.assertEqual(index["zip_sha256"], sha256(outer).hexdigest())
        self.assertNotEqual(index["zip_sha256"], sha256(original).hexdigest())
        self.assertEqual(index["json_sha256"], sha256(body).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(github_existing_cycle, "ROOT", root), \
                 patch.object(github_existing_cycle, "original", return_value=(document, rows, meta, outer)), \
                 patch.object(github_existing_cycle, "recover", return_value={}), \
                 patch.dict(os.environ, GITHUB_RUN_ID="3"):
                github_existing_cycle.restore("2030-04-01")
            self.assertEqual((root/"boat_all_day_output/forecasts.json").read_bytes(), body)
            self.assertEqual(json.loads((root/"boat_all_day_output/first-receipt.json").read_text()), meta)

    def test_encrypted_native_p0_p1_result_archives_capture_and_restore_without_inference(self):
        from tests.private_cycle_ui_fixture import _artifacts
        artifacts, observations, _ = _artifacts()
        encrypted_artifacts = [encrypted(raw, meta, "P0" if meta["name"].startswith("boat-p0") else
                               "P1" if meta["name"].startswith("boat-national") else "RESULT") for raw, meta in artifacts]
        mapping = {}
        for raw, meta in encrypted_artifacts:
            mapping[f"actions/artifacts/{meta['id']}"] = json.dumps(meta).encode()
            mapping[f"actions/artifacts/{meta['id']}/zip"] = raw
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/"captured"
            with patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("reader inferred")), \
                 patch("race_ai.observed_weight_learning.fit_from_verified", side_effect=AssertionError("reader fitted")):
                manifest = capture_artifacts("2030-04-01", [meta["id"] for _, meta in encrypted_artifacts], target,
                                             github_get=lambda endpoint: mapping[endpoint])
                restored = restore_manifest(manifest, target)
            self.assertEqual(restored["observations"], observations)
            self.assertEqual({r["stage"] for r in restored["rows"]}, {"P0", "P1"})
            for raw, meta in encrypted_artifacts:
                self.assertEqual((target/f"artifact-{meta['id']}.zip").read_bytes(), raw)
                self.assertTrue(any(r["id"] == meta["id"] and r["digest"] == meta["digest"] for r in restored["receipts"]))

    def test_encrypted_results_supply_history_and_original_training_with_outer_receipt(self):
        from tests.test_observed_weight_learning import dataset, NOW
        rows, observations = dataset(8)
        training = observed_weight_learning.fit_from_verified(rows, observations, now=NOW)
        report = dict(day_jst="2030-04-01", result_observation_versions=len(observations),
                      automatic_learning=dict(training_sha256=training["training_sha256"]))
        report["report_sha256"] = digest(report)
        original = packed({"official-result-observations.json": json.dumps(observations),
                           "status.json": json.dumps(report), "trained_observed_models.json": json.dumps(training)})
        metadata = dict(id=701, name="race-existing-cycle-99", expired=False, created_at="2030-04-01T08:00:02Z",
                        workflow_run=dict(id=99, head_repository_id=1416489937))
        outer, meta = encrypted(original, metadata, "RESULT")
        self.assertEqual(cycle_recovery._result_day(outer, meta), "2030-04-01")
        self.assertEqual(cycle_recovery.result_archive(outer, meta, "2030-04-01"), observations)
        context = observed_result_history.context_from_result_archive(outer, meta, verified_at="2030-04-01T08:01:00Z")
        self.assertEqual(context["observations"], observations)
        self.assertEqual(context["receipt"], meta)
        learned = observed_weight_learning.context_from_result_archive(outer, meta)
        self.assertEqual(learned["training"], training)
        self.assertEqual(learned["receipt"], meta)

    def test_encrypted_continuity_preserves_source_waits_and_actual_save_clock(self):
        original = packed({"repeat-session.json": session(), "continuity.json": b'{"private":true}'})
        metadata = dict(id=70, name="race-cycle-continuity-7", expired=False, created_at="2030-04-01T02:00:00Z",
                        workflow_run=dict(id=7, head_repository_id=1416489937))
        outer, meta = encrypted(original, metadata, "CONTINUITY")
        control = cycle_recovery.authenticated_source_control(outer, meta, expected_run=7)
        self.assertEqual(control["source_wait"]["state"], "RATE_LIMIT_WAIT")
        self.assertEqual(control["lifetime_requests"], 700)
        self.assertEqual(control["receipt"], {k: meta[k] for k in ("id", "digest", "created_at")})

    def test_encrypted_artifacts_project_through_existing_private_feed_reader(self):
        from tests import test_workflow_live_projection as fixtures
        case = fixtures.WorkflowLiveProjectionTests()
        case.setUp(); self.addCleanup(case.doCleanups)
        for ident, (raw, meta) in list(case.archives.items()):
            if meta["name"].startswith("boat-"):
                case.archives[ident] = encrypted(raw, meta, "P0" if meta["name"].startswith("boat-p0") else "P1")
        case.report["first_forecast_artifacts"] = [deepcopy(meta) for ident, (_, meta) in case.archives.items() if ident != 701]
        case.result(701, case.observations, case.report, "2030-04-01T02:30:00Z")
        case.archives[701] = encrypted(*case.archives[701], "RESULT")
        with patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("reader inferred")):
            status = case.refresh()
            cached = fixtures.projection.read_projection(case.root)
        self.assertEqual(cached["status"], status)
        self.assertGreater(status["counts"]["forecasts"], 0)
        self.assertEqual(status["counts"]["result_observations"], 2)
        for ident, (raw, _) in case.archives.items():
            self.assertEqual((case.root/f"workflow-projection/artifacts/{ident}/artifact-{ident}.zip").read_bytes(), raw)

    def test_repeat_complete_reads_actual_encrypted_result_before_advancing_session(self):
        from contextlib import redirect_stdout
        from race_ai import repeated_cycle
        from tests.test_continuity_checkpoint import continuity
        report = dict(day_jst="2030-04-01", round_no=1, run_id="99", forecast_count=0,
                      scored_forecasts=0, result_observation_versions=0)
        report["report_sha256"] = digest(report)
        original = packed({"official-result-observations.json": b"[]", "status.json": json.dumps(report)})
        metadata = dict(id=701, name="race-existing-cycle-99", expired=False, created_at="2030-04-01T08:00:02Z",
                        workflow_run=dict(id=99, head_repository_id=1416489937))
        outer, meta = encrypted(original, metadata, "RESULT")
        mapping = {"actions/artifacts/701": json.dumps(meta).encode(), "actions/artifacts/701/zip": outer}
        now = datetime(2030, 4, 1, 8, 0, 3, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); folder = root/"cycle_recovery_output"; folder.mkdir()
            (folder/"continuity.json").write_bytes(continuity())
            session_path = folder/"repeat-session.json"
            repeated_cycle.start(session_path, day="2030-04-01", run_id=99, now=now)
            repeated_cycle.prepare(session_path, 1, now=now)
            output = root/"existing_cycle_output"; output.mkdir(); (output/"status.json").write_text(json.dumps(report))
            with patch.object(github_existing_cycle, "ROOT", root), \
                 patch.object(github_existing_cycle, "gh", side_effect=lambda endpoint: mapping[endpoint]), \
                 patch.object(github_existing_cycle.time, "sleep"), \
                 patch.object(github_existing_cycle, "datetime") as clock, \
                 patch.dict(os.environ, GITHUB_RUN_ID="99"), redirect_stdout(io.StringIO()):
                clock.now.return_value = now
                github_existing_cycle.repeat_complete("2030-04-01", 1, 700, 701)
            self.assertEqual(repeated_cycle.load(session_path)["completed_round"], 1)
            restored = cycle_recovery.load_state(folder/"continuity.json", "2030-04-01")
            self.assertEqual(restored["history_context"]["receipt"], meta)

    def test_all_model_wrapper_reads_verified_encrypted_baseline_and_rejects_head_tamper(self):
        _, original, metadata = sample()
        outer, meta = encrypted(original, metadata, "P0")
        meta["expires_at"] = "2030-04-08T02:00:00Z"
        info = dict(id=2, head_sha=HEAD, repository=dict(id=1416489937, full_name="haji84/RACE-AI"),
                    head_repository=dict(id=1416489937, full_name="haji84/RACE-AI"))
        mapping = {"actions/artifacts/1": json.dumps(meta).encode(), "actions/artifacts/1/zip": outer,
                   "actions/runs/2": json.dumps(info).encode()}
        with patch.object(boat_all_model_cycle, "gh", side_effect=lambda endpoint: mapping[endpoint]), \
             patch.object(boat_all_model_cycle, "utc_now", return_value=datetime(2030, 4, 1, 2, tzinfo=timezone.utc)):
            body, checked = boat_all_model_cycle._artifact(1, member="forecasts.json", expected_name="boat-p0-existing-2",
                                                        expected_run="2", expected_head=HEAD)
            with zipfile.ZipFile(io.BytesIO(original)) as archive: self.assertEqual(body, archive.read("forecasts.json"))
            self.assertEqual(checked, meta)
            meta["workflow_run"]["head_sha"] = "b" * 40
            mapping["actions/artifacts/1"] = json.dumps(meta).encode()
            with self.assertRaises(ValueError):
                boat_all_model_cycle._artifact(1, member="forecasts.json", expected_name="boat-p0-existing-2",
                                              expected_run="2", expected_head=HEAD)
