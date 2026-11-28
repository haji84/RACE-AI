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
    need(type(snap) is dict and set(snap) == fields and
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
    # Never promote the input to an organizer- or model-verified forecast.
    return snap


def _strengths(riders):
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


def _python311_sum(values, start=0):
    """Reproduce the left-to-right arithmetic used by the original writer."""
    total = start
    for value in values:
        total = total + value
    return total


def generate_A_B(snapshot, *, generated_at, max_tickets=12, _replay_python311=False):
    """Pure deterministic model. Input must originate in a prior source file.

    Not a provider scraper, not a production win probability. Intended for a
    trusted owner-private runner which independently checks raw source bytes.
    """
    validate_snapshot(snapshot, computed_at=generated_at)
    need(type(max_tickets) is int and 1 <= max_tickets <= 12,
         "TICKET_COUNT_OUT_OF_RANGE")
    strengths = _strengths(snapshot["riders"])
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
    weight_sum = _python311_sum if _replay_python311 else sum
    norm = weight_sum(masses.values())
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
    result["prediction_sha256"] = digest(result)
    return result


# The strict, sealed-record entry point above remains byte-for-byte compatible
# with previously stored research originals. Current displayed research uses
# generate_evidence_analysis below. It has no clock bypass, network access,
# storage writer, wager operation, learned weights, or production promotion.
EVIDENCE_METHOD = "forward-phase-independent-pair-selection-20261122"
EVIDENCE_A = "observed-ability-on-evidenced-scenarios"
EVIDENCE_B = "role-and-pace-on-evidenced-scenarios"
# These are declared rule parameters, NOT fitted winning probabilities.
# Keep candidates with at least half the strongest support in their OWN market.
# Pair supports sum different thirds before this rule; the common threshold
# therefore does not force the two markets to share tickets or point counts.
MARKET_SUPPORT_FLOORS = {"3t": .50, "2t": .50}


def _finite_feature(value, *, maximum=150, zero_unknown=False):
    if type(value) is str and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value.strip()):
        value = float(value)
    if (type(value) not in (int, float) or not isfinite(value)
            or value < 0 or value > maximum or (zero_unknown and value == 0)):
        return None
    return float(value)


def _first_feature(row, *keys, maximum=150, zero_unknown=False):
    for key in keys:
        if key in row:
            return _finite_feature(row[key], maximum=maximum,
                                   zero_unknown=zero_unknown)
    return None


def _weighted_observed(values):
    """Unknown is absent, not zero or an invented population average."""
    present = [(weight, value) for weight, value in values if value is not None]
    return (sum(weight * value for weight, value in present) /
            sum(weight for weight, _ in present)) if present else None


def _explicit_attack_comment(comment):
    """Admit a narrow affirmative first clause, never a negated substring."""
    clause = re.split(r"[。.!！、,\n]", comment.strip(), maxsplit=1)[0].strip()
    return bool(re.fullmatch(
        r"(?:自力(?:自在)?(?:勝負|主体|で(?:頑張る|頑張ります|頑張りたい|勝負|やる|行く|戦う))?"
        r"|先行(?:で勝負|主体)?|前で(?:やる|頑張る|勝負)|自分で(?:やる|動く|戦う))", clause))


