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
RELEASE_SHA = "0534b5d939275cacf61d161dd69aa6d9dc073c96"
FIRST_FAILED_ID = 42993305843
FIRST_FAILED_SHA = "5f5bd960e3377a87541f9d6b348d3c045ea51cf0"
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


def recovery_selection(*, run: dict, artifacts: dict) -> dict:
    """Select saved bytes only; this never authorizes another source attempt."""
    def require(ok):
        if not ok:
            raise ValueError('BOAT_ORIGINAL_RECOVERY_EVIDENCE_REJECTED')
    require(type(run) is dict and type(run.get('id')) is int and run['id'] > 0)
    original_incident = (run['id'] == 42995325741 and
                         run.get('head_sha') == 'e24f09f150e2318dd16a96bdc6db1d8c1317b9ae')
    require((original_incident or run.get('head_sha') == RELEASE_SHA) and
            run.get('head_branch') == RELEASE_REF and
            run.get('event') == 'workflow_dispatch' and
            type(run.get('workflow_id')) is int and run['workflow_id'] == 405276784 and
            run.get('status') == 'completed' and
            run.get('conclusion') in ('success', 'failure', 'cancelled', 'timed_out'))
    for key in ('repository', 'head_repository'):
        repo = run.get(key)
        require(type(repo) is dict and type(repo.get('id')) is int and
                repo['id'] == 1416489937 and repo.get('full_name') == REPO)
    require(type(artifacts) is dict and type(artifacts.get('artifacts')) is list and
            type(artifacts.get('total_count')) is int)
    items = artifacts['artifacts']
    require(0 < len(items) <= 1024 and artifacts['total_count'] == len(items))
    require(all(type(item) is dict and type(item.get('id')) is int and item['id'] > 0
                for item in items))
    require(len({item['id'] for item in items}) == len(items))
    selected = []
    for prefix in ('boat-p0-existing', 'race-cycle-continuity', 'race-source-control'):
        found = [item for item in items if item.get('name') == f"{prefix}-{run['id']}"]
        require(len(found) == 1)
        item = found[0]
        provenance = item.get('workflow_run')
        require(type(provenance) is dict and provenance.get('id') == run['id'] and
                provenance.get('head_sha') == run['head_sha'] and
                all(type(provenance.get(k)) is int and provenance[k] == 1416489937
                    for k in ('repository_id', 'head_repository_id')))
        require(item.get('expired') is False and type(item.get('size_in_bytes')) is int and
                0 < item['size_in_bytes'] <= 160*1024*1024 and
                type(item.get('digest')) is str and
                re.fullmatch(r'sha256:[a-f0-9]{64}', item['digest']) is not None)
        _stamp(item.get('created_at'))
        selected.append(item)
    return dict(source_run_id=run['id'], source_sha=run['head_sha'],
                day_jst=_stamp(selected[0]['created_at']).astimezone(ZoneInfo('Asia/Tokyo')).date().isoformat(),
                p0_artifact=selected[0]['id'],
                companion_artifacts=[item['id'] for item in selected[1:]],
                source_dispatch_allowed=False)


