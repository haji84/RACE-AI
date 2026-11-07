"""Owned, offline official program adapter with strict source identity binding.

Headers locate the source fields; rendered line boundaries retain empty
statistics in their original slots. Missing values never establish withdrawal.
Receipt time is preserved, including historical replay, and is never promoted
to source publication time or proof of a pre-cutoff forecast.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit

from .boat_observation_context import HOST, JST, MAX_BYTES, _Node, _Tree, _cells


SCHEMA = "RACE_AI_BOAT_OFFICIAL_PROGRAM_V1"
PATH = "/owpc/pc/race/racelist"
_STRUCTURAL = {"table", "thead", "tbody", "tr", "td", "th"}
_MISSING = {"", "-", "--", "―", "—", "－", "欠場", "欠艇"}
_BLOCKS = {"div", "p", "li"}
_RACE_TABS = {"racelist", "odds3t", "beforeinfo", "pcexpect", "myexpect",
              "raceresult", "pitreport", "pointchart"}


class BoatProgramError(ValueError):
    """Unverified identity, ambiguous source structure or invalid source value."""


def _one(nodes, description):
    values = list(nodes)
    if len(values) != 1:
        raise BoatProgramError(f"BOAT_PROGRAM_EXPECTED_ONE_{description}")
    return values[0]


def _normalized(value):
    return unicodedata.normalize("NFKC", value)


def _compact(value):
    return re.sub(r"\s+", "", _normalized(value))


def _url(value, *, path, keys):
    try:
        u = urlsplit(value)
        q = parse_qs(u.query, keep_blank_values=True)
        if (u.scheme != "https" or u.netloc != HOST or u.path != path or u.fragment
                or set(q) != set(keys) or any(len(values) != 1 for values in q.values())):
            raise ValueError()
        return {key: q[key][0] for key in keys}
    except (TypeError, AttributeError, ValueError, KeyError):
        raise BoatProgramError("BOAT_PROGRAM_SOURCE_URL_INVALID") from None


def _identity(value, *, path=PATH):
    q = _url(value, path=path, keys=("hd", "jcd", "rno"))
    try:
        if (not re.fullmatch(r"[0-9]{8}", q["hd"])
                or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", q["jcd"])
                or not re.fullmatch(r"[1-9]|1[0-2]", q["rno"])):
            raise ValueError()
        datetime.strptime(q["hd"], "%Y%m%d")
        return q["hd"], q["jcd"], int(q["rno"])
    except (TypeError, ValueError):
        raise BoatProgramError("BOAT_PROGRAM_SOURCE_IDENTITY_INVALID") from None


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise BoatProgramError("BOAT_PROGRAM_CAPTURE_TIMESTAMP_REQUIRES_TIMEZONE") from None


def _schedule(frame, expected, source_url):
    schedule = _one((table for table in frame.find("table")
                     if "締切予定時刻" in _compact(table.text())), "CLOSING_SCHEDULE")
    head = _one(schedule.find("thead"), "SCHEDULE_HEADER")
    headers = list(head.find("th"))[1:]
    if len(headers) != 12:
        raise BoatProgramError("BOAT_PROGRAM_INCOMPLETE_SCHEDULE")
    selected = []
    for number, cell in enumerate(headers, 1):
        link = _one(cell.find("a"), "SCHEDULE_LINK")
        identity = _identity(urljoin(source_url, link.attrs.get("href", "")))
        if identity != (expected[0], expected[1], number) or _compact(link.text()) != f"{number}R":
            raise BoatProgramError("BOAT_PROGRAM_BODY_IDENTITY_MISMATCH")
        if not cell.has("is-thColor2") and not cell.has("is-thColor3"):
            selected.append(number)
    if selected != [expected[2]]:
        raise BoatProgramError("BOAT_PROGRAM_SELECTED_RACE_MISMATCH")
    times = list(_one(schedule.find("tbody"), "SCHEDULE_TIMES").find("td"))
    if len(times) != 13 or _compact(times[0].text()) != "締切予定時刻":
        raise BoatProgramError("BOAT_PROGRAM_CLOSING_SCHEDULE_INVALID")
    closing = _normalized(times[expected[2]].text()).strip()
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", closing):
        raise BoatProgramError("BOAT_PROGRAM_CLOSING_TIME_INVALID")
    return closing


def _navigation(frame, expected, source_url):
    tabs = _one(frame.find(css="tab3"), "RACE_TABS")
    links = list(tabs.find("a"))
    if not links:
        raise BoatProgramError("BOAT_PROGRAM_RACE_TAB_IDENTITY_MISSING")
    for link in links:
        value = urljoin(source_url, link.attrs.get("href", ""))
        path = urlsplit(value).path
        if path == "/owpc/pc/race/pointrank":
            q = _url(value, path=path, keys=("hd", "jcd"))
            valid = (q["hd"], q["jcd"]) == expected[:2]
        else:
            valid = (path in {"/owpc/pc/race/" + name for name in _RACE_TABS}
                     and _identity(value, path=path) == expected)
        if not valid:
            raise BoatProgramError("BOAT_PROGRAM_RACE_TAB_IDENTITY_MISMATCH")


def _span(node, key):
    value = node.attrs.get(key, "1")
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]?", value) or int(value) > 30:
        raise BoatProgramError("BOAT_PROGRAM_TABLE_SPAN_INVALID")
    return int(value)


def _header_columns(table):
    head = _one(table.find("thead"), "PROGRAM_HEADER")
    rows = list(head.find("tr"))
    if not rows or len(rows) > 10:
        raise BoatProgramError("BOAT_PROGRAM_HEADER_LAYOUT_INVALID")
    grid = {}
    for r, row in enumerate(rows):
        column = 0
        for cell in _cells(row):
            while (r, column) in grid:
                column += 1
            height, width = _span(cell, "rowspan"), _span(cell, "colspan")
            if r + height > len(rows) or column + width > 60:
                raise BoatProgramError("BOAT_PROGRAM_HEADER_LAYOUT_INVALID")
            for target_r in range(r, r + height):
                for target_c in range(column, column + width):
                    if (target_r, target_c) in grid:
                        raise BoatProgramError("BOAT_PROGRAM_HEADER_SPAN_OVERLAP")
                    grid[target_r, target_c] = cell
            column += width
    width = max((column for _, column in grid), default=-1) + 1
    if any((r, c) not in grid for r in range(len(rows)) for c in range(width)):
        raise BoatProgramError("BOAT_PROGRAM_HEADER_GRID_INCOMPLETE")
    return [" ".join(dict.fromkeys(_compact(grid[r, c].text()) for r in range(len(rows))))
            for c in range(width)]


def _columns(table):
    labels = _header_columns(table)
    tests = {
        "lane": lambda value: value == "枠",
        "photo": lambda value: "写真" in value,
        "identity": lambda value: "登録番号" in value and "氏名" in value,
        "st": lambda value: "平均ST" in value,
        "national": lambda value: "全国" in value,
        "local": lambda value: "当地" in value,
        "motor": lambda value: "モーター" in value,
        "boat": lambda value: "ボート" in value and "ボートレーサー" not in value,
    }
    columns = {}
    for field, test in tests.items():
        candidates = [number for number, label in enumerate(labels) if test(label)]
        if len(candidates) > 1:
            raise BoatProgramError("BOAT_PROGRAM_AMBIGUOUS_FIELD_HEADER")
        columns[field] = candidates[0] if candidates else None
    if any(columns[field] is None for field in ("lane", "photo", "identity")):
        raise BoatProgramError("BOAT_PROGRAM_IDENTITY_HEADERS_MISSING")
    if len({value for value in columns.values() if value is not None}) != len([value for value in columns.values() if value is not None]):
        raise BoatProgramError("BOAT_PROGRAM_FIELD_HEADER_COLLISION")
    return columns, len(labels)


def _slots(node):
    """Preserve structural empty lines, ignoring formatting-only whitespace."""
    children = [child for child in node.children
                if isinstance(child, _Node) or child.strip()]
    if children and all(isinstance(child, _Node) and child.tag in _BLOCKS for child in children):
        return [value for child in children for value in _slots(child)]
    def render(child):
        if isinstance(child, str):
            return re.sub(r"\s+", " ", child)
        if child.tag in {"script", "style"}:
            raise BoatProgramError("BOAT_PROGRAM_UNEXPECTED_STAT_MARKUP")
        if child.tag == "br":
            return "\x1e"
        return "".join(render(item) for item in child.children)
    rendered = "".join(render(child) for child in node.children)
    if "\x1e" in rendered:
        return [_normalized(value).strip() for value in rendered.split("\x1e")]
    values = _normalized(rendered).split()
    return values or [""]


def _number(token, *, maximum):
    token = _normalized(token).strip()
    if token in _MISSING:
        return None
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?|\.[0-9]+", token):
        raise BoatProgramError("BOAT_PROGRAM_STAT_VALUE_INVALID")
    value = float(token)
    if not 0 <= value <= maximum:
        raise BoatProgramError("BOAT_PROGRAM_STAT_VALUE_OUT_OF_RANGE")
    return value


def _metric(cell, field, missing):
    if cell is None:
        missing[field] = "FIELD_NOT_IN_SOURCE"
        return None
    slots = _slots(cell)
    if all(value in _MISSING for value in slots):
        missing[field] = "NOT_PUBLISHED"
        return None
    if len(slots) != 3:
        raise BoatProgramError("BOAT_PROGRAM_STAT_LAYOUT_INVALID")
    if field == "average_st":
        if not re.fullmatch(r"F[0-9]+", slots[0]) or not re.fullmatch(r"L[0-9]+", slots[1]):
            raise BoatProgramError("BOAT_PROGRAM_START_STAT_LAYOUT_INVALID")
        value = _number(slots[2], maximum=1)
    else:
        rates = [_number(token, maximum=100) for token in slots[1:]]
        if field.startswith(("motor_", "boat_")):
            token = slots[0]
            if token in _MISSING:
                value = None
            elif not re.fullmatch(r"[1-9][0-9]{0,2}", token):
                raise BoatProgramError("BOAT_PROGRAM_ALLOCATION_NUMBER_INVALID")
            else:
                value = int(token)
        else:
            value = _number(slots[0], maximum=10)
        if field.endswith("_top2_rate"):
            value = rates[0]
        elif field.endswith("_top3_rate"):
            value = rates[1]
    if value is None:
        missing[field] = "NOT_PUBLISHED"
    return value


def _racer(photo, identity, *, withdrawn, missing):
    profiles = list(photo.find("a")) + list(identity.find("a"))
    printed = re.match(r"\s*([0-9]{4})\s*/", _normalized(identity.text()))
    if not profiles and not printed and withdrawn:
        missing.update(racer_registration_id="EXPLICIT_WITHDRAWAL", name="EXPLICIT_WITHDRAWAL")
        return None, None
    if len(profiles) != 2 or not printed:
        raise BoatProgramError("BOAT_PROGRAM_RACER_IDENTITY_INCOMPLETE")
    registration = printed.group(1)
    for profile in profiles:
        q = _url(urljoin("https://" + HOST, profile.attrs.get("href", "")),
                 path="/owpc/pc/data/racersearch/profile", keys=("toban",))
        if q["toban"] != registration:
            raise BoatProgramError("BOAT_PROGRAM_PROFILE_REGISTRATION_CONFLICT")
    # Preserve the displayed Unicode spelling rather than NFKC-changing names.
    name = profiles[1].text().strip()
    if not name or len(name) > 128:
        raise BoatProgramError("BOAT_PROGRAM_RACER_NAME_MISSING")
    return registration, name


def _participants(table, columns, width, *, race_id, closed_at, source_url, captured_at):
    boats = []
    for body in table.find("tbody"):
        rows = list(body.find("tr"))
        if len(rows) not in (1, 4):
            raise BoatProgramError("BOAT_PROGRAM_ENTRY_ROW_GROUP_INVALID")
        cells = _cells(rows[0])
        expanded = []
        for cell in cells:
            expanded.extend([cell] * _span(cell, "colspan"))
        if len(expanded) != width:
            raise BoatProgramError("BOAT_PROGRAM_ENTRY_ROW_INCOMPLETE")
        current_cells = [expanded[index] for index in columns.values() if index is not None]
        if any(_span(cell, "rowspan") != len(rows) for cell in current_cells):
            raise BoatProgramError("BOAT_PROGRAM_ENTRY_ROW_BINDING_INVALID")
        lane_cell = expanded[columns["lane"]]
        lane = _normalized(lane_cell.text()).strip()
        if not re.fullmatch(r"[1-6]", lane) or not lane_cell.has("is-boatColor" + lane):
            raise BoatProgramError("BOAT_PROGRAM_LANE_IDENTITY_INVALID")
        # Restrict withdrawal evidence to this entry, never another race or an
        # absence of exhibition statistics.
        withdrawn = any(marker in cell.text() for cell in current_cells for marker in ("欠場", "欠艇"))
        missing = {}
        registration, name = _racer(expanded[columns["photo"]], expanded[columns["identity"]],
                                     withdrawn=withdrawn, missing=missing)
        metrics = {}
        for field, column in (("average_st", "st"), ("national_win_rate", "national"),
                              ("local_win_rate", "local"), ("motor_no", "motor"), ("boat_no", "boat")):
            index = columns[column]
            metrics[field] = _metric(None if index is None else expanded[index], field, missing)
        for column in ("national", "local", "motor", "boat"):
            index = columns[column]
            for place in (2, 3):
                field = f"{column}_top{place}_rate"
                metrics[field] = _metric(None if index is None else expanded[index], field, missing)
        boats.append(dict(race_id=race_id, lane=int(lane), racer_registration_id=registration,
                          name=name, **metrics, entry_status="withdrawn" if withdrawn else "listed",
                          closed_at=closed_at, verified_source=True, source_url=source_url,
                          captured_at=captured_at, missing_fields=missing))
    if not 1 <= len(boats) <= 6 or len({row["lane"] for row in boats}) != len(boats):
        raise BoatProgramError("BOAT_PROGRAM_ROSTER_SIZE_OR_LANES_INVALID")
    for field in ("racer_registration_id", "motor_no", "boat_no"):
        values = [row[field] for row in boats if row[field] is not None]
        if len(values) != len(set(values)):
            raise BoatProgramError("BOAT_PROGRAM_DUPLICATE_RACER_OR_ALLOCATION")
    return sorted(boats, key=lambda row: row["lane"])


def _race_status(frame):
    # Notices must belong to this dated, selected race frame and occur outside
    # entry/history tables. A historical result's absence is not race status.
    def notices(node):
        for child in node.children:
            if isinstance(child, _Node) and child.tag != "table":
                if child.tag in {"h3", "p"}:
                    yield _compact(child.text())
                yield from notices(child)
    states = set()
    for notice in notices(frame):
        if re.match(r"(?:この|本|当該)?レース(?:は|が)?[、,]?中止(?:となりました|です|になりました)", notice):
            states.add("CANCELLED")
        if re.match(r"(?:この|本|当該)?レース(?:は|が)?[、,]?不成立(?:となりました|です|になりました)", notice):
            states.add("NO_CONTEST")
        if re.match(r"(?:この|本|当該)?出走表.*(?:掲載されていません|未公開|ありません)", notice):
            states.add("NOT_PUBLISHED")
    if len(states) > 1:
        raise BoatProgramError("BOAT_PROGRAM_CONFLICTING_RACE_STATUS")
    return next(iter(states), "LISTED")


def parse_program(raw: bytes, *, day: date, venue: str, race_no: int,
                  source_url: str, captured_at: str) -> dict:
    """Parse original official bytes, preserving pinned-compatible program keys.

    Identity verification is separate from forecast eligibility. A historical
    body may be replayed with its actual later receipt, which is explicitly
    ineligible for pre-cutoff use. No source publication time is inferred.
    """
    if (type(day) is not date or not isinstance(venue, str)
            or not re.fullmatch(r"0[1-9]|1[0-9]|2[0-4]", venue)
            or type(race_no) is not int or not 1 <= race_no <= 12):
        raise BoatProgramError("BOAT_PROGRAM_REQUEST_IDENTITY_INVALID")
    expected = day.strftime("%Y%m%d"), venue, race_no
    if _identity(source_url) != expected:
        raise BoatProgramError("BOAT_PROGRAM_REQUEST_IDENTITY_MISMATCH")
    captured = _timestamp(captured_at)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise BoatProgramError("BOAT_PROGRAM_BOUNDED_ORIGINAL_BYTES_REQUIRED")
    try:
        html = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise BoatProgramError("BOAT_PROGRAM_UNSUPPORTED_ENCODING") from None
    tree = _Tree()
    tree.feed(html)
    tree.close()
    if tree.invalid or any(node.tag in _STRUCTURAL for node in tree.stack):
        raise BoatProgramError("BOAT_PROGRAM_MALFORMED_TABLE")
    frame = _one(tree.root.find(css="contentsFrame1_inner"), "CONTENT_FRAME")
    closing = _schedule(frame, expected, source_url)
    _navigation(frame, expected, source_url)
    candidates = []
    for table in frame.find("table"):
        heads = list(table.find("thead"))
        if len(heads) == 1:
            heading = _compact(heads[0].text())
            if all(label in heading for label in ("枠", "ボートレーサー", "登録番号", "氏名")):
                candidates.append(table)
    race_id = f"{expected[0]}-{venue}-{race_no:02d}"
    closed_at = f"{day.isoformat()}T{closing}:00+09:00"
    race_status = _race_status(frame)
    if not candidates and race_status != "LISTED":
        boats = []
    else:
        table = _one(candidates, "PROGRAM_TABLE")
        if race_status == "NOT_PUBLISHED":
            raise BoatProgramError("BOAT_PROGRAM_NOT_PUBLISHED_CONFLICTS_WITH_ROSTER")
        columns, width = _columns(table)
        boats = _participants(table, columns, width, race_id=race_id, closed_at=closed_at,
                              source_url=source_url, captured_at=captured_at)
    active = [row["lane"] for row in boats if row["entry_status"] == "listed"]
    trifecta = len(active) >= 3 and race_status == "LISTED"
    same_day = captured.astimezone(JST).date() == day
    eligible = same_day and captured < datetime.fromisoformat(closed_at)
    return dict(schema=SCHEMA, date_jst=day.isoformat(), venue=venue, race_id=race_id,
                closed_at=closed_at, boats=boats, source_url=source_url,
                source_sha256=sha256(raw).hexdigest(), first_observed_at=captured_at,
                captured_at=captured_at, redistribution_authorized=False,
                status="OFFICIAL_BODY_IDENTITY_VERIFIED", body_identity_verified=True, race_status=race_status,
                active_lanes=active, active_entrant_count=len(active), trifecta_available=trifecta,
                trifecta_status=(race_status if race_status != "LISTED" else "AVAILABLE" if trifecta
                                 else "FEWER_THAN_THREE_ACTIVE_ENTRANTS"),
                pre_cutoff_eligible=eligible,
                eligibility_reason=("EVENT_DAY_MISMATCH" if not same_day else
                                    "CAPTURED_AT_OR_AFTER_CUTOFF" if not eligible else "CAPTURED_BEFORE_CUTOFF"),
                missing_fields={str(row["lane"]): row["missing_fields"] for row in boats if row["missing_fields"]},
                source=dict(source_url=source_url, sha256=sha256(raw).hexdigest(), captured_at=captured_at,
                            published_at=None, freshness_status="UNKNOWN"))
