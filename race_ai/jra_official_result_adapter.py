"""Parse official JRA results separately from frozen pre-race native inputs.

No fetching, encryption, timestamp attestation or source-use grant occurs here.
Normal labels require the complete registered roster, unique numeric placings
and one matching official trifecta payout. Other outcomes remain unscored.
"""
from datetime import date
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from .jra_official_sparse_adapter import _document, _clock, _Node, VENUES


SCHEMA = "RACE_AI_JRA_OFFICIAL_RESULT_SOURCE_V1"


def _need(ok, reason):
    if not ok:
        raise ValueError("JRA_RESULT_"+reason)


def _cells(node, tag=None, classes=()):
    return list(node.nodes(tag, classes))


def _one(node, tag=None, classes=()):
    found = _cells(node, tag, classes)
    _need(len(found) == 1, "SOURCE_STRUCTURE")
    return found[0]


def _identity(document, source_url):
    matches = [re.fullmatch(r"レース結果\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*\([^)]*\)\s*(\d+)回([^\d\s]+)(\d+)日\s*(\d+)レース", n.text())
               for n in document.nodes("h1")]
    matches = [m for m in matches if m]
    _need(len(matches) == 1, "RACE_HEADING")
    y, m, d, meeting, venue, day, number = matches[0].groups()
    event = date(int(y), int(m), int(d))
    _need(venue in VENUES and 1 <= int(number) <= 12, "RACE_VENUE_OR_NUMBER")
    url = urlsplit(source_url); query = parse_qs(url.query)
    cnames = query.get("CNAME", [])
    _need(url.path == "/JRADB/accessS.html" and set(query) == {"CNAME"} and len(cnames) == 1, "RESULT_SOURCE_URL")
    cname = re.fullmatch(r"pw01sde10(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[A-Fa-f0-9]{2}", cnames[0])
    _need(cname is not None and cname.groups() == (VENUES[venue], y, f"{int(meeting):02d}",
          f"{int(day):02d}", f"{int(number):02d}", event.strftime("%Y%m%d")), "URL_BODY_RACE_IDENTITY")
    return dict(race_id=f"horse:{event.isoformat()}:jra-{VENUES[venue]}:{int(number)}",
                event_date_jst=event.isoformat(), venue=venue, race_no=int(number))


def _horse_identity(cell, source_url):
    links = _cells(cell, "a")
    _need(len(links) == 1, "REGISTERED_HORSE_ID_REQUIRED")
    url = urlsplit(urljoin(source_url, links[0].attrs.get("href", "")))
    query = parse_qs(url.query); cnames = query.get("CNAME", [])
    _need(url.scheme == "https" and url.hostname in ("www.jra.go.jp", "jra.go.jp") and
          url.username is None and url.password is None and url.port is None and not url.fragment and
          url.path == "/JRADB/accessU.html" and set(query) == {"CNAME"} and len(cnames) == 1, "REGISTERED_HORSE_ID_REQUIRED")
    # Card/result navigation contexts differ; the registered ten-digit horse
    # identifier remains the same in the observed dud00 and dud10 links.
    match = re.fullmatch(r"pw01dud(?:00|10)(\d{10})/[A-Fa-f0-9]{2}", cnames[0])
    _need(match is not None, "REGISTERED_HORSE_ID_REQUIRED")
    return "jra:"+match[1]


def _state(facts, status, reason, *, refunds=()):
    facts.update(status=status, reason=reason, ordered_top3=[], payout_per_100_yen=None,
                 refund_numbers=sorted(set(refunds)))
    return facts


