"""Pure supplemental official BOAT context parsing; no transport or inference.

The supported beforeinfo layout has four rows per racer, a separate start
exhibition grid, and optional weather1 blocks. Pit reports have one five-cell
row per racer and a separately attributed reporter. These structures were
checked against private official captures; captured text is not bundled here.
Capture availability, publication freshness, and forecast readiness are
separate facts. In particular, weights and weather can precede exhibition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit


SCHEMA = "RACE_AI_BOAT_OBSERVATION_CONTEXT_V1"
JST = timezone(timedelta(hours=9))
MAX_BYTES = 1_000_000
HOST = "www.boatrace.jp"
MISSING = {"", "-", "--", "―", "—", "－", "欠場", "欠艇"}
_STRUCTURAL = {"table", "thead", "tbody", "tr", "td", "th"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Unsupported(Exception):
    """An unrecognized source layout, rather than a missing numeric value."""


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def text(self):
        if self.tag in {"script", "style"}:
            return ""
        return "".join(child.text() if isinstance(child, _Node) else child for child in self.children)

    def has(self, css):
        return css in self.attrs.get("class", "").split()

    def find(self, tag=None, css=None):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (css is None or child.has(css)):
                    yield child
                yield from child.find(tag, css)


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]
        self.invalid = False

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag == "br":
            self.stack[-1].children.append(" ")
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                if any(node.tag in _STRUCTURAL for node in self.stack[index + 1:]):
                    self.invalid = True
                del self.stack[index:]
                return
        if tag in _STRUCTURAL:
            self.invalid = True

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _one(nodes, *, layout=False):
    values = list(nodes)
    if len(values) != 1:
        if layout:
            raise _Unsupported()
        raise ValueError("BOAT_CONTEXT_AMBIGUOUS_OR_MISSING_IDENTITY")
    return values[0]


def _cells(row):
    return [node for node in row.children if isinstance(node, _Node) and node.tag in {"td", "th"}]


def _moment(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result
    except (TypeError, AttributeError, ValueError, OverflowError):
        raise ValueError("BOAT_CONTEXT_TIMESTAMP_REQUIRES_TIMEZONE") from None


def _identity(value, kind):
    try:
        u = urlsplit(value)
        q = parse_qs(u.query, keep_blank_values=True)
        if (u.scheme != "https" or u.netloc != HOST or u.path != "/owpc/pc/race/" + kind or u.fragment
                or set(q) != {"hd", "jcd", "rno"} or any(len(items) != 1 for items in q.values())
                or not re.fullmatch(r"20[0-9]{6}", q["hd"][0])
                or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", q["jcd"][0])
                or not re.fullmatch(r"[1-9]|1[0-2]", q["rno"][0])):
            raise ValueError()
        datetime.strptime(q["hd"][0], "%Y%m%d")
        return q["hd"][0], q["jcd"][0], int(q["rno"][0])
    except (TypeError, AttributeError, ValueError, KeyError):
        raise ValueError("BOAT_CONTEXT_SOURCE_IDENTITY_INVALID") from None


def _canonical_name(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _roster(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) != 6:
        raise ValueError("BOAT_CONTEXT_SIX_PERSON_ROSTER_REQUIRED")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("BOAT_CONTEXT_ROSTER_INVALID")
        lane, registration = row.get("lane"), row.get("registration_number")
        if (type(lane) is not int or lane not in range(1, 7) or lane in result
                or not isinstance(registration, str) or not re.fullmatch(r"[0-9]{4}", registration)
                or (row.get("name") is not None and not isinstance(row["name"], str))):
            raise ValueError("BOAT_CONTEXT_ROSTER_INVALID")
        result[lane] = row
    if len({row["registration_number"] for row in rows}) != 6:
        raise ValueError("BOAT_CONTEXT_DUPLICATE_REGISTRATION")
    return result


def _context(raw, *, kind, source_url, captured_at, expected_race_id, roster):
    expected = _identity(source_url, kind)
    day, venue, race_no = expected
    if expected_race_id != f"{day}-{venue}-{race_no:02d}":
        raise ValueError("BOAT_CONTEXT_EXPECTED_RACE_MISMATCH")
    bound = None if kind == "racelist" else _roster(roster)
    captured = _moment(captured_at)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("BOAT_CONTEXT_BOUNDED_ORIGINAL_BYTES_REQUIRED")
    try:
        html = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("BOAT_CONTEXT_UNSUPPORTED_ENCODING") from None
    tree = _Tree()
    tree.feed(html)
    tree.close()
    if tree.invalid or any(node.tag in _STRUCTURAL for node in tree.stack):
        raise ValueError("BOAT_CONTEXT_MALFORMED_TABLE")
    frame = _one(tree.root.find(css="contentsFrame1_inner"))
    schedules = [table for table in frame.find("table") if "締切予定時刻" in table.text()]
    schedule = _one(schedules)
    headers = list(_one(schedule.find("thead")).find("th"))[1:]
    if len(headers) != 12:
        raise ValueError("BOAT_CONTEXT_INCOMPLETE_SCHEDULE")
    selected = []
    for number, cell in enumerate(headers, 1):
        link = _one(cell.find("a"))
        if (_identity(urljoin(source_url, link.attrs.get("href", "")), kind) != (day, venue, number)
                or link.text().strip() != f"{number}R"):
            raise ValueError("BOAT_CONTEXT_BODY_DAY_OR_VENUE_MISMATCH")
        if not cell.has("is-thColor2") and not cell.has("is-thColor3"):
            selected.append(number)
    if selected != [race_no]:
        raise ValueError("BOAT_CONTEXT_SELECTED_RACE_MISMATCH")
    times = list(_one(schedule.find("tbody")).find("td"))
    if (len(times) != 13 or times[0].text().strip() != "締切予定時刻"
            or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", times[race_no].text().strip())):
        raise ValueError("BOAT_CONTEXT_CLOSING_SCHEDULE_INVALID")
    tabs = _one(frame.find(css="tab3"))
    links = list(tabs.find("a"))
    if not links:
        raise ValueError("BOAT_CONTEXT_RACE_TABS_MISSING")
    for link in links:
        full_url = urljoin(source_url, link.attrs.get("href", ""))
        u = urlsplit(full_url)
        if u.path == "/owpc/pc/race/pointrank":
            if u.scheme != "https" or u.netloc != HOST or parse_qs(u.query, keep_blank_values=True) != {"hd": [day], "jcd": [venue]} or u.fragment:
                raise ValueError("BOAT_CONTEXT_RACE_TAB_MISMATCH")
        elif (u.path not in {"/owpc/pc/race/" + name for name in
                            ("racelist", "beforeinfo", "pitreport", "odds3t", "pcexpect", "myexpect", "raceresult", "pointchart")}
              or _identity(full_url, u.path.rsplit("/", 1)[-1]) != expected):
            raise ValueError("BOAT_CONTEXT_RACE_TAB_MISMATCH")
    result = dict(schema=SCHEMA, kind=kind, race_id=expected_race_id,
                  event_date_jst=datetime.strptime(day, "%Y%m%d").date().isoformat(), venue_code=venue,
                  source_cutoff_at=f"{datetime.strptime(day, '%Y%m%d').date().isoformat()}T{times[race_no].text().strip()}:00+09:00",
                  race_no=race_no, status="UNSUPPORTED_STRUCTURE", body_identity_verified=True,
                  roster_binding_status="NOT_PUBLISHED", forecast_ready=False,
                  source=dict(source_url=source_url, sha256=sha256(raw).hexdigest(), captured_at=captured.isoformat(),
                              published_at=None, published_time_raw=None, freshness_status="UNKNOWN"),
                  participants=[], visual_observations={key: "UNAVAILABLE_FROM_SOURCE"
                                                       for key in ("turn", "exit", "runup", "extension")})
    return frame, bound, result


def _number(text, *, low=0, high=100, suffix=None):
    token = unicodedata.normalize("NFKC", text).strip()
    if token in MISSING:
        return None
    if suffix:
        suffix = unicodedata.normalize("NFKC", suffix)
        if not token.endswith(suffix):
            raise ValueError("BOAT_CONTEXT_NUMERIC_UNIT_INVALID")
        token = token[:-len(suffix)].strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", token):
        raise ValueError("BOAT_CONTEXT_NUMERIC_VALUE_INVALID")
    value = float(token)
    if not low <= value <= high:
        raise ValueError("BOAT_CONTEXT_NUMERIC_VALUE_OUT_OF_RANGE")
    return value


def _table(frame, *labels):
    return _one((table for table in frame.find("table")
                 if (heading := next(table.find("thead"), None)) is not None
                 and all(label in re.sub(r"\s+", "", heading.text()) for label in labels)), layout=True)


def _participant(cells, roster):
    lane = unicodedata.normalize("NFKC", cells[0].text()).strip()
    if not re.fullmatch(r"[1-6]", lane) or not cells[0].has("is-boatColor" + lane):
        raise ValueError("BOAT_CONTEXT_LANE_IDENTITY_INVALID")
    profiles = list(cells[1].find("a")) + list(cells[2].find("a"))
    if len(profiles) != 2:
        raise ValueError("BOAT_CONTEXT_PROFILE_REGISTRATION_MISSING")
    registrations = []
    for profile in profiles:
        u = urlsplit(urljoin("https://" + HOST, profile.attrs.get("href", "")))
        q = parse_qs(u.query, keep_blank_values=True)
        if (u.scheme != "https" or u.netloc != HOST or u.path != "/owpc/pc/data/racersearch/profile" or u.fragment
                or set(q) != {"toban"} or len(q["toban"]) != 1 or not re.fullmatch(r"[0-9]{4}", q["toban"][0])):
            raise ValueError("BOAT_CONTEXT_PROFILE_REGISTRATION_INVALID")
        registrations.append(q["toban"][0])
    name = profiles[1].text().strip()
    if len(set(registrations)) != 1 or not name:
        raise ValueError("BOAT_CONTEXT_ROSTER_BINDING_MISMATCH")
    if roster is not None:
        bound = roster[int(lane)]
        if (registrations[0] != bound["registration_number"]
                or (bound.get("name") and _canonical_name(name) != _canonical_name(bound["name"]))):
            raise ValueError("BOAT_CONTEXT_ROSTER_BINDING_MISMATCH")
    return dict(lane=int(lane), registration_number=registrations[0], name=name)


def _validate_participants(participants):
    if (len(participants) != 6 or {row["lane"] for row in participants} != set(range(1, 7))
            or len({row["registration_number"] for row in participants}) != 6):
        raise ValueError("BOAT_CONTEXT_PARTICIPANTS_INCOMPLETE_OR_DUPLICATE")
    return sorted(participants, key=lambda row: row["lane"])


def parse_program_roster(raw: bytes, *, source_url, captured_at, expected_race_id):
    """Read six official program identities and the printed cutoff only.

    This metadata adapter supports the observed SG navigation, including the
    venue/day pointrank tab. It preserves original-byte provenance and validates
    the complete dated schedule. It neither parses forecast inputs nor extends
    the supported event scope of any separately pinned forecasting adapter.
    """
    frame, _, result = _context(raw, kind="racelist", source_url=source_url,
                               captured_at=captured_at, expected_race_id=expected_race_id, roster=None)
    try:
        wrapper = _one(frame.find(css="is-tableFixed__3rdadd"), layout=True)
        table = _table(wrapper, "枠", "ボートレーサー", "登録番号/級別", "全国", "当地", "モーター", "ボート")
        participants = []
        for body in table.find("tbody"):
            rows = list(body.find("tr"))
            if len(rows) != 4 or len(cells := _cells(rows[0])) < 8:
                raise _Unsupported()
            if any(cell.attrs.get("rowspan") != "4" for cell in cells[:3]):
                raise _Unsupported()
            row = _participant(cells, None)
            printed = re.match(r"\s*([0-9]{4})\s*/", unicodedata.normalize("NFKC", cells[2].text()))
            if not printed or printed.group(1) != row["registration_number"]:
                raise ValueError("BOAT_CONTEXT_PRINTED_REGISTRATION_MISMATCH")
            participants.append(row)
        participants = _validate_participants(participants)
    except _Unsupported:
        raise ValueError("BOAT_CONTEXT_PROGRAM_ROSTER_UNSUPPORTED_STRUCTURE") from None
    return {key: result[key] for key in ("race_id", "source_cutoff_at", "source")} | {"participants": participants}


def _starts(frame):
    table = _table(frame, "スタート展示", "コース", "ST")
    rows = list(_one(table.find("tbody"), layout=True).find("tr"))
    if len(rows) != 6:
        raise _Unsupported()
    if all(len(_cells(row)) == 1 and _cells(row)[0].attrs.get("colspan") == "3"
           and not row.text().strip() and not list(row.find("img")) for row in rows):
        return {}
    result = {}
    positions = []
    for row in rows:
        image = _one((node for node in row.find("img") if re.fullmatch(
            r"/static_extra/pc/images/img_boat2_[1-6]\.png", node.attrs.get("src", ""))), layout=True)
        lane = int(image.attrs["src"][-5])
        position = _one(row.find(css="table1_boatImage1Number"), layout=True).text().strip()
        token = _one(row.find(css="table1_boatImage1Time"), layout=True).text().strip()
        if not re.fullmatch(r"[1-6]", position) or lane in result:
            raise ValueError("BOAT_CONTEXT_EXHIBITION_IDENTITY_INVALID")
        positions.append(int(position))
        if token in MISSING:
            value, status = None, "NOT_PUBLISHED"
        elif re.fullmatch(r"0?\.[0-9]{2}", token):
            value, status = float(token), "OK"
        elif re.fullmatch(r"[FL](?:0?\.[0-9]{2})?", token):
            value, status = None, token[0]
        else:
            raise ValueError("BOAT_CONTEXT_EXHIBITION_ST_INVALID")
        # Official display position is retained as printed. It is not evidence
        # for actual race entry or an independently measured visual course.
        result[lane] = dict(exhibition_st=value, exhibition_st_status=status,
                            exhibition_st_raw=token or None, exhibition_source_position_number=int(position),
                            exhibition_course=None)
    if set(result) != set(range(1, 7)) or set(positions) != set(range(1, 7)):
        raise ValueError("BOAT_CONTEXT_EXHIBITION_IDENTITIES_INCOMPLETE")
    return result


def _weather(frame):
    blocks = list(frame.find(css="weather1"))
    if not blocks:
        return None
    block = _one(blocks, layout=True)
    result = dict(air_temperature_c=None, water_temperature_c=None, wind_speed_mps=None,
                  wave_height_cm=None, wind_direction_source_code=None, weather_label=None,
                  reported_race_no=None, source_reported_local_time=None, reported_at=None,
                  freshness_status="UNKNOWN_SOURCE_TIME_HAS_NO_DATE")
    title = _one(block.find(css="weather1_title"), layout=True).text().strip()
    match = re.search(r"\b((?:[01][0-9]|2[0-3]):[0-5][0-9])現在", title)
    result["source_reported_local_time"] = match.group(1) if match else None
    race = re.search(r"(?:^|\s)([1-9]|1[0-2])R時点", title)
    result["reported_race_no"] = int(race.group(1)) if race else None
    fields = {"気温": ("air_temperature_c", "℃", -40, 60),
              "水温": ("water_temperature_c", "℃", -10, 60),
              "風速": ("wind_speed_mps", "m", 0, 100), "波高": ("wave_height_cm", "cm", 0, 1000)}
    seen = set()
    for unit in block.find(css="weather1_bodyUnit"):
        label = next(unit.find(css="weather1_bodyUnitLabelTitle"), None)
        label = label.text().strip() if label is not None else ""
        if label in fields:
            key, suffix, low, high = fields[label]
            if key in seen:
                raise _Unsupported()
            seen.add(key)
            value = _one(unit.find(css="weather1_bodyUnitLabelData"), layout=True)
            result[key] = _number(value.text(), low=low, high=high, suffix=suffix)
        if unit.has("is-weather"):
            result["weather_label"] = label or None
        if unit.has("is-windDirection"):
            classes = " ".join(node.attrs.get("class", "") for node in unit.find())
            code = re.findall(r"\bis-wind([0-9]{1,2})\b", classes)
            if len(code) > 1:
                raise _Unsupported()
            result["wind_direction_source_code"] = int(code[0]) if code else None
    return result


def parse_beforeinfo(raw: bytes, *, source_url, captured_at, expected_race_id, roster):
    """Parse supplemental weights/equipment/weather, including empty exhibition.

    ``roster`` requires six {lane, registration_number, name?} dictionaries.
    Publication times without a printed date remain unknown. This record never
    asserts that a forecast may run; call eligibility_for_cutoff separately.
    """
    frame, roster, result = _context(raw, kind="beforeinfo", source_url=source_url,
                                    captured_at=captured_at, expected_race_id=expected_race_id, roster=roster)
    try:
        table = _table(frame, "ボートレーサー", "体重", "展示", "チルト", "プロペラ", "部品交換", "調整重量")
        starts = _starts(frame)
        participants = []
        for body in table.find("tbody"):
            rows = list(body.find("tr"))
            cells = [_cells(row) for row in rows]
            if len(cells) != 4 or [len(row) for row in cells] != [10, 2, 3, 2]:
                raise _Unsupported()
            if [cells[1][0].text().strip(), cells[2][1].text().strip(), cells[3][0].text().strip()] != ["進入", "ST", "着順"]:
                raise _Unsupported()
            first = cells[0]
            row = _participant(first, roster)
            marker = first[6].text().strip()
            if marker not in MISSING | {"新"}:
                raise ValueError("BOAT_CONTEXT_PROPELLER_MARKER_UNKNOWN")
            labels = _one(first[7].find(css="labelGroup1"), layout=True)
            parts = [label.text().strip() for label in labels.find("li") if label.text().strip()]
            row.update(bodyweight_kg=_number(first[3].text(), low=20, high=150, suffix="kg"),
                       adjustmentweight_kg=_number(cells[2][0].text(), high=30),
                       display_time=_number(first[4].text(), low=0.01), tilt=_number(first[5].text(), low=-10, high=10),
                       propeller_change_marker=marker if marker == "新" else None,
                       propeller_change_status="REPORTED_NEW" if marker == "新" else "NOT_PUBLISHED",
                       parts_replacement=parts or None)
            row.update(starts.get(row["lane"], dict(exhibition_st=None, exhibition_st_status="NOT_PUBLISHED",
                                                  exhibition_st_raw=None, exhibition_source_position_number=None,
                                                  exhibition_course=None)))
            participants.append(row)
        result.update(status="PARSED", roster_binding_status="VERIFIED",
                      participants=_validate_participants(participants), weather=_weather(frame))
    except _Unsupported:
        pass
    return result


def parse_pitreport(raw: bytes, *, source_url, captured_at, expected_race_id, roster):
    """Preserve official report text and attribution without sentiment scores."""
    frame, roster, result = _context(raw, kind="pitreport", source_url=source_url,
                                    captured_at=captured_at, expected_race_id=expected_race_id, roster=roster)
    notices = [node for node in frame.find("h3") if "ピットレポートの表示対象レースではありません" in node.text()]
    if len(notices) == 1:
        if any("ピットレポート" in head.text() for table in frame.find("table") for head in table.find("thead")):
            raise ValueError("BOAT_CONTEXT_NOT_OFFERED_CONFLICTS_WITH_REPORTS")
        result["status"] = "NOT_OFFERED"
        return result
    try:
        table = _table(frame, "枠", "ボートレーサー", "ピットレポート", "登録番号/級別")
        reporters = [node.text().strip() for node in frame.find("p") if node.text().strip().startswith("レポーター：")]
        if len(reporters) > 1:
            raise _Unsupported()
        reporter = re.sub(r"^レポーター：\s*", "", reporters[0]).strip() if reporters else None
        participants = []
        for body in table.find("tbody"):
            rows = list(body.find("tr"))
            if len(rows) != 1 or len(cells := _cells(rows[0])) != 5:
                raise _Unsupported()
            row = _participant(cells, roster)
            registration = re.match(r"\s*([0-9]{4})\s*/", cells[2].text())
            if not registration or registration.group(1) != row["registration_number"]:
                raise ValueError("BOAT_CONTEXT_PRINTED_REGISTRATION_MISMATCH")
            text = cells[3].text().strip() or None
            row.update(comment=text, comment_status="REPORTED" if text else "NOT_PUBLISHED",
                       comment_attribution=dict(racer_name=row["name"], reporter=reporter, kind="OFFICIAL_PIT_REPORT"))
            participants.append(row)
        result.update(status="PARSED", roster_binding_status="VERIFIED", reporter=reporter,
                      participants=_validate_participants(participants))
    except _Unsupported:
        pass
    return result


def eligibility_for_cutoff(record, *, cutoff_at):
    """Report capture availability before a cutoff without inventing freshness.

    A pre-cutoff context remains supplemental; eligibility neither guarantees
    current weather nor establishes exhibition/forecast readiness. Historical
    receipt cannot be backdated using source page labels or the request date.
    """
    cutoff = _moment(cutoff_at)
    captured = _moment(record["source"]["captured_at"])
    # The caller may impose an earlier operational cutoff, but a later supplied
    # timestamp cannot extend the official deadline printed in this source.
    before = captured < min(cutoff, _moment(record["source_cutoff_at"]))
    same_day = (cutoff.astimezone(JST).date().isoformat() == record["event_date_jst"]
                and captured.astimezone(JST).date().isoformat() == record["event_date_jst"])
    parsed = record.get("status") == "PARSED" and record.get("roster_binding_status") == "VERIFIED"
    reason = ("CAPTURED_AT_OR_AFTER_CUTOFF" if not before else "EVENT_DAY_MISMATCH" if not same_day
              else "CONTEXT_NOT_PARSED_AND_BOUND" if not parsed else "CAPTURED_BEFORE_CUTOFF")
    return dict(captured_before_cutoff=before, pre_cutoff_eligible=before and same_day and parsed,
                publication_freshness_status=record["source"]["freshness_status"], reason=reason)
