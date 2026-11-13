"""Whitelisted operational counters bound to an encrypted final checkpoint.

The producer alone decrypts in Actions. The host verifies actual artifact ZIPs,
repository/run/head and ciphertext bytes without acquiring the owner key.
"""
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
import json
import re

from . import boat_private_original_archive as archive

SCHEMA = "RACE_AI_BOAT_PUBLIC_SOURCE_CONTROL_V1"
REPO = "haji84/RACE-AI"
REPO_ID = 1416489937
MEMBER = "source-control.json"
MAX_SUMMARY = 16*1024
MAX_SUMMARY_ZIP = 64*1024
MAX_CONTINUITY_ZIP = archive.MAX_PLAIN_ZIP+archive.MAX_OVERHEAD
NORMAL_STOPS = frozenset((None, "BOUNDED_SESSION_END", "MAX_ROUNDS_REACHED",
    "SESSION_SOURCE_BUDGET_EXHAUSTED", "SOURCE_BUDGET_EXHAUSTED", "ROUND_SOURCE_BUDGET_EXHAUSTED",
    "DAY_CHANGED", "DAY_HANDOFF", "WORKER_HANDOFF"))
STOP_REASONS = NORMAL_STOPS | {"ROUND_SOURCE_BUDGET_EXHAUSTED", "SOURCE_REVIEW_REQUIRED",
    "SOURCE_VERIFICATION_REQUIRED", "SOURCE_HTTP_401_NO_RETRY", "SOURCE_HTTP_403_NO_RETRY", "SOURCE_HTTP_429_NO_RETRY"}
WAIT_REASONS = frozenset(("SOURCE_REVIEW_REQUIRED", "SOURCE_AUTHORIZATION_REQUIRED", "HTTP_RATE_LIMIT",
    "SOURCE_TEMPORARILY_UNAVAILABLE", "SOURCE_NOT_YET_PUBLISHED", "SERVER_RETRY_TIME_UNREPRESENTABLE",
    "SOURCE_VERIFICATION_REQUIRED", "NO_QUALIFIED_FIRST_P0", "PREVIOUS_SOURCE_HALT_REQUIRES_REVIEW"))
WAIT_STATES = frozenset(("RATE_LIMIT_WAIT", "TRANSIENT_SOURCE_WAIT", "AUTHORIZATION_WAIT",
                       "WAITING_PUBLICATION", "SOURCE_REVIEW_WAIT"))
ROOT_FIELDS = frozenset(("schema", "repository", "repository_id", "run_id", "head_sha", "day_jst",
                         "continuity_cipher_sha256", "control"))
CONTROL_FIELDS = frozenset(("requests_used", "completed_round", "prepared_round", "lifetime_requests",
                            "lifetime_completed_rounds", "source_wait", "stop_reason"))


def need(ok, reason):
    if not ok: raise ValueError("SAFE_SOURCE_CONTROL_"+reason)


def _count(value):
    return type(value) is int and 0 <= value <= 2**63-1


