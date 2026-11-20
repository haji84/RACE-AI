"""Automatically create A (published pre-race marks) and B (six-phase tactics).

This is a deterministic, untrained, source-bounded RESEARCH predictor.
It requires an owner-supplied pre-race snapshot and real source receipts;
it performs NO provider requests and does not assert an organizer-verified
cutoff or video-confirmed rider movement. No PR71 four-model dependency.

A and B are different algorithms: A orders all 3-ren-tan permutations
from pre-race published marks/strengths; B ranks distinct six-phase
tactical branches conditioned on line hypotheses and observed rider facts.
C is optional HOLD until independently reviewed past video labels exist.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from itertools import permutations
from math import isfinite
from urllib.parse import urlsplit
from . import keirin_rider_form_evidence as condition
import json
import re

SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_PRE_RACE_FACTS_V1"
PREDICTION = "RACE_AI_KEIRIN_AUTOMATIC_MARKS_AND_SIX_PHASE_V1"
MODEL_A = "marks-ordinal-plus-observed-rider-strength-v1"
MODEL_B = "line-tactical-six-phase-untrained-v1"
PHASES = ("INITIAL", "BELL", "FINAL_HOME", "FINAL_BACK", "FOURTH_CORNER", "GOAL")
STYLES = frozenset(("NIGE", "MAKURI", "SASHI", "MARK", "ALLROUND", "UNKNOWN"))
CLASSES = frozenset(("CHALLENGE", "A1_A2", "S", "GIRLS", "OTHER"))
VENUE = re.compile(r"^20[0-9]{10}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
RID = re.compile(r"^[0-9]{4,8}$")


class AutomaticForecastError(ValueError):
    pass


def need(condition, code):
    if not condition:
        raise AutomaticForecastError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def when(value):
    need(type(value) is str, "TIMEZONE_AWARE_SOURCE_CLOCK_REQUIRED")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AutomaticForecastError("SOURCE_CLOCK_INVALID") from None
    need(out.utcoffset() is not None, "TIMEZONE_AWARE_SOURCE_CLOCK_REQUIRED")
    return out.astimezone(timezone.utc)


def _url(value):
    need(type(value) is str and len(value) <= 2048,
         "SOURCE_URL_REQUIRED")
    try:
        u = urlsplit(value)
        good = (u.scheme == "https" and bool(u.hostname) and
                u.username is None and u.password is None and
                u.port is None and not u.fragment)
    except ValueError:
        good = False
    need(good, "SOURCE_URL_INVALID")
    return value


def validate_snapshot(snap, *, computed_at):
    """Check source facts, not independently establish a publisher's identity."""
    fields = {"schema", "race_id", "as_of", "published_cutoff_at",
              "cutoff_source", "source_pages", "competition", "round_stage",
              "round_rule", "line_groups", "riders"}
    need(type(snap) is dict and
         set(snap) in (fields, fields | {"condition_evidence"}) and
         snap.get("schema") == SCHEMA and
         type(snap.get("race_id")) is str and
         VENUE.fullmatch(snap["race_id"]) is not None,
         "PRE_RACE_SOURCE_SCHEMA_OR_ID_INVALID")
    rid = snap["race_id"]
    computed, asof, cutoff = (
        when(computed_at), when(snap["as_of"]),
        when(snap["published_cutoff_at"]))
    need(asof <= computed and (cutoff-computed).total_seconds() >= 65,
         "PREDICTION_AFTER_OR_TOO_CLOSE_TO_PUBLISHED_CUTOFF")
    need(type(snap["competition"]) is str and
         snap["competition"] in CLASSES and
         type(snap["round_stage"]) is str and
         1 <= len(snap["round_stage"]) <= 80,
         "RACE_CLASS_OR_ROUND_MISSING")
    rule = snap["round_rule"]
    need(rule is None or (type(rule) is dict and
         set(rule) == {"objective", "evidence_sha256"} and
         rule["objective"] in
            ("TITLE_WIN", "DIRECT_QUALIFY", "ALL_ADVANCE", "PLACEMENT_POINTS") and
         type(rule["evidence_sha256"]) is str and
         SHA.fullmatch(rule["evidence_sha256"])),
         "ROUND_RULE_MUST_BE_EVIDENCED_OR_UNKNOWN")
    receipt = snap["cutoff_source"]
    need(type(receipt) is dict and
         set(receipt) == {"url", "bytes_sha256", "captured_at"} and
         type(receipt["bytes_sha256"]) is str and
         SHA.fullmatch(receipt["bytes_sha256"]) and
         when(receipt["captured_at"]) <= asof,
         "CUT_OFF_SOURCE_RECEIPT_REQUIRED")
    _url(receipt["url"])
    pages = snap["source_pages"]
    need(type(pages) is list and 1 <= len(pages) <= 16,
         "SOURCE_PAGE_RECEIPTS_REQUIRED")
    roles = set()
    for row in pages:
        need(type(row) is dict and
             set(row) == {"kind", "url", "bytes_sha256", "captured_at"} and
             row["kind"] in ("RACECARD", "MARKS", "LINE", "PROGRAM") and
             type(row["bytes_sha256"]) is str and
             SHA.fullmatch(row["bytes_sha256"]) is not None and
             when(row["captured_at"]) <= asof,
             "SOURCE_PAGE_UNATTESTED_OR_AFTER_ASOF")
        _url(row["url"])
        roles.add(row["kind"])
    need({"RACECARD", "MARKS", "LINE"}.issubset(roles) or
         (snap["competition"] == "GIRLS" and
          {"RACECARD", "MARKS"}.issubset(roles)),
         "RACECARD_MARKS_AND_LINES_REQUIRED")
    riders = snap["riders"]
    need(type(riders) is list and 5 <= len(riders) <= 9,
         "FIVE_TO_NINE_STARTERS_REQUIRED")
    n = len(riders)
    seen_cars = set()
    athlete_ids = set()
    for row in riders:
        need(type(row) is dict and set(row) == {
            "car", "athlete_id", "mark_rank", "competition_points",
            "recent_form_score", "h_count", "b_count", "style"},
            "RIDER_FACTS_INCOMPLETE")
        car, athlete, mark = row["car"], row["athlete_id"], row["mark_rank"]
        # A source usually publishes only a few ◎○▲△ marks. An explicitly
        # unmarked rider is not an unobserved or invented numerical rank.
        marked = type(mark) is int and 1 <= mark <= n
        # A/B uses car numbers, not athlete-registration identities.
        # Some sources publish only provider-local player IDs. Never
        # manufacture an official ID. C keeps its independent ID gate.
        identity_known = type(athlete) is str and RID.fullmatch(athlete) is not None
        need(type(car) is int and 1 <= car <= 9 and car not in seen_cars and
             (athlete is None or identity_known) and
             (not identity_known or athlete not in athlete_ids) and
             (marked or mark == "UNMARKED"),
             "CAR_MARK_OR_PERSISTENT_RIDER_ID_DUPLICATE")
        need(type(row["competition_points"]) in (int, float) and
             isfinite(row["competition_points"]) and
             0 <= row["competition_points"] <= 150 and
             type(row["recent_form_score"]) in (int, float) and
             isfinite(row["recent_form_score"]) and
             0 <= row["recent_form_score"] <= 1 and
             type(row["h_count"]) is int and 0 <= row["h_count"] <= 99 and
             type(row["b_count"]) is int and 0 <= row["b_count"] <= 99 and
             row["style"] in STYLES,
             "RIDER_PRE_RACE_FEATURE_OUT_OF_BOUNDS")
        seen_cars.add(car)
        if identity_known:
            athlete_ids.add(athlete)
    lines = snap["line_groups"]
    need(type(lines) is list and 1 <= len(lines) <= n and
         all(type(g) is list and bool(g) and
             len(g) == len(set(g)) and
             all(type(c) is int for c in g) for g in lines),
         "PREDICTED_LINE_GROUPS_REQUIRED")
    all_members = sum(lines, [])
    need(set(all_members) == seen_cars and len(all_members) == n,
         "LINE_GROUPS_NOT_AN_EXACT_STARTER_PARTITION")
    need(snap["competition"] != "GIRLS" or
         all(len(g) == 1 for g in lines),
         "GIRLS_PERMANENT_LINE_NOT_VERIFIED")
    if "condition_evidence" in snap:
        try:
            condition.validate(
                snap["condition_evidence"], starters=seen_cars,
                source_pages=pages, as_of=snap["as_of"],
                target_race_id=rid)
        except condition.FormEvidenceError as exc:
            raise AutomaticForecastError(str(exc)) from None
    # Never promote the input to an organizer- or model-verified forecast.
    return snap