def _verified_failed_before_source(row, evidence):
    """One exact earlier failed checkout; no generalized failed-run override.

    Owner job failed at source-free regression before P0/P1 admission.
    Recheck GitHub independent run, job and artifact metadata every time.
    Missing pages, altered outputs or any recorded source phase fail closed.
    """
    if type(evidence) is not dict or type(row) is not dict:
        return False
    r=evidence.get("run")
    jobs=evidence.get("jobs")
    artifacts=evidence.get("artifacts")
    if (type(r) is not dict or type(jobs) is not dict or
            type(artifacts) is not dict or
            row.get("id") != FIRST_FAILED_ID or
            r.get("id") != FIRST_FAILED_ID or
            r.get("head_sha") != FIRST_FAILED_SHA or
            r.get("head_branch") != RELEASE_REF or
            r.get("event") != "workflow_dispatch" or
            r.get("name") != WORKFLOW or
            r.get("status") != "completed" or
            r.get("conclusion") != "failure" or
            row.get("created_at") != r.get("created_at") or
            row.get("conclusion") != "failure" or
            row.get("status") != "completed"):
        return False
    job_rows=jobs.get("jobs")
    item_rows=artifacts.get("artifacts")
    if (type(job_rows) is not list or len(job_rows) > 30 or
            type(jobs.get("total_count")) is not int or
            jobs["total_count"] != len(job_rows) or
            type(item_rows) is not list or
            artifacts.get("total_count") != 1 or len(item_rows) != 1 or
            item_rows[0].get("name") !=
            "existing-cycle-source-42993305843"):
        return False
    owner_jobs=[j for j in job_rows if type(j) is dict and j.get("name") ==
                "Existing frozen P0, exhibition P1, separate official results and PDCA"]
    if len(owner_jobs) != 1 or owner_jobs[0].get("conclusion") != "failure":
        return False
    steps=owner_jobs[0].get("steps")
    if type(steps) is not list or len(steps) < 60:
        return False
    index={s.get("name"):s for s in steps if type(s) is dict}
    if len(index) != len(steps):
        return False
    failed="Test originals, pending results, tampering and unchanged models"
    if index.get(failed, {}).get("conclusion") != "failure":
        return False
    # Every path that could issue or save genuine P0/P1 was skipped before
    # any source session. The failed run retained only source code.
    must_skip=(
        "Check all earlier same-day receipts before first P0",
        "Authenticate the requested grid before any bootstrap source GET",
        "Obtain first P0 from verified official B only if truly absent",
        "Save first P0 separately before reading results",
        "Execute new-day P0 families from the authenticated first receipt",
        "Freeze additional new-day P0 as owner ciphertext",
        "Wait without source requests for the authenticated exhibition window",
        "Initialize continuous source session and account for initial B GET",
        "Deadline-ordered five-model round 01",
    )
    return all(index.get(name, {}).get("conclusion") == "skipped"
               for name in must_skip)



def _resume_admitted(run: dict, *, proof: dict, now: datetime) -> bool:
    """Only an AES-authenticated closed worker can resume on the same JST day."""
    if type(proof) is not dict:
        return False
    base = proof.get("day_start_lifetime_requests")
    total = proof.get("lifetime_requests")
    return bool(
        proof.get("status") == "AUTHENTICATED_EXISTING_OWNER_FINAL_CONTROL"
        and proof.get("source_run_id") == run.get("id")
        and proof.get("source_sha") == RELEASE_SHA
        and proof.get("day_jst") == now.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()
        and run.get("head_sha") == RELEASE_SHA
        and run.get("event") == "workflow_dispatch"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and proof.get("prepared_round") is None
        and proof.get("source_wait") is None
        and proof.get("previous_stop_reason") in (
            "BOUNDED_SESSION_END", "MAX_ROUNDS_REACHED", "WORKER_HANDOFF")
        and type(base) is int and type(total) is int
        and 0 <= base <= total
        and 0 <= total - base <= 240 - 45
        and type(proof.get("continuity_artifact_id")) is int
        and type(proof.get("source_control_artifact_id")) is int
        and proof["continuity_artifact_id"] != proof["source_control_artifact_id"]
    )