def _evidence_profiles(snapshot):
    rows = snapshot.get("riders")
    need(type(rows) is list and 5 <= len(rows) <= 9, "FIVE_TO_NINE_STARTERS_REQUIRED")
    profiles, missing = {}, []
    for row in rows:
        car = row.get("car", row.get("number"))
        need(type(car) is int and 1 <= car <= 9 and car not in profiles,
             "INVALID_OR_DUPLICATE_CAR")
        observed = {
            "competition_points": _first_feature(row, "competition_points", "score", zero_unknown=True),
            "win_rate": _first_feature(row, "win_rate", maximum=100),
            "top2_rate": _first_feature(row, "top2_rate", maximum=100),
            "top3_rate": _first_feature(row, "top3_rate", maximum=100),
            "H": _first_feature(row, "h_count", "H", maximum=99),
            "B": _first_feature(row, "b_count", "B", maximum=99),
            "S": _first_feature(row, "S", maximum=99),
            "nige": _first_feature(row, "nige", maximum=99),
            "makuri": _first_feature(row, "makuri", maximum=99),
            "sashi": _first_feature(row, "sashi", maximum=99),
            "mark": _first_feature(row, "mark", maximum=99),
            "gear": _first_feature(row, "gear", maximum=6),
        }
        for key, value in observed.items():
            if value is None:
                missing.append(f"riders.{car}.{key}")
        style = row.get("style", "UNKNOWN")
        style = {"逃": "NIGE", "両": "ALLROUND", "追": "MARK"}.get(style, style)
        if style not in STYLES:
            style = "UNKNOWN"
        comment = str(row.get("comment") or "")
        # Only explicit self-propulsion intent is interpreted. A quoted name,
        # vague positive remark or a third person's injury is not a fact about
        # this rider's fitness. Full interview text is never returned here.
        comment_intent = _explicit_attack_comment(comment)
        sources = row.get("field_sources") or {}
        if not sources.get("comment"):
            comment_intent = False
        rank = row.get("mark_rank")
        mark_index = ((len(rows) + 1 - rank) / len(rows)
                      if type(rank) is int and 1 <= rank <= len(rows) else
                      0.0 if rank == "UNMARKED" else None)
        profiles[car] = {
            "car": car, "name": row.get("name"), "observed": observed,
            "style": style, "mark_index": mark_index,
            "comment_attack_intent": comment_intent,
            "field_sources": dict(sources),
            "warnings": (["UNAVAILABLE_SOURCE_VALUE"]
                         if observed["competition_points"] is None else []),
        }
    point_values = [p["observed"]["competition_points"] for p in profiles.values()
                    if p["observed"]["competition_points"] is not None]
    need(point_values, "COMPETITION_POINTS_UNAVAILABLE_FOR_ALL")
    hi, lo = max(point_values), min(point_values)
    # The ten-point floor avoids stretching a 0.1-point tie into a full-scale
    # strength difference. This research transform is declared, not learned.
    scale = max(10.0, hi - lo)
    max_h = max((p["observed"]["H"] or 0) for p in profiles.values())
    max_b = max((p["observed"]["B"] or 0) for p in profiles.values())
    for p in profiles.values():
        o = p["observed"]
        point = None if o["competition_points"] is None else 1 - (hi - o["competition_points"]) / scale
        rate = lambda key: None if o[key] is None else o[key] / 100
        p["head_strength"] = _weighted_observed(((.60, point), (.30, rate("win_rate")), (.10, p["mark_index"])))
        p["second_strength"] = _weighted_observed(((.60, point), (.35, rate("top2_rate")), (.05, p["mark_index"])))
        p["third_strength"] = _weighted_observed(((.55, point), (.40, rate("top3_rate")), (.05, p["mark_index"])))
        moves = [o[k] for k in ("nige", "makuri", "sashi", "mark")]
        total = sum(moves) if all(v is not None for v in moves) else None
        p["attack_share"] = ((o["nige"] + o["makuri"]) / total
                             if total else None)
        p["sashi_share"] = (o["sashi"] / total if total else None)
        p["follow_share"] = ((o["sashi"] + o["mark"]) / total if total else None)
        p["lead_activity"] = _weighted_observed((
            (.40, p["attack_share"]),
            (.30, None if o["H"] is None else o["H"] / max(1, max_h)),
            (.30, None if o["B"] is None else o["B"] / max(1, max_b))))
        p["explicit_attack"] = (p["style"] in ("NIGE", "MAKURI", "ALLROUND")
                                or p["comment_attack_intent"]
                                or any((o[k] or 0) > 0 for k in ("H", "B", "nige", "makuri")))
        p["explicit_sashi"] = ((o["sashi"] or 0) > 0 or p["style"] in ("SASHI", "ALLROUND"))
        for key in ("head_strength", "second_strength", "third_strength"):
            need(p[key] is not None, "INSUFFICIENT_OBSERVED_FINISH_FEATURES")
    return profiles, missing


def _evidence_line_groups(snapshot, cars):
    groups = snapshot.get("line_groups")
    if groups is None:
        return None
    need(type(groups) is list and groups and all(type(g) is list and g for g in groups),
         "LINE_GROUPS_NOT_AN_EXACT_STARTER_PARTITION")
    flat = sum(groups, [])
    need(len(flat) == len(cars) and len(set(flat)) == len(cars) and set(flat) == set(cars),
         "LINE_GROUPS_NOT_AN_EXACT_STARTER_PARTITION")
    return [list(g) for g in groups]


def _profile_facts(p):
    o = p["observed"]
    number = lambda v: "未確認" if v is None else f"{v:g}"
    return (f"{p['car']}番：得点{number(o['competition_points'])}、掲載4ヶ月勝率{number(o['win_rate'])}%、"
            f"H/B={number(o['H'])}/{number(o['B'])}、逃/捲/差/マ="
            f"{number(o['nige'])}/{number(o['makuri'])}/{number(o['sashi'])}/{number(o['mark'])}")


def _arrange(front, order):
    return list(front) + [c for c in order if c not in front]


def _evidence_phase(phase, order, explanation, actions):
    out = _view(phase, order, actions)
    out["explanation"] = explanation
    out["position_unknown"] = False
    return out


