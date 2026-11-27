"""Official SP watchdog safety decisions with a fake gh transport."""

from base64 import b64encode
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha1, sha256
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


def timestamp(delta, now=NOW):
    return (now - timedelta(minutes=delta)).isoformat()


def run(rid, *, age=75, event="schedule", status="completed", conclusion="success", now=NOW):
    return {
        "id": rid, "workflow_id": PRODUCER, "path": PATH, "head_branch": "main",
        "head_sha": "b" * 40, "repository": {"id": REPO_ID},
        "head_repository": {"id": REPO_ID}, "run_attempt": 1, "event": event,
        "status": status, "conclusion": conclusion, "created_at": timestamp(age + 6, now),
        "updated_at": timestamp(age - 1, now),
    }


class Github:
    def __init__(self, *, age=75, now=NOW):
        self.now = now
        self.calls = []
        self.repository = {
            "id": REPO_ID, "full_name": "haji84/RACE-AI", "default_branch": "main",
            "archived": False, "disabled": False,
        }
        self.heads = [MAIN]
        self.workflow_state = "active"
        self.active = {}
        self.rows = [run(7, age=age, now=now)]
        self.captures = {7: (age, "success")}
        self.receipt = {
            "schema": "RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1",
            "day_jst": (now - timedelta(minutes=age) + timedelta(hours=9)).date().isoformat(),
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
                    "started_at": timestamp(age + 5, self.now), "completed_at": timestamp(age, self.now),
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
                    "size_in_bytes": len(self.archive), "created_at": timestamp(age - 1, self.now),
                    "workflow_run": {"id": rid, "head_branch": "main", "head_sha": "b" * 40,
                                     "repository_id": REPO_ID, "head_repository_id": REPO_ID},
                }
                data = {"total_count": 1, "artifacts": [artifact]}
        elif endpoint.endswith("/zip"):
            return self.archive
        else:
            raise AssertionError(path)
        return json.dumps(data).encode()


class PublicationFailureGithub(Github):
    def __init__(self, *, age=35, event="workflow_dispatch"):
        super().__init__(age=age)
        self.rows[0].update(event=event, conclusion="failure", updated_at=timestamp(age - 6))
        self.age = age
        self.originals = [{"race_id": "202611260101", "cipher_sha256": "d" * 64},
                          {"race_id": "202611260202", "cipher_sha256": "e" * 64}]
        self.receipt.update(new_A_B_sealed=2, new_A_B_git_archived=2, new_encrypted_originals=self.originals)
        self.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 59
        self.readback = {
            "day_jst": "2026-11-26", "schema": "RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1",
            "new_archived": 2, "independently_verified": 2,
            "records": [dict(original, state="SECOND_RUNNER_GITHUB_SHA_CONFIRMED")
                        for original in self.originals],
        }
        self.settlement = {
            "day_jst": "2026-11-26", "state": "OFFICIAL_SP_SAVED_RESULT_UPDATES_PUBLISHED",
            "source_requests": 0, "provider_denied": False, "source_unavailable": False,
            "no_provider_tick": True,
        }
        self.job_changes = {}
        self.artifact_changes = {}
        self.additional_archive = {}
        self.corrupt_zip = set()

    def __call__(self, args):
        path = args[-1]
        if path.endswith("/zip"):
            artifact_id = int(path.split("/")[-2])
            if artifact_id in self.additional_archive:
                self.calls.append(tuple(args))
                raw = self.additional_archive[artifact_id]
                return bytes([raw[0] ^ 1]) + raw[1:] if artifact_id in self.corrupt_zip else raw
        if "/artifacts?" in path:
            artifacts = {
                "keirin-official-sp-readback-7": (601, self.readback, self.age - 3,
                                                 "keirin-git-independent.json"),
                "keirin-official-sp-settlement-7": (602, self.settlement, self.age + 3, "summary.json"),
            }
            name = path.partition("name=")[2].split("&")[0]
            if name in artifacts:
                self.calls.append(tuple(args))
                artifact_id, summary, age, member = artifacts[name]
                if summary is None:
                    return b'{"total_count":0,"artifacts":[]}'
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as zipped:
                    zipped.writestr(member, json.dumps(summary))
                raw = self.additional_archive[artifact_id] = buffer.getvalue()
                artifact = {
                    "name": name, "id": artifact_id, "size_in_bytes": len(raw), "expired": False,
                    "created_at": timestamp(age), "digest": "sha256:" + sha256(raw).hexdigest(),
                    "workflow_run": {"id": 7, "head_branch": "main", "head_sha": "b" * 40,
                                     "repository_id": REPO_ID, "head_repository_id": REPO_ID},
                }
                artifact.update(self.artifact_changes.get(name, {}))
                return json.dumps({"total_count": 1, "artifacts": [artifact]}).encode()
        raw = super().__call__(args)
        if "/jobs?" not in path:
            return raw
        jobs = json.loads(raw)["jobs"]
        age = self.age
        jobs[0].update(id=101, started_at=timestamp(age + 6), completed_at=timestamp(age - 1))
        supplemental = (
            ("official-sp-settle", 102, "skipped" if self.rows[0]["event"] == "schedule" else "success",
             age + 6, age + 2),
            ("official-sp-independent-readback", 103, "success", age - 2, age - 3),
            ("official-sp-publish", 104, "failure", age - 4, age - 5),
            ("source-free-tests", 105, "success", age + 6, age + 5),
        )
        for name, job_id, conclusion, started, finished in supplemental:
            jobs.append(dict(id=job_id, name=name, status="completed", conclusion=conclusion, run_id=7,
                             run_attempt=1, head_sha="b"*40, started_at=timestamp(started),
                             completed_at=timestamp(finished)))
        for job in jobs:
            job.update(self.job_changes.get(job["name"], {}))
        return json.dumps({"jobs": jobs, "total_count": len(jobs)}).encode()


