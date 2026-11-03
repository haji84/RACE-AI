"""Historical BOAT racer-entry tendencies, from already verified past results.

Research feature builder, NOT a forecast model. Race winner's kimarite
characterizes the race outcome, not a proven mechanical failure by a loser.
Past actual entries must NEVER be treated as today's before-info entries.
No network, BOATERS scraping, leakage, age bonus, or model promotion.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))
RACE_ID = re.compile(r"^(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])$")
METHODS = frozenset({"nige", "sashi", "makuri", "makurizashi", "nuki", "megumare"})


def _ts(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value):
        raise ValueError("timezone-aware timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp has no zone")
    return result


def profile_before(records: list[dict], *, as_of: str, racer_id: str) -> dict:
    """Produce descriptive denominators and rates only, no invented weak labels.

    records must have verified result capture timestamp. Excludes abnormal
    results by rejection, not by silently treating disqualifications as losses.
    Caller is responsible for proving each provided source authenticity.
    """
    clock = _ts(as_of)
    if not isinstance(racer_id, str) or re.fullmatch(r"\d{4}", racer_id) is None:
        raise ValueError("registered four-digit racer ID required")
    if not isinstance(records, list) or len(records) > 25000:
        raise ValueError("bounded verified history list required")
    fields = {"race_id", "cutoff_at", "result_captured_at", "winner_method", "entries", "source_sha256"}
    seen = set()
    courses = {str(i): {"starts": 0, "wins": 0, "top2": 0, "top3": 0,
                        "win_rate": None} for i in range(1, 7)}
    # Frame-versus-actual-course samples are needed to model future
    # pre-race entry changes. A lane number is NEVER proof of actual entry.
    frame_course_counts = {str(f): {str(course): 0 for course in range(1,7)}
                           for f in range(1,7)}
    win_method_by_course = {str(course): {method: 0 for method in sorted(METHODS)}
                            for course in range(1,7)}
    selected_races = []
    stats = {"entered_inward": 0, "entered_from_outer_to_1_3": 0,
             "displaced_outward": 0, "displaced_top3": 0,
             "crossed_by_outer_frame": 0, "crossed_by_outer_frame_top3": 0,
             "in1_starts": 0, "in1_wins": 0,
             "in1_losses_by_winner_method": {k: 0 for k in sorted(METHODS)}}
    included = []
    for race in records:
        if not isinstance(race, dict) or set(race) != fields:
            raise ValueError("exact verified historical result fields required")
        rid = race["race_id"]
        m = RACE_ID.fullmatch(rid) if isinstance(rid, str) else None
        if m is None or rid in seen:
            raise ValueError("invalid or duplicate race identifier")
        seen.add(rid)
        cutoff = _ts(race["cutoff_at"])
        result_ts = _ts(race["result_captured_at"])
        if (cutoff.utcoffset() != timedelta(hours=9)
                or cutoff.strftime("%Y%m%d") != m[1]
                or not cutoff < result_ts < clock
                or not isinstance(race["source_sha256"], str)
                or re.fullmatch("[0-9a-f]{64}", race["source_sha256"]) is None
                or race["winner_method"] not in METHODS):
            raise ValueError("post-as-of or unsupported historical source")
        entries = race["entries"]
        if not isinstance(entries, list) or len(entries) != 6:
            raise ValueError("six settled entrants required")
        seen_frame, seen_course, seen_finish, seen_ids = set(), set(), set(), set()
        for row in entries:
            if not isinstance(row, dict) or set(row) != {"frame", "course", "racer_id", "finish"}:
                raise ValueError("exact entrant identity/course/result required")
            f, c, place, identity = row["frame"], row["course"], row["finish"], row["racer_id"]
            if (type(f) is not int or f not in range(1, 7) or f in seen_frame
                    or type(c) is not int or c not in range(1, 7) or c in seen_course
                    or type(place) is not int or place not in range(1, 7) or place in seen_finish
                    or not isinstance(identity, str) or re.fullmatch(r"\d{4}", identity) is None
                    or identity in seen_ids):
                raise ValueError("non-standard or duplicate complete finish")
            seen_frame.add(f); seen_course.add(c); seen_finish.add(place); seen_ids.add(identity)
        selected = next((row for row in entries if row["racer_id"] == racer_id), None)
        if selected is None:
            continue
        included.append(rid)
        selected_races.append((cutoff, place, selected["course"]))
        f, c, place = selected["frame"], selected["course"], selected["finish"]
        frame_course_counts[str(f)][str(c)] += 1
        if place == 1:
            win_method_by_course[str(c)][race["winner_method"]] += 1
        bucket = courses[str(c)]
        bucket["starts"] += 1
        bucket["wins"] += (place == 1)
        bucket["top2"] += (place <= 2)
        bucket["top3"] += (place <= 3)
        stats["entered_inward"] += c < f
        stats["entered_from_outer_to_1_3"] += f >= 4 and c <= 3
        stats["displaced_outward"] += c > f
        stats["displaced_top3"] += c > f and place <= 3
        crossed = any(x["frame"] > f and x["course"] < c for x in entries)
        stats["crossed_by_outer_frame"] += crossed
        stats["crossed_by_outer_frame_top3"] += crossed and place <= 3
        if c == 1:
            stats["in1_starts"] += 1
            stats["in1_wins"] += (place == 1)
            if place != 1:
                stats["in1_losses_by_winner_method"][race["winner_method"]] += 1
    for bucket in courses.values():
        if bucket["starts"]:
            bucket["win_rate"] = bucket["wins"] / bucket["starts"]
    # New racers are never penalized for lacking lifetime volume. Latest
    # source-confirmed finish samples are provided as observed recent form,
    # not a subjective age or talent label.
    selected_races.sort(key=lambda x:x[0], reverse=True)
    def last_n(n):
        sample = selected_races[:n]
        return {"starts":len(sample),
                "wins":sum(place==1 for _,place,_ in sample),
                "top3":sum(place<=3 for _,place,_ in sample),
                "top3_rate":sum(place<=3 for _,place,_ in sample)/len(sample)
                             if sample else None}
    recent = {"last_10":last_n(10),"last_30":last_n(30)}
    return {"schema": "RACE_AI_BOAT_RACER_HISTORIC_TENDENCIES_V1",
            "racer_id": racer_id, "as_of": clock.isoformat(),
            "sample_races": len(included), "race_ids": included,
            "actual_entry_course_history": courses, "tendencies": stats,
            "by_frame_actual_course_counts":frame_course_counts,
            "wins_by_actual_course_and_kimarite":win_method_by_course,
            "recent_form":recent,
            "derived_from_verified_results_only": True,
            "source_authenticity_independently_verified": False,
            "model_score_or_personality_label": None,
            "description": "Descriptive sample counts only. No causal attribution, future-entry assumption, or calibrated win claim."}
