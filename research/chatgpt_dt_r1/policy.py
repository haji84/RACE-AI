"""Research selection policy; no wagers or source authentication.

Public dict APIs
---------------
``fixed_selection(forecast, k, market='trifecta')`` selects probability top-K,
preserving unknown retrospective clocks. Its policy hash includes K and market.
``select_tickets(forecast, odds_snapshot, config=None, decision_at=None)`` uses
the probability-top ticket frozen in the forecast as the odds-band anchor. Odds
must contain every candidate, with publication/capture clocks and a source SHA.
Missing/late/partial odds return HOLD; malformed forecasts raise ValueError.
Config keys: market, min_marginal_probability, min_expected_net_per_unit,
target_coverage, stake_per_ticket. Defaults never force the maximum ticket count.

Forecasts contain race_id/day/model_id/model_sha256/input_sha256/cohort,
prediction_at/cutoff_at/status and complete trifectas/exactas distributions of
{cars:[...], probability:float}. Exactas must be their trifecta marginal.
Retrospective clocks may both be null; prospective clocks must both be present.
Clocks and hashes are checked declarations, NOT independent source attestations.

Selection summaries preserve model/input/policy lineage, actual ticket count,
raw set coverage, expected monetary values at captured prices and HOLD confidence.
Probabilities are conditional on a unique normal finish (no dead heats); actual
incidents must remain in the separate all-target scorer whenever top-3 is valid.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from itertools import permutations
import json
import math
import re


RACE_TIMEZONE = timezone(timedelta(hours=9))


class PolicyError(ValueError):
    """A machine-readable contract failure, suitable for a HOLD reason."""


def require(ok, code):
    if not ok:
        raise PolicyError(code)


def finite_number(value, code="INVALID_NUMBER"):
    require(isinstance(value, (int, float)) and not isinstance(value, bool), code)
    require(math.isfinite(value), code)
    return float(value)


def probability(value, code="INVALID_PROBABILITY"):
    value = finite_number(value, code)
    require(0 <= value <= 1, code)
    return value


def checked_sha(value, code="INVALID_SHA256"):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, code)
    return value


def checked_day(value):
    require(isinstance(value, str), "INVALID_DAY")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise PolicyError("INVALID_DAY") from error
    require(parsed.isoformat() == value, "INVALID_DAY")
    return parsed


def clock(value):
    require(isinstance(value, str), "MISSING_CLOCK")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PolicyError("INVALID_CLOCK") from error
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "NAIVE_CLOCK")
    return parsed.astimezone(timezone.utc)


def check_race_day(day, cutoff_at):
    """KEIRIN's declared calendar day is the Japan-local cutoff date."""
    require(clock(cutoff_at).astimezone(RACE_TIMEZONE).date() == checked_day(day), "CUTOFF_RACE_DAY_MISMATCH")


def digest(value):
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PolicyError("NON_CANONICAL_JSON") from error
    return sha256(payload.encode("utf-8")).hexdigest()


def checked_cars(raw, length=None):
    require(isinstance(raw, (tuple, list)), "INVALID_TICKET")
    require(length is None or len(raw) == length, "INVALID_TICKET_LENGTH")
    require(all(isinstance(c, int) and not isinstance(c, bool) and 1 <= c <= 9 for c in raw), "INVALID_CAR")
    require(len(set(raw)) == len(raw), "DUPLICATE_CAR")
    return tuple(raw)


def _distribution(rows, size):
    require(isinstance(rows, list) and rows, "MISSING_DISTRIBUTION")
    values = {}
    for row in rows:
        require(isinstance(row, dict), "INVALID_TICKET_ROW")
        cars = checked_cars(row.get("cars"), size)
        require(cars not in values, "DUPLICATE_TICKET")
        values[cars] = probability(row.get("probability"))
    require(abs(math.fsum(values.values()) - 1) <= 1e-7, "PROBABILITY_MASS_NOT_ONE")
    return values