def _strengths(riders, *, condition_adjustments=None):
    n = len(riders)
    lo = min(r["competition_points"] for r in riders)
    hi = max(r["competition_points"] for r in riders)
    span = hi - lo
    power = {}
    for r in riders:
        # Uncalibrated research score. No made-up missing source features.
        mark = ((n + 1 - r["mark_rank"]) / n
                if type(r["mark_rank"]) is int else 0.10)
        points = (r["competition_points"] - lo) / span if span else 0.5
        hb = min(r["h_count"] + r["b_count"], 30) / 30
        power[r["car"]] = (
            .50 * mark + .30 * points + .14 * r["recent_form_score"]
            + .06 * hb)
        if condition_adjustments is not None:
            power[r["car"]] += condition_adjustments.get(r["car"], 0.0)
    return power


def _baseline_A(snap, strengths, *, max_tickets=12):
    riders = [r["car"] for r in snap["riders"]]
    group_for = {car: i for i, g in enumerate(snap["line_groups"]) for car in g}
    picks = []
    for top3 in permutations(riders, 3):
        # Same-line cooperative wheel hypothesis is a small research modifier,
        # not a proven historical follow success.
        bonus = .055 * (group_for[top3[0]] == group_for[top3[1]])
        s = (1.00 * strengths[top3[0]] +
             .73 * strengths[top3[1]] +
             .52 * strengths[top3[2]] + bonus)
        picks.append((s, top3))
    picks.sort(key=lambda v: (-v[0], v[1]))
    return [list(ticket) for _, ticket in picks[:max_tickets]]


