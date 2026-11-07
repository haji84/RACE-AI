"""Offline B-program/K-result joins and descriptive historical entry samples.

Uses the pinned parsers without modifying their source. Printed B deadlines,
not the K parser's date-only ``race_at``, determine each race's cutoff. Archive
URLs, byte hashes and caller-supplied capture clocks preserve lineage; they do
not independently authenticate the upstream or attest the capture time.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import race_ai

_REFERENCE = str(Path(__file__).resolve().parents[1] / "pr64-reference" / "race_ai")
if _REFERENCE not in race_ai.__path__:
    race_ai.__path__.append(_REFERENCE)

from .core import _blocks, parse_b, parse_k
from .official_archive_probe import official_url
from .official_b_snapshot_adapter import program_details
from .official_lzh_extract import extract_daily_lzh
from .boat_k_day_methods import HEADER, join_k
from .boat_racer_tendencies import _ts, profile_before

HISTORY_SCHEMA = "RACE_AI_BOAT_ENTRY_OBSERVATIONS_V1"
PROFILE_SCHEMA = "RACE_AI_BOAT_ENTRY_CONDITIONAL_PROFILE_V1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FIELDS = {"source_url", "source_sha256", "extracted_text_sha256", "captured_at"}
_MAX_TEXT = 20_000_000


def _day(value):
    result = value if type(value) is date else date.fromisoformat(value)
    if not isinstance(result, date):
        raise ValueError("ENTRY_DAY_INVALID")
    return result


def _source(source, kind, day, raw=None):
    if (not isinstance(source, dict) or set(source) != _SOURCE_FIELDS
            or source["source_url"] != official_url(day, kind)):
        raise ValueError("ENTRY_SOURCE_IDENTITY_MISMATCH")
    if any(not isinstance(source[key], str) or not _SHA.fullmatch(source[key])
           for key in ("source_sha256", "extracted_text_sha256")):
        raise ValueError("ENTRY_SOURCE_HASH_INVALID")
    if raw is not None and source["extracted_text_sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("ENTRY_SOURCE_HASH_MISMATCH")
    _ts(source["captured_at"])
    return deepcopy(source)


def _proof_hash(proofs):
    return hashlib.sha256(json.dumps(proofs, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _venue_blocks(raw, kind):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_TEXT:
        raise ValueError("ENTRY_TEXT_SIZE_INVALID")
    text = unicodedata.normalize("NFKC", raw.decode("cp932"))
    if "START" + kind not in text[:200]:
        raise ValueError("ENTRY_SOURCE_KIND_MISMATCH")
    venues = {}
    for venue, body in _blocks(text, kind):
        if venue not in range(1, 25) or venue in venues:
            raise ValueError("ENTRY_VENUE_INVALID_OR_DUPLICATE")
        venues[venue] = body
    return venues


def build_entry_history(b_raw, k_raw, *, day, b_source, k_source):
    """Join already extracted CP932 daily bytes with explicit source metadata.

    Both source dictionaries require the exact official archive URL, archive
    ``source_sha256``, ``extracted_text_sha256`` and aware ``captured_at``.
    This API checks the extracted hash; use ``build_entry_history_from_archives``
    to also verify the supplied archive hash against actual LZH bytes.
    Abnormal/incomplete K races remain explicit exclusions, never losses.
    """
    day = _day(day)
    b_proof = _source(b_source, "B", day, b_raw)
    k_proof = _source(k_source, "K", day, k_raw)
    b_venues, k_venues = _venue_blocks(b_raw, "B"), _venue_blocks(k_raw, "K")
    if set(k_venues) - set(b_venues):
        raise ValueError("B_K_VENUE_MISMATCH")
    rosters = defaultdict(dict)
    for row in parse_b(b_raw, day.isoformat()):
        roster = rosters[row["race_id"]]
        if row["lane"] in roster or row["racer_id"] in roster.values():
            raise ValueError("B_ROSTER_DUPLICATE")
        roster[row["lane"]] = row["racer_id"]
    closing, schedule_proofs = {}, {}
    for venue, body in b_venues.items():
        headers = list(HEADER.finditer(body))
        if not headers:
            raise ValueError("B_PROGRAM_HEADERS_MISSING")
        # Preserve the dated venue prelude and whole race-header lines after
        # NFKC normalization. The detail parser supplies the deadline; parse_b supplies
        # the independent six-frame roster. No statistics row is repaired.
        prelude = body[:headers[0].start()]
        header_lines = [next(line for line in body[h.start():].splitlines() if line.strip())
                        for h in headers]
        packet = (f"STARTB\n{venue:02d}BBGN\n" + prelude + "\n"
                  + "\n".join(header_lines) + f"\n{venue:02d}BEND\n").encode("cp932")
        _, cutoffs = program_details(packet, day)
        if not cutoffs or set(cutoffs) & set(closing):
            raise ValueError("B_PROGRAM_CUTOFF_DUPLICATE")
        closing.update(cutoffs)
        schedule_proofs[f"{venue:02d}"] = {
            "parser": "pr64-reference/race_ai/official_b_snapshot_adapter.program_details",
            "input_scope": "NFKC-normalized dated venue prelude and full race-header lines",
            "parser_input_sha256": hashlib.sha256(packet).hexdigest(),
        }
    if set(closing) != set(rosters) or any(set(rows) != set(range(1, 7)) for rows in rosters.values()):
        raise ValueError("B_PROGRAM_ROSTER_CUTOFF_MISMATCH")
    records, excluded = [], {}
    race_proofs = {rid: {"cutoff_at": cutoff,
                       "frame_racer_ids": {str(f): identity for f, identity in rosters[rid].items()}}
                   for rid, cutoff in closing.items()}
    for venue, body in k_venues.items():
        venue_id = f"{venue:02d}"
        k_ids = [f"{day:%Y%m%d}-{venue_id}-{int(h[1]):02d}" for h in HEADER.finditer(body)]
        if len(k_ids) != len(set(k_ids)) or any(rid not in closing for rid in k_ids):
            raise ValueError("B_K_RACE_IDENTITY_MISMATCH")
        times = {int(rid[-2:]): datetime.fromisoformat(stamp)
                 for rid, stamp in closing.items() if rid[9:11] == venue_id}
        joined, skipped = join_k(k_raw, day, venue_id, times,
                                k_proof["captured_at"], k_proof["source_sha256"], _blocks, parse_k)
        for race in joined:
            expected = rosters[race["race_id"]]
            if {row["frame"]: row["racer_id"] for row in race["entries"]} != expected:
                raise ValueError("B_K_ROSTER_MISMATCH")
            if not _ts(race["cutoff_at"]) < _ts(race["result_captured_at"]):
                raise ValueError("K_RESULT_CAPTURE_NOT_AFTER_CUTOFF")
        records.extend(joined)
        excluded.update(skipped)
    for rid in set(closing) - {row["race_id"] for row in records} - set(excluded):
        excluded[rid] = "K_RESULT_MISSING"
    return {"schema": HISTORY_SCHEMA, "date_jst": day.isoformat(),
            "records": sorted(records, key=lambda row: row["race_id"]),
            "source_proofs": {"B": b_proof, "K": k_proof},
            "source_proofs_sha256": _proof_hash({"B": b_proof, "K": k_proof}),
            "race_proofs": race_proofs, "schedule_proofs": schedule_proofs,
            "excluded_races": dict(sorted(excluded.items()))}


def build_entry_history_from_archives(b_archive, k_archive, *, day, b_source, k_source):
    """Verify archive hashes and extract both files with the pinned LZH parser.

    Accepts bytes and the same source metadata as ``build_entry_history``.
    The extracted-text hash may be omitted; it is then computed from extraction.
    No files or network calls are made.
    """
    day = _day(day)
    texts, proofs = [], []
    for kind, raw, supplied in (("B", b_archive, b_source), ("K", k_archive, k_source)):
        if (not isinstance(raw, bytes) or not isinstance(supplied, dict)
                or set(supplied) not in (_SOURCE_FIELDS, _SOURCE_FIELDS - {"extracted_text_sha256"})):
            raise ValueError("ENTRY_ARCHIVE_SOURCE_INVALID")
        if supplied["source_sha256"] != hashlib.sha256(raw).hexdigest():
            raise ValueError("ENTRY_ARCHIVE_SOURCE_HASH_MISMATCH")
        text = extract_daily_lzh(raw, f"{kind}{day:%y%m%d}.TXT")
        proof = dict(supplied)
        proof.setdefault("extracted_text_sha256", hashlib.sha256(text).hexdigest())
        proofs.append(proof)
        texts.append(text)
    return build_entry_history(*texts, day=day, b_source=proofs[0], k_source=proofs[1])


def _bucket():
    return {"starts": 0, "wins": 0, "top2": 0, "top3": 0, "denominator": 0,
            "win_rate": None, "top2_rate": None, "top3_rate": None}


def _add(bucket, finish):
    bucket["starts"] += 1
    bucket["denominator"] += 1
    for field, limit in (("wins", 1), ("top2", 2), ("top3", 3)):
        bucket[field] += finish <= limit


def conditional_profile_before(histories, *, as_of, racer_id):
    """Supplement the existing strict history validator with conditional rates.

    Accepts one daily intake bundle or a list of bundles. Every source and
    result capture must be strictly earlier than ``as_of``; a late bundle is
    rejected rather than used as historical evidence. There are no causal
    attempt/resistance labels or predicted entry probabilities.
    """
    clock = _ts(as_of)
    histories = [histories] if isinstance(histories, dict) else histories
    if not isinstance(histories, list) or len(histories) > 3660:
        raise ValueError("BOUNDED_ENTRY_HISTORY_REQUIRED")
    records, proofs = [], []
    for history in histories:
        if not isinstance(history, dict) or history.get("schema") != HISTORY_SCHEMA:
            raise ValueError("ENTRY_HISTORY_SCHEMA_INVALID")
        day = _day(history["date_jst"])
        sources = history["source_proofs"]
        if not isinstance(sources, dict) or set(sources) != {"B", "K"}:
            raise ValueError("ENTRY_SOURCE_PROOFS_REQUIRED")
        if history.get("source_proofs_sha256") != _proof_hash(sources):
            raise ValueError("ENTRY_SOURCE_PROOFS_CHANGED_AFTER_JOIN")
        for kind in ("B", "K"):
            _source(sources[kind], kind, day)
            if not _ts(sources[kind]["captured_at"]) < clock:
                raise ValueError("ENTRY_SOURCE_NOT_AVAILABLE_AS_OF")
        for race in history["records"]:
            proof = history["race_proofs"].get(race["race_id"], {})
            if (not race["race_id"].startswith(day.strftime("%Y%m%d") + "-")
                    or race["source_sha256"] != sources["K"]["source_sha256"]
                    or race["result_captured_at"] != sources["K"]["captured_at"]
                    or race["cutoff_at"] != proof.get("cutoff_at")
                    or {str(row["frame"]): row["racer_id"] for row in race["entries"]}
                        != proof.get("frame_racer_ids")):
                raise ValueError("ENTRY_HISTORY_SOURCE_OR_ROSTER_MISMATCH")
        records.extend(history["records"])
        proofs.append({"date_jst": day.isoformat(), **deepcopy(sources)})
    # Keep the existing profile contract and all of its strict validation intact.
    existing = profile_before(records, as_of=as_of, racer_id=racer_id)
    buckets = {name: _bucket() for name in (
        "inward", "outer_to_inner3", "displaced", "crossed_by_outer_frame", "any_inward_mover_present")}
    courses = {str(course): _bucket() for course in range(1, 7)}
    for race in records:
        selected = next((row for row in race["entries"] if row["racer_id"] == racer_id), None)
        if selected is None:
            continue
        frame, course, finish = selected["frame"], selected["course"], selected["finish"]
        mover = any(row["course"] < row["frame"] for row in race["entries"])
        conditions = {"inward": course < frame, "outer_to_inner3": frame >= 4 and course <= 3,
                      "displaced": course > frame,
                      "crossed_by_outer_frame": any(row["frame"] > frame and row["course"] < course for row in race["entries"]),
                      "any_inward_mover_present": mover}
        for name, included in conditions.items():
            if included:
                _add(buckets[name], finish)
        if mover:
            _add(courses[str(course)], finish)
    for bucket in list(buckets.values()) + list(courses.values()):
        if bucket["denominator"]:
            for rate, count in (("win_rate", "wins"), ("top2_rate", "top2"), ("top3_rate", "top3")):
                bucket[rate] = bucket[count] / bucket["denominator"]
    return {"schema": PROFILE_SCHEMA, "racer_id": racer_id, "as_of": existing["as_of"],
            "sample_races": existing["sample_races"], "race_ids": existing["race_ids"],
            "conditional_buckets": buckets, "actual_course_when_inward_mover_present": courses,
            "source_proofs": proofs, "derived_from_verified_results_only": True,
            "source_authenticity_independently_verified": False,
            "description": "Descriptive observed samples only. No causal attribution, future-entry assumption, or calibrated win claim."}