def validate_forecast(forecast):
    """Return checked, sorted distributions without altering the input dict."""
    require(isinstance(forecast, dict), "INVALID_FORECAST")
    for key in ("race_id", "model_id"):
        require(isinstance(forecast.get(key), str) and bool(forecast[key].strip()), "MISSING_" + key.upper())
    checked_day(forecast.get("day"))
    checked_sha(forecast.get("model_sha256"), "INVALID_MODEL_SHA256")
    checked_sha(forecast.get("input_sha256"), "INVALID_INPUT_SHA256")
    if forecast.get("input_schema_sha256") is not None:
        checked_sha(forecast["input_schema_sha256"], "INVALID_INPUT_SCHEMA_SHA256")
    cohort = forecast.get("cohort")
    require(cohort in ("retrospective", "prospective"), "INVALID_COHORT")
    status = str(forecast.get("status", "")).upper()
    require(status in {"READY", "OK", "FORECAST", "FORECASTED", "PREDICTED"}, "FORECAST_" + (status or "STATUS_MISSING"))
    prediction_at, cutoff_at = forecast.get("prediction_at"), forecast.get("cutoff_at")
    require((prediction_at is None) == (cutoff_at is None), "PARTIAL_FORECAST_CLOCKS")
    if cohort == "prospective":
        require(prediction_at is not None, "PROSPECTIVE_CLOCKS_REQUIRED")
    if prediction_at is not None:
        require(clock(prediction_at) < clock(cutoff_at), "PREDICTION_NOT_BEFORE_CUTOFF")
        check_race_day(forecast["day"], cutoff_at)
    trifectas = _distribution(forecast.get("trifectas"), 3)
    exactas = _distribution(forecast.get("exactas"), 2)
    cars = sorted(set(c for ticket in trifectas for c in ticket))
    require(3 <= len(cars) <= 9, "UNSUPPORTED_FIELD_SIZE")
    require(set(trifectas) == set(permutations(cars, 3)), "INCOMPLETE_TRIFECTA_DISTRIBUTION")
    require(set(exactas) == set(permutations(cars, 2)), "INCOMPLETE_EXACTA_DISTRIBUTION")
    require(forecast.get("field_size", len(cars)) == len(cars), "FIELD_SIZE_MISMATCH")
    marginal = defaultdict(float)
    for ticket, p in trifectas.items():
        marginal[ticket[:2]] += p
    require(all(abs(exactas[t] - p) <= 1e-7 for t, p in marginal.items()), "EXACTA_MARGINAL_MISMATCH")
    out = dict(forecast, field_size=len(cars), starters=cars)
    for name, values in (("trifectas", trifectas), ("exactas", exactas)):
        out[name] = [{"cars": list(t), "probability": p}
                     for t, p in sorted(values.items(), key=lambda item: (-item[1], item[0]))]
    return out


def ticket_cap(anchor_odds):
    """Owner bands: <=10:2; (10,20]:4; (20,100):9; >=100:12."""
    value = finite_number(anchor_odds, "INVALID_ODDS")
    require(value > 0, "INVALID_ODDS")
    if value <= 10:
        return 2
    if value <= 20:
        return 4
    return 9 if value < 100 else 12


def odds_band(value):
    cap = ticket_cap(value)
    return {2: "<=10", 4: "(10,20]", 9: "(20,100)", 12: ">=100"}[cap]


def _selection_base(forecast, market, policy):
    keys = ("race_id", "day", "model_id", "model_sha256", "input_sha256", "input_schema_sha256",
            "prediction_at", "cutoff_at", "cohort", "field_size", "class", "venue")
    return {
        **{key: forecast.get(key) for key in keys}, "market": market,
        "policy": policy, "policy_sha256": digest(policy), "status": "HOLD", "confidence": "HOLD",
        "selected_tickets": [], "ticket_count": 0, "raw_coverage": 0.0,
        "expected_gross": None, "expected_net": None, "total_stake": 0.0,
        "hold_reasons": [], "conditional_distribution": True,
        "conditional_distribution_caveat": "Unique normal finish only; no dead-heat or abnormal-completion mass is modelled.",
        "source_attested": False,
    }