def parse_official_result_source(raw, metadata, *, now):
    """Inspect official source facts; this alone proves no frozen input pairing.

    JRA's ordinary official result payout is the published return per100yen.
    This parser never multiplies it by popularity, stake counts or ticket count.
    """
    now = _clock(now)
    document, source_url, capture = _document(raw, metadata, now)
    race = _identity(document, source_url)
    facts = dict(schema=SCHEMA, race=race, roster={}, finish_rows=[], captured_at=capture.isoformat(),
                 published_at=None, source_ref=source_url, source_sha256=metadata["source_sha256"],
                 future_frozen_input_paired=False)
    status_nodes = [n.text() for n in document.nodes(classes=("race_status",))]
    if any(any(word in text for word in ("開催中止", "競走取りやめ", "レース中止")) for text in status_nodes):
        return _state(facts, "special", "EXPLICIT_RACE_CANCELLATION")
    if any(any(word in text for word in ("未確定", "審議中", "確定後", "未発表")) for text in status_nodes):
        return _state(facts, "pending", "RESULT_NOT_FINAL")
    tables = _cells(document, "table", ("basic", "narrow-xy", "striped"))
    if not tables:
        return _state(facts, "pending", "RESULT_TABLE_NOT_AVAILABLE")
    _need(len(tables) == 1, "AMBIGUOUS_RESULT_TABLE")
    table = tables[0]
    _need(_one(table, "th", ("place",)).text() == "着順" and
          re.sub(r"\s+", "", _one(table, "th", ("num",)).text()) == "馬番", "RESULT_TABLE_HEADERS")
    rows = [r for r in table.nodes("tr") if any(isinstance(c, _Node) and c.tag == "td" for c in r.children)]
    if not rows:
        return _state(facts, "pending", "RESULT_ROWS_NOT_AVAILABLE")
    _need(3 <= len(rows) <= 18, "RESULT_FIELD_SIZE")
    seen_ids = set(); refunds = []; nonfinish = False; pending = False
    for row in rows:
        number = _one(row, "td", ("num",)).text()
        _need(re.fullmatch(r"\d{1,2}", number) is not None, "RESULT_NUMBER")
        number = int(number)
        identity = _horse_identity(_one(row, "td", ("horse",)), source_url)
        _need(1 <= number <= 18 and str(number) not in facts["roster"] and identity not in seen_ids, "DUPLICATE_OR_INVALID_ENTRANT")
        facts["roster"][str(number)] = identity; seen_ids.add(identity)
        place = re.sub(r"\s+", "", _one(row, "td", ("place",)).text())
        if place.isdecimal():
            position = int(place)
            _need(1 <= position <= len(rows), "INVALID_OFFICIAL_PLACING")
        else:
            position = None
            if place in ("", "-", "--", "未確定", "未発表"):
                pending = True
            else:
                nonfinish = True
                if "取消" in place or "除外" in place:
                    refunds.append(number)
        facts["finish_rows"].append(dict(number=number, identity=identity, finish=position))
    if nonfinish:
        return _state(facts, "special", "NONFINISH_OR_SPECIAL_PLACING", refunds=refunds)
    if pending:
        return _state(facts, "pending", "RESULT_PLACINGS_NOT_FINAL")
    ranks = [r["finish"] for r in facts["finish_rows"]]
    if sorted(ranks) != list(range(1, len(rows)+1)):
        return _state(facts, "special", "TIED_OR_NONUNIQUE_PLACINGS")
    units = _cells(document, "div", ("refund_unit",))
    if not units:
        return _state(facts, "pending", "PAYOUT_NOT_AVAILABLE")
    _need(len(units) == 1, "AMBIGUOUS_PAYOUT_AREA")
    unit = units[0]
    # Only actual payout records establish a refund. The standard page-wide
    # caution also mentions refunds on ordinary settled pages.
    refund_declared = False
    for item in unit.nodes("li"):
        labels = [n.text() for n in item.nodes("dt")]
        if set(item.attrs.get("class", "").split()) & {"refund", "henkan", "cancel"} or any("返還" in text for text in labels):
            refund_declared = True
            for cell in item.nodes(classes=("num",)):
                if re.fullmatch(r"\d{1,2}", cell.text()) and str(int(cell.text())) in facts["roster"]:
                    refunds.append(int(cell.text()))
    if refund_declared:
        return _state(facts, "special", "EXPLICIT_RESULT_REFUND", refunds=refunds)
    trifectas = _cells(unit, "li", ("tierce",))
    if not trifectas:
        return _state(facts, "pending", "TRIFECTA_NOT_AVAILABLE")
    if len(trifectas) != 1:
        return _state(facts, "special", "MULTIPLE_TRIFECTA_RECORDS")
    trifecta = trifectas[0]
    _need(_one(trifecta, "dt").text() == "3連単", "TRIFECTA_LABEL")
    payments = _cells(trifecta, "div", ("line",))
    if len(payments) != 1:
        return _state(facts, "special" if payments else "pending", "TRIFECTA_PAYMENT_COUNT")
    combo = re.fullmatch(r"\s*(\d{1,2})\s*[-→]\s*(\d{1,2})\s*[-→]\s*(\d{1,2})\s*", _one(payments[0], "div", ("num",)).text())
    amount = re.fullmatch(r"\s*([\d,]+)\s*円\s*", _one(payments[0], "div", ("yen",)).text())
    if combo is None or amount is None:
        return _state(facts, "special", "SPECIAL_TRIFECTA_PAYMENT")
    winning = list(map(int, combo.groups())); payout = int(amount[1].replace(",", ""))
    _need(len(set(winning)) == 3 and all(str(n) in facts["roster"] for n in winning) and
          0 < payout <= 10**9, "INVALID_TRIFECTA_PAYMENT")
    ordered = [r["number"] for r in sorted(facts["finish_rows"], key=lambda r: r["finish"])[:3]]
    _need(winning == ordered, "FINISH_TRIFECTA_CONFLICT")
    facts.update(status="settled", reason="ORDINARY_SETTLED_RESULT", ordered_top3=ordered,
                 payout_per_100_yen=payout, refund_numbers=[])
    return facts


