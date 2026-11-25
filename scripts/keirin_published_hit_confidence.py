"""Bind historical hit counts to the actual ticket budgets of a published forecast."""

import argparse
import gzip
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from race_ai.keirin_small_ticket_budget import wilson_lower


def grade(hits, total, days):
    if not (0 <= hits <= total and 0 <= days <= total and bool(total) == bool(days)):
        raise ValueError("Invalid historical hit counts")
    if total < 30 or days < 3:
        return "未評価"
    lower = wilson_lower(hits, total)
    for minimum, label in ((0.90, "激アツ"), (0.50, "高"), (0.25, "中")):
        if lower >= minimum:
            return label
    return "低"


def build(raw_forecasts, assessments, history_through, assessed_at):
    packet = json.loads(raw_forecasts)
    forecast_day = date.fromisoformat(packet["date"])
    if history_through >= forecast_day or assessed_at.tzinfo is None:
        raise ValueError("Confidence needs an earlier history cutoff and a timezone")
    if assessed_at < datetime.fromisoformat(packet["generated_at"]):
        raise ValueError("The assessment cannot predate the published ticket selection")
    races = {r["race_id"]: r for r in packet["races"]}
    if len(races) != len(packet["races"]) or not races:
        raise ValueError("Expected distinct published races")
    source_digest = hashlib.sha256(raw_forecasts).hexdigest()
    groups = {}
    assignments = {race_id: {} for race_id in races}
    for market, field in (("2t", "default_exacta_points"), ("3t", "default_trifecta_points")):
        assessment = assessments[market]
        if assessment["forecast_asset_sha256"] != source_digest:
            raise ValueError(f"Different forecast asset for {market}")
        if set(assessment["races"]) != set(races):
            raise ValueError(f"Race IDs do not match the {market} forecast")
        groups[market] = {}
        for race_id, ref in assessment["races"].items():
            points = races[race_id][field]
            if ref["points"] != points:
                raise ValueError(f"Different number of tickets for {market} {race_id}")
            key = ref["group"]
            cohort = assessment["groups"][key]
            expected_variant = races[race_id]["model_variant"]
            if market == "2t" and expected_variant == "both_updates":
                expected_variant = "line"
            lower, upper, score = cohort["lower"], cohort["upper"], ref["score"]
            if not (lower <= score < upper or (score == upper == 1)):
                raise ValueError(f"Support outside the historical band for {race_id}")
            if cohort["points"] != points or cohort["variant"] != expected_variant:
                raise ValueError(f"Incompatible historical cohort for {market} {race_id}")
            hits, total = cohort["hits"], cohort["n"]
            dates = set(cohort.get("dates", cohort.get("by_date", {})))
            days = len(dates)
            if any(type(v) is not int for v in (hits, total, cohort["days"])):
                raise ValueError(f"Expected integer counts for {key}")
            if days != cohort["days"] or any(date.fromisoformat(d) > history_through for d in dates):
                raise ValueError(f"Invalid historical dates for {key}")
            summary = dict(points=points, grade=grade(hits, total, days), hits=hits, total=total, days=days)
            if groups[market].setdefault(key, summary) != summary:
                raise ValueError(f"Inconsistent ticket budget for {key}")
            assignments[race_id][market] = key
    return dict(schema="KEIRIN_PUBLISHED_HIT_CONFIDENCE_V1", date=packet["date"],
                forecast_sha256=source_digest,
                assessed_at=assessed_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
                training_through=history_through.isoformat(), groups=groups, races=assignments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast", type=Path, required=True, help="Published forecast JSON.gz")
    parser.add_argument("--exacta", type=Path, required=True)
    parser.add_argument("--trifecta", type=Path, required=True)
    parser.add_argument("--history-through", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = gzip.decompress(args.forecast.read_bytes())
    data = build(source, {"2t": json.loads(args.exacta.read_bytes()), "3t": json.loads(args.trifecta.read_bytes())},
                 args.history_through, datetime.now(timezone.utc))
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with args.output.open("xb") as output:
        output.write(gzip.compress(payload, mtime=0))
    print(hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    main()
