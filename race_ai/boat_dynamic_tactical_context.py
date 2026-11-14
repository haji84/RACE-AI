"""Source-free P1 tactical context: tilt, entry pressure, dynamic kado and qualifying.

The official 2025-08-12 tilt table is a dated REFERENCE, never proof of
current permission. All current inputs and eligibility must be independently
attested upstream. No provider requests or live model coefficient changes.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import math
import re

from .boat_racer_tendencies import _ts, profile_before, JST

SCHEMA = "RACE_AI_BOAT_P1_DYNAMIC_TACTICAL_CONTEXT_V1"
ENTRY_SCHEMA = "RACE_AI_BOAT_INWARD_ENTRY_RESEARCH_V1"
QUAL_SCHEMA = "RACE_AI_BOAT_EVENT_QUALIFYING_CONTEXT_V1"
MIX_SCHEMA = "RACE_AI_BOAT_SIX_WAY_INTERACTIONS_V1"
OFFICIAL_TILT_URL = "https://www.boatrace.jp/owsp/sp/site/pr_info/2015/08/97/"
OFFICIAL_TILT_AS_OF = "2025-08-12"
TILT_BASE = (-0.5, 0., 0.5, 1., 1.5, 2., 3.)
# Only Hamanako, Biwako and Wakamatsu have 2.5 in the dated official list.
TILT_REFERENCES = {
    **{f"{c:02d}": TILT_BASE for c in
       (4, 5, 7, 8, 9, 10, 13, 14, 15, 16, 17, 19, 21, 23, 24)},
    "01": TILT_BASE[:4], "02": TILT_BASE[:3],
    "03": TILT_BASE[:6], "06": tuple(sorted(TILT_BASE + (2.5,))),
    "11": tuple(sorted(TILT_BASE + (2.5,))),
    "12": TILT_BASE[:5], "18": TILT_BASE[:6],
    "20": tuple(sorted(TILT_BASE + (2.5,))),
    "22": TILT_BASE[:5],
}
VENUES = frozenset(f"{n:02d}" for n in range(1, 25))
RECEIPT_FIELDS = frozenset(("captured_at", "source_sha256"))
TILT_MEASUREMENTS = frozenset(("frame", "racer_id", "course", "tilt_deg"))
RACER = re.compile(r"[0-9]{4}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def _need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _stamp(value):
    return _ts(value)


def _proof(obj, before, name):
    _need(type(obj) is dict and set(obj) == RECEIPT_FIELDS and
          type(obj["source_sha256"]) is str and
          SHA.fullmatch(obj["source_sha256"]) and
          _stamp(obj["captured_at"]) <= _stamp(before),
          "TACTICS_" + name + "_PROOF_INVALID")


def _number(v):
    return type(v) in (int, float) and math.isfinite(v)


def _frac(n, d):
    return n / d if d else None


def _counted(races):
    total = len(races)
    win = sum(finish == 1 for finish in races)
    top3 = sum(finish <= 3 for finish in races)
    return {"starts": total, "wins": win, "top3": top3,
            "win_rate": _frac(win, total), "top3_rate": _frac(top3, total)}


def entry_response_profile(records, *, racer_id, as_of):
    """Actual-course histories identify recorded inward/outward moves, not intent.

    Being displaced outward is NOT proof a specific opponent caused it;
    merely holding frame when another inward move occurs is not a filmed block.
    """
    base = profile_before(records, as_of=as_of, racer_id=racer_id)
    inward, outward, challenged, held, changed = [], [], [], [], []
    for race in records:
        selected = next((r for r in race["entries"] if r["racer_id"] == racer_id), None)
        if selected is None:
            continue
        f, c, finish = selected["frame"], selected["course"], selected["finish"]
        if c < f:
            inward.append(finish)
        if c > f:
            outward.append(finish)
        pressure = any(row["frame"] > f and row["course"] <= f
                       for row in race["entries"] if row["racer_id"] != racer_id)
        if pressure:
            challenged.append(finish)
            if c == f:
                held.append(finish)
            elif c > f:
                changed.append(finish)
    return {
        "schema": ENTRY_SCHEMA, "racer_id": racer_id, "as_of": _stamp(as_of).isoformat(),
        "historical_races": base["sample_races"],
        "moved_inward": _counted(inward),
        "moved_outward": _counted(outward),
        "outer_racer_entered_inside_original_frame": _counted(challenged),
        "kept_original_course_in_that_setting": _counted(held),
        "moved_outward_in_that_setting": _counted(changed),
        "pit_departure_or_intent_observed": False,
        "direct_defense_observed": False,
        "replay_video_proof_needed_for_causal_block": True,
        "independently_authenticated": False,
    }


def p1_tilt_entry_context(*, race_id, venue_code, as_of, cutoff_at,
                          exhibition, receipt, slow_count,
                          current_venue_rule=None):
    """Provisional P1 formation. Actual race course after close is forbidden."""
    clock = _stamp(as_of)
    match = re.fullmatch(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])", race_id) if type(race_id) is str else None
    _need(match is not None and type(venue_code) is str and venue_code in VENUES and
          match[2] == venue_code and match[1] == clock.astimezone(JST).strftime("%Y%m%d") and
          clock < _stamp(cutoff_at), "TACTICS_P1_RACE_OR_CLOCK_INVALID")
    _proof(receipt, as_of, "EXHIBITION")
    _need(type(exhibition) is list and len(exhibition) == 6,
          "TACTICS_SIX_EXHIBITION_ROWS_REQUIRED")
    _need(type(slow_count) is int and 1 <= slow_count <= 5,
          "TACTICS_FORMATION_SLOW_COUNT_UNKNOWN")
    current_options = None
    if current_venue_rule is not None:
        _need(type(current_venue_rule) is dict and
              set(current_venue_rule) == {"venue_code", "effective_on_jst",
                                          "allowed_angles", "receipt"},
              "TACTICS_VENUE_RULE_INVALID")
        _need(current_venue_rule["venue_code"] == venue_code and
              date.fromisoformat(current_venue_rule["effective_on_jst"]) <=
              clock.astimezone(JST).date(), "TACTICS_VENUE_RULE_DATE_MISMATCH")
        _proof(current_venue_rule["receipt"], as_of, "VENUE_TILT")
        allowed = current_venue_rule["allowed_angles"]
        _need(type(allowed) is list and len(allowed) >= 1 and
              all(_number(x) and -0.5 <= x <= 3 and x*2 == int(x*2)
                  for x in allowed) and len(set(allowed)) == len(allowed),
              "TACTICS_VENUE_ANGLES_INVALID")
        current_options = set(allowed)
    courses, frames, racers = set(), set(), set()
    rows = []
    for row in exhibition:
        _need(type(row) is dict and set(row) == TILT_MEASUREMENTS,
              "TACTICS_EXHIBITION_ROW_INVALID")
        f, c, rid, tilt = row["frame"], row["course"], row["racer_id"], row["tilt_deg"]
        _need(type(f) is int and 1 <= f <= 6 and f not in frames and
              type(c) is int and 1 <= c <= 6 and c not in courses and
              type(rid) is str and RACER.fullmatch(rid) and rid not in racers,
              "TACTICS_EXHIBITION_DUPLICATE_OR_UNRESOLVED")
        _need(tilt is None or _number(tilt) and tilt*2 == int(tilt*2)
              and -0.5 <= tilt <= 3, "TACTICS_TILT_INVALID")
        if current_options is not None and tilt is not None:
            _need(tilt in current_options, "TACTICS_TILT_NOT_ALLOWED_AT_VENUE")
        frames.add(f); courses.add(c); racers.add(rid)
        rows.append({"frame": f, "course": c, "racer_id": rid,
                     "tilt_deg": tilt, "tilt_known": tilt is not None,
                     "outer_high_tilt_marker": bool(tilt is not None and
                        tilt >= 1.5 and (c >= 4 or c == slow_count + 1)),
                     "dated_2025_reference_allowed":
                         None if tilt is None else tilt in TILT_REFERENCES[venue_code],
                     "is_kado": c == slow_count + 1,
                     "is_kado_uke": c == slow_count})
    by_course = {r["course"]: r["racer_id"] for r in rows}
    threats = [r["course"] for r in rows if r["outer_high_tilt_marker"]]
    return {
        "schema": SCHEMA, "race_id": race_id, "venue_code": venue_code,
        "as_of": clock.isoformat(), "provisional_from_start_exhibition": True,
        "actual_race_course_unknown_before_cutoff": True,
        "source_receipt_claim_not_independent_attestation": True,
        "rule_status": ("CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH"
                        if current_options is not None else
                        "HOLD_CURRENT_VENUE_TILT_RULE_UNVERIFIED"),
        "official_dated_reference": {"as_of": OFFICIAL_TILT_AS_OF,
                                     "source_url": OFFICIAL_TILT_URL,
                                     "allowed_angles": list(TILT_REFERENCES[venue_code])},
        "rows": sorted(rows, key=lambda x: x["course"]),
        "formation": {
            "slow_count": slow_count, "dash_count": 6-slow_count,
            "kado_course": slow_count+1, "kado_racer_id": by_course[slow_count+1],
            "kado_uke_course": slow_count,
            "kado_uke_racer_id": by_course[slow_count],
            "is_three_three": slow_count == 3},
        "outer_high_tilt_courses": sorted(threats),
        "high_tilt_is_not_proven_attack_success": True,
        "calibrated_attack_probability": None}


def qualifying_standings(*, event_id, venue_code, as_of, event_rules,
                         standings, standings_receipt, board_complete=False):
    """Published event ranks/points: provisional cutline, not qualification."""
    clock = _stamp(as_of)
    _need(type(event_id) is str and 1 <= len(event_id) <= 128 and
          type(venue_code) is str and venue_code in VENUES,
          "TACTICS_QUAL_EVENT_INVALID")
    _need(type(event_rules) is dict and set(event_rules) ==
          {"event_id", "venue_code", "qualifying_slots", "minimum_starts",
           "receipt"}, "TACTICS_EVENT_RULES_REQUIRED")
    _need(event_rules["event_id"] == event_id and
          event_rules["venue_code"] == venue_code and
          type(event_rules["qualifying_slots"]) is int and
          1 <= event_rules["qualifying_slots"] <= 60 and
          type(event_rules["minimum_starts"]) is int and
          0 <= event_rules["minimum_starts"] <= 20,
          "TACTICS_EVENT_RULES_MISMATCH")
    _proof(event_rules["receipt"], as_of, "EVENT_RULES")
    _proof(standings_receipt, as_of, "EVENT_STANDINGS")
    _need(type(board_complete) is bool and type(standings) is list
          and len(standings) <= 100, "TACTICS_STANDINGS_INVALID")
    fields = {"racer_id", "official_rank", "total_points", "deductions",
              "official_rate", "starts", "remaining_starts", "eligibility"}
    result, seen, ranks = [], set(), set()
    for row in standings:
        _need(type(row) is dict and set(row) == fields,
              "TACTICS_STANDING_ROW_REQUIRED")
        rid, rank = row["racer_id"], row["official_rank"]
        _need(type(rid) is str and RACER.fullmatch(rid) and rid not in seen
              and (rank is None or type(rank) is int and rank >= 1
                   and rank not in ranks), "TACTICS_STANDING_ID_OR_RANK_INVALID")
        seen.add(rid)
        if rank is not None:
            ranks.add(rank)
        _need(_number(row["total_points"]) and
              _number(row["deductions"]) and
              row["deductions"] >= 0 and
              type(row["starts"]) is int and row["starts"] >= 0 and
              (row["remaining_starts"] is None or
               type(row["remaining_starts"]) is int and
               0 <= row["remaining_starts"] <= 20) and
              (row["official_rate"] is None or
               _number(row["official_rate"]) and
               0 <= row["official_rate"] <= 20) and
              row["eligibility"] in ("ELIGIBLE", "EXCLUDED", "UNVERIFIED"),
              "TACTICS_STANDING_AMOUNT_INVALID")
        result.append({**row, "status": "PROVISIONAL_NOT_CLINCHED"})
    slots = event_rules["qualifying_slots"]
    border = next((r["official_rate"] for r in result
                   if r["official_rank"] == slots and
                   r["eligibility"] == "ELIGIBLE"), None)
    safe_border = (board_complete and len(result) >= slots and
                   border is not None and all(r["official_rank"] is not None
                   for r in result) and
                   {r["official_rank"] for r in result} == set(range(1, len(result)+1)))
    gap = {r["racer_id"]: (round(r["official_rate"]-border, 4) if
          safe_border and r["official_rate"] is not None else None)
           for r in result}
    return {
        "schema": QUAL_SCHEMA, "event_id": event_id, "venue_code": venue_code,
        "as_of": clock.isoformat(),
        "qualifying_slots": slots, "minimum_starts": event_rules["minimum_starts"],
        "board_complete_claim": board_complete,
        "provisional_cutline_rate": border if safe_border else None,
        "border_status": ("CURRENT_RANK_ONLY_NOT_FINAL" if safe_border else
                          "HOLD_NO_COMPLETE_OFFICIAL_BOARD"),
        "participants": sorted(result, key=lambda r:
                               r["official_rank"] if r["official_rank"] is not None
                               else 99999),
        "rate_gap_to_current_cutline": gap,
        "final_qualification_certified": False,
        "needed_points_for_final_qualification": None,
        "tie_break_and_exclusions_require_event_rules": True,
        "source_receipts_require_independent_readback": True}


def six_way_research_context(matchup, tilt, entry_profiles, qualification=None):
    """Compose pre-close covariates, never multiply win rates into a forecast."""
    from .boat_six_course_tactical_features import MATCHUP_SCHEMA
    _need(type(matchup) is dict and matchup.get("schema") == MATCHUP_SCHEMA
          and type(tilt) is dict and tilt.get("schema") == SCHEMA,
          "TACTICS_RESEARCH_MIX_INPUT_REQUIRED")
    ids = matchup["by_course_racer_ids"]
    by_course = {str(row["course"]): row["racer_id"] for row in tilt["rows"]}
    _need(type(ids) is dict and
          {str(c): v for c, v in ids.items()} == by_course,
          "TACTICS_ENTRY_COURSE_CHANGED_OR_UNVERIFIED")
    _need(type(entry_profiles) is dict and
          set(entry_profiles) == set(ids.values()) and
          all(type(v) is dict and v.get("schema") == ENTRY_SCHEMA and
              v.get("racer_id") == rid and
              v.get("as_of") == tilt["as_of"]
              for rid, v in entry_profiles.items()),
          "TACTICS_ENTRY_STUDY_MISSING_OR_ASOF_MISMATCH")
    if qualification is not None:
        _need(type(qualification) is dict and
              qualification.get("schema") == QUAL_SCHEMA and
              qualification.get("venue_code") == tilt["venue_code"] and
              qualification.get("as_of") == tilt["as_of"],
              "TACTICS_QUALIFYING_NOT_SAME_RACE_TIME")
    per_course = {}
    for row in tilt["rows"]:
        p = entry_profiles[row["racer_id"]]
        per_course[str(row["course"])] = {
            "frame": row["frame"],
            "racer_id": row["racer_id"],
            "tilt_deg": row["tilt_deg"],
            "outer_high_tilt_marker": row["outer_high_tilt_marker"],
            "historical_inward_move_win_rate": p["moved_inward"]["win_rate"],
            "historical_outward_move_top3_rate": p["moved_outward"]["top3_rate"],
            "inner_pressure_kept_course_rate":
                 _frac(p["kept_original_course_in_that_setting"]["starts"],
                       p["outer_racer_entered_inside_original_frame"]["starts"])}
    return {
        "schema": MIX_SCHEMA, "race_id": tilt["race_id"],
        "as_of": tilt["as_of"], "formation": tilt["formation"],
        "six_course_features": matchup["features"],
        "entry_tilt_cross_features": per_course,
        "qualifying_rank_and_point_gaps":
             None if qualification is None else {
                 "event_id": qualification["event_id"],
                 "border_status": qualification["border_status"],
                 "rate_gaps": qualification["rate_gap_to_current_cutline"],
                 "standings": qualification["participants"]},
        "current_venue_rule_status": tilt["rule_status"],
        "conditional_escape_probability": None,
        "outer_attack_probability": None,
        "future_calibration_completed": False,
        "source_authenticity_independently_verified": False,
        "original_model_unchanged": True}
