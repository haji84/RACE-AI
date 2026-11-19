"""Explicit trusted-main replay of saved evidence; no provider or state writes.

This deliberately does not call settle-days --saved-only: that live runner
may acquire missing GitHub bundles and persist new settlement/progress state.
Only one fetched immutable commit and already saved bundles are used here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import argparse
import json
import os
import re
import subprocess

SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_SAVED_ONLY_CHECK_V1"
READY = "SAVED_ONLY_REPLAYED_LIVE_ACCEPTANCE_PENDING"
PRIVATE_KEY_ENV = "RACE_AI_KEIRIN_PRIVATE_RSA_PEM"
STATE_REF = "refs/heads/state/keirin-encrypted-history"


class SavedCheckHold(ValueError):
    pass


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Unknown arguments may be an accidentally pasted private value.
        raise SavedCheckHold("HOLD_SAVED_ONLY_ARGUMENTS_INVALID")


def need(ok, code):
    if not ok:
        raise SavedCheckHold(code)


def _git(repo, *args):
    env = {key: value for key, value in os.environ.items() if key != PRIVATE_KEY_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run(["git", *args], cwd=repo, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=35, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SavedCheckHold("HOLD_SAVED_STATE_NOT_READABLE") from None
    return done.returncode, done.stdout.strip()


def _checked_context():
    values = os.environ
    need(values.get("GITHUB_ACTIONS") == "true"
         and values.get("GITHUB_REPOSITORY") == "haji84/RACE-AI"
         and values.get("GITHUB_REPOSITORY_ID") == "1416489937"
         and values.get("GITHUB_REF") == "refs/heads/main"
         and values.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
         and values.get("RACE_AI_KEIRIN_SAVED_CHECK_MODE") == "saved-only"
         and re.fullmatch(r"[1-9][0-9]{0,16}", values.get("GITHUB_RUN_ID", ""))
         and re.fullmatch(r"[1-9][0-9]{0,8}", values.get("GITHUB_RUN_ATTEMPT", ""))
         and re.fullmatch(r"[0-9a-f]{40}", values.get("GITHUB_SHA", ""))
         and values["GITHUB_SHA"] != "0" * 40, "HOLD_UNTRUSTED_SAVED_ONLY_CONTEXT")


def _snapshot(repo):
    need(repo.is_absolute() and repo.is_dir() and not repo.is_symlink()
         and (repo / ".git").exists(), "HOLD_GIT_CHECKOUT_REQUIRED")
    status, origin = _git(repo, "remote", "get-url", "--all", "origin")
    need(status == 0 and origin in (
        "https://github.com/haji84/RACE-AI", "https://github.com/haji84/RACE-AI.git",
        "git@github.com:haji84/RACE-AI", "git@github.com:haji84/RACE-AI.git"),
        "HOLD_UNEXPECTED_GIT_REMOTE")
    status, commit = _git(repo, "rev-parse", "HEAD")
    need(status == 0 and commit == os.environ["GITHUB_SHA"], "HOLD_CHECKOUT_COMMIT_MISMATCH")
    status, reference = _git(repo, "ls-remote", "--exit-code", "--refs", "origin", STATE_REF)
    need(status != 2, "HOLD_EXISTING_STATE_BRANCH_NOT_FOUND")
    need(status == 0, "HOLD_SAVED_STATE_NOT_READABLE")
    need(re.fullmatch(r"[0-9a-f]{40}\t" + re.escape(STATE_REF), reference),
         "HOLD_STATE_BRANCH_RESPONSE_INVALID")
    head = reference.split("\t", 1)[0]
    # Fetch the observed object, without updating even a local tracking ref.
    status, _ = _git(repo, "fetch", "--no-tags", "--no-write-fetch-head", "origin", head)
    need(status == 0, "HOLD_SAVED_STATE_NOT_READABLE")
    status, kind = _git(repo, "--no-replace-objects", "cat-file", "-t", head)
    need(status == 0 and kind == "commit", "HOLD_SAVED_STATE_COMMIT_INVALID")
    return head


def _days(repo, head):
    from race_ai import keirin_nationwide_cipher_history as archive
    from race_ai import keirin_official_run_history as history
    found = set()
    for root in (archive.ROOT, history.ROOT):
        prefix = root + "/"
        status, paths = _git(repo, "--no-replace-objects", "ls-tree", "-d", "--name-only",
                             head, "--", prefix)
        need(status == 0, "HOLD_SAVED_STATE_NOT_READABLE")
        for path in paths.splitlines():
            need(path.startswith(prefix), "HOLD_SAVED_DAY_PATH_INVALID")
            day = path[len(prefix):]
            need(re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day)
                 and date.fromisoformat(day).isoformat() == day, "HOLD_SAVED_DAY_PATH_INVALID")
            found.add(day)
    return sorted(found)


def _pairs(repo, head, prefix, identifier, *, count_limit, cipher_limit, byte_limit):
    """Check complete pairs, modes and total size before decrypting any blob."""
    status, tree = _git(repo, "--no-replace-objects", "ls-tree", "-r", "-l", head, "--", prefix)
    need(status == 0, "HOLD_SAVED_STATE_NOT_READABLE")
    pairs, total = {}, 0
    for line in tree.splitlines():
        metadata, path = line.split("\t", 1)
        mode, kind, digest, size = metadata.split()
        need(mode == "100644" and kind == "blob" and path.startswith(prefix)
             and size.isascii() and size.isdecimal(), "HOLD_SAVED_ARCHIVE_TREE_INVALID")
        match = re.fullmatch(identifier + r"\.(sealed|receipt)\.json", path[len(prefix):])
        need(match is not None, "HOLD_SAVED_ARCHIVE_TREE_INVALID")
        identity, label = match.groups()
        limit = cipher_limit if label == "sealed" else 16384
        need(0 < int(size) < limit, "HOLD_SAVED_ARCHIVE_READ_LIMIT_EXCEEDED")
        total += int(size)
        need(total <= byte_limit, "HOLD_SAVED_ARCHIVE_READ_LIMIT_EXCEEDED")
        pairs.setdefault(identity, set()).add(label)
        need(len(pairs) <= count_limit, "HOLD_SAVED_ARCHIVE_READ_LIMIT_EXCEEDED")
    need(all(labels == {"sealed", "receipt"} for labels in pairs.values()),
         "HOLD_SAVED_ARCHIVE_PAIR_INCOMPLETE")
    return sorted(pairs)


def _saved_day(repo, head, day, owner_private_pem):
    from race_ai import keirin_nationwide_cipher_history as archive
    from race_ai import keirin_official_run_history as history
    from scripts import keirin_official_day_pipeline as pipeline
    digests = _pairs(repo, head, f"{history.ROOT}/{day}/", r"([0-9a-f]{64})",
        count_limit=history.MAX_DAY_REVISIONS, cipher_limit=history.MAX_CIPHER_BYTES,
        byte_limit=history.DEFAULT_DAY_READ_BYTES)
    revisions = [history._read_at(repo, head, day, digest) for digest in digests]
    revisions.sort(key=lambda row: (history._when(row["receipt"]["observed_at"]),
                                    row["receipt"]["evidence_plaintext_sha256"]))
    saved = pipeline.replay_day_evidence(day, owner_private_pem, revisions)
    need(saved["schedule"] is not None, "HOLD_OFFICIAL_SCHEDULE_NOT_AVAILABLE")
    ids = _pairs(repo, head, f"{archive.ROOT}/{day}/", r"(20[0-9]{10})",
        count_limit=1000, cipher_limit=archive.MAX_BYTES,
        byte_limit=history.DEFAULT_DAY_READ_BYTES)
    originals = {}
    for rid in ids:
        need(rid[:8] == day.replace("-", ""), "HOLD_SAVED_ORIGINAL_DAY_INVALID")
        cipher_path, receipt_path = archive._refs(rid)
        receipt = json.loads(archive.read_blob_bytes(repo, head, receipt_path, max_bytes=16384))
        checked = archive._read_at(repo, head, rid, receipt["cipher_sha256"])
        originals[rid] = {key: checked[key] for key in (
            "cipher_sha256", "producer_run_id", "producer_commit")}
        originals[rid]["raw_cipher"] = archive.read_blob_bytes(repo, head, cipher_path)
    packets = {rid: saved["origin_run_bundles"][item["producer_run_id"]]
               for rid, item in originals.items()
               if item["producer_run_id"] in saved["origin_run_bundles"]}
    report, rows, _ = pipeline.settle_collected(schedule=saved["schedule"],
        originals_by_race=originals, official_records_by_race=saved["official_records"],
        origin_packets_by_race=packets, owner_private_pem=owner_private_pem,
        schedule_versions=saved["schedule_versions"])
    accepted = {"AB_SETTLED_FROM_INDEPENDENT_RECEIPTS", "CANCELLED_FULL_REFUND_NO_MODEL_SCORE"}
    complete = (saved["cohort_state"] is None and
        len(originals) == report["originals_server_verified_before_cutoff"] ==
        len(report["statuses"]) == report["registered_races"] and
        report["paired_A_B_scored"] + report["confirmed_cancelled_full_refund_races"] ==
        report["registered_races"] and all(row["state"] in accepted for row in report["statuses"]))
    report["state"] = READY if complete else "HOLD_SAVED_EVIDENCE_INCOMPLETE"
    return report, rows


def _write(path, data):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _replay(repo, root, owner_private_pem, report, clock):
    _checked_context()
    from cryptography.exceptions import UnsupportedAlgorithm
    from scripts import keirin_official_day_pipeline as pipeline
    from scripts import keirin_official_backlog_days as backlog
    from race_ai import keirin_official_run_history as history
    try:
        public = pipeline.check_owner_private_key(owner_private_pem)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        fixed = {"EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED",
                 "EXISTING_OWNER_PRIVATE_SECRET_INVALID", "EXISTING_OWNER_RSA_PRIVATE_SECRET_REQUIRED",
                 "OWNER_PUBLIC_SPKI_PIN_MISMATCH"}
        raise SavedCheckHold("HOLD_" + str(exc) if str(exc) in fixed else
                             "HOLD_OWNER_PRIVATE_KEY_NOT_VERIFIED") from None
    head = _snapshot(repo)
    report.update(observed_state_commit=head, source_commit=os.environ["GITHUB_SHA"],
                  run_id=os.environ["GITHUB_RUN_ID"])
    known = _days(repo, head)
    need(bool(known), "HOLD_NO_SAVED_OFFICIAL_DAYS")
    # Reuse the bounded backlog rotation, but never manufacture an unsaved day.
    days = [day for day in backlog.select_days(clock(), known) if day in known]
    need(bool(days), "HOLD_NO_SAVED_OFFICIAL_DAYS")
    report["days_selected"] = days
    for day in days:
        day_root = root / day
        day_root.mkdir(mode=0o700)
        try:
            safe, rows = _saved_day(repo, head, day, owner_private_pem)
            sealed = history.seal_evidence({
                "schema": "RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DAY_V1", "day_jst": day,
                "safe_report": safe, "owner_rows": rows}, public, day,
                clock().astimezone(timezone.utc).isoformat())
            _write(day_root / "owner-view.sealed.json", sealed)
        except SavedCheckHold as exc:
            safe = {"schema": SCHEMA, "day_jst": day, "state": str(exc)}
        except (ValueError, TypeError, KeyError, OSError, RuntimeError):
            safe = {"schema": SCHEMA, "day_jst": day,
                    "state": "HOLD_SAVED_EVIDENCE_INVALID_OR_UNAVAILABLE"}
        _write(day_root / "safe.json", _json(safe))
        report["days_held" if safe["state"].startswith("HOLD_") else "days_completed"] += 1
        report["day_reports"].append({key: safe[key] for key in (
            "day_jst", "state", "registered_races", "paired_A_B_scored",
            "originals_server_verified_before_cutoff") if key in safe})
    report["state"] = "HOLD_SAVED_EVIDENCE_INCOMPLETE" if report["days_held"] else READY


def main(argv=None, *, clock=None):
    parser = _SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--private-root", required=True)
    # Git's existing low-level blob readers inherit the process environment.
    # Remove the key before any subprocess; it is never written to disk.
    key = os.environ.pop(PRIVATE_KEY_ENV, "").encode("utf-8")
    report = {"schema": SCHEMA, "provider_requests": 0, "state_writes": 0,
              "live_acceptance_completed": False, "days_completed": 0,
              "days_held": 0, "days_selected": [], "day_reports": []}
    root = None
    try:
        args = parser.parse_args(argv)
        repo, candidate = Path(args.repo), Path(args.private_root)
        need(candidate.is_absolute() and candidate.parent.is_dir() and
             candidate.resolve() == candidate and not candidate.exists() and
             not candidate.is_symlink() and repo.resolve() not in (candidate, *candidate.parents),
             "HOLD_NEW_PRIVATE_OUTPUT_DIRECTORY_REQUIRED")
        candidate.mkdir(mode=0o700)
        root = candidate
        _replay(repo, root, key, report, clock or (lambda: datetime.now(timezone.utc)))
    except SavedCheckHold as exc:
        report["state"] = str(exc)
    except ImportError:
        report["state"] = "HOLD_SAVED_ONLY_DEPENDENCY_UNAVAILABLE"
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        report["state"] = "HOLD_SAVED_EVIDENCE_INVALID_OR_UNAVAILABLE"
    if root is not None:
        try:
            _write(root / "batch-safe.json", _json(report))
        except (ValueError, OSError):
            report["state"] = "HOLD_SAVED_ONLY_SAFE_REPORT_NOT_WRITTEN"
    print(_json(report).decode("utf-8"), end="")
    return 0 if report["state"] == READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