def decide(*, now: datetime, release: dict, owner_doc: dict, history: dict, retry_proof=None, resume_proof=None) -> dict:
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
        elif (text.rfind(RELEASE_TOKEN) < 0 or
              text.rfind(RELEASE_TOKEN) <=
              text.rfind("ACTIVE_FULL_FIRST_TO_FIXED_ATTEMPT_TWO_BOUNDARY")):
            # Old historical HOLD records are preserved. Only an explicitly
            # later owner release can lift the original fixed boundary.
            status = "HOLD_SOURCE_OWNER_FIXED_BOUNDARY_NOT_RELEASED"
        else:
            items = history.get("workflow_runs")
            count = history.get("total_count")
            if (type(items) is not list or type(count) is not int or count < 0
                    or len(items) > 100 or count < len(items)):
                status = "HOLD_INCOMPLETE_RUN_HISTORY"
            else:
                jst = ZoneInfo("Asia/Tokyo")
                current_day = now.astimezone(jst).date()
                day_start = datetime(
                    current_day.year, current_day.month, current_day.day,
                    tzinfo=jst).astimezone(timezone.utc)
                # Every returned run must be time-valid and ordered newest
                # first. GitHub REST can omit older pages after 100 runs.
                rows = []
                for item in items:
                    if type(item) is not dict:
                        raise ValueError("BOAT_DISPATCH_RUN_METADATA_INVALID")
                    stamp = _stamp(item.get("created_at"))
                    if stamp > now:
                        raise ValueError("BOAT_DISPATCH_RUN_FUTURE_TIMESTAMP")
                    rows.append((stamp, item))
                ordered = all(rows[i][0] >= rows[i+1][0]
                              for i in range(len(rows)-1))
                window_covered = count == len(rows) or (
                    count > len(rows) and len(rows) == 100 and ordered and
                    bool(rows) and rows[-1][0] < day_start)
                if not ordered or not window_covered:
                    status = "HOLD_INCOMPLETE_RUN_HISTORY"
                else:
                    # PR regression runs share this same workflow/name/ref,
                    # but cannot issue originals and must not count as a
                    # source owner attempt.
                    relevant = [(at, run) for at, run in rows
                                if run.get("head_branch") == RELEASE_REF and
                                run.get("name") == WORKFLOW and
                                run.get("event") == "workflow_dispatch"]
                    active = any(
                        run.get("status") in {
                            "queued", "in_progress", "waiting",
                            "pending", "requested"}
                        for _, run in relevant)
                    today = [run for at, run in relevant if at >= day_start]
                    if active:
                        status = "HOLD_ACTIVE_OWNER_WORKFLOW"
                    elif len(today) == 0:
                        status = "READY_EXISTING_OWNER_WORKFLOW_ONLY"
                    elif (len(today) == 1 and
                          _verified_failed_before_source(today[0], retry_proof)):
                        status = "READY_RETRY_AFTER_VERIFIED_PRE_SOURCE_FAILURE"
                    elif (0 < len(today) <= 24 and
                          all(run.get("status") == "completed" and
                              run.get("conclusion") == "success" and
                              run.get("head_sha") == RELEASE_SHA and
                              run.get("event") == "workflow_dispatch"
                              for run in today) and
                          _resume_admitted(today[0], proof=resume_proof, now=now)):
                        status = "READY_AUTHENTICATED_SAME_DAY_CONTINUATION"
                    else:
                        status = "HOLD_ALREADY_DISPATCHED_FOR_JST_DAY"
    return {
        "schema": SCHEMA,
        "status": status,
        "dispatch_allowed": status in {
            "READY_EXISTING_OWNER_WORKFLOW_ONLY",
            "READY_RETRY_AFTER_VERIFIED_PRE_SOURCE_FAILURE",
            "READY_AUTHENTICATED_SAME_DAY_CONTINUATION"},
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
    p.add_argument("--retry-proof", type=Path)
    p.add_argument("--github-output", type=Path)
    args = p.parse_args(argv)
    result = decide(
        now=datetime.now(timezone.utc), release=_load(args.release),
        owner_doc=_load(args.owner_doc), history=_load(args.history),
        retry_proof=_load(args.retry_proof) if args.retry_proof else None)
    if args.github_output:
        if args.github_output.is_symlink() or not args.github_output.is_file():
            raise SystemExit("BOAT_DISPATCH_OUTPUT_INVALID")
        with args.github_output.open("a", encoding="utf8") as out:
            out.write("ready=" + ("true" if result["dispatch_allowed"] else "false") + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
