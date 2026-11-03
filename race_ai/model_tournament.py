"""Read-only, same-race comparison for existing four-sport ranking models.

Consumes ORIGINAL research suite records and separate owner-supplied results.
Does not generate new models, fetch public data, attest receipts, retrain,
auto-select production models, or wager. A local hash is NOT a pre-cutoff proof.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

from .four_sport_model_suite import verify_suite
from .ticket_selection_engine import evaluate_ticket_trials, PLAN_NAMES
from .verified_bulk_backtest import BadRecord, load_jsonl

JST = timezone(timedelta(hours=9))
SCORED = frozenset(("HIT", "MISS", "HIT_PLUS_REFUND", "MISS_PLUS_REFUND"))
SETTLED = SCORED | {"FULL_REFUND"}
FIELDS = ("cohort", "race_id", "sport", "day_jst", "model_id", "plan_id",
          "ticket_count", "status", "hit_rank", "gross_yen", "received_yen",
          "refund_yen", "net_yen", "manshu_opportunity", "manshu_hit",
          "result_revision", "source_grade", "source_prediction_sha256",
          "trials_sha256", "as_of", "cutoff_at")


def _need(cond, reason):
    if not cond:
        raise BadRecord(reason)


def _date(value):
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise BadRecord("invalid aware time") from error
    _need(d.tzinfo is not None and d.utcoffset() is not None,
          "offset-aware timestamp required")
    return d.astimezone(JST).date().isoformat()


def _key(race_id, cohort):
    _need(type(race_id) is str and 3 <= len(race_id) <= 180,
          "race identity required")
    _need(type(cohort) is str and 1 <= len(cohort) <= 48 and
          all(v.isascii() and (v.isalnum() or v in "_-") for v in cohort),
          "cohort must be stable ASCII label")
    return cohort, race_id


def _score_record(record):
    _need(type(record) is dict and set(record) == {"cohort", "suite", "result"},
          "expected original suite, separate result and cohort")
    suite, result = record["suite"], record["result"]
    _need(verify_suite(suite), "original suite hash or ticket trial mismatch")
    cohort, rid = _key(suite["race_id"], record["cohort"])
    _need(type(suite.get("models")) is dict and
          type(suite.get("ticket_trials")) is dict and
          tuple(suite["models"]) == tuple(suite["ticket_trials"]),
          "inconsistent model roster")
    day = _date(suite["sales_cutoff_at"])
    if result is not None:
        _need(type(result) is dict, "result must be a separate record")
        _need(result.get("race_id") == rid, "result from another race")
    out = []
    for model_id, prediction in suite["models"].items():
        trials = suite["ticket_trials"][model_id]
        verdict = evaluate_ticket_trials(prediction, trials, result)
        verdict_rows = verdict["plans"]
        high_payouts = set()
        if result is not None and result["status"] == "SETTLED":
            high_payouts = {
                tuple(w["combination"])
                for w in result["winning_combinations"]
                if w["payout_per_100_yen"] >= 10000
            }
        for plan_name in PLAN_NAMES:
            plan = trials["plans"][plan_name]
            actual = verdict_rows[plan_name] if verdict_rows is not None else None
            status = actual["status"] if actual else (
                "RESULT_NOT_OBSERVED" if result is None else verdict["state"])
            out.append({
                "cohort": cohort, "race_id": rid, "sport": suite["sport"],
                "day_jst": day, "model_id": model_id,
                "plan_id": plan_name, "ticket_count": plan["ticket_count"],
                "status": status,
                "hit_rank": actual["hit_rank"] if actual else None,
                "gross_yen": actual["gross_yen"] if actual else None,
                "received_yen": actual["received_yen"] if actual else None,
                "refund_yen": actual["refund_yen"] if actual else None,
                "net_yen": actual["net_yen"] if actual else None,
                "manshu_opportunity": bool(high_payouts) if actual else None,
                "manshu_hit": (any(tuple(t) in high_payouts for t in
                                   plan["ordered_tickets"])
                               if actual and actual["status"] in SCORED else
                               False if actual else None),
                "result_revision": result["revision"] if result else None,
                "source_grade": (result["source_grade"] if result
                                 else "unverified"),
                "source_prediction_sha256": prediction["prediction_sha256"],
                "trials_sha256": trials["trials_sha256"],
                "as_of": suite["as_of"], "cutoff_at": suite["sales_cutoff_at"],
            })
    return (cohort, rid), tuple(suite["models"]), out


def _metrics(rows):
    eligible = [x for x in rows if x["status"] in SCORED]
    settled = [x for x in rows if x["status"] in SETTLED]
    stake = sum(r["gross_yen"] for r in settled)
    received = sum(r["received_yen"] for r in settled)
    manshu_races = sum(bool(r["manshu_opportunity"]) for r in eligible)
    captured = sum(bool(r["manshu_hit"]) for r in eligible)
    hit = sum(r["hit_rank"] is not None for r in eligible)
    return {
        "records": len(rows), "scorable": len(eligible),
        "hit_count": hit, "hit_rate": hit/len(eligible) if eligible else None,
        "stake_yen": stake, "received_yen": received,
        "net_yen": received - stake, "roi": received/stake if stake else None,
        "refund_yen": sum(r["refund_yen"] for r in settled),
        "full_refunds": sum(r["status"] == "FULL_REFUND" for r in settled),
        "pending": sum(r["status"] not in SETTLED for r in rows),
        "manshu_races": manshu_races, "manshu_hits": captured,
        "manshu_capture_rate": (
            captured/manshu_races if manshu_races else None),
        "hit_at_1": sum(r["hit_rank"] is not None and
                        r["hit_rank"] <= 1 for r in eligible),
        "hit_at_3": sum(r["hit_rank"] is not None and
                        r["hit_rank"] <= 3 for r in eligible),
        "hit_at_6": sum(r["hit_rank"] is not None and
                        r["hit_rank"] <= 6 for r in eligible),
        "hit_at_8": sum(r["hit_rank"] is not None and
                        r["hit_rank"] <= 8 for r in eligible),
        "hit_at_12": sum(r["hit_rank"] is not None and
                         r["hit_rank"] <= 12 for r in eligible),
        "source_grades": dict(Counter(r["source_grade"] for r in rows)),
    }


def evaluate(records, schedule=None, *, minimum_paired=100, minimum_days=5):
    """Compare only exact same-race, same-phase predicted models.

    A provisional research leader is never equivalent to approval or
    independently verified historical/forward performance. For source
    authenticity, verified freeze timestamps and results use external audits.
    """
    _need(type(minimum_paired) is int and minimum_paired >= 1 and
          type(minimum_days) is int and minimum_days >= 1, "invalid gates")
    _need(type(records) is list and len(records) <= 10000, "bounded records")
    indexed = {}
    rosters = {}
    versions = {}
    for item in records:
        key, names, scored = _score_record(item)
        _need(key not in indexed, "duplicate race and phase, original immutable")
        indexed[key] = scored
        prior = rosters.setdefault(key[0], names)
        _need(prior == names, "different model rosters in the same cohort")
        signatures = tuple((name, model["model_version"],
                            model.get("model_sha256"))
                           for name, model in item["suite"]["models"].items())
        pinned = versions.setdefault(key[0], signatures)
        _need(pinned == signatures,
              "mixed model versions or weights in the same cohort")
    if schedule is None:
        expected = set(indexed)
        completeness_known = False
    else:
        _need(type(schedule) is list and len(schedule) <= 10000,
              "bounded schedule required")
        expected = set()
        for s in schedule:
            _need(type(s) is dict and set(s) == {"cohort", "race_id"},
                  "schedule requires race and cohort")
            key = _key(s["race_id"], s["cohort"])
            _need(key not in expected, "duplicate schedule slot")
            expected.add(key)
        _need(set(indexed).issubset(expected),
              "predicted race not in expected schedule")
        completeness_known = True
    model_rows = defaultdict(list)
    for batch in indexed.values():
        for row in batch:
            model_rows[(row["cohort"],row["model_id"],row["plan_id"])].append(row)
    scorecards = {}
    for (cohort, model, plan), values in sorted(model_rows.items()):
        scorecards.setdefault(cohort, {}).setdefault(model, {})[plan] = _metrics(values)
    common = {}
    for cohort, roster in sorted(rosters.items()):
        rows_for_cohort = {rid: batch for (phase,rid), batch in indexed.items()
                           if phase == cohort}
        paired = {}
        for rid, batch in rows_for_cohort.items():
            by_name = {r["model_id"]: r for r in batch
                       if r["plan_id"] == "fixed_8"}
            if (set(by_name) == set(roster) and
                all(r["status"] in SCORED for r in by_name.values())):
                paired[rid] = by_name
        matched_races = sorted(paired)
        n = len(matched_races)
        days = len({paired[rid][roster[0]]["day_jst"] for rid in matched_races})
        per_model = {}
        for mid in roster:
            shared = [paired[rid][mid] for rid in matched_races]
            per_model[mid] = _metrics(shared)
        unresolved = sorted(rid for rid, batch in rows_for_cohort.items()
                            if any(row["status"] not in SETTLED for row in batch
                                   if row["plan_id"] == "fixed_8"))
        cutoff_ok = (completeness_known and not unresolved and
                     not any(k[0] == cohort for k in expected-indexed.keys()))
        eligible = n >= minimum_paired and days >= minimum_days and cutoff_ok
        leaders = []
        if eligible:
            for mid in roster:
                own = per_model[mid]
                def dominates(other):
                    rival = per_model[other]
                    return (
                        own["hit_count"] >= rival["hit_count"] and
                        own["net_yen"] >= rival["net_yen"] and
                        own["manshu_hits"] >= rival["manshu_hits"] and
                        (own["hit_count"] > rival["hit_count"] or
                         own["net_yen"] > rival["net_yen"] or
                         own["manshu_hits"] > rival["manshu_hits"]))
                if all(dominates(other) for other in roster if other != mid):
                    leaders.append(mid)
        common[cohort] = {
            "model_ids": list(roster), "paired_scored_races": n,
            "paired_days": days, "minimum_paired": minimum_paired,
            "minimum_days": minimum_days,
            "coverage_in_expected_schedule": cutoff_ok,
            "unresolved_result_race_ids": unresolved,
            "metrics_same_races_fixed_8": per_model,
            "provisional_research_leader": leaders[0] if len(leaders)==1 else None,
            "selection_state": ("RESEARCH_PARETO_LEADER_NOT_APPROVED"
                                if len(leaders)==1 else
                                "NO_PARETO_LEADER" if eligible else
                                "INSUFFICIENT_PAIRED_EVIDENCE"),
            "production_promotion_authorized": False,
        }
    return {
        "schema":"RACE_AI_OWNER_SUPPLIED_MODEL_TOURNAMENT_V1",
        "records":len(indexed), "scheduled":len(expected),
        "schedule_verified_complete":False,
        "schedule_supplied":completeness_known,
        "missing_forecast_keys":[{"cohort":a,"race_id":b}
                                 for a,b in sorted(expected-set(indexed))],
        "cohort_comparisons":common, "scorecards":scorecards,
        "research_only":True, "external_result_authentication":False,
        "external_prediction_receipt_verified":False,
        "automatic_model_switch":False, "official_hit_rate":None,
        "note": "Owner-supplied comparisons. Never assert prospective performance "
                "or choose a production model without independent freeze and "
                "result-source audit.",
        "all_rows":[r for batch in indexed.values() for r in batch],
    }


def run(forecasts_path, schedule_path, out_dir, *, minimum_paired=100, minimum_days=5):
    forecast_path = Path(forecasts_path)
    target = Path(out_dir)
    _need(not target.exists(), "never overwrite previously generated report")
    forecasts = list(load_jsonl(forecast_path))
    schedule = list(load_jsonl(schedule_path)) if schedule_path else None
    report = evaluate(forecasts, schedule,
                      minimum_paired=minimum_paired,
                      minimum_days=minimum_days)
    report["input_sha256"] = {
        "forecast_and_result_bundle": sha256(forecast_path.read_bytes()).hexdigest(),
        "schedule":sha256(Path(schedule_path).read_bytes()).hexdigest()
                   if schedule_path else None}
    rows = report.pop("all_rows")
    target.mkdir(parents=True, exist_ok=False)
    (target/"summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    with (target/"per_model_per_race.csv").open("w", encoding="utf-8-sig",
                                              newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-supplied model tournament")
    parser.add_argument("--bundles", required=True)
    parser.add_argument("--schedule")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-paired", type=int, default=100)
    parser.add_argument("--min-days", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        result = run(args.bundles, args.schedule, args.out,
                     minimum_paired=args.min_paired,
                     minimum_days=args.min_days)
    except (BadRecord, OSError, ValueError, TypeError) as exc:
        print("BAKEOFF_BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"records":result["records"],
                      "comparison_states":{k:v["selection_state"] for k,v in
                      result["cohort_comparisons"].items()}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