def parse_result(raw, metadata, *, frozen_native_payload, now, source_rights_ref):
    """Return a generic settled/pending/special observation for admitted intake.

    The caller separately authenticates the frozen input artifact and result
    source archive. This method checks their exact semantic identity only.
    """
    now = _clock(now)
    _need(type(source_rights_ref) is str and 0 < len(source_rights_ref) <= 256, "SOURCE_PURPOSE_REQUIRED")
    _need(type(frozen_native_payload) is dict and type(frozen_native_payload.get("snapshot")) is dict, "FROZEN_NATIVE_INPUT_REQUIRED")
    snapshot = frozen_native_payload["snapshot"]; race = snapshot.get("race")
    _need(type(race) is dict and race.get("sport") == "horse", "FROZEN_HORSE_RACE_REQUIRED")
    facts = parse_official_result_source(raw, metadata, now=now)
    _need(all(race.get(k) == facts["race"][k] for k in ("race_id", "venue", "event_date_jst")), "FROZEN_RESULT_RACE_MISMATCH")
    capture = _clock(facts["captured_at"]); cutoff = _clock(race.get("sales_cutoff_at"))
    _need(_clock(race.get("as_of")) < cutoff < capture <= now, "FROZEN_RESULT_CAPTURE_CLOCK")
    participants = snapshot.get("participants")
    _need(type(participants) is list and 3 <= len(participants) <= 18 and
          all(type(p) is dict and type(p.get("number")) is int and type(p.get("identity")) is str for p in participants), "FROZEN_REGISTERED_ROSTER_REQUIRED")
    roster = {str(p["number"]):p["identity"] for p in participants}
    _need(len(roster) == len(participants) and len(set(roster.values())) == len(roster), "FROZEN_REGISTERED_ROSTER_REQUIRED")
    verified = bool(facts["roster"])
    if verified:
        _need(facts["roster"] == roster, "FROZEN_RESULT_REGISTERED_ROSTER_MISMATCH")
    _need(facts["status"] != "settled" or verified, "SETTLED_ROSTER_REQUIRED")
    return dict(race_id=race["race_id"], sport="horse", status=facts["status"], reason=facts["reason"],
                ordered_top3=facts["ordered_top3"], roster=facts["roster"], identity_verified=verified,
                captured_at=facts["captured_at"], published_at=None, source_ref=facts["source_ref"],
                source_rights_ref=source_rights_ref, source_sha256=facts["source_sha256"],
                payout_per_100_yen=facts["payout_per_100_yen"], refund_numbers=facts["refund_numbers"],
                closed_at=race["sales_cutoff_at"])
