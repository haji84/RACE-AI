"""Create-once capture selections across ephemeral GitHub runners.

Public records contain only race IDs, selection time and workflow identity.
A selection is not a GET attempt, successful normalization or forecast. The
existing state branch and owner opt-in are mandatory; no reset or force push.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re

from . import keirin_nationwide_cipher_history as archive

ROOT = "state/keirin/ab/capture-selections/v1"
SCHEMA = "RACE_AI_KEIRIN_CAPTURE_SELECTION_NOT_GET_EVIDENCE_V1"
JST = timezone(timedelta(hours=9))
MAX_EVENTS = 1000
MAX_EVENT_BYTES = 4096
MAX_RACES = 8


class CaptureSelectionError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise CaptureSelectionError(code)


def _day(day):
    _need(type(day) is str and re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day),
          "CAPTURE_SELECTION_DAY_INVALID")
    try:
        _need(date.fromisoformat(day).isoformat() == day, "CAPTURE_SELECTION_DAY_INVALID")
    except ValueError:
        raise CaptureSelectionError("CAPTURE_SELECTION_DAY_INVALID") from None
    return day


def _path(day, run_id, attempt):
    _day(day)
    _need(all(type(value) is str and archive.RUN.fullmatch(value)
              for value in (run_id, attempt)), "CAPTURE_SELECTION_RUN_IDENTITY_INVALID")
    return f"{ROOT}/{day}/{run_id}.{attempt}.json"


def _canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _check(doc, day):
    _need(type(doc) is dict and set(doc) == {
        "schema", "day_jst", "selected_at", "selected_race_ids",
        "producer_run_id", "producer_run_attempt"} and doc["schema"] == SCHEMA and
        doc["day_jst"] == day, "CAPTURE_SELECTION_METADATA_UNTRUSTED")
    _path(day, doc["producer_run_id"], doc["producer_run_attempt"])
    _need(type(doc["selected_at"]) is str, "CAPTURE_SELECTION_CLOCK_INVALID")
    try:
        at = datetime.fromisoformat(doc["selected_at"].replace("Z", "+00:00"))
        _need(at.utcoffset() is not None and at.astimezone(JST).date().isoformat() == day,
              "CAPTURE_SELECTION_CLOCK_INVALID")
    except ValueError:
        raise CaptureSelectionError("CAPTURE_SELECTION_CLOCK_INVALID") from None
    ids = doc["selected_race_ids"]
    _need(type(ids) is list and 1 <= len(ids) <= MAX_RACES and
          all(type(rid) is str and re.fullmatch(r"20[0-9]{10}", rid) and
              rid[:8] == day.replace("-", "") for rid in ids) and
          ids == sorted(set(ids)), "CAPTURE_SELECTION_RACE_IDS_INVALID")
    return doc


def _read_event(repo, head, path, day):
    raw = archive.read_blob_bytes(repo, head, path, max_bytes=MAX_EVENT_BYTES)
    _need(raw is not None, "CAPTURE_SELECTION_EVENT_MISSING")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError):
        raise CaptureSelectionError("CAPTURE_SELECTION_JSON_INVALID") from None
    _check(doc, day)
    _need(_path(day, doc["producer_run_id"], doc["producer_run_attempt"]) == path,
          "CAPTURE_SELECTION_PATH_IDENTITY_MISMATCH")
    _need(_canonical(doc) == raw, "CAPTURE_SELECTION_CANONICAL_BYTES_REQUIRED")
    return doc


def _events(repo, head, day):
    prefix = f"{ROOT}/{_day(day)}/"
    _, names = archive._cmd(repo, "--no-replace-objects", "ls-tree", "-r",
                            "--name-only", head, "--", prefix)
    paths = names.splitlines() if names else []
    _need(len(paths) <= MAX_EVENTS, "CAPTURE_SELECTION_DAY_EVENT_LIMIT_EXCEEDED")
    events = {}
    for path in paths:
        _need(path.startswith(prefix) and
              re.fullmatch(r"[1-9][0-9]{0,16}\.[1-9][0-9]{0,16}\.json", path[len(prefix):]),
              "CAPTURE_SELECTION_HISTORY_PATH_INVALID")
        events[path] = _read_event(repo, head, path, day)
    return events


def read_day(*, repo, day, synthetic_local=False):
    """Return validated selection counts, not claimed provider-attempt counts."""
    _day(day)
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    counts = {}
    for event in _events(repo, archive._refresh(repo), day).values():
        for rid in event["selected_race_ids"]:
            counts[rid] = counts.get(rid, 0) + 1
    return counts


def append_selected(*, repo, day, selected_race_ids, selected_at,
                    producer_run_id, producer_run_attempt, synthetic_local=False):
    """Record the bounded selection before GETs; never overwrite a run attempt."""
    _need(type(selected_race_ids) is list and
          all(type(rid) is str for rid in selected_race_ids),
          "CAPTURE_SELECTION_RACE_IDS_INVALID")
    doc = _check({"schema": SCHEMA, "day_jst": day, "selected_at": selected_at,
                  "selected_race_ids": sorted(selected_race_ids),
                  "producer_run_id": producer_run_id,
                  "producer_run_attempt": producer_run_attempt}, day)
    path = _path(day, producer_run_id, producer_run_attempt)
    payload = _canonical(doc)
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    for _ in range(3):
        head = archive._refresh(repo)
        events = _events(repo, head, day)
        if path in events:
            _need(events[path]["selected_race_ids"] == doc["selected_race_ids"],
                  "CAPTURE_RUN_ATTEMPT_ALREADY_HAS_DIFFERENT_SELECTION")
            return {"state": "CAPTURE_SELECTION_ALREADY_RECORDED_NOT_NEW_GET",
                    "selected_races": len(selected_race_ids)}
        _need(len(events) < MAX_EVENTS, "CAPTURE_SELECTION_DAY_EVENT_LIMIT_EXCEEDED")
        with TemporaryDirectory(prefix="keirin-capture-selection-") as temporary:
            tree = Path(temporary) / "tree"
            archive._cmd(repo, "worktree", "add", "--detach", str(tree), head)
            try:
                parent = tree
                for part in path.split("/")[:-1]:
                    parent = parent / part
                    _need(not parent.is_symlink(), "CAPTURE_SELECTION_SYMLINK_REJECTED")
                    parent.mkdir(exist_ok=True)
                target = tree / path
                with target.open("xb") as handle:
                    handle.write(payload)
                archive._cmd(tree, "add", "--", path)
                archive._cmd(tree, "-c", "user.name=RACE-AI", "-c",
                             "user.email=race-ai@users.noreply.github.com",
                             "commit", "-m", "intake(keirin): record selected race IDs before GET")
                newhead = archive._cmd(tree, "rev-parse", "HEAD")[1]
                status, _ = archive._cmd(tree, "push", "origin",
                                        f"HEAD:refs/heads/{archive.BRANCH}", okay=True)
            finally:
                archive._cmd(repo, "worktree", "remove", "--force", str(tree), okay=True)
        if status == 0:
            observed = archive._refresh(repo)
            _need(_read_event(repo, observed, path, day) == doc,
                  "CAPTURE_SELECTION_EXACT_READBACK_FAILED")
            ancestor, _ = archive._cmd(repo, "--no-replace-objects", "merge-base",
                                       "--is-ancestor", newhead, observed, okay=True)
            _need(ancestor == 0, "CAPTURE_SELECTION_NEW_COMMIT_NOT_IN_READBACK_HISTORY")
            return {"state": "CAPTURE_SELECTION_RECORDED_NOT_GET_EVIDENCE",
                    "selected_races": len(selected_race_ids)}
    raise CaptureSelectionError("CAPTURE_SELECTION_CONCURRENT_GIT_RETRY_EXHAUSTED")
