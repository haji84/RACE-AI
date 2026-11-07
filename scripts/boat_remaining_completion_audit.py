"""Read-only Actions audit of retained completion blockers; no provider HTTP."""
import argparse
import base64
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "RACE_AI_REMAINING_COMPLETION_AUDIT_V1"
REASONS = frozenset("""
RESULT_CUTOFF_MISMATCH RESULT_IDENTITY_UNVERIFIED RESULT_RACE_IDENTITY_MISMATCH
RESULT_CAPTURE_BEFORE_CUTOFF RESULT_AMBIGUOUS_FORECAST_CUTOFF RESULT_AMBIGUOUS_SCHEDULE_CUTOFF
RESULT_AMBIGUOUS_OBSERVATION_CUTOFF RESULT_ROSTER_LANES_MISMATCH RESULT_ROSTER_IDENTITY_MISMATCH
RESULT_ROSTER_MISMATCH RESULT_ROSTER_MISSING RESULT_PAYOUT_INVALID RESULT_WINNER_MISMATCH
RESULT_FINISH_ORDER_MISMATCH RESULT_CUTOFF_REFERENCE_CHRONOLOGY RESULT_CUTOFF_REFERENCE_ROSTER_REQUIRED
""".split())
STOPS = frozenset("""
FINISHED HTTP_ACCESS_DENIED TIME_LIMIT REQUEST_LIMIT REQUEST_TIMEOUT REQUEST_DISPATCH_FAILED
CAPTURE_ERROR CAPTURE_HOLD BODY_BOUND BYTE_GUARD_UNAVAILABLE LEDGER_LIMIT
""".split())
CASE_REASONS = frozenset("""
OFFICIAL_BROWSER_CAPTURE_STOPPED OFFICIAL_BROWSER_VISIBLE_UI_CONTROL
OFFICIAL_BROWSER_READ_ONLY_UI_LABEL OFFICIAL_BROWSER_CASE_IDENTITY
OFFICIAL_BROWSER_CASE_RESPONSE_CLOCK UI_OPERATION_REJECTED
""".split())
RESOURCE_TYPES = frozenset(("document", "script", "stylesheet", "xhr", "fetch", "other"))
ENDPOINTS = frozenset(("RaceInfo", "OtherRaceInfo", "RaceResult", "RaceBeforeInfo", "Program"))


def _clock(value):
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at if at.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def audit_saved_view(view, *, now):
    if type(view) is not dict or type(view.get("records")) is not list or now.utcoffset() is None:
        raise ValueError("AUDIT_VIEW_INVALID")
    states = Counter(); reasons = Counter(); offsets = Counter()
    saved_rosters = Counter(); source_rosters = Counter()
    overdue = future = uncertain_cutoff = held = early = identity_verified = 0
    for row in view["records"]:
        result = row.get("result")
        status = result.get("status") if type(result) is dict else "missing"
        status = status if status in ("final", "void", "pending", "unsupported", "missing") else "OTHER"
        states[status] += 1
        cutoff = _clock(row.get("cutoff_at"))
        originals = [cutoff] if cutoff is not None else [
            _clock(value) for value in row.get("saved_cutoff_variants", [])]
        known_clocks = bool(originals) and all(at is not None for at in originals)
        if status not in ("final", "void"):
            if known_clocks and max(originals) <= now:
                overdue += 1
            elif known_clocks and min(originals) > now:
                future += 1
            else:
                uncertain_cutoff += 1
        if status != "unsupported":
            continue
        held += 1
        saved_rosters[str(min(len(row.get("participants", [])), 100))] += 1
        observed = _clock(result.get("observed_at"))
        rejected = [r for r in row.get("result_observation_rejections", [])
                    if observed is not None and _clock(r.get("captured_at")) == observed]
        reason = rejected[-1].get("reason") if rejected else None
        reasons[reason if reason in REASONS else "OTHER"] += 1
        observations = [o for o in row.get("result_observations", [])
                        if observed is not None and _clock(o.get("captured_at")) == observed]
        if len(observations) != 1:
            continue
        source = observations[0]
        identity_verified += source.get("body_identity_verified") is True
        data = source.get("data") or {}
        source_rosters[str(min(len(data.get("results") or []), 100))] += 1
        closed = _clock(source.get("closed_at"))
        if closed is not None and known_clocks:
            maximum = max(abs((closed - at).total_seconds()) for at in originals)
            offsets[str(int(maximum)) if maximum <= 86400 and maximum.is_integer() else "OTHER"] += 1
            predictions = [p for p in [row.get("prediction"), *row.get("comparison_predictions", [])] if p is not None]
            saved = [_clock(p.get("persisted_at")) for p in predictions]
            early += bool(saved) and all(at is not None and at < min(closed, *originals) for at in saved)
    return {
        "races": len(view["records"]), "result_states": dict(states), "held_races": held,
        "overdue_unmatched_races": overdue, "future_unmatched_races": future,
        "unknown_or_mixed_cutoff_unmatched_races": uncertain_cutoff,
        "current_rejection_reason_counts": dict(reasons), "cutoff_offset_seconds_counts": dict(offsets),
        "saved_roster_sizes": dict(saved_rosters), "source_roster_sizes": dict(source_rosters),
        "all_saved_before_both_clocks": early, "latest_held_body_identity_verified": identity_verified,
    }


