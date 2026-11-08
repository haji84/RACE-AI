"""Offline bridge from already retained official term/B-K rows to grade research.

NO provider GET, no new state writer, no owner key read. The fan-term
assessment window must not be mistaken for the class application dates.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import re

from .boat_racer_term import term_info

JST = timezone(timedelta(hours=9))
SHA = re.compile(r"[0-9a-f]{64}\Z")
RID = re.compile(r"[0-9]{4}\Z")
RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
GRADES = {"A1", "A2", "B1", "B2"}


def clock(value):
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("GRADE_BRIDGE_AWARE_CLOCK_REQUIRED")
    if d.utcoffset() is None:
        raise ValueError("GRADE_BRIDGE_AWARE_CLOCK_REQUIRED")
    return d.astimezone(timezone.utc)


def need(code, condition):
    if not condition:
        raise ValueError(code)


def term_from_asof(at):
    d = clock(at).astimezone(JST)
    return f"{d.year}-{'1' if d.month <= 6 else '2'}"


def following_term(term):
    year, half = term.split("-")
    return f"{year}-2" if half == "1" else f"{int(year)+1}-1"


def build_saved_grade_input(racer_database, history_store, *, race_id,
                            as_of, roster, allow_source):
    """Source-free. Private DB access, read-only. Response is NOT verified.

    Official source publication_at was not part of the TERM parsed records.
    A dated first capture is only an observation time, never proof of when
    the grade was first announced or officially finalized.
    """
    at = clock(as_of)
    need("GRADE_BRIDGE_EVENT_INVALID",
         isinstance(race_id, str) and RACE.fullmatch(race_id) is not None and
         race_id[:8] == at.astimezone(JST).strftime("%Y%m%d"))
    need("GRADE_BRIDGE_ROSTER_INVALID",
         isinstance(roster, list) and len(roster) == 6 and
         all(type(r.get("boat")) is int and r.get("boat") in range(1, 7) and
             isinstance(r.get("racer_id"), str) and RID.fullmatch(r["racer_id"])
             and r.get("program_class") in GRADES
             for r in roster) and
         {r["boat"] for r in roster} == set(range(1, 7)) and
         len({r["racer_id"] for r in roster}) == 6)
    need("GRADE_BRIDGE_SOURCE_ADMISSION_REQUIRED", callable(allow_source))
    current = term_from_asof(at)
    upcoming = following_term(current)
    sources = racer_database._latest_sources("TERM", at.isoformat())
    seen = set()
    terms = []
    provenance = []
    ids = {r["racer_id"] for r in roster}
    for term in sorted(t for t in sources if re.fullmatch(r"20\d{2}-[12]", t) and t <= upcoming):
        sid = sources[term]
        racer_database._admit(sid, at.isoformat(), allow_source)
        s = racer_database.db.execute(
            "SELECT sha,url,captured_at FROM sources WHERE id=?", (sid,)
        ).fetchone()
        need("GRADE_BRIDGE_TERM_SOURCE_MISSING", s is not None)
        sha, url, captured_at = s
        info = term_info(term)
        need("GRADE_BRIDGE_TERM_SOURCE_IDENTITY",
             isinstance(sha, str) and SHA.fullmatch(sha) and
             url == info["source_url"] and clock(captured_at) <= at)
        for rid, raw in racer_database.db.execute(
                "SELECT racer_id,document FROM racers WHERE source_id=?", (sid,)):
            if rid not in ids:
                continue
            item = json.loads(raw)
            need("GRADE_BRIDGE_TERM_ROW_UNVERIFIED",
                 item.get("racer_id") == rid and item.get("term") == term and
                 item.get("period_start") == info["period_start"] and
                 item.get("period_end") == info["period_end"] and
                 item.get("recorded_class") in GRADES and
                 isinstance(item.get("record_sha256"), str) and
                 SHA.fullmatch(item["record_sha256"]))
            previous = item.get("previous_classes")
            need("GRADE_BRIDGE_PREVIOUS_CLASSES_INVALID",
                 isinstance(previous, list) and len(previous) == 3 and
                 all(p == "" or p in GRADES for p in previous))
            need("GRADE_BRIDGE_DUPLICATE_TERM_ROW",
                 (rid, term) not in seen)
            seen.add((rid, term))
            ts = clock(captured_at).isoformat()
            terms.append({
                "racer_id": rid,
                "term": term,
                "recorded_class": item["recorded_class"],
                "previous_classes": previous,
                "status": "ANNOUNCED_PENDING" if term == upcoming else "HISTORIC_OFFICIAL",
                "captured_at": ts,
                "published_at": ts,
                "confirmation_at": None,
                "source_sha256": sha,
            })
        provenance.append({
            "term": term,
            "source_sha256": sha,
            "captured_at": clock(captured_at).isoformat(),
            "publication_at_is_only_captured_observation": True,
            "independently_authenticated_here": False,
        })
    starts = []
    seen_starts = set()
    # Existing history store only reveals sources that precede as_of.
    # K's day-only race_at must not be reused as an exact start instant.
    for row in history_store.history_rows(sorted(ids), at.isoformat()):
        if row.get("participation") != "CONFIRMED_START":
            continue
        rid, race = row.get("racer_id"), row.get("race_id")
        need("GRADE_BRIDGE_RACE_ROSTER_INVALID",
             rid in ids and isinstance(race, str) and RACE.fullmatch(race))
        need("GRADE_BRIDGE_DUPLICATE_START", (rid, race) not in seen_starts)
        seen_starts.add((rid, race))
        cutoff, captured = clock(row["cutoff_at"]), clock(row["available_at"])
        finish = row.get("finish")
        need("GRADE_BRIDGE_RESULT_CLOCK_OR_VALUE_INVALID",
             cutoff < captured < at and
             cutoff.astimezone(JST).strftime("%Y%m%d") == race[:8] and
             (finish is None or type(finish) is int and 1 <= finish <= 6) and
             isinstance(row.get("source_sha256"), str) and
             SHA.fullmatch(row["source_sha256"]))
        starts.append({
            "racer_id": rid, "race_id": race,
            "raced_at": cutoff.isoformat(),  # date proxy, NOT race start instant
            "result_captured_at": captured.isoformat(),
            "started": True, "finish": finish,
            "source_sha256": row["source_sha256"],
        })
    return {
        "schema": "RACE_AI_BOAT_GRADE_TRANSITION_RESEARCH_V1",
        "race_id": race_id, "as_of": at.isoformat(),
        "roster": roster, "term_records": terms,
        "start_records": starts, "source_provenance": provenance,
        "race_time_basis": "B_PRINTED_CUTOFF_DAY_NOT_ACTUAL_START_INSTANT",
        "source_authentication_requires_Actions_readback": True,
        "history_opportunity_coverage_complete": False,
        "future_formal_grade_confirmed": False,
        "production_model_changed": False,
    }
