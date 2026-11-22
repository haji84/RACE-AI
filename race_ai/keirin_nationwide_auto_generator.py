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


def generate_A_B(snapshot, *, generated_at, max_tickets=12):
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
    result["prediction_sha256"] = digest(result)
    return result


# The strict, sealed-record entry point above remains byte-for-byte compatible
# with previously stored research originals. Current displayed research uses
# generate_evidence_analysis below. It has no clock bypass, network access,
# storage writer, wager operation, learned weights, or production promotion.
EVIDENCE_METHOD = "evidence-scenarios-independent-market-selection-20261122"
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


def _scenario_path(groups, profiles, leader, challenger, kind, finish, *, known_lines=True):
    """Movement is a conditional hypothesis; identities survive overtaking."""
    # S is a published start-taking count, not a recording of today's start.
    ordered_groups = sorted(groups, key=lambda g: (
        -max((profiles[c]["observed"]["S"] or 0) for c in g), g[0]))
    initial = sum(ordered_groups, [])
    lead_line = next(g for g in groups if leader in g)
    other_line = next((g for g in groups if challenger in g), []) if challenger else []
    prefix = ("掲載並びとS回数から置く初周の仮説。実際の位置取りは未確認。" if known_lines else
              "並び未取得。初周の隊列は確定できず、車番列は計算用表示。")
    steps = [_evidence_phase("INITIAL", initial, prefix, ["PREDICTED_LINE_ORDER_ONLY"])]
    bell = _arrange(lead_line, initial)
    steps.append(_evidence_phase("BELL", bell,
        f"{leader}番が前へ動く場合を置く。" + (f"対抗する自力は{challenger}番。" if challenger else "同一枝では別線の仕掛けを置かない。"),
        ["LEADER_ATTACKS", f"CAR_{leader}"]))
    home = list(bell)
    if kind == "COUNTER":
        home_text = f"{leader}番の先行に対し{challenger}番が別線から仕掛ける。"
        actions = ["CHALLENGER_EARLY_COUNTER", f"CAR_{challenger}"]
    elif kind == "ATTACKER_FADE":
        home_text = f"{leader}番が先行を続ける。" + (f"{challenger}番との踏み合いを仮定する。" if challenger else "長い踏み出しで終盤に余力を欠く場合を置く。")
        actions = ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]
    else:
        home_text = f"{leader}番が先行位置を維持する場合。追走の成立は未検証。"
        actions = ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]
    steps.append(_evidence_phase("FINAL_HOME", home, home_text, actions))
    back = (_arrange(other_line, home) if kind == "COUNTER" else list(home))
    back_text = (f"{challenger}番の捲りが届き、別線が前に出る場合。" if kind == "COUNTER" else
                 f"{leader}番を先頭に最終バックへ入る場合。")
    steps.append(_evidence_phase("FINAL_BACK", back, back_text,
        ["CHALLENGER_MAKURI", f"CAR_{challenger}"] if kind == "COUNTER" else ["LEADER_TRIES_TO_HOLD_PACE", f"CAR_{leader}"]))
    corner = _arrange(finish[:2], back)
    corner_text = (f"{finish[0]}番が前を交わしに出る仮説。元の仕掛け役は{leader}番のまま記録。" if kind in ("FOLLOWER_PASS", "ATTACKER_FADE", "LATE_FINISH") else
                   "前のラインが4コーナーへ。")
    corner_text += " " + _finish_route_reason(finish[1], 2, groups, leader, finish[0], kind)
    steps.append(_evidence_phase("FOURTH_CORNER", corner, corner_text,
        ["FOLLOWER_SASHI_SCENARIO", f"CAR_{finish[0]}"] if kind == "FOLLOWER_PASS" else ["FRONT_LINE_CONTINUITY_UNVERIFIED"]))
    goal = _arrange(finish, corner)
    if kind == "ATTACKER_FADE":
        goal_text = f"最終バック先頭の仕掛け役{leader}番が少なくとも3番手以下へ下がる失速を仮定。{finish[0]}-{finish[1]}-{finish[2]}の順を候補にする。"
        goal_actions = ["FRONT_LEADER_PACE_FADE", f"CAR_{leader}"]
    else:
        goal_text = _finish_route_reason(finish[2], 3, groups, leader, finish[0], kind) + f" {finish[0]}-{finish[1]}-{finish[2]}を候補とする。実測着順ではない。"
        goal_actions = ["LATE_SPRINT_OVERTAKE", f"CAR_{finish[0]}"] if kind in ("FOLLOWER_PASS", "LATE_FINISH") else ["FOURTH_CORNER_ORDER_CONTINUES"]
    steps.append(_evidence_phase("GOAL", goal, goal_text, goal_actions))
    if not known_lines:
        for step in steps[:-1]:
            step["projected_order"] = None
            step["projected_top3"] = None
            step["position_unknown"] = True
            step["hypothesis_actions"] = ["POSITION_UNAVAILABLE_LINE_MISSING"]
            step["explanation"] = "並びの根拠が未取得のため、この局面の隊列は表示できない。Aの着順候補は能力資料のみから算出。"
    return steps


