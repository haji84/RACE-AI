"""Parse the observed KEIRIN.JP profile and published history result pages.

These pure parsers do not assert transport success, grant source rights, infer
injury or fill unknown dates. Registration is bound in BOTH source documents.
The source's displayed update time is not its original publication time.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from math import isfinite
import re

from . import keirin_official_schedule as calendar
from . import keirin_official_sp_receipt as receipt
from . import keirin_official_public_source as official_result
from . import keirin_official_reviewed_pdf as reviewed_unit

JST = timezone(timedelta(hours=9))
_REG = re.compile(r"[0-9]{6}\Z")
_TOKEN = re.compile(r"btnResultClick\('([A-Za-z0-9_-]{43})'\)\Z")
_VIDEO = re.compile(r"https://wm\.st\.keirin\.jp/wm-keirin([0-9]{2})/"
                    r"([0-9]{8})-([0-9]{2})-[0-9]{2}-([0-9]{2})-[0-9]{2}-[0-9]{2}\.mp4\Z")
_SYMBOLS = frozenset("123456789") | {"落", "落再", "失", "故", "棄", "欠", "未", "途中欠場"}


class OfficialFormHistoryError(ValueError):
    """Fixed safe codes only; raw pages, identities and tokens stay private."""


def _need(ok, code):
    if not ok:
        raise OfficialFormHistoryError("OFFICIAL_FORM_" + code)


def _aware(value):
    if type(value) is str:
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise OfficialFormHistoryError("OFFICIAL_FORM_CLOCK_INVALID") from None
    _need(isinstance(value, datetime) and value.utcoffset() is not None, "CLOCK_INVALID")
    return value.astimezone(timezone.utc)


def _registration(value):
    _need(type(value) is str and _REG.fullmatch(value), "REGISTRATION_INVALID")
    return value


def _text(node):
    return re.sub(r"\s+", " ", calendar._text(node)).strip()


def _one(document, identity):
    found = [n for n in document.nodes if n.attrs.get("id") == identity]
    _need(len(found) == 1 and found[0].closed, "FIELD_MISSING_OR_DUPLICATE")
    return found[0]


def _document(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES, "BODY_BOUND")
    try:
        doc = receipt._body(raw, sha256(raw).hexdigest())
    except (ValueError, UnicodeError, RecursionError):
        raise OfficialFormHistoryError("OFFICIAL_FORM_DOCUMENT_INVALID") from None
    _need(not any(n.tag == "base" or n.tag == "input" and
                  n.attrs.get("type", "").lower() == "password" for n in doc.nodes),
          "NONPUBLIC_OR_AMBIGUOUS_DOCUMENT")
    return doc


def _updated(value, observed):
    _need(type(value) is str, "UPDATE_TIME_MISSING")
    found = re.fullmatch(r"(20[0-9]{2}/[0-9]{2}/[0-9]{2})\s+([0-9]{2}:[0-9]{2})\s*更新",
                         unescape(value).strip())
    _need(found is not None, "UPDATE_TIME_INVALID")
    try:
        parsed = datetime.strptime(found[1] + " " + found[2], "%Y/%m/%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        raise OfficialFormHistoryError("OFFICIAL_FORM_UPDATE_TIME_INVALID") from None
    parsed = parsed.astimezone(timezone.utc)
    _need(parsed <= observed, "SOURCE_UPDATED_AFTER_OBSERVATION")
    return parsed


def _number(text, low, high, *, integral=False):
    try:
        result = int(text) if integral else float(text)
    except (ValueError, TypeError):
        raise OfficialFormHistoryError("OFFICIAL_FORM_STATISTIC_INVALID") from None
    _need(isfinite(result) and low <= result <= high, "STATISTIC_INVALID")
    return result


def parse_profile(raw, *, expected_registration_id, observed_at):
    """Read stable registration, displayed stats and opaque published links.

    Meeting labels deliberately remain MM/DD. The actual result page must
    establish each race's full date, venue, race number and actual field size.
    """
    registration, observed = _registration(expected_registration_id), _aware(observed_at)
    document = _document(raw)
    _need(_text(_one(document, "regnum")) == registration, "PROFILE_REGISTRATION_MISMATCH")
    updated = _updated(_text(_one(document, "UNQ_orlabel_99")), observed)
    result_form = _one(document, "raceResultURL")
    _need(result_form.tag == "input" and result_form.attrs.get("value") == "/sp/race",
          "PUBLISHED_RESULT_FORM_CHANGED")
    identity = {key: _text(_one(document, f"UNQ_orlabel_{number}")) for key, number in
                (("name", 1), ("prefecture", 2), ("graduation_period", 3), ("grade", 5))}
    _need(all(0 < len(v) <= 80 for v in identity.values()), "PROFILE_IDENTITY_INVALID")
    stats = {
        "competition_points": _number(_text(_one(document, "UNQ_orlabel_19")), 0, 150),
        "win_rate_percent": _number(_text(_one(document, "UNQ_orlabel_14")), 0, 100),
        "h_count": _number(_text(_one(document, "UNQ_orlabel_17")), 0, 200, integral=True),
        "b_count": _number(_text(_one(document, "UNQ_orlabel_18")), 0, 200, integral=True),
    }
    source_hash = sha256(raw).hexdigest()
    rows = [n for n in document.nodes if n.tag == "tr" and re.fullmatch(
        r"RaceResults_[0-9]+|table_view[1-5]", n.attrs.get("id", ""))]
    _need(1 <= len(rows) <= 25 and len({n.attrs["id"] for n in rows}) == len(rows),
          "HISTORY_ROWS_MISSING_OR_DUPLICATE")
    references, absences, seen = [], [], set()
    for row in rows:
        _need(row.closed, "HISTORY_ROW_INCOMPLETE")
        cells = [n for n in row.children if n.tag == "td"]
        _need(len(cells) == 2, "HISTORY_ROW_LAYOUT_CHANGED")
        labels = [_text(n) for n in calendar._descendants(cells[0]) if n.tag == "span"]
        _need(len(labels) == 3 and re.fullmatch(r"[0-9]{2}/[0-9]{2}", labels[0]),
              "MEETING_LABEL_INVALID")
        common = dict(registration_id=registration, profile_sha256=source_hash,
                      meeting_label=labels[0], venue_label=labels[1], grade_label=labels[2],
                      current_meeting=row.attrs["id"].startswith("table_view"),
                      profile_updated_at=updated.isoformat())
        descendants = list(calendar._descendants(cells[1]))
        row_symbols = [n.attrs.get("alt", "") for n in descendants if n.tag == "img"]
        links = [n for n in descendants if "btnResultClick" in n.attrs.get("onclick", "")]
        ordinal = 0
        for node in links:
            match = _TOKEN.fullmatch(node.attrs["onclick"])
            _need(match is not None, "HISTORY_LINK_NOT_PUBLISHED_GRAMMAR")
            token = match[1]
            _need(token not in seen, "DUPLICATE_HISTORY_REFERENCE")
            seen.add(token)
            images = [n for n in calendar._descendants(node) if n.tag == "img"]
            _need(len(images) == 1, "RESULT_SYMBOL_NOT_BOUND_TO_LINK")
            symbol = images[0].attrs.get("alt")
            _need(symbol in _SYMBOLS and images[0].attrs.get("src", "").startswith(
                "/sp/static/img/icon/print/"), "RESULT_SYMBOL_UNSUPPORTED")
            ordinal += 1
            references.append(dict(common, ordinal_in_meeting=ordinal, token=token,
                                   token_sha256=sha256(token.encode()).hexdigest(),
                                   method="POST", source_url="https://keirin.jp/sp/race",
                                   disp="SJ0326", observed_status_symbol=symbol))
        content = _text(cells[1])
        if not links or "途中欠場" in row_symbols:
            status = next((label for label in ("病気欠場", "負傷欠場", "その他欠場", "不参加")
                           if label in content), None)
            if "途中欠場" in row_symbols:
                status = "途中欠場"
            if status:
                absences.append(dict(common, status_text=status, start_date=None,
                                     end_date=None, period_verified=False))
    _need(references, "NO_PUBLISHED_HISTORY_RESULTS")
    return dict(schema="RACE_AI_KEIRIN_OFFICIAL_FORM_PROFILE_V1", registration_id=registration,
                **identity, stats=stats, source_sha256=source_hash,
                source_url="https://keirin.jp/sp/racerracentrecord?snum=" + registration,
                observed_at=observed.isoformat(), source_updated_at=updated.isoformat(),
                original_publication_time=None, history_references=references,
                absence_observations=absences, comments=[], comments_availability="NOT_ON_THIS_PAGE")


def _state(row):
    _need(type(row) is dict and type(row.get("tyaku")) is str and
          type(row.get("kojinStateItemSubData")) is list, "RESULT_RIDER_LAYOUT_INVALID")
    notes = row["kojinStateItemSubData"]
    _need(len(notes) <= 10 and all(type(n) is dict and type(n.get("kojinState")) is str
                                 and type(n.get("tyakuNote", "")) is str for n in notes),
          "RESULT_NOTES_INVALID")
    note = " ".join(n["kojinState"] + " " + n.get("tyakuNote", "") for n in notes).strip()
    place = row["tyaku"].strip()
    if re.fullmatch(r"[1-9]", place):
        _need(not any(s in note for s in ("棄権", "欠場", "失格")), "CONTRADICTORY_RESULT_STATUS")
        return ("FALL_FINISHED" if any(s in note for s in ("落車", "落滑入"))
                else "FINISHED"), int(place), note
    _need(place == "", "UNKNOWN_RESULT_RANK")
    if "落車棄権" in note:
        return "FALL_DNF", None, note
    if "欠場" in note or "不出走" in note:
        return "DNS", None, note
    if "失格" in note:
        return "DISQUALIFIED", None, note
    if "棄権" in note:
        return "OTHER_DNF", None, note
    raise OfficialFormHistoryError("OFFICIAL_FORM_UNKNOWN_RESULT_STATUS")


def parse_history_result(raw, *, expected_registration_id, observed_at, expected_reference):
    """Join official actual result by registration; never guess date/headcount."""
    registration, observed = _registration(expected_registration_id), _aware(observed_at)
    ref = expected_reference
    _need(type(ref) is dict and ref.get("registration_id") == registration and
          ref.get("method") == "POST" and ref.get("source_url") == "https://keirin.jp/sp/race" and
          ref.get("disp") == "SJ0326" and type(ref.get("token")) is str and
          re.fullmatch(r"[A-Za-z0-9_-]{43}", ref["token"]) is not None and
          ref.get("token_sha256") == sha256(ref["token"].encode()).hexdigest() and
          re.fullmatch(r"[a-f0-9]{64}", str(ref.get("profile_sha256", ""))) is not None,
          "RESULT_PROFILE_REFERENCE_INVALID")
    document = _document(raw)
    try:
        embedded = receipt._embedded(document)
    except ValueError:
        raise OfficialFormHistoryError("OFFICIAL_FORM_EMBEDDED_RESULT_INVALID") from None
    container, result = embedded.get("SC0201"), embedded.get("SJ0326")
    _need(type(container) is dict and container.get("resultCd") == 0 and
          type(container.get("C0201data")) is dict and type(result) is dict and
          result.get("resultCd") == 0 and result.get("tyakujyunDispFlg") is True,
          "RESULT_NOT_FINAL_OR_UNAVAILABLE")
    header = container["C0201data"]
    _need(header.get("flgRaceCancel") is False, "RACE_CANCELLED")
    full_day, period = header.get("txtEventDate"), header.get("txtKikan")
    _need(type(full_day) is str and re.fullmatch(r"20[0-9]{2}/[0-9]{2}/[0-9]{2}", full_day) and
          type(period) is str and re.fullmatch(r"20[0-9]{2}/[0-9]{2}/[0-9]{2}～20[0-9]{2}/[0-9]{2}/[0-9]{2}", period),
          "RESULT_DATE_NOT_EXPLICIT")
    try:
        event_day = date.fromisoformat(full_day.replace("/", "-"))
        first, last = [date.fromisoformat(x.replace("/", "-")) for x in period.split("～")]
    except ValueError:
        raise OfficialFormHistoryError("OFFICIAL_FORM_RESULT_DATE_INVALID") from None
    _need(first <= event_day <= last and 0 <= (last - first).days <= 31 and
          first.strftime("%m/%d") == ref.get("meeting_label") and
          event_day <= observed.astimezone(JST).date(), "RESULT_MEETING_OR_DATE_MISMATCH")
    venue = header.get("joName")
    _need(type(venue) is str and type(ref.get("venue_label")) is str and
          ref["venue_label"] in venue, "RESULT_VENUE_LABEL_MISMATCH")
    race_no = header.get("selRaceNo")
    _need(type(race_no) is int and 1 <= race_no <= 12, "RESULT_RACE_NUMBER_INVALID")
    match = _VIDEO.fullmatch(result.get("digestUrl", ""))
    _need(match is not None and match[1] == match[3] and 1 <= int(match[1]) <= 99 and
          match[2] == event_day.strftime("%Y%m%d") and int(match[4]) == race_no,
          "RESULT_PUBLISHED_IDENTIFIERS_DISAGREE")
    rows = result.get("tyakujyunItemSubData")
    _need(type(rows) is list and 5 <= len(rows) <= 9, "RESULT_FIELD_SIZE_UNKNOWN")
    _need(all(type(row) is dict and type(row.get("sensyuRegistNo")) is str and
              _REG.fullmatch(row["sensyuRegistNo"]) and type(row.get("syaban")) is str and
              re.fullmatch(r"[1-9]", row["syaban"]) for row in rows), "RESULT_ROSTER_INVALID")
    _need(len({row["sensyuRegistNo"] for row in rows}) == len(rows) and
          len({row["syaban"] for row in rows}) == len(rows), "RESULT_ROSTER_DUPLICATED")
    selected = [row for row in rows if row["sensyuRegistNo"] == registration]
    _need(len(selected) == 1, "RESULT_REGISTRATION_MISMATCH")
    states = [_state(row) for row in rows]
    field_size = sum(status != "DNS" for status, _, _ in states)
    _need(5 <= field_size <= 9, "RESULT_ACTUAL_FIELD_SIZE_UNSUPPORTED")
    status, place, note = _state(selected[0])
    _need(place is None or place <= field_size, "RESULT_RANK_EXCEEDS_FIELD")
    symbol = ref.get("observed_status_symbol")
    if symbol in frozenset("123456789"):
        _need(place == int(symbol), "PROFILE_RESULT_RANK_MISMATCH")
    elif symbol in ("落", "落再"):
        _need(status in ("FALL_DNF", "FALL_FINISHED"), "PROFILE_RESULT_FALL_MISMATCH")
    elif symbol == "失":
        _need(status == "DISQUALIFIED", "PROFILE_RESULT_DISQUALIFICATION_MISMATCH")
    elif symbol in ("欠", "途中欠場"):
        _need(status == "DNS", "PROFILE_RESULT_ABSENCE_MISMATCH")
    elif symbol in ("故", "棄"):
        _need(status in ("OTHER_DNF", "FALL_DNF"), "PROFILE_RESULT_NONFINISH_MISMATCH")
    else:
        raise OfficialFormHistoryError("OFFICIAL_FORM_PROFILE_RESULT_SYMBOL_UNKNOWN")
    updated = _updated(result.get("lastUpdateTime"), observed)
    _need(updated.astimezone(JST).date() >= event_day and
          updated <= _aware(ref["profile_updated_at"]), "RESULT_UPDATE_NOT_PRE_PROFILE")
    return dict(schema="RACE_AI_KEIRIN_OFFICIAL_HISTORY_RESULT_V1", registration_id=registration,
                race_id=event_day.strftime("%Y%m%d") + match[1] + f"{race_no:02d}",
                race_date=event_day.isoformat(), venue_code=int(match[1]), venue_name=venue,
                race_no=race_no, field_size=field_size, listed_rider_count=len(rows),
                status=status, place=place, official_status_text=note,
                source_url="https://keirin.jp/sp/race", source_method="POST",
                source_sha256=sha256(raw).hexdigest(), observed_at=observed.isoformat(),
                source_updated_at=updated.isoformat(), original_publication_time=None,
                profile_sha256=ref["profile_sha256"], reference_token_sha256=ref["token_sha256"])


def parse_final_result(raw, *, expected_race_id, observed_at, expected_reference,
                       verified_unit_evidence=None, source_bytes_by_sha=None,
                       unit_verified_at=None):
    """Verify actual order, and independently verify any external payout unit.

    The observed SP result page does not explicitly define its displayed payout
    as per 100 yen. An existing allowed official guide, its receipt, and exact
    bytes must establish that unit before ``payouts_100yen`` is returned. Exact
    ticket-hit comparison does not depend on optional monetary evidence.
    """
    observed, ref = _aware(observed_at), expected_reference
    _need(type(expected_race_id) is str and re.fullmatch(r"20[0-9]{10}", expected_race_id),
          "FINAL_RACE_ID_INVALID")
    _need(type(ref) is dict and ref.get("source_url") == "https://keirin.jp/sp/race" and
          ref.get("method") == "POST" and ref.get("disp") == "SJ0326" and
          type(ref.get("token")) is str and
          re.fullmatch(r"(?:[A-Za-z0-9_-]{43}|[A-Za-z0-9_-]{64})", ref["token"]),
          "FINAL_PUBLISHED_REFERENCE_INVALID")
    cutoff = _aware(ref.get("official_cutoff_at"))
    _need(cutoff.astimezone(JST).strftime("%Y%m%d") == expected_race_id[:8] and cutoff < observed,
          "FINAL_CUTOFF_INCONSISTENT")
    starters = ref.get("starters")
    _need(type(starters) is list and 5 <= len(starters) <= 9 and
          all(type(r) is dict and type(r.get("car")) is int and 1 <= r["car"] <= 9 and
              type(r.get("registration_id")) is str and _REG.fullmatch(r["registration_id"])
              for r in starters), "FINAL_FROZEN_ROSTER_INVALID")
    by_car = {r["car"]: r["registration_id"] for r in starters}
    _need(len(by_car) == len(starters) and len(set(by_car.values())) == len(starters),
          "FINAL_FROZEN_ROSTER_DUPLICATED")
    document = _document(raw)
    try:
        embedded = receipt._embedded(document)
    except ValueError:
        raise OfficialFormHistoryError("OFFICIAL_FORM_EMBEDDED_RESULT_INVALID") from None
    head_doc, result = embedded.get("SC0201"), embedded.get("SJ0326")
    _need(type(head_doc) is dict and head_doc.get("resultCd") == 0 and
          type(head_doc.get("C0201data")) is dict and type(result) is dict and
          result.get("resultCd") == 0, "RESULT_NOT_FINAL_OR_UNAVAILABLE")
    head = head_doc["C0201data"]
    _need(head.get("flgRaceCancel") is False, "RACE_CANCELLED")
    _need(head.get("txtEventDate") == expected_race_id[:4] + "/" + expected_race_id[4:6] + "/" +
          expected_race_id[6:8] and head.get("selRaceNo") == int(expected_race_id[10:]) and
          head.get("aftBetDate") == cutoff.astimezone(JST).strftime("%Y%m%d%H%M"),
          "FINAL_RACE_OR_CUTOFF_MISMATCH")
    video = _VIDEO.fullmatch(result.get("digestUrl", ""))
    _need(video is not None and video[1] == video[3] == expected_race_id[8:10] and
          video[2] == expected_race_id[:8] and int(video[4]) == int(expected_race_id[10:]),
          "FINAL_PUBLISHED_IDENTIFIERS_DISAGREE")
    payment = result.get("haraiGakuSubData")
    _need(head.get("flgKekkaRefund") is False and type(payment) is dict and
          payment.get("APartReturnDispFlg") is False, "REFUND_STATUS_UNVERIFIED")
    _need(result.get("haraiGakuDispFlg") is True and result.get("tyakujyunDispFlg") is True and
          result.get("bikouDispFlg") is False, "RESULT_NOT_FINAL_OR_UNAVAILABLE")
    updated = _updated(result.get("lastUpdateTime"), observed)
    _need(cutoff < updated <= observed, "FINAL_UPDATE_NOT_AFTER_CUTOFF")
    rows = result.get("tyakujyunItemSubData")
    _need(type(rows) is list and len(rows) == len(starters), "FINAL_ROSTER_INCOMPLETE")
    seen, groups, finishes = set(), {}, []
    for row in rows:
        _need(type(row) is dict and type(row.get("syaban")) is str and
              re.fullmatch(r"[1-9]", row["syaban"]), "FINAL_CAR_INVALID")
        car = int(row["syaban"])
        _need(car in by_car and car not in seen and row.get("sensyuRegistNo") == by_car[car],
              "FINAL_REGISTRATION_OR_CAR_MISMATCH")
        seen.add(car)
        status, place, note = _state(row)
        _need(status != "DNS", "REFUND_STATUS_UNVERIFIED")
        if place is not None:
            _need(place <= len(starters), "FINAL_RANK_OUT_OF_RANGE")
            groups.setdefault(place, []).append(car)
        finishes.append(dict(car=car, registration_id=by_car[car], status=status, place=place,
                             official_status_text=note))
    paid = official_result._payouts(payment.get("RT3HaraiGakuDispItemSubData"), detail=True,
                                    starters=set(by_car))
    winners = official_result._winning_orders(groups)
    _need(paid is not None and winners is not None and set(paid) == winners,
          "FINAL_ORDER_AND_PAYOUT_DISAGREE")
    digest = sha256(raw).hexdigest()
    parsed = dict(schema="RACE_AI_KEIRIN_OFFICIAL_SP_FINAL_ORDER_V1", race_id=expected_race_id,
                status="FINAL_NORMAL", refund_status="NONE", official_cutoff_at=cutoff.isoformat(),
                starters=starters, finishes=finishes, winning_triples=[list(x) for x in sorted(winners)],
                published_payout_amounts=[dict(triple=list(x), amount_yen=paid[x]) for x in sorted(winners)],
                payout_unit_state="SOURCE_UNIT_UNVERIFIED", monetary_comparison_eligible=False,
                source_url="https://keirin.jp/sp/race", source_method="POST", source_sha256=digest,
                reference_token_sha256=sha256(ref["token"].encode()).hexdigest(),
                source_updated_at=updated.isoformat(), original_publication_time=None,
                observed_at=observed.isoformat(), provider_revision_ref="observed-content-sha256:" + digest)
    if verified_unit_evidence is not None:
        unit = verified_unit_evidence
        _need(type(unit) is dict and type(source_bytes_by_sha) is dict and
              unit.get("url") in reviewed_unit.UNIT_URLS and
              type(unit.get("verified_payout_basis_yen")) is int and
              unit["verified_payout_basis_yen"] == 100 and
              unit.get("exact_excerpt") == reviewed_unit.UNIT_URLS[unit["url"]],
              "PAYOUT_UNIT_EVIDENCE_INVALID")
        try:
            unit_raw = reviewed_unit._bytes(source_bytes_by_sha, unit.get("source_sha256"))
        except (ValueError, TypeError):
            raise OfficialFormHistoryError("OFFICIAL_FORM_PAYOUT_UNIT_SOURCE_CHANGED") from None
        verified_at = observed if unit_verified_at is None else _aware(unit_verified_at)
        _need(verified_at >= observed and
              unit["exact_excerpt"].encode("utf-8") in unit_raw and
              _aware(unit.get("observed_at")) <= verified_at, "PAYOUT_UNIT_NOT_SUPPORTED")
        parsed.update(payout_unit_state="OFFICIAL_GUIDE_VERIFIED_100_YEN",
                      monetary_comparison_eligible=True,
                      payouts_100yen=[dict(triple=list(x), yen=paid[x]) for x in sorted(winners)],
                      payout_unit_evidence={key: unit[key] for key in
                                            ("url", "source_sha256", "observed_at",
                                             "verified_payout_basis_yen", "exact_excerpt")})
        if unit_verified_at is not None:
            # Preserve when the result itself was actually received. A later
            # independent unit confirmation is a separate observation clock.
            parsed['payout_unit_verified_at'] = verified_at.isoformat()
    return parsed
