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
BLOCK_REASONS = STOPS | frozenset("OFFICIAL_BROWSER_"+code for code in (
    "REQUEST_SCHEMA", "CREDENTIAL_HEADER", "OFFICIAL_SOURCE", "UNNEEDED_RESOURCE",
    "STATIC_READ_ONLY", "NORMAL_READ_POST", "NORMAL_READ_IDENTITY", "READ_METHOD",
    "NORMAL_UI_DOCUMENT", "NORMAL_UI_READ", "READ_REQUEST_BODY", "READ_REQUEST_CONTENT_TYPE",
    "DUPLICATE_FORM_FIELD", "CREDENTIAL_BODY"))
OBSERVATION_FIELDS = frozenset("""
schema sport race_id captured_at closed_at source_sha256 source_url body_identity_verified status data
missing_reason reason source_kind source_format verified_official
""".split())
DATA_FIELDS = frozenset("""
status confirmed finish_confirmed confirmed_scope results payouts top3 dead_heat refund_boats refunds
""".split())
FINISH_FIELDS = frozenset("""
race_id lane racer_registration_id name finish finish_status verified_official race_time race_time_seconds
""".split())


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


def audit_observation_conflicts(base, addition):
    """Attribute observation differences; never decide that they are safe."""
    groups = {}; base_conflicts = set(); invalid = 0
    canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for position, view in enumerate((base, addition)):
        for row in view["records"]:
            for observation in row.get("result_observations", []):
                captured = _clock(observation.get("captured_at"))
                if captured is None:
                    invalid += 1
                    continue
                key = (row["race_id"], captured)
                values = groups.setdefault(key, {})
                values.setdefault(canonical(observation), observation)
                if position == 0 and len(values) > 1:
                    base_conflicts.add(key)
    fields = Counter(); data_fields = Counter(); finishes = Counter()
    same = different = unknown = pairs = conflicts = 0
    def count_changes(left, right, allowed, output):
        for field in set(left) | set(right):
            if (field in left) != (field in right) or canonical(left.get(field)) != canonical(right.get(field)):
                output[field if field in allowed else "OTHER"] += 1
    for variants in groups.values():
        if len(variants) < 2:
            continue
        conflicts += 1
        values = list(variants.values())
        for index, left in enumerate(values):
            for right in values[index+1:]:
                pairs += 1
                a, b = left.get("source_sha256"), right.get("source_sha256")
                valid = lambda h: type(h) is str and len(h) == 64 and all(c in "0123456789abcdef" for c in h)
                if not valid(a) or not valid(b):
                    unknown += 1
                elif a == b:
                    same += 1
                else:
                    different += 1
                count_changes(left, right, OBSERVATION_FIELDS, fields)
                x, y = left.get("data"), right.get("data")
                if type(x) is not dict or type(y) is not dict:
                    continue
                count_changes(x, y, DATA_FIELDS, data_fields)
                def by_lane(data):
                    rows = data.get("results")
                    if type(rows) is not list or any(type(r) is not dict or type(r.get("lane")) is not int for r in rows):
                        return {}
                    return {r["lane"]: r for r in rows} if len({r["lane"] for r in rows}) == len(rows) else {}
                first, second = by_lane(x), by_lane(y)
                for lane in set(first) & set(second):
                    count_changes(first[lane], second[lane], FINISH_FIELDS, finishes)
    return {
        "conflicting_capture_groups": conflicts, "variant_pairs": pairs,
        "base_conflicting_capture_groups": len(base_conflicts),
        "same_source_bytes_conflicts": same, "different_source_bytes_conflicts": different,
        "unknown_source_bytes_conflicts": unknown, "uncomparable_observations": invalid,
        "differing_fields": dict(fields), "differing_data_fields": dict(data_fields),
        "differing_finish_fields": dict(finishes), "observations_reconciled": 0,
    }


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
    method = lambda e: e.get("method") if e.get("method") in ("GET", "POST") else "OTHER"
    methods = Counter(method(e) for e in ledger if type(e.get("sequence")) is int and e["sequence"] > 0)
    blocked = Counter(e.get("reason") if e.get("reason") in BLOCK_REASONS else "OTHER"
                      for e in ledger if e.get("event") == "BLOCKED_REQUEST")
    blocked_methods = Counter(method(e) for e in ledger if e.get("event") == "BLOCKED_REQUEST")
    stop = index.get("stop_reason")
    failure = body.get("browser_failure") or {}
    stage = failure.get("stage")
    return {
        "source_requests": None if unknown else len(attempts) + (count or 0),
        "source_requests_upper_bound": body["maximum_requests"], "request_count_unknown": unknown,
        "stop_reason": stop if stop in STOPS else "OTHER",
        "resource_type_counts": dict(resources) if original else None,
        "http_status_counts": dict(statuses), "known_endpoint_counts": dict(endpoints) if original else None,
        "wire_method_counts": dict(methods) if original else None,
        "blocked_reason_counts": dict(blocked) if original else None,
        "blocked_method_counts": dict(blocked_methods) if original else None,
        "static_cache_replays": sum(e.get("event") == "STATIC_CACHE_REPLAY" for e in ledger) if original else None,
        "semantic_ui_clicks": sum(e.get("event") == "NORMAL_SEMANTIC_UI_CLICK" for e in ledger) if original else None,
        "saved_rendered_dom_count": _retained_dom_count(body),
        "case_reason_counts": dict(reasons) if original else None,
        "failure_stage": stage if stage in ("PROCESS", "INDEX_VALIDATION", "LAUNCH", "INDEX_HEADER", "QUARANTINE", "SOURCE_VALIDATION") else "OTHER",
        "original_index_available": original,
    }