class ArchiveTimeoutGithub(PublicationFailureGithub):
    day = "2026-11-26"
    archive_head = "f" * 40
    lease_path = "state/keirin/ab/official-source-continuation/v1/leases/" + day

    def __init__(self, *, age=75):
        super().__init__(age=age)
        self.captures[7] = age, "failure"
        self.receipt.update(state="HOLD_OFFICIAL_SP_CAPTURE_ARCHIVE_FETCH_TIMEOUT", statuses={},
                            source_requests=0, registered_races=0, new_A_B_sealed=0,
                            new_A_B_git_archived=0, new_conditioned_A_B_git_archived=0,
                            new_encrypted_originals=[], paired_comparable_races=0)
        self.job_changes = {
            "official-sp-independent-readback": {"conclusion": "skipped"},
            "official-sp-publish": {"conclusion": "skipped"},
            "official-sp-settle": {"started_at": timestamp(age - 2), "completed_at": timestamp(age - 6)},
        }
        self.settlement.update(state="OFFICIAL_SP_RESULT_POLL_COMPLETE", source_requests=7,
                               no_provider_tick=False)
        self.artifact_changes["keirin-official-sp-settlement-7"] = {"created_at": timestamp(age - 5)}
        identity = dict(event_day=self.day, run_id="7", job="official-sp-settle", attempt_id="a" * 32,
                        source_commit="b" * 40, policy="EXISTING_OFFICIAL_PUBLIC_SP_20261121_V1",
                        general_source_release=False)
        self.claim = dict(identity, schema="RACE_AI_KEIRIN_OFFICIAL_SOURCE_CONTINUATION_CLAIM_V1",
                          started_at=timestamp(age - 3), max_source_requests=300)
        self.finish = dict(identity, schema="RACE_AI_KEIRIN_OFFICIAL_SOURCE_CONTINUATION_FINISH_V1",
                           state="PARTIAL", finished_at=timestamp(age - 5), requests_consumed=7)
        self.leases = {"7.official-sp-settle.claim.json": self.claim, "7.official-sp-settle.finish.json": self.finish}
        self.files = ["race_ai/keirin_nationwide_cipher_history.py", "scripts/keirin_official_nationwide_continuation.py"]
        self.blobs = {}

    def __call__(self, args):
        path = args[-1]
        base = "repos/haji84/RACE-AI"
        if path == f"{base}/compare/{'b' * 40}...{MAIN}?per_page=1":
            data = {"status": "ahead", "merge_base_commit": {"sha": "b" * 40},
                    "files": [{"filename": name, "status": "modified"} for name in self.files]}
        elif path == f"{base}/branches/state%2Fkeirin-encrypted-history":
            data = {"name": "state/keirin-encrypted-history", "commit": {"sha": self.archive_head}}
        elif path == f"{base}/contents/{self.lease_path}?ref={self.archive_head}":
            data = []
            for name, document in self.leases.items():
                raw = json.dumps(document).encode()
                digest = sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
                data.append({"type": "file", "name": name, "sha": digest, "size": len(raw)})
                self.blobs[digest] = {"sha": digest, "size": len(raw), "encoding": "base64",
                                      "content": b64encode(raw).decode()}
        elif path.startswith(f"{base}/git/blobs/"):
            data = self.blobs[path.rsplit("/", 1)[1]]
        else:
            return super().__call__(args)
        self.calls.append(tuple(args))
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

    def supervise(self, client, *, dispatch=False, now=NOW, **options):
        return self.watchdog.supervise(client, now=now, dispatch=dispatch, state_dir=self.state, **options)

    def test_pre_source_timeout_requires_opt_in_and_allows_one_guarded_recovery(self):
        gh = ArchiveTimeoutGithub()
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_JOB_FAILED")
        proof = self.supervise(gh, recovery=(7, MAIN))
        self.assertEqual(proof["decision"], "WOULD_DISPATCH_OFFICIAL_CONTINUE")
        self.assertTrue(proof["pre_source_archive_timeout_verified"])
        self.assertNotIn(WRITE, gh.calls)
        self.assertEqual(self.supervise(gh, dispatch=True, recovery=(7, MAIN))["decision"],
                         "DISPATCHED_OFFICIAL_CONTINUE")
        self.assertEqual(self.supervise(gh, dispatch=True, recovery=(7, MAIN))["decision"],
                         "HOLD_LOCAL_ATTEMPT_RECENT")
        self.assertEqual(gh.calls.count(WRITE), 1)

    def test_recovery_refuses_missing_or_inconsistent_source_proof(self):
        for issue in ("different_failure", "source_work", "capture_lease", "missing_finish", "wrong_finish",
                      "provider_denial", "unrepaired_main", "wrong_main", "wrong_run", "new_day", "recent"):
            with self.subTest(issue=issue):
                gh = ArchiveTimeoutGithub(age=40 if issue == "recent" else 75)
                now, request = NOW, (7, MAIN)
                if issue == "different_failure":
                    gh.receipt["state"] = "HOLD_OTHER_FAILURE"
                elif issue == "source_work":
                    gh.receipt["source_requests"] = 1
                elif issue == "capture_lease":
                    gh.leases["7.official-sp-capture.claim.json"] = gh.claim
                elif issue == "missing_finish":
                    gh.leases.pop("7.official-sp-settle.finish.json")
                elif issue == "wrong_finish":
                    gh.finish["requests_consumed"] = 6
                elif issue == "provider_denial":
                    gh.settlement["provider_denied"] = True
                elif issue == "unrepaired_main":
                    gh.files.pop()
                elif issue == "wrong_main":
                    request = (7, "e" * 40)
                elif issue == "wrong_run":
                    request = (8, MAIN)
                elif issue == "new_day":
                    now += timedelta(hours=12)
                decision = self.supervise(gh, dispatch=True, now=now, recovery=request)["decision"]
                self.assertTrue(decision.startswith("HOLD_") or decision == "SKIP_RECENT_OFFICIAL_SP_CAPTURE")
                self.assertNotIn(WRITE, gh.calls)

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

    def test_verified_current_jst_backlog_uses_a_20_minute_recovery_delay(self):
        for age, decision in ((19, "SKIP_RECENT_OFFICIAL_SP_CAPTURE"),
                              (20, "SKIP_RECENT_OFFICIAL_SP_CAPTURE"),
                              (21, "WOULD_DISPATCH_OFFICIAL_CONTINUE")):
            with self.subTest(age=age):
                gh = Github(age=age)
                gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 45
                report = self.supervise(gh)
                self.assertEqual(report["decision"], decision)
                self.assertEqual(report.get("recovery_delay_minutes"), 20)
                self.assertNotIn(WRITE, gh.calls)

    def test_missing_day_empty_backlog_and_prior_jst_receipts_keep_45_minutes(self):
        jst_after_midnight = NOW + timedelta(hours=12, minutes=5)
        for pending, stamp, decision_at in (
                (0, "2026-11-26", NOW),
                (4, None, NOW),
                (4, "2026-11-26", jst_after_midnight)):
            with self.subTest(pending=pending, stamp=stamp, at=decision_at):
                gh = Github(age=35, now=decision_at)
                gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = pending
                if stamp is None:
                    gh.receipt.pop("day_jst")
                else:
                    gh.receipt["day_jst"] = stamp
                report = self.supervise(gh, dispatch=True, now=decision_at)
                self.assertEqual(report["decision"], "SKIP_RECENT_OFFICIAL_SP_CAPTURE")
                self.assertEqual(report.get("recovery_delay_minutes"), 45)
                self.assertNotIn(WRITE, gh.calls)

    def test_invalid_capture_day_or_provider_stop_prevents_backlog_dispatch(self):
        for field, value, decision in (
                ("day_jst", "2026-11-27", "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                ("day_jst", "2026-11-25", "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                ("day_jst", "2026-11-40", "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                ("provider_denied", True, "HOLD_CAPTURE_PROVIDER_STOP"),
                ("source_lease_finish_failed", True, "HOLD_CAPTURE_STOPPING_STATE")):
            with self.subTest(field=field, value=value):
                gh = Github(age=35)
                gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 1
                gh.receipt[field] = value
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], decision)
                self.assertNotIn(WRITE, gh.calls)

    def test_shorter_delay_still_requires_capture_newer_than_last_local_attempt(self):
        self.state.mkdir(mode=0o700)
        previous = self.state / "last-attempt.json"
        previous.touch(mode=0o600, exist_ok=False)
        for status, previous_age, expected in (
                ("accepted", 33, "HOLD_PRIOR_DISPATCH_OUTCOME_UNVERIFIED"),
                ("unconfirmed", 33, "HOLD_PRIOR_DISPATCH_UNCONFIRMED"),
                ("accepted", 41, "DISPATCHED_OFFICIAL_CONTINUE")):
            with self.subTest(status=status, previous_age=previous_age):
                previous.write_text(json.dumps({"at": timestamp(previous_age), "status": status}))
                gh = Github(age=35)
                gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 1
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], expected)
                self.assertEqual(gh.calls.count(WRITE), int(expected == "DISPATCHED_OFFICIAL_CONTINUE"))

    def test_crossing_jst_midnight_before_dispatch_holds_the_shorter_decision(self):
        before_midnight = NOW + timedelta(hours=11, minutes=59)
        gh = Github(age=35, now=before_midnight)
        gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 1
        report = self.watchdog.supervise(
            gh, now=before_midnight, state_dir=self.state, dispatch=True,
            clock=lambda: before_midnight + timedelta(minutes=2),
        )
        self.assertEqual(report["decision"], "HOLD_CAPTURE_JST_DAY_CHANGED_NO_DISPATCH")
        self.assertFalse((self.state / "last-attempt.json").exists())
        self.assertNotIn(WRITE, gh.calls)

    def test_backlog_count_is_only_used_after_the_receipt_digest_matches(self):
        gh = Github(age=35)
        gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 1

        def wrong_zip(args):
            raw = gh(args)
            if args[-1].endswith("/zip"):
                return bytes([raw[0] ^ 1]) + raw[1:]
            return raw

        self.assertEqual(self.supervise(wrong_zip, dispatch=True)["decision"], "HOLD_CAPTURE_OUTCOME_UNVERIFIED")
        self.assertNotIn(WRITE, gh.calls)

    def test_backward_clock_prevents_backlog_dispatch(self):
        gh = Github(age=35)
        gh.receipt["statuses"]["SOURCE_CAPTURE_BUDGET_PENDING"] = 1
        report = self.watchdog.supervise(
            gh, now=NOW, state_dir=self.state, dispatch=True,
            clock=lambda: NOW - timedelta(seconds=1),
        )
        self.assertEqual(report["decision"], "HOLD_CAPTURE_CLOCK_CHANGED_NO_DISPATCH")
        self.assertFalse((self.state / "last-attempt.json").exists())
        self.assertNotIn(WRITE, gh.calls)

    def test_capture_continues_after_uniquely_failed_publication_with_independent_proof(self):
        for event, provider_work in (("workflow_dispatch", False), ("workflow_dispatch", True),
                                     ("schedule", False)):
            with self.subTest(event=event, provider_work=provider_work):
                gh = PublicationFailureGithub(event=event)
                if event == "schedule":
                    gh.settlement = None
                elif provider_work:
                    gh.settlement.update(source_requests=6, no_provider_tick=False, source_lease_finish_failed=False)
                report = self.supervise(gh)
                self.assertEqual(report["decision"], "WOULD_DISPATCH_OFFICIAL_CONTINUE")
                self.assertTrue(report.get("publication_only_failure_verified"))
                self.assertEqual(report.get("recovery_delay_minutes"), 20)
                self.assertNotIn(WRITE, gh.calls)

    def test_publication_failure_never_causes_an_extra_recent_capture(self):
        gh = PublicationFailureGithub(age=20)
        report = self.supervise(gh, dispatch=True)
        self.assertEqual(report["decision"], "SKIP_RECENT_OFFICIAL_SP_CAPTURE")
        self.assertTrue(report.get("publication_only_failure_verified"))
        self.assertFalse(self.state.exists())
        self.assertNotIn(WRITE, gh.calls)

    def test_verified_publication_failure_uses_the_existing_durable_attempt_guard(self):
        gh = PublicationFailureGithub()
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "DISPATCHED_OFFICIAL_CONTINUE")
        self.assertTrue((self.state / "last-attempt.json").is_file())
        self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_LOCAL_ATTEMPT_RECENT")
        self.assertEqual(gh.calls.count(WRITE), 1)

    def test_any_other_failure_or_wrong_attempt_keeps_the_existing_stop(self):
        for job, changes in (
                ("official-sp-capture", {"conclusion": "failure"}),
                ("official-sp-independent-readback", {"conclusion": "failure"}),
                ("official-sp-settle", {"conclusion": "failure"}),
                ("source-free-tests", {"conclusion": "cancelled"}),
                ("official-sp-independent-readback", {"run_attempt": 2}),
                ("official-sp-publish", {"run_id": 99}),
                ("official-sp-settle", {"conclusion": "skipped"}),
        ):
            with self.subTest(job=job, changes=changes):
                gh = PublicationFailureGithub()
                gh.job_changes[job] = changes
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], "HOLD_CAPTURE_JOB_FAILED")
                self.assertNotIn(WRITE, gh.calls)

    def test_missing_forged_and_mismatched_independent_artifacts_hold(self):
        for issue in ("missing", "zip", "count", "lineage", "race"):
            with self.subTest(issue=issue):
                gh = PublicationFailureGithub()
                if issue == "missing":
                    gh.readback = None
                elif issue == "zip":
                    gh.corrupt_zip.add(601)
                elif issue == "count":
                    gh.readback["independently_verified"] = 1
                elif issue == "lineage":
                    gh.artifact_changes["keirin-official-sp-readback-7"] = {"created_at": timestamp(80)}
                elif issue == "race":
                    gh.readback["records"][0]["cipher_sha256"] = "5"*64
                report = self.supervise(gh, dispatch=True)
                self.assertEqual(report["decision"], "HOLD_CAPTURE_OUTCOME_UNVERIFIED")
                self.assertNotIn(WRITE, gh.calls)

    def test_publication_failure_exception_requires_new_source_clean_originals(self):
        for field, value, expected in (
                ("new_A_B_git_archived", 0, "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                ("provider_denied", True, "HOLD_CAPTURE_PROVIDER_STOP"),
                ("source_lease_finish_failed", True, "HOLD_CAPTURE_STOPPING_STATE")):
            with self.subTest(field=field):
                gh = PublicationFailureGithub()
                gh.receipt[field] = value
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], expected)
                self.assertNotIn(WRITE, gh.calls)

    def test_manual_settlement_artifact_must_bind_a_clean_result(self):
        for issue, expected in (("missing", "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                                ("zip", "HOLD_CAPTURE_OUTCOME_UNVERIFIED"),
                                ("denied", "HOLD_CAPTURE_PROVIDER_STOP"),
                                ("stop", "HOLD_CAPTURE_PROVIDER_STOP"),
                                ("unavailable", "HOLD_CAPTURE_STOPPING_STATE"),
                                ("failed_lease", "HOLD_CAPTURE_STOPPING_STATE"),
                                ("unknown_lease", "HOLD_CAPTURE_STOPPING_STATE")):
            with self.subTest(issue=issue):
                gh = PublicationFailureGithub()
                if issue == "missing":
                    gh.settlement = None
                elif issue == "zip":
                    gh.corrupt_zip.add(602)
                elif issue == "denied":
                    gh.settlement["provider_denied"] = True
                elif issue == "stop":
                    gh.settlement["state"] = "HOLD_OFFICIAL_SP_PROVIDER_STOP"
                elif issue == "unavailable":
                    gh.settlement["source_unavailable"] = True
                elif issue == "failed_lease":
                    gh.settlement["source_lease_finish_failed"] = True
                elif issue == "unknown_lease":
                    gh.settlement.update(no_provider_tick=False, source_requests=4)
                self.assertEqual(self.supervise(gh, dispatch=True)["decision"], expected)
                self.assertNotIn(WRITE, gh.calls)