def _finish_candidates(profiles, head, line, leader, challenger, kind, groups, known_lines):
    """Scenario positions constrain candidates before support selection.

    A HOLD does not silently turn into a different-line counter win. A simple
    FOLLOWER_PASS leaves the attacker second; losing that attacker is a separate
    explicitly labeled FADE branch. This prevents a near-flat field from being
    expanded into every permutation with the same generic explanation.
    """
    cars = list(profiles)
    group_of = {c: g for g in groups for c in g}
    lead_line = group_of[leader]
    other_leaders = {g[0] for g in groups if g[0] not in (head, leader)}
    follower = lead_line[1] if len(lead_line) > 1 else None
    head_follower = line[1] if len(line) > 1 else None
    if not known_lines:
        allowed_seconds = set(cars) - {head}
    elif kind == "FOLLOWER_PASS":
        allowed_seconds = {leader}
    elif kind == "COUNTER":
        allowed_seconds = {leader}
        if head_follower is not None:
            allowed_seconds.add(head_follower)
    elif kind == "ATTACKER_FADE":
        # The actual attacking identity falls out of the first two, even when
        # its follower has already passed at the fourth corner.
        allowed_seconds = set(lead_line[1:]) | other_leaders
        if head_follower is not None:
            allowed_seconds.add(head_follower)
        allowed_seconds -= {head, leader}
    elif kind == "LATE_FINISH":
        allowed_seconds = {leader}
        if follower is not None:
            allowed_seconds.add(follower)
    else:  # HOLD
        allowed_seconds = {follower} if follower is not None else other_leaders
        # A rival leader can stay alongside the front line, but cannot push
        # past a much stronger follower on generic rank alone.
        if follower is not None:
            allowed_seconds |= {c for c in other_leaders
                if profiles[c]["second_strength"] >= profiles[follower]["second_strength"] * 1.15}
    allowed_seconds.discard(head)
    if not allowed_seconds:
        return
    p2 = {}
    for c in sorted(allowed_seconds):
        factor = 1.0
        if c in line:
            factor *= 1.25
        p2[c] = max(.001, profiles[c]["second_strength"]) * factor
    best2 = max(p2.values())
    seconds = [c for c in p2 if p2[c] >= best2 * .58]
    for second in seconds:
        p3 = {}
        # Third comes from a remaining line member or another line's front.
        # A remote third-wheel jumping both teammates is not invented just
        # because its four-month place rate looks attractive.
        if not known_lines:
            allowed_thirds = set(cars)
        else:
            allowed_thirds = set(line) | set(lead_line) | other_leaders
            second_group = group_of[second]
            if second_group[0] == second and len(second_group) > 1:
                allowed_thirds.add(second_group[1])
        for c in sorted(allowed_thirds):
            if c in (head, second):
                continue
            factor = 1.15 if c in line else 1.0
            p3[c] = max(.001, profiles[c]["third_strength"]) * factor
        best3 = max(p3.values())
        for third in sorted(p3):
            if p3[third] >= best3 * .50:
                yield [head, second, third], p2[second] / best2, p3[third] / best3


