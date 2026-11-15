"""Idempotent finished-race audit and next-race refresh queue for PR64/PR71.

Collector, authenticated private Blob reader, PR64 validators, and append-only
receipt storage MUST be injected. This pure module performs no network or
automatic model promotion. An hourly chat task is not a live cutoff scheduler.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json

from .exhibition_autorun import _moment
from .pr64_exhibition_pipeline import _rank, score_after_finish, daily_rollup


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def audit_cycle(races, *, clock, load_forecast, load_result, validate_forecast,
                validate_result, latest_audit, append_audit, read_audit,
                max_closed=24):
    """Process verified past-cutoff races oldest first, never alter forecasts.

    For each finished race:
      1) original PR64 readback and parent-verified snapshot -> fixed top8
      2) independently validated official result/dispositions and captured_at
      3) SHA-keyed, compare-and-append PDCA object, then exact readback
    Uncertain store writes are never retried automatically. A later official
    result correction may append a new revision, never rewrite the old one.
    The callbacks must use server-side append-only storage, not a mutable file.
    """
    callbacks=(clock,load_forecast,load_result,validate_forecast,
               validate_result,latest_audit,append_audit,read_audit)
    if not isinstance(races,list) or not all(callable(f) for f in callbacks):
        raise ValueError("complete race ledger and authenticated adapters required")
    if type(max_closed) is not int or not 1<=max_closed<=100:
        raise ValueError("bounded result budget required")
    now=_moment(clock())
    seen=set()
    closed=[]
    upcoming=[]
    for r in races:
        if not isinstance(r,dict) or r.get("sport")!="boat":
            raise ValueError("BOAT-only race ledger required")
        rid=r.get("race_id")
        if not isinstance(rid,str) or rid in seen:
            raise ValueError("duplicate or missing race ID")
        seen.add(rid)
        if r.get("cutoff_verified") is not True or r.get("source_permission_approved") is not True:
            continue
        cutoff=_moment(r["cutoff_at"])
        if cutoff!=_moment(r["closed_at"]):
            raise ValueError("inconsistent signed cutoff")
        (closed if cutoff<=now else upcoming).append(r)
    closed.sort(key=lambda r:(_moment(r["cutoff_at"]),r["race_id"]))
    upcoming.sort(key=lambda r:(_moment(r["cutoff_at"]),r["race_id"]))
    states=[]
    processed=0
    for r in closed:
        rid=r["race_id"]
        if processed>=max_closed:
            states.append({"race_id":rid,"state":"AUDIT_BUDGET_DEFERRED"});continue
        processed+=1
        try:
            original=load_forecast(r)
            if original is None:
                frozen=None
            else:
                frozen=_rank(original,r,now,validate_forecast)
        except (ValueError,KeyError,TypeError,OSError):
            states.append({"race_id":rid,"state":"FORECAST_READBACK_UNVERIFIED"});continue
        try:
            bundle=load_result(r)
            report=score_after_finish(r,frozen,bundle,now=now,validate_result=validate_result)
        except (ValueError,KeyError,TypeError,OSError):
            states.append({"race_id":rid,"state":"RESULT_READBACK_UNVERIFIED"});continue
        if report.get("state")!="RESULT_SCORED":
            states.append({"race_id":rid,"state":report["state"]});continue
        try:
            prior=latest_audit(rid)
            if prior is not None and (not isinstance(prior,dict)
                 or type(prior.get("revision")) is not int or prior["revision"]<1
                 or not isinstance(prior.get("report"),dict)
                 or prior.get("sha256")!=_digest(prior["report"])):
                raise ValueError("untrusted prior revision")
            if prior is not None and prior["report"]==report:
                states.append({**report,"audit_state":"ALREADY_SAVED",
                               "revision":prior["revision"]})
                continue
            # Official result corrections may change the winner and metrics,
            # but NEVER swap the original frozen forecast/evidence.
            if prior is not None and any(
                prior["report"].get(key) != report.get(key) for key in
                ("cutoff_at","frozen","forecast_receipt_sha256",
                 "forecast_snapshot_id","forecast_model_id")):
                states.append({"race_id":rid,"state":"FORECAST_VERSION_CONFLICT_NO_OVERWRITE"})
                continue
            # A changed official result needs a NEW revision, never a patch.
            # Predicted tickets stay byte-for-byte the same.
            revision=1 if prior is None else prior["revision"]+1
            new={"race_id":rid,"revision":revision,"report":report,
                 "sha256":_digest(report),
                 "previous_sha256":None if prior is None else prior["sha256"]}
            saved=append_audit(new)
            if saved is not True:raise ValueError("unacknowledged audit write")
            durable=read_audit(rid,revision)
            if durable!=new:raise ValueError("mismatched postwrite readback")
            states.append({**report,"audit_state":"DURABLY_APPENDED",
                           "revision":revision})
        except (ValueError,KeyError,TypeError,OSError):
            states.append({"race_id":rid,"state":"AUDIT_POST_UNCERTAIN_NO_RETRY"})
    rollup=daily_rollup(states)
    return {
        "schema":"RACE_AI_PR64_71_PDCA_CYCLE_V1",
        "as_of":now.isoformat(),
        "total_known_races":len(races),
        "completed_races_considered":len(closed),
        "completed_races_checked":processed,
        "future_races":len(upcoming),
        "next_refresh": [
            {"race_id":r["race_id"],"cutoff_at":r["cutoff_at"],
             "plan":"GET_NEW_AS_OF_FACTS_AND_REGENERATE_UNFROZEN_NEXT_RACE"}
            for r in upcoming[:8]],
        "results":states,
        "kpis":rollup,
        "model_auto_promoted":False,
        "live_polling_started":False,
    }