def _finish_route_reason(car, place, groups, leader, head, kind):
    group = next(g for g in groups if car in g)
    lead_line = next(g for g in groups if leader in g)
    if car == leader:
        return (f"{car}番は最終バックまでの先行位置から粘って{place}着へ残る条件。" if kind != "ATTACKER_FADE" else
                f"仕掛け役{car}番が差された後、失速しつつ{place}着まで残る条件。")
    if group[0] == head:
        pos = group.index(car) + 1
        if pos == place:
            return f"{car}番は{head}番のライン{pos}番手から、その位置を保ち{place}着へ届く条件。"
        if pos < place:
            return f"{car}番は{head}番のライン{pos}番手から追走するが、別線が間に入り{place}着へ下がって残る条件。"
        return f"{car}番は{head}番のライン{pos}番手から、前の味方の減速で開く進路を使い{place}着へ上がる条件。"
    if car in lead_line:
        pos = lead_line.index(car) + 1
        return f"{car}番は先行した{leader}番のライン{pos}番手。前の選手の減速で空く進路を使い{place}着へ入る条件。"
    if group[0] == car:
        return f"別線先頭の{car}番が外の進路を維持して粘り、{place}着へ入る条件。"
    return f"{car}番は別線先頭{group[0]}番の動きに続き、追走が切れず{place}着へ届く条件。"


def _adjacent_pass(order, overtaker, evidence):
    """One explicit local movement, never a finished-ticket reorder."""
    result = list(order)
    index = result.index(overtaker)
    need(index > 0, "PASS_REQUIRES_RIDER_IMMEDIATELY_AHEAD")
    passed = result[index - 1]
    result[index - 1], result[index] = result[index], result[index - 1]
    return result, {"overtaker": overtaker, "passed": passed, "evidence": list(evidence)}


def _scenario_prefix(groups, profiles, leader, challenger, kind):
    """Choose INITIAL through CORNER before considering any finishing ticket.

    A line's early move is an explicit branch assumption, not an observed
    movement. Terminal candidates may not feed back into these five states.
    """
    ordered_groups = sorted(groups, key=lambda g: (
        -max((profiles[c]["observed"]["S"] or 0) for c in g), g[0]))
    initial = sum(ordered_groups, [])
    lead_line = next(g for g in groups if leader in g)
    other_line = next((g for g in groups if challenger in g), []) if challenger else []
    steps = [_evidence_phase("INITIAL", initial,
        "掲載並びとS回数から置く初周の仮説。実際の位置取りは未確認。",
        ["PREDICTED_LINE_ORDER_ONLY"])]
    bell = _arrange(lead_line, initial)
    steps.append(_evidence_phase("BELL", bell,
        f"{leader}番のラインが先手を取る分岐。",
        ["LEADER_ATTACKS", f"CAR_{leader}"]))
    home = list(bell)
    home_text = f"{leader}番が先行を続け、掲載ラインが追走する仮説。"
    actions = ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]
    if kind == "COUNTER":
        home_text = f"{leader}番の先行に{challenger}番のラインが外から反撃を始める分岐。"
        actions = ["CHALLENGER_EARLY_COUNTER", f"CAR_{challenger}"]
    elif kind == "ATTACKER_FADE" and challenger is not None:
        # Both attacking identities are established before the final back.
        # Interleaving describes parallel lines, not a late remote-rider jump.
        front = [leader, challenger]
        if len(lead_line) > 1:
            front.append(lead_line[1])
        if len(other_line) > 1:
            front.append(other_line[1])
        home = _arrange(front, home)
        home_text = (f"{leader}番と{challenger}番が踏み合う条件を置く。"
                     "外の先頭と内の番手が先頭付近まで並ぶ仮説。")
        actions = ["CHALLENGER_EARLY_COUNTER", f"CAR_{challenger}"]
    elif kind == "LATE_FINISH":
        # The solo rider must first obtain a near-front position. It cannot
        # suddenly move from the rear at the finish because of a high score.
        front = lead_line[:2] + [challenger]
        home = _arrange(front, home)
        home_text = f"単騎の{challenger}番が{leader}番の先行ライン直後へ追い上げる条件。"
        actions = ["SOLO_RIDER_FOLLOWS_ATTACK", f"CAR_{challenger}"]
    steps.append(_evidence_phase("FINAL_HOME", home, home_text, actions))
    back = _arrange(other_line, home) if kind == "COUNTER" else list(home)
    back_text = (f"{challenger}番の捲りが届き、そのラインが前へ出る分岐。" if kind == "COUNTER" else
                 f"元の仕掛け役{leader}番を先頭にバックへ入る条件。")
    steps.append(_evidence_phase("FINAL_BACK", back, back_text,
        ["CHALLENGER_MAKURI", f"CAR_{challenger}"] if kind == "COUNTER" else
        ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]))
    corner = list(back)
    corner_events = []
    corner_text = "バックの前後関係を保って4コーナーへ入る条件。"
    if kind == "ATTACKER_FADE":
        # One fade branch per attacker: the adjacent two riders pass that
        # attacker. No Cartesian product of hypothetical replacement leaders.
        for _ in range(2):
            index = corner.index(leader)
            overtaker = corner[index + 1]
            corner, event = _adjacent_pass(corner, overtaker,
                [f"仕掛け役{leader}番が踏み合い・長い先行で減速する場合。",
                 _profile_facts(profiles[leader])])
            corner_events.append(event)
        corner_text = (f"先行した{leader}番が減速し、直後の2車が順に交わす条件。"
                       "落車・負傷を推定したものではない。")
    elif kind == "LATE_FINISH" and corner.index(challenger) == 2:
        corner, event = _adjacent_pass(corner, challenger,
            ["前のライン直後から外へ踏み上げる単騎の条件。", _profile_facts(profiles[challenger])])
        corner_events.append(event)
        corner_text = f"単騎{challenger}番が前方追走から1車を交わし、先頭直後まで進む条件。"
    step = _evidence_phase("FOURTH_CORNER", corner, corner_text,
        ["FRONT_LEADER_PACE_FADE", f"CAR_{leader}"] if kind == "ATTACKER_FADE" else
        ["FORWARD_CORNER_POSITION"])
    step["local_transitions"] = corner_events
    steps.append(step)
    return steps