def _time(value):
    need(type(value) is str and len(value) <= 64, "CLOCK_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        need(result.utcoffset() is not None, "CLOCK_INVALID")
        return result
    except (ValueError, OverflowError): raise ValueError("SAFE_SOURCE_CONTROL_CLOCK_INVALID") from None


def _json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            need(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    def nonfinite(_): raise ValueError("SAFE_SOURCE_CONTROL_JSON_INVALID")
    try: return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError): raise ValueError("SAFE_SOURCE_CONTROL_JSON_INVALID") from None


def validate_summary(value):
    need(type(value) is dict and set(value) == ROOT_FIELDS and value["schema"] == SCHEMA
         and value["repository"] == REPO and type(value["repository_id"]) is int and value["repository_id"] == REPO_ID,
         "SCHEMA_INVALID")
    need(_count(value["run_id"]) and value["run_id"] > 0 and type(value["head_sha"]) is str
         and re.fullmatch(r"[a-f0-9]{40}", value["head_sha"]), "IDENTITY_INVALID")
    day = value["day_jst"]
    need(type(day) is str and re.fullmatch(r"\d{4}-\d\d-\d\d", day) and date.fromisoformat(day).isoformat() == day,
         "DAY_INVALID")
    need(type(value["continuity_cipher_sha256"]) is str and re.fullmatch(r"[a-f0-9]{64}", value["continuity_cipher_sha256"]),
         "CIPHER_HASH_INVALID")
    control = value["control"]
    accepted=(CONTROL_FIELDS,CONTROL_FIELDS | {"day_start_lifetime_requests"})
    need(type(control) is dict and set(control) in accepted, "CONTROL_FIELDS_INVALID")
    if "day_start_lifetime_requests" in control:
        base=control["day_start_lifetime_requests"]
        need(_count(base) and base<=control["lifetime_requests"] and
             control["lifetime_requests"]-base>=control["requests_used"],"DAY_SOURCE_BUDGET_INVALID")
    for field in ("requests_used", "completed_round", "lifetime_requests", "lifetime_completed_rounds"):
        need(_count(control[field]), "COUNT_INVALID")
    need(control["lifetime_requests"] >= control["requests_used"]
         and control["lifetime_completed_rounds"] >= control["completed_round"], "LIFETIME_COUNT_INVALID")
    prepared = control["prepared_round"]
    need(prepared is None or _count(prepared) and prepared == control["completed_round"]+1, "PREPARED_ROUND_INVALID")
    need(control["stop_reason"] is None or type(control["stop_reason"]) is str and control["stop_reason"] in STOP_REASONS,
         "STOP_REASON_INVALID")
    wait = control["source_wait"]
    if wait is not None:
        need(type(wait) is dict and set(wait) == {"state", "reason", "retry_at", "http_status", "attempts"}
             and type(wait["state"]) is str and wait["state"] in WAIT_STATES
             and type(wait["reason"]) is str and wait["reason"] in WAIT_REASONS, "WAIT_INVALID")
        need(_count(wait["attempts"]) and wait["attempts"] > 0 and (wait["http_status"] is None
             or type(wait["http_status"]) is int and 100 <= wait["http_status"] <= 599), "WAIT_COUNT_INVALID")
        if wait["retry_at"] is not None: _time(wait["retry_at"])
    return True


def build_summary(cipher, *, run_id, head_sha, key=None):
    """Derive only safe fields from the exact owner-authenticated sealed bytes."""
    plain, header = archive._open_envelope(cipher, key=key)
    need(header["kind"] == "CONTINUITY" and header["run_id"] == archive._run(run_id)
         and header["head_sha"] == head_sha, "SEALED_SCOPE_INVALID")
    from .continuity_checkpoint import _control
    with archive._checked_zip(plain, max_zip_bytes=archive.MAX_PLAIN_ZIP) as source:
        member = "repeat-session.json" if "repeat-session.json" in source.namelist() else "bootstrap-source-control.json"
        need(member in source.namelist() and source.getinfo(member).file_size <= 1024*1024, "FINAL_CONTROL_REQUIRED")
        state = _control(source.read(member), member, int(header["run_id"]))
    wait = deepcopy(state.get("source_wait"))
    if wait is not None:
        if wait["reason"] not in WAIT_REASONS: wait["reason"] = "SOURCE_REVIEW_REQUIRED"
        if wait["retry_at"] is not None: wait["retry_at"] = _time(wait["retry_at"]).isoformat()
    reason = state.get("halted_reason") or state.get("previous_halted_reason") or state.get("control_reason")
    if reason not in STOP_REASONS: reason = "SOURCE_REVIEW_REQUIRED"
    day_base=state.get("day_start_lifetime_requests")
    if day_base is not None:
        need(_count(day_base) and day_base<=state["lifetime_requests"] and
             state["lifetime_requests"]-day_base>=state["requests_used"],"DAY_SOURCE_BUDGET_INVALID")
    value = dict(schema=SCHEMA, repository=REPO, repository_id=REPO_ID, run_id=int(header["run_id"]),
        head_sha=head_sha, day_jst=state["day_jst"], continuity_cipher_sha256=sha256(cipher).hexdigest(),
        control=dict(requests_used=state["requests_used"], completed_round=state["completed_round"],
            prepared_round=state.get("prepared_round"), lifetime_requests=state.get("lifetime_requests", state["requests_used"]),
            lifetime_completed_rounds=state.get("lifetime_completed_rounds", state["completed_round"]),
            source_wait=wait, stop_reason=reason))
    if day_base is not None:
        value["control"]["day_start_lifetime_requests"]=day_base
    validate_summary(value)
    return value


def _metadata(raw, meta, *, name, run_id, head_sha):
    need(type(meta) is dict and meta.get("expired") is False and meta.get("name") == name
         and type(meta.get("id")) is int and meta["id"] > 0
         and meta.get("digest") == "sha256:"+sha256(raw).hexdigest()
         and type(meta.get("size_in_bytes")) is int and meta["size_in_bytes"] == len(raw), "ARTIFACT_RECEIPT_INVALID")
    run = meta.get("workflow_run")
    need(type(run) is dict and type(run.get("id")) is int and run["id"] == run_id
         and all(type(run.get(k)) is int and run[k] == REPO_ID for k in ("repository_id", "head_repository_id"))
         and type(head_sha) is str and re.fullmatch(r"[a-f0-9]{40}", head_sha) and run.get("head_sha") == head_sha,
         "ARTIFACT_RUN_HEAD_INVALID")
    _time(meta.get("created_at"))


def require_legacy_clear(raw):
    """The host fallback must never invoke owner decryption, even if a key exists."""
    with archive._checked_zip(raw, max_zip_bytes=archive.MAX_PLAIN_ZIP) as source:
        need(archive.CIPHER_MEMBER not in source.namelist(), "PUBLIC_COMPANION_REQUIRED")


def read_summary(raw, meta, continuity_raw, continuity_meta, *, run_id, head_sha):
    """Authenticate the public companion and its exact opaque sibling cipher."""
    need(type(raw) is bytes and len(raw) <= MAX_SUMMARY_ZIP and type(continuity_raw) is bytes
         and len(continuity_raw) <= MAX_CONTINUITY_ZIP, "ARTIFACT_BOUND_INVALID")
    _metadata(raw, meta, name=f"race-source-control-{run_id}", run_id=run_id, head_sha=head_sha)
    _metadata(continuity_raw, continuity_meta, name=f"race-cycle-continuity-{run_id}", run_id=run_id, head_sha=head_sha)
    with archive._checked_zip(raw, max_zip_bytes=MAX_SUMMARY_ZIP, max_expanded=MAX_SUMMARY) as source:
        need(source.namelist() == [MEMBER], "SUMMARY_MEMBERS_INVALID")
        value = _json(source.read(MEMBER))
    validate_summary(value)
    need(value["run_id"] == run_id and value["head_sha"] == head_sha, "SUMMARY_IDENTITY_INVALID")
    with archive._checked_zip(continuity_raw, max_zip_bytes=MAX_CONTINUITY_ZIP, max_expanded=MAX_CONTINUITY_ZIP) as source:
        need(source.namelist() == [archive.CIPHER_MEMBER], "CONTINUITY_MEMBERS_INVALID")
        cipher = source.read(archive.CIPHER_MEMBER)
    header, _, _, _ = archive._split(cipher)
    need(header["kind"] == "CONTINUITY" and header["run_id"] == str(run_id) and header["head_sha"] == head_sha
         and sha256(cipher).hexdigest() == value["continuity_cipher_sha256"], "CONTINUITY_CIPHER_BINDING_INVALID")
    control = value["control"]; wait = deepcopy(control["source_wait"]); reason = control["stop_reason"]
    if reason not in NORMAL_STOPS:
        from .source_retry_policy import plan_http_wait
        status = {"SOURCE_HTTP_401_NO_RETRY": 401, "SOURCE_HTTP_403_NO_RETRY": 403,
                  "SOURCE_HTTP_429_NO_RETRY": 429}.get(reason)
        if status in (401, 403): wait = plan_http_wait(status, {}, _time(continuity_meta["created_at"]))
        elif status == 429:
            if wait is None or wait["state"] != "RATE_LIMIT_WAIT" or wait["http_status"] != 429:
                wait = plan_http_wait(429, {}, _time(continuity_meta["created_at"]))
        else: wait = dict(state="SOURCE_REVIEW_WAIT", reason="SOURCE_REVIEW_REQUIRED", retry_at=None, http_status=None, attempts=1)
    hard_reason = None if reason in NORMAL_STOPS or wait and wait["retry_at"] is not None else reason
    proof = lambda receipt: {k: deepcopy(receipt[k]) for k in ("id", "digest", "created_at")}
    return dict(previous_run_id=run_id, day_jst=value["day_jst"], previous_session_requests=control["requests_used"],
        completed_round=control["completed_round"], prepared_round=control["prepared_round"],
        lifetime_requests=control["lifetime_requests"], lifetime_completed_rounds=control["lifetime_completed_rounds"],
        source_wait=wait, previous_halted_reason=hard_reason, previous_stop_reason=reason,
        **({"day_start_lifetime_requests":control["day_start_lifetime_requests"]}
            if "day_start_lifetime_requests" in control else {}),
        receipt=proof(continuity_meta), source_control_receipt=proof(meta))
