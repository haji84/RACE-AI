"""Actual day-stamped source bytes -> the unchanged daily seller native input.

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
OFFICIAL_B_SCHEMA = "RACE_AI_BOAT_SELLER_OFFICIAL_B_CARDS_V1"
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


def official_b_cards_source(raw_b, document, receipt, *, day, as_of):
    """Project the exact B archive authenticated by an existing P0 receipt.

    The caller independently authenticates the original GitHub receipt before
    supplying it. This offline boundary checks its document, archive, extracted
    bytes, complete daily ledger, registration identities and observed ratings.
    No CSV is invented or labelled as an original. Nationwide rating windows
    and source publication times absent from B remain unknown. Waku ratings
    cannot be recovered from this source.
    """
    from .boat_entry_observations import extract_daily_lzh, _venue_blocks
    from .boat_history_store import allocations
    from .boat_k_day_methods import HEADER
    from .core import parse_b
    from .official_archive_probe import official_url
    from .official_b_snapshot_adapter import program_details

    try:
        day = day if type(day) is date else date.fromisoformat(day)
        asof = _time(as_of)
        _need(type(raw_b) is bytes and 0 < len(raw_b) <= MAX_SOURCE_BYTES, "BOUNDED_ORIGINAL_B_ARCHIVE_REQUIRED")
        _need(type(document) is dict and document.get("schema") == "RACE_AI_EXISTING_P0_DAY_V1"
              and document.get("day_jst") == day.isoformat() and document.get("actual_purchases") is False,
              "OFFICIAL_B_P0_DOCUMENT_REQUIRED")
        receipt_fields = {"repository_id", "repository", "run_id", "head_sha", "artifact_id", "created_at",
                          "payload_sha256", "independently_verified"}
        _need(type(receipt) is dict and set(receipt) == receipt_fields
              and receipt["repository_id"] == "1416489937" and receipt["repository"] == "haji84/RACE-AI"
              and receipt["independently_verified"] is True
              and type(receipt["artifact_id"]) is int and receipt["artifact_id"] > 0
              and type(receipt["run_id"]) in (str, int) and re.fullmatch(r"[1-9][0-9]{0,19}", str(receipt["run_id"]))
              and type(receipt["head_sha"]) is str and re.fullmatch(r"[0-9a-f]{40}", receipt["head_sha"])
              and receipt["head_sha"] == document.get("code_sha")
              and receipt["payload_sha256"] == digest(document), "OFFICIAL_B_VERIFIED_DOCUMENT_RECEIPT_REQUIRED")
        captured, saved = _time(document["captured_at"]), _time(receipt["created_at"])
        _need(captured <= _time(document["completed_at"]) <= saved <= asof, "OFFICIAL_B_SOURCE_OR_RECEIPT_CLOCK_INVALID")
        _need(document["source_url"] == official_url(day, "B"), "OFFICIAL_B_SOURCE_URL_MISMATCH")
        _need(hashlib.sha256(raw_b).hexdigest() == document["source_sha256"], "OFFICIAL_B_ARCHIVE_HASH_MISMATCH")
        text = extract_daily_lzh(raw_b, f"B{day:%y%m%d}.TXT")
        _need(hashlib.sha256(text).hexdigest() == document["extracted_text_sha256"], "OFFICIAL_B_TEXT_HASH_MISMATCH")

        # The existing header parser independently verifies the printed body
        # date and deadlines. Statistics stay in the unchanged original rows;
        # allocations also supports their tight 100.00 column boundaries.
        closing = {}
        for venue, body in _venue_blocks(text, "B").items():
            headers = list(HEADER.finditer(body))
            _need(headers, "OFFICIAL_B_RACE_HEADERS_REQUIRED")
            lines = [next(line for line in body[h.start():].splitlines() if line.strip()) for h in headers]
            packet = (f"STARTB\n{venue:02d}BBGN\n" + body[:headers[0].start()] + "\n"
                      + "\n".join(lines) + f"\n{venue:02d}BEND\n").encode("cp932")
            _, cutoffs = program_details(packet, day)
            _need(not set(closing).intersection(cutoffs), "OFFICIAL_B_DUPLICATE_RACE")
            closing.update(cutoffs)
        details = allocations(text)
        roster = {}; values = {}
        for row in parse_b(text, day.isoformat()):
            rid = _race_id(row["race_id"], day); lane = row["lane"]
            detail = details[(int(rid[8:10]), int(rid[10:12]), lane)]
            racers = roster.setdefault(rid, {})
            _need(str(lane) not in racers and row["racer_id"] not in racers.values()
                  and row["racer_id"] == detail["racer_id"], "OFFICIAL_B_REGISTRATION_BINDING_INVALID")
            racers[str(lane)] = row["racer_id"]
            card = values.setdefault(rid, {"レースコード": rid})
            card[f"艇{lane}_全国勝率"] = f"{detail['national_win_rate']:.2f}"
            card[f"艇{lane}_級別"] = detail["grade"]
        _need(0 < len(values) <= MAX_RACES and len(details) == 6 * len(values)
              and all(set(r) == set("123456") for r in roster.values()), "OFFICIAL_B_COMPLETE_ROSTERS_REQUIRED")
        _need({_race_id(r, day) for r in closing} == set(values), "OFFICIAL_B_ROSTER_DEADLINE_MISMATCH")

        schedule = document.get("schedule")
        predictions = document.get("predictions")
        # The B archive is a complete *schedule*, not a claim that every
        # listed race was still open when the first P0 was saved. A late
        # bootstrap legitimately saves only future races. Do not infer or
        # generate P0s for races which passed the three-minute cutoff buffer.
        _need(type(schedule) is list and type(predictions) is list
              and type(document.get("race_count")) is int
              and len(schedule) == len(values)
              and 0 < document["race_count"] == len(predictions) <= len(values),
              "OFFICIAL_B_COMPLETE_DAILY_LEDGER_REQUIRED")
        ledger = {}
        for row in schedule:
            rid = _race_id(row["race_id"], day)
            _need(rid not in ledger, "OFFICIAL_B_DUPLICATE_DAILY_RACE")
            ledger[rid] = _time(row["cutoff_at"])
        _need(ledger == {_race_id(r, day): _time(at) for r, at in closing.items()}, "OFFICIAL_B_DAILY_LEDGER_MISMATCH")
        skipped = document.get("skipped", [])
        _need(type(skipped) is list and len(skipped) <= len(values),
              "OFFICIAL_B_SKIPPED_RACES_INVALID")
        skipped_ids = set()
        for item in skipped:
            _need(type(item) is dict and set(item) == {"race_id", "reason"}
                  and item["reason"] == "CUTOFF_BUFFER",
                  "OFFICIAL_B_SKIPPED_RACES_INVALID")
            rid = _race_id(item["race_id"], day)
            _need(rid in ledger and rid not in skipped_ids
                  and ledger[rid] <= _time(document["completed_at"]) + timedelta(minutes=3),
                  "OFFICIAL_B_SKIPPED_CUTOFF_UNVERIFIED")
            skipped_ids.add(rid)
        seen = set(); source_ids = set(); rights = set(); publications = set()
        for prediction in predictions:
            rid = _race_id(prediction["race_id"], day)
            _need(rid not in seen and rid in ledger and prediction.get("stage") == "P0"
                  and prediction.get("event_date_jst") == day.isoformat()
                  and prediction.get("suite_sha256") == digest({k: v for k, v in prediction.items() if k != "suite_sha256"}),
                  "OFFICIAL_B_SAVED_SUITE_BINDING_INVALID")
            seen.add(rid)
            _need(captured <= _time(prediction["as_of"]) <= saved < ledger[rid]
                  and _time(prediction["sales_cutoff_at"]) == ledger[rid], "OFFICIAL_B_SAVED_SUITE_CLOCK_INVALID")
            evidence = prediction["source_evidence"]
            _need(type(evidence) is list and len(evidence) == 1 and type(evidence[0]) is dict,
                  "OFFICIAL_B_SAVED_SOURCE_BINDING_INVALID")
            evidence = evidence[0]
            published = evidence.get("published_at")
            _need(evidence.get("source_url") == document["source_url"]
                  and evidence.get("source_sha256") == document["source_sha256"]
                  and _time(evidence["captured_at"]) == captured
                  and (published is None or isinstance(published, str) and _time(published) <= captured)
                  and type(evidence.get("source_id")) is str and bool(evidence["source_id"])
                  and type(evidence.get("source_rights_ref")) is str and 0 < len(evidence["source_rights_ref"]) <= 256,
                  "OFFICIAL_B_SAVED_SOURCE_BINDING_INVALID")
            source_ids.add(evidence["source_id"]); rights.add(evidence["source_rights_ref"])
            publications.add(published)
            observations = prediction["observations"]
            _need(type(observations) is list and len(observations) == 6, "OFFICIAL_B_SAVED_ROSTER_REQUIRED")
            lanes = set()
            for observation in observations:
                lane = observation["lane"]
                _need(type(lane) is int and lane in range(1, 7) and lane not in lanes
                      and observation["registration_no"] == roster[rid][str(lane)], "OFFICIAL_B_SAVED_REGISTRATION_MISMATCH")
                lanes.add(lane)
                metric = observation["features"]["national_win_rate"]
                value = metric["value"]
                _need(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 10
                      and value == float(values[rid][f"艇{lane}_全国勝率"])
                      and metric.get("source_id") == evidence["source_id"], "OFFICIAL_B_SAVED_NATIONAL_RATING_MISMATCH")
        _need(seen.isdisjoint(skipped_ids) and seen | skipped_ids == set(values)
              and len(rights) == 1 and len(source_ids) == 1 and len(publications) == 1,
              "OFFICIAL_B_COMPLETE_DAILY_BINDING_REQUIRED")
        proof = dict(source_ref=document["source_url"], source_sha256=document["source_sha256"],
            extracted_text_sha256=document["extracted_text_sha256"], source_rights_ref=next(iter(rights)),
            captured_at=document["captured_at"], published_at=next(iter(publications)), rating_window=None,
            event_date_jst=day.isoformat(), dataset_kind="race_cards", metric_semantics=SEMANTICS["race_cards"],
            original_document_sha256=receipt["payload_sha256"], original_receipt=deepcopy(receipt))
        projection_sha = digest(values)
        projected = dict(source_ref="urn:race-ai:seller-official-b:" + projection_sha,
            source_sha256=projection_sha, source_rights_ref=proof["source_rights_ref"], source_members=[deepcopy(proof)],
            roster_sha256=digest(roster),
            transform_id="OFFICIAL_B_NATIONAL_RATING_AND_GRADE_BY_VERIFIED_RACE_LANE_V1")
        return dict(schema=OFFICIAL_B_SCHEMA, raw=raw_b, document=deepcopy(document), receipt=deepcopy(receipt),
            event_date_jst=day.isoformat(), metric_semantics=SEMANTICS["race_cards"], cards=values, roster=roster,
            expected_race_ids=sorted(values), source_evidence=[proof, projected], source_requests=0)
    except SellerInputError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise SellerInputError("OFFICIAL_B_SOURCE_SCHEMA_OR_BODY_INVALID") from None


def _dataset(source, kind, day, asof):
    if isinstance(source, dict) and source.get("schema") == OFFICIAL_B_SCHEMA:
        _need(kind == "race_cards", "EXACT_WIN_RATING_POINTS_SEMANTICS_REQUIRED")
        verified = official_b_cards_source(source.get("raw"), source.get("document"), source.get("receipt"), day=day, as_of=asof)
        _need(source == verified, "OFFICIAL_B_SOURCE_PROJECTION_CHANGED")
        return deepcopy(verified["cards"]), deepcopy(verified["source_evidence"]), []
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

    CSV sources use ``SOURCE_FIELDS``; official B cards use the authenticated
    ``official_b_cards_source`` result. Both preserve actual original bytes.
    ``expected_race_ids`` comes from the verified daily ledger; a partial cards
    set cannot silently reset the native daily maximum of five selections.
    Missing waku rows remain missing for the native NO_WAKU10 denominator.
    """
    day = day if type(day) is date else date.fromisoformat(day)
    asof = _time(as_of)
    at = as_of if isinstance(as_of, str) else asof.isoformat()
    result = dict(schema=SCHEMA, day=day.isoformat(), stage="P0", as_of=at, native_inputs={},
                  readiness={k: dict(state="INPUT_MISSING", reasons=[]) for k in ("seller", "race_cards", "waku10")},
                  available_inputs={}, source_evidence=[],
                  coverage={}, source_requests=0, source_publication_times_inferred=False,
                  strategy_scope="COMPLETE_DAILY_BATCH_MAX_FIVE_SELECTIONS_BEFORE_0700_JST")
    readiness = result["readiness"]["seller"]
    reasons = []
    if cards_source is None: reasons.append("DAY_STAMPED_RACE_CARDS_WITH_NATIONAL_RATING_AND_GRADE_REQUIRED")
    if waku_source is None: reasons.append("SAME_FRAME_WIN_RATING_WAKU10_REQUIRED")
    if expected_race_ids is None: reasons.append("VERIFIED_COMPLETE_DAILY_RACE_LEDGER_REQUIRED")
    try:
        expected = None
        if expected_race_ids is not None:
            _need(isinstance(expected_race_ids, (list, tuple, set)) and 1 <= len(expected_race_ids) <= MAX_RACES,
                  "VERIFIED_DAILY_RACE_LEDGER_INVALID")
            expected = {_race_id(r, day) for r in expected_race_ids}
            _need(len(expected) == len(expected_race_ids), "DUPLICATE_DAILY_RACE")
        datasets = {}
        for kind, source in (("race_cards", cards_source), ("waku10", waku_source)):
            if source is None:
                datasets[kind] = ({}, [])
                result["readiness"][kind]["reasons"] = [
                    "DAY_STAMPED_RACE_CARDS_WITH_NATIONAL_RATING_AND_GRADE_REQUIRED" if kind == "race_cards"
                    else "SAME_FRAME_WIN_RATING_WAKU10_REQUIRED"]
                continue
            rows, proofs, missing = _dataset(source, kind, day, asof)
            datasets[kind] = (rows, missing)
            result["available_inputs"][kind] = deepcopy(rows)
            result["source_evidence"].extend(proofs)
            result["readiness"][kind].update(state="READY", reasons=[])
        cards, missing_cards = datasets["race_cards"]
        waku, missing_waku = datasets["waku10"]
        result["coverage"] = dict(expected_races=len(expected) if expected is not None else None,
            card_races=len(cards), card_entrants=6*len(cards), same_frame_races=len(waku),
            missing_card_races=sorted(expected-cards.keys()) if expected is not None else None,
            unexpected_card_races=sorted(cards.keys()-expected) if expected is not None else None,
            missing_same_frame_races=sorted(expected-waku.keys()) if expected is not None else None,
            incomplete_card_races=sorted(missing_cards),
            incomplete_same_frame_races=sorted(missing_waku),
            entrant_identity_basis=("OFFICIAL_B_AND_SAVED_P0_REGISTRATION_BY_RACE_AND_LANE"
                if isinstance(cards_source, dict) and cards_source.get("schema") == OFFICIAL_B_SCHEMA
                else "CSV_RACE_ID_AND_NUMBERED_LANE_HEADERS"))
        if expected is not None and cards_source is not None and set(cards) != expected:
            reasons.append("COMPLETE_DAILY_RACE_CARDS_REQUIRED")
            result["readiness"]["race_cards"].update(state="INPUT_MISSING", reasons=["COMPLETE_DAILY_RACE_CARDS_REQUIRED"])
        if expected is not None:
            _need(set(waku).issubset(expected), "SAME_FRAME_RACE_OUTSIDE_DAILY_LEDGER")
        if waku and len(missing_waku) == len(waku):
            reasons.append("OBSERVED_SAME_FRAME_WIN_RATINGS_REQUIRED")
            result["readiness"]["waku10"].update(state="INPUT_MISSING", reasons=["OBSERVED_SAME_FRAME_WIN_RATINGS_REQUIRED"])
        if asof >= datetime.combine(day, time(7), JST):
            readiness.update(state="DEADLINE_PASSED", reasons=["SELLER_0700_WINDOW_PASSED"])
            return result
        if reasons:
            readiness["reasons"] = reasons
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