def _checked_retained_bytes(item):
    encoded = item.get("raw_base64")
    if type(encoded) is not str or len(encoded) > 3*1024*1024:
        raise ValueError("AUDIT_FILE_BOUND")
    raw = base64.b64decode(encoded, validate=True)
    if (type(item.get("byte_count")) is not int or len(raw) > 2*1024*1024 or
            len(raw) != item["byte_count"] or sha256(raw).hexdigest() != item.get("source_sha256")):
        raise ValueError("AUDIT_FILE_INTEGRITY")
    return raw


def _original_index(body):
    files = (body.get("browser_quarantine") or {}).get("files", [])
    indexes = [f for f in files if type(f) is dict and f.get("kind") == "ORIGINAL_INDEX"]
    if not indexes:
        return body.get("browser_index") or {}, False
    if len(indexes) != 1:
        raise ValueError("AUDIT_INDEX_CONFLICT")
    item = indexes[0]
    raw = _checked_retained_bytes(item)
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError("AUDIT_INDEX_SCHEMA")
    return value, True


def _retained_dom_count(body):
    quarantine = body.get("browser_quarantine")
    if type(quarantine) is not dict or type(quarantine.get("files")) is not list:
        return None
    found = {}
    for item in quarantine["files"]:
        if type(item) is not dict or item.get("kind") != "RENDERED_DOM":
            continue
        raw = _checked_retained_bytes(item)
        name = item.get("file")
        if type(name) is not str or name in found and found[name] != raw:
            raise ValueError("AUDIT_DOM_INVENTORY_CONFLICT")
        found[name] = raw
    return len(found)