def _move_line(order, line, *, to_front=True):
    line_order = [x for x in line if x in order]
    rest = [x for x in order if x not in line_order]
    return line_order + rest if to_front else rest + line_order


def _view(phase, order, actions):
    return {
        "phase": phase,
        "projected_order": list(order),
        "projected_top3": list(order[:3]),
        "hypothesis_actions": list(actions),
        "actual_rider_position_video_verified": False,
    }


def _scenario(snap, strengths, leader, challenger, variant):
    groups = snap["line_groups"]
    leader_group = next(g for g in groups if leader in g)
    challenger_group = next(g for g in groups if challenger in g)
    order = list(sum(groups, []))
    phases = [_view(PHASES[0], order, ["PREDICTED_LINE_ORDER_ONLY"])]
    order = _move_line(order, leader_group)
    phases.append(_view("BELL", order, ["LEADER_ATTACKS", f"LEADER_CAR_{leader}"]))
    if variant % 2:
        order = _move_line(order, challenger_group)
        home = ["CHALLENGER_EARLY_COUNTER", f"CAR_{challenger}"]
    else:
        home = ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]
    phases.append(_view("FINAL_HOME", order, home))
    if variant in (0, 3):
        order = _move_line(order, leader_group)
        back = ["LEADER_MAKURI_OR_KAMASHI", f"CAR_{leader}"]
    else:
        order = _move_line(order, challenger_group)
        back = ["CHALLENGER_MAKURI", f"CAR_{challenger}"]
    phases.append(_view("FINAL_BACK", order, back))
    front_group = next(g for g in groups if order[0] in g)
    corner = ["FRONT_LINE_CONTINUITY_UNVERIFIED"]
    if len(front_group) >= 2 and variant in (1, 3):
        follower = front_group[1]
        if follower in order:
            order.remove(follower)
            order.insert(0, follower)
            corner = ["FOLLOWER_SASHI_SCENARIO", f"CAR_{follower}"]
    phases.append(_view("FOURTH_CORNER", order, corner))
    goal = ["FOURTH_CORNER_ORDER_CONTINUES"]
    if variant == 2 and len(order) >= 2:
        # Explicit late acceleration hypothesis, not race observation.
        contender = sorted(order[1:4], key=lambda c: (-strengths[c], c))[0]
        order.remove(contender)
        order.insert(0, contender)
        goal = ["LATE_SPRINT_OVERTAKE", f"CAR_{contender}"]
    elif variant == 3 and len(order) >= 3:
        fade = order.pop(0)
        order.insert(2, fade)
        goal = ["FRONT_LEADER_PACE_FADE", f"CAR_{fade}"]
    phases.append(_view("GOAL", order, goal))
    assert len(phases) == 6
    return phases


