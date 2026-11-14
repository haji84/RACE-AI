"""Offline original-artifact readback and immutable owner-private view cache."""
from copy import deepcopy
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai.actions_contract import digest
from tests.private_cycle_ui_fixture import _artifacts

try:
    projection = importlib.import_module("race_ai.workflow_live_projection")
except ModuleNotFoundError:
    projection = None


def packed(members):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, json.dumps(value, ensure_ascii=False))
    return stream.getvalue()


class WorkflowLiveProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(projection, "refresh_projection", None)),
                        "saved workflow projection is not connected")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        artifacts, self.observations, _ = _artifacts()
        self.archives = {meta["id"]: (raw, deepcopy(meta)) for raw, meta in artifacts}
        self.calls = []
        self.run_id = 99
        self.listed = [meta["id"] for _, meta in artifacts if meta["workflow_run"]["id"] == 99]
        self.report = dict(day_jst="2030-04-01", run_id="99",
                           first_forecast_artifacts=[deepcopy(meta) for _, meta in artifacts
                                                     if meta["id"] != 701],
                           bounded_repeat_session={"source_wait": None},
                           forecast_count=999999)
        self.result(701, self.observations, self.report, "2030-04-01T02:30:00Z")

    def result(self, ident, rows, report, created_at):
        report = deepcopy(report)
        report["report_sha256"] = digest(report)
        raw = packed({"official-result-observations.json": rows, "status.json": report})
        meta = dict(id=ident, name="race-existing-cycle-99" + ("-cycle-02" if ident != 701 else ""),
                    expired=False, created_at=created_at, digest="sha256:" + sha256(raw).hexdigest(),
                    workflow_run=dict(id=99, head_repository_id=1416489937))
        self.archives[ident] = raw, meta

    def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == f"actions/runs/{self.run_id}":
            return json.dumps(dict(id=self.run_id, workflow_id=405276784,
                                   head_branch="feat/four-sport-forecast-audit-view-20261022")).encode()
        prefix = f"actions/runs/{self.run_id}/artifacts?per_page=100"
        if endpoint.startswith(prefix):
            page = int(endpoint.rsplit("page=", 1)[-1]) if "&page=" in endpoint else 1
            entries = [deepcopy(self.archives[i][1]) if i in self.archives else
                       dict(id=i, name="unrelated-source-bundle") for i in self.listed]
            return json.dumps(dict(total_count=len(entries), artifacts=entries[(page-1)*100:page*100])).encode()
        parts = endpoint.split("/")
        if len(parts) in (3, 4) and parts[:2] == ["actions", "artifacts"]:
            raw, meta = self.archives[int(parts[2])]
            return raw if len(parts) == 4 else json.dumps(meta).encode()
        raise AssertionError("unexpected API request")

    def refresh(self):
        return projection.refresh_projection(self.get, self.root, self.run_id,
                                             dataset_status="SYNTHETIC_ONLY")

    def test_exact_originals_project_without_inference_and_counts_are_not_report_claims(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("provider GET")), \
             patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("inference")), \
             patch("race_ai.observed_weight_learning.fit_from_verified", side_effect=AssertionError("training")):
            status = self.refresh()
            cached = projection.read_projection(self.root)
        self.assertEqual(cached["status"], status)
        view = cached["view"]
        self.assertEqual(view["dataset_status"], "SYNTHETIC_ONLY")
        forecasts = [p for r in view["records"] for p in
                     [r["prediction"], *r["comparison_predictions"]] if p]
        self.assertEqual({p["stage"] for p in forecasts}, {"P0", "P1"})
        self.assertEqual(status["counts"]["forecasts"], len(forecasts))
        self.assertNotEqual(status["counts"]["forecasts"], 999999)
        self.assertEqual(status["counts"]["result_observations"], 2)
        self.assertFalse(view["independent_receipt_verified"])
        for delivery in status["delivery"]["boat"].values():
            self.assertIsNone(delivery["visible_at"])
            self.assertEqual(delivery["window_status"], "UNKNOWN",
                             "as_of must not become an invented source or generation time")
        for ident, (raw, _) in self.archives.items():
            original = self.root / "workflow-projection" / "artifacts" / str(ident) / f"artifact-{ident}.zip"
            self.assertEqual(original.read_bytes(), raw)
            self.assertEqual(original.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "workflow-projection").stat().st_mode & 0o777, 0o700)

    def test_repeat_poll_never_redownloads_originals_or_changes_revision(self):
        before = self.refresh()
        self.calls.clear()
        after = self.refresh()
        self.assertEqual(after, before)
        self.assertFalse(any(endpoint.startswith("actions/artifacts/") for endpoint in self.calls))

    def test_large_repeated_result_reports_keep_originals_and_a_bounded_view_input(self):
        initial=self.refresh();before=projection.read_projection(self.root)['view']
        report=deepcopy(self.report);report['diagnostic_padding']='x'*(11*1024*1024)
        for ident,at in ((701,'2030-04-01T02:30:00Z'),(702,'2030-04-01T03:00:00Z'),
                         (703,'2030-04-01T03:30:00Z')):
            self.result(ident,self.observations,report,at)
            if ident==703:self.archives[ident][1]['name']='race-existing-cycle-99-cycle-03'
        self.listed.extend((702,703))
        # An already cached original is immutable; this test changes the first
        # report before its capture in a fresh private cache.
        other=tempfile.TemporaryDirectory();self.addCleanup(other.cleanup)
        self.root=Path(other.name)
        status=self.refresh();after=projection.read_projection(self.root)['view']
        fingerprints=lambda view:[(row['race_id'],p['prediction_sha256'],p['ordered_top8'])
            for row in view['records'] for p in [row['prediction'],*row['comparison_predictions']] if p]
        self.assertEqual(fingerprints(before),fingerprints(after))
        self.assertEqual(status['counts'],initial['counts'])
        self.assertEqual([r['result_observations'] for r in before['records']],
                         [r['result_observations'] for r in after['records']])
        refs={(r['artifact_id'],r['member_name']):r['member_sha256']
              for r in after['original_document_references']}
        for ident in (701,702,703):
            raw=self.archives[ident][0]
            cached=self.root/'workflow-projection'/'artifacts'/str(ident)/f'artifact-{ident}.zip'
            self.assertEqual(cached.read_bytes(),raw)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                self.assertEqual(refs[(ident,'status.json')],sha256(archive.read('status.json')).hexdigest())

    def test_pending_forecast_document_keeps_exact_reference_without_a_view_body(self):
        before=self.refresh()
        pending=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',day_jst='2030-04-01',
                     observed_at='2030-04-01T02:00:00Z',paired_forecasts=[],
                     paired_forecast_count=0,additional_official_feature_shadows=[],
                     observed_pairwise_p1_bundles=[],learned_pairwise_shadows=[])
        raw=packed({'national.json':pending})
        meta=dict(id=900,name='boat-national-cutoff-99-cycle-03',expired=False,
                  digest='sha256:'+sha256(raw).hexdigest(),created_at='2030-04-01T02:00:00Z',
                  workflow_run=dict(id=99,head_repository_id=1416489937))
        self.archives[900]=raw,meta;self.listed.append(900)
        with patch.object(projection,'project_state',wraps=projection.project_state) as project:
            after=self.refresh()
        self.assertEqual(after['counts'],before['counts'])
        self.assertFalse(any(d['artifact_id']==900 for d in project.call_args.args[0]['original_documents']))
        view=projection.read_projection(self.root)['view']
        self.assertTrue(any(d['artifact_id']==900 and d['member_name']=='national.json'
                            for d in view['original_document_references']))
        original=self.root/'workflow-projection'/'artifacts'/'900'/'artifact-900.zip'
        self.assertEqual(original.read_bytes(),raw)
    def test_new_result_refresh_preserves_first_forecast_sha_and_capture_history(self):
        self.refresh()
        before = projection.read_projection(self.root)["view"]
        later = deepcopy(self.observations[-1])
        later["captured_at"] = "2030-04-01T03:00:00Z"
        later["data"]["payouts"][0]["payout_per_100_yen"] = 2600
        later["source_sha256"] = sha256(json.dumps(later["data"], sort_keys=True).encode()).hexdigest()
        self.result(702, [*self.observations, later], self.report, "2030-04-01T03:10:00Z")
        self.listed.append(702)
        self.calls.clear()
        status = self.refresh()
        after = projection.read_projection(self.root)["view"]
        self.assertNotEqual(status["revision"], digest(before))
        self.assertEqual(status["counts"]["result_observations"], 3)
        def originals(view):
            return [(p["prediction_sha256"], p["persisted_at"], p["ordered_top8"])
                    for row in view["records"] for p in
                    [row["prediction"], *row["comparison_predictions"]] if p]
        self.assertEqual(originals(after), originals(before))
        self.assertEqual([p for p in self.calls if p.startswith("actions/artifacts/")],
                         ["actions/artifacts/702", "actions/artifacts/702/zip"])

    def test_paginated_run_artifacts_include_saved_result_on_page_two(self):
        originals = list(self.listed)
        self.listed = list(range(1000, 1100)) + originals
        status = self.refresh()
        self.assertEqual(status["counts"]["result_observations"], 2)
        self.assertIn("actions/runs/99/artifacts?per_page=100&page=2", self.calls)

    def test_corrupt_original_or_view_never_silently_replaces_published_snapshot(self):
        status = self.refresh()
        pointer = self.root / "workflow-projection" / "current.json"
        prior = pointer.read_bytes()
        original = self.root / "workflow-projection" / "artifacts" / "1" / "artifact-1.zip"
        original.write_bytes(original.read_bytes() + b"corrupt")
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(pointer.read_bytes(), prior)
        snapshot = self.root / "workflow-projection" / "days" / status["day_jst"] / "snapshots" / status["revision"] / "view.json"
        snapshot.write_text("{}")
        with self.assertRaises(ValueError):
            projection.read_projection(self.root)

    def test_missing_or_changed_original_receipt_fails_before_publication(self):
        self.refresh()
        pointer = self.root / "workflow-projection" / "current.json"
        before = pointer.read_bytes()
        report = deepcopy(self.report)
        report["first_forecast_artifacts"][0]["digest"] = "sha256:" + "f" * 64
        self.result(702, self.observations, report, "2030-04-01T03:10:00Z")
        self.listed.append(702)
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(pointer.read_bytes(), before)

    def test_corrupt_report_hash_cannot_publish_claimed_source_wait(self):
        self.refresh()
        pointer = self.root / "workflow-projection" / "current.json"
        before = pointer.read_bytes()
        report = deepcopy(self.report)
        report["report_sha256"] = "f" * 64
        raw = packed({"official-result-observations.json": self.observations,
                      "status.json": report})
        meta = deepcopy(self.archives[701][1])
        meta.update(id=702, name="race-existing-cycle-99-cycle-02",
                    digest="sha256:" + sha256(raw).hexdigest(), created_at="2030-04-01T03:00:00Z")
        self.archives[702] = raw, meta
        self.listed.append(702)
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(pointer.read_bytes(), before)

    def test_source_wait_is_authenticated_and_readers_perform_no_api_calls(self):
        wait = dict(state="RATE_LIMIT_WAIT", reason="SOURCE_HTTP_429",
                    retry_at="2030-04-01T03:30:00Z", http_status=429, attempts=1)
        report = deepcopy(self.report)
        report["bounded_repeat_session"]["source_wait"] = wait
        self.result(701, self.observations, report, "2030-04-01T02:30:00Z")
        status = self.refresh()
        self.assertEqual(status["source_wait"], wait)
        calls = list(self.calls)
        with patch("subprocess.Popen", side_effect=AssertionError("GitHub request")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("provider request")):
            self.assertEqual(projection.read_projection(self.root)["status"], status)
        self.assertEqual(self.calls, calls)

    def test_new_day_has_separate_snapshot_and_does_not_relabel_yesterdays_originals(self):
        previous = self.refresh()
        old = projection.read_projection(self.root)
        p0 = dict(schema="RACE_AI_EXISTING_P0_DAY_V1", day_jst="2030-04-02",
                  predictions=[], race_count=0, model_forecast_count=0, actual_purchases=False)
        raw = packed({"forecasts.json": p0})
        meta = dict(id=800, name="boat-p0-existing-100", expired=False,
                    digest="sha256:" + sha256(raw).hexdigest(), created_at="2030-04-02T01:00:00Z",
                    workflow_run=dict(id=100, head_repository_id=1416489937))
        self.archives[800] = raw, meta
        report = dict(day_jst="2030-04-02", run_id="100", first_forecast_artifacts=[meta])
        report["report_sha256"] = digest(report)
        raw = packed({"official-result-observations.json": [], "status.json": report})
        meta = dict(id=801, name="race-existing-cycle-100", expired=False,
                    digest="sha256:" + sha256(raw).hexdigest(), created_at="2030-04-02T01:05:00Z",
                    workflow_run=dict(id=100, head_repository_id=1416489937))
        self.archives[801] = raw, meta
        self.run_id = 100
        self.listed = [800, 801]
        current = self.refresh()
        self.assertEqual(current["day_jst"], "2030-04-02")
        self.assertEqual(current["counts"]["forecasts"], 0)
        self.assertEqual(projection.read_projection(self.root, day="2030-04-01"), old)
        self.assertEqual(projection.read_projection(self.root)["view"]["event_date_jst"], "2030-04-02")
        self.assertNotEqual(previous["revision"], current["revision"])
        # A delayed poll/restart of yesterday's run may refresh its own history
        # but cannot replace the new day's current pointer.
        self.run_id = 99
        self.listed = [123, 124, 701]
        self.refresh()
        self.assertEqual(projection.read_projection(self.root)["status"], current)

    def test_delayed_older_run_poll_retains_latest_same_day_result_and_wait(self):
        self.refresh()
        wait = dict(state="RATE_LIMIT_WAIT", reason="SOURCE_HTTP_429",
                    retry_at="2030-04-01T03:30:00Z", http_status=429, attempts=1)
        report = deepcopy(self.report)
        report["bounded_repeat_session"]["source_wait"] = wait
        self.result(702, self.observations, report, "2030-04-01T03:10:00Z")
        self.listed.append(702)
        latest = self.refresh()
        self.listed.remove(702)
        delayed = self.refresh()
        self.assertEqual(delayed, latest)
        self.assertEqual(delayed["source_wait"], wait)

    def test_foreign_workflow_is_rejected_before_artifact_downloads(self):
        def foreign(endpoint):
            self.calls.append(endpoint)
            return json.dumps(dict(id=99, workflow_id=1,
                                   head_branch="feat/four-sport-forecast-audit-view-20261022")).encode()
        with self.assertRaises(ValueError):
            projection.refresh_projection(foreign, self.root, 99)
        self.assertEqual(self.calls, ["actions/runs/99"])

    def test_git_symlink_and_hardlink_output_paths_are_refused(self):
        (self.root / ".git").mkdir()
        with self.assertRaises((ValueError, OSError)):
            self.refresh()
        self.assertEqual(self.calls, [])
        (self.root / ".git").rmdir()
        actual = self.root / "actual"
        actual.mkdir(mode=0o700)
        (self.root / "workflow-projection").symlink_to(actual, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.refresh()
        self.assertEqual(self.calls, [])
        (self.root / "workflow-projection").unlink()
        self.refresh()
        pointer = self.root / "workflow-projection" / "current.json"
        os.link(pointer, self.root / "pointer-alias")
        with self.assertRaises((ValueError, OSError)):
            projection.read_projection(self.root)


if __name__ == "__main__":
    unittest.main()