def _local_finish_paths(prefix, profiles, groups, leader, challenger, kind):
    """Derive finish states from the fixed corner with evidenced local moves.

    A mandatory branch event may be followed by one independent adjacent
    duel for second/third. More simultaneous passes are left unmodelled;
    the absence of a path is not a claim the real outcome is impossible.
    """
    corner = list(prefix[-1]["projected_order"])
    order, events = corner, []
    if kind in ("FOLLOWER_PASS", "LATE_FINISH"):
        overtaker = (next(g for g in groups if leader in g)[1]
                     if kind == "FOLLOWER_PASS" else challenger)
        need(order.index(overtaker) == 1, "FINISH_ATTACK_REQUIRES_ADJACENT_POSITION")
        order, event = _adjacent_pass(order, overtaker,
            ["番手から直線で差し切る条件。" if kind == "FOLLOWER_PASS" else
             "先頭直後へ進んだ単騎が直線で交わす条件。", _profile_facts(profiles[overtaker])])
        events = [event]
    paths = [(list(order), list(events), 1.0)]
    # A second-place challenge or a third-place challenge. They are separate
    # terminal branches, not freely combined to generate every permutation.
    for index, metric in ((2, "second_strength"), (3, "third_strength")):
        overtaker, passed = order[index], order[index - 1]
        if kind == "FOLLOWER_PASS" and index == 2:
            # Losing the original attacker from second is the FADE branch.
            continue
        if kind == "ATTACKER_FADE" and overtaker == leader and index == 2:
            continue
        stronger = profiles[overtaker][metric] > profiles[passed][metric]
        sashi = profiles[overtaker]["explicit_sashi"]
        if not (stronger or sashi):
            continue
        changed, event = _adjacent_pass(order, overtaker,
            [f"4角で直前の{passed}番と競り、{index}着へ上がる条件。",
             "掲載の該当着内指標が上位。" if stronger else "掲載の差し実績・差し脚質を条件にする。",
             _profile_facts(profiles[overtaker]), _profile_facts(profiles[passed])])
        if kind == "ATTACKER_FADE" and leader in changed[:2]:
            continue
        # A move for third never changes the separately computed pair weight.
        pair_fit = (min(1.0, max(.001, profiles[overtaker][metric]) /
                        max(.001, profiles[passed][metric])) if index == 2 else 1.0)
        paths.append((changed, events + [event], pair_fit))
    return paths


def _ability_only_scenarios(profiles):
    """Missing lines permit a labelled ability comparison, never a fake path."""
    scenarios = []
    for head in profiles:
        for second in profiles:
            if head == second:
                continue
            thirds = [c for c in profiles if c not in (head, second)]
            third_weights = {c: max(.001, profiles[c]["third_strength"]) ** .8 for c in thirds}
            total = sum(third_weights.values())
            pair = max(.001, profiles[head]["head_strength"]) ** 2 * max(.001, profiles[second]["second_strength"]) ** 1.3
            for third in thirds:
                order = _arrange([head, second, third], list(profiles))
                prefix = []
                for phase in PHASES[:-1]:
                    prefix.append({"phase": phase, "projected_order": None,
                        "projected_top3": None, "position_unknown": True,
                        "hypothesis_actions": ["POSITION_UNAVAILABLE_LINE_MISSING"],
                        "explanation": "並び未取得のため、この局面の隊列は推測しない。能力比較のみ。"})
                prefix.append(_evidence_phase("GOAL", order,
                    "並び・進路を確認できない能力比較。実際の着順ではない。", ["ABILITY_COMPARISON_ONLY"]))
                scenarios.append({"scenario_id": f"ABILITY_{head}_{second}_{third}",
                    "tactical_branch_id": f"ABILITY_{head}_{second}", "branch_kind": "ABILITY_ONLY",
                    "attacking_car": None, "challenger_car": None, "faded_car": None,
                    "projected_3ren_tan": [head, second, third], "six_phases": prefix,
                    "finish_transitions": [], "rationale": ["並び未取得。掲載得点・着内率に限る能力候補。"],
                    "support_A": pair * third_weights[third] / total, "support_B": pair * third_weights[third] / total,
                    "pair_support_A": pair, "pair_support_B": pair,
                    "known_line_hypothesis": False})
    return scenarios


