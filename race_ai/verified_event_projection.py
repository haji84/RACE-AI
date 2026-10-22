"""Fail-closed, offline bridge from externally attested source events to audit UI.

This module NEVER fetches upstream sources, mints a rights grant, signs a
timestamp, or changes an original prediction. Caller-provided verifiers must
validate distinct external authorities. Default verifiers grant NOTHING.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import itertools
import json
import math
import re

SPORTS = {"boat", "keirin", "autorace", "horse"}
SCHEMA = "RACE_AI_VERIFIED_EVENT_BUNDLE_V1"
OUTPUT_SCHEMA = "RACE_AI_FORECAST_AUDIT_V1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")

class AdmissionError(ValueError):
    """Invalid evidence; the integration must not call a provider as fallback."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc(value):
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise AdmissionError("timezone-aware complete timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.utcoffset() is None:
            raise ValueError("naive timestamp")
        return dt.timestamp()
    except (ValueError, OverflowError) as exc:
        raise AdmissionError("invalid timestamp") from exc


def ticket(candidate):
    if (not isinstance(candidate, list) or len(candidate) != 3
        or any(type(x) is not int or x < 1 or x > 99 for x in candidate)
        or len(set(candidate)) != 3):
        raise AdmissionError("invalid ordered trifecta")
    return tuple(candidate)


def validate_market_isolation(value):
    forbidden = {"odds", "payout", "popularity", "rank_market",
                 "market_implied_win_probability", "market_probability"}
    def visit(node):
        if isinstance(node, dict):
            if any(any(x in str(k).lower() for x in forbidden) for k in node):
                raise AdmissionError("market-derived field in prediction input")
            for item in node.values():
                visit(item)
        elif isinstance(node, list):
            for item in node:
                visit(item)
    visit(value)


def validate_universe(forecast, entrants):
    """Require all N*(N-1)*(N-2) distinct ordered outcomes and a stable top8."""
    if not isinstance(forecast, dict):
        raise AdmissionError("prediction payload required")
    validate_market_isolation({k: v for k, v in forecast.items()
                              if k not in {"odds_independent"}})
    candidates = forecast.get("candidates")
    if not isinstance(candidates, list):
        raise AdmissionError("complete candidate universe required")
    full = set(itertools.permutations(entrants, 3))
    if len(candidates) != len(full):
        raise AdmissionError("incomplete three-place outcome universe")
    seen = set()
    normalized = []
    for item in candidates:
        if not isinstance(item, dict) or set(item) != {"combination", "score"}:
            raise AdmissionError("candidate schema invalid")
        combo = ticket(item["combination"])
        if combo not in full or combo in seen:
            raise AdmissionError("candidate duplicate or entrant mismatch")
        seen.add(combo)
        score = item["score"]
        if type(score) not in (int, float) or not math.isfinite(score) or score < 0:
            raise AdmissionError("invalid prediction score")
        normalized.append((combo, float(score)))
    if seen != full:
        raise AdmissionError("missing candidate")
    if not math.isclose(math.fsum(score for _, score in normalized), 1.0,
                        rel_tol=0, abs_tol=1e-6):
        raise AdmissionError("outcome probabilities must sum to one")
    normalized.sort(key=lambda row: (-row[1], row[0]))
    recommended = [list(combo) for combo, _ in normalized[:8]]
    if forecast.get("ordered_top8") != recommended:
        raise AdmissionError("top8 differs from complete odds-free ranking")
    if forecast.get("odds_independent") is not True:
        raise AdmissionError("market independence not asserted")
    return recommended


def project(bundle, *, allow_source=None, verify_freeze=None, verify_result=None):
    """Build read-only UI projection. No unverified source may enter scoring.

    allow_source(source, purpose) -> bool: independently admitted rights for
       the specific source and display/analysis purpose, not a payload flag.
    verify_freeze(receipt, content_hash, persisted_at, cutoff_at) -> bool: trusted
       service signed receipt, tested beyond any mutable local clock.
    verify_result(result, source) -> bool: independently checked official
       source and revision. All callbacks default DENY.
    """
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise AdmissionError("event bundle schema unsupported")
    if bundle.get("classification") != "REAL_REPORTED":
        raise AdmissionError("real reported event bundle required")
    races = bundle.get("races")
    if not isinstance(races, list) or len(races) > 10000:
        raise AdmissionError("invalid race count")
    rows, used = [], set()
    for entry in races:
        if not isinstance(entry, dict):
            raise AdmissionError("race event invalid")
        required = {"race_id", "sport", "venue", "race_no", "cutoff_at",
                    "event_date_jst", "entrants", "source", "trifecta_offered"}
        if not required.issubset(entry):
            raise AdmissionError("race identity incomplete")
        race_id = entry["race_id"]
        if (not isinstance(race_id, str) or not race_id or race_id in used
            or len(race_id) > 250):
            raise AdmissionError("duplicate/invalid race id")
        used.add(race_id)
        if entry["sport"] not in SPORTS:
            raise AdmissionError("unknown sport")
        if not isinstance(entry["venue"], str) or not entry["venue"]:
            raise AdmissionError("venue required")
        if type(entry["race_no"]) is not int or not 1 <= entry["race_no"] <= 99:
            raise AdmissionError("race number invalid")
        day = entry["event_date_jst"]
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
            raise AdmissionError("event day invalid")
        if not isinstance(entry["trifecta_offered"], bool):
            raise AdmissionError("offering must be explicit boolean")
        deadline = utc(entry["cutoff_at"])
        entrants = entry["entrants"]
        if (not isinstance(entrants, list) or not 3 <= len(entrants) <= 18
            or any(type(e) is not int or not 1 <= e <= 99 for e in entrants)
            or len(set(entrants)) != len(entrants)):
            raise AdmissionError("entrants invalid")

        source = entry["source"]
        if not isinstance(source, dict) or not str(source.get("url", "")).startswith("https://"):
            raise AdmissionError("source URL missing")
        allowed = bool(allow_source is not None and
                       allow_source(source, "analysis") and
                       allow_source(source, "derived_display"))
        row = {
            "race_id": race_id, "sport": entry["sport"],
            "venue": entry["venue"], "race_no": entry["race_no"],
            "event_date_jst": day, "cutoff_at": entry["cutoff_at"],
            "offering_status": "TRIFECTA_OFFERED" if allowed and entry["trifecta_offered"]
                               else "NOT_OFFERED" if allowed else "UNKNOWN",
            "race_status": "source_admitted" if allowed else "source_blocked",
            "prediction": None, "result": None, "no_forecast_reason": None,
            "evidence_url": source["url"] if allowed and "?" not in source["url"] and "@" not in source["url"].split("/")[2] else None,
            "source_provenance": "SOURCE_ADMITTED" if allowed else "RIGHTS_NOT_ADMITTED"
        }
        if not allowed:
            row["no_forecast_reason"] = "SOURCE_RIGHTS_NOT_VERIFIED"
            rows.append(row)
            continue

        forecast = entry.get("forecast")
        if forecast is not None:
            selected = validate_universe(forecast, entrants)
            at = utc(forecast.get("generated_at"))
            stored = utc(forecast.get("persisted_at"))
            if not at <= stored < deadline or forecast.get("cutoff_at") != entry["cutoff_at"]:
                row["no_forecast_reason"] = "NOT_PERSISTED_BEFORE_OFFICIAL_CUTOFF"
            else:
                snapshot_hash = forecast.get("input_sha256")
                forecast_hash = forecast.get("prediction_sha256")
                recompute = {k: v for k, v in forecast.items()
                             if k != "prediction_sha256" and k != "receipt"}
                if not (isinstance(snapshot_hash, str) and HEX64.fullmatch(snapshot_hash)
                        and isinstance(forecast_hash, str)
                        and forecast_hash == digest(recompute)):
                    raise AdmissionError("forecast payload digest mismatch")
                valid_receipt = bool(verify_freeze is not None and
                                     verify_freeze(forecast.get("receipt"), forecast_hash,
                                                   forecast["persisted_at"], entry["cutoff_at"]))
                row["prediction"] = {
                    "ordered_top8": selected, "generated_at": forecast["generated_at"],
                    "persisted_at": forecast["persisted_at"],
                    "cutoff_at": forecast["cutoff_at"],
                    "input_sha256": snapshot_hash,
                    "prediction_sha256": forecast_hash,
                    "model_version": str(forecast.get("model_version", "unvalidated")),
                    "model_id": str(forecast.get("model_id", "unknown")),
                    "rationale": str(forecast.get("rationale", "reason unavailable"))[:500],
                    "odds_independent": True,
                    "external_receipt_verified": valid_receipt,
                }
                if not valid_receipt:
                    row["no_forecast_reason"] = "EXTERNAL_FREEZE_RECEIPT_NOT_VERIFIED"
        else:
            row["no_forecast_reason"] = "NO_PRIOR_FORECAST"

        results = entry.get("result_revisions", [])
        if not isinstance(results, list) or len(results) > 100:
            raise AdmissionError("official result revisions invalid")
        recorded = []
        for n, res in enumerate(results, start=1):
            if not isinstance(res, dict) or res.get("revision_no") != n:
                raise AdmissionError("result revision out of sequence")
            if res.get("status") not in {"final", "void", "pending", "unsupported"}:
                raise AdmissionError("result status invalid")
            if utc(res.get("confirmed_at")) < deadline:
                raise AdmissionError("result timestamp precedes cutoff")
            winners = res.get("winning_combinations", [])
            if (not isinstance(winners, list) or
                any(ticket(c) not in set(itertools.permutations(entrants, 3))
                    for c in winners) or
                (res["status"] == "final") != bool(winners)):
                raise AdmissionError("official settlement invalid")
            payout = res.get("payout_yen_per_100")
            if payout is not None and (type(payout) is not int or payout < 0):
                raise AdmissionError("invalid payout")
            if verify_result is None or not verify_result(res, source):
                row["no_forecast_reason"] = row["no_forecast_reason"] or "RESULT_SOURCE_UNVERIFIED"
                recorded = []
                break
            recorded.append({
                "revision_no": n, "status": res["status"],
                "winning_combinations": winners,
                "confirmed_at": res["confirmed_at"],
                "payout_yen_per_100": payout,
            })
        if recorded:
            row["result"] = {k: v for k, v in recorded[-1].items() if k != "revision_no"}
            row["result_revisions"] = recorded
        rows.append(row)
    return {"schema": OUTPUT_SCHEMA, "dataset_status": "REAL_REPORTED",
            "note": "External source, freeze and result verification are distinct; no browser-only authenticity claim.",
            "records": rows}
