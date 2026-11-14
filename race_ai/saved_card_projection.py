"""Pure projection of saved public-card observations, without model inputs.

The caller supplies the original member's independently checked byte hash.
Rendered text establishes only the captured page's stated day. Neither that
text, supplied flags, nor a SHA establishes pre-cutoff publication or rights.
"""
from datetime import date, datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qsl, urlsplit

SCHEMA = "RACE_AI_PRIVATE_CYCLE_VIEW_V1"
INPUT_SCHEMA = "RACE_AI_OWNER_REQUESTED_PUBLIC_CARDS_V1"
SHA = re.compile(r"[a-f0-9]{64}\Z")
JST = timezone(timedelta(hours=9))


def _need(condition, reason):
    if not condition:
        raise ValueError("saved card projection rejected: " + reason)


def _moment(value):
    _need(type(value) is str and len(value) <= 64, "observation clock")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("saved card projection rejected: observation clock") from None
    _need(parsed.utcoffset() is not None, "observation timezone")
    try:
        parsed.astimezone(JST)
    except (ValueError, OverflowError):
        raise ValueError("saved card projection rejected: local observation clock") from None
    return parsed


def _source_url(value, sport, day):
    _need(type(value) is str and 1 <= len(value) <= 2048 and
          not any(c.isspace() or ord(c) < 32 for c in value), "source URL")
    try:
        url = urlsplit(value)
        _need(url.scheme == "https" and url.username is None and url.password is None and
              url.port is None and not url.fragment, "source URL identity")
    except ValueError:
        raise ValueError("saved card projection rejected: source URL identity") from None
    if sport in ("keirin", "autorace"):
        match = re.fullmatch(r"/" + sport + r"/[a-z][a-z0-9-]{0,63}/racecard/"
                             r"(20\d{6})\d{2}/([1-9])/(?:[1-9]|1[0-2])", url.path)
        _need(url.netloc == "www.winticket.jp" and not url.query and match is not None,
              "source URL scope")
        try:
            start = date.fromisoformat(match[1][:4] + "-" + match[1][4:6] + "-" + match[1][6:])
        except ValueError:
            raise ValueError("saved card projection rejected: source meeting day") from None
        _need((start + timedelta(days=int(match[2]) - 1)).isoformat() == day, "source meeting day")
    else:
        _need(url.netloc == "www.keiba.go.jp" and
              url.path == "/KeibaWeb/TodayRaceInfo/DebaTable", "source URL scope")
        try:
            pairs = parse_qsl(url.query, strict_parsing=True, max_num_fields=3)
        except ValueError:
            raise ValueError("saved card projection rejected: source query") from None
        query = dict(pairs)
        _need(len(pairs) == len(query) == 3 and set(query) == {
            "k_raceDate", "k_babaCode", "k_raceNo"}, "source query")
        _need(query["k_raceDate"] == day.replace("-", "/") and
              re.fullmatch(r"\d{1,2}", query["k_babaCode"]) is not None and
              1 <= int(query["k_babaCode"]) <= 99 and
              re.fullmatch(r"(?:0?[1-9]|1[0-2])", query["k_raceNo"]) is not None,
              "source query day or identity")