def generate_A_B(snapshot, *, generated_at, max_tickets=12):
    """Pure deterministic model. Input must originate in a prior source file.

    Not a provider scraper, not a production win probability. Intended for a
    trusted owner-private runner which independently checks raw source bytes.
    """
    validate_snapshot(snapshot, computed_at=generated_at)
    need(type(max_tickets) is int and 1 <= max_tickets <= 12,
         "TICKET_COUNT_OUT_OF_RANGE")
    condition_reports = None
    if "condition_evidence" in snapshot:
        try:
            condition_reports = condition.assess(
                snapshot["condition_evidence"],
                starters={r["car"] for r in snapshot["riders"]},
                source_pages=snapshot["source_pages"],
                as_of=snapshot["as_of"], target_race_id=snapshot["race_id"])
        except condition.FormEvidenceError as exc:
            raise AutomaticForecastError(str(exc)) from None
    strengths = _strengths(
        snapshot["riders"],
        condition_adjustments=(
            {car: r["score_adjustment"] for car, r in condition_reports.items()}
            if condition_reports is not None else None))
    a = _baseline_A(snapshot, strengths, max_tickets=max_tickets)
    leaders = [g[0] for g in snapshot["line_groups"]]
    leaders.sort(key=lambda c: (-strengths[c], c))
    scenarios = []
    masses = {}
    for pos, leader in enumerate(leaders[:5]):
        challenger = next((c for c in leaders if c != leader), leader)
        for variant in range(4):
            # Distinct scenario paths; a branch score is not a probability.
            index = f"L{leader}_V{variant}"
            phase_steps = _scenario(snapshot, strengths, leader, challenger, variant)
            mode_weight = (1.00, .77, .56, .37)[variant]
            lead_style = next(r["style"] for r in snapshot["riders"]
                              if r["car"] == leader)
            if lead_style == "NIGE" and variant in (0, 3):
                mode_weight *= 1.12
            elif lead_style in ("MAKURI", "ALLROUND") and variant in (1, 2):
                mode_weight *= 1.12
            if condition_reports is not None:
                # A small exploratory tactical reweight. Missing evidence
                # leaves the exact original weights untouched. Never infer
                # a medical limit or a fallen rider's inability to lead.
                delta = condition_reports[leader]["score_adjustment"]
                mode_weight *= (
                    1.0 + 2.0 * delta if variant in (0, 3)
                    else 1.0 - delta)
            # Apply only source-evidenced objectives. UNKNOWN does not
            # silently inherit a generic advancement rule.
            rule = snapshot["round_rule"]
            if rule is not None:
                if rule["objective"] == "TITLE_WIN" and variant == 2:
                    mode_weight *= 1.15
                elif rule["objective"] in ("DIRECT_QUALIFY","ALL_ADVANCE") and variant == 0:
                    mode_weight *= 1.15
            mass = max(.01, strengths[leader] + .15) * (
                1.0 / (1.0 + pos)) * mode_weight
            scenarios.append({
                "scenario_id": index, "six_phases": phase_steps,
                "projected_3ren_tan": phase_steps[-1]["projected_top3"],
                "unscaled_research_weight": mass,
            })
            masses[index] = mass
    need(len(scenarios) >= 2, "MULTIPLE_SIX_PHASE_SCENARIOS_REQUIRED")
    norm = sum(masses.values())
    aggregate = {}
    for scenario in scenarios:
        w = scenario["unscaled_research_weight"] / norm
        ticket = tuple(scenario["projected_3ren_tan"])
        scenario["relative_research_weight"] = w
        del scenario["unscaled_research_weight"]
        aggregate[ticket] = aggregate.get(ticket, 0.0) + w
    ranked = sorted(aggregate, key=lambda t: (-aggregate[t], t))
    b = [list(t) for t in ranked[:max_tickets]]
    need(a and b, "AUTO_PREDICTION_EMPTY")
    result = {
        "schema": PREDICTION,
        "race_id": snapshot["race_id"],
        "generated_at": generated_at,
        "published_cutoff_at": snapshot["published_cutoff_at"],
        "source_facts_sha256": digest(snapshot),
        "source_as_of": snapshot["as_of"],
        "A": {"model": MODEL_A, "ranked_tickets": a,
              "based_on_published_marks_not_shared_PR71": True},
        "B": {"model": MODEL_B, "ranked_tickets": b,
              "six_phase_scenarios": scenarios,
              "round_objective_source": (
                  "SOURCE_EVIDENCED" if snapshot["round_rule"] is not None
                  else "UNKNOWN_NOT_IMPUTED")},
        "C": {"state": "HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS"},
        "official_cutoff_independently_authenticated": False,
        "official_result_observed": False,
        "all_six_phase_orders_are_hypotheses_not_video_truth": True,
        "branch_weights_are_not_calibrated_probabilities": True,
        "formal_model_promoted": False,
        "old_PR71_four_models_required": False,
        "real_money_wager_placed": False,
    }
    if condition_reports is not None:
        public_safe_trace = [condition_reports[c] for c in
                             sorted(condition_reports)]
        result["A"]["pre_cutoff_form_fall_trace"] = public_safe_trace
        result["B"]["pre_cutoff_form_fall_trace"] = public_safe_trace
        result["condition_research_notes"] = {
            "schema": condition.SCHEMA,
            "captured_before_prediction": True,
            "personal_medical_recovery_claimed": False,
            "fall_alone_never_penalizes": True,
            "comment_text_not_automatically_interpreted": True,
            "ranking_weights_uncalibrated": True,
            "historical_source_rows_in_private_snapshot": True,
        }
    result["prediction_sha256"] = digest(result)
    return result
