"""Read-only six-course BOAT tactical research from retained, prior K results.

A race's winner method is NOT proof of who blocked whom. Never relabel a
racer's loss as an observed direct attack. No provider GET, model promotion,
live forecast edits, synthetic fills or source-secret access.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta, date
import math
import re

from .boat_racer_tendencies import profile_before, _ts, JST

SCHEMA = "RACE_AI_BOAT_SIX_COURSE_TACTICS_V1"
MATCHUP_SCHEMA = "RACE_AI_BOAT_SIX_COURSE_MATCHUP_V1"
METHODS = ("nige", "sashi", "makuri", "makurizashi", "nuki", "megumare")
SHA = re.compile(r"[0-9a-f]{64}\Z")
RACER = re.compile(r"[0-9]{4}\Z")
RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
CONDITIONS = ("1_nige", "1_loss_makuri", "1_loss_sashi",
              "1_loss_makurizashi", "2_nigashi", "2_sashi", "2_makuri",
              "3_kado_4_makuri_won") + tuple(
    f"{c}_{m}" for c in range(3, 7)
    for m in ("sashi", "makuri", "makurizashi"))


def _require(ok, code):
    if not ok:
        raise ValueError(code)


def _rate(n, d):
    return n / d if d else None


def _summary(rows):
    n = len(rows)
    wins = sum(x["finish"] == 1 for _, x in rows)
    top2 = sum(x["finish"] <= 2 for _, x in rows)
    top3 = sum(x["finish"] <= 3 for _, x in rows)
    return dict(starts=n, wins=wins, top2=top2, top3=top3,
                win_rate=_rate(wins, n), top2_rate=_rate(top2, n),
                top3_rate=_rate(top3, n))


def _day(yyyymmdd):
    _require(type(yyyymmdd) is str and re.fullmatch(r"\d{8}", yyyymmdd),
             "TACTICS_DAY_INVALID")
    return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:]))


def _validate_meeting(meeting, as_of):
    if meeting is None:
        return None
    _require(type(meeting) is dict and set(meeting) ==
             {"venue", "first_day_jst", "captured_at", "source_sha256"},
             "TACTICS_MEETING_IDENTITY_REQUIRED")
    _require(type(meeting["venue"]) is str and
             re.fullmatch(r"0[1-9]|1\d|2[0-4]", meeting["venue"]) and
             type(meeting["source_sha256"]) is str and
             SHA.fullmatch(meeting["source_sha256"]), "TACTICS_MEETING_PROOF_INVALID")
    start = date.fromisoformat(meeting["first_day_jst"])
    _require(start <= as_of.astimezone(JST).date() and
             _ts(meeting["captured_at"]) <= as_of, "TACTICS_MEETING_AFTER_AS_OF")
    return start


def _valid_method(method, course):
    return (method == "nige" and course == 1 or
            method in ("sashi", "makuri") and course >= 2 or
            method == "makurizashi" and course >= 3 or
            method in ("nuki", "megumare"))


def analyze_racer(records, *, racer_id, as_of, meeting=None, corner_evidence=None):
    """Return all six actual-course styles with denominators and no guesswork.

    Current-meeting information requires an explicit, upstream-confirmed
    opening day. 3-course kado-uke is only an observational 4-corner proxy,
    and is UNKNOWN without a source-backed 3:3 formation record.
    """
    clock = _ts(as_of)
    _require(type(racer_id) is str and RACER.fullmatch(racer_id),
             "TACTICS_RACER_ID_INVALID")
    _require(type(records) is list, "TACTICS_RECORDS_REQUIRED")
    base = profile_before(records, as_of=clock.isoformat(), racer_id=racer_id)
    opening = _validate_meeting(meeting, clock)
    corners = {} if corner_evidence is None else corner_evidence
    _require(type(corners) is dict, "TACTICS_FORMATION_PROOFS_REQUIRED")
    by_race = {r["race_id"]: r for r in records}
    for rid, evidence in corners.items():
        _require(rid in by_race and type(evidence) is dict and set(evidence) ==
                 {"slow_count", "corner_course", "captured_at", "source_sha256"},
                 "TACTICS_FORMATION_PROOF_INVALID")
        slow = evidence["slow_count"]
        _require(type(slow) is int and 1 <= slow <= 5 and
                 type(evidence["corner_course"]) is int and
                 evidence["corner_course"] == slow + 1 and
                 type(evidence["source_sha256"]) is str and
                 SHA.fullmatch(evidence["source_sha256"]) and
                 _ts(evidence["captured_at"]) <= clock,
                 "TACTICS_FORMATION_NOT_ATTESTED")

    selected = []
    for r in records:
        winner = next(x for x in r["entries"] if x["finish"] == 1)
        _require(_valid_method(r["winner_method"], winner["course"]),
                 "TACTICS_WINNER_METHOD_COURSE_MISMATCH")
        row = next((x for x in r["entries"] if x["racer_id"] == racer_id), None)
        if row is not None:
            selected.append((r, row))
    selected.sort(key=lambda pair: (_ts(pair[0]["cutoff_at"]),
                                    pair[0]["race_id"]), reverse=True)
    all_courses = {}
    for course in range(1, 7):
        rows = [(r, x) for r, x in selected if x["course"] == course]
        total = _summary(rows)
        wins = total["wins"]
        allowed = (("nige", "nuki", "megumare") if course == 1 else
                   ("sashi", "makuri", "nuki", "megumare") if course == 2 else
                   ("sashi", "makuri", "makurizashi", "nuki", "megumare"))
        by_method = Counter(r["winner_method"] for r, x in rows if x["finish"] == 1)
        total["winning_methods"] = {method: {
            "wins": by_method[method],
            "per_start": _rate(by_method[method], len(rows)),
            "among_wins": _rate(by_method[method], wins)} for method in allowed}
        total["last_10_in_course"] = _summary(rows[:10])
        all_courses[str(course)] = total

    ones = [(r, x) for r, x in selected if x["course"] == 1]
    lost = [(r, x) for r, x in ones if x["finish"] != 1]
    lost_method = Counter(r["winner_method"] for r, _ in lost)
    defeat = {m: {"count": lost_method[m],
                  "per_course_start": _rate(lost_method[m], len(ones)),
                  "among_losses": _rate(lost_method[m], len(lost))}
              for m in ("sashi", "makuri", "makurizashi")}
    twos = [(r, x) for r, x in selected if x["course"] == 2]
    nigashi = sum(r["winner_method"] == "nige" and any(
        p["course"] == 1 and p["finish"] == 1 for p in r["entries"])
        for r, _ in twos)

    # A kado-uke proxy must NOT turn a mere 3rd lane into a proven blocker.
    corners3 = [(r, x) for r, x in selected if x["course"] == 3
                and corners.get(r["race_id"], {}).get("slow_count") == 3]
    fourth_won = sum(r["winner_method"] == "makuri" and any(
        p["course"] == 4 and p["finish"] == 1 for p in r["entries"])
        for r, _ in corners3)
    nige_with_corner = sum(r["winner_method"] == "nige" and any(
        p["course"] == 1 and p["finish"] == 1 for p in r["entries"])
        for r, _ in corners3)
    now_day = clock.astimezone(JST).date()
    windows = {
        "last_10": _summary(selected[:10]),
        "last_30": _summary(selected[:30]),
        "last_90_days": _summary([(r, x) for r, x in selected
                                 if _day(r["race_id"][:8]) > now_day - timedelta(days=90)]),
        "last_365_days": _summary([(r, x) for r, x in selected
                                  if _day(r["race_id"][:8]) > now_day - timedelta(days=365)]),
        "current_meeting": None}
    if opening is not None:
        term = [(r, x) for r, x in selected if
                _day(r["race_id"][:8]) >= opening and
                r["race_id"][9:11] == meeting["venue"]]
        windows["current_meeting"] = {
            **_summary(term), "venue": meeting["venue"],
            "first_day_jst": meeting["first_day_jst"],
            "meeting_identity_requires_independent_proof": True}

    return {
        "schema": SCHEMA, "racer_id": racer_id, "as_of": clock.isoformat(),
        "sample_races": base["sample_races"], "windows": windows,
        "by_actual_course": all_courses,
        "first_course_losses": {
            "starts": len(ones), "losses": len(lost),
            "winner_method_NOT_proof_of_direct_attack": defeat},
        "second_course_nigashi": {
            "starts": len(twos), "first_course_nige": nigashi,
            "rate": _rate(nigashi, len(twos))},
        "third_course_kado_uke_proxy": {
            "formation_proven_starts": len(corners3),
            "fourth_course_makuri_wins": fourth_won,
            "fourth_course_makuri_win_rate": _rate(fourth_won, len(corners3)),
            "first_course_nige_wins": nige_with_corner,
            "first_course_nige_rate": _rate(nige_with_corner, len(corners3)),
            "direct_blocking_observed": False},
        "source_authenticity_independently_verified": False,
        "trained_or_calibrated_prediction": False,
        "production_forecast_modified": False}


def from_private_history_store(store, *, racer_id, as_of, meeting=None,
                               corner_evidence=None):
    """Offline reuse of existing append-only B/K store, including verified ST."""
    from .boat_history_store import aggregate
    days = store.visible_days(as_of)
    records = [r for day in days for r in day["history"]["records"]
               if any(p["racer_id"] == racer_id for p in r["entries"])]
    out = analyze_racer(records, racer_id=racer_id, as_of=as_of,
                        meeting=meeting, corner_evidence=corner_evidence)
    rows = store.history_rows([racer_id], as_of)
    out["windows"]["last_10_with_st"] = aggregate(rows[-10:])
    out["windows"]["last_30_with_st"] = aggregate(rows[-30:])
    for course in range(1, 7):
        subset = [r for r in rows if r["course"] == course]
        out["by_actual_course"][str(course)]["last_10_with_st"] = aggregate(subset[-10:])
    if meeting is not None:
        first = date.fromisoformat(meeting["first_day_jst"])
        out["windows"]["current_meeting_with_st"] = aggregate([
            r for r in rows if r["venue"] == meeting["venue"]
            and date.fromisoformat(r["day"]) >= first])
    return out


def matchup_features(profiles, *, entrant_by_course):
    """Six-entrant pre-race research features; real course must be attested."""
    _require(type(entrant_by_course) is dict and
             set(entrant_by_course) == set(range(1, 7)) and
             all(type(r) is str and RACER.fullmatch(r)
                 for r in entrant_by_course.values()) and
             len(set(entrant_by_course.values())) == 6,
             "TACTICS_SIX_COURSE_ASSIGNMENT_REQUIRED")
    _require(type(profiles) is dict and
             set(profiles) == set(entrant_by_course.values()),
             "TACTICS_ALL_SIX_PROFILES_REQUIRED")
    clocks = set()
    for rid, p in profiles.items():
        _require(type(p) is dict and p.get("schema") == SCHEMA and
                 p.get("racer_id") == rid, "TACTICS_RACER_PROFILE_MISMATCH")
        clocks.add(p["as_of"])
    _require(len(clocks) == 1, "TACTICS_MIXED_AS_OF_FORBIDDEN")
    def rate(course, method):
        x = profiles[entrant_by_course[course]]["by_actual_course"][str(course)]
        return x["winning_methods"].get(method, {}).get("per_start")
    one = profiles[entrant_by_course[1]]
    two = profiles[entrant_by_course[2]]
    three = profiles[entrant_by_course[3]]
    losing = one["first_course_losses"]["winner_method_NOT_proof_of_direct_attack"]
    features = {
        "1_nige": rate(1, "nige"),
        "1_loss_makuri": losing["makuri"]["per_course_start"],
        "1_loss_sashi": losing["sashi"]["per_course_start"],
        "1_loss_makurizashi": losing["makurizashi"]["per_course_start"],
        "2_nigashi": two["second_course_nigashi"]["rate"],
        "2_sashi": rate(2, "sashi"), "2_makuri": rate(2, "makuri"),
        "3_kado_4_makuri_won": three["third_course_kado_uke_proxy"]["fourth_course_makuri_win_rate"]}
    for course in range(3, 7):
        for method in ("sashi", "makuri", "makurizashi"):
            features[f"{course}_{method}"] = rate(course, method)
    return {"schema": MATCHUP_SCHEMA, "by_course_racer_ids": dict(entrant_by_course),
            "features": features, "conditional_escape_probability": None,
            "production_forecast_modified": False,
            "feature_missing": sorted(k for k, v in features.items() if v is None)}


def _wilson(successes, total):
    z = 1.959963984540054
    p = successes / total
    denom = 1 + z*z/total
    center = (p + z*z/(2*total)) / denom
    radius = z * math.sqrt((p*(1-p) + z*z/(4*total))/total)/denom
    return [center - radius, center + radius]


def prior_analogue_escape(matchup, examples, *, as_of, current_race_id,
                          minimum_support=30, tolerance=0.15):
    """Retrospective matched escape share, NOT calibrated future probability."""
    clock = _ts(as_of)
    _require(type(matchup) is dict and matchup.get("schema") == MATCHUP_SCHEMA,
             "TACTICS_MATCHUP_REQUIRED")
    values = matchup["features"]
    _require(type(values) is dict and set(CONDITIONS) <= set(values),
             "TACTICS_ALL_SIX_COURSE_FEATURES_REQUIRED")
    if any(values[key] is None for key in CONDITIONS):
        return {"status": "HOLD_FEATURE_MISSING", "support": 0,
                "empirical_escape_rate": None, "calibrated_probability": None}
    _require(type(examples) is list and len(examples) <= 100000 and
             type(minimum_support) is int and minimum_support >= 30 and
             type(tolerance) in (float, int) and 0 <= tolerance <= 1,
             "TACTICS_RESEARCH_SETTINGS_INVALID")
    _require(all(type(values[k]) in (float, int) and
                 math.isfinite(values[k]) and 0 <= values[k] <= 1
                 for k in CONDITIONS), "TACTICS_RESEARCH_FEATURE_INVALID")
    expected = {"race_id", "features_as_of", "cutoff_at", "result_captured_at",
                "source_sha256", "winner_course", "winner_method", "features"}
    seen, similar = set(), []
    for row in examples:
        _require(type(row) is dict and set(row) == expected,
                 "TACTICS_EXAMPLE_SCHEMA_INVALID")
        rid = row["race_id"]
        _require(type(rid) is str and RACE.fullmatch(rid) and
                 rid not in seen and rid != current_race_id,
                 "TACTICS_EXAMPLE_DUPLICATE_OR_TARGET")
        seen.add(rid)
        _require(_ts(row["features_as_of"]) < _ts(row["cutoff_at"]) <
                 _ts(row["result_captured_at"]) < clock and
                 _ts(row["cutoff_at"]).astimezone(JST).strftime("%Y%m%d") == rid[:8],
                 "TACTICS_EXAMPLE_TIME_LEAKAGE")
        _require(type(row["source_sha256"]) is str and
                 SHA.fullmatch(row["source_sha256"]) and
                 type(row["winner_course"]) is int and
                 1 <= row["winner_course"] <= 6 and
                 row["winner_method"] in METHODS and
                 _valid_method(row["winner_method"], row["winner_course"]),
                 "TACTICS_EXAMPLE_RESULT_INVALID")
        features = row["features"]
        _require(type(features) is dict and set(features) == set(CONDITIONS) and
                 all(type(v) in (int, float) and math.isfinite(v)
                     and 0 <= v <= 1 for v in features.values()),
                 "TACTICS_EXAMPLE_FEATURES_INVALID")
        dist = math.fsum(abs(values[k] - features[k])
                         for k in CONDITIONS)/len(CONDITIONS)
        if dist <= tolerance:
            similar.append((dist, rid, row["winner_course"] == 1 and
                            row["winner_method"] == "nige"))
    similar.sort()
    if len(similar) < minimum_support:
        return {"status": "HOLD_INSUFFICIENT_PRIOR_ANALOGUES",
                "support": len(similar), "empirical_escape_rate": None,
                "calibrated_probability": None}
    n = len(similar)
    wins = sum(hit for _, _, hit in similar)
    return {"status": "DESCRIPTIVE_ANALOGUES_ONLY", "support": n,
            "inside_escape_wins": wins, "empirical_escape_rate": wins/n,
            "wilson_95": _wilson(wins, n),
            "calibrated_probability": None, "forward_validation_completed": False,
            "production_forecast_modified": False}
