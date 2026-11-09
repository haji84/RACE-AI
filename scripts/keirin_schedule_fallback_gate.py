#!/usr/bin/env python3
"""GitHub-only backup capture gate; never opens a race page or uses S3.

Only an actual recent scheduled run of the primary main workflow suppresses
backup capture. An API error is an explicit HOLD, not a claim of success.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path


WORKFLOW = ".github/workflows/keirin-github-autonomous.yml"
_RECENT = timedelta(minutes=75)
_ACTIVE = timedelta(hours=3)
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def decide_fallback(payload, *, now=None):
    """Return (launch, reason) from a trusted GitHub Actions runs response."""
    if not isinstance(payload, dict) or not isinstance(
            payload.get("workflow_runs"), list):
        raise ValueError("INVALID_PRIMARY_RUNS_RESPONSE")
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("UTC_CLOCK_REQUIRED")
    now = now.astimezone(timezone.utc)
    for run in payload["workflow_runs"]:
        if not isinstance(run, dict):
            raise ValueError("INVALID_PRIMARY_RUN_ROW")
        if not (run.get("path") == WORKFLOW
                and run.get("head_branch") == "main"
                and run.get("event") == "schedule"):
            continue
        when = run.get("created_at")
        if not isinstance(when, str):
            raise ValueError("PRIMARY_SCHEDULE_TIMESTAMP_MISSING")
        try:
            moment = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("PRIMARY_SCHEDULE_TIMESTAMP_INVALID") from exc
        if moment.utcoffset() is None:
            raise ValueError("PRIMARY_SCHEDULE_TIMESTAMP_NAIVE")
        age = now - moment.astimezone(timezone.utc)
        if age < timedelta(minutes=-5):
            raise ValueError("PRIMARY_SCHEDULE_CLOCK_IN_FUTURE")
        if age < timedelta(0):
            age = timedelta(0)
        if run.get("status") in ("queued", "in_progress", "waiting",
                                 "pending", "requested") and age <= _ACTIVE:
            return False, "MAIN_SCHEDULE_ACTIVE"
        if age <= _RECENT:
            return False, "MAIN_SCHEDULE_RECENT"
    return True, "NO_RECENT_MAIN_SCHEDULE"


def main():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not _REPO.fullmatch(repo):
        raise SystemExit("INVALID_GITHUB_REPOSITORY")
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("GH_TOKEN_REQUIRED")
    # Real scheduled evidence only, not the green PR/push unit tests.
    route = f"/repos/{repo}/actions/workflows/keirin-github-autonomous.yml/runs"
    route += "?event=schedule&branch=main&per_page=30"
    response = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", route],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    if response.returncode:
        raise SystemExit("MAIN_SCHEDULE_RUN_LIST_UNAVAILABLE")
    try:
        payload = json.loads(response.stdout)
        launch, reason = decide_fallback(payload)
    except (ValueError, TypeError) as exc:
        raise SystemExit("MAIN_SCHEDULE_RUN_LIST_NOT_TRUSTED") from exc
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        raise SystemExit("GITHUB_OUTPUT_NOT_AVAILABLE")
    with Path(output).open("a", encoding="utf-8") as f:
        f.write("should_capture=" + ("true" if launch else "false") + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as f:
            f.write("Backup recorder admission: " + reason + "\n")
    print(json.dumps({
        "backup_capture_admitted": launch,
        "reason": reason,
        "permanent_storage_verified": False,
        "recorded_video_verified": False,
    }))


if __name__ == "__main__":
    main()