def _lead_branch_support(profile):
    activity = profile["lead_activity"]
    return .50 + .50 * (activity if activity is not None else .5)


def _counter_branch_support(profile):
    counter = profile["observed"]["makuri"]
    return .50 + .35 * (counter / max(1, counter + (profile["observed"]["nige"] or 0))
                       if counter is not None else .5)


def _evidence_scenarios(profiles, groups):
    if groups is None:
        return _ability_only_scenarios(profiles)
    leaders = [g[0] for g in groups]
    group_of = {c: g for g in groups for c in g}
    active = [c for c in leaders if profiles[c]["explicit_attack"]] or list(leaders)
    active.sort(key=lambda c: (-profiles[c]["head_strength"], c))
    shells = []
    for leader in active:
        p = profiles[leader]
        lead_line = group_of[leader]
        others = [c for c in active if c != leader]
        best_other = max(others, key=lambda c: profiles[c]["head_strength"], default=None)
        lead_activity = p["lead_activity"]
        lead_support = _lead_branch_support(p)
        shells.append((leader, best_other, "HOLD", lead_support,
            [f"{leader}番が先手を取り、4角まで位置を保つ条件。", _profile_facts(p)]))
        if len(lead_line) >= 2:
            follower = lead_line[1]
            fp = profiles[follower]
            if fp["explicit_sashi"]:
                support = (.50 + .50 * (fp["sashi_share"] or 0)) * (.8 + .2 * lead_support)
                shells.append((leader, best_other, "FOLLOWER_PASS", support,
                    [f"{leader}番の先行に{follower}番が追走し、直線で差す条件。", _profile_facts(fp)]))
            if best_other is not None or (lead_activity is not None and lead_activity >= .65):
                shells.append((leader, best_other, "ATTACKER_FADE", .35 + .25 * (1 if best_other is not None else .5),
                    [f"先行役{leader}番が踏み合い・長い先行で減速する条件。",
                     "その時点の隣接2車が交わす1本の経路。失速後の全組合せは作らない。", _profile_facts(p)]))
        for challenger in others:
            cp = profiles[challenger]
            support = _counter_branch_support(cp)
            shells.append((leader, challenger, "COUNTER", support,
                [f"{leader}番の先行に{challenger}番が反撃し、バックまでに前へ出る条件。", _profile_facts(cp)]))
        for g in groups:
            solo = g[0]
            if len(g) == 1 and solo != leader and profiles[solo]["explicit_sashi"]:
                shells.append((leader, solo, "LATE_FINISH", .50,
                    [f"単騎{solo}番が先行ライン近くまで追い上げてから差す条件。", _profile_facts(profiles[solo])]))
    scenarios = []
    seen_branches = set()
    for leader, challenger, kind, branch_support, reasons in shells:
        branch_id = f"{kind}_{leader}_{challenger or 0}"
        if branch_id in seen_branches:
            continue
        seen_branches.add(branch_id)
        prefix = _scenario_prefix(groups, profiles, leader, challenger, kind)
        paths = _local_finish_paths(prefix, profiles, groups, leader, challenger, kind)
        by_pair = {}
        for order, events, pair_fit in paths:
            pair = tuple(order[:2])
            head_power = max(.001, profiles[pair[0]]["head_strength"])
            second_power = max(.001, profiles[pair[1]]["second_strength"])
            base = head_power ** 2 * second_power ** 1.3
            # Both arms respect branch evidence. A gives ability more weight;
            # B applies the full tactical-condition penalty and local fit.
            pair_a = base * branch_support ** .5
            pair_b = base * branch_support * pair_fit
            row = by_pair.setdefault(pair, {"pair_A": pair_a, "pair_B": pair_b, "paths": {}})
            row["pair_A"] = max(row["pair_A"], pair_a)
            row["pair_B"] = max(row["pair_B"], pair_b)
            third = order[2]
            row["paths"].setdefault(third, (order, events))
        for pair, row in by_pair.items():
            third_weights = {third: max(.001, profiles[third]["third_strength"]) ** .8
                             for third in row["paths"]}
            total = sum(third_weights.values())
            for third, (order, events) in row["paths"].items():
                ticket = order[:3]
                fraction = third_weights[third] / total
                finish_text = ("4角の位置を保ってゴールする条件。" if not events else
                    " ".join(f"{e['overtaker']}番が直前の{e['passed']}番を交わす。" for e in events))
                finish_text += " 実測着順ではなく、前段から導いた条件付きの到達順。"
                goal = _evidence_phase("GOAL", order, finish_text,
                    ["LOCAL_FINISH_TRANSITIONS"] + ([f"CAR_{leader}", "FRONT_LEADER_PACE_FADE"] if kind == "ATTACKER_FADE" else []))
                scenarios.append({"scenario_id": branch_id + "_" + "-".join(map(str, ticket)),
                    "tactical_branch_id": branch_id, "branch_kind": kind,
                    "attacking_car": leader, "challenger_car": challenger,
                    "faded_car": leader if kind == "ATTACKER_FADE" else None,
                    "projected_3ren_tan": ticket, "six_phases": prefix + [goal],
                    "finish_transitions": events, "rationale": list(reasons) + [finish_text],
                    "branch_support": branch_support,
                    "pair_support_A": row["pair_A"], "pair_support_B": row["pair_B"],
                    "conditional_third_support": fraction,
                    "support_A": row["pair_A"] * fraction,
                    "support_B": row["pair_B"] * fraction,
                    "known_line_hypothesis": True})
    need(scenarios, "NO_EVIDENCE_SUPPORTED_SCENARIOS")
    return scenarios


