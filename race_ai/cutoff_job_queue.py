"""Pre-cutoff, all-sport queue planning using only known race-ledger facts.

No source collection, model inference, or dispatch is performed here.
Missing or unverified cutoff data is a reason for *not* claiming prediction.
"""
from datetime import datetime
import json
from pathlib import Path


class QueueError(ValueError):
    pass


def _utc(stamp):
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("naive")
        return dt.timestamp()
    except (TypeError, AttributeError, ValueError) as exc:
        raise QueueError("timezone-aware clock required") from exc


def plan(records, *, now):
    when = _utc(now)
    keys, jobs = set(), []
    for row in records:
        key = row.get("race_id")
        if not isinstance(key, str) or not key or key in keys:
            raise QueueError("race identity missing or duplicate")
        keys.add(key)
        stamp = row.get("cutoff_at")
        cutoff = _utc(stamp) if stamp else None
        if cutoff is None:
            reason = "SALES_CUTOFF_NOT_DISCOVERED"
        elif row.get("cutoff_verified") is not True:
            reason = "SALES_CUTOFF_UNVERIFIED"
        elif cutoff <= when:
            reason = "MISSED_DEADLINE"
        elif row.get("source_permission_approved") is not True:
            reason = "SOURCE_PERMISSION_NOT_ADMITTED"
        elif row.get("prediction") is not None:
            reason = "FORECAST_PRESENT_CHECK_RECEIPT"
        else:
            reason = "READY_FOR_AUTHORIZED_INPUT_AND_MODEL"
        jobs.append({
            "race_id": key,
            "sport": row.get("sport"),
            "venue": row.get("venue"),
            "race_no": row.get("race_no"),
            "cutoff_at": stamp,
            "state": reason,
            "forecast_generated": False,
            "forecast_frozen": False,
        })
    # All known cutoff timestamps are ordered together across sports.
    # Missing cutoff events are kept, at the end, not silently dropped.
    jobs.sort(key=lambda x: (_utc(x["cutoff_at"]) if x["cutoff_at"]
                              else float("inf"),x["race_id"]))
    return {
        "schema": "RACE_AI_PREDICTION_QUEUE_AUDIT_V1",
        "run_as_of": now,
        "all_known_races": len(jobs),
        "race_count_verified_complete": False,
        "jobs": jobs,
    }


def from_audit_file(input_path, *, now):
    source = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if source.get("schema") != "RACE_AI_FORECAST_AUDIT_V1":
        raise QueueError("unsupported audit input")
    return plan(source["records"], now=now)
