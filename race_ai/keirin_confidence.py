"""Source-bound, pre-cutoff research coherence assessments.

These thresholds are designed research rules, NOT calibrated hit probabilities.
The existing A/B generator, its hashes, and historical forecasts are unchanged.
Ticket selection affects coverage only; shrinking a ticket set cannot promote it.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import json
from math import isfinite
import re

from race_ai import keirin_nationwide_auto_generator as generator


SCHEMA = "RACE_AI_KEIRIN_CONFIDENCE_ASSESSMENT_V1"
UNIVERSE_SCHEMA = "RACE_AI_KEIRIN_CONFIDENCE_UNIVERSE_V1"
RULES_VERSION = "research-coherence-v1"
GRADES = {0: "未評価", 1: "低", 2: "中", 3: "高", 4: "激アツ"}
THRESHOLDS = {4:(.85, .85, .90, .90), 3:(.70, .70, .80, .80), 2:(.50, .50, .60, .50)}
MARKETS = frozenset(("3t", "2t"))
STRATEGIES = frozenset(("normal", "rollover"))
EVIDENCE_KINDS = frozenset(("canonical_b_orders", "authored_goals"))
COUNTER_FAMILIES = frozenset(("counterattack", "follower_sashi", "late_sprint", "pace_fade", "other"))
SOURCE_STATES = frozenset(("published_prediction", "not_applicable_girls", "unknown"))
ORIGINS = frozenset(("canonical_projection_v1", "independent_preselection_v1", "legacy_ticket_links"))
UNIVERSE_FIELDS = frozenset(("schema", "race_id", "source_as_of", "cutoff", "source_prediction_sha256",
    "source_facts_sha256", "cars", "evidence_kind", "candidate_origin", "source_status", "scenarios"))
SCENARIO_FIELDS = frozenset(("id", "role", "counter_family", "phases", "goal_candidates", "research_weight"))
PHASE_FIELDS = frozenset(("phase", "projected_order", "projected_top3", "hypothesis_actions", "actual_rider_position_video_verified"))
BUNDLE_FIELDS = frozenset(("schema", "rules_version", "race_id", "assessed_at", "cutoff", "source_prediction_sha256",
    "source_facts_sha256", "scenario_universe_sha256", "evaluations"))
ENTRY_FIELDS = frozenset(("grade", "rank", "market", "strategy", "tickets_sha256", "metrics", "reasons", "limitations"))
METRIC_FIELDS = frozenset(("scenario_count", "axis_cars", "axis_top2_share", "pair_top4_share", "triple_top6_share",
    "scenario_coverage", "major_uncovered_ids", "evidence_kind", "weight_basis", "late_phase_axis_presence"))
SHARE_FIELDS = frozenset(("axis_top2_share", "pair_top4_share", "triple_top6_share", "scenario_coverage", "late_phase_axis_presence"))
SHA = re.compile(r"^[0-9a-f]{64}$")
WEIGHT = re.compile(r"^(?:0\.[0-9]{12}|1\.000000000000)$")
CODE = re.compile(r"^[A-Z][A-Z0-9_]*$")
LIMITATIONS = [
    "数値の閾値は未校正の暫定研究ルールで、実績から校正した的中確率・回収率ではない。",
    "シナリオの研究上の重みと候補数の割合は、実際にその着順になる確率を示さない。",
    "6局面は出走前資料から置いた仮説であり、実際の走行位置や利益を保証しない。",
]


class ConfidenceAssessmentError(ValueError):
    pass


def _need(condition, code):
    if not condition:
        raise ConfidenceAssessmentError(code)


def _clock(value):
    try:
        return generator.when(value)
    except generator.AutomaticForecastError as exc:
        raise ConfidenceAssessmentError(str(exc)) from None


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise ConfidenceAssessmentError("NON_CANONICAL_CONFIDENCE_VALUE") from None


def _digest(value):
    return sha256(_canonical(value)).hexdigest()


def _hash(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def _strings(values, *, empty=True):
    return (type(values) is list and (empty or bool(values)) and
            all(type(x) is str and bool(x.strip()) for x in values) and
            len(values) == len(set(values)))


def _reason(code, message, scenario_ids=()):
    return dict(code=code, message=message, scenario_ids=list(scenario_ids))


def _ticket(value, places, cars):
    if type(value) is dict:
        value = value.get("combo")
    if type(value) is str:
        _need(re.fullmatch(r"[1-9](?:-[1-9]){1,2}", value) is not None, "TICKET_COMBO_INVALID")
        value = [int(x) for x in value.split("-")]
    _need(type(value) is list and len(value) == places and
          all(type(x) is int and x in cars for x in value) and len(set(value)) == places,
          "TICKET_CARS_INVALID")
    return tuple(value)


def _tickets(values, market, cars, *, empty=True):
    _need(type(values) is list and (empty or bool(values)), "TICKET_LIST_REQUIRED")
    tuples = [_ticket(value, 3 if market == "3t" else 2, cars) for value in values]
    _need(len(tuples) == len(set(tuples)), "DUPLICATE_TICKETS")
    return sorted(tuples)


def _ticket_hash(tuples):
    return _digest([list(t) for t in sorted(tuples)])


def _wire_weight(value):
    # Exact binary float, then decimal tie-up: ECMAScript Number.toFixed(12).
    return format(Decimal.from_float(float(value)).quantize(
        Decimal("0.000000000001"), rounding=ROUND_HALF_UP), "f")


def _validate_universe(universe):
    _need(type(universe) is dict and set(universe) == UNIVERSE_FIELDS and
          universe.get("schema") == UNIVERSE_SCHEMA, "CONFIDENCE_UNIVERSE_SCHEMA_INVALID")
    _need(type(universe["race_id"]) is str and generator.VENUE.fullmatch(universe["race_id"]), "CONFIDENCE_RACE_ID_INVALID")
    _need(_hash(universe["source_prediction_sha256"]) and _hash(universe["source_facts_sha256"]), "CONFIDENCE_SOURCE_HASH_INVALID")
    _clock(universe["source_as_of"]); _clock(universe["cutoff"])
    cars = universe["cars"]
    _need(type(cars) is list and 5 <= len(cars) <= 9 and
          all(type(x) is int and 1 <= x <= 9 for x in cars) and cars == sorted(cars) and len(set(cars)) == len(cars), "CONFIDENCE_CARS_INVALID")
    _need(type(universe["evidence_kind"]) is str and universe["evidence_kind"] in EVIDENCE_KINDS and
          type(universe["candidate_origin"]) is str and universe["candidate_origin"] in ORIGINS, "CONFIDENCE_EVIDENCE_KIND_INVALID")
    status = universe["source_status"]
    _need(type(status) is dict and set(status) == {"lineup", "required_missing", "conflicting_fields"} and
          type(status["lineup"]) is str and status["lineup"] in SOURCE_STATES and _strings(status["required_missing"]) and
          _strings(status["conflicting_fields"]), "CONFIDENCE_SOURCE_STATUS_INVALID")
    scenarios = universe["scenarios"]
    _need(type(scenarios) is list and 1 <= len(scenarios) <= 128, "CONFIDENCE_SCENARIOS_REQUIRED")
    ids = []
    for scenario in scenarios:
        _need(type(scenario) is dict and set(scenario) == SCENARIO_FIELDS, "CONFIDENCE_SCENARIO_SCHEMA_INVALID")
        sid = scenario["id"]
        _need(type(sid) is str and 1 <= len(sid) <= 120, "CONFIDENCE_SCENARIO_ID_INVALID")
        ids.append(sid)
        _need(type(scenario["role"]) is str and scenario["role"] in ("main", "counter") and
              ((scenario["role"] == "main" and scenario["counter_family"] is None) or
               (scenario["role"] == "counter" and type(scenario["counter_family"]) is str and
                scenario["counter_family"] in COUNTER_FAMILIES)), "CONFIDENCE_SCENARIO_ROLE_INVALID")
        phases = scenario["phases"]
        _need(type(phases) is list and all(type(p) is str and bool(p.strip()) for p in phases) or
              type(phases) is list and all(type(p) is dict for p in phases), "CONFIDENCE_PHASE_REPRESENTATION_INVALID")
        ordered = bool(phases) and type(phases[0]) is dict
        if universe["evidence_kind"] == "canonical_b_orders":
            _need(ordered, "CANONICAL_PHASE_ORDERS_REQUIRED")
        if ordered:
            for phase in phases:
                _need(set(phase) == PHASE_FIELDS and phase["phase"] in generator.PHASES and
                      type(phase["projected_order"]) is list and
                      all(type(x) is int for x in phase["projected_order"]) and
                      sorted(phase["projected_order"]) == cars and
                      phase["projected_top3"] == phase["projected_order"][:3] and
                      _strings(phase["hypothesis_actions"]) and
                      phase["actual_rider_position_video_verified"] is False, "CONFIDENCE_PHASE_ORDER_INVALID")
        goals = scenario["goal_candidates"]
        _need(type(goals) is dict and bool(goals) and set(goals) <= MARKETS, "CONFIDENCE_GOAL_MARKETS_INVALID")
        for market, values in goals.items():
            _need(type(values) is list and all(type(value) is list for value in values),
                  "CONFIDENCE_GOAL_ARRAYS_REQUIRED")
            _tickets(values, market, cars, empty=False)
        if ordered:
            for phase in phases:
                if phase["phase"] == "GOAL":
                    for market, values in goals.items():
                        places = 3 if market == "3t" else 2
                        _need(phase["projected_order"][:places] in values,
                              "CONFIDENCE_PHASE_GOAL_MISMATCH")
        weight = scenario["research_weight"]
        if universe["evidence_kind"] == "canonical_b_orders":
            _need(type(weight) is str and WEIGHT.fullmatch(weight) and float(weight) > 0, "CONFIDENCE_RESEARCH_WEIGHT_INVALID")
        else:
            _need(weight is None, "AUTHORED_WEIGHTS_MUST_BE_EQUAL")
    _need(len(ids) == len(set(ids)), "CONFIDENCE_DUPLICATE_SCENARIO_ID")
    if universe["evidence_kind"] == "canonical_b_orders":
        _need(abs(sum(float(s["research_weight"]) for s in scenarios)-1) <= 1e-8, "CONFIDENCE_RESEARCH_WEIGHT_SUM_INVALID")
    return universe


def universe_sha256(universe):
    """Full denominator and provenance hash; portable JSON contains no floats."""
    _validate_universe(universe)
    return _digest(universe)


def _empty_metrics(universe):
    return dict(scenario_count=len(universe["scenarios"]), axis_cars=[], axis_top2_share=None,
                pair_top4_share=None, triple_top6_share=None, scenario_coverage=None,
                major_uncovered_ids=[], evidence_kind=universe["evidence_kind"],
                weight_basis="canonical_relative_research" if universe["evidence_kind"] == "canonical_b_orders" else "equal_scenarios",
                late_phase_axis_presence=None)


def _blockers(universe, market, assessed_at, selected):
    reasons = []
    at, cutoff, asof = _clock(assessed_at), _clock(universe["cutoff"]), _clock(universe["source_as_of"])
    if at < asof:
        reasons.append(_reason("SOURCE_AFTER_ASSESSMENT", "資料の取得時点が評価時刻より後のため、出走前評価を付けられない。"))
    if (cutoff-at).total_seconds() < 65:
        reasons.append(_reason("AFTER_OR_TOO_CLOSE_TO_CUTOFF", "締切まで65秒未満、または締切後のため、新しい評価を付けない。"))
    status = universe["source_status"]
    if status["lineup"] == "unknown":
        reasons.append(_reason("LINEUP_UNCONFIRMED", "並びが未確認のため、高低を新しく判定する材料が不足している。"))
    if status["required_missing"]:
        reasons.append(_reason("REQUIRED_FACTS_MISSING", "評価に必要な資料が欠けている："+"、".join(status["required_missing"])))
    if status["conflicting_fields"]:
        reasons.append(_reason("SOURCE_FIELDS_CONFLICT", "資料に未解消の不一致がある："+"、".join(status["conflicting_fields"])))
    expected_origin = "canonical_projection_v1" if universe["evidence_kind"] == "canonical_b_orders" else "independent_preselection_v1"
    if universe["candidate_origin"] != expected_origin:
        reasons.append(_reason("INDEPENDENT_CANDIDATE_UNIVERSE_REQUIRED", "買い目から逆算した候補集合は使わず、選択前に独立して検討した展開候補を必要とする。"))
    scenarios = universe["scenarios"]
    if len(scenarios) < 2 or len({_digest([s["phases"], s["goal_candidates"]]) for s in scenarios}) < 2:
        reasons.append(_reason("DISTINCT_SCENARIOS_REQUIRED", "内容の異なる複数の6局面シナリオを必要とする。"))
    if not any(s["role"] == "main" for s in scenarios) or not any(s["role"] == "counter" for s in scenarios):
        reasons.append(_reason("COUNTER_SCENARIO_REQUIRED", "本筋と主要な対抗筋の両方が独立したシナリオとして必要。"))
    incomplete = [s["id"] for s in scenarios if len(s["phases"]) != 6 or
                  (s["phases"] and type(s["phases"][0]) is dict and
                   [p["phase"] for p in s["phases"]] != list(generator.PHASES))]
    if incomplete:
        reasons.append(_reason("SIX_PHASES_INCOMPLETE", "初周・打鐘・最終H・最終B・4角・ゴールの6局面がそろっていない。", incomplete))
    absent = [s["id"] for s in scenarios if market not in s["goal_candidates"]]
    if absent:
        reasons.append(_reason("MARKET_GOALS_MISSING", "この券種について独立して列挙したゴール候補が不足している。", absent))
    if not selected:
        reasons.append(_reason("EMPTY_TICKET_SET", "評価対象の買い目がない。"))
    return reasons


def _share(value):
    return round(min(1.0, max(0.0, value)), 12)


def _measure(universe, selected, market):
    scenarios = universe["scenarios"]
    raw = [float(s["research_weight"]) if universe["evidence_kind"] == "canonical_b_orders" else 1.0 for s in scenarios]
    total = sum(raw)
    weights = [x/total for x in raw]
    winners, pairs, triples = defaultdict(float), defaultdict(float), defaultdict(float)
    goals, covered, coverage = [], [], 0.0
    chosen = set(selected)
    for scenario, weight in zip(scenarios, weights):
        candidates = set(_tickets(scenario["goal_candidates"][market], market, universe["cars"], empty=False))
        goals.append(candidates)
        covered.append(candidates <= chosen)
        coverage += weight * len(candidates & chosen)/len(candidates)
        for ticket in candidates:
            amount = weight/len(candidates)
            winners[ticket[0]] += amount
            pairs[ticket[:2]] += amount
            if market == "3t":
                triples[ticket] += amount
    axis = sorted(sorted(winners, key=lambda car: (-winners[car], car))[:2])
    major = {i for i, weight in enumerate(weights) if weight >= .10-1e-12}
    for family in COUNTER_FAMILIES:
        members = [i for i, s in enumerate(scenarios) if s["counter_family"] == family]
        if members:
            major.add(min(members, key=lambda i: (-weights[i], scenarios[i]["id"])))
    missing = [scenarios[i]["id"] for i in sorted(major) if not covered[i]]
    late = None
    if all(type(s["phases"][0]) is dict for s in scenarios):
        late = _share(sum(w for s, w in zip(scenarios, weights)
                          if all(set(axis) & set(p["projected_order"][:2]) for p in s["phases"][3:])))
    metrics = _empty_metrics(universe)
    metrics.update(axis_cars=axis, axis_top2_share=_share(sum(winners[c] for c in axis)),
                   pair_top4_share=_share(sum(sorted(pairs.values(), reverse=True)[:4])),
                   triple_top6_share=_share(sum(sorted(triples.values(), reverse=True)[:6])) if market == "3t" else None,
                   scenario_coverage=_share(coverage), major_uncovered_ids=missing,
                   late_phase_axis_presence=late)
    return metrics


def grade_coherence_metrics(metrics, market):
    """Pure four-grade rule shared by separately validated research adapters.

    This only classifies already measured fixed-universe metrics. It does not
    create an assessment, validate source provenance, or waive cutoff gates.
    The thresholds are designed rules, not empirical success/return rates.
    """
    for rank, (axis, pair, triple, coverage) in THRESHOLDS.items():
        if (metrics["axis_top2_share"] >= axis and metrics["pair_top4_share"] >= pair and
            (market == "2t" or metrics["triple_top6_share"] >= triple) and
            metrics["scenario_coverage"] >= coverage and
            (rank < 3 or not metrics["major_uncovered_ids"])):
            return rank
    return 1


def _grade(metrics, market):
    # Keep the established formal evaluator's internal call surface unchanged.
    return grade_coherence_metrics(metrics, market)


def _percent(value):
    return f"{value*100:.1f}%"


def _next_level_reason(metrics, market, rank):
    if rank >= 4:
        return None
    next_rank = rank+1
    limits = THRESHOLDS[next_rank]
    checks = [("axis_top2_share", limits[0], "勝ち切り候補の集中"),
              ("pair_top4_share", limits[1], "1・2着候補の集中")]
    if market == "3t":
        checks.append(("triple_top6_share", limits[2], "3着までの候補の集中"))
    checks.append(("scenario_coverage", limits[3], "買い目に残る候補"))
    gaps = [f"{label}の候補内比重が約{_percent(metrics[key])}で基準{_percent(limit)}以上に未達"
            for key, limit, label in checks if metrics[key] < limit]
    if next_rank >= 3 and metrics["major_uncovered_ids"]:
        gaps.append("主要な筋の候補に未採用がある")
    return _reason("NEXT_LEVEL_NOT_MET", "「"+GRADES[next_rank]+"」に届かない点："+"、".join(gaps)+"。これらは的中率の基準ではない。",
                   metrics["major_uncovered_ids"] if next_rank >= 3 else [])


def evaluate_ticket_set(universe, tickets, *, market, strategy, assessed_at):
    """Assess a selected set against one immutable, independently built universe.

    Two-car authored inputs must explicitly supply two-car goal candidates.
    The universe's prediction hash identifies its parent, not a later selection.
    """
    _validate_universe(universe)
    _need(type(market) is str and market in MARKETS and type(strategy) is str and strategy in STRATEGIES,
          "CONFIDENCE_MARKET_OR_STRATEGY_INVALID")
    selected = _tickets(tickets, market, universe["cars"])
    reasons = _blockers(universe, market, assessed_at, selected)
    metrics = _empty_metrics(universe)
    rank = 0
    if not reasons:
        metrics = _measure(universe, selected, market)
        rank = _grade(metrics, market)
        axis_text = "・".join(map(str, metrics["axis_cars"]))
        pair_text = "1・2着候補の上位4組までの候補内比重は約"+_percent(metrics["pair_top4_share"])
        if market == "3t":
            pair_text += "、3着までの上位6組までは約"+_percent(metrics["triple_top6_share"])
        reasons = [
            _reason("AXIS_GOAL_CONCENTRATION", f"勝ち切り候補上位{len(metrics['axis_cars'])}車は{axis_text}番。複数の6局面シナリオのゴール候補内比重は約{_percent(metrics['axis_top2_share'])}（的中率ではない）。"),
            _reason("PARTNER_GOAL_CONCENTRATION", pair_text+"。買い目を選ぶ前の全展開に対する比重であり、的中率ではない。"),
            _reason("FIXED_UNIVERSE_COVERAGE", f"全{metrics['scenario_count']}シナリオを固定の分母とし、買い目に残る候補内比重は約{_percent(metrics['scenario_coverage'])}。点数の少なさへの加点はない。"),
        ]
        if metrics["major_uncovered_ids"]:
            families = {None:"本筋", "counterattack":"別線の仕掛け", "follower_sashi":"番手の差し",
                        "late_sprint":"直線の逆転", "pace_fade":"先行の失速", "other":"対抗展開"}
            omitted = [s["id"]+"（"+families[s["counter_family"]]+"）" for s in universe["scenarios"]
                       if s["id"] in metrics["major_uncovered_ids"]]
            reasons.append(_reason("MAJOR_SCENARIO_UNCOVERED", "主要な筋 "+"・".join(omitted)+" の候補に未採用があるため、高以上にはしない。", metrics["major_uncovered_ids"]))
        gap = _next_level_reason(metrics, market, rank)
        if gap is not None:
            reasons.append(gap)
        reasons.append(_reason("PROVISIONAL_RESEARCH_RULE", "未校正の暫定研究ルールにより「"+GRADES[rank]+"」と判定した。"))
    return dict(grade=GRADES[rank], rank=rank, market=market, strategy=strategy,
                tickets_sha256=_ticket_hash(selected), metrics=metrics,
                reasons=reasons, limitations=list(LIMITATIONS))


def _validate_baseline(snapshot, baseline):
    _need(type(baseline) is dict and baseline.get("schema") == generator.PREDICTION and
          _hash(baseline.get("prediction_sha256")) and
          baseline["prediction_sha256"] == generator.digest({k:v for k,v in baseline.items() if k != "prediction_sha256"}), "CONFIDENCE_BASELINE_HASH_INVALID")
    _need(type(baseline.get("race_id")) is str and generator.VENUE.fullmatch(baseline["race_id"]),
          "CONFIDENCE_BASELINE_RACE_ID_INVALID")
    for key in ("source_facts_sha256",):
        _need(_hash(baseline.get(key)), "CONFIDENCE_BASELINE_SOURCE_HASH_INVALID")
    for key in ("source_as_of", "generated_at", "published_cutoff_at"):
        _clock(baseline.get(key))
    _need(_clock(baseline["source_as_of"]) <= _clock(baseline["generated_at"]) and
          (_clock(baseline["published_cutoff_at"])-_clock(baseline["generated_at"])).total_seconds() >= 65,
          "CONFIDENCE_BASELINE_TIME_INVALID")
    _need(baseline.get("official_result_observed") is False and baseline.get("formal_model_promoted") is False and
          baseline.get("branch_weights_are_not_calibrated_probabilities") is True,
          "CONFIDENCE_RESEARCH_BASELINE_REQUIRED")
    _need(type(baseline.get("A")) is dict and type(baseline.get("B")) is dict and
          baseline["A"].get("model") == generator.MODEL_A and baseline["B"].get("model") == generator.MODEL_B,
          "CONFIDENCE_BASELINE_MODELS_INVALID")
    _need(all(type(baseline[name].get("ranked_tickets")) is list and bool(baseline[name]["ranked_tickets"])
              for name in ("A", "B")), "CONFIDENCE_BASELINE_TICKETS_REQUIRED")
    _need(type(baseline["B"].get("six_phase_scenarios")) is list and bool(baseline["B"]["six_phase_scenarios"]), "CONFIDENCE_BASELINE_SCENARIOS_REQUIRED")
    if snapshot is not None:
        try:
            generator.validate_snapshot(snapshot, computed_at=baseline["generated_at"])
        except generator.AutomaticForecastError as exc:
            raise ConfidenceAssessmentError(str(exc)) from None
        _need(baseline["source_facts_sha256"] == generator.digest(snapshot) and
              baseline.get("race_id") == snapshot["race_id"] and
              baseline["source_as_of"] == snapshot["as_of"] and
              baseline["published_cutoff_at"] == snapshot["published_cutoff_at"], "CONFIDENCE_SOURCE_BINDING_MISMATCH")


def canonical_universe(snapshot, baseline):
    """Normalize unchanged canonical B orders; A is evaluated against this too."""
    _validate_baseline(snapshot, baseline)
    scenarios = []
    for source in baseline["B"]["six_phase_scenarios"]:
        _need(type(source) is dict and set(source) == {"scenario_id", "six_phases", "projected_3ren_tan", "relative_research_weight"}, "CONFIDENCE_BASELINE_SCENARIO_INVALID")
        phases = source["six_phases"]
        _need(type(phases) is list and bool(phases) and all(type(p) is dict and
              _strings(p.get("hypothesis_actions")) and type(p.get("projected_order")) is list and
              all(type(c) is int for c in p["projected_order"]) for p in phases), "CONFIDENCE_BASELINE_PHASES_INVALID")
        actions = {action for phase in phases for action in phase["hypothesis_actions"]}
        family = None
        for action, value in (("FRONT_LEADER_PACE_FADE", "pace_fade"), ("LATE_SPRINT_OVERTAKE", "late_sprint"),
                              ("FOLLOWER_SASHI_SCENARIO", "follower_sashi"), ("CHALLENGER_EARLY_COUNTER", "counterattack"),
                              ("CHALLENGER_MAKURI", "counterattack")):
            if action in actions:
                family = value; break
        goal = source["projected_3ren_tan"]
        _need(type(goal) is list and len(goal) == 3 and phases[-1].get("projected_top3") == goal,
              "CONFIDENCE_BASELINE_GOAL_MISMATCH")
        weight = source["relative_research_weight"]
        _need(type(weight) in (int, float) and isfinite(weight) and 0 < weight <= 1, "CONFIDENCE_BASELINE_WEIGHT_INVALID")
        scenarios.append(dict(id=source["scenario_id"], role="counter" if family else "main", counter_family=family,
                              phases=deepcopy(phases), goal_candidates={"3t":[list(goal)], "2t":[list(goal[:2])]},
                              research_weight=_wire_weight(weight)))
    cars = sorted(snapshot["riders"][i]["car"] for i in range(len(snapshot["riders"]))) if snapshot is not None else sorted(scenarios[0]["phases"][0]["projected_order"])
    missing = []
    if snapshot is not None:
        for rider in sorted(snapshot["riders"], key=lambda r:r["car"]):
            if rider["competition_points"] <= 0:
                missing.append(f"riders.{rider['car']}.competition_points")
            if rider["style"] == "UNKNOWN":
                missing.append(f"riders.{rider['car']}.style")
    universe = dict(schema=UNIVERSE_SCHEMA, race_id=baseline["race_id"], source_as_of=baseline["source_as_of"],
                    cutoff=baseline["published_cutoff_at"], source_prediction_sha256=baseline["prediction_sha256"],
                    source_facts_sha256=baseline["source_facts_sha256"], cars=cars,
                    evidence_kind="canonical_b_orders", candidate_origin="canonical_projection_v1",
                    source_status=dict(lineup="not_applicable_girls" if snapshot is not None and snapshot["competition"] == "GIRLS" else "published_prediction",
                                       required_missing=missing, conflicting_fields=[]), scenarios=scenarios)
    _validate_universe(universe)
    return universe


def _baseline_bundle(snapshot, baseline, assessed_at):
    universe = canonical_universe(snapshot, baseline)
    _need(_clock(assessed_at) >= _clock(baseline["generated_at"]), "ASSESSMENT_BEFORE_PREDICTION")
    _need((_clock(baseline["published_cutoff_at"])-_clock(assessed_at)).total_seconds() >= 65,
          "ASSESSMENT_AFTER_OR_TOO_CLOSE_TO_CUTOFF")
    evaluations = {name:evaluate_ticket_set(universe, baseline[name]["ranked_tickets"], market="3t", strategy="normal", assessed_at=assessed_at)
                   for name in ("A", "B")}
    return dict(schema=SCHEMA, rules_version=RULES_VERSION, race_id=baseline["race_id"], assessed_at=assessed_at,
                cutoff=baseline["published_cutoff_at"], source_prediction_sha256=baseline["prediction_sha256"],
                source_facts_sha256=baseline["source_facts_sha256"], scenario_universe_sha256=universe_sha256(universe),
                evaluations=evaluations)


def assess_baseline(snapshot, baseline, *, assessed_at):
    """Create a new sidecar for a fresh pre-cutoff baseline, never an old original."""
    _need(snapshot is not None, "FULL_SNAPSHOT_REQUIRED_FOR_NEW_ASSESSMENT")
    return _baseline_bundle(snapshot, baseline, assessed_at)


def _validate_entry(entry):
    _need(type(entry) is dict and set(entry) == ENTRY_FIELDS and type(entry["rank"]) is int and
          entry["rank"] in GRADES and entry["grade"] == GRADES[entry["rank"]] and
          type(entry["market"]) is str and entry["market"] in MARKETS and
          type(entry["strategy"]) is str and entry["strategy"] in STRATEGIES and _hash(entry["tickets_sha256"]), "CONFIDENCE_ENTRY_SCHEMA_INVALID")
    metrics = entry["metrics"]
    _need(type(metrics) is dict and set(metrics) == METRIC_FIELDS and type(metrics["scenario_count"]) is int and
          0 <= metrics["scenario_count"] <= 128 and type(metrics["axis_cars"]) is list and
          len(metrics["axis_cars"]) <= 2 and all(type(c) is int and 1 <= c <= 9 for c in metrics["axis_cars"]) and
          len(set(metrics["axis_cars"])) == len(metrics["axis_cars"]) and
          _strings(metrics["major_uncovered_ids"]) and type(metrics["evidence_kind"]) is str and metrics["evidence_kind"] in EVIDENCE_KINDS and
          metrics["weight_basis"] in ("canonical_relative_research", "equal_scenarios"), "CONFIDENCE_METRICS_INVALID")
    for key in SHARE_FIELDS:
        value = metrics[key]
        _need(value is None or type(value) in (int, float) and isfinite(value) and 0 <= value <= 1, "CONFIDENCE_METRIC_RANGE_INVALID")
    _need(metrics["weight_basis"] == ("canonical_relative_research" if metrics["evidence_kind"] == "canonical_b_orders" else "equal_scenarios") and
          (entry["market"] != "2t" or metrics["triple_top6_share"] is None), "CONFIDENCE_METRIC_SCOPE_MISMATCH")
    if entry["rank"] == 0:
        _need(all(metrics[k] is None for k in SHARE_FIELDS) and not metrics["axis_cars"] and not metrics["major_uncovered_ids"], "UNASSESSED_METRICS_INVALID")
    else:
        _need(all(metrics[k] is not None for k in ("axis_top2_share", "pair_top4_share", "scenario_coverage")) and
              (entry["market"] != "3t" or metrics["triple_top6_share"] is not None) and
              _grade(metrics, entry["market"]) == entry["rank"], "CONFIDENCE_GRADE_METRICS_MISMATCH")
    _need(type(entry["reasons"]) is list and bool(entry["reasons"]), "CONFIDENCE_REASONS_REQUIRED")
    for reason in entry["reasons"]:
        _need(type(reason) is dict and set(reason) == {"code", "message", "scenario_ids"} and
              type(reason["code"]) is str and CODE.fullmatch(reason["code"]) and
              type(reason["message"]) is str and bool(reason["message"].strip()) and _strings(reason["scenario_ids"]), "CONFIDENCE_REASON_INVALID")
    _need(_strings(entry["limitations"], empty=False), "CONFIDENCE_LIMITATIONS_REQUIRED")


def checked_assessment(bundle, *, snapshot, baseline, sealed_at=None):
    """Validate a saved sidecar, without calling the assessment creation API.

    snapshot=None is only for displaying data already fully validated on entry
    and storage/decryption. It cannot re-attest missing source facts. Positive
    ratings still require exact reconstructed metrics, tickets, and a matching
    universe hash for one of the two admissible source-line contexts.
    """
    _need(type(bundle) is dict and set(bundle) == BUNDLE_FIELDS and bundle.get("schema") == SCHEMA and
          bundle.get("rules_version") == RULES_VERSION, "CONFIDENCE_BUNDLE_SCHEMA_INVALID")
    _validate_baseline(snapshot, baseline)
    _need(bundle["race_id"] == baseline["race_id"] and bundle["cutoff"] == baseline["published_cutoff_at"] and
          bundle["source_prediction_sha256"] == baseline["prediction_sha256"] and
          bundle["source_facts_sha256"] == baseline["source_facts_sha256"] and _hash(bundle["scenario_universe_sha256"]),
          "CONFIDENCE_BUNDLE_BINDING_MISMATCH")
    at, cutoff = _clock(bundle["assessed_at"]), _clock(bundle["cutoff"])
    _need(_clock(baseline["generated_at"]) <= at and (cutoff-at).total_seconds() >= 65, "CONFIDENCE_ASSESSMENT_TIME_INVALID")
    if sealed_at is not None:
        _need(at <= _clock(sealed_at) < cutoff, "CONFIDENCE_SEAL_TIME_INVALID")
    _need(type(bundle["evaluations"]) is dict and set(bundle["evaluations"]) == {"A", "B"}, "CONFIDENCE_AB_SCOPE_REQUIRED")
    for entry in bundle["evaluations"].values():
        _validate_entry(entry)
        _need(entry["market"] == "3t" and entry["strategy"] == "normal" and entry["metrics"]["evidence_kind"] == "canonical_b_orders",
              "CONFIDENCE_AB_SCOPE_REQUIRED")
    expected = _baseline_bundle(snapshot, baseline, bundle["assessed_at"])
    if snapshot is not None:
        _need(bundle == expected, "CONFIDENCE_RECOMPUTED_ASSESSMENT_MISMATCH")
    else:
        universe = canonical_universe(None, baseline)
        for name in ("A", "B"):
            _need(bundle["evaluations"][name]["tickets_sha256"] == expected["evaluations"][name]["tickets_sha256"], "CONFIDENCE_TICKETS_BINDING_MISMATCH")
        ranks = [bundle["evaluations"][name]["rank"] for name in ("A", "B")]
        _need(all(r == 0 for r in ranks) or all(r > 0 for r in ranks), "CONFIDENCE_PARTIAL_SOURCE_STATE_MISMATCH")
        for name in ("A", "B"):
            _need(bundle["evaluations"][name]["metrics"]["scenario_count"] == len(universe["scenarios"]),
                  "CONFIDENCE_SCENARIO_COUNT_MISMATCH")
        if all(r > 0 for r in ranks):
            _need(bundle["evaluations"] == expected["evaluations"], "CONFIDENCE_RECOMPUTED_ASSESSMENT_MISMATCH")
            hashes = {universe_sha256(universe)}
            universe["source_status"]["lineup"] = "not_applicable_girls"
            hashes.add(universe_sha256(universe))
            _need(bundle["scenario_universe_sha256"] in hashes, "CONFIDENCE_UNIVERSE_BINDING_MISMATCH")
    return deepcopy(bundle)