def select_evidence_tickets(candidates, *, market, indistinguishable_field=False):
    """Keep the support window, not a budget-derived/fixed point count.

    All candidates already have specific scenario support. This is a visible,
    uncalibrated research rule. It is not claimed to minimize loss or maximize
    expected value, because current odds and calibrated probabilities are not
    available. Equal-score candidates are never chopped at an arbitrary N.
    """
    need(market in MARKET_SUPPORT_FLOORS, "MARKET_INVALID")
    need(type(candidates) is list and candidates, "MARKET_CANDIDATES_REQUIRED")
    rows = sorted(candidates, key=lambda x: (-x["support"], x["ticket"]))
    need(all(type(x.get("support")) in (int, float) and isfinite(x["support"]) and x["support"] > 0 for x in rows), "CANDIDATE_SUPPORT_INVALID")
    peak = rows[0]["support"]
    floor = MARKET_SUPPORT_FLOORS[market]
    eligible = [dict(row, relative_to_peak=row["support"] / peak)
                for row in rows if indistinguishable_field or row["support"] >= peak * floor - 1e-15]
    # A window retaining every alternative supplied no selection evidence.
    # Preserve those candidates, but never convert that uncertainty into a
    # recommendation to buy the whole universe or an arbitrary first N.
    abstain = indistinguishable_field or (len(rows) > 1 and len(eligible) == len(rows))
    selected = [] if abstain else eligible
    total = sum(x["support"] for x in rows)
    pct = round(floor * 100)
    name = "3連単" if market == "3t" else "2車単"
    meta = {
        "point_count": len(selected), "candidate_count": len(rows),
        "excluded_count": len(rows) - len(eligible), "held_count": len(eligible) if abstain else 0,
        "relative_support_floor": floor,
        "abstention_code": ("INDISTINGUISHABLE_RIDER_EVIDENCE" if indistinguishable_field else
                            "ALL_CANDIDATES_WITHIN_SUPPORT_WINDOW" if abstain else None),
        "threshold_rule": f"最上位候補の研究支持値の{pct}%以上。点数の上限・穴埋めなし。",
        "count_reason": (f"見送り・絞る根拠不足。全単騎の算出能力・役割・位置取り指標に差がなく、車番順や枝数では優劣を付けない。{name}の{len(rows)}候補を保持し、採用は0点。" if indistinguishable_field else
                         f"見送り・絞る根拠不足。{name}の全{len(rows)}候補が採用窓内に残り、選別が成立しない。候補は保持し、採用は0点。" if abstain else
                         f"{name}の展開候補{len(rows)}通りを重複除去して評価。最上位の研究支持値の{pct}%以上を残した結果、{len(selected)}点。"),
        "selected_support_fraction": sum(x["support"] for x in selected) / total,
        "calibrated_probability": False,
        "support_fraction_meaning": "作った展開候補内の支持値比率。的中率・現実の網羅率ではない。",
        "recommendation": ("ABSTAIN_INSUFFICIENT_SEPARATION" if abstain else
                           "REVIEW_WIDE_CANDIDATES" if len(selected) > 30 else "CONDITIONAL_CANDIDATES"),
        "width_warning": (f"候補が{len(selected)}点に分散。1点100円でも{len(selected) * 100:,}円になるため再検討。全候補の一括購入を勧める表示ではない。"
                          if len(selected) > 30 else ""),
        "excluded_candidates": [{"ticket": x["ticket"], "relative_to_peak": x["support"] / peak,
                                 "reason": "研究支持値がこの券種の採用境界より小さい。実現しないとの断定ではない。"}
                                for x in rows if not indistinguishable_field and x["support"] < peak * floor - 1e-15],
    }
    return selected, meta


