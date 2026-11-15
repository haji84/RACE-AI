"""Source-free, count-only audit of authenticated saved BOAT dates.

Never creates predictions or touches provider APIs. Only existing owner-encrypted
Git history is read. No URL fragments, credentials, original picks, player
records, or plaintext views are printed or uploaded.
"""
import argparse
import base64
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from race_ai.boat_history_store import wire
from race_ai.existing_model_coverage import catalog, is_retired
from scripts import boat_saved_view_feed as feed_cli

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "RACE_AI_BOAT_DATED_DISPLAY_PDCA_AUDIT_V1"
CHECK_DAYS = ("2026-11-08", "2026-11-09", "2026-11-10")
MAX_REPORT = 4 * 1024 * 1024


def required_models():
    return {m["model_id"] for m in catalog()
            if "boat" in m["applicable_sports"] and not is_retired(m["model_id"])}


def classify(*, races, forecasts, missing_model_slots, missing_results, unverified, review, model_groups):
    """Fail-closed. A browser and official-source acceptance is still separate."""
    if races == 0:
        return "HOLD_NO_SAVED_DAY"
    if forecasts == 0:
        return "HOLD_NO_SAVED_FORECAST"
    if missing_model_slots:
        return "HOLD_INCOMPLETE_MODEL_COVERAGE"
    if missing_results:
        return "HOLD_RESULTS_NOT_FINAL"
    if review or unverified:
        return "HOLD_RESULT_RECONCILIATION"
    if model_groups == 0:
        return "HOLD_NO_MODEL_COMPARISON"
    return "READY_FOR_INDEPENDENT_BROWSER_AND_SOURCE_PROOF"


