"""Real native inference, encryption and local Git; fictional source structures."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from race_ai import boat_all_model_cycle as engine, boat_model_runtime as runtime, boat_all_model_store as store
from race_ai.actions_contract import digest
from race_ai.boat_history_store import HistoryStore, wire
from race_ai.boat_pdca_recipient import receiver_document
from tests.test_boat_all_model_cycle import source_context, native_baseline, fitted_ranker, HEAD, NOW
from tests.test_boat_history_store import archives, DAY
from tests.test_boat_model_runtime import local_repos

try:
    cli = importlib.import_module("scripts.boat_all_model_cycle")
except ModuleNotFoundError:
    cli = None

KEY = bytes(range(32))


def zipped(name, raw):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, raw)
    return out.getvalue()


class AllModelCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ranker = fitted_ranker()

    def setUp(self):
        self.assertIsNotNone(cli, "all-model Actions wrapper is absent")
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.repo = local_repos(self.base)
        self.temp = self.base/"private"; self.temp.mkdir(mode=0o700)
        self.output = self.base/"outputs"; self.output.touch(mode=0o600)
        self.env = patch.dict(os.environ, dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="haji84/RACE-AI",
            GITHUB_REPOSITORY_ID="1416489937", GITHUB_RUN_ID="42", GITHUB_SHA=HEAD, RUNNER_TEMP=str(self.temp),
            RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(), GITHUB_OUTPUT=str(self.output)))
        self.env.start(); self.addCleanup(self.env.stop)
        self.patches = [patch.object(cli, "ROOT", self.repo), patch.object(cli, "git_auth"),
                        patch.object(cli, "_existing_view", return_value={"records": []}), patch.object(cli, "utc_now", return_value=NOW)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        class LocalRuntime(runtime.GitRuntimeRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(["remote", "get-url", "origin"]).decode().strip()
        class LocalForecast(store.GitForecastRepository):
            def _check_remote(self):
                self.fetch_url = self.push_url = self._run(["remote", "get-url", "origin"]).decode().strip()
        self.runtime_git = LocalRuntime(self.repo); self.forecast_git = LocalForecast(self.repo)
        for target, name, value in ((runtime, "GitRuntimeRepository", LocalRuntime), (store, "GitForecastRepository", LocalForecast)):
            p = patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        source = self.base/"source"; source.mkdir(mode=0o700)
        db = HistoryStore(source/"history.sqlite"); raw, proofs = archives()
        db.ingest_day(DAY, raw["B"], raw["K"], proofs["B"], proofs["K"]); db.close()
        self.files = {"history.sqlite": (source/"history.sqlite").read_bytes(), "racers.sqlite": (source/"history.sqlite").read_bytes(),
                      "ranker.json": wire(self.ranker).encode(), "metadata.json": wire({"schema": "SYNTHETIC_RUNTIME"}).encode(),
                      "native-view.json": wire({"records": []}).encode()}
        self.publish_runtime()

    def publish_runtime(self):
        raw, _ = runtime.seal_runtime(self.files, receiver_document(key=KEY, run_id="42", source_head=HEAD), created_at=NOW.isoformat())
        pointer = runtime.publish_runtime(raw, self.repo, expected_parent=self.runtime_git.head(), transport=self.runtime_git)
        folder = self.repo/"audit/state"; folder.mkdir(parents=True, exist_ok=True)
        (folder/"boat-model-runtime-input.json").write_text(wire(pointer))
        return pointer

    def artifact(self, member, body, *, ident=101, name=None, saved="2030-04-01T18:00:20+09:00"):
        archive = zipped(member, body)
        meta = dict(id=ident, name=name or cli.artifact_name("42", 1), expired=False,
                    digest="sha256:"+hashlib.sha256(archive).hexdigest(), size_in_bytes=len(archive), created_at=saved,
                    expires_at="2030-04-08T18:00:20+09:00",
                    workflow_run=dict(id=42, repository_id=1416489937, head_repository_id=1416489937, head_sha=HEAD))
        run = dict(id=42, head_sha=HEAD, repository=dict(id=1416489937, full_name="haji84/RACE-AI"),
                   head_repository=dict(id=1416489937, full_name="haji84/RACE-AI"))
        mapping = {f"actions/artifacts/{ident}": wire(meta).encode(), f"actions/artifacts/{ident}/zip": archive,
                   "actions/runs/42": wire(run).encode()}
        return mapping, meta

    def run_cli(self, args):
        out = io.StringIO()
        with redirect_stdout(out): code = cli.main(args)
        self.assertNotIn(base64.b64encode(KEY).decode(), out.getvalue())
        return code, out.getvalue()

    def test_prepare_cache_binds_exact_pointer_files_and_current_round(self):
        code, _ = self.run_cli(["prepare", "--round", "1"]); self.assertEqual(code, 0)
        ready = cli.restore_ready()
        self.assertEqual((ready["run_id"], ready["round_no"], ready["source_code_commit"]), ("42", 1, HEAD))
        self.assertEqual(ready["metadata_sha256"], hashlib.sha256(self.files["metadata.json"]).hexdigest())
        self.assertEqual(Path(ready["runtime_files"]["history.sqlite"]).read_bytes(), self.files["history.sqlite"])
        with patch.object(runtime, "restore_runtime", side_effect=AssertionError("cache performed transport")):
            self.assertEqual(cli.prepare_runtime(round_no=2)["round_no"], 2)
        Path(ready["runtime_files"]["metadata.json"]).write_bytes(b'{"tampered":true}')
        with self.assertRaises(ValueError): cli.restore_ready()

    def test_compact_saved_races_refresh_separate_p0_and_p1_issued_maps(self):
        mid = "multisport-chronological-ranker-v1"
        view = {"records": [dict(race_id="20300401-01-01", stage="P0", prediction=dict(model_id=mid))]}
        with patch.object(cli, "_existing_view", return_value=view):
            ready = cli.prepare_runtime(round_no=1)
            self.assertEqual(json.loads(Path(ready["issued_p0_models_path"]).read_text()), {"20300401-01-01": [mid]})
            self.assertEqual(json.loads(Path(ready["issued_models_path"]).read_text()), {})
            view["records"].append(dict(race_id="boat:2030-04-01:boatrace-jcd-01:1", stage="P1", prediction=dict(model_id=mid)))
            with patch.object(runtime, "restore_runtime", side_effect=AssertionError("cached runtime restored")):
                updated = cli.prepare_runtime(round_no=2)
            self.assertEqual(json.loads(Path(updated["issued_models_path"]).read_text()), {"20300401-01-01": [mid]})
            self.assertEqual(updated["issued_p0_models_sha256"], ready["issued_p0_models_sha256"])
            self.assertNotEqual(updated["issued_models_sha256"], ready["issued_models_sha256"])
        for invalid in ("20300230-01-01", "20300401-25-01", "20300401-01-13", "20300401-1-1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                cli._inventory({"records": [dict(race_id=invalid)]}, {"P0": {}, "P1": {}})

    def test_generate_and_independent_readback_keep_cipher_only_and_real_native_predictions(self):
        cli.prepare_runtime(round_no=1)
        ctx = source_context(); engine.retain_current_input(ctx["program"], ctx["beforeinfo"], ctx["as_of"], self.temp/"boat-all-model-inputs/cycle-1")
        baseline = native_baseline(ctx)
        mapping, _ = self.artifact("national.json", wire(baseline).encode(), ident=99,
                                   name="boat-national-cutoff-42", saved="2030-04-01T18:00:05+09:00")
        with patch.object(cli, "gh", side_effect=lambda p: mapping[p]):
            code, text = self.run_cli(["generate", "--round", "1", "--baseline-artifact", "99"])
        self.assertEqual(code, 0, text)
        folder = self.temp/"boat-all-model-forecasts/cycle-1"
        self.assertEqual([p.name for p in folder.iterdir()], ["forecasts.enc"])
        cipher = (folder/"forecasts.enc").read_bytes(); payload = store.open_forecasts(cipher, key=KEY)
        self.assertGreater(payload["summary"]["generated_forecasts"], 0)
        self.assertEqual(payload["summary"]["reused_baseline_forecasts"], 5)
        self.assertEqual(Path(cli.restore_ready()["runtime_files"]["history.sqlite"]).read_bytes(), self.files["history.sqlite"])
        with patch.object(engine, "forecast_round", side_effect=AssertionError("sealed round regenerated")):
            code, text = self.run_cli(["generate", "--round", "1", "--baseline-artifact", "99"])
            self.assertEqual(code, 0, text)
        mapping, _ = self.artifact("forecasts.enc", cipher)
        with patch.object(cli, "gh", side_effect=lambda p: mapping[p]), patch.object(cli, "utc_now", return_value=datetime.fromisoformat("2030-04-01T18:00:30+09:00")):
            code, text = self.run_cli(["readback", "--round", "1", "--artifact", "101"])
        self.assertEqual(code, 0, text)
        ref = json.loads((self.temp/"boat-all-model-readback.json").read_text())
        self.assertEqual(ref["receipt"]["payload_sha256"], digest(payload))
        self.assertTrue(ref["receipt"]["independently_verified"])
        view = json.loads(Path(ref["private_view_path"]).read_text())
        self.assertTrue(view["independent_receipts_verified"])
        self.assertEqual(store.restore_forecasts(ref["pointer"], self.repo, key=KEY, transport=self.forecast_git), payload)

    def test_wrong_artifact_bytes_or_head_cannot_publish(self):
        cli.prepare_runtime(round_no=1)
        ctx = source_context(); engine.retain_current_input(ctx["program"], ctx["beforeinfo"], ctx["as_of"], self.temp/"boat-all-model-inputs/cycle-1")
        self.assertEqual(self.run_cli(["generate", "--round", "1"])[0], 0)
        cipher = (self.temp/"boat-all-model-forecasts/cycle-1/forecasts.enc").read_bytes()
        for kind in ("digest", "head", "member", "cipher"):
            mapping, meta = self.artifact("extra.enc" if kind == "member" else "forecasts.enc", cipher+b"x" if kind == "cipher" else cipher)
            if kind == "digest": meta["digest"] = "sha256:"+"f"*64
            if kind == "head": meta["workflow_run"]["head_sha"] = "b"*40
            mapping["actions/artifacts/101"] = wire(meta).encode()
            with patch.object(cli, "gh", side_effect=lambda p: mapping[p]), patch.object(cli, "utc_now", return_value=datetime.fromisoformat("2030-04-01T18:00:30+09:00")):
                self.assertEqual(self.run_cli(["readback", "--round", "1", "--artifact", "101"])[0], 2)
            self.assertIsNone(self.forecast_git.head())
            self.assertFalse((self.temp/"boat-all-model-readback.json").exists())

    def test_runtime_saved_p0_bootstrap_uses_current_clock_and_genuine_fitted_model(self):
        from tests.test_frozen_day_cycle import sample
        document, _, _ = sample()
        receipt = dict(repository_id="1416489937", repository="haji84/RACE-AI", run_id="41", head_sha="b"*40,
                       artifact_id=98, created_at="2030-04-01T01:43:00Z", payload_sha256=digest(document), independently_verified=True)
        self.files["p0-source.json"] = wire(dict(document=document, receipt=receipt)).encode()
        self.publish_runtime()
        now = datetime.fromisoformat("2030-04-01T01:44:00Z")
        with patch.object(cli, "utc_now", return_value=now):
            code, text = self.run_cli(["bootstrap-current"])
        self.assertEqual(code, 0, text)
        payload = store.open_forecasts((self.temp/"boat-all-model-forecasts/cycle-0/forecasts.enc").read_bytes(), key=KEY)
        self.assertEqual(payload["stage"], "P0")
        self.assertEqual(payload["generated_at"], now.isoformat())
        self.assertEqual(payload["summary"]["generated_forecasts"], 5)
        learned = next(s for s in payload["dispatch_reports"][0]["slots"] if s["model_id"] == "multisport-chronological-ranker-v1")
        self.assertTrue(learned["prediction"]["trained"])