def select_scenario_markets(scenarios, *, arm, indistinguishable_field=False):
    """Select both full pools; direct pair support never counts third outcomes.

    Each branch scores a pair before splitting its mass among reachable thirds.
    Max aggregation prevents duplicate stories or additional third candidates
    from inflating either market. Legacy caller rows without explicit pair
    support use their strongest exact support, never the sum of descriptions.
    """
    need(arm in ("A", "B"), "ARM_INVALID")
    aggregate3, aggregate2 = {}, {}
    for s in scenarios:
        t = tuple(s["projected_3ren_tan"])
        support = s[f"support_{arm}"]
        if t not in aggregate3:
            aggregate3[t] = dict(ticket=list(t), support=support, scenario_ids=[], reasons=[])
        row = aggregate3[t]
        row["support"] = max(row["support"], support)
        row["scenario_ids"].append(s["scenario_id"])
        for reason in s["rationale"]:
            if reason not in row["reasons"]:
                row["reasons"].append(reason)
        pair = t[:2]
        if pair not in aggregate2:
            aggregate2[pair] = dict(ticket=list(pair), support=0.0, scenario_ids=[], reasons=[])
        target = aggregate2[pair]
        pair_support = s.get(f"pair_support_{arm}", support)
        need(type(pair_support) in (int, float) and isfinite(pair_support) and pair_support > 0,
             "PAIR_SUPPORT_INVALID")
        target["support"] = max(target["support"], pair_support)
        if s["scenario_id"] not in target["scenario_ids"]:
            target["scenario_ids"].append(s["scenario_id"])
        for reason in s["rationale"]:
            if reason not in target["reasons"]:
                target["reasons"].append(reason)
    chosen3, meta3 = select_evidence_tickets(list(aggregate3.values()), market="3t", indistinguishable_field=indistinguishable_field)
    chosen2, meta2 = select_evidence_tickets(list(aggregate2.values()), market="2t", indistinguishable_field=indistinguishable_field)
    def complete(pool):
        ordered = sorted(pool.values(), key=lambda x: (-x["support"], x["ticket"]))
        peak = ordered[0]["support"]
        return [dict(x, relative_to_peak=x["support"] / peak) for x in ordered]
    candidates3, candidates2 = complete(aggregate3), complete(aggregate2)
    return {
        "ranked_tickets": [x["ticket"] for x in chosen3],
        "ranked_2ren_tan": [x["ticket"] for x in chosen2],
        "point_count_3t": len(chosen3), "point_count_2t": len(chosen2),
        "markets": {"3t": {"tickets": [x["ticket"] for x in chosen3], "point_count": len(chosen3)},
                    "2t": {"tickets": [x["ticket"] for x in chosen2], "point_count": len(chosen2)}},
        "ticket_evidence": {"3t": chosen3, "2t": chosen2},
        "candidate_tickets": {"3t": [x["ticket"] for x in candidates3],
                              "2t": [x["ticket"] for x in candidates2]},
        "candidate_evidence": {"3t": candidates3, "2t": candidates2},
        "selection_context": {"indistinguishable_solo_field": indistinguishable_field},
        "selection": {"3t": meta3, "2t": meta2},
    }