def _continuity_projection(pin, *, key, now, day, reader):
    from race_ai.boat_private_original_archive import open_original_zip, MAX_WIRE
    from race_ai.continuity_checkpoint import _sealed_json
    from race_ai.boat_saved_view_intake import project_native_state
    actual = reader.future.metadata(pin["id"])
    run = actual.get("workflow_run") if type(actual) is dict else None
    valid = (
        type(actual) is dict and type(run) is dict and
        actual.get("id") == pin["id"] and actual.get("digest") == pin["digest"] and
        actual.get("name") == "race-cycle-continuity-"+str(pin["run_id"]) and
        type(actual.get("size_in_bytes")) is int and 0 < actual["size_in_bytes"] <= MAX_WIRE and
        actual.get("expired") is False and run.get("id") == pin["run_id"] and
        run.get("head_sha") == pin["head_sha"] and
        all(type(run.get(k)) is int and run[k] == 1416489937 for k in ("repository_id", "head_repository_id")) and
        reader.stamp(actual["created_at"]) <= now < reader.stamp(actual["expires_at"])
    )
    if not valid:
        raise ValueError("AUDIT_CONTINUITY_METADATA")
    raw = reader.future.gh("actions/artifacts/"+str(pin["id"])+"/zip")
    if type(raw) is not bytes or len(raw) != actual["size_in_bytes"] or "sha256:"+sha256(raw).hexdigest() != pin["digest"]:
        raise ValueError("AUDIT_CONTINUITY_BYTES")
    with open_original_zip(raw, actual, expected_kind="CONTINUITY", key=key) as archive:
        info = archive.getinfo("continuity.json")
        if info.file_size > 32*1024*1024:
            raise ValueError("AUDIT_CONTINUITY_BOUND")
        state = _sealed_json(archive.read(info), "state_sha256")
    if state.get("schema") != "RACE_AI_RECOVERED_FIRST_RECEIPTS_V1" or state.get("complete") is not True or state.get("day_jst") != day:
        raise ValueError("AUDIT_CONTINUITY_STATE")
    return project_native_state(state)


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
    required = {"schema", "day_jst", "journal_artifact"}
    if type(value) is not dict or not required <= set(value) <= required | {"continuity_artifact"} or value["schema"] != "RACE_AI_REMAINING_COMPLETION_AUDIT_INPUT_V1":
        raise ValueError("AUDIT_INPUT_SCHEMA")
    if date.fromisoformat(value["day_jst"]).isoformat() != value["day_jst"]:
        raise ValueError("AUDIT_INPUT_DAY")
    C._pins([value["journal_artifact"], *([value["continuity_artifact"]] if "continuity_artifact" in value else [])])
    now = datetime.now(timezone.utc)
    body, _, receipt = C._journal_artifact(value["journal_artifact"], now=now, key=key)
    git_auth()
    generation, view = A._owner_view(value["day_jst"])
    conflicts = None
    if "continuity_artifact" in value:
        projected = _continuity_projection(value["continuity_artifact"], key=key, now=now, day=value["day_jst"], reader=C)
        conflicts = audit_observation_conflicts(view, projected)
        conflicts["artifact_id"] = value["continuity_artifact"]["id"]
        conflicts["authenticated_continuity_readback"] = True
    return value["day_jst"], generation, view, body, receipt, conflicts


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
        day, generation, view, body, receipt, conflicts = _load_authenticated(args.input)
        report = {
            "schema": SCHEMA, "status": "REMAINING_COMPLETION_AUDIT_VERIFIED",
            "day_jst": day, "feed_generation": generation, "journal_artifact_id": receipt["id"],
            "boat": audit_saved_view(view, now=datetime.now(timezone.utc)),
            "native": audit_journal(body), "source_requests": 0, "official_source_requests": 0,
            "continuity_projection": conflicts,
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
