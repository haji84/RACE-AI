"""Source-free, count-only daily BOAT scoring coverage for automatic site audits.

Consumes only an already AES-authenticated saved view and the ORIGINAL
retained_model_pdca_audit.score_view result. Never downloads official racing
pages, changes forecasts, or assumes yesterday's 142 races recur today.
"""
from collections import Counter
from datetime import date
import re

SCHEMA = "RACE_AI_BOAT_SAVED_DAY_AUTO_SITE_AUDIT_V1"
STATES = ("final", "void", "pending", "missing", "unsupported")


def need(ok, reason):
    if not ok:
        raise ValueError("BOAT_AUTO_SITE_" + reason)


def summarize(view, score, states, *, day):
    need(type(day) is str and date.fromisoformat(day).isoformat() == day,
         "DAY_INVALID")
    need(type(view) is dict and view.get("dataset_status") == "REAL_REPORTED" and
         type(view.get("records")) is list, "AUTHENTICATED_VIEW_REQUIRED")
    rows = [r for r in view["records"] if r.get("sport") == "boat" and
            r.get("event_date_jst") == day]
    need(0 < len(rows) <= 288 and
         len({r.get("race_id") for r in rows}) == len(rows),
         "RACE_COHORT_INVALID")
    need(type(states) is dict and set(states) == {r["race_id"] for r in rows},
         "STATUS_INVENTORY_INVALID")
    statuses = Counter()
    for row in rows:
        value = states[row["race_id"]]
        need(type(value) is str and value in STATES, "RESULT_STATUS_INVALID")
        statuses[value] += 1
    need(type(score) is dict and
         score.get("schema") == "RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1" and
         score.get("source") == "AES_AUTHENTICATED_SAVED_VIEW_ONLY" and
         score.get("no_provider_requests") is True and
         score.get("rewrote_predictions") is False and
         score.get("actual_purchases") is False,
         "NATIVE_SCORER_REQUIRED")
    groups = score.get("model_groups")
    need(type(groups) is list and len(groups) <= 256, "GROUPS_INVALID")
    model_summaries = []
    group_forecasts = group_scored = group_void = group_held = group_pending = 0
    for entry in groups:
        need(type(entry) is dict and
             type(entry.get("model_id")) is str and
             re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", entry["model_id"]) is not None and
             entry.get("stage") in ("P0", "P1", "A_PRE_TRIAL", "B_POST_TRIAL"),
             "MODEL_ID_OR_STAGE_INVALID")
        names = ("forecasts", "eligible", "hits", "misses", "void", "held", "pending")
        need(all(type(entry.get(k)) is int and entry[k] >= 0 for k in names),
             "MODEL_COUNTS_INVALID")
        need(entry["forecasts"] ==
             entry["eligible"] + entry["void"] + entry["held"] + entry["pending"] and
             entry["eligible"] == entry["hits"] + entry["misses"],
             "MODEL_COUNTS_CONFLICT")
        group_forecasts += entry["forecasts"]
        group_scored += entry["eligible"]
        group_void += entry["void"]
        group_held += entry["held"]
        group_pending += entry["pending"]
        model_summaries.append({k:entry[k] for k in ("model_id","stage",*names)})
    need(group_forecasts == score.get("total_forecasts") and
         group_scored == score.get("total_scored") and
         group_held + group_pending == score.get("unresolved"),
         "NATIVE_MODEL_TOTALS_CONFLICT")
    forecast_total = sum(
        (1 if row.get("prediction") is not None else 0) +
        len(row.get("comparison_predictions") or [])
        for row in rows)
    need(group_forecasts == forecast_total, "SAVED_PREDICTION_TOTALS_CONFLICT")
    complete = (group_forecasts > 0 and group_held == group_pending == 0 and
                group_scored + group_void == forecast_total and
                statuses["final"] + statuses["void"] == len(rows))
    return dict(schema=SCHEMA, status="COMPLETE" if complete else "HOLD",
                event_day=day, saved_races=len(rows), saved_forecasts=forecast_total,
                official_final_races=statuses["final"],
                official_void_races=statuses["void"],
                pending_result_races=statuses["pending"] + statuses["missing"],
                reference_or_unsupported_races=statuses["unsupported"],
                model_scored_forecasts=group_scored,
                model_void_forecasts=group_void,
                model_held_forecasts=group_held,
                model_pending_forecasts=group_pending,
                model_groups=model_summaries,
                official_provider_gets=0, original_forecast_rewrites=0,
                individual_race_ids_exported=False)