def generate_evidence_analysis(snapshot):
    """Current display research: facts -> paths -> candidates -> market counts.

    This intentionally does not call the sealed pre-cutoff generator: it is
    also usable for result-unread retrospective research. Callers must record
    actual creation time and original source capture time. It cannot attest a
    pre-cutoff original, train weights, confirm a result or save a wager.
    """
    profiles, missing = _evidence_profiles(snapshot)
    groups = _evidence_line_groups(snapshot, profiles)
    # Compare the effective scoring/role inputs, not raw metadata already
    # subsumed by them. For example, an empty comment cannot distinguish an
    # ALLROUND rider who has the same explicit attack evidence from style and
    # moves. Raw facts remain in feature_audit but cannot defeat abstention.
    signatures = {
        (p["head_strength"], p["second_strength"], p["third_strength"],
         p["explicit_attack"], p["explicit_sashi"], _lead_branch_support(p),
         _counter_branch_support(p), p["observed"]["S"] or 0)
        for p in profiles.values()
    }
    indistinguishable = (groups is not None and all(len(g) == 1 for g in groups)
                         and len(signatures) == 1)
    scenarios = _evidence_scenarios(profiles, groups)
    warnings = list(snapshot.get("line_warnings") or [])
    output = {}
    for arm, name in (("A", EVIDENCE_A), ("B", EVIDENCE_B)):
        if arm == "B" and groups is None:
            output[arm] = {
                "state": "UNGENERATED_LINE_EVIDENCE_MISSING", "model": name,
                "method_mode": EVIDENCE_METHOD, "confidence": "未評価",
                "confidence_reason": "並びの根拠が取得できていない。",
                "ranked_tickets": [], "ranked_2ren_tan": [], "point_count_3t": 0,
                "point_count_2t": 0, "six_phase_scenarios": [],
                "rationale": warnings + ["Bは並び未取得のため未生成。Aの表示は独立して継続。"],
                "reconciliation": {"state": "RESULT_NOT_READ", "official_result": None, "hit": None, "payout": None},
            }
            continue
        chosen = select_scenario_markets(scenarios, arm=arm, indistinguishable_field=indistinguishable)
        total = sum(s[f"support_{arm}"] for s in scenarios)
        own_scenarios = [dict(s, relative_research_weight=s[f"support_{arm}"] / total) for s in scenarios]
        if groups is None:
            rationale = [
                "Aは並び未取得のため、掲載得点・着内率などの能力資料だけで着順候補を比較。",
                "初周から4角の隊列・仕掛け役・追い抜き経路は生成しない。着順候補を実在する展開の証拠とは扱わない。",
            ]
        else:
            rationale = [
                ("Aは出典付きの能力資料を軸に、成立条件を置いた展開候補から買い目を選択。" if arm == "A" else
                 "BはH/B・決まり手・並び・追走位置から、先行維持、番手差し、別線反撃、仕掛け役の失速を分岐。"),
                "初周から4角までの位置を先に決め、直前の車を交わす根拠付きの局所遷移からゴールと買い目を導く。",
                "Aも展開成立の条件を考慮。Bはその条件の重みと局所の追い抜き適合をさらに反映する。同じ資料を使うため独立した裏付けではない。",
            ]
        rationale += [
            "買い目を先に12点へ揃える処理は廃止。各券種の候補支持値から点数が決まる。",
            "2車単は3着を決める前の1・2着支持値を独立評価。3着候補数の加算や採用済み3連単の抜き出しは行わない。",
            "複数の全候補が選別窓に残る場合は、候補を保持したまま見送りとする。",
            "掲載4ヶ月の勝率・連対率を使用。直近の調子の上向き・下降や回復を示す指標ではない。",
            "支持値と選別境界は未学習の明示的な研究ルール。的中率・期待収益・オッズを算出したものではない。",
        ] + warnings
        output[arm] = dict(chosen,
            state="GENERATED_RESEARCH_ONLY", model=name, method_mode=EVIDENCE_METHOD,
            confidence="未評価", confidence_reason="資料の欠測と分岐の安定性を別途評価。未較正のため的中率は表示しない。",
            rationale=rationale, six_phase_scenarios=own_scenarios,
            reconciliation={"state": "RESULT_NOT_READ", "official_result": None, "hit": None, "payout": None})
    condition_rows = snapshot.get("condition_evidence") or []
    output["condition_sensitivity"] = {
        "applied": False, "medical_state_inferred": False,
        "unverified_rows": len(condition_rows),
        "reason": "落車コメントだけで能力を数値減点しない。補正は出典と明示した成立条件を持つ別の感度検討として扱う。",
    }
    output["method"] = {
        "id": EVIDENCE_METHOD, "model_A": EVIDENCE_A, "model_B": EVIDENCE_B,
        "stages": ["SOURCE_FACTS", "SIX_PHASE_SCENARIOS", "FULL_CANDIDATE_POOLS", "INDEPENDENT_MARKET_SELECTION", "DERIVED_COUNTS"],
        "fixed_ticket_cap": None, "fixed_ticket_fill": False,
        "phase_generation": "FORWARD_STATE_TRANSITIONS",
        "pair_support": "MAX_INDEPENDENT_PAIR_SUPPORT",
        "selection_abstention": "ALL_CANDIDATES_RETAINED_WITHOUT_SEPARATION",
        "market_support_floors": dict(MARKET_SUPPORT_FLOORS),
        "calibrated_probabilities": False, "production_weight_promotion": False,
        "formal_pre_cutoff_attestation": False,
        "feature_weights": {"head": {"points": .60, "win_rate": .30, "published_mark": .10},
                            "second": {"points": .60, "top2_rate": .35, "published_mark": .05},
                            "third": {"points": .55, "top3_rate": .40, "published_mark": .05}},
        "strength_transform": "得点差をmax(10点,場内最高最低差)で割る相対尺度。欠測はゼロで埋めず、その選手の既知指標のみ重みを再配分。",
        "candidate_windows": {"finish_moves": "必要な番手差し等の後、根拠付きの隣接追い抜きを追加で1回まで。遠い車を直線で飛ばさない。"},
        "ticket_support": "1・2着能力の頭2乗×2着1.3乗に、Aは分岐支持の平方根、Bは分岐支持と局所適合を反映。3連単だけ許可3着の能力0.8乗比で分配。2車単はこの分配前の支持を使う。全て未較正。",
    }
    output["feature_audit"] = {
        "riders": [profiles[c] for c in sorted(profiles)], "missing": missing,
        "used": ["competition_points", "published_mark", "win_rate", "top2_rate", "top3_rate", "H", "B", "S", "nige", "makuri", "sashi", "mark", "style", "explicit_sourced_attack_intent", "sourced_line_hypothesis"],
        "recorded_not_scored": ["gear"],
        "unknown_not_imputed": ["recent_form_trend", "verified_registration", "verified_fall_rest_return_history", "weather", "wind", "bank_affinity", "bank_geometry", "round_advancement_rule"],
        "gear_reason": "ギヤ比単体から有利・不利や調子を決める検証済み対応がないため、記録のみ。",
    }
    return output
