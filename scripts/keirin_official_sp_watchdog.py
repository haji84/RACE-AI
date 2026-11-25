"""Check the existing GitHub official SP schedule and optionally dispatch its fallback."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile
import zlib


REPO = "haji84/RACE-AI"
REPO_ID = 1416489937
REPO_API = f"repos/{REPO}"
MAIN_API = f"{REPO_API}/branches/main"
WORKFLOW = "keirin-nationwide-ab-auto.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW}"
WORKFLOW_API = f"{REPO_API}/actions/workflows/{WORKFLOW}"
ACTIVE = ("in_progress", "queued", "requested", "pending", "waiting")
TRUSTED_EVENTS = ("schedule", "workflow_dispatch")
CAPTURE_JOB = "official-sp-capture"
CAPTURE_STEP = "Register the official day and preserve future original forecasts"
CAPTURE_SCHEMA = "RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1"
SAFE_CAPTURE_STATES = ("OFFICIAL_SP_BASELINES_ARCHIVED", "OFFICIAL_SP_DAY_REGISTERED_WITH_EXPLICIT_HOLDS")
SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_SP_WATCHDOG_V1"
RECENT = timedelta(minutes=45)
CLOCK_SKEW = timedelta(minutes=3)
METADATA_HOLD = "HOLD_INVALID_GITHUB_METADATA"
OUTCOME_HOLD = "HOLD_CAPTURE_OUTCOME_UNVERIFIED"
LOCAL_HOLD = "HOLD_UNSAFE_LOCAL_RECEIPT"
ARTIFACT_LIMIT = 64 * 1024
RUNS_LIMIT = 100
JOB_LOOKUP_LIMIT = 12


class Hold(ValueError):
    """Carry only a fixed reason code to the status report."""


def require(condition, reason):
    if not condition:
        raise Hold(reason)


def call_gh(args):
    environment = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1",
                       GH_NO_EXTENSION_UPDATE_NOTIFIER="1")
    result = subprocess.run(
        ["gh", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=environment, timeout=15, check=False,
    )
    require(result.returncode == 0, "HOLD_GITHUB_REQUEST_FAILED")
    return result.stdout


def api(gh, path):
    return gh(("api", "--hostname", "github.com", path))


def decode(data, limit, reason):
    require(type(data) is bytes and len(data) <= limit, reason)
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeError):
        raise Hold(reason) from None
    require(type(obj) is dict, reason)
    return obj


def metadata(gh, path):
    return decode(api(gh, path), 2_000_000, METADATA_HOLD)


def utc(value, now, reason=METADATA_HOLD):
    require(isinstance(value, str), reason)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(timestamp.tzinfo is not None, reason)
        timestamp = timestamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise Hold(reason) from None
    require(timestamp <= now + CLOCK_SKEW, reason)
    return timestamp


def sha(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{40}", value) is not None


def positive_id(value):
    return type(value) is int and 0 < value < 10**18


def main_head(gh):
    branch = metadata(gh, MAIN_API)
    commit = branch.get("commit")
    require(branch.get("name") == "main" and branch.get("protected") is True
            and isinstance(commit, dict) and sha(commit.get("sha")), "HOLD_MAIN_BRANCH_METADATA")
    return commit["sha"]


def active_workflow(gh):
    workflow = metadata(gh, WORKFLOW_API)
    require(workflow.get("state") == "active" and workflow.get("path") == WORKFLOW_PATH
            and positive_id(workflow.get("id")), "HOLD_WORKFLOW_METADATA")
    return workflow["id"]


def listing(obj, key, limit, reason):
    items, count = obj.get(key), obj.get("total_count")
    require(type(items) is list and type(count) is int and
            len(items) == min(limit, count)
            and all(isinstance(item, dict) for item in items), reason)
    return items, count


def validate_run(run, workflow_id):
    repository, head_repository = run.get("repository"), run.get("head_repository")
    require(run.get("head_branch") == "main" and run.get("path") == WORKFLOW_PATH
            and run.get("workflow_id") == workflow_id and positive_id(run.get("id"))
            and positive_id(run.get("run_attempt")) and sha(run.get("head_sha"))
            and isinstance(repository, dict) and repository.get("id") == REPO_ID
            and isinstance(head_repository, dict) and head_repository.get("id") == REPO_ID,
            METADATA_HOLD)


def require_idle(gh, workflow_id):
    for status in ACTIVE:
        path = f"{WORKFLOW_API}/runs?branch=main&status={status}&per_page=1"
        rows, count = listing(metadata(gh, path), "workflow_runs", 1, METADATA_HOLD)
        if count:
            validate_run(rows[0], workflow_id)
            # A transition between queue states during the query is ambiguous too.
            raise Hold("HOLD_ACTIVE_OFFICIAL_SP_WORKFLOW")


def capture_times(gh, run, now, created, updated):
    path = f"{REPO_API}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
    jobs, total = listing(metadata(gh, path), "jobs", 100, METADATA_HOLD)
    captures = [job for job in jobs if job.get("name") == CAPTURE_JOB]
    require(total == len(jobs) and len(captures) == 1, OUTCOME_HOLD)
    capture = captures[0]
    require(capture.get("run_id") == run["id"] and capture.get("run_attempt") == run["run_attempt"]
            and capture.get("head_sha") == run["head_sha"] and capture.get("status") == "completed",
            OUTCOME_HOLD)
    require(run.get("conclusion") in ("success", "skipped") and
            capture.get("conclusion") in ("success", "skipped"), "HOLD_CAPTURE_JOB_FAILED")
    if capture["conclusion"] == "skipped":
        return None
    steps = capture.get("steps")
    require(type(steps) is list and len(steps) <= 50 and all(isinstance(row, dict) for row in steps),
            OUTCOME_HOLD)
    step = [row for row in steps if row.get("name") == CAPTURE_STEP]
    require(len(step) == 1 and step[0].get("status") == "completed"
            and step[0].get("conclusion") == "success", OUTCOME_HOLD)
    started = utc(step[0].get("started_at"), now, OUTCOME_HOLD)
    finished = utc(step[0].get("completed_at"), now, OUTCOME_HOLD)
    require(created <= started <= finished <= updated, OUTCOME_HOLD)
    return started, finished


def latest_capture(gh, workflow_id, now):
    path = f"{WORKFLOW_API}/runs?branch=main&per_page={RUNS_LIMIT}"
    rows, total = listing(metadata(gh, path), "workflow_runs", RUNS_LIMIT, METADATA_HOLD)
    trusted, dates, seen = [], [], set()
    for run in rows:
        validate_run(run, workflow_id)
        require(run["id"] not in seen, METADATA_HOLD)
        seen.add(run["id"])
        created = utc(run.get("created_at"), now)
        dates.append(created)
        if run.get("status") in ACTIVE:
            raise Hold("HOLD_ACTIVE_OFFICIAL_SP_WORKFLOW")
        require(run.get("status") == "completed", METADATA_HOLD)
        if run.get("event") in TRUSTED_EVENTS:
            updated = utc(run.get("updated_at"), now)
            require(created <= updated, METADATA_HOLD)
            trusted.append((updated, created, run))
    if total > len(rows):
        # The protected source lease allows a capture on its first attempt only.
        require(min(dates) <= now - RECENT, "HOLD_INCOMPLETE_RECENT_HISTORY")

    latest = None
    trusted.sort(key=lambda row: (row[0], row[2]["id"]), reverse=True)
    for number, (updated, created, run) in enumerate(trusted):
        if latest and updated < latest[2]:
            break
        require(number < JOB_LOOKUP_LIMIT, "HOLD_CAPTURE_LOOKUP_LIMIT")
        times = capture_times(gh, run, now, created, updated)
        if times and (latest is None or times[1] > latest[2]):
            latest = run, *times
    require(latest is not None, "HOLD_NO_VERIFIED_CAPTURE_HISTORY")
    return latest


def require_safe_capture(gh, run, finished, now):
    receipt_name = f"keirin-official-sp-receipt-{run['id']}"
    path = f"{REPO_API}/actions/runs/{run['id']}/artifacts?name={receipt_name}&per_page=1"
    receipts, total = listing(metadata(gh, path), "artifacts", 1, OUTCOME_HOLD)
    require(total == 1, OUTCOME_HOLD)
    receipt = receipts[0]
    source = receipt.get("workflow_run")
    size = receipt.get("size_in_bytes")
    require(receipt.get("name") == receipt_name and receipt.get("expired") is False
            and positive_id(receipt.get("id")) and type(size) is int and 0 < size <= ARTIFACT_LIMIT
            and isinstance(source, dict) and source.get("id") == run["id"]
            and source.get("head_branch") == "main" and source.get("head_sha") == run["head_sha"]
            and source.get("head_repository_id") == source.get("repository_id") == REPO_ID
            and finished <= utc(receipt.get("created_at"), now, OUTCOME_HOLD), OUTCOME_HOLD)
    raw = api(gh, f"{REPO_API}/actions/artifacts/{receipt['id']}/zip")
    require(type(raw) is bytes and len(raw) == size and
            receipt.get("digest") == "sha256:" + sha256(raw).hexdigest(), OUTCOME_HOLD)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1 and entries[0].filename == "summary.json"
                    and entries[0].file_size <= ARTIFACT_LIMIT, OUTCOME_HOLD)
            summary = decode(archive.read(entries[0]), ARTIFACT_LIMIT, OUTCOME_HOLD)
    except (zipfile.BadZipFile, RuntimeError, OSError, zlib.error):
        raise Hold(OUTCOME_HOLD) from None
    require(summary.get("schema") == CAPTURE_SCHEMA and type(summary.get("provider_denied")) is bool
            and summary.get("source_or_forecast_plaintext_exposed") is False, OUTCOME_HOLD)
    require(summary["provider_denied"] is False, "HOLD_CAPTURE_PROVIDER_STOP")
    statuses = summary.get("statuses")
    require(type(statuses) is dict and all(type(count) is int and count >= 0 for count in statuses.values()),
            OUTCOME_HOLD)
    require(not statuses.get("PROVIDER_STOPPED"), "HOLD_CAPTURE_PROVIDER_STOP")
    require(summary.get("state") in SAFE_CAPTURE_STATES and not statuses.get("SOURCE_UNAVAILABLE")
            and summary.get("source_lease_finish_failed", False) is False, "HOLD_CAPTURE_STOPPING_STATE")
    requests = summary.get("source_requests")
    require(type(requests) is int and 0 < requests <= 300, OUTCOME_HOLD)


def require_private(info, mode, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    require(kind(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == mode and (directory or info.st_nlink == 1), LOCAL_HOLD)


@contextmanager
def attempt_lock(folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require_private(os.fstat(directory), 0o700, directory=True)
        lock = os.open("dispatch.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory)
        try:
            require_private(os.fstat(lock), 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Hold("HOLD_LOCAL_WATCHDOG_ACTIVE") from None
            yield directory
        finally:
            os.close(lock)
    finally:
        os.close(directory)


def require_local_clear(directory, now, last_capture_started):
    try:
        descriptor = os.open("last-attempt.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
    except FileNotFoundError:
        return
    with os.fdopen(descriptor, "rb") as receipt:
        require_private(os.fstat(receipt.fileno()), 0o600)
        attempt = decode(receipt.read(1025), 1024, LOCAL_HOLD)
    require(set(attempt) == {"at", "status"} and attempt["status"] in ("unconfirmed", "accepted"), LOCAL_HOLD)
    attempted = utc(attempt["at"], now, LOCAL_HOLD)
    require(attempt["status"] != "unconfirmed" or last_capture_started > attempted,
            "HOLD_PRIOR_DISPATCH_UNCONFIRMED")
    require(now - attempted > RECENT, "HOLD_LOCAL_ATTEMPT_RECENT")
    require(last_capture_started > attempted, "HOLD_PRIOR_DISPATCH_OUTCOME_UNVERIFIED")


def save_attempt(folder, directory, now, status):
    temporary = tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=".attempt-", delete=False)
    try:
        with temporary:
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write(json.dumps({"at": now.isoformat(), "status": status}).encode() + b"\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(Path(temporary.name).name, "last-attempt.json", src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        Path(temporary.name).unlink(missing_ok=True)


def supervised_dispatch(gh, report, state_dir, now, capture, workflow_id, head):
    try:
        with attempt_lock(state_dir) as directory:
            require_local_clear(directory, now, capture[1])
            require(active_workflow(gh) == workflow_id, "HOLD_WORKFLOW_METADATA")
            require(latest_capture(gh, workflow_id, now) == capture, "HOLD_CAPTURE_HISTORY_MOVED_NO_DISPATCH")
            require_idle(gh, workflow_id)
            require(main_head(gh) == head, "HOLD_MAIN_MOVED_NO_DISPATCH")
            save_attempt(state_dir, directory, now, "unconfirmed")
            report["dispatch_attempted"] = True
            try:
                gh(("workflow", "run", WORKFLOW, "--repo", f"github.com/{REPO}", "--ref", "main",
                    "-f", "mode=official-continue"))
                save_attempt(state_dir, directory, now, "accepted")
            except (OSError, subprocess.SubprocessError, Hold):
                raise Hold("HOLD_DISPATCH_UNCONFIRMED") from None
    except OSError:
        raise Hold(LOCAL_HOLD) from None
    return "DISPATCHED_OFFICIAL_CONTINUE"


def supervise(gh, *, now, dispatch=False, state_dir=None):
    report = {"schema": SCHEMA, "dispatch_attempted": False}
    try:
        repo = metadata(gh, REPO_API)
        require(repo.get("id") == REPO_ID and repo.get("full_name") == REPO
                and repo.get("default_branch") == "main" and repo.get("archived") is False
                and repo.get("disabled") is False, "HOLD_REPOSITORY_IDENTITY")
        head = main_head(gh)
        report["main_sha"] = head
        workflow_id = active_workflow(gh)
        require_idle(gh, workflow_id)
        capture = latest_capture(gh, workflow_id, now)
        run, _, finished = capture
        report.update(last_actual_capture_run_id=run["id"], last_actual_capture_at=finished.isoformat())
        require_safe_capture(gh, run, finished, now)
        if now - finished <= RECENT:
            decision = "SKIP_RECENT_OFFICIAL_SP_CAPTURE"
        elif not dispatch:
            decision = "WOULD_DISPATCH_OFFICIAL_CONTINUE"
        else:
            if state_dir is None:
                state_dir = Path.home() / "Library/Application Support/RACE-AI/keirin-production-watch/state"
            decision = supervised_dispatch(gh, report, state_dir, now, capture, workflow_id, head)
    except Hold as exc:
        decision = str(exc)
    except (OSError, subprocess.SubprocessError):
        decision = "HOLD_GITHUB_REQUEST_FAILED"
    report["decision"] = decision
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--dispatch", action="store_true",
                        help="Allow the existing official-continue dispatch when all checks pass")
    args = parser.parse_args(argv)
    report = supervise(call_gh, now=datetime.now(timezone.utc), dispatch=args.dispatch)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
