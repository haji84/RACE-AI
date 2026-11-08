"""Offline KEIRIN variable-pick research selector and immutable local comparison.

No odds enter the underlying PR71 model. All expected values are hypotheses
until calibrated on genuine pre-cutoff forecasts. Never place bets or overwrite
the existing eight-ticket private forecast contract.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from itertools import permutations
from pathlib import Path
import json
import math
import os

from .comprehensive_four_sport_models import digest
from .four_sport_model_suite import verify_suite

SCHEMA = "RACE_AI_KEIRIN_VARIABLE_SELECTION_V1"
AUDIT_SCHEMA = "RACE_AI_KEIRIN_VARIABLE_SELECTION_AUDIT_V1"
ODDS_SCHEMA = "RACE_AI_KEIRIN_TRIFECTA_ODDS_SNAPSHOT_V1"
# Research heuristic, NOT a fitted volatility threshold.
WIDE_EFFECTIVE_OUTCOMES_THRESHOLD = 25.0
STAKE_YEN = 100


class VariableSelectionError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise VariableSelectionError(code)


def instant(value):
    require(type(value) is str, "AWARE_TIMESTAMP_REQUIRED")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(t.utcoffset() is not None, "AWARE_TIMESTAMP_REQUIRED")
        return t.astimezone(timezone.utc)
    except ValueError as exc:
        raise VariableSelectionError("INVALID_TIMESTAMP") from exc


def ticket(value, starters):
    require(type(value) is list and len(value) == 3
            and all(type(n) is int and n in starters for n in value)
            and len(set(value)) == 3, "INVALID_TRIFECTA")
    return tuple(value)


def number(value, *, minimum=0.0):
    require(type(value) in (int, float) and math.isfinite(value)
            and value >= minimum, "INVALID_FINITE_NUMBER")
    return float(value)


def seal(record):
    return sha256(json.dumps(record, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _verified_document(document, schema):
    require(type(document) is dict and document.get("schema") == schema,
            "INVALID_DOCUMENT_SCHEMA")
    proof = document.get("document_sha256")
    require(type(proof) is str and len(proof) == 64 and
            proof == seal({k: v for k, v in document.items()
                           if k != "document_sha256"}),
            "DOCUMENT_HASH_MISMATCH")
    return document


def select_research_tickets(suite, model_id, odds_snapshot, *,
                            decision_at, source_admission=None):
    """Research selection: concentrated max8, dispersed max12, zero if no edge.

    Per-ticket hypothetical edge is independent model P * decimal gross odds - 1.
    Fixed 100-yen reference stakes target hypothetical expected yen gain, not
    maximum basket ROI. This does NOT establish profitability.
    """
    require(verify_suite(suite) is True and suite.get("sport") == "keirin",
            "VERIFIED_KEIRIN_RESEARCH_SUITE_REQUIRED")
    models = suite["models"]
    require(type(model_id) is str and model_id in models,
            "MODEL_ID_NOT_IN_VERIFIED_SUITE")
    model = models[model_id]
    require(model.get("odds_independent") is True and
            model.get("official_prediction") is False,
            "RESEARCH_MODEL_CONTRACT_REJECTED")
    cutoff = instant(suite["sales_cutoff_at"])
    issued = instant(decision_at)
    captured = instant(suite["as_of"])
    require(captured <= issued < cutoff, "DECISION_NOT_PRE_CUTOFF")
    require(type(odds_snapshot) is dict
            and set(odds_snapshot) == {
                "schema", "race_id", "captured_at", "source_ref",
                "source_rights_ref", "prices"}
            and odds_snapshot["schema"] == ODDS_SCHEMA
            and odds_snapshot["race_id"] == suite["race_id"]
            and type(odds_snapshot["source_ref"]) is str
            and bool(odds_snapshot["source_ref"])
            and type(odds_snapshot["source_rights_ref"]) is str
            and bool(odds_snapshot["source_rights_ref"]),
            "ODDS_PROVENANCE_REQUIRED")
    odds_at = instant(odds_snapshot["captured_at"])
    require(captured <= odds_at <= issued < cutoff, "ODDS_AFTER_DECISION_OR_CUTOFF")
    if suite.get("scope") != "SYNTHETIC_ONLY":
        require(callable(source_admission)
                and source_admission(
                    odds_snapshot["source_ref"],
                    odds_snapshot["source_rights_ref"],
                    "private_odds_research") is True,
                "ODDS_SOURCE_ADMISSION_REQUIRED")

    candidates = model.get("candidates")
    require(type(candidates) is list
            and len(candidates) == model.get("candidate_count")
            and 6 <= len(candidates) <= 504,
            "FULL_DISTRIBUTION_REQUIRED")
    require(all(type(row) is dict and type(row.get("combination")) is list
                for row in candidates), "INVALID_MODEL_CANDIDATE")
    starters = sorted({n for row in candidates
                       for n in row["combination"] if type(n) is int})
    require(3 <= len(starters) <= 9 and all(1 <= n <= 9 for n in starters),
            "INVALID_STARTERS")
    universe = set(permutations(starters, 3))
    require(len(universe) == len(candidates), "INCOMPLETE_TRIFECTA_UNIVERSE")
    p_by_ticket = {}
    for row in candidates:
        require(set(row) == {"combination", "score"},
                "INVALID_MODEL_CANDIDATE")
        t = ticket(row["combination"], starters)
        require(t not in p_by_ticket, "DUPLICATE_MODEL_COMBINATION")
        p_by_ticket[t] = number(row["score"])
    require(set(p_by_ticket) == universe
            and math.isclose(math.fsum(p_by_ticket.values()), 1.0,
                             rel_tol=0, abs_tol=1e-7),
            "MODEL_PROBABILITY_MASS_INVALID")
    effective = 1.0 / math.fsum(p*p for p in p_by_ticket.values())
    wide = effective > WIDE_EFFECTIVE_OUTCOMES_THRESHOLD
    cap = 12 if wide else 8
    prices = odds_snapshot["prices"]
    require(type(prices) is list and 0 < len(prices) <= len(universe),
            "ODDS_PRICES_REQUIRED")
    odds_by_ticket = {}
    for row in prices:
        require(type(row) is dict and set(row) == {
            "triple", "decimal_odds"}, "INVALID_ODDS_ROW")
        t = ticket(row["triple"], starters)
        require(t not in odds_by_ticket, "DUPLICATE_ODDS_ROW")
        odd = number(row["decimal_odds"], minimum=1.000000001)
        require(odd <= 1_000_000, "ODDS_OUT_OF_SCOPE")
        odds_by_ticket[t] = odd

    edges = sorted(((p_by_ticket[t] * o - 1.0, p_by_ticket[t], t, o)
                    for t, o in odds_by_ticket.items()
                    if p_by_ticket[t] * o > 1.0 + 1e-10),
                   key=lambda row: (-row[0], -row[1], row[2]))
    chosen = edges[:cap]
    rows = [
        {"triple": list(t), "reference_stake_yen": STAKE_YEN,
         "model_probability_hypothesis": p,
         "odds_decimal_as_of": odd,
         "hypothetical_expected_return_multiplier": p*odd,
         "hypothetical_expected_net_yen": STAKE_YEN*edge}
        for edge, p, t, odd in chosen
    ]
    record = {
        "schema": SCHEMA,
        "race_id": suite["race_id"],
        "model_id": model_id,
        "model_version": model["model_version"],
        "model_prediction_sha256": model["prediction_sha256"],
        "suite_sha256": suite["suite_sha256"],
        "odds_snapshot_sha256": digest(odds_snapshot),
        "odds_source_ref": odds_snapshot["source_ref"],
        "odds_captured_at": odds_snapshot["captured_at"],
        "forecast_as_of": suite["as_of"],
        "selection_at": decision_at,
        "official_cutoff_at": suite["sales_cutoff_at"],
        "selection_method": "positive_hypothetical_edge_fixed_100yen_v1",
        "dispersion_assessment": "WIDE_HEURISTIC" if wide else "FOCUSED_HEURISTIC",
        "effective_outcomes_hypothesis": effective,
        "pre_cutoff_odds_rows": len(odds_by_ticket),
        "max_picks": cap, "pick_count": len(rows),
        "tickets": rows,
        "reference_investment_yen": STAKE_YEN*len(rows),
        "hypothetical_hit_probability": math.fsum(r["model_probability_hypothesis"]
                                                  for r in rows),
        "hypothetical_expected_net_yen": math.fsum(
            r["hypothetical_expected_net_yen"] for r in rows),
        "hypothetical_expected_roi": (
            math.fsum(r["hypothetical_expected_return_multiplier"]
                      for r in rows)/len(rows)-1.0 if rows else None),
        "research_status": ("SELECTED_UNVERIFIED_RESEARCH" if rows
                            else "SKIP_NO_POSITIVE_HYPOTHETICAL_EDGE"),
        "model_calibrated": model.get("calibrated") is True,
        "model_accuracy_independently_verified": False,
        "official_pre_cutoff_witness_verified": False,
        "formal_kpi": None,
        "actual_purchase_placed": False,
        "real_money_recommendation": "NO_BET_UNVERIFIED",
    }
    record["document_sha256"] = seal(record)
    return record


def evaluate_settled_result(selection, result, *, revision):
    """Research-only settlement, preserving result revisions separately."""
    _verified_document(selection, SCHEMA)
    require(type(revision) is int and revision >= 1, "REVISION_REQUIRED")
    require(type(result) is dict
            and result.get("race_id") == selection["race_id"]
            and type(result.get("observed_at")) is str
            and instant(result["observed_at"]) >= instant(
                selection["official_cutoff_at"]),
            "RESULT_RACE_OR_TIME_MISMATCH")
    status, refund = result.get("status"), result.get("refund_status")
    settled = status == "FINAL_NORMAL" and refund == "NONE"
    audit = {
        "schema": AUDIT_SCHEMA,
        "race_id": selection["race_id"],
        "model_id": selection["model_id"],
        "selection_sha256": selection["document_sha256"],
        "result_sha256": digest(result),
        "result_revision": revision,
        "result_auth_independently_verified": False,
        "formal_kpi": None,
        "research_hit": None,
        "reference_investment_yen": selection["reference_investment_yen"],
        "reference_payout_yen": None,
        "reference_profit_yen": None,
        "reference_roi": None,
        "status": "PENDING_OR_REFUND" if not settled else "SETTLED_RESEARCH",
    }
    if settled:
        starters = list(range(1, 10))
        winners, payouts = result.get("winning_triples"), result.get("payouts_100yen")
        require(type(winners) is list and type(payouts) is list
                and len(winners) > 0 and len(winners) == len(payouts),
                "FINAL_PAYOUT_EVIDENCE_REQUIRED")
        winning = [ticket(w, starters) for w in winners]
        require(len(set(winning)) == len(winning), "DUPLICATE_WINNER")
        payout_map = {}
        for row in payouts:
            require(type(row) is dict and set(row) == {"triple", "yen"}
                    and type(row["yen"]) is int and row["yen"] > 0,
                    "INVALID_SETTLED_PAYOUT")
            t = ticket(row["triple"], starters)
            require(t not in payout_map, "DUPLICATE_PAYOUT")
            payout_map[t] = row["yen"]
        require(set(payout_map) == set(winning), "WIN_PAYOUT_MISMATCH")
        if selection["pick_count"] > 0:
            stake_map = {tuple(row["triple"]): row["reference_stake_yen"]
                         for row in selection["tickets"]}
            payout = sum(payout_map.get(t, 0)*stake//100
                         for t, stake in stake_map.items())
            invest = selection["reference_investment_yen"]
            audit["research_hit"] = bool(set(stake_map) & set(winning))
            audit["reference_payout_yen"] = payout
            audit["reference_profit_yen"] = payout - invest
            audit["reference_roi"] = payout/invest
        else:
            audit["status"] = "SETTLED_SKIPPED_RESEARCH"
    audit["document_sha256"] = seal(audit)
    return audit


def aggregate_latest_audits(audits):
    """Do not double-count revisions or turn missing/skip into a loss."""
    require(type(audits) is list, "AUDIT_LIST_REQUIRED")
    seen = set()
    invested = paid = wins = tested = skipped = unresolved = 0
    for item in audits:
        _verified_document(item, AUDIT_SCHEMA)
        key = (item["race_id"], item["model_id"])
        require(key not in seen, "DUPLICATE_RACE_MODEL_REVISION")
        seen.add(key)
        if item["status"] == "SETTLED_RESEARCH":
            require(type(item["reference_payout_yen"]) is int
                    and type(item["reference_investment_yen"]) is int
                    and item["reference_investment_yen"] > 0,
                    "INVALID_SETTLED_AUDIT")
            invested += item["reference_investment_yen"]
            paid += item["reference_payout_yen"]
            wins += int(item["research_hit"] is True)
            tested += 1
        elif item["status"] == "SETTLED_SKIPPED_RESEARCH":
            skipped += 1
        else:
            unresolved += 1
    return {"schema": "RACE_AI_KEIRIN_VARIABLE_RESEARCH_AGGREGATE_V1",
            "settled_prediction_count": tested, "wins": wins,
            "hit_rate": wins/tested if tested else None,
            "reference_investment_yen": invested,
            "reference_payout_yen": paid,
            "reference_profit_yen": paid-invested,
            "reference_roi": paid/invested if invested else None,
            "skipped": skipped, "unresolved_or_refunded": unresolved,
            "formal_hit_rate": None, "actual_purchase_profit": None}


def read_private_document(path, *, schema):
    """Owner-local plaintext, never publish in GitHub."""
    file = Path(path)
    require(file.is_absolute() and file.is_file() and not file.is_symlink(),
            "PRIVATE_FILE_REQUIRED")
    require(file.stat().st_size <= 1_000_000, "PRIVATE_FILE_TOO_LARGE")
    return _verified_document(json.loads(file.read_text(encoding="utf-8")),
                              schema)


def freeze_private_document_once(path, document, *, schema):
    """Exclusive 0600 file creation, identical replay allowed; never overwrite."""
    _verified_document(document, schema)
    file = Path(path)
    require(file.is_absolute() and not file.is_symlink(),
            "ABSOLUTE_OWNER_PRIVATE_PATH_REQUIRED")
    parent = file.parent
    require(not parent.is_symlink()
            and not parent.resolve().is_relative_to(Path.cwd().resolve()),
            "PUBLIC_WORKTREE_STORAGE_REFUSED")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = (json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)+"\n").encode("utf-8")
    require(len(raw) <= 1_000_000, "DOCUMENT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(file, flags, 0o600)
    except FileExistsError:
        previous = read_private_document(file, schema=schema)
        require(previous == document, "IMMUTABLE_DOCUMENT_CONFLICT")
        return {"state": "ALREADY_SAVED_IDENTICAL",
                "document_sha256": document["document_sha256"]}
    with os.fdopen(handle, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    previous = read_private_document(file, schema=schema)
    require(previous == document, "PRIVATE_READBACK_FAILED")
    return {"state": "CREATED_AND_READ_BACK",
            "document_sha256": document["document_sha256"]}
