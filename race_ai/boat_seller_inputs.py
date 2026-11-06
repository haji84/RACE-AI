"""Actual day-stamped CSV sources -> the unchanged daily seller native input.

No fetching, proxy ratings, forecast generation, or persistence. The seller
expects same-frame win *rating points* from waku10; a win fraction or percent
is a different statistic. Caller-provided source rights are checked separately
by the existing dispatcher. Unknown source publication times stay unknown.
"""
from copy import deepcopy
import csv
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import math
import re
from urllib.parse import urlsplit

from .actions_contract import digest, stamp

SCHEMA = "RACE_AI_BOAT_SELLER_NATIVE_INPUTS_V1"
JST = timezone(timedelta(hours=9))
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_RACES = 24 * 12
SEMANTICS = {"race_cards": "NATIONAL_WIN_RATING_POINTS_0_10",
             "waku10": "SAME_FRAME_WIN_RATING_POINTS_0_10"}
SOURCE_FIELDS = {"raw", "dataset_kind", "event_date_jst", "metric_semantics", "source_url",
                 "source_sha256", "source_rights_ref", "captured_at", "published_at"}


class SellerInputError(ValueError):
    pass


def _need(ok, reason):
    if not ok:
        raise SellerInputError(reason)


def _time(value):
    if isinstance(value, datetime):
        _need(value.utcoffset() is not None, "AWARE_AS_OF_REQUIRED")
        return value
    return stamp(value)


def _race_id(value, day):
    _need(isinstance(value, str), "DAILY_RACE_IDENTITY_INVALID")
    match = re.fullmatch(r"(\d{8})-?(0[1-9]|1\d|2[0-4])-?(0[1-9]|1[0-2])", value)
    if match is None:
        match = re.fullmatch(r"boat:(\d{4}-\d\d-\d\d):boatrace-jcd-(0[1-9]|1\d|2[0-4]):([1-9]|1[0-2])", value)
        _need(match is not None, "DAILY_RACE_IDENTITY_INVALID")
        stamp_day, venue, number = match.groups()
        stamp_day = stamp_day.replace("-", "")
    else:
        stamp_day, venue, number = match.groups()
    _need(stamp_day == day.strftime("%Y%m%d"), "SOURCE_DAY_MISMATCH")
    return stamp_day + venue + f"{int(number):02d}"


def _columns(kind):
    if kind == "race_cards":
        return ("レースコード",) + tuple(f"艇{n}_{field}" for n in range(1, 7) for field in ("全国勝率", "級別"))
    return ("レースコード",) + tuple(f"艇{n}_枠番別勝率" for n in range(1, 7))


def _rating(value):
    if not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        raise SellerInputError("WIN_RATING_POINTS_INVALID") from None
    _need(math.isfinite(number) and 0 <= number <= 10, "WIN_RATING_POINTS_INVALID")
    return number


def _dataset(source, kind, day, asof):
    _need(isinstance(source, dict) and set(source) == SOURCE_FIELDS, "SOURCE_PROVENANCE_REQUIRED")
    _need(source["dataset_kind"] == kind and source["metric_semantics"] == SEMANTICS[kind],
          "EXACT_WIN_RATING_POINTS_SEMANTICS_REQUIRED")
    _need(source["event_date_jst"] == day.isoformat(), "SOURCE_DAY_MISMATCH")
    raw = source["raw"]
    _need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_SOURCE_BYTES, "BOUNDED_ORIGINAL_CSV_REQUIRED")
    _need(hashlib.sha256(raw).hexdigest() == source["source_sha256"], "SOURCE_HASH_MISMATCH")
    parsed = urlsplit(source["source_url"])
    _need(parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password and not parsed.fragment,
          "SOURCE_URL_INVALID")
    _need(isinstance(source["source_rights_ref"], str) and 0 < len(source["source_rights_ref"]) <= 256,
          "SOURCE_RIGHTS_REFERENCE_REQUIRED")
    capture = _time(source["captured_at"])
    published = source["published_at"]
    _need(capture <= asof and (published is None or _time(published) <= capture), "SOURCE_AFTER_AS_OF")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise SellerInputError("UTF8_CSV_REQUIRED") from None
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    columns = _columns(kind)
    _need(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames) and
          set(columns).issubset(reader.fieldnames), "NATIVE_CSV_COLUMNS_REQUIRED")
    result = {}; incomplete = []
    try:
        for row in reader:
            _need(len(result) < MAX_RACES and None not in row and all(row.get(k) is not None for k in columns),
                  "CSV_ROW_LAYOUT_INVALID")
            rid = _race_id(row["レースコード"], day)
            _need(rid not in result, "DUPLICATE_DAILY_RACE")
            projection = {k: row[k] for k in columns}
            projection["レースコード"] = rid
            missing = False
            for n in range(1, 7):
                rating_key = f"艇{n}_" + ("全国勝率" if kind == "race_cards" else "枠番別勝率")
                missing |= _rating(projection[rating_key]) is None
                if kind == "race_cards":
                    grade = projection[f"艇{n}_級別"]
                    _need(not grade or grade in ("A1", "A2", "B1", "B2"), "OBSERVED_RACER_GRADE_INVALID")
                    missing |= not grade
            if missing:
                incomplete.append(rid)
            result[rid] = projection
    except csv.Error:
        raise SellerInputError("CSV_ROW_LAYOUT_INVALID") from None
    _need(result, "EMPTY_DAILY_CSV")
    proof = dict(source_ref=source["source_url"], source_sha256=source["source_sha256"],
                 source_rights_ref=source["source_rights_ref"], captured_at=source["captured_at"],
                 published_at=published, event_date_jst=day.isoformat(), dataset_kind=kind,
                 metric_semantics=source["metric_semantics"])
    projection_sha = digest(result)
    projected = dict(source_ref="urn:race-ai:seller-"+kind+":"+projection_sha,
                     source_sha256=projection_sha, source_rights_ref=source["source_rights_ref"],
                     source_members=[deepcopy(proof)], transform_id="NATIVE_CSV_DAY_AND_LANE_PROJECTION_V1")
    return result, [proof, projected], incomplete