def _evidence_scenarios(profiles, groups):
    known_lines = groups is not None
    groups = groups or [[c] for c in profiles]
    leaders = [g[0] for g in groups]
    group_of = {c: g for g in groups for c in g}
    active = [c for c in leaders if profiles[c]["explicit_attack"]]
    # A missing statement about who attacks is a reason for uncertainty,
    # not permission to invent a decisive move record.
    if not active:
        active = list(leaders)
    active.sort(key=lambda c: (-profiles[c]["head_strength"], c))
    shells = []
    for leader in active:
        p = profiles[leader]
        lead_line = group_of[leader]
        others = [c for c in active if c != leader]
        best_other = max(others, key=lambda c: profiles[c]["head_strength"], default=None)
        lead_activity = p["lead_activity"]
        lead_support = .50 + .50 * (lead_activity if lead_activity is not None else .5)
        # HOLD is supported by the leader's observed attack/style; its support
        # still changes with actual H/B and decisive-move values.
        shells.append((leader, best_other, "HOLD", leader, lead_line, lead_support,
            [f"{leader}番が先手を取って残る条件。", _profile_facts(p)]))
        if known_lines and len(lead_line) >= 2:
            follower = lead_line[1]
            fp = profiles[follower]
            if fp["explicit_sashi"]:
                sashi = fp["sashi_share"] or 0
                support = (.50 + .50 * sashi) * (.8 + .2 * lead_support)
                shells.append((leader, best_other, "FOLLOWER_PASS", follower, lead_line, support,
                    [f"{leader}番の先行に{follower}番が追走し、差し切る条件。", _profile_facts(p), _profile_facts(fp)]))
            # Pace-fade is admitted only with a competing active line or high
            # observed lead activity. It is not a claim that the rider is hurt.
            if best_other is not None or (lead_activity is not None and lead_activity >= .65):
                late_heads = [follower] + ([best_other] if best_other is not None else [])
                for winner in dict.fromkeys(late_heads):
                    shells.append((leader, best_other, "ATTACKER_FADE", winner, group_of[winner],
                        .35 + .25 * (1 if best_other is not None else .5),
                        [f"仕掛け役{leader}番が踏み続けて終盤に失速する条件。", f"{winner}番が浮上する仮説。落車や負傷の推定ではない。", _profile_facts(p)]))
        for challenger in others:
            cp = profiles[challenger]
            # Actual counter evidence is more meaningful than taking only
            # the strongest arbitrary rival for every branch.
            counter = cp["observed"]["makuri"]
            if not cp["explicit_attack"]:
                continue
            counter_support = .50 + .35 * (counter / max(1, counter + (cp["observed"]["nige"] or 0)) if counter is not None else .5)
            shells.append((leader, challenger, "COUNTER", challenger, group_of[challenger], counter_support,
                [f"{leader}番の先行に対して{challenger}番が別線から反撃する条件。", _profile_facts(p), _profile_facts(cp)]))
        # Strong solo riders do not gain an invented follower. They can win a
        # late finish following a real attacking line's work.
        for g in groups:
            solo = g[0]
            if len(g) == 1 and solo != leader and profiles[solo]["explicit_sashi"]:
                shells.append((leader, solo, "LATE_FINISH", solo, [solo], .50,
                    [f"{leader}番が作った流れを単騎の{solo}番が直線で交わす条件。", _profile_facts(profiles[solo])]))
    scenarios = []
    seen = set()
    for leader, challenger, kind, head, finish_line, branch_support, reasons in shells:
        for ticket, second_fit, third_fit in _finish_candidates(profiles, head, finish_line, leader, challenger, kind, groups, known_lines):
            # Repeated identical shells must not manufacture support mass.
            key = (leader, challenger, kind, tuple(ticket))
            if key in seen:
                continue
            seen.add(key)
            head_power = max(.001, profiles[ticket[0]]["head_strength"])
            second_power = max(.001, profiles[ticket[1]]["second_strength"])
            third_power = max(.001, profiles[ticket[2]]["third_strength"])
            ability = head_power ** 2 * second_power ** 1.3 * third_power ** .8
            # A sees the same admissible scenario universe but prioritizes
            # observed ability. B changes support with the attack/follow roles.
            support_a = ability
            support_b = ability * branch_support * second_fit * third_fit
            scenario_id = f"{kind}_{leader}_{challenger or 0}_{'-'.join(map(str,ticket))}"
            ticket_reasons = [
                _finish_route_reason(ticket[1], 2, groups, leader, head, kind),
                _finish_route_reason(ticket[2], 3, groups, leader, head, kind),
            ] if known_lines else ["並び未取得のため2・3着の進路は確認できない。掲載連対率・得点による能力候補に限る。"]
            if known_lines and kind == "HOLD" and len(group_of[leader]) > 1 and ticket[1] != group_of[leader][1]:
                ticket_reasons.append(f"{group_of[leader][1]}番の番手追走が乱れ、別線の{ticket[1]}番が間へ入ることが必要。連係成功率は未検証。")
            scenarios.append({
                "scenario_id": scenario_id, "branch_kind": kind,
                "attacking_car": leader, "challenger_car": challenger,
                "faded_car": leader if kind == "ATTACKER_FADE" else None,
                "projected_3ren_tan": ticket,
                "six_phases": _scenario_path(groups, profiles, leader, challenger, kind, ticket, known_lines=known_lines),
                "rationale": list(reasons) + ticket_reasons,
                "support_A": support_a, "support_B": support_b,
                "known_line_hypothesis": known_lines,
            })
    need(scenarios, "NO_EVIDENCE_SUPPORTED_SCENARIOS")
    return scenarios


