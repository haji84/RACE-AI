"""Pure JRA card-to-native sparse conversion; no fetching or source grants.

Only complete, explicitly displayed historical finish facts enter the existing
horse-history transforms. Raw odds, current results and unobserved ratings are
never copied into native inputs. Callers authenticate and encrypt preservation.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from unicodedata import normalize
from urllib.parse import parse_qs, urljoin, urlsplit

from . import comprehensive_four_sport_models as native
from .horse_history_features import derive, _performance


JST = timezone(timedelta(hours=9))
RULE_URL = "https://www.jra.go.jp/dento/soku/instructions/hatsubai/jra.html"
CHANNEL = "SOKU_PAT_JRA_CENTRAL_ORDINARY_BET"
VENUES = {"札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05",
          "中山": "06", "中京": "07", "京都": "08", "阪神": "09", "小倉": "10"}
MAX_BYTES = 2_000_000
RECENT_TRANSFORM = "official-prior-finish-percentile-all-surfaces-last3-v1"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _need(ok, reason):
    if not ok:
        raise ValueError("JRA_SPARSE_" + reason)


def _clock(value):
    try:
        stamp = value if type(value) is datetime else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("JRA_SPARSE_AWARE_CLOCK_REQUIRED") from None
    _need(stamp.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
    return stamp


class _Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def nodes(self, tag=None, classes=()):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and set(classes) <= set(child.attrs.get("class", "").split()):
                    yield child
                yield from child.nodes(tag, classes)

    def text(self):
        if self.tag in ("script", "style", "noscript"):
            return ""
        return normalize("NFKC", " ".join(c.text() if isinstance(c, _Node) else c for c in self.children)).strip()


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def _document(raw, metadata, now):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and type(metadata) is dict, "BOUNDED_SOURCE_REQUIRED")
    _need(metadata.get("status") == 200 and type(metadata.get("byte_count")) is int and
          metadata["byte_count"] == len(raw) and metadata.get("source_sha256") == sha256(raw).hexdigest(), "SOURCE_BYTES_MISMATCH")
    url = metadata.get("source_url")
    _need(type(url) is str and metadata.get("final_url") == url, "SOURCE_URL_MISMATCH")
    parsed = urlsplit(url)
    _need(parsed.scheme == "https" and parsed.hostname in ("www.jra.go.jp", "jra.go.jp") and
          parsed.username is None and parsed.password is None and parsed.port is None and not parsed.fragment, "OFFICIAL_SOURCE_REQUIRED")
    capture = _clock(metadata.get("response_received_at"))
    _need(_clock(metadata.get("fetched_at")) <= capture <= now, "SOURCE_AVAILABILITY_CLOCK")
    headers = metadata.get("headers", {})
    _need(type(headers) is dict, "SOURCE_HEADERS_REQUIRED")
    content_type = next((str(v) for k, v in headers.items() if k.lower() == "content-type"), "")
    _need(content_type.split(";", 1)[0].strip().lower() in ("text/html", "application/xhtml+xml"), "SOURCE_MIME")
    prefix = raw[:8192].decode("ascii", "ignore")
    declaration = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type + " " + prefix, re.I)
    encoding = declaration[1].lower() if declaration else metadata.get("encoding")
    encoding = {"shift_jis": "cp932", "shift-jis": "cp932", "utf8": "utf-8"}.get(encoding, encoding)
    _need(encoding in ("cp932", "utf-8"), "EXPLICIT_SOURCE_CHARSET_REQUIRED")
    try:
        html = raw.decode(encoding, "strict")
    except UnicodeError:
        raise ValueError("JRA_SPARSE_SOURCE_CHARSET") from None
    parser = _Parser(); parser.feed(html)
    return parser.root, url, capture


def _one(node, *, tag=None, classes=()):
    found = list(node.nodes(tag, classes))
    _need(len(found) == 1, "SOURCE_STRUCTURE")
    return found[0]


def _source(metadata, rights):
    return dict(source_ref=metadata["source_url"], source_rights_ref=rights,
                source_sha256=metadata["source_sha256"], captured_at=metadata["response_received_at"], published_at=None)


def _race(document, source_url):
    heads = []
    pattern = r"出馬表\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*\([^)]*\)\s*(\d+)回([^\d\s]+)(\d+)日\s*(\d+)レース"
    for heading in document.nodes("h1"):
        match = re.fullmatch(pattern, heading.text())
        if match:
            heads.append(match)
    _need(len(heads) == 1, "CARD_RACE_HEADING")
    y, m, d, meeting, venue, meeting_day, race_no = heads[0].groups()
    event = date(int(y), int(m), int(d))
    _need(venue in VENUES and 1 <= int(race_no) <= 12, "CARD_VENUE_OR_RACE")
    url = urlsplit(source_url)
    query = parse_qs(url.query)
    cname = query.get("CNAME", [])
    _need(url.path == "/JRADB/accessD.html" and set(query) == {"CNAME"} and len(cname) == 1, "CARD_URL")
    identity = re.fullmatch(r"pw01dde01(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[A-Fa-f0-9]{2}", cname[0])
    _need(identity is not None and identity.groups() == (VENUES[venue], y, f"{int(meeting):02d}",
          f"{int(meeting_day):02d}", f"{int(race_no):02d}", event.strftime("%Y%m%d")), "CARD_URL_BODY_IDENTITY")
    times = [re.fullmatch(r"発走時刻\s*:\s*(\d{1,2})時(\d{1,2})分", n.text())
             for n in document.nodes("div", ("cell", "time"))]
    times = [x for x in times if x]
    _need(len(times) == 1, "OFFICIAL_START_REQUIRED")
    hour, minute = map(int, times[0].groups())
    _need(0 <= hour <= 23 and 0 <= minute <= 59, "OFFICIAL_START_REQUIRED")
    start = datetime(event.year, event.month, event.day, hour, minute, tzinfo=JST)
    course = _one(document, tag="div", classes=("cell", "course")).text()
    _need(not any("障害" in n.text() for n in document.nodes("div", ("cell", "category"))), "UNVALIDATED_JUMP_DISCIPLINE")
    distance = re.search(r"コース\s*:\s*([\d,]+)\s*メートル\s*\((芝|ダート|ダ)[・)]", course)
    _need(distance is not None and "障害" not in course, "FLAT_DISTANCE_SURFACE_REQUIRED")
    metres = int(distance[1].replace(",", ""))
    _need(100 <= metres <= 10000, "DISTANCE_INVALID")
    return dict(race_id=f"horse:{event.isoformat()}:jra-{VENUES[venue]}:{int(race_no)}", sport="horse",
                venue=venue, event_date_jst=event.isoformat(), distance_m=metres,
                surface="turf" if distance[2] == "芝" else "dirt", race_kind="JRA_OFFICIAL_CARD", race_revision=1), start


def _cutoff(evidence, race, start, now):
    _need(type(evidence) is dict and set(evidence) == {"raw", "metadata", "sales_channel", "rule_id"}, "CUTOFF_EVIDENCE_SCHEMA")
    event = start.date()
    _need(evidence["sales_channel"] == CHANNEL and event.weekday() == 5 and
          evidence["rule_id"] == f"JRA_{event.year}_SATURDAY_ALL_RACES_START_MINUS_60_SECONDS", "SALES_CHANNEL_RULE")
    document, url, _ = _document(evidence["raw"], evidence["metadata"], now)
    _need(url == RULE_URL, "OFFICIAL_RULE_SOURCE")
    text = re.sub(r"\s+", "", document.text())
    _need(f"即PAT会員の発売時間({event.year}年)" in text and "土曜日全レース" in text and
          "発売締切時刻" in text and "各レース発走時刻1分前" in text, "OFFICIAL_RULE_TEXT")
    return start-timedelta(seconds=60)


def _history(cell, horse_id, source_url, capture, rights):
    def text(classes):
        rows = list(cell.nodes(classes=classes))
        return rows[0].text() if len(rows) == 1 else ""
    stamp = re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text(("date",)))
    venue = text(("rc",))
    finish = re.fullmatch(r"\s*(\d+)\s*着\s*", text(("place",)))
    size = re.search(r"(\d+)\s*頭", text(("num",)))
    info = list(cell.nodes(classes=("info_line2",)))
    distance = re.search(r"(?<![\d:])([\d,]{3,6})\s*(芝|ダート|ダ)(?![ァ-ヶ])", info[0].text()) if len(info) == 1 else None
    links = []
    for link in cell.nodes("a"):
        url = urljoin(source_url, link.attrs.get("href", "")); parsed = urlsplit(url)
        if parsed.scheme == "https" and parsed.hostname in ("www.jra.go.jp", "jra.go.jp") and parsed.path == "/JRADB/accessS.html":
            links.append(url)
    if not (stamp and venue and finish and size and distance and len(set(links)) == 1):
        return None
    try:
        event = date(*map(int, stamp.groups()))
    except ValueError:
        return None
    n, place, metres = int(size[1]), int(finish[1]), int(distance[1].replace(",", ""))
    if not (2 <= n <= 40 and 1 <= place <= n and 100 <= metres <= 10000):
        return None
    return dict(horse_id=horse_id, race_id=links[0], event_date=event.isoformat(), venue=venue,
                surface="turf" if distance[2] == "芝" else "dirt", distance_m=metres,
                field_size=n, finish_position=place, status="FINISHED", source_ref=source_url,
                source_rights_ref=rights, published_at=None, captured_at=capture.isoformat())


def build_sparse_payload(raw, metadata, *, now, source_rights_ref, cutoff_evidence=None):
    """Return READY native input or explicit HOLD; never fetch or infer a cutoff.

    ``cutoff_evidence`` contains raw official rule bytes, actual metadata,
    ``sales_channel`` and ``rule_id``. It admits no caller-chosen offset.
    ``now`` is the actual conversion clock, at or after source completion.
    Returned JSON is private source input, not an independent save receipt.
    """
    now = _clock(now)
    _need(type(source_rights_ref) is str and 0 < len(source_rights_ref) <= 256, "SOURCE_PURPOSE_REQUIRED")
    document, source_url, capture = _document(raw, metadata, now)
    race, start = _race(document, source_url)
    if cutoff_evidence is None:
        return dict(state="HOLD", reasons=["OFFICIAL_CUTOFF_EVIDENCE_REQUIRED"], summary=dict(participant_count=0))
    cutoff = _cutoff(cutoff_evidence, race, start, now)
    if not now < cutoff:
        return dict(state="HOLD", reasons=["SALES_CUTOFF_PASSED"], summary=dict(participant_count=0))
    race.update(sales_cutoff_at=cutoff.isoformat(), as_of=now.isoformat())
    table = _one(document, tag="table", classes=("basic", "narrow-xy", "mt20"))
    rows = [n for n in table.nodes("tr") if any(isinstance(c, _Node) and c.tag == "td" and "horse" in c.attrs.get("class", "").split() for c in n.children)]
    _need(3 <= len(rows) <= 18, "CONFIRMED_FIELD_REQUIRED")
    # Only current entrant cells establish current withdrawal. Historical
    # result cells and page-wide notices cannot cancel the current horse.
    withdrawn = 0
    for row in rows:
        current = (_one(row, tag="td", classes=("num",)), _one(row, tag="td", classes=("horse",)))
        withdrawn += int(any(set(part.attrs.get("class", "").split()) &
            {"cancel", "cancelled", "withdrawn", "scratch", "excluded"}
            for cell in current for part in (cell, *cell.nodes())))
    if withdrawn:
        return dict(state="HOLD", reasons=["CURRENT_ENTRANT_WITHDRAWN"],
                    summary=dict(participant_count=len(rows), current_withdrawal_count=withdrawn))
    scope = native.SYNTHETIC if metadata.get("scope") == native.SYNTHETIC else native.RESEARCH
    allowed = set(native.COMMON_REQUIRED+native.SPORT_REQUIRED["horse"]+native.SPORT_OPTIONAL["horse"])
    participants, seen_ids, seen_numbers, lineage = [], set(), set(), {}
    complete = excluded = 0
    for row in rows:
        number_cell = _one(row, tag="td", classes=("num",))
        horse = _one(row, tag="td", classes=("horse",))
        number_text = "".join(c for c in number_cell.children if type(c) is str).strip()
        _need(re.fullmatch(r"\d{1,2}", number_text) is not None, "HORSE_NUMBER_REQUIRED")
        number = int(number_text)
        name_line = _one(horse, classes=("name_line",))
        links = list(name_line.nodes("a"))
        _need(len(links) == 1, "STABLE_HORSE_ID_REQUIRED")
        profile = urlsplit(urljoin(source_url, links[0].attrs.get("href", "")))
        query = parse_qs(profile.query)
        identity = re.fullmatch(r"pw01dud00(\d{10})/[A-Fa-f0-9]{2}", query.get("CNAME", [""])[0])
        _need(profile.scheme == "https" and profile.hostname in ("www.jra.go.jp", "jra.go.jp") and
              profile.path == "/JRADB/accessU.html" and set(query) == {"CNAME"} and len(query["CNAME"]) == 1 and
              identity is not None, "STABLE_HORSE_ID_REQUIRED")
        horse_id = "jra:"+identity[1]
        _need(1 <= number <= 18 and number not in seen_numbers and horse_id not in seen_ids, "DUPLICATE_OR_INVALID_ENTRANT")
        seen_ids.add(horse_id); seen_numbers.add(number)
        past = [c for c in row.children if isinstance(c, _Node) and c.tag == "td" and
                "past" in c.attrs.get("class", "").split() and any(f"p{i}" in c.attrs.get("class", "").split() for i in range(1, 5))]
        _need(len(past) <= 4, "HISTORY_CELL_COUNT")
        history = []
        for cell in past:
            observed = _history(cell, horse_id, source_url, capture, source_rights_ref)
            if observed is None:
                excluded += 1
            else:
                _need(date.fromisoformat(observed["event_date"]) < now.astimezone(JST).date(), "HISTORY_NOT_PRIOR")
                history.append(observed); complete += 1
        report = derive(history, dict(horse_id=horse_id, venue=race["venue"], surface=race["surface"],
                                     distance_m=race["distance_m"], jockey_id=None), as_of=now.isoformat(), scope=scope)
        features = {}
        for name, item in report["features"].items():
            features[name] = dict(item, source_ref=source_url, source_rights_ref=source_rights_ref,
                                  source_sha256=metadata["source_sha256"], published_at=None,
                                  captured_at=capture.isoformat())
        recent = sorted(history, key=lambda h: (h["event_date"], h["race_id"]), reverse=True)[:3]
        if recent:
            # An observed all-surface summary is distinct from target-surface
            # ability/fit; those original missing fields remain untouched.
            features["recent_3race_form"] = dict(value=sum(_performance(h) for h in recent)/len(recent),
                published_at=None, captured_at=capture.isoformat(), source_ref=source_url,
                source_rights_ref=source_rights_ref, source_sha256=metadata["source_sha256"],
                sample_n=len(recent), transform_id=RECENT_TRANSFORM)
            lineage[str(number)] = dict(recent_3race_form=dict(transform_id=RECENT_TRANSFORM,
                target_surface_fit_evaluated=False, sample_n=len(recent),
                historical_race_ids=[h["race_id"] for h in recent], source_ref=source_url,
                source_rights_ref=source_rights_ref, source_sha256=metadata["source_sha256"],
                captured_at=capture.isoformat()))
        if not features:
            return dict(state="HOLD", reasons=["PARTICIPANT_WITHOUT_SUPPORTED_HISTORY"],
                        summary=dict(participant_count=len(rows), complete_history_rows=complete, excluded_history_rows=excluded))
        participants.append(dict(number=number, identity=horse_id, draw=number, style="unknown", group_id=None,
            features=features, missing={k: "NOT_AVAILABLE" for k in sorted(allowed-features.keys())}))
    snapshot = dict(schema=native.SCHEMA_SPARSE, scope=scope, race=race, participants=participants, environment={},
                    environment_missing={k: "NOT_AVAILABLE" for k in native.ENV_COMMON+native.ENV_SPORT["horse"]})
    # Structural validation does not authorize the actual source or its purpose.
    if scope == native.SYNTHETIC:
        native.validate(snapshot)
    payload = dict(snapshot=snapshot, stage="P0", feature_lineage=lineage, source_evidence=[_source(metadata, source_rights_ref),
        _source(cutoff_evidence["metadata"], source_rights_ref)], cutoff_evidence=dict(
            sales_channel=CHANNEL, rule_id=cutoff_evidence["rule_id"], official_start_at=start.isoformat(),
            rule_source_sha256=cutoff_evidence["metadata"]["source_sha256"], card_source_sha256=metadata["source_sha256"]))
    return dict(state="READY", native_payload=payload, summary=dict(participant_count=len(participants),
        complete_history_rows=complete, excluded_history_rows=excluded, source_captured_at=capture.isoformat(),
        converted_at=now.isoformat(), native_input_sha256=native.digest(payload), provider_permission_confirmed=False,
        independent_pre_cutoff_receipt_verified=False))