def _summary(view, day, generation, expected):
    rows = [r for r in view["records"] if r.get("sport") == "boat" and r.get("event_date_jst") == day]
    if len({r["race_id"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_SAVED_RACE")
    if not rows:
        return dict(day=day, status="HOLD_NO_SAVED_DAY", generation=generation, races=0,
                    forecasts=0, models_present=0, missing_model_slots=0,
                    results_final=0, results_void=0, results_pending=0, unverified_results=0,
                    model_comparisons=0, prediction_comparison_groups=[],
                    plaintext_published=False, official_source_requests=0)
    if len(rows) > 288 or any(row.get("event_date_jst") != day for row in rows):
        raise ValueError("EVENT_DAY_OR_RACE_BOUND_INVALID")
    count = 0
    observed = set()
    missing_slots = 0
    final_count = void_count = missing_result_count = 0
    unverified = 0
    for row in rows:
        predictions = [p for p in [row.get("prediction"), *(row.get("comparison_predictions") or [])]
                       if p and not is_retired(p.get("model_id"))]
        count += len(predictions)
        present = {p.get("model_id") for p in predictions if isinstance(p.get("model_id"), str)}
        observed.update(present)
        missing_slots += len(expected - present)
        result = row.get("result") or {}
        status = result.get("status")
        if status == "final":
            final_count += 1
        elif status == "void":
            void_count += 1
        else:
            missing_result_count += 1
        # An archived result without its source hash and time is not independently proven.
        if status in ("final", "void") and not (
            isinstance(result.get("source_sha256"), str)
            and len(result["source_sha256"]) == 64
            and isinstance(result.get("observed_at"), str)
        ):
            unverified += 1
    subset = dict(view, event_date_jst=day, records=rows)
    raw = wire(subset).encode("utf-8")
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("DAY_PLAINTEXT_BOUND_INVALID")
    base = Path(os.environ["RUNNER_TEMP"]).resolve()
    if not base.is_dir():
        raise ValueError("PRIVATE_DIRECTORY_UNAVAILABLE")
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix="boat-date-proof-", suffix=".json", dir=base)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        env = {k:v for k,v in os.environ.items()
               if k not in ("GH_TOKEN", "GITHUB_TOKEN", "RACE_AI_STATE_KEY")}
        proc = subprocess.run(
            ["node", str(ROOT / "scripts" / "saved_performance_report.cjs"), "--input", name],
            cwd=ROOT, env=env, capture_output=True, check=False, timeout=110)
        if proc.returncode != 0 or len(proc.stdout) > MAX_REPORT or proc.stderr:
            raise ValueError("EXISTING_PDCA_REPORT_UNAVAILABLE")
        report = json.loads(proc.stdout)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)
    if report.get("schema") != "RACE_AI_SAVED_PERFORMANCE_AGGREGATES_V1":
        raise ValueError("EXISTING_PDCA_SCHEMA_INVALID")
    coverage = report.get("coverage") or {}
    if (coverage.get("races") != len(rows) or coverage.get("forecasts") != count
            or len(coverage.get("days") or []) != 1
            or coverage["days"][0].get("day") != day):
        raise ValueError("PDCA_COVERAGE_CONFLICT")
    groups = report.get("groups") or []
    result_groups = []
    reviews = 0
    for g in groups:
        if g.get("sport") != "boat":
            raise ValueError("PDCA_SPORT_MISMATCH")
        o = g.get("observed") or {}
        fields = ("hits", "misses", "pending", "void", "noForecast", "review")
        if any(type(o.get(k)) is not int or o[k] < 0 for k in fields):
            raise ValueError("PDCA_MODEL_STATUS_INVALID")
        if sum(o[k] for k in fields) != len(rows):
            raise ValueError("PDCA_MODEL_COUNT_MISMATCH")
        reviews += o["review"]
        result_groups.append(dict(model_id=g["model_id"], stage=g["stage"],
                                  scope=g["scope"], issued=g["issued"],
                                  hit=o["hits"], miss=o["misses"], pending=o["pending"],
                                  void=o["void"], no_forecast=o["noForecast"], hold=o["review"]))
    result_groups.sort(key=lambda g:(g["model_id"],g["stage"],g["scope"],g["issued"]))
    status=classify(races=len(rows), forecasts=count, missing_model_slots=missing_slots,
                    missing_results=missing_result_count, unverified=unverified,
                    review=reviews, model_groups=len(groups))
    return dict(day=day, generation=generation, status=status, races=len(rows),
                forecasts=count, models_present=len(observed & expected),
                missing_applicable_models=sorted(expected - observed),
                missing_model_slots=missing_slots,
                results_final=final_count, results_void=void_count,
                results_pending=missing_result_count, unverified_results=unverified,
                model_comparisons=len(groups), prediction_comparison_groups=result_groups,
                digest_of_count_report=hashlib.sha256(wire(result_groups).encode()).hexdigest(),
                plaintext_published=False, official_source_requests=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", nargs="+", default=list(CHECK_DAYS))
    args = parser.parse_args(argv)
    try:
        if not args.days or len(args.days) > 7 or len(set(args.days)) != len(args.days) or any(
            type(d) is not str or date.fromisoformat(d).isoformat() != d for d in args.days):
            raise ValueError("DATE_SELECTION_INVALID")
        config = feed_cli._json(feed_cli._read(ROOT / "audit/state/boat-saved-view-input.json",8192),8192)
        raw = base64.b64decode(config["bootstrap"], validate=True)
        if hashlib.sha256(raw).hexdigest() != config["bootstrap_sha256"]:
            raise ValueError("BOOTSTRAP_DIGEST_INVALID")
        bootstrap = feed_cli.F.open_bootstrap(raw)
        feed_cli.git_auth()
        git = feed_cli.F.FeedRepository(ROOT)
        expected = required_models()
        values = []
        for day in args.days:
            try:
                _, _, generation, view = feed_cli.F.current_view(git,bootstrap,day=day)
                values.append(_summary(view,day,generation,expected))
            except ValueError as exc:
                if str(exc) != "HISTORY_DAY_UNAVAILABLE":
                    raise
                values.append(dict(day=day,status="HOLD_NO_SAVED_DAY",races=0,
                                   forecasts=0, models_present=0, results_final=0,
                                   results_void=0,results_pending=0,model_comparisons=0,
                                   plaintext_published=False,official_source_requests=0))
        output = dict(schema=SCHEMA, days=values,
                      acceptance="HOLD" if any(x["status"] != "READY_FOR_INDEPENDENT_BROWSER_AND_SOURCE_PROOF" for x in values) else "REQUIRES_BROWSER_AND_OFFICIAL_PROOF",
                      official_source_requests=0, plaintext_published=False)
        print(wire(output))
        return 0  # A count-only HOLD is evidence, not a failed control plane.
    except Exception:
        print(wire(dict(schema=SCHEMA, acceptance="REJECTED",
                        error="AUTHENTICATED_DATE_AUDIT_FAILED", official_source_requests=0,
                        plaintext_published=False)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
