"""Read-only KEIRIN.JP public data, with private, reproducible source receipts.

The ordinary HTTPS source is authoritative; it supplies no digital signature.
Raw receipts must stay in owner-private/encrypted storage. Never print or upload
them to a public repository, artifact, or log. No login, betting, TLS bypass,
retry-after-block, inferred cutoff, inferred payout, or settlement happens here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
from html import unescape
from itertools import permutations
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


SCHEDULE_SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_PUBLIC_SCHEDULE_V1"
RESULT_SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_PUBLIC_RESULT_RECEIPT_V1"
MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 20
JST = timezone(timedelta(hours=9))
KINDS = frozenset({"JSJ057", "JSJ017", "JSJ018", "JSJ001", "JSJ012"})
TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
NORMAL_RESULT_FIELDS = frozenset({
    "race_id", "status", "refund_status", "official_cutoff_at",
    "source_published_at", "observed_at", "source_url", "source_sha256",
    "provider_revision_ref", "winning_triples", "payouts_100yen",
})


class OfficialSourceError(ValueError):
    """No source-backed conclusion can be made from the supplied response."""


class OfficialProviderStop(OfficialSourceError):
    """The provider refused access or rate-limited; do not retry this run."""

    def __init__(self, status):
        self.status = status
        super().__init__(f"OFFICIAL_PROVIDER_STOP_{status}")


def _need(ok, code):
    if not ok:
        raise OfficialSourceError(code)


def _day(value):
    _need(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
          "OFFICIAL_DAY_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise OfficialSourceError("OFFICIAL_DAY_INVALID") from None


def _race(value):
    _need(type(value) is str and re.fullmatch(r"\d{12}", value),
          "OFFICIAL_RACE_ID_INVALID")
    day = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    _day(day)
    _need(value[8:10] != "00" and 1 <= int(value[10:]) <= 12,
          "OFFICIAL_RACE_ID_INVALID")
    return day, value[8:10], int(value[10:])


def _aware(value):
    if type(value) is str:
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise OfficialSourceError("OFFICIAL_TIMESTAMP_INVALID") from None
    _need(isinstance(value, datetime) and value.tzinfo is not None and
          value.utcoffset() is not None, "OFFICIAL_TIMESTAMP_INVALID")
    return value


def _url(kind, **params):
    _need(kind in KINDS, "OFFICIAL_REQUEST_TYPE_INVALID")
    if kind == "JSJ057":
        _need(set(params) == {"kday"} and type(params["kday"]) is str and
              re.fullmatch(r"\d{8}", params["kday"]),
              "OFFICIAL_REQUEST_DAY_INVALID")
    else:
        _need(set(params) == {"encp"} and type(params["encp"]) is str and
              TOKEN.fullmatch(params["encp"]), "OFFICIAL_TOKEN_INVALID")
    return "https://keirin.jp/pc/json?" + urlencode({"type": kind, **params})


def _check_url(url):
    _need(type(url) is str, "OFFICIAL_URL_INVALID")
    try:
        parsed = urlsplit(url)
        params = parse_qs(parsed.query, strict_parsing=True)
        _need(parsed.scheme == "https" and parsed.netloc == "keirin.jp" and
              parsed.path == "/pc/json" and not parsed.fragment and
              all(len(v) == 1 for v in params.values()), "OFFICIAL_URL_INVALID")
        kind = params.pop("type")[0]
        _need(url == _url(kind, **{k: v[0] for k, v in params.items()}),
              "OFFICIAL_URL_NOT_CANONICAL")
        return kind
    except (KeyError, TypeError, ValueError):
        raise OfficialSourceError("OFFICIAL_URL_INVALID") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OfficialSourceError("OFFICIAL_REDIRECT_NOT_FOLLOWED")


def _http_get(url):
    """A bounded ordinary TLS GET. Authentication and redirect following are absent."""
    _check_url(url)
    try:
        with build_opener(_NoRedirect()).open(url, timeout=TIMEOUT_SECONDS) as response:
            _need(response.status == 200 and response.url == url,
                  "OFFICIAL_HTTP_RESPONSE_INVALID")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            _need(content_type == "application/json", "OFFICIAL_JSON_CONTENT_TYPE_REQUIRED")
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (403, 429):
            raise OfficialProviderStop(exc.code) from None
        raise OfficialSourceError(f"OFFICIAL_HTTP_{exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise OfficialSourceError("OFFICIAL_TRANSPORT_UNAVAILABLE") from None
    _need(0 < len(raw) <= MAX_BYTES, "OFFICIAL_SOURCE_SIZE_INVALID")
    return raw


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _need(key not in value, "OFFICIAL_DUPLICATE_JSON_FIELD")
        value[key] = item
    return value


def _invalid_number(_):
    raise OfficialSourceError("OFFICIAL_NONFINITE_JSON_NUMBER")


def _payload(snapshot, expected_url=None):
    _need(type(snapshot) is dict and set(snapshot) == {
        "url", "raw_bytes", "source_sha256", "observed_at"},
        "OFFICIAL_SNAPSHOT_SCHEMA_INVALID")
    _check_url(snapshot["url"])
    _need(expected_url is None or snapshot["url"] == expected_url,
          "OFFICIAL_SNAPSHOT_REQUEST_MISMATCH")
    raw = snapshot["raw_bytes"]
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and
          type(snapshot["source_sha256"]) is str and
          SHA.fullmatch(snapshot["source_sha256"]) and
          sha256(raw).hexdigest() == snapshot["source_sha256"],
          "OFFICIAL_SNAPSHOT_BYTES_OR_HASH_INVALID")
    _aware(snapshot["observed_at"])
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_invalid_number)
    except (UnicodeError, ValueError, RecursionError):
        raise OfficialSourceError("OFFICIAL_JSON_INVALID") from None
    _need(type(data) is dict and type(data.get("resultCd")) is int and
          data["resultCd"] == 0, "OFFICIAL_DATA_NOT_AVAILABLE")
    return data


def _fetch(url, fetcher, clock):
    _check_url(url)
    try:
        raw = (fetcher or _http_get)(url)
    except HTTPError as exc:
        if exc.code in (403, 429):
            raise OfficialProviderStop(exc.code) from None
        raise OfficialSourceError(f"OFFICIAL_HTTP_{exc.code}") from None
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
          "OFFICIAL_SOURCE_SIZE_INVALID")
    stamp = _aware(clock() if clock else datetime.now(timezone.utc)).isoformat()
    snapshot = {"url": url, "raw_bytes": raw,
                "source_sha256": sha256(raw).hexdigest(), "observed_at": stamp}
    _payload(snapshot)
    return snapshot


def _updated(value):
    if value is None or value == "":
        return None
    _need(type(value) is str, "OFFICIAL_UPDATE_TIME_INVALID")
    match = re.fullmatch(r"\s*(\d{4}/\d{2}/\d{2} \d{2}:\d{2}(?::\d{2})?)\s*更新\s*",
                         unescape(value))
    _need(match is not None, "OFFICIAL_UPDATE_TIME_INVALID")
    text = match.group(1)
    try:
        parsed = datetime.strptime(text, "%Y/%m/%d %H:%M:%S" if len(text) == 19
                                   else "%Y/%m/%d %H:%M")
    except ValueError:
        raise OfficialSourceError("OFFICIAL_UPDATE_TIME_INVALID") from None
    return parsed.replace(tzinfo=JST).isoformat()


def _wall_time(day, value):
    if value in (None, "", "--:--"):
        return None
    _need(type(value) is str and re.fullmatch(r"\d{2}:\d{2}", value),
          "OFFICIAL_RACE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(day + "T" + value + ":00+09:00")
    except ValueError:
        raise OfficialSourceError("OFFICIAL_RACE_TIME_INVALID") from None
    return parsed.isoformat()


def _parse_registry(snapshot, day):
    compact = _day(day).strftime("%Y%m%d")
    data = _payload(snapshot, _url("JSJ057", kday=compact))
    _need(type(data.get("reqprm")) is dict and
          data["reqprm"].get("kday") == compact and
          type(data.get("kResultCd")) is int and data["kResultCd"] == 1 and
          type(data.get("kInfo")) is list and len(data["kInfo"]) <= 43,
          "OFFICIAL_REGISTRY_DAY_OR_LIST_INVALID")
    # Only an explicit empty list in this observed successful response shape
    # can represent an empty cohort. Missing data and unfamiliar status values
    # must not be reinterpreted as a no-meeting day.
    venues, codes, tokens = [], set(), set()
    for entry in data["kInfo"]:
        _need(type(entry) is dict, "OFFICIAL_VENUE_INVALID")
        code, name, token, grade = (entry.get(k) for k in
                                    ("KeirinCd", "jyoName", "encPrm", "gradeIconChar"))
        _need(type(code) is str and re.fullmatch(r"\d{2}", code) and code != "00"
              and code not in codes and entry.get("bKeirinCd", code) == code and
              type(name) is str and bool(name.strip()) and
              type(token) is str and TOKEN.fullmatch(token) and token not in tokens and
              grade in {"GP", "G1", "G2", "G3", "F1", "F2"},
              "OFFICIAL_VENUE_IDENTITY_INVALID")
        codes.add(code)
        tokens.add(token)
        venues.append({"venue": name, "venue_code": code, "grade": grade,
                       "event_token": token})
    return sorted(venues, key=lambda v: v["venue_code"])


def _parse_venue(snapshot, day, venue):
    compact = _day(day).strftime("%Y%m%d")
    data = _payload(snapshot, _url("JSJ017", encp=venue["event_token"]))
    code = venue["venue_code"]
    _need(data.get("keirinCd") == code and data.get("kaisaihi") == compact and
          type(data.get("reqprm")) is dict and
          data["reqprm"].get("bkcd") == code and
          data["reqprm"].get("kday") == compact,
          "OFFICIAL_SCHEDULE_IDENTITY_MISMATCH")
    _need(data.get("syusouDispFlag") == 1 and type(data.get("rInfo")) is list and
          1 <= len(data["rInfo"]) <= 12, "OFFICIAL_SCHEDULE_NOT_PUBLISHED")
    updated = _updated(data.get("lastUpdateTime"))
    _need(updated is None or _aware(updated) <= _aware(snapshot["observed_at"]),
          "OFFICIAL_SCHEDULE_UPDATE_AFTER_OBSERVATION")
    races, seen = [], set()
    for row in data["rInfo"]:
        _need(type(row) is dict and type(row.get("raceNo")) is int and
              1 <= row["raceNo"] <= 12 and row["raceNo"] not in seen,
              "OFFICIAL_RACE_NUMBER_INVALID")
        number = row["raceNo"]
        seen.add(number)
        cutoff, start = (_wall_time(day, row.get(k)) for k in ("denTime", "stTime"))
        _need(cutoff is None or start is None or _aware(cutoff) < _aware(start),
              "OFFICIAL_CUTOFF_AFTER_START")
        riders, cars = [], set()
        _need(type(row.get("sInfo")) is list and 1 <= len(row["sInfo"]) <= 9,
              "OFFICIAL_STARTER_LIST_INVALID")
        for rider in row["sInfo"]:
            _need(type(rider) is dict and type(rider.get("syaban")) is int and
                  1 <= rider["syaban"] <= 9 and rider["syaban"] not in cars and
                  type(rider.get("senNo")) is str and
                  re.fullmatch(r"\d{6}", rider["senNo"]),
                  "OFFICIAL_STARTER_IDENTITY_INVALID")
            cars.add(rider["syaban"])
            riders.append({"car": rider["syaban"], "registration_id": rider["senNo"]})
        races.append({
            "race_id": compact + code + f"{number:02d}",
            "venue": venue["venue"], "venue_code": code, "race_no": number,
            "grade": venue["grade"], "event_token": venue["event_token"],
            "official_cutoff_at": cutoff, "start_at": start,
            "starters": sorted(riders, key=lambda r: r["car"]),
            "source_url": snapshot["url"], "source_sha256": snapshot["source_sha256"],
            "source_published_at": updated, "source_observed_at": snapshot["observed_at"],
        })
    _need(seen == set(range(1, len(seen) + 1)), "OFFICIAL_RACE_UNIVERSE_HAS_GAPS")
    block = {
        "venue": venue["venue"], "venue_code": code, "grade": venue["grade"],
        "source_url": snapshot["url"], "source_bytes_sha256": snapshot["source_sha256"],
        "source_available_at": snapshot["observed_at"], "race_numbers": sorted(seen),
        "source_race_day": day,
    }
    return block, sorted(races, key=lambda r: r["race_no"])


def _index(snapshots):
    _need(type(snapshots) is list and len(snapshots) <= 130,
          "OFFICIAL_SNAPSHOT_LIST_INVALID")
    indexed = {}
    for snapshot in snapshots:
        _payload(snapshot)
        _need(snapshot["url"] not in indexed, "OFFICIAL_DUPLICATE_SOURCE_RECEIPT")
        indexed[snapshot["url"]] = snapshot
    return indexed


def _build_schedule(day, snapshots):
    indexed = _index(snapshots)
    registry = indexed[_url("JSJ057", kday=_day(day).strftime("%Y%m%d"))]
    venues = _parse_registry(registry, day)
    blocks, races = [], []
    ordered = [registry]
    for venue in venues:
        snapshot = indexed[_url("JSJ017", encp=venue["event_token"])]
        block, venue_races = _parse_venue(snapshot, day, venue)
        blocks.append(block)
        races.extend(venue_races)
        ordered.append(snapshot)
    _need(len(indexed) == len(ordered), "OFFICIAL_UNEXPECTED_SCHEDULE_RECEIPT")
    return {"schema": SCHEDULE_SCHEMA, "day_jst": day,
            "expected_venue_codes": [v["venue_code"] for v in venues],
            "venue_snapshots": blocks, "races": races, "snapshots": ordered}


def fetch_day_schedule(day_jst, *, fetcher=None, clock=None):
    """Fetch the nationwide roster and each venue's explicit official race times.

    ``fetcher(url) -> bytes`` is an injectable, trusted acquisition boundary.
    A caller may cache bytes by exact URL within one bounded polling run.
    Missing cutoff times remain None; races are retained in the denominator.
    """
    compact = _day(day_jst).strftime("%Y%m%d")
    registry = _fetch(_url("JSJ057", kday=compact), fetcher, clock)
    venues = _parse_registry(registry, day_jst)
    snapshots = [registry]
    for venue in venues:
        snapshots.append(_fetch(_url("JSJ017", encp=venue["event_token"]), fetcher, clock))
    return _build_schedule(day_jst, snapshots)


def reparse_day_schedule(schedule):
    """Reparse the raw receipts; this is integrity checking, not a signature."""
    try:
        return type(schedule) is dict and schedule == _build_schedule(
            schedule["day_jst"], schedule["snapshots"])
    except (OfficialSourceError, KeyError, TypeError, ValueError, RecursionError):
        return False


def _schedule_evidence(schedule, race_id):
    _need(reparse_day_schedule(schedule), "OFFICIAL_SCHEDULE_RECEIPT_INVALID")
    day, code, _ = _race(race_id)
    _need(schedule["day_jst"] == day, "OFFICIAL_SCHEDULE_RACE_DAY_MISMATCH")
    indexed = _index(schedule["snapshots"])
    registry = indexed[_url("JSJ057", kday=_day(day).strftime("%Y%m%d"))]
    venue = next((v for v in _parse_registry(registry, day) if v["venue_code"] == code), None)
    _need(venue is not None, "OFFICIAL_RACE_VENUE_NOT_REGISTERED")
    return {"day_jst": day, "registry_snapshot": registry,
            "schedule_snapshot": indexed[_url("JSJ017", encp=venue["event_token"])]}


def _evidence_race(evidence, race_id):
    day, code, _ = _race(race_id)
    _need(type(evidence) is dict and set(evidence) == {
        "day_jst", "registry_snapshot", "schedule_snapshot"} and evidence["day_jst"] == day,
        "OFFICIAL_RESULT_SCHEDULE_EVIDENCE_INVALID")
    venue = next((v for v in _parse_registry(evidence["registry_snapshot"], day)
                  if v["venue_code"] == code), None)
    _need(venue is not None, "OFFICIAL_RESULT_VENUE_NOT_REGISTERED")
    _, races = _parse_venue(evidence["schedule_snapshot"], day, venue)
    race = next((r for r in races if r["race_id"] == race_id), None)
    _need(race is not None, "OFFICIAL_RESULT_RACE_NOT_REGISTERED")
    return race, races


def _summary_row(snapshot, race, races):
    data = _payload(snapshot, _url("JSJ018", encp=race["event_token"]))
    _need(data.get("bkcd") == race["venue_code"] and
          data.get("kday") == race["race_id"][:8], "OFFICIAL_RESULT_IDENTITY_MISMATCH")
    rows = data.get("resultList")
    _need(type(rows) is list and len(rows) <= 12 and
          type(data.get("raceCount")) is int and data["raceCount"] == len(rows),
          "OFFICIAL_RESULT_LIST_INVALID")
    known = {r["race_no"] for r in races}
    seen, selected = set(), None
    for row in rows:
        _need(type(row) is dict and type(row.get("rclblRaceNo")) is str and
              re.fullmatch(r"(?:[1-9]|1[0-2])R", row["rclblRaceNo"]),
              "OFFICIAL_RESULT_RACE_NUMBER_INVALID")
        number = int(row["rclblRaceNo"][:-1])
        _need(number in known and number not in seen, "OFFICIAL_RESULT_RACE_SCOPE_INVALID")
        seen.add(number)
        if number == race["race_no"]:
            selected = row
    if selected is not None:
        _need(type(selected.get("raceRVPrm")) is str and TOKEN.fullmatch(selected["raceRVPrm"]),
              "OFFICIAL_RESULT_RACE_TOKEN_INVALID")
    return selected


def _header(snapshot, race, races, token):
    data = _payload(snapshot, _url("JSJ001", encp=token)).get("C0201data")
    _need(type(data) is dict and data.get("selKaisai") == race["race_id"][:8] and
          data.get("selKjyoCd") == race["venue_code"] and
          type(data.get("selRaceNo")) is int and data["selRaceNo"] == race["race_no"] and
          data.get("encSelParaK") == race["event_token"] and data.get("encSelParaR") == token,
          "OFFICIAL_RESULT_HEADER_IDENTITY_MISMATCH")
    choices = data.get("C0201race")
    _need(type(choices) is list and len(choices) == len(races) and
          all(type(choice) is dict for choice in choices) and
          choices[race["race_no"] - 1].get("encParaR") == token and
          type(data.get("flgRaceCancel")) is bool and
          type(data.get("flgSectionCancel")) is bool,
          "OFFICIAL_RESULT_HEADER_RACE_MAP_INVALID")
    return data


def _money(value, suffix):
    if type(value) is not str or not re.fullmatch(
            r"(?:[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)" + suffix, value):
        return None
    digits = value[:-len(suffix)] if suffix else value
    amount = int(digits.replace(",", ""))
    return amount if 100 <= amount <= 10**9 and amount % 10 == 0 else None


def _payouts(rows, *, detail, starters):
    if type(rows) is not list or not 1 <= len(rows) <= 20:
        return None
    paid = {}
    for entry in rows:
        if type(entry) is not dict or (detail and entry.get("kumiDispFlg") is not True):
            return None
        combination = entry.get("kumiBan" if detail else "kumi")
        amount = _money(entry.get("haraiGaku" if detail else "kingaku"), "" if detail else "円")
        if type(combination) is not str or not re.fullmatch(r"[1-9]-[1-9]-[1-9]", combination):
            return None
        triple = tuple(int(n) for n in combination.split("-"))
        if amount is None or len(set(triple)) != 3 or not set(triple) <= starters or triple in paid:
            return None
        paid[triple] = amount
    return paid


def _finish_groups(detail, row, race):
    finishes = detail.get("tyakujyunItemSubData")
    if type(finishes) is not list or len(finishes) != len(race["starters"]):
        return None
    starters = {r["car"]: r["registration_id"] for r in race["starters"]}
    seen, groups = set(), {}
    for entry in finishes:
        if type(entry) is not dict:
            return None
        car, place = entry.get("syaban"), entry.get("tyaku")
        if type(car) is not str or not re.fullmatch(r"[1-9]", car) or int(car) in seen:
            return None
        car = int(car)
        if car not in starters or entry.get("sensyuRegistNo") != starters[car]:
            return None
        seen.add(car)
        if type(place) is str and re.fullmatch(r"[1-9]", place):
            groups.setdefault(int(place), []).append(car)
        elif place not in ("落", "失", "棄", "落車棄権", "失格", "途中欠場"):
            return None
    if seen != set(starters):
        return None
    for rank in (1, 2, 3):
        summary = row.get(f"tyakui{rank}List")
        if type(summary) is not list or any(type(x) is not dict or
                x.get("rclblTyakui") != rank or type(x.get("rclblSyaban")) is not int
                for x in summary):
            return None
        if sorted(x["rclblSyaban"] for x in summary) != sorted(groups.get(rank, [])):
            return None
    return groups


def _winning_orders(groups):
    prefixes, preceding = {()}, 0
    for rank in sorted(groups):
        if preceding >= 3:
            break
        cars = groups[rank]
        if rank != preceding + 1:
            return None
        take = min(3 - preceding, len(cars))
        prefixes = {prefix + order for prefix in prefixes for order in permutations(cars, take)}
        preceding += len(cars)
    if preceding < 3 or not 1 <= len(prefixes) <= 20:
        return None
    return prefixes


def _result_revision_sha256(result):
    # The settlement receipt uses this exact canonical JSON, without a newline.
    # A later reread of identical source bytes must not change revision identity.
    value = {key: item for key, item in result.items() if key != "observed_at"}
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _checked_previous_result(previous, race):
    """Check the caller's reverified prior result, without claiming its origin.

    The caller must retrieve the prior receipt from authenticated history and
    reparse its saved source bytes. This contract check cannot replace that step.
    """
    _need(type(previous) is dict and set(previous) == NORMAL_RESULT_FIELDS and
          previous["race_id"] == race["race_id"] and
          previous["status"] == "FINAL_NORMAL" and previous["refund_status"] == "NONE",
          "OFFICIAL_PREVIOUS_RESULT_IDENTITY_OR_STATUS_INVALID")
    _need(_check_url(previous["source_url"]) == "JSJ012" and
          type(previous["source_sha256"]) is str and SHA.fullmatch(previous["source_sha256"]) and
          previous["provider_revision_ref"] == "observed-content-sha256:" + previous["source_sha256"],
          "OFFICIAL_PREVIOUS_RESULT_SOURCE_INVALID")
    _need(all(type(previous[key]) is str for key in
              ("official_cutoff_at", "source_published_at", "observed_at")),
          "OFFICIAL_PREVIOUS_RESULT_CLOCK_INVALID")
    cutoff, published, observed = (_aware(previous[key]) for key in
                                   ("official_cutoff_at", "source_published_at", "observed_at"))
    _need(cutoff.astimezone(JST).strftime("%Y%m%d") == race["race_id"][:8] and
          cutoff < published <= observed, "OFFICIAL_PREVIOUS_RESULT_CLOCK_INVALID")
    starters = {r["car"] for r in race["starters"]}

    def triple(value):
        _need(type(value) is list and len(value) == 3 and
              all(type(car) is int and car in starters for car in value) and
              len(set(value)) == 3, "OFFICIAL_PREVIOUS_RESULT_TRIPLE_INVALID")
        return tuple(value)

    winners, payouts = previous["winning_triples"], previous["payouts_100yen"]
    _need(type(winners) is list and type(payouts) is list and
          1 <= len(winners) == len(payouts) <= 20,
          "OFFICIAL_PREVIOUS_RESULT_PAYOUTS_INVALID")
    won, paid = [triple(value) for value in winners], []
    for row in payouts:
        _need(type(row) is dict and set(row) == {"triple", "yen"} and
              type(row["yen"]) is int and 100 <= row["yen"] <= 10**9 and row["yen"] % 10 == 0,
              "OFFICIAL_PREVIOUS_RESULT_PAYOUTS_INVALID")
        paid.append(triple(row["triple"]))
    _need(len(set(won)) == len(won) and len(set(paid)) == len(paid) and set(won) == set(paid),
          "OFFICIAL_PREVIOUS_RESULT_PAYOUTS_INVALID")
    return _result_revision_sha256(previous), published


def _record(race_id, evidence, snapshots, previous_result=None):
    race, races = _evidence_race(evidence, race_id)
    provenance = {
        "source_kind": "KEIRIN_JP_PUBLIC_HTTPS", "cryptographic_signature_verified": False,
        "source_published_at_basis": "JSJ012.lastUpdateTime",
        "publication_time_is_page_update": True,
        "provider_issued_revision_id": None,
        "revision_ref_kind": "LOCAL_OBSERVED_CONTENT_SHA256",
        "schedule_evidence": evidence, "previous_result": deepcopy(previous_result),
    }
    output = {"schema": RESULT_SCHEMA, "race_id": race_id, "state": "HOLD_RESULT_PENDING",
              "result": None, "provenance": provenance, "snapshots": snapshots}

    def hold(state):
        output["state"] = state
        return output

    indexed = _index(snapshots)
    if race["official_cutoff_at"] is None:
        _need(not indexed, "OFFICIAL_UNEXPECTED_RESULT_RECEIPT")
        return hold("HOLD_OFFICIAL_CUTOFF_UNAVAILABLE")
    summary_url = _url("JSJ018", encp=race["event_token"])
    row = _summary_row(indexed[summary_url], race, races)
    if row is None:
        _need(set(indexed) == {summary_url}, "OFFICIAL_UNEXPECTED_RESULT_RECEIPT")
        return output
    token = row["raceRVPrm"]
    header_url, detail_url = _url("JSJ001", encp=token), _url("JSJ012", encp=token)
    _need(set(indexed) == {summary_url, header_url, detail_url},
          "OFFICIAL_RESULT_RECEIPTS_INCOMPLETE")
    head = _header(indexed[header_url], race, races, token)
    detail_snapshot = indexed[detail_url]
    detail = _payload(detail_snapshot, detail_url)
    if head["flgRaceCancel"] or head["flgSectionCancel"]:
        return hold("HOLD_CANCELLATION_DETAILS_UNVERIFIED")
    current = head.get("C0201racedtl")
    if type(current) is not dict or _wall_time(evidence["day_jst"], current.get("aftBetTime")) != race["official_cutoff_at"]:
        return hold("HOLD_OFFICIAL_CUTOFF_CHANGED")
    if head["C0201race"][race["race_no"] - 1].get("flgRaceEnd") is not True:
        return output
    payment = detail.get("haraiGakuSubData")
    if (row.get("kessyaList") != [] or type(payment) is not dict or
            payment.get("APartReturnDispFlg") is not False or
            detail.get("syabanItemDispFlg") is not False):
        return hold("HOLD_REFUND_DETAILS_UNVERIFIED")
    if (detail.get("haraiGakuDispFlg") is not True or
            detail.get("tyakujyunDispFlg") is not True or detail.get("bikouDispFlg") is not False):
        return hold("HOLD_RESULT_STATUS_UNVERIFIED")
    published = _updated(detail.get("lastUpdateTime"))
    if published is None:
        return hold("HOLD_PUBLICATION_TIME_UNAVAILABLE")
    if not (_aware(race["official_cutoff_at"]) < _aware(published) <= _aware(detail_snapshot["observed_at"])):
        return hold("HOLD_PUBLICATION_TIME_INCONSISTENT")
    starters = {r["car"] for r in race["starters"]}
    detail_paid = _payouts(payment.get("RT3HaraiGakuDispItemSubData"), detail=True, starters=starters)
    summary_paid = _payouts(row.get("harai3renList"), detail=False, starters=starters)
    if detail_paid is None or summary_paid is None:
        return hold("HOLD_SPECIAL_PAYOUT_UNVERIFIED")
    groups = _finish_groups(detail, row, race)
    expected = _winning_orders(groups) if groups is not None else None
    if detail_paid != summary_paid or expected != set(detail_paid):
        return hold("HOLD_OFFICIAL_RESULT_DISAGREEMENT")
    winners = sorted(detail_paid)
    result = {
        "race_id": race_id, "status": "FINAL_NORMAL", "refund_status": "NONE",
        "official_cutoff_at": race["official_cutoff_at"], "source_published_at": published,
        "observed_at": detail_snapshot["observed_at"], "source_url": detail_url,
        "source_sha256": detail_snapshot["source_sha256"],
        "provider_revision_ref": "observed-content-sha256:" + detail_snapshot["source_sha256"],
        "winning_triples": [list(w) for w in winners],
        "payouts_100yen": [{"triple": list(w), "yen": detail_paid[w]} for w in winners],
    }
    if previous_result is not None:
        prior_digest, prior_published = _checked_previous_result(previous_result, race)
        fields = ("status", "refund_status", "official_cutoff_at", "winning_triples", "payouts_100yen")
        changed = any(previous_result[k] != result[k] for k in fields)
        newer = _aware(published) > prior_published
        regressed = _aware(published) < prior_published
        if regressed or (changed and not newer):
            provenance["candidate_result"] = result
            provenance["revision_review_reason"] = (
                "OFFICIAL_PAGE_UPDATE_REGRESSED" if regressed
                else "OFFICIAL_PAGE_UPDATE_NOT_NEWER")
            return hold("HOLD_RESULT_REVISION_REVIEW")
        if changed:
            provenance["revision_relationship"] = {
                "kind": "NORMAL_RESULT_CORRECTION",
                "previous_result_revision_sha256": prior_digest,
                "previous_source_sha256": previous_result["source_sha256"],
                "previous_source_published_at": previous_result["source_published_at"],
                "current_result_revision_sha256": _result_revision_sha256(result),
            }
    output.update(state="OFFICIAL_FINAL", result=result)
    return output


def fetch_race_result(race_id, *, schedule=None, fetcher=None, clock=None, previous_result=None):
    """Return a source-bound normal result, or a reasoned HOLD without money guesses.

    Result lists and cutoffs are checked separately from the actual result detail.
    Same-rank finishers are expanded only to verify the official payout orders;
    payout amounts always come from the two official result views. ``previous_result``
    must come from a reverified prior receipt in the caller's authenticated history.
    A semantic correction needs a strictly newer official page-update timestamp;
    the new result links to the prior canonical revision without overwriting it.
    """
    day, _, _ = _race(race_id)
    if schedule is None:
        schedule = fetch_day_schedule(day, fetcher=fetcher, clock=clock)
    evidence = _schedule_evidence(schedule, race_id)
    race, races = _evidence_race(evidence, race_id)
    snapshots = []
    if race["official_cutoff_at"] is not None:
        summary = _fetch(_url("JSJ018", encp=race["event_token"]), fetcher, clock)
        snapshots.append(summary)
        row = _summary_row(summary, race, races)
        if row is not None:
            token = row["raceRVPrm"]
            snapshots.append(_fetch(_url("JSJ001", encp=token), fetcher, clock))
            snapshots.append(_fetch(_url("JSJ012", encp=token), fetcher, clock))
    return _record(race_id, evidence, snapshots, previous_result)


def reparse_race_result(record):
    """Verify every normalized value against its saved official response bytes."""
    try:
        if type(record) is not dict or type(record.get("provenance")) is not dict:
            return False
        provenance = record["provenance"]
        return record == _record(record["race_id"], provenance["schedule_evidence"],
                                 record["snapshots"], provenance.get("previous_result"))
    except (OfficialSourceError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        return False
