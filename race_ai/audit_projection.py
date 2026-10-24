"""Read-only projection of PR #69 synthetic journal for the four-sport audit UI.

Never admits real source data and never changes the immutable stored event history.
Production requires a separately authorized source/store, trusted external receipt,
and independent result provenance. Do NOT reuse this test projection as an
official prediction or hit-rate.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .actions_contract import race_key
from .actions_store import SyntheticJournal


def export_synthetic_journal(store: SyntheticJournal) -> dict:
    store.verify()
    latest = {}
    for event in store.events("race"):
        snap = event["payload"]
        key = race_key(snap)
        prior = latest.get(key)
        if prior is None or snap["revision"] > prior["revision"]:
            latest[key] = snap

    predictions = {}
    for event in store.events("freeze"):
        p = event["payload"]
        snap = p["snapshot"]
        key = (race_key(snap), snap["revision"])
        predictions[key] = {
            "ordered_top8": p["prediction"]["ordered_top8"],
            "generated_at": p["prediction"]["generated_at"],
            "persisted_at": event["recorded_at"],
            "cutoff_at": snap["sales_cutoff_at"],
            "input_sha256": snap["snapshot_hash"],
            "prediction_sha256": p["prediction"]["prediction_hash"],
            "model_version": str(p["prediction"]["model"]["version"]),
            "odds_independent": True,
            "external_receipt_verified": False,
            "rationale": "SYNTHETIC_ONLY: internal test journal; no external clock or real source",
        }

    results = {}
    for event in store.events("result"):
        p = event["payload"]
        key = (p["race_key"], p["race_revision"])
        if key not in results or p["revision"] > results[key]["revision"]:
            results[key] = {
                "revision": p["revision"],
                "status": p["status"],
                "winning_combinations": p["winning_combinations"],
                "confirmed_at": event["recorded_at"],
            }

    missing = {}
    for event in store.events("no_forecast"):
        p = event["payload"]
        missing[(p["race_key"], p["race_revision"])] = p["reason"]

    rows = []
    for key, snap in sorted(latest.items()):
        version = (key, snap["revision"])
        r = snap["race_id"]
        rows.append({
            "race_id": f"{r['sport']}:{r['event_date_jst']}:{r['venue']}:{r['race_no']}",
            "sport": r["sport"],
            "venue": r["venue"],
            "race_no": r["race_no"],
            "cutoff_at": snap["sales_cutoff_at"],
            "offering_status": "TRIFECTA_OFFERED" if snap["trifecta_offered"] else "NOT_OFFERED",
            "race_status": snap["status"],
            "prediction": predictions.get(version),
            "result": {k: v for k, v in results[version].items() if k != "revision"} if version in results else None,
            "no_forecast_reason": missing.get(version, "NO_SYNTHETIC_FREEZE") if version not in predictions else None,
            "evidence_url": None,
            "source_provenance": "SYNTHETIC_ONLY",
        })

    return {
        "schema": "RACE_AI_FORECAST_AUDIT_V1",
        "dataset_status": "SYNTHETIC_ONLY",
        "event_date_jst": sorted({r["race_id"]["event_date_jst"] for r in latest.values()})[0] if latest else None,
        "note": "Simulated-only PR69 journal. No real results, no external freeze proof, no accuracy claim.",
        "records": rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Export synthetic immutable journal to read-only UI dataset")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    store = SyntheticJournal(args.db)
    try:
        value = export_synthetic_journal(store)
    finally:
        store.close()
    if args.out.exists():
        parser.error("Refusing to overwrite existing audit projection")
    args.out.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