def select_evidence_tickets(candidates, *, market):
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
    selected = [dict(row, relative_to_peak=row["support"] / peak)
                for row in rows if row["support"] >= peak * floor - 1e-15]
    total = sum(x["support"] for x in rows)
    pct = round(floor * 100)
    name = "3連単" if market == "3t" else "2車単"
    meta = {
        "point_count": len(selected), "candidate_count": len(rows),
        "excluded_count": len(rows) - len(selected),
        "relative_support_floor": floor,
        "threshold_rule": f"最上位候補の研究支持値の{pct}%以上。点数の上限・穴埋めなし。",
        "count_reason": f"{name}の展開候補{len(rows)}通りを重複除去して評価。最上位の研究支持値の{pct}%以上を残した結果、{len(selected)}点。",
        "selected_support_fraction": sum(x["support"] for x in selected) / total,
        "calibrated_probability": False,
        "support_fraction_meaning": "作った展開候補内の支持値比率。的中率・現実の網羅率ではない。",
        "recommendation": "REVIEW_WIDE_CANDIDATES" if len(selected) > 30 else "CONDITIONAL_CANDIDATES",
        "width_warning": (f"候補が{len(selected)}点に分散。1点100円でも{len(selected) * 100:,}円になるため再検討。全候補の一括購入を勧める表示ではない。"
                          if len(selected) > 30 else ""),
        "excluded_candidates": [{"ticket": x["ticket"], "relative_to_peak": x["support"] / peak,
                                 "reason": "研究支持値がこの券種の採用境界より小さい。実現しないとの断定ではない。"}
                                for x in rows if x["support"] < peak * floor - 1e-15],
    }
    return selected, meta