def _seal(selection):
    return dict(selection, selection_sha256=digest(selection))


def fixed_selection(forecast, k, market="trifecta"):
    """Fixed-K research selection; requires no historical odds or invented clocks."""
    require(market in ("trifecta", "exacta"), "INVALID_MARKET")
    require(isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= (12 if market == "trifecta" else 2), "INVALID_K")
    f = validate_forecast(forecast)
    policy = {"version": "dt-r1-fixed-k-v1", "market": market, "k": k, "tie_break": "cars_ascending"}
    out = _selection_base(f, market, policy)
    tickets = f[market + "s"][:k]
    out.update(status="SELECTED", selected_tickets=tickets, ticket_count=len(tickets), requested_k=k,
               raw_coverage=min(1.0, math.fsum(t["probability"] for t in tickets)),
               cap=k, anchor_ticket=f[market + "s"][0]["cars"], anchor_fixed_at=f.get("prediction_at"),
               odds_band=None, anchor_odds=None, decision_at=f.get("prediction_at"),
               total_stake=100.0 * len(tickets), stake_per_ticket=100.0,
               price_risk="No odds supplied; expected or realised return is not inferred.")
    return _seal(out)


def _config(config):
    out = {"market": "trifecta", "min_marginal_probability": .01, "min_expected_net_per_unit": 0.0,
           "target_coverage": 1.0, "stake_per_ticket": 100.0}
    if config is not None:
        require(isinstance(config, dict) and set(config) <= set(out), "INVALID_POLICY_CONFIG")
        out.update(config)
    require(out["market"] in ("trifecta", "exacta"), "INVALID_MARKET")
    out["min_marginal_probability"] = probability(out["min_marginal_probability"])
    out["target_coverage"] = probability(out["target_coverage"])
    require(out["target_coverage"] > 0, "INVALID_TARGET_COVERAGE")
    out["min_expected_net_per_unit"] = finite_number(out["min_expected_net_per_unit"])
    require(out["min_expected_net_per_unit"] >= -1, "INVALID_EV_THRESHOLD")
    out["stake_per_ticket"] = finite_number(out["stake_per_ticket"])
    require(out["stake_per_ticket"] > 0, "INVALID_STAKE")
    return out


