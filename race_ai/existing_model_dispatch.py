"""Offline dispatch of the existing sixteen families, without creating models.

Schedule rows explicitly identify race_id, sport, cutoff_at and stage. Inputs
are {race_id: {stage: {native_group: payload}}}; a payload holds the unchanged
native snapshot/source arguments. Originals are prior dispatcher slots with
their exact native prediction and content hash. No receipt is authenticated or
created here. Generated output is private research, never a frozen forecast.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess

from .actions_contract import digest, stamp
from .existing_model_coverage import catalog, active_catalog, is_retired
from .boat_ab_shadow import build_pair, MODEL_IDS as AB
from .boat_live_feature_shadow import build_live_feature_shadow, MODEL_ID as CLITE
from .boat_tactical_scenarios import predict_tactical_shadow, MODEL_ID as TACTICAL
from .boat_multi_feature_models import run_models, MODEL_IDS as FULL
from .boat_observed_pairwise_models import predict_pair, MODEL_IDS as OBSERVED
from .four_sport_model_suite import run_suite, ALL_MODELS
from .four_sport_learning import forecast as learned_forecast, LEARNED_ID
from .autorace_personal_baseline import predict_personal, MODEL_ID as PERSONAL
from research.seller_shadow_v1.model import generate as seller_generate

GROUPS = (("boat_ab", AB), ("boat_clite", (CLITE,)),
          ("boat_tactical", (TACTICAL,)), ("boat_full", FULL),
          ("boat_observed", OBSERVED), ("shared", ALL_MODELS),
          ("shared_learned", (LEARNED_ID,)), ("autorace_personal", (PERSONAL,)),
          ("boat_pdca", ("boat-pdca-lane-shadow-v1",)),
          ("seller", ("seller-shadow-v1-20261104",)))
SPORTS = {"boat", "keirin", "autorace", "horse"}
STAGES = {"P0", "P1", "A_PRE_TRIAL", "B_POST_TRIAL"}
JST = timezone(timedelta(hours=9))


class InputRejected(ValueError):
    pass


class SourceNotAuthorized(ValueError):
    pass


class InputMissing(ValueError):
    pass


class NativeRuntimeUnavailable(ValueError):
    pass


def _time(value):
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("aware dispatch time required")
        return value
    return stamp(value)


def _race_key(value, sport):
    """Only documented official BOAT aliases; never guess a different venue."""
    if sport == "boat" and isinstance(value, str):
        match = re.fullmatch(r"(\d{4})(\d\d)(\d\d)-?(\d\d)-?(\d\d)", value)
        if match:
            y, m, d, venue, n = match.groups()
            return f"boat:{y}-{m}-{d}:boatrace-jcd-{venue}:{int(n)}"
    return value


def _native_hash(prediction):
    for field in ("prediction_sha256", "model_sha256", "bundle_sha256", "prediction_hash"):
        if field in prediction:
            value = prediction[field]
            if value != digest({k:v for k,v in prediction.items() if k != field}):
                raise ValueError("original native prediction hash mismatch")
            return value
    return None


def _original_index(originals, schedule):
    index = {}
    allowed = {(r["race_id"], r["stage"]):r for r in schedule}
    for supplied in originals:
        row = deepcopy(supplied)
        key = (row.get("race_id"), row.get("stage"))
        if key not in allowed:
            raise ValueError("original outside schedule")
        race = allowed[key]
        prediction = row.get("prediction")
        if (not isinstance(prediction, dict) or row.get("model_id") not in {s["model_id"] for s in catalog()}
                or row.get("sport") != race["sport"] or _time(row.get("cutoff_at")) != _time(race["cutoff_at"])):
            raise ValueError("original identity incomplete or conflicting")
        spec = next(s for s in catalog() if s["model_id"] == row["model_id"])
        if race["sport"] not in spec["applicable_sports"]:
            raise ValueError("original model is incompatible with schedule sport")
        if (prediction.get("race_id") is not None and
                _race_key(prediction["race_id"], race["sport"]) != _race_key(race["race_id"], race["sport"])):
            raise ValueError("original native race differs from outer identity")
        phase = prediction.get("stage", prediction.get("phase"))
        if row["model_id"] == "boat-pdca-lane-shadow-v1" and phase == "post_exhibition":
            phase = "P1"
        if (row['model_id'] in FULL and race['stage']=='P0' and
                prediction.get('input_schema')!='RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1'):
            raise ValueError('original complete exhibition model requires P1')
        if (prediction.get("cutoff_at") is not None and _time(prediction["cutoff_at"]) != _time(race["cutoff_at"]) or
                phase is not None and phase != race["stage"]):
            raise ValueError("original native cutoff or stage differs from outer identity")
        if row["model_id"] in AB:
            context = row.get("native_context")
            if (not isinstance(context, dict) or _native_hash(context) is None or race["stage"] != "P1" or
                    _race_key(context.get("race_id"), race["sport"]) != _race_key(race["race_id"], race["sport"]) or
                    _time(context.get("cutoff_at")) != _time(race["cutoff_at"]) or
                    prediction not in context.get("models", [])):
                raise ValueError("original A/B parent identity or content differs")
        if row["model_id"] == "seller-shadow-v1-20261104":
            selected = [r for r in prediction.get("rows", []) if "tickets" in r and
                        _race_key(r.get("race_id"), "boat") == _race_key(race["race_id"], "boat")]
            forecasted = [r for r in prediction.get("rows", []) if "tickets" in r]
            if (race["stage"] != "P0" or len(selected) != 1 or len(forecasted) > 5 or
                    prediction.get("forecasted") != len(forecasted) or
                    prediction.get("date") != _time(race["cutoff_at"]).astimezone(JST).date().isoformat()):
                raise ValueError("original seller batch does not contain target race forecast")
        if (prediction.get("model_id", prediction.get("model")) != row["model_id"]
                or row.get("model_version") != prediction.get("model_version")
                or row.get("output_sha256") != digest(prediction)
                or row.get("prediction_sha256") != _native_hash(prediction)):
            raise ValueError("original content or model identity mismatch")
        identity = (*key, row["model_id"], row.get("model_version"))
        if identity in index and index[identity] != row:
            raise ValueError("conflicting original for one model version")
        index[identity] = row
    return index


def _scope(group, payload):
    snapshot_scope = payload.get("snapshot", {}).get("scope")
    outer_scope = payload.get("scope")
    if snapshot_scope is not None and outer_scope is not None and snapshot_scope != outer_scope:
        raise InputRejected("outer and native snapshot scopes differ")
    return snapshot_scope or outer_scope or "OPERATOR_SUPPLIED_RESEARCH"


def _authorize(group, payload, allow_source):
    scope = _scope(group, payload)
    if scope == "SYNTHETIC_ONLY":
        return
    if scope != "OPERATOR_SUPPLIED_RESEARCH" or not callable(allow_source):
        raise SourceNotAuthorized("independent source authorizer required")
    snapshot = payload.get("snapshot", {})
    evidence = []
    if group in ("shared", "shared_learned"):
        def visit(value):
            if isinstance(value, dict):
                if "source_ref" in value and "source_rights_ref" in value:
                    evidence.append((value["source_ref"], value["source_rights_ref"]))
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(snapshot)
    elif group == "boat_observed":
        evidence = [(s["source_url"], s["source_rights_ref"]) for s in snapshot.get("sources", [])]
    else:
        supplied = payload.get("source_evidence", [])
        if not isinstance(supplied, list):
            raise SourceNotAuthorized("source evidence required")
        evidence = [(e["source_ref"], e["source_rights_ref"]) for e in supplied]
        # Native models without authorization callbacks need separately bound
        # grants for their actual source references/hashes, not a payload flag.
        references = set()
        hashes = set()
        if group == "boat_full":
            references = {r["source_ref"] for r in snapshot.get("entrants", [])}
            # The explicitly sparse schema may carry no weather observations.
            # Its validator requires all condition provenance to be None then.
            if snapshot.get("conditions_source") is not None:
                references.add(snapshot["conditions_source"])
        elif group in ("boat_ab", "boat_clite", "boat_tactical"):
            base = payload.get("source", payload.get("base_source", {}))
            hashes = {base.get("program_source_sha256"), base.get("beforeinfo_source_sha256")}
            if group == "boat_clite":
                hashes.add(payload.get("extra", {}).get("source_sha256"))
            if group == "boat_tactical":
                hashes |= {h["source_receipt"]["official_source_sha256"] for h in payload.get("histories", [])}
                hashes.add(payload.get("venue", {}).get("official_source_sha256"))
        elif group == "autorace_personal":
            references.add(snapshot.get("race", {}).get("source_url"))
        elif group == "seller":
            hashes = {digest(payload.get("cards")), digest(payload.get("waku"))}
        elif group == "boat_pdca":
            facts = payload.get("facts", {})
            hashes = {facts.get("source_sha256"), facts.get("program_sha256")}
            for prior in payload.get("rows", []):
                hashes.add(json.loads(prior["report_json"])["source_sha256"])
                hashes.add(prior["report_sha256"])
        if (not references.issubset({e["source_ref"] for e in supplied}) or
                not hashes.issubset({e.get("source_sha256") for e in supplied})):
            raise SourceNotAuthorized("native source evidence is not bound")
    if not evidence or any(allow_source(ref, rights, "analysis") is not True for ref, rights in set(evidence)):
        raise SourceNotAuthorized("source rights not independently admitted")


def _bind(group, payload, row, now):
    if group == "seller":
        if row["stage"] != "P0":
            raise InputRejected("seller native method requires the morning stage")
        if payload.get("at") is not None and _time(payload["at"]) != now:
            raise InputRejected("new generation cannot use an earlier clock")
        day = date.fromisoformat(payload["day"])
        if _time(row["cutoff_at"]).astimezone(JST).date() != day:
            raise InputRejected("seller day differs from schedule")
        return
    if group in ("boat_ab", "boat_clite", "boat_tactical", "boat_pdca"):
        source = payload.get("source", payload.get("base_source", payload.get("facts", {})))
        rid, cutoff, sport = source.get("race_id"), source.get("cutoff_at"), "boat"
        as_of = source.get("captured_at")
        if row["stage"] != "P1":
            raise InputRejected("exhibition native input requires P1")
    else:
        source = payload.get("snapshot", {})
        race = source.get("race", source)
        rid, cutoff = race.get("race_id"), race.get("sales_cutoff_at")
        sport = race.get("sport", "autorace" if group == "autorace_personal" else "boat")
        as_of = race.get("as_of", race.get("as_of_at"))
        if group in ("boat_full", "boat_observed"):
            if group == "boat_full":
                sparse_p0=(source.get("schema")=="RACE_AI_BOAT_MULTI_FEATURE_SNAPSHOT_SPARSE_V1" and
                           payload.get("stage")=="P0" and row["stage"]=="P0")
                if row["stage"]!="P1" and not sparse_p0:
                    raise InputRejected("complete exhibition input requires P1")
                if payload.get("stage",row["stage"])!=row["stage"]:
                    raise InputRejected("native stage differs from schedule")
            if group == "boat_observed" and source.get("stage") != row["stage"]:
                raise InputRejected("native stage differs from schedule")
        if group == "autorace_personal" and race.get("phase") != row["stage"]:
            raise InputRejected("native phase differs from schedule")
    if (_race_key(rid, row["sport"]) != _race_key(row["race_id"], row["sport"])
            or sport != row["sport"] or _time(cutoff) != _time(row["cutoff_at"])
            or _time(as_of) > now):
        raise InputRejected("native race, cutoff, sport or time differs from schedule")
    if payload.get("generated_at") is not None and _time(payload["generated_at"]) != now:
        raise InputRejected("new generation cannot use an earlier clock")


def _execute(group, payload, row, now, allow_source):
    required = {"boat_ab":("source",), "boat_clite":("base_source","extra"),
                "boat_tactical":("source","histories","venue"), "boat_full":("snapshot",),
                "boat_observed":("snapshot",), "shared":("snapshot",),
                "shared_learned":("snapshot","learned_model"), "autorace_personal":("snapshot",),
                "boat_pdca":("facts","rows"),
                "seller":("cards","waku","day")}[group]
    if any(not payload.get(field) for field in required):
        raise InputMissing("genuine native input is absent")
    _bind(group, payload, row, now)
    _authorize(group, payload, allow_source)
    at = payload.get("generated_at", now.isoformat())
    if group == "boat_ab":
        pair = build_pair(payload["source"], at)
        return {**{p["model_id"]:p for p in pair["models"]}, "__context__":pair}
    if group == "boat_clite":
        p = build_live_feature_shadow(payload["base_source"], payload["extra"], at)
    elif group == "boat_tactical":
        p = predict_tactical_shadow(payload["source"], payload["histories"], payload["venue"], at)
    elif group == "boat_full":
        return run_models(payload["snapshot"])
    elif group == "boat_observed":
        return predict_pair(payload["snapshot"], allow_source=allow_source)["models"]
    elif group == "shared":
        return run_suite(payload["snapshot"], allow_source=allow_source)["models"]
    elif group == "shared_learned":
        p = learned_forecast(payload["snapshot"], payload["learned_model"], allow_source=allow_source)
    elif group == "autorace_personal":
        p = predict_personal(payload["snapshot"], generated_at=at)
    elif group == "boat_pdca":
        wire = json.dumps({"facts":payload["facts"], "rows":payload["rows"], "now":now.isoformat()},
                          ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(wire) > 2 * 1024 * 1024:
            raise InputRejected("PDCA bounded input exceeded")
        script = Path(__file__).resolve().parents[1] / "scripts" / "existing_pdca_offline.mjs"
        try:
            process = subprocess.run(["node", str(script)], input=wire, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NativeRuntimeUnavailable("PDCA native runtime unavailable") from exc
        if process.returncode != 0 or len(process.stdout) > 2 * 1024 * 1024:
            raise InputRejected("PDCA native input rejected")
        report = json.loads(process.stdout)
        if report.get("status") == "PDCA_NOT_ENOUGH_EARLIER_RESULTS":
            return {"__state__":"INPUT_MISSING", "__reason__":"PDCA_REQUIRES_24_EARLIER_SAME_VENUE_RESULTS"}
        if report.get("status") != "PDCA_CHALLENGER_READY" or not isinstance(report.get("candidate"), dict):
            raise InputRejected("PDCA native response invalid")
        p = report["candidate"]
    elif group == "seller":
        day = date.fromisoformat(payload["day"])
        if now.astimezone(JST).hour >= 7:
            return {"__state__":"DEADLINE_PASSED", "__reason__":"SELLER_0700_WINDOW_PASSED"}
        batch = seller_generate(payload["cards"], payload["waku"], day, now)
        chosen = next((r for r in batch["rows"] if _race_key(r["race_id"], "boat") == _race_key(row["race_id"], "boat")), None)
        if chosen is None or "tickets" not in chosen:
            return {"__state__":"RULE_FILTERED", "__reason__":chosen["status"] if chosen else "RACE_NOT_IN_SELLER_CARDS"}
        # Keep the entire native daily original: its <=5 race rule is global,
        # and its native 3/5-ticket plans are never padded into a fake Top8.
        return {"seller-shadow-v1-20261104":batch}
    else:
        raise InputRejected("native group is not connected")
    return {p["model_id"]:p}


def dispatch(schedule, native_inputs, *, now, allow_source=None, originals=()):
    """Return current active race/stage/model slots without external/storage I/O.

    Native inputs are JSON values. Non-callback native real inputs additionally
    require source_evidence[{source_ref,source_rights_ref,source_sha256?}] bound
    to their source references/hashes. An external authorizer must admit those
    grants; source_rights_verified flags never confer permission.

    A schedule row may pin model_versions={model_id: version_string_or_null}.
    Without an explicit pin all supplied original versions are retained; this
    runner never decides to upgrade a model. A/B originals retain their exact
    parent pair under native_context because native model entries omit race
    identity. Seller inputs must use one consistent complete daily batch; a
    supplied first daily original freezes its selection for the remaining rows.
    Callers must provide their complete original inventory, not omit earlier
    receipts to evade the first-original or seller daily-selection rules.

    boat_pdca={facts,rows,scope,...} invokes only the fixed local Node wrapper's
    existing pure builder through bounded JSON pipes. It never uses D1 or the
    worker's freeze/settle functions. Native models lacking model_version keep
    None; content hashes and model IDs do not invent an algorithm version.
    """
    clock = _time(now)
    rows, inputs = deepcopy(schedule), deepcopy(native_inputs)
    if not isinstance(rows, list) or len(rows) > 20000 or not isinstance(inputs, dict):
        raise ValueError("bounded schedule and native input map required")
    seen, races = set(), {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("race_id"), str)
                or not row["race_id"] or row.get("sport") not in SPORTS or row.get("stage") not in STAGES):
            raise ValueError("schedule requires race, sport and explicit supported stage")
        cutoff = _time(row["cutoff_at"])
        versions = row.get("model_versions", {})
        if (not isinstance(versions, dict) or any(mid not in {s["model_id"] for s in catalog()}
                or version is not None and (not isinstance(version, str) or not version) for mid,version in versions.items())):
            raise ValueError("schedule model_versions requires explicit known model version pins")
        key = (row["race_id"], row["stage"])
        identity = (row["sport"], cutoff)
        if key in seen or row["race_id"] in races and races[row["race_id"]] != identity:
            raise ValueError("duplicate or conflicting schedule identity")
        seen.add(key); races[row["race_id"]] = identity
    originals_by_key = _original_index(originals, rows)
    seller_days, seller_signatures = {}, {}
    for original in originals_by_key.values():
        if original["model_id"] != "seller-shadow-v1-20261104":
            continue
        day = original["prediction"]["date"]
        if day in seller_days and seller_days[day]["output_sha256"] != original["output_sha256"]:
            raise ValueError("conflicting original seller daily decisions")
        seller_days[day] = original
    for row in rows:
        if is_retired("seller-shadow-v1-20261104"):break
        payload = inputs.get(row["race_id"], {}).get(row["stage"], {}).get("seller")
        if row["sport"] == "boat" and row["stage"] == "P0" and isinstance(payload, dict):
            day = _time(row["cutoff_at"]).astimezone(JST).date().isoformat()
            signature = digest({"cards":payload.get("cards"), "waku":payload.get("waku")})
            seller_signatures.setdefault(day, set()).add(signature)
    slots, invocations = [], []
    for row in rows:
        per_model = {}
        for spec in active_catalog():
            mid = spec["model_id"]
            base = {**{k:row[k] for k in ("race_id", "sport", "cutoff_at", "stage")},
                    "model_id":mid, "model_version":None, "prediction":None, "prediction_sha256":None,
                    "output_sha256":None, "scope":None, "external_receipt_verified":False,
                    "official_prediction":False, "dispatch_generated_at":None}
            version_pins = row.get("model_versions", {})
            saved = [p for key,p in originals_by_key.items() if key[:3] == (row["race_id"], row["stage"], mid)
                     and (mid not in version_pins or p.get("model_version") == version_pins[mid])]
            if row["sport"] not in spec["applicable_sports"]:
                base.update(status="NOT_APPLICABLE", reason="MODEL_SPORT_NOT_APPLICABLE")
            elif saved:
                for original in saved:
                    reused = deepcopy(original)
                    reused.update(status="ORIGINAL_REUSED", reason="SAVED_NATIVE_CONTENT_RETAINED_NOT_REISSUED",
                                  external_receipt_verified=False, official_prediction=False)
                    slots.append(reused)
                continue
            elif clock >= _time(row["cutoff_at"]):
                base.update(status="DEADLINE_PASSED", reason="NO_POST_CUTOFF_BACKFILL")
            else:
                base.update(status="INPUT_MISSING", reason="NO_NATIVE_INPUT_SUPPLIED")
            per_model[mid] = base
        supplied = inputs.get(row["race_id"], {}).get(row["stage"], {})
        if not isinstance(supplied, dict):
            raise ValueError("native groups must be a map")
        for group, mids in GROUPS:
            pending = [per_model[mid] for mid in mids if mid in per_model and per_model[mid]["status"] == "INPUT_MISSING"]
            if not pending:
                continue
            payload = (supplied.get("shared_learned", supplied.get("shared"))
                       if group == "shared_learned" else supplied.get(group))
            if group == "seller" and row["stage"] == "P0":
                day = _time(row["cutoff_at"]).astimezone(JST).date().isoformat()
                saved_day = seller_days.get(day)
                if saved_day is not None:
                    batch = saved_day["prediction"]
                    selected = any("tickets" in r and _race_key(r["race_id"], "boat") == _race_key(row["race_id"], "boat") for r in batch["rows"])
                    for s in pending:
                        if s["model_id"] in row.get("model_versions", {}) and saved_day.get("model_version") != row["model_versions"][s["model_id"]]:
                            s.update(status="INPUT_REJECTED", reason="SAVED_SELLER_VERSION_DIFFERS_FROM_REQUESTED_PIN")
                            continue
                        if selected:
                            s.update(status="ORIGINAL_REUSED", reason="SAVED_SELLER_DAILY_DECISION_NOT_RERANKED",
                                     prediction=deepcopy(batch), output_sha256=saved_day["output_sha256"],
                                     prediction_sha256=saved_day["prediction_sha256"], scope=saved_day.get("scope"))
                        else:
                            s.update(status="RULE_FILTERED", reason="NOT_SELECTED_IN_SAVED_SELLER_DAILY_DECISION")
                    continue
                if len(seller_signatures.get(day, ())) > 1:
                    for s in pending: s.update(status="INPUT_REJECTED", reason="INCONSISTENT_SELLER_DAILY_INPUT_BATCHES")
                    continue
            if group == "shared_learned" and (not isinstance(payload, dict) or not payload.get("learned_model")):
                for s in pending: s.update(status="TRAINED_ARTIFACT_MISSING", reason="NO_GENUINE_FITTED_MULTISPORT_ARTIFACT")
                continue
            if payload is None:
                continue
            try:
                if not isinstance(payload, dict): raise InputRejected("native payload must be a map")
                result = _execute(group, payload, row, clock, allow_source)
                invocations.append(dict(race_id=row["race_id"],stage=row["stage"],native_group=group,
                                        requested_model_ids=[s["model_id"] for s in pending]))
                for s in pending:
                    if "__state__" in result:
                        s.update(status=result["__state__"], reason=result["__reason__"])
                        continue
                    p = result[s["model_id"]]
                    if s["model_id"] in row.get("model_versions", {}) and p.get("model_version") != row["model_versions"][s["model_id"]]:
                        s.update(status="INPUT_REJECTED", reason="NATIVE_MODEL_VERSION_DIFFERS_FROM_REQUESTED_PIN")
                        continue
                    s.update(status="GENERATED_UNATTESTED", reason="NATIVE_RESEARCH_OUTPUT_NO_EXTERNAL_FREEZE",
                             prediction=deepcopy(p), prediction_sha256=_native_hash(p), output_sha256=digest(p),
                             model_version=p.get("model_version"), scope=_scope(group,payload),
                             native_context=deepcopy(result.get("__context__")),
                             native_stage=p.get("stage",p.get("phase")), dispatch_generated_at=clock.isoformat())
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                state = "SOURCE_NOT_AUTHORIZED" if isinstance(exc, SourceNotAuthorized) else "INPUT_MISSING" if isinstance(exc, InputMissing) else "UNCONNECTED_NATIVE_RUNTIME" if isinstance(exc, NativeRuntimeUnavailable) else "INPUT_REJECTED"
                for s in pending: s.update(status=state, reason=type(exc).__name__)
            except Exception:
                # An unexpected model/runtime fault is not missing source data.
                # Fail closed per family and never expose private exception text.
                # SystemExit/KeyboardInterrupt remain fatal and are not swallowed.
                for s in pending:
                    s.update(status="EXECUTION_FAILED", reason="NATIVE_EXECUTION_EXCEPTION")
        slots.extend(per_model.values())
    report = dict(schema="RACE_AI_EXISTING_MODEL_DISPATCH_V1", as_of=clock.isoformat(), slots=slots,
                native_invocations=invocations, status_counts=dict(Counter(s["status"] for s in slots)),
                retained_originals=list(originals_by_key.values()),
                input_sha256=digest(inputs), source_requests=0, external_receipts_created=False,
                originals_overwritten=False, new_model_created=False, research_only=True)
    retired = [item["model_id"] for item in catalog() if is_retired(item["model_id"])]
    if retired: report["retired_model_ids"] = retired
    return report