def project_saved_cards(document, *, artifact_id, original_json_sha256, dataset_status):
    """Return observation-only private UI rows; perform no I/O or inference.

    ``race_id`` remains the exact saved public page URL. No mapping to official
    race identifiers, participant features, forecasts, or result rows occurs.
    """
    _need(dataset_status in ("REAL_REPORTED", "SYNTHETIC_ONLY"), "explicit dataset status")
    _need(type(artifact_id) is int and 0 < artifact_id < 10**16, "artifact identity")
    _need(type(original_json_sha256) is str and SHA.fullmatch(original_json_sha256) is not None,
          "original member SHA")
    _need(type(document) is dict and document.get("schema") == INPUT_SCHEMA, "document schema")
    try:
        size = len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError("saved card projection rejected: JSON value") from None
    _need(size <= 8 * 1024 * 1024, "document size")
    _need(type(document.get("forecast_count")) is int and document["forecast_count"] == 0,
          "observations cannot contain forecasts")
    day = document.get("date_jst")
    try:
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day, "document day")
        parsed_day = date.fromisoformat(day)
    except (ValueError, TypeError):
        raise ValueError("saved card projection rejected: document day") from None
    completed = _moment(document.get("completed_at"))
    _need(completed.astimezone(JST).date() == parsed_day, "completion day")
    sources = document.get("sources")
    _need(type(sources) is list and 1 <= len(sources) <= 160, "source count")
    month = ("0?" if parsed_day.month < 10 else "") + str(parsed_day.month)
    number = ("0?" if parsed_day.day < 10 else "") + str(parsed_day.day)
    day_marker = re.compile(rf"(?<!\d){parsed_day.year}\s*年\s*{month}\s*月\s*{number}\s*日(?!\d)")
    scope = "synthetic" if dataset_status == "SYNTHETIC_ONLY" else "research"
    records, seen = [], set()
    for source in sources:
        _need(type(source) is dict and source.get("sport") in ("keirin", "autorace", "horse") and
              source.get("state") == "CURRENT_DATE_CARD_OBSERVED", "source schema or state")
        sport, uri = source["sport"], source.get("url")
        _source_url(uri, sport, day)
        _need(source.get("final_url") == uri, "source redirect identity")
        _need(uri not in seen, "duplicate source URL")
        seen.add(uri)
        source_sha = source.get("source_sha256")
        _need(type(source_sha) is str and SHA.fullmatch(source_sha) is not None, "source SHA")
        observed = _moment(source.get("observed_at"))
        _need(observed.astimezone(JST).date() == parsed_day and observed <= completed,
              "source observation day or ordering")
        text = source.get("visible_text")
        _need(type(text) is str and 0 < len(text) <= 40000 and day_marker.search(text) is not None,
              "rendered source day")
        observation = dict(source_url=uri, source_uri=uri, final_url=uri,
            observed_at=source["observed_at"], source_sha256=source_sha,
            artifact_id=artifact_id, original_json_sha256=original_json_sha256,
            kind="CAPTURED_PUBLIC_PAGE_FACTS", independent_source_verified=False,
            pre_cutoff_receipt_verified=False)
        records.append(dict(race_id=uri, sport=sport, venue=None, race_no=None,
            event_date_jst=day, cutoff_at=None, saved_cutoff_variants=[], saved_schedule_cutoff_variants=[],
            offering_status="UNKNOWN", scope=scope, source_provenance="OWNER_SAVED_PUBLIC_CARD_OBSERVATION",
            source_sha256=source_sha, source_observation_view=True, source_observation=observation,
            participants=[], prediction=None, comparison_predictions=[], result=None,
            result_observations=[], result_observation_rejections=[], result_revisions=[], history=[],
            missing_reasons=["SOURCE_OBSERVATION_ONLY", "NO_QUALIFIED_NATIVE_FEATURE_SNAPSHOT",
                             "OFFICIAL_CUTOFF_NOT_SAVED", "NO_SAVED_PREDICTION",
                             "NO_SAVED_RESULT_OBSERVATION", "PRIVATE_IMPORT_NOT_INDEPENDENTLY_VERIFIED"]))
    return dict(schema=SCHEMA, dataset_status=dataset_status, event_date_jst=day,
        source_state_sha256=original_json_sha256, source_complete=False,
        coverage_scope="CAPTURED_PUBLIC_CARD_OBSERVATIONS_ONLY", independent_receipt_verified=False,
        independent_source_verified=False,
        original_document_references=[dict(artifact_id=artifact_id, member_name="cards.json",
                                          member_sha256=original_json_sha256)],
        unresolved_learned_dependencies=[],
        note="Saved public-page observations; no native feature snapshots, forecasts, or results.",
        records=records)