def audit_journal(body):
    from urllib.parse import urlsplit
    index, original = _original_index(body)
    attempts = body.get("attempts", [])
    browser = body.get("browser_attempt") or {}
    unknown = any(a.get("state") == "RESERVED" for a in attempts) or browser.get("state") == "RESERVED"
    count = browser.get("actual_request_count")
    if browser and (type(count) is not int or count < 0):
        unknown = True
    resources = Counter(); statuses = Counter(); endpoints = Counter()
    for response in index.get("responses", []):
        kind = response.get("resource_type")
        resources[kind if kind in RESOURCE_TYPES else "OTHER"] += 1
        code = response.get("status")
        if type(code) is int and 100 <= code <= 599:
            statuses[str(code)] += 1
        try:
            endpoint = urlsplit(response.get("url", "")).path.rsplit("/", 1)[-1]
        except (ValueError, TypeError):
            endpoint = None
        endpoints[endpoint if endpoint in ENDPOINTS else "OTHER"] += 1
    reasons = Counter(c.get("reason") if c.get("reason") in CASE_REASONS else "OTHER"
                      for c in index.get("cases", []))
    ledger = index.get("ledger", [])
    stop = index.get("stop_reason")
    failure = body.get("browser_failure") or {}
    stage = failure.get("stage")
    return {
        "source_requests": None if unknown else len(attempts) + (count or 0),
        "source_requests_upper_bound": body["maximum_requests"], "request_count_unknown": unknown,
        "stop_reason": stop if stop in STOPS else "OTHER",
        "resource_type_counts": dict(resources) if original else None,
        "http_status_counts": dict(statuses), "known_endpoint_counts": dict(endpoints) if original else None,
        "static_cache_replays": sum(e.get("event") == "STATIC_CACHE_REPLAY" for e in ledger) if original else None,
        "semantic_ui_clicks": sum(e.get("event") == "NORMAL_SEMANTIC_UI_CLICK" for e in ledger) if original else None,
        "saved_rendered_dom_count": _retained_dom_count(body),
        "case_reason_counts": dict(reasons) if original else None,
        "failure_stage": stage if stage in ("PROCESS", "INDEX_VALIDATION", "LAUNCH", "INDEX_HEADER", "QUARANTINE", "SOURCE_VALIDATION") else "OTHER",
        "original_index_available": original,
    }


def _load_authenticated(path):
    # Reached only after the explicit Actions/owner guard.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import race_ai
    reference = str(ROOT/"pr64-reference"/"race_ai")
    if reference not in race_ai.__path__:
        race_ai.__path__.append(reference)
    from race_ai.boat_pdca_state import state_key
    from scripts import all_existing_model_official_result_collect as C
    from scripts import boat_prospective_audit as A
    from scripts.boat_saved_view_feed import git_auth
    key = state_key("production")
    value = json.loads(C._repository_file(ROOT/path, 32768))
    if type(value) is not dict or set(value) != {"schema", "day_jst", "journal_artifact"} or value["schema"] != "RACE_AI_REMAINING_COMPLETION_AUDIT_INPUT_V1":
        raise ValueError("AUDIT_INPUT_SCHEMA")
    if date.fromisoformat(value["day_jst"]).isoformat() != value["day_jst"]:
        raise ValueError("AUDIT_INPUT_DAY")
    C._pins([value["journal_artifact"]])
    now = datetime.now(timezone.utc)
    body, _, receipt = C._journal_artifact(value["journal_artifact"], now=now, key=key)
    git_auth()
    generation, view = A._owner_view(value["day_jst"])
    return value["day_jst"], generation, view, body, receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and
            os.environ.get("GITHUB_REPOSITORY") == "haji84/RACE-AI" and
            os.environ.get("GITHUB_REPOSITORY_ID") == "1416489937"):
        print(json.dumps({"schema": SCHEMA, "status": "REMAINING_COMPLETION_AUDIT_HOLD",
                          "reason": "OWNER_ACTIONS_CONTEXT_REQUIRED", "source_requests": 0}))
        return 2
    try:
        if args.input != "audit/state/remaining-completion-audit-input.json":
            raise ValueError("AUDIT_INPUT_PATH")
        day, generation, view, body, receipt = _load_authenticated(args.input)
        report = {
            "schema": SCHEMA, "status": "REMAINING_COMPLETION_AUDIT_VERIFIED",
            "day_jst": day, "feed_generation": generation, "journal_artifact_id": receipt["id"],
            "boat": audit_saved_view(view, now=datetime.now(timezone.utc)),
            "native": audit_journal(body), "source_requests": 0, "official_source_requests": 0,
            "diagnostic_only": True, "plaintext_source_published": False, "originals_changed": False,
            "forecasting_performed": False, "results_admitted": 0, "accuracy_improvement_proven": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"schema": SCHEMA, "status": "REMAINING_COMPLETION_AUDIT_HOLD",
                          "reason": "AUTHENTICATED_READ_OR_PROJECTION_REJECTED", "source_requests": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
