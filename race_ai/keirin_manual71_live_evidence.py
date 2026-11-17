"""Public-safe five-gate acceptance report for the existing owner KEIRIN Actions.

This checks evidence that OTHER trusted stages actually produced. It cannot
authenticate a third-party result, materialize a private 71R forecast, deploy
a viewer, or prove a human saw a page. It must never infer those facts from
a green workflow or a SHA-only private SQLite readback.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

PILOT = "75-07"
SOURCE_RACE = "202611177507"
STATE = "PR71_SEPARATE_GITHUB_RUNNER_AES_GCM_READBACK_OK"
CIPHER_STATE = "CLOUD_PR71_ENCRYPTED_GIT_HISTORY_READBACK_VERIFIED"
READBACK_STATE = "PRIVATE_MANUAL71_AUDIT_SHA_READBACK_VERIFIED"
AUDIT_STATE = "PRIVATE_MANUAL71_PILOT_RESEARCH_STORED"
SHA = re.compile(r"^[a-f0-9]{64}$")
RUN = re.compile(r"^[1-9][0-9]{0,19}$")
ALLOWED_GATES = ("result_fetch", "result_match", "encrypted_save",
                 "fresh_runner_readback", "html_display")


def _sha(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _run(value):
    return type(value) is str and RUN.fullmatch(value) is not None


def examine(*, producer, readback, action_run_id=None,
            source_receipt=None, viewer_receipt=None,
            independently_verify_source=None,
            independently_verify_browser=None,
            producer_job_id=None, reader_job_id=None,
            trusted_main=False):
    """Require independent evidence for each stage and the SAME source race.

    The two callbacks belong to independently trusted runtimes and are not
    replaced by booleans read from the submitted evidence. Absence means HOLD.
    This function is an acceptance guard, not a result-fetching service.
    """
    p = producer if type(producer) is dict else {}
    r = readback if type(readback) is dict else {}
    man = p.get("manual71_pilot") if type(p.get("manual71_pilot")) is dict else {}
    again = (r.get("manual71_pilot_readback")
             if type(r.get("manual71_pilot_readback")) is dict else {})
    gates = {key: "HOLD" for key in ALLOWED_GATES}
    reasons = {key: "MISSING_LIVE_EVIDENCE" for key in ALLOWED_GATES}
    actual_run = _run(action_run_id)
    distinct_jobs = (
        type(producer_job_id) is str and bool(producer_job_id) and
        type(reader_job_id) is str and bool(reader_job_id) and
        producer_job_id != reader_job_id
    )
    trusted_runtime = trusted_main is True and actual_run and distinct_jobs

    # Result provenance: an owner-supplied description or 3rd-party GET
    # is NOT an authenticated organizer final result.
    if (trusted_runtime and type(source_receipt) is dict and
            source_receipt.get("race_id") == SOURCE_RACE and
            _sha(source_receipt.get("result_revision_sha256")) and
            source_receipt["result_revision_sha256"] == man.get("source_revision_sha256") and
            callable(independently_verify_source) and
            independently_verify_source(source_receipt) is True):
        gates["result_fetch"] = "PASS"
        reasons["result_fetch"] = "TRUSTED_SOURCE_RECEIPT_VERIFIED"
    else:
        reasons["result_fetch"] = "OFFICIAL_FINAL_SOURCE_NOT_INDEPENDENTLY_VERIFIED"

    # The present adapter records provisional/private research comparisons.
    # It may prove the comparison program operated, NOT a formally settled hit.
    audit_exists = (
        man.get("state") == AUDIT_STATE and
        type(man.get("new_audits")) is int and man["new_audits"] >= 1 and
        _sha(man.get("source_revision_sha256")) and
        _sha(man.get("audit_rowset_sha256")) and
        _sha(man.get("latest_html_sha256"))
    )
    if audit_exists and gates["result_fetch"] == "PASS":
        gates["result_match"] = "PASS"
        reasons["result_match"] = "RESULT_JOIN_AND_RESEARCH_AUDIT_PRESENT"
    else:
        reasons["result_match"] = (
            "RESEARCH_AUDIT_NOT_PRESENT" if not audit_exists else
            "REFERENCE_JOIN_NOT_OFFICIALLY_ATTESTED"
        )

    # Existing Git/AES return values can be validated independently without
    # claiming a result was official.
    archived = (
        trusted_runtime and p.get("state") == CIPHER_STATE and
        type(p.get("generation")) is int and p["generation"] >= 1 and
        _sha(p.get("cipher_sha256")) and audit_exists
    )
    if archived:
        gates["encrypted_save"] = "PASS"
        reasons["encrypted_save"] = "CIPHER_AND_GIT_GENERATION_RECORDED"
    else:
        reasons["encrypted_save"] = "NO_SAME_RACE_ENCRYPTED_AUDIT_COMMIT"

    read_ok = (
        archived and r.get("state") == STATE and
        r.get("generation") == p.get("generation") and
        again.get("state") == READBACK_STATE and
        again.get("audit_rowset_sha256") == man.get("audit_rowset_sha256") and
        again.get("latest_html_sha256") == man.get("latest_html_sha256") and
        type(again.get("verified_rows")) is int and again["verified_rows"] >= 1
    )
    if read_ok:
        gates["fresh_runner_readback"] = "PASS"
        reasons["fresh_runner_readback"] = "DIFFERENT_JOB_PRIVATE_SHA_READBACK"
    else:
        reasons["fresh_runner_readback"] = "FRESH_RUNNER_AUDIT_READBACK_NOT_PROVEN"

    # SHA of an HTML blob in a private DB is not a browser rendering receipt.
    # Require a separate trusted owner-viewer check, without exposing picks.
    if (read_ok and type(viewer_receipt) is dict and
            viewer_receipt.get("race_id") == SOURCE_RACE and
            viewer_receipt.get("encrypted_generation") == p.get("generation") and
            _sha(viewer_receipt.get("rendered_html_sha256")) and
            viewer_receipt["rendered_html_sha256"] == again.get("latest_html_sha256") and
            callable(independently_verify_browser) and
            independently_verify_browser(viewer_receipt) is True):
        gates["html_display"] = "PASS"
        reasons["html_display"] = "AUTHENTICATED_OWNER_VIEWER_RENDERED"
    else:
        reasons["html_display"] = "BROWSER_VIEW_AND_OWNER_ACCESS_NOT_VERIFIED"

    return {
        "schema": "RACE_AI_KEIRIN_MANUAL71_LIVE_FIVE_GATE_V1",
        "target_jst": "2026-11-17",
        "pilot_race_id": PILOT,
        "production_run_id": action_run_id if actual_run else None,
        "trusted_main_two_jobs": bool(trusted_runtime),
        "gates": gates,
        "hold_reasons": {k: reasons[k] for k in ALLOWED_GATES if gates[k] != "PASS"},
        "overall": "PASS" if all(gates[k] == "PASS" for k in ALLOWED_GATES)
                   else "HOLD",
        "expanded_to_71": False,
        "prediction_plaintext_exposed": False,
        "real_result_or_model_hit_claimed_by_checker": False,
    }


def load_report(path):
    """Keep input on runner private temp. Do not print private JSON."""
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if type(value) is dict else None
