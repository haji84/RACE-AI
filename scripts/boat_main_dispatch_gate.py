"""Source-free, fail-closed main-to-existing-BOAT-owner dispatch decision.

No new model, result parser, scorer, ticket, source fetch, AES writer or
external scheduler. A release-gate and real existing runner evidence must be
verified before the *original* production workflow is dispatched.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

SCHEMA = "RACE_AI_BOAT_MAIN_OWNER_DISPATCH_GATE_V1"
REPO = "haji84/RACE-AI"
WORKFLOW = "BOAT nationwide cutoff-ordered A/B research (no Vercel)"
RELEASE_REF = "production/boat-p0-p1-20261111"
RELEASE_SHA = "fb3b89d49db815c9e88daa09c1303c7a6dd87d83"
RELEASE_TOKEN = "RACE_AI_SOURCE_OWNER_BOUNDARY_RELEASED_V1"
MAX_JSON_BYTES = 1024 * 1024  # owner status text is about 287 KiB before base64


def _load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_JSON_BYTES:
        raise ValueError("BOAT_DISPATCH_INPUT_INVALID")
    result = json.loads(path.read_text(encoding="utf8"))
    if type(result) is not dict:
        raise ValueError("BOAT_DISPATCH_JSON_OBJECT_REQUIRED")
    return result


def _stamp(value: str) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise ValueError("BOAT_DISPATCH_TIMESTAMP_INVALID")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("BOAT_DISPATCH_TIMESTAMP_AWARE_REQUIRED")
    return dt.astimezone(timezone.utc)


def decide(*, now: datetime, release: dict, owner_doc: dict, history: dict) -> dict:
    """Positive proof required. Missing/partial GitHub responses never mean GO."""
    if now.utcoffset() is None:
        raise ValueError("BOAT_DISPATCH_CLOCK_AWARE_REQUIRED")
    now = now.astimezone(timezone.utc)
    status = "HOLD_RELEASE_OR_SOURCE_UNVERIFIED"
    if (release.get("ref") != "refs/heads/" + RELEASE_REF
            or (release.get("object") or {}).get("sha") != RELEASE_SHA):
        status = "HOLD_RELEASE_SHA_MISMATCH"
    else:
        text = None
        try:
            if owner_doc.get("encoding") == "base64" and type(owner_doc.get("content")) is str:
                raw = base64.b64decode(owner_doc["content"], validate=False)
                if 0 < len(raw) <= MAX_JSON_BYTES:
                    text = raw.decode("utf8")
        except (ValueError, UnicodeDecodeError):
            text = None
        if text is None:
            status = "HOLD_SOURCE_OWNER_DOCUMENT_UNAVAILABLE"
        elif ("ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY" in text
              or RELEASE_TOKEN not in text):
            status = "HOLD_SOURCE_OWNER_FIXED_BOUNDARY_NOT_RELEASED"
        else:
            items = history.get("workflow_runs")
            count = history.get("total_count")
            if (type(items) is not list or type(count) is not int or count < 0
                    or len(items) > 100 or count < len(items)):
                status = "HOLD_INCOMPLETE_RUN_HISTORY"
            elif count > len(items):
                # Do not infer absence of a past same-day original from page 1.
                status = "HOLD_INCOMPLETE_RUN_HISTORY"
            else:
                current_day = now.astimezone(ZoneInfo("Asia/Tokyo")).date()
                previous = False
                for item in items:
                    if type(item) is not dict:
                        raise ValueError("BOAT_DISPATCH_RUN_METADATA_INVALID")
                    if item.get("head_branch") != RELEASE_REF:
                        continue
                    if item.get("name") != WORKFLOW:
                        continue
                    if _stamp(item.get("created_at")).astimezone(
                            ZoneInfo("Asia/Tokyo")).date() == current_day:
                        previous = True
                status = ("HOLD_ALREADY_DISPATCHED_FOR_JST_DAY" if previous else
                          "READY_EXISTING_OWNER_WORKFLOW_ONLY")
    return {
        "schema": SCHEMA,
        "status": status,
        "dispatch_allowed": status == "READY_EXISTING_OWNER_WORKFLOW_ONLY",
        "release_sha": RELEASE_SHA,
        "new_model_or_scorer_added": False,
        "official_source_requests": 0,
        "future_real_forecast_proven": False,
        "official_results_reconciled": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--owner-doc", type=Path, required=True)
    p.add_argument("--history", type=Path, required=True)
    p.add_argument("--github-output", type=Path)
    args = p.parse_args(argv)
    result = decide(
        now=datetime.now(timezone.utc), release=_load(args.release),
        owner_doc=_load(args.owner_doc), history=_load(args.history))
    if args.github_output:
        if args.github_output.is_symlink() or not args.github_output.is_file():
            raise SystemExit("BOAT_DISPATCH_OUTPUT_INVALID")
        with args.github_output.open("a", encoding="utf8") as out:
            out.write("ready=" + ("true" if result["dispatch_allowed"] else "false") + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
