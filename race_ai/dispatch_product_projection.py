"""Pure private display of saved existing-model dispatch output.

Native content and seals remain unchanged. This module never forecasts, fetches,
stores, settles, authenticates receipts, or promotes supplied metadata to proof.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta, timezone
import math
import re

from .actions_contract import digest, stamp
from .existing_model_coverage import catalog

SCHEMA = "RACE_AI_PRIVATE_CYCLE_VIEW_V1"
DISPATCH_SCHEMA = "RACE_AI_EXISTING_MODEL_DISPATCH_V1"
STAGES = ("P0", "P1", "A_PRE_TRIAL", "B_POST_TRIAL")
STATES = frozenset(("NOT_APPLICABLE", "INPUT_MISSING", "TRAINED_ARTIFACT_MISSING",
                    "DEADLINE_PASSED", "RULE_FILTERED", "UNCONNECTED_NATIVE_RUNTIME",
                    "SOURCE_NOT_AUTHORIZED", "INPUT_REJECTED", "GENERATED_UNATTESTED", "ORIGINAL_REUSED"))
SAVED = frozenset(("GENERATED_UNATTESTED", "ORIGINAL_REUSED"))
SHA = re.compile(r"[a-f0-9]{64}\Z")
JST = timezone(timedelta(hours=9))
AB = frozenset(("boat-display-rating-PL-reference-v1-UNVALIDATED", "boat-course-motor-shadow-v0.1-UNTRAINED"))


class DispatchProductProjectionError(ValueError):
    """Dispatch content cannot be safely represented as a private view."""


def _need(condition, reason):
    if not condition:
        raise DispatchProductProjectionError("private dispatch projection rejected: " + reason)


def _tree(value, depth=0):
    # Native dictionaries may have integer permutation keys. A JSON round trip
    # would change their types and invalidate their exact saved representation.
    _need(depth <= 64, "native depth")
    if type(value) is dict:
        _need(all(type(key) in (str, int) for key in value), "native object key")
        for child in value.values():
            _tree(child, depth + 1)
    elif type(value) in (list, tuple):
        for child in value:
            _tree(child, depth + 1)
    else:
        _need(type(value) in (str, int, float, bool, type(None)) and
              (type(value) is not float or math.isfinite(value)), "finite native content")


def _clock(value):
    try:
        return stamp(value)
    except (TypeError, ValueError) as exc:
        raise DispatchProductProjectionError("private dispatch projection rejected: timestamp") from exc


def _sha(value, optional=False):
    _need(optional and value is None or type(value) is str and SHA.fullmatch(value) is not None, "SHA format")


def _label(value, limit=250):
    return type(value) is str and bool(value.strip()) and len(value) <= limit


def _race_key(value, sport):
    if sport == "boat" and type(value) is str:
        match = re.fullmatch(r"(\d{4})(\d\d)(\d\d)-?(\d\d)-?(\d\d)", value)
        if match:
            y, m, d, venue, number = match.groups()
            return f"boat:{y}-{m}-{d}:boatrace-jcd-{venue}:{int(number)}"
    return value


def _schedule_identity(row):
    _need(type(row) is dict and _label(row.get("race_id")) and row.get("sport") in ("boat", "keirin", "autorace", "horse") and row.get("stage") in STAGES, "schedule identity")
    _need(row["stage"] in ("P0", "P1") or row["sport"] == "autorace", "native phase sport")
    return (row["sport"], row["race_id"], row["stage"]), _clock(row.get("cutoff_at"))


def _metadata(row):
    day = _clock(row["cutoff_at"]).astimezone(JST).date().isoformat()
    rid = _race_key(row["race_id"], row["sport"])
    match = re.fullmatch(r"(boat|keirin|autorace|horse):(\d{4}-\d\d-\d\d):([^:]+):(\d{1,2})", rid)
    venue, number = row.get("venue"), row.get("race_no")
    if match:
        sport, rid_day, rid_venue, rid_number = match.groups()
        _need(sport == row["sport"] and rid_day == day, "schedule race/cutoff identity")
        _need(venue is None or venue == rid_venue, "schedule venue identity")
        _need(number is None or number == int(rid_number), "schedule race number identity")
        venue, number = rid_venue, int(rid_number)
    _need(venue is None or _label(venue, 100), "saved venue metadata")
    _need(number is None or type(number) is int and 1 <= number <= 99, "saved race number metadata")
    _need(row.get("event_date_jst", day) == day and date.fromisoformat(day).isoformat() == day, "schedule JST day")
    participants = row.get("participants")
    if participants is not None:
        _need(type(participants) is list and len(participants) <= 99, "saved participants")
        numbers = []
        for person in participants:
            _need(type(person) is dict and type(person.get("number")) is int and 1 <= person["number"] <= 99, "saved participant number")
            numbers.append(person["number"])
        _need(len(numbers) == len(set(numbers)), "duplicate saved participant")
    return day, venue, number, participants


def _native_hash(prediction):
    for field in ("prediction_sha256", "model_sha256", "bundle_sha256", "prediction_hash"):
        if field in prediction:
            value = prediction[field]
            _sha(value)
            _need(value == digest({k: v for k, v in prediction.items() if k != field}), "native seal mismatch")
            return value
    return None


def _validate_prediction(slot):
    p = slot["prediction"]
    _need(type(p) is dict, "native prediction object")
    _sha(slot.get("output_sha256"))
    _need(slot["output_sha256"] == digest(p), "native output hash mismatch")
    native_hash = _native_hash(p)
    _need(slot.get("prediction_sha256") == native_hash, "slot/native prediction hash mismatch")
    _need(p.get("model_id", p.get("model")) == slot["model_id"] and p.get("model_version") == slot.get("model_version"), "native model identity")
    if p.get("race_id") is not None:
        _need(_race_key(p["race_id"], slot["sport"]) == _race_key(slot["race_id"], slot["sport"]), "native race identity")
    if p.get("sport") is not None:
        _need(p["sport"] == slot["sport"], "native sport identity")
    for field in ("cutoff_at", "sales_cutoff_at"):
        if p.get(field) is not None:
            _need(_clock(p[field]) == _clock(slot["cutoff_at"]), "native cutoff identity")
    phase = p.get("stage", p.get("phase"))
    expected = "P1" if slot["model_id"] == "boat-pdca-lane-shadow-v1" and phase == "post_exhibition" else phase
    _need(expected is None or expected == slot["stage"], "native stage identity")
    if slot.get("native_stage") is not None:
        _need(slot["native_stage"] == phase, "native saved phase identity")
    # A/B entries themselves omit the race, cutoff and snapshot identity.
    if p.get("race_id") is None and slot["model_id"] != "seller-shadow-v1-20261104":
        context = slot.get("native_context")
        _need(slot["model_id"] in AB and slot["stage"] == "P1" and
              type(context) is dict and _native_hash(context) is not None and
              _race_key(context.get("race_id"), slot["sport"]) == _race_key(slot["race_id"], slot["sport"]) and
              _clock(context.get("cutoff_at")) == _clock(slot["cutoff_at"]) and
              p in context.get("models", []), "native parent identity")
    if slot["model_id"] == "seller-shadow-v1-20261104":
        _seller_row(p, slot)
    return p


def _seller_row(p, slot):
    rows = p.get("rows")
    _need(type(rows) is list and all(type(r) is dict for r in rows), "seller batch rows")
    forecasted = [r for r in rows if "tickets" in r]
    selected = [r for r in forecasted if _race_key(r.get("race_id"), "boat") == _race_key(slot["race_id"], "boat")]
    _need(slot["stage"] == "P0" and p.get("date") == _clock(slot["cutoff_at"]).astimezone(JST).date().isoformat() and
          len(selected) == 1 and len(forecasted) <= 5 and type(p.get("forecasted")) is int and p["forecasted"] == len(forecasted), "seller target race identity")
    return selected[0]


def _ticket(value):
    return type(value) is list and len(value) == 3 and all(type(n) is int and 1 <= n <= 99 for n in value) and len(set(value)) == 3


def _triples(rows):
    _need(type(rows) is list and 0 < len(rows) <= 941094, "NATIVE_RANKING_UNREPRESENTABLE")
    out = []
    for row in rows:
        if type(row) is dict:
            for field in ("score", "relative_weight"):
                if field in row:
                    _need(type(row[field]) in (int, float) and math.isfinite(row[field]) and row[field] >= 0, "NATIVE_RANKING_UNREPRESENTABLE")
        value = row if type(row) is list else row.get("combination", row.get("ticket")) if type(row) is dict else None
        if type(value) is str and re.fullmatch(r"\d{1,2}-\d{1,2}-\d{1,2}", value):
            value = [int(n) for n in value.split("-")]
        _need(_ticket(value), "NATIVE_RANKING_UNREPRESENTABLE")
        out.append(deepcopy(value))
    _need(len({tuple(t) for t in out}) == len(out), "NATIVE_RANKING_UNREPRESENTABLE")
    return out


def _ranking(p, slot):
    top = p.get("ordered_top8", p.get("top8", p.get("main_top8")))
    ranked = p.get("candidates", p.get("full_120", p.get("all120", p.get("ranked_relative_weights"))))
    top, combinations = _triples(top), _triples(ranked)
    _need(1 <= len(top) <= 8 and combinations[:len(top)] == top, "NATIVE_RANKING_UNREPRESENTABLE")
    if p.get("candidate_count") is not None:
        _need(type(p["candidate_count"]) is int and p["candidate_count"] == len(combinations), "NATIVE_RANKING_UNREPRESENTABLE")
    if "candidates" in p:
        _need(all(type(row) is list or type(row) is dict and "combination" in row and
                  set(row) <= {"combination", "score"} for row in ranked), "NATIVE_RANKING_UNREPRESENTABLE")
    candidates = deepcopy(ranked) if "candidates" in p else combinations
    return top, candidates


def _prediction(slot):
    p = _validate_prediction(slot)
    seller = slot["model_id"] == "seller-shadow-v1-20261104"
    if seller:
        plans = _seller_row(p, slot).get("tickets")
        _need(type(plans) is dict, "NATIVE_RANKING_UNREPRESENTABLE")
        top, three = _triples(plans.get("five")), _triples(plans.get("three"))
        _need(len(top) == 5 and len(three) == 3 and top[:3] == three, "NATIVE_RANKING_UNREPRESENTABLE")
        candidates = deepcopy(top)
    else:
        top, candidates = _ranking(p, slot)
    reasons = ["PRIVATE_CYCLE_RESEARCH_VIEW_ONLY", "INDEPENDENT_RECEIPT_NOT_VERIFIED"]
    context = slot.get("native_context") if slot["model_id"] in AB else None
    context = context if type(context) is dict else {}
    result = dict(stage=slot["stage"], native_stage=p.get("stage", p.get("phase")),
                  model_id=slot["model_id"], model_version=slot.get("model_version"),
                  prediction_sha256=slot.get("prediction_sha256"), output_sha256=slot["output_sha256"],
                  model_sha256=p.get("model_sha256"), input_sha256=p.get("input_sha256"),
                  source_sha256=p.get("source_sha256", context.get("source_sha256")),
                  generated_at=p.get("generated_at", p.get("built_at_jst") if seller else context.get("generated_at")),
                  as_of=p.get("as_of"), cutoff_at=slot["cutoff_at"], persisted_at=None,
                  ordered_top8=top, candidates=candidates, odds_independent=p.get("odds_independent"),
                  native_dispatch_prediction=True,
                  native_source_reference=dict(prediction_sha256=slot.get("prediction_sha256"),
                      output_sha256=slot["output_sha256"], parent_context_sha256=_native_hash(context) if context else None),
                  dispatch_status=slot["status"], dispatch_reason=slot["reason"],
                  hash_basis="NATIVE_PREDICTION" if slot.get("prediction_sha256") else "NATIVE_OUTPUT_CONTENT",
                  private_cycle_view=True, external_receipt_verified=False,
                  official_prediction=False, official_metrics_eligible=False)
    if seller:
        result.update(native_ticket_plan="five", native_top8_available=False,
                      candidate_order_scope="SAVED_FIVE_TICKET_PLAN_ONLY", native_ticket_plans=deepcopy(plans))
        reasons.append("FULL_CANDIDATE_ORDER_NOT_SAVED")
    for field, reason in (("prediction_sha256", "NATIVE_PREDICTION_SHA_NOT_SAVED"),
                          ("model_version", "MODEL_VERSION_NOT_SAVED"), ("generated_at", "GENERATED_AT_NOT_SAVED"),
                          ("input_sha256", "INPUT_SHA_NOT_SAVED"), ("source_sha256", "SOURCE_SHA_NOT_SAVED"),
                          ("odds_independent", "ODDS_INDEPENDENCE_NOT_SAVED")):
        if result[field] is None:
            reasons.append(reason)
    for field in ("model_sha256", "input_sha256", "source_sha256"):
        _sha(result[field], optional=True)
    for field in ("generated_at", "as_of"):
        if result[field] is not None:
            _clock(result[field])
    result["missing_reasons"] = reasons
    return result


def project_dispatch(report, *, dataset_status):
    """Project supplied dispatch originals, preserving missing slots and metadata.

    Accept a bare dispatch or a saved local operation's ``dispatch`` member.
    A complete supplied roster is still not independently proven live coverage.
    """
    _need(dataset_status in ("REAL_REPORTED", "SYNTHETIC_ONLY"), "dataset status")
    _need(type(report) is dict, "dispatch object")
    if report.get("schema") != DISPATCH_SCHEMA and "dispatch" in report:
        report = report["dispatch"]
    _tree(report)
    _need(type(report) is dict and report.get("schema") == DISPATCH_SCHEMA, "dispatch schema")
    _need(report.get("research_only") is True and report.get("external_receipts_created") is False and
          report.get("originals_overwritten") is False and report.get("new_model_created") is False and
          type(report.get("source_requests")) is int and report["source_requests"] == 0, "dispatch safety flags")
    _clock(report.get("as_of"))
    _sha(report.get("input_sha256"))
    slots = report.get("slots")
    _need(type(slots) is list and len(slots) <= 320000, "dispatch slot count")
    counts = report.get("status_counts")
    _need(type(counts) is dict and all(type(n) is int and n >= 0 for n in counts.values()) and
          counts == dict(Counter(s.get("status") for s in slots if type(s) is dict)), "dispatch status counts")
    originals = report.get("retained_originals", [])
    _need(type(originals) is list and len(originals) <= 320000, "retained original count")
    rows = report.get("schedule")
    if rows is None:
        rows, seen = [], set()
        for slot in slots:
            key, _ = _schedule_identity(slot)
            if key not in seen:
                rows.append({k: deepcopy(slot[k]) for k in ("race_id", "sport", "stage", "cutoff_at")})
                seen.add(key)
    _need(type(rows) is list and len(rows) <= 20000, "schedule count")
    specs = {s["model_id"]: s for s in catalog()}
    schedule, records = {}, {}
    for supplied in rows:
        key, cutoff = _schedule_identity(supplied)
        _need(key not in schedule, "duplicate schedule stage")
        pins = supplied.get("model_versions", {})
        _need(type(pins) is dict and all(mid in specs and (version is None or _label(version, 100)) for mid, version in pins.items()), "schedule model version pins")
        offering = supplied.get("offering_status", "UNKNOWN")
        _need(offering in ("TRIFECTA_OFFERED", "NOT_OFFERED", "UNKNOWN"), "schedule offering status")
        schedule[key] = supplied
        race_key = key[:2]
        day, venue, number, participants = _metadata(supplied)
        if race_key in records:
            row = records[race_key]
            _need(_clock(row["cutoff_at"]) == cutoff, "conflicting race cutoff")
            for field, saved in (("venue", venue), ("race_no", number)):
                if saved is not None:
                    _need(row[field] is None or row[field] == saved, "conflicting race metadata")
                    row[field] = saved
            if participants is not None:
                _need(row["participants"] is None or row["participants"] == participants, "conflicting saved participants")
                row["participants"] = deepcopy(participants)
        else:
            row = dict(race_id=key[1], sport=key[0], cutoff_at=supplied["cutoff_at"],
                       event_date_jst=day, venue=venue, race_no=number, participants=deepcopy(participants),
                       scheduled_stages=[], prediction=None, comparison_predictions=[], dispatch_slots=[],
                       offering_status=offering,
                       scope="synthetic" if dataset_status == "SYNTHETIC_ONLY" else "research",
                       source_sha256=None, source_provenance=None, result=None, result_revisions=[],
                       private_cycle_view=True, native_dispatch_view=True, official_metrics_eligible=False,
                       missing_reasons=["PRIVATE_CYCLE_RESEARCH_VIEW_ONLY", "INDEPENDENT_RECEIPT_NOT_VERIFIED"])
            records[race_key] = row
            _need(len(records) <= 10000, "private race count")
        _need(row["offering_status"] in ("UNKNOWN", offering) or offering == "UNKNOWN", "conflicting offering status")
        if offering != "UNKNOWN":
            row["offering_status"] = offering
        row["scheduled_stages"].append(key[2])
    identities, present = set(), set()
    for slot in slots:
        key, cutoff = _schedule_identity(slot)
        _need(key in schedule and cutoff == _clock(schedule[key]["cutoff_at"]), "slot/schedule identity")
        mid = slot.get("model_id")
        _need(mid in specs and (slot.get("model_version") is None or _label(slot["model_version"], 100)), "slot model identity")
        identity = (*key, mid, slot.get("model_version"))
        _need(identity not in identities, "duplicate slot identity")
        identities.add(identity); present.add((*key, mid))
        status, reason = slot.get("status"), slot.get("reason")
        applicable = key[0] in specs[mid]["applicable_sports"]
        _need(status in STATES and _label(reason, 2000) and (status != "NOT_APPLICABLE") == applicable, "slot status/applicability")
        _need(slot.get("external_receipt_verified") is False and slot.get("official_prediction") is False, "slot evidence flags")
        _need((slot.get("prediction") is not None) == (status in SAVED), "slot prediction status")
        if status in SAVED:
            pins = schedule[key].get("model_versions", {})
            _need(mid not in pins or pins[mid] == slot.get("model_version"), "slot/schedule model version pin")
            native_scope = slot["prediction"].get("scope") if type(slot["prediction"]) is dict else None
            scope = slot.get("scope")
            _need(scope in (None, "SYNTHETIC_ONLY", "OPERATOR_SUPPLIED_RESEARCH") and native_scope in (None, "SYNTHETIC_ONLY", "OPERATOR_SUPPLIED_RESEARCH"), "native source scope")
            _need(scope is None or native_scope is None or scope == native_scope, "slot/native scope mismatch")
            for declared in (scope, native_scope):
                _need(declared is None or (declared == "SYNTHETIC_ONLY") == (dataset_status == "SYNTHETIC_ONLY"), "dataset/native scope mismatch")
        row = records[key[:2]]
        coverage = {k: deepcopy(slot.get(k)) for k in ("stage", "model_id", "model_version", "status", "reason", "prediction_sha256", "output_sha256")}
        coverage.update(applicable=applicable, projection_status="NO_PREDICTION", projection_reason=reason)
        if status in SAVED:
            # Identity/hash failures reject the report. Representability failures
            # retain the actual slot, with a reason and without an invented pick.
            _validate_prediction(slot)
            try:
                projected = _prediction(slot)
            except DispatchProductProjectionError as exc:
                if "NATIVE_RANKING_UNREPRESENTABLE" not in str(exc):
                    raise
                coverage.update(projection_status="UNREPRESENTABLE", projection_reason="NATIVE_RANKING_UNREPRESENTABLE")
                row["missing_reasons"].append("NATIVE_RANKING_UNREPRESENTABLE:" + mid)
            else:
                if row["prediction"] is None:
                    row["prediction"] = projected
                else:
                    _need(len(row["comparison_predictions"]) < 64, "comparison prediction limit exceeded")
                    row["comparison_predictions"].append(projected)
                coverage.update(projection_status="PROJECTED", projection_reason=None)
        row["dispatch_slots"].append(coverage)
    for key in schedule:
        for mid, spec in specs.items():
            if (*key, mid) not in present:
                applies = key[0] in spec["applicable_sports"]
                records[key[:2]]["dispatch_slots"].append(dict(stage=key[2], model_id=mid, model_version=None,
                    status="INPUT_MISSING" if applies else "NOT_APPLICABLE", reason="DISPATCH_SLOT_MISSING", applicable=applies,
                    prediction_sha256=None, output_sha256=None, projection_status="NO_PREDICTION", projection_reason="DISPATCH_SLOT_MISSING"))
    for row in records.values():
        if row["venue"] is None or row["race_no"] is None:
            row["missing_reasons"].append("SAVED_RACE_METADATA_MISSING")
        if row["prediction"] is None:
            row["missing_reasons"].append("NO_SAVED_PREDICTION")
        row["missing_reasons"] = list(dict.fromkeys(row["missing_reasons"]))
    days = {r["event_date_jst"] for r in records.values()}
    return dict(schema=SCHEMA, dataset_status=dataset_status, records=list(records.values()),
                event_date_jst=next(iter(days)) if len(days) == 1 else None,
                as_of=report["as_of"], input_sha256=report["input_sha256"],
                dispatch_status_counts=dict(Counter(s["status"] for s in slots)),
                retained_original_count=len(originals),
                evidence_imported_only=True, research_only=True, independent_receipts_verified=False,
                schedule_completeness_proven=False, all_models_operational=False,
                official_metrics_eligible=False, external_receipts_created=False,
                source_requests=0, new_model_created=False, originals_overwritten=False,
                verification_limitations="Private native research output; no independent freeze, source permission, schedule completeness or official metrics proof.")
