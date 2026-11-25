"""Official SP watchdog safety decisions with a fake gh transport."""

from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


NOW = datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc)
MAIN = "a" * 40
PRODUCER = 421980983
REPO_ID = 1416489937
PATH = ".github/workflows/keirin-nationwide-ab-auto.yml"
WORKFLOW = "repos/haji84/RACE-AI/actions/workflows/keirin-nationwide-ab-auto.yml"
WRITE = ("workflow", "run", "keirin-nationwide-ab-auto.yml",
         "--repo", "github.com/haji84/RACE-AI", "--ref", "main", "-f", "mode=official-continue")


def timestamp(delta):
    return (NOW - timedelta(minutes=delta)).isoformat()


def run(rid, *, age=75, event="schedule", status="completed", conclusion="success"):
    return {
        "id": rid, "workflow_id": PRODUCER, "path": PATH, "head_branch": "main",
        "head_sha": "b" * 40, "repository": {"id": REPO_ID},
        "head_repository": {"id": REPO_ID}, "run_attempt": 1, "event": event,
        "status": status, "conclusion": conclusion, "created_at": timestamp(age + 6),
        "updated_at": timestamp(age - 1),
    }


class Github:
    def __init__(self, *, age=75):
        self.calls = []
        self.repository = {
            "id": REPO_ID, "full_name": "haji84/RACE-AI", "default_branch": "main",
            "archived": False, "disabled": False,
        }
        self.heads = [MAIN]
        self.workflow_state = "active"
        self.active = {}
        self.rows = [run(7, age=age)]
        self.captures = {7: (age, "success")}
        self.receipt = {
            "schema": "RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1",
            "state": "OFFICIAL_SP_BASELINES_ARCHIVED", "source_requests": 5,
            "provider_denied": False, "source_or_forecast_plaintext_exposed": False,
            "statuses": {}, "safe_diagnostics": [],
        }
        self.archive = None
        self.failure = None
        self.on_dispatch = None
        self.on_history = None

    def __call__(self, args):
        args = tuple(args)
        self.calls.append(args)
        if args == WRITE:
            if self.on_dispatch is not None:
                self.on_dispatch()
            if self.failure is not None:
                raise self.failure
            return b"https://github.com/haji84/RACE-AI/actions/runs/999\n"
        assert args[:3] == ("api", "--hostname", "github.com"), args
        path = args[3]
        endpoint = path.partition("?")[0]
        if path == "repos/haji84/RACE-AI":
            data = self.repository
        elif path == "repos/haji84/RACE-AI/branches/main":
            head = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
            data = {"name": "main", "protected": True, "commit": {"sha": head}}
        elif path == WORKFLOW:
            data = {"id": PRODUCER, "path": PATH, "state": self.workflow_state}
        elif endpoint == WORKFLOW + "/runs":
            rows = self.rows
            for status, matching in self.active.items():
                if "status=" + status + "&" in path:
                    rows = matching
                    break
            else:
                if "status=" in path:
                    rows = []
                elif self.on_history is not None:
                    self.on_history()
                    rows = self.rows
            data = {"total_count": len(rows), "workflow_runs": rows}
        elif endpoint.endswith("/jobs"):
            rid = int(endpoint.split("/runs/")[1].split("/")[0])
            age, conclusion = self.captures[rid]
            job = {
                "name": "official-sp-capture", "run_id": rid, "run_attempt": 1,
                "head_sha": "b" * 40, "status": "completed", "conclusion": conclusion,
                "steps": [] if conclusion == "skipped" else [{
                    "name": "Register the official day and preserve future original forecasts",
                    "status": "completed", "conclusion": conclusion,
                    "started_at": timestamp(age + 5), "completed_at": timestamp(age),
                }],
            }
            data = {"total_count": 1, "jobs": [job]}
        elif endpoint.endswith("/artifacts"):
            rid = int(endpoint.split("/runs/")[1].split("/")[0])
            age, _ = self.captures[rid]
            target = f"keirin-official-sp-receipt-{rid}"
            if self.receipt is None:
                data = {"total_count": 0, "artifacts": []}
            else:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as zipped:
                    zipped.writestr("summary.json", json.dumps(self.receipt))
                self.archive = buffer.getvalue()
                artifact = {
                    "id": rid + 500, "name": target, "expired": False,
                    "digest": "sha256:" + sha256(self.archive).hexdigest(),
                    "size_in_bytes": len(self.archive), "created_at": timestamp(age - 1),
                    "workflow_run": {"id": rid, "head_branch": "main", "head_sha": "b" * 40,
                                     "repository_id": REPO_ID, "head_repository_id": REPO_ID},
                }
                data = {"total_count": 1, "artifacts": [artifact]}
        elif endpoint.endswith("/zip"):
            return self.archive
        else:
            raise AssertionError(path)
        return json.dumps(data).encode()


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        # The first cycle intentionally fails here, before the CLI exists.
        spec = importlib.util.find_spec("scripts.keirin_official_sp_watchdog")
        self.assertIsNotNone(spec, "The official SP watchdog CLI is missing")
        self.watchdog = importlib.import_module(spec.name)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.state = Path(self.folder.name) / "private"

    def supervise(self, client, *, dispatch=False, now=NOW):
        return self.watchdog.supervise(client, now=now, dispatch=dispatch, state_dir=self.state)

    def test_stale_safe_capture_is_read_only_by_default(self):
        gh = Github()
        report = self.supervise(gh)
        self.assertEqual(report["decision"], "WOULD_DISPATCH_OFFICIAL_CONTINUE")
        self.assertEqual(report["last_actual_capture_run_id"], 7)
        self.assertFalse(self.state.exists())
        self.assertNotIn(WRITE, gh.calls)

    def test_recent_real_capture_holds_even_on_a_previous_main_sha(self):
        gh = Github(age=22)
        report = self.supervise(gh, dispatch=True)
        self.assertEqual(report["decision"], "SKIP_RECENT_OFFICIAL_SP_CAPTURE")
        self.assertNotIn(WRITE, gh.calls)

    def test_active_main_workflow_from_any_event_blocks_before_history(self):
        gh = Github()
        gh.active["queued"] = [run(99, event="push", status="queued", conclusion=None)]
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_ACTIVE_OFFICIAL_SP_WORKFLOW")
        self.assertNotIn(WRITE, gh.calls)

    def test_recent_green_workflow_with_skipped_capture_does_not_hide_stale_capture(self):
        gh = Github()
        gh.rows.insert(0, run(9, age=8, event="workflow_dispatch"))
        gh.captures[9] = (8, "skipped")
        report = self.supervise(gh)
        self.assertEqual(report["decision"], "WOULD_DISPATCH_OFFICIAL_CONTINUE")
        self.assertEqual(report["last_actual_capture_run_id"], 7)

    def test_green_outer_job_still_can_report_provider_denial(self):
        gh = Github()
        gh.receipt["provider_denied"] = True
        gh.rows.insert(0, run(9, age=8, event="workflow_dispatch"))
        gh.captures[9] = (8, "skipped")
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_PROVIDER_STOP")
        self.assertNotIn(WRITE, gh.calls)

    def test_unknown_or_missing_receipt_holds(self):
        for receipt, expected in [(None, "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                                  ({"state": "OFFICIAL_SP_BASELINES_ARCHIVED"}, "HOLD_CAPTURE_OUTCOME_UNVERIFIED")]:
            with self.subTest(receipt=receipt):
                gh = Github()
                gh.receipt = receipt
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], expected)
                self.assertNotIn(WRITE, gh.calls)

    def test_lease_failure_holds_even_when_workflow_is_green(self):
        gh = Github()
        gh.receipt["source_lease_finish_failed"] = True
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_STOPPING_STATE")

    def test_stopped_outer_job_cannot_be_ignored(self):
        gh = Github()
        gh.rows[0]["conclusion"] = "failure"
        gh.captures[7] = (75, "failure")
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_JOB_FAILED")
        self.assertNotIn(WRITE, gh.calls)

    def test_rejects_wrong_repository_or_inactive_workflow(self):
        for field, expected in (("repository", "HOLD_REPOSITORY_IDENTITY"),
                                ("workflow_state", "HOLD_WORKFLOW_METADATA")):
            gh = Github()
            if field == "repository":
                gh.repository["id"] += 1
            else:
                gh.workflow_state = "disabled_manually"
            with self.subTest(field=field):
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], expected)
                self.assertNotIn(WRITE, gh.calls)

    def test_records_attempt_before_exact_dispatch_and_applies_local_cooldown(self):
        gh = Github()

        def assert_receipt():
            receipt = self.state / "last-attempt.json"
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(receipt.read_text())["status"], "unconfirmed")

        gh.on_dispatch = assert_receipt
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "DISPATCHED_OFFICIAL_CONTINUE")
        self.assertEqual(gh.calls[-2], ("api", "--hostname", "github.com", "repos/haji84/RACE-AI/branches/main"))
        self.assertEqual(gh.calls.count(WRITE), 1)
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_LOCAL_ATTEMPT_RECENT")
        self.assertEqual(gh.calls.count(WRITE), 1)

    def test_cli_receipt_is_separate_from_the_video_research_state(self):
        home = Path(self.folder.name)
        with patch.object(Path, "home", return_value=home):
            report = self.watchdog.supervise(Github(), now=NOW, dispatch=True)
        self.assertEqual(report["decision"], "DISPATCHED_OFFICIAL_CONTINUE")
        state = home / "Library/Application Support/RACE-AI/keirin-production-watch/state"
        self.assertTrue((state / "last-attempt.json").is_file())
        self.assertFalse((home / "Library/Application Support/RACE-AI/keirin-mac").exists())

    def test_ambiguous_dispatch_stays_held_past_cooldown(self):
        gh = Github()
        gh.failure = OSError("credential or other output must not appear")
        report = self.supervise(gh, dispatch=True)
        self.assertEqual(report["decision"], "HOLD_DISPATCH_UNCONFIRMED")
        self.assertNotIn("credential", json.dumps(report))
        later = NOW + timedelta(hours=2)
        self.assertEqual(self.supervise(gh, dispatch=True, now=later)["decision"],
                         "HOLD_PRIOR_DISPATCH_UNCONFIRMED")
        self.assertEqual(gh.calls.count(WRITE), 1)

    def test_main_moved_holds_before_attempt_is_recorded(self):
        gh = Github()
        gh.heads = [MAIN, "c" * 40]
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_MAIN_MOVED_NO_DISPATCH")
        self.assertFalse((self.state / "last-attempt.json").exists())
        self.assertNotIn(WRITE, gh.calls)



    def test_capture_which_finishes_during_preflight_prevents_dispatch(self):
        gh = Github()
        checks = []

        def finish_after_first_inspection():
            checks.append(True)
            if len(checks) == 2:
                gh.rows.insert(0, run(10, age=4))
                gh.captures[10] = (4, "success")

        gh.on_history = finish_after_first_inspection
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_HISTORY_MOVED_NO_DISPATCH")
        self.assertNotIn(WRITE, gh.calls)
        self.assertFalse((self.state / "last-attempt.json").exists())

    def test_native_file_lock_prevents_an_overlapping_local_dispatch(self):
        gh = Github()
        self.state.mkdir(mode=0o700)
        lock = self.state / "dispatch.lock"
        lock.touch(mode=0o600)
        with lock.open("rb") as owned:
            fcntl.flock(owned, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_LOCAL_WATCHDOG_ACTIVE")
        self.assertNotIn(WRITE, gh.calls)

    def test_acknowledged_dispatch_without_safe_capture_is_not_retried(self):
        gh = Github()
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "DISPATCHED_OFFICIAL_CONTINUE")
        later = NOW + timedelta(hours=2)
        self.assertEqual(self.supervise(gh, dispatch=True, now=later)["decision"],
                         "HOLD_PRIOR_DISPATCH_OUTCOME_UNVERIFIED")
        self.assertEqual(gh.calls.count(WRITE), 1)

    def test_unsafe_state_receipt_path_prevents_dispatch(self):
        gh = Github()
        self.state.mkdir(mode=0o700)
        (self.state / "last-attempt.json").symlink_to("/dev/null")
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_UNSAFE_LOCAL_RECEIPT")
        self.assertNotIn(WRITE, gh.calls)

    def test_malformed_receipt_state_fails_closed_with_safe_json(self):
        gh = Github()
        gh.receipt["state"] = {"unexpected": "must not appear"}
        report = self.supervise(gh, dispatch=True)
        self.assertEqual(report["decision"], "HOLD_CAPTURE_STOPPING_STATE")
        self.assertNotIn("must not appear", json.dumps(report))
        self.assertNotIn(WRITE, gh.calls)