def build_seller_native_inputs(cards_source=None, waku_source=None, *, day, as_of, expected_race_ids=None):
    """Produce one complete daily payload shared by every scheduled P0 slot.

    Sources use ``SOURCE_FIELDS`` and must contain actual original CSV bytes.
    ``expected_race_ids`` comes from the verified daily ledger; a partial cards
    set cannot silently reset the native daily maximum of five selections.
    Missing waku rows remain missing for the native NO_WAKU10 denominator.
    """
    day = day if type(day) is date else date.fromisoformat(day)
    asof = _time(as_of)
    at = as_of if isinstance(as_of, str) else asof.isoformat()
    result = dict(schema=SCHEMA, day=day.isoformat(), stage="P0", as_of=at, native_inputs={},
                  readiness={"seller": dict(state="INPUT_MISSING", reasons=[])}, source_evidence=[],
                  coverage={}, source_requests=0, source_publication_times_inferred=False,
                  strategy_scope="COMPLETE_DAILY_BATCH_MAX_FIVE_SELECTIONS_BEFORE_0700_JST")
    readiness = result["readiness"]["seller"]
    if asof >= datetime.combine(day, time(7), JST):
        readiness.update(state="DEADLINE_PASSED", reasons=["SELLER_0700_WINDOW_PASSED"])
        return result
    reasons = []
    if cards_source is None: reasons.append("DAY_STAMPED_RACE_CARDS_WITH_NATIONAL_RATING_AND_GRADE_REQUIRED")
    if waku_source is None: reasons.append("SAME_FRAME_WIN_RATING_WAKU10_REQUIRED")
    if expected_race_ids is None: reasons.append("VERIFIED_COMPLETE_DAILY_RACE_LEDGER_REQUIRED")
    if reasons:
        readiness["reasons"] = reasons
        return result
    try:
        _need(isinstance(expected_race_ids, (list, tuple, set)) and 1 <= len(expected_race_ids) <= MAX_RACES,
              "VERIFIED_DAILY_RACE_LEDGER_INVALID")
        expected = {_race_id(r, day) for r in expected_race_ids}
        _need(len(expected) == len(expected_race_ids), "DUPLICATE_DAILY_RACE")
        cards, card_proofs, missing_cards = _dataset(cards_source, "race_cards", day, asof)
        waku, waku_proofs, missing_waku = _dataset(waku_source, "waku10", day, asof)
        result["source_evidence"] = card_proofs + waku_proofs
        result["coverage"] = dict(expected_races=len(expected), card_races=len(cards), same_frame_races=len(waku),
            missing_card_races=sorted(expected-cards.keys()), unexpected_card_races=sorted(cards.keys()-expected),
            missing_same_frame_races=sorted(expected-waku.keys()), incomplete_card_races=sorted(missing_cards),
            incomplete_same_frame_races=sorted(missing_waku),
            entrant_identity_basis="CSV_RACE_ID_AND_NUMBERED_LANE_HEADERS")
        if set(cards) != expected:
            readiness["reasons"] = ["COMPLETE_DAILY_RACE_CARDS_REQUIRED"]
            return result
        _need(set(waku).issubset(expected), "SAME_FRAME_RACE_OUTSIDE_DAILY_LEDGER")
        if len(missing_waku) == len(waku):
            readiness["reasons"] = ["OBSERVED_SAME_FRAME_WIN_RATINGS_REQUIRED"]
            return result
        payload = dict(scope="OPERATOR_SUPPLIED_RESEARCH", cards=cards, waku=waku, day=day.isoformat(),
                       source_evidence=deepcopy(result["source_evidence"]))
        result["native_inputs"]["seller"] = payload
        readiness.update(state="READY", reasons=[])
        return result
    except (SellerInputError, TypeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, SellerInputError) else "NATIVE_SOURCE_SCHEMA_OR_CLOCK_INVALID"
        readiness.update(state="INPUT_REJECTED", reasons=[reason])
        return result
