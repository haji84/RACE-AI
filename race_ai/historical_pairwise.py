"""Offline historical result append-only ingestion and same-race 8-vs-12 parity.

OWNER-SUPPLIED sources are unverified until independently authenticated.
No HTTP calls, wagers, pre-cutoff claims, or post-result prediction changes.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

from race_ai.verified_bulk_backtest import (
    BadRecord, choose_results, load_jsonl, settle,
    validate_forecast, validate_result,
)

SCORABLE = frozenset(("HIT", "MISS", "HIT_PLUS_REFUND", "MISS_PLUS_REFUND"))
SETTLED = SCORABLE | {"FULL_REFUND"}
FIELDS = (
    "race_id", "model_id", "cohort", "source_grade", "result_status",
    "status_8", "status_12", "hit_rank_8", "hit_rank_12",
    "gross_8", "gross_12", "received_8", "received_12",
    "refund_8", "refund_12", "source_url",
)


def compare(forecasts, results, model_id=None, cohort=None):
    """Compare prefix8 and prefix12 of the SAME unmodified 12-pick record."""
    chosen = {}
    skipped_short = []
    for f in forecasts:
        validate_forecast(f)
        if model_id is not None and f["model_id"] != model_id:
            continue
        if cohort is not None and f.get("cohort") != cohort:
            continue
        key = (f["race_id"], f["model_id"], f.get("cohort"))
        if key in chosen:
            raise BadRecord(f"duplicate forecast for parity cohort: {key!r}")
        chosen[key] = f
        if len(f["picks"]) < 12:
            skipped_short.append(f["race_id"])
    indexed = choose_results(results)
    report_rows = []
    totals = {8: {"stake": 0, "returned": 0, "refund": 0, "hits": 0},
              12: {"stake": 0, "returned": 0, "refund": 0, "hits": 0}}
    count_normal = 0
    count_settled = 0
    pending = []
    exceptions = []
    self_reported_only = 0
    for key, f in sorted(chosen.items()):
        if len(f["picks"]) != 12:
            continue
        r = indexed.get(f["race_id"])
        f8 = {**f, "picks": f["picks"][:8]}
        a, b = settle(f8, r), settle(f, r)
        if a["status"] in SETTLED and b["status"] in SETTLED:
            count_settled += 1
            for n, data in ((8, a), (12, b)):
                totals[n]["stake"] += data["gross_yen"]
                totals[n]["returned"] += data["received_yen"]
                totals[n]["refund"] += data["refund_yen"]
        if a["status"] in SCORABLE and b["status"] in SCORABLE:
            count_normal += 1
            for n, data in ((8, a), (12, b)):
                totals[n]["hits"] += int(data["hit_rank"] is not None)
        elif a["status"] not in SETTLED or b["status"] not in SETTLED:
            pending.append(f["race_id"])
        else:
            exceptions.append(f["race_id"])
        if (a["freeze_status"] != "INPUT_ATTESTED_PRECUTOFF"
                or a["result_source_grade"] not in
                ("official_observed", "third_party_observed")):
            self_reported_only += 1
        report_rows.append({
            "race_id": f["race_id"],
            "model_id": f["model_id"],
            "cohort": f.get("cohort", ""),
            "source_grade": a["result_source_grade"],
            "result_status": a["result_status"],
            "status_8": a["status"],
            "status_12": b["status"],
            "hit_rank_8": a["hit_rank"],
            "hit_rank_12": b["hit_rank"],
            "gross_8": a["gross_yen"] if a["status"] in SETTLED else None,
            "gross_12": b["gross_yen"] if b["status"] in SETTLED else None,
            "received_8": a["received_yen"],
            "received_12": b["received_yen"],
            "refund_8": a["refund_yen"],
            "refund_12": b["refund_yen"],
            "source_url": a["result_source_url"],
        })
    summary = {
        "cohort_scope": "SAME_RACE_SAME_FORECAST_PREFIX_8_VS_12",
        "adaptive_storm_selection_validated": False,
        "not_a_prospective_claim": True,
        "input_forecasts": len(chosen),
        "paired_12_pick_races": len(report_rows),
        "excluded_fewer_than_12": len(skipped_short),
        "excluded_race_ids": sorted(skipped_short),
        "settled_parity_races": count_settled,
        "normal_accuracy_denominator": count_normal,
        "pending_or_special_race_ids": pending,
        "full_refund_or_incompatible_denominator_race_ids": exceptions,
        "unverified_provenance_or_freeze_count": self_reported_only,
    }
    for n in (8, 12):
        z = totals[n]
        summary[f"pick_{n}"] = {
            "hits": z["hits"],
            "hit_rate": z["hits"] / count_normal if count_normal else None,
            "stake_yen": z["stake"],
            "received_yen": z["returned"],
            "refund_yen": z["refund"],
            "net_yen": z["returned"] - z["stake"],
            "roi": z["returned"] / z["stake"] if z["stake"] else None,
        }
    summary["delta_12_minus_8"] = {
        "hits": totals[12]["hits"] - totals[8]["hits"],
        "added_stake_yen": totals[12]["stake"] - totals[8]["stake"],
        "added_return_yen": totals[12]["returned"] - totals[8]["returned"],
    }
    return summary, report_rows


def append_revisions(base, incoming, output):
    """Append unique (race_id, revision) observations, fail on conflicts."""
    base, incoming, output = map(Path, (base, incoming, output))
    if output.exists():
        raise BadRecord("refusing to overwrite any existing result revision output")
    prior = list(load_jsonl(base))
    newer = list(load_jsonl(incoming))
    seen = {}
    def canonical(r):
        return json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    all_rows = []
    for r in prior + newer:
        validate_result(r)
        key = (r["race_id"], r.get("revision", 1))
        encoded = canonical(r)
        if key in seen:
            if seen[key] != encoded:
                raise BadRecord(f"conflicting immutable result revision: {key!r}")
            continue
        seen[key] = encoded
        all_rows.append(r)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        for r in all_rows:
            f.write(canonical(r) + "\n")
    return {
        "previous_observations": len(prior),
        "incoming_observations": len(newer),
        "new_unique_observations": len(all_rows) - len(prior),
        "total_unique_observations": len(all_rows),
        "base_sha256": sha256(base.read_bytes()).hexdigest(),
        "incoming_sha256": sha256(incoming.read_bytes()).hexdigest(),
        "merged_sha256": sha256(output.read_bytes()).hexdigest(),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline owner-supplied historical evidence review")
    sub = p.add_subparsers(dest="action", required=True)
    comp = sub.add_parser("compare", help="compare 8/12 prefixes of same forecast")
    for name in ("forecasts", "results", "out"):
        comp.add_argument("--" + name, required=True)
    comp.add_argument("--model-id")
    comp.add_argument("--cohort")
    merge = sub.add_parser("append-results", help="append immutable result revisions")
    for name in ("base", "incoming", "out"):
        merge.add_argument("--" + name, required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "append-results":
            print(json.dumps(
                append_revisions(args.base, args.incoming, args.out),
                ensure_ascii=False, indent=2,
            ))
            return 0
        out = Path(args.out)
        if out.exists():
            raise BadRecord("refusing to overwrite previous comparison output")
        summary, rows = compare(
            list(load_jsonl(args.forecasts)), list(load_jsonl(args.results)),
            args.model_id, args.cohort,
        )
        out.mkdir(parents=True, exist_ok=False)
        summary["input_sha256"] = {
            name: sha256(Path(getattr(args, name)).read_bytes()).hexdigest()
            for name in ("forecasts", "results")
        }
        (out / "comparison.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with (out / "same_race_8_vs_12.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not summary["pending_or_special_race_ids"] else 1
    except (BadRecord, OSError) as exc:
        print("AUDIT_BLOCKED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