def select_scenario_markets(scenarios, *, arm):
    """Both market pools aggregate the FULL universe before either selection.

    A takes the strongest evidence path per exact finish, preventing repeated
    descriptions from boosting a ticket. B does the same before summing distinct
    third-place outcomes into a 2T pair. Thus a stable 1-2 can survive while no
    single uncertain third survives the separate 3T selection.
    """
    need(arm in ("A", "B"), "ARM_INVALID")
    aggregate3 = {}
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
    aggregate2 = {}
    for t, row in aggregate3.items():
        pair = t[:2]
        if pair not in aggregate2:
            aggregate2[pair] = dict(ticket=list(pair), support=0.0, scenario_ids=[], reasons=[])
        target = aggregate2[pair]
        target["support"] += row["support"]
        target["scenario_ids"].extend(row["scenario_ids"])
        for reason in row["reasons"]:
            if reason not in target["reasons"]:
                target["reasons"].append(reason)
    chosen3, meta3 = select_evidence_tickets(list(aggregate3.values()), market="3t")
    chosen2, meta2 = select_evidence_tickets(list(aggregate2.values()), market="2t")
    return {
        "ranked_tickets": [x["ticket"] for x in chosen3],
        "ranked_2ren_tan": [x["ticket"] for x in chosen2],
        "point_count_3t": len(chosen3), "point_count_2t": len(chosen2),
        "markets": {"3t": {"tickets": [x["ticket"] for x in chosen3], "point_count": len(chosen3)},
                    "2t": {"tickets": [x["ticket"] for x in chosen2], "point_count": len(chosen2)}},
        "ticket_evidence": {"3t": chosen3, "2t": chosen2},
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
        chosen = select_scenario_markets(scenarios, arm=arm)
        total = sum(s[f"support_{arm}"] for s in scenarios)
        own_scenarios = [dict(s, relative_research_weight=s[f"support_{arm}"] / total) for s in scenarios]
        rationale = [
            ("Aは出典付きの能力資料を軸に、成立条件を置いた展開候補から買い目を選択。" if arm == "A" else
             "BはH/B・決まり手・並び・追走位置から、先行維持、番手差し、別線反撃、仕掛け役の失速を分岐。"),
            "買い目を先に12点へ揃える処理は廃止。各券種の候補支持値から点数が決まる。",
            "2車単は全着順候補の1・2着支持値を集計して独立選択。採用済み3連単の抜き出しではない。",
            "掲載4ヶ月の勝率・連対率を使用。直近の調子の上向き・下降や回復を示す指標ではない。",
            "支持値と選別境界は未学習の明示的な研究ルール。的中率・期待収益・オッズを算出したものではない。",
        ] + warnings
        if groups is None:
            rationale.append("Aも並びは未取得。初周から4コーナーは成立条件を確認できない仮置きで、能力資料に限る候補。")
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
        "market_support_floors": dict(MARKET_SUPPORT_FLOORS),
        "calibrated_probabilities": False, "production_weight_promotion": False,
        "formal_pre_cutoff_attestation": False,
        "feature_weights": {"head": {"points": .60, "win_rate": .30, "published_mark": .10},
                            "second": {"points": .60, "top2_rate": .35, "published_mark": .05},
                            "third": {"points": .55, "top3_rate": .40, "published_mark": .05}},
        "strength_transform": "得点差をmax(10点,場内最高最低差)で割る相対尺度。欠測はゼロで埋めず、その選手の既知指標のみ重みを再配分。",
        "candidate_windows": {"second_relative_floor": .58, "third_relative_floor": .50},
        "ticket_support": "能力の頭2乗×2着1.3乗×3着0.8乗。Bのみ分岐・位置適合を乗じる。全て未較正。",
    }
    output["feature_audit"] = {
        "riders": [profiles[c] for c in sorted(profiles)], "missing": missing,
        "used": ["competition_points", "published_mark", "win_rate", "top2_rate", "top3_rate", "H", "B", "S", "nige", "makuri", "sashi", "mark", "style", "explicit_sourced_attack_intent", "sourced_line_hypothesis"],
        "recorded_not_scored": ["gear"],
        "unknown_not_imputed": ["recent_form_trend", "verified_registration", "verified_fall_rest_return_history", "weather", "wind", "bank_affinity", "bank_geometry", "round_advancement_rule"],
        "gear_reason": "ギヤ比単体から有利・不利や調子を決める検証済み対応がないため、記録のみ。",
    }
    return output