def select_tickets(forecast, odds_snapshot, *, config=None, decision_at=None):
    """Select probability-ranked candidates that pass marginal-probability/EV gates.

    All candidates need valid odds; partial-market snapshots return HOLD. Expected
    gross = sum(p * captured_odds * stake), expected net subtracts the FULL stake.
    Neither quantity is calibrated confidence or a promise of final payout.
    """
    f = validate_forecast(forecast)
    cfg = _config(config)
    market = cfg["market"]
    policy = {"version": "dt-r1-odds-policy-v1", "anchor": "frozen_probability_top_ticket",
              "tie_break": "cars_ascending", **cfg}
    out = _selection_base(f, market, policy)
    # The anchor is fixed from probability order, before any odds are inspected.
    ranked = f[market + "s"]
    anchor = tuple(ranked[0]["cars"])
    out.update(anchor_ticket=list(anchor), anchor_fixed_at=f.get("prediction_at"), cap=None,
               anchor_odds=None, odds_band=None, decision_at=decision_at,
               stake_per_ticket=cfg["stake_per_ticket"])
    try:
        require(isinstance(odds_snapshot, dict), "MISSING_ODDS")
        require(f.get("prediction_at") is not None, "ODDS_POLICY_FORECAST_CLOCKS_REQUIRED")
        decision = clock(decision_at)
        require(clock(f["prediction_at"]) <= decision < clock(f["cutoff_at"]), "DECISION_NOT_BEFORE_CUTOFF")
        require(odds_snapshot.get("race_id") == f["race_id"], "ODDS_RACE_MISMATCH")
        require(odds_snapshot.get("market") == market, "ODDS_MARKET_MISMATCH")
        require(odds_snapshot.get("complete") is True, "PARTIAL_ODDS")
        checked_sha(odds_snapshot.get("source_sha256"), "ODDS_SOURCE_SHA_REQUIRED")
        require(isinstance(odds_snapshot.get("source"), str) and bool(odds_snapshot["source"].strip()), "ODDS_SOURCE_REQUIRED")
        published, captured = clock(odds_snapshot.get("published_at")), clock(odds_snapshot.get("captured_at"))
        require(published <= captured <= decision, "ODDS_CLOCK_ORDER")
        require(clock(f["prediction_at"]) <= captured, "ANCHOR_NOT_FIXED_BEFORE_ODDS_USE")
        if f.get("anchor_ticket") is not None:
            require(checked_cars(f["anchor_ticket"], len(anchor)) == anchor, "ANCHOR_MISMATCH")
        if f.get("anchor_fixed_at") is not None:
            require(clock(f["anchor_fixed_at"]) == clock(f["prediction_at"]), "ANCHOR_CLOCK_MISMATCH")
        prices = {}
        require(isinstance(odds_snapshot.get("tickets"), list), "MISSING_ODDS_TICKETS")
        for row in odds_snapshot["tickets"]:
            require(isinstance(row, dict), "INVALID_ODDS_ROW")
            cars = checked_cars(row.get("cars"), len(anchor))
            require(cars not in prices, "DUPLICATE_ODDS_TICKET")
            value = finite_number(row.get("odds"), "INVALID_ODDS")
            require(value > 0, "INVALID_ODDS")
            prices[cars] = value
        require(set(prices) == {tuple(t["cars"]) for t in ranked}, "PARTIAL_OR_EXTRA_ODDS")
        anchor_price = prices[anchor]
        cap = ticket_cap(anchor_price) if market == "trifecta" else 2
        out.update(cap=cap, anchor_odds=anchor_price, odds_band=odds_band(anchor_price),
                   odds_published_at=odds_snapshot["published_at"], odds_captured_at=odds_snapshot["captured_at"],
                   odds_source=odds_snapshot["source"], odds_source_sha256=odds_snapshot["source_sha256"])
        chosen = []
        coverage = 0.0
        stake = cfg["stake_per_ticket"]
        for row in ranked:
            p, price = row["probability"], prices[tuple(row["cars"])]
            net_per_unit = p * price - 1
            if p < cfg["min_marginal_probability"] or net_per_unit < cfg["min_expected_net_per_unit"]:
                continue
            chosen.append({**row, "odds": price, "stake": stake,
                           "expected_gross": p * price * stake, "expected_net": net_per_unit * stake})
            coverage += p
            if len(chosen) >= cap or coverage >= cfg["target_coverage"]:
                break
        require(bool(chosen), "NO_CANDIDATE_PASSES_MARGINAL_GATES")
        total_stake = stake * len(chosen)
        expected_gross = math.fsum(t["expected_gross"] for t in chosen)
        out.update(status="SELECTED", selected_tickets=chosen, ticket_count=len(chosen),
                   raw_coverage=min(1.0, math.fsum(t["probability"] for t in chosen)), total_stake=total_stake,
                   expected_gross=expected_gross, expected_net=expected_gross - total_stake,
                   hit_returns_at_captured_odds=[{"cars": t["cars"], "gross": t["odds"] * stake,
                                                  "net_after_all_stakes": t["odds"] * stake - total_stake}
                                                 for t in chosen],
                   price_risk="Captured odds may change; conditional model expectation is not a guaranteed return.")
    except (PolicyError, KeyError, TypeError) as error:
        out["hold_reasons"] = [str(error) if isinstance(error, PolicyError) else "INVALID_ODDS_SNAPSHOT"]
    return _seal(out)
