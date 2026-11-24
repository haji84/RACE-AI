"""Inventory every dated KEIRIN race/source entry, independently of results or film coverage.

Read private SHA-pinned study cards, monthly/SQLite archives and dated KDreams result
indices. The resulting JSONL is a private work queue. A listed race or programme
does not establish that its film was played or its riders were observed.
"""

import argparse
import csv
import gzip
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import lru_cache
from itertools import groupby
from hashlib import file_digest, sha256
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from scripts.keirin_capture_public_two_sources import fetch_once
from scripts.keirin_rider_profile_identity import IdentityIndex, name_key, prefecture_key

DOMAIN = "https://keirin.kdreams.jp"
DETAIL = re.compile(r"/[a-z0-9-]+/racedetail/([0-9]{16})/")
NET_SHORT_PREFECTURES = {"北海": "北海道", "神奈": "神奈川", "和歌": "和歌山", "鹿児": "鹿児島"}
CANCEL = re.compile(r"(?:競走中止|開催中止|レース中止|中止)")


def compact_id(key):
    if not re.fullmatch(r"[0-9]{12}", key):
        raise ValueError("Invalid race identifier")
    day, venue, race = key[:8], key[8:10], key[10:]
    date.fromisoformat(day)
    if venue == "00" or not 1 <= int(race) <= 12:
        raise ValueError("Invalid race venue/number")
    return f"{day}-{venue}-{race}"


@lru_cache(maxsize=512)
def monthly_key(identifier, stated, race_no):
    if not re.fullmatch(r"[0-9]{16}", identifier):
        raise ValueError("Invalid monthly meeting identifier")
    venue, start, stage, race = identifier[:2], identifier[2:10], identifier[10:12], identifier[-2:]
    begin = date.fromisoformat(start)
    if not 1 <= int(stage) <= 7 or int(race_no) not in (int(race), int(identifier[-4:])):
        raise ValueError("Monthly meeting race number mismatch")
    actual = begin + timedelta(days=int(stage) + int(identifier[12:14]) - 1)
    if date.fromisoformat(stated) not in (begin, actual):
        raise ValueError("Monthly meeting date mismatch")
    return compact_id(f"{actual:%Y%m%d}{venue}{race}")


def daily_rows(html, day):
    soup = BeautifulSoup(html, "lxml")
    stamp = f"{day:%Y年%m月%d日} レース結果一覧"
    if not any(h.get_text(" ", strip=True) == stamp for h in soup.select("h2")):
        raise ValueError("Calendar header does not match requested day")
    tables = soup.select(".raceinfo_table")
    if len(tables) != 1:
        raise ValueError("Unrecognized daily results table")
    result = {}
    for anchor in tables[0].select("a[href]"):
        href = urlsplit(urljoin(DOMAIN, anchor["href"]))
        label = anchor.get_text(" ", strip=True)
        if "/racedetail/" not in href.path and not re.fullmatch(r"[0-9]+R", label):
            continue
        match = DETAIL.fullmatch(href.path)
        if not match or href.netloc != "keirin.kdreams.jp" or href.scheme != "https":
            raise ValueError("Unrecognized or external race link in results table")
        identifier = match.group(1)
        race = identifier[-2:]
        if not re.fullmatch(rf"{int(race)}R(?:\s*[(（]?{CANCEL.pattern}[)）]?)?", label):
            raise ValueError("Race link and displayed number disagree")
        key = monthly_key(identifier, day.isoformat(), race)
        if key[:8] != day.strftime("%Y%m%d"):
            raise ValueError("Race link and calendar date disagree")
        value = (DOMAIN + href.path, bool(CANCEL.search(label)))
        if key in result and result[key] != value:
            raise ValueError("Conflicting daily race links")
        result[key] = value
    if not result and not re.search(r"開催(?:は|が)?(?:ありま|ございま)せん|該当(?:する|の)(?:開催|レース).*ありません", tables[0].get_text()):
        raise ValueError("No verified races or explicit empty-day notice")
    return result


def calendar_links(html, day):
    return {key: url for key, (url, _) in daily_rows(html, day).items()}


def save_capture(dest, raw):
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(gzip.compress(raw, mtime=0))
            out.flush()
            os.link(tmp, dest)
        except FileExistsError:
            pass
        finally:
            tmp.unlink(missing_ok=True)


def cache_calendars(root, first, last, *, fetch=fetch_once, pause=time.sleep):
    """Cache complete source documents by day; a denial interrupts further requests."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        dest = root / f"{day.isoformat()}.html.gz"
        if dest.exists():
            continue
        data = fetch(f"{DOMAIN}/raceresult/{day:%Y/%m/%d}/")
        daily_rows(data.decode("utf-8"), day)
        save_capture(dest, data)
        pause(1)


class Census:
    def __init__(self, first, last):
        if first > last:
            raise ValueError("Inverted date interval")
        self.first, self.last = first, last
        self.bounds = (first.strftime("%Y%m%d"), last.strftime("%Y%m%d"))
        self.entries = defaultdict(dict)
        self.links = {}
        self.checked_days = set()
        self.calendar_receipts = {}
        self.public_receipts = {}
        self.failed_days = {}
        self.conflicts = set()
        self.confirmed_absent = {}
        self.invalid = Counter()
        self.public_counts = Counter()
        self.historical_witnesses = defaultdict(set)
        self.unresolved_signatures = defaultdict(set)

    def register(self, key, source, field):
        if not self.bounds[0] <= key[:8] <= self.bounds[1]:
            return
        row = self.entries[key].setdefault(source, {})
        for car, rider in field.items():
            if type(car) is not int or car not in range(1, 10):
                raise ValueError("Invalid car")
            if rider is not None and not re.fullmatch(r"[0-9]{6}", rider):
                raise ValueError("Invalid registration")
            if rider is not None and row.get(car) not in (None, rider):
                self.conflicts.add((key, car))
            if rider is not None or car not in row:
                row[car] = rider

    def add_calendars(self, root):
        for offset in range((self.last - self.first).days + 1):
            day = self.first + timedelta(days=offset)
            path = root / f"{day.isoformat()}.html.gz"
            if not path.is_file():
                self.failed_days[day.isoformat()] = "missing"
                continue
            try:
                with gzip.open(path, "rb") as stream:
                    raw = stream.read()
                found = daily_rows(raw.decode("utf-8"), day)
                self.calendar_receipts[day.isoformat()] = sha256(raw).hexdigest()
            except (ValueError, OSError, EOFError) as error:
                self.failed_days[day.isoformat()] = str(error)
                continue
            self.checked_days.add(day.isoformat())
            self.links.update(found)

    def records(self):
        for key in sorted(self.links.keys() | self.entries.keys()):
            sources = self.entries.get(key, {})
            complete_source = next((s for s in ("programme", "public_starters", "verified_starters") if s in sources), None)
            verified = sources.get(complete_source)
            absent = self.confirmed_absent.get(key, set()) if "programme" not in sources else set()
            field = sorted(verified if verified is not None else {car for row in sources.values() for car in row})
            conflict = verified is not None and any(
                cars and set(cars) - absent != set(field) for cars in sources.values()
            )
            if self.links.get(key, (None, False))[1] and verified is None:
                field = []
            riders = {}
            for car in field:
                values = {cars[car] for cars in sources.values() if cars.get(car)}
                disagrees = len(values) > 1 or (key, car) in self.conflicts
                conflict |= disagrees
                riders[car] = next(iter(values)) if len(values) == 1 and not disagrees else None
            duplicated = {rider for rider, n in Counter(riders.values()).items() if rider and n > 1}
            if duplicated:
                conflict = True
                riders = {car: None if reg in duplicated else reg for car, reg in riders.items()}
            url, cancelled = self.links.get(key, (None, False))
            if cancelled and verified is not None:
                conflict = True
            complete = verified is not None and not conflict
            yield {
                "race_id": key,
                "race_date": date.fromisoformat(key[:8]).isoformat(),
                "riders": [{"car": car, "rider_id": rider} for car, rider in riders.items()],
                "race_detail_url": url,
                "listing_status": "daily_result_link" if url else "archive_only",
                "roster_status": ("conflict" if conflict else complete_source if complete
                                  else "archived_entries" if field else "unavailable"),
                "roster_complete": complete,
                "event_status": ("unknown" if cancelled and verified is not None else
                                 "cancelled_reported" if cancelled else "finish_verified" if "programme" in sources
                                 else "unknown"),
                "sources": sorted(sources),
            }


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def checked_blobs(manifest, directory):
    for record in json.loads(manifest.read_bytes())["blobs"]:
        path = directory / Path(record["path"]).name
        if digest(path) != record["sha256"]:
            raise ValueError("Source archive digest mismatch")
        yield path


def _bind(index, name, term, prefecture, csv_source, census, key, car):
    stripped = re.sub(r"[（(]欠車[)）]$", "", str(term).strip())
    if not stripped.isascii() or not stripped.isdigit():
        return None
    identity = name_key(name), int(stripped), name_key(prefecture)
    value = index.bind(identity, from_csv=csv_source)
    if (identity, csv_source) in getattr(index, "disputed", ()):
        census.conflicts.add((key, car))
    return value


class WitnessedIdentityIndex:
    """Extend the existing registry only for exact tuples seen on two matching pages."""
    def __init__(self, baseline, witnesses):
        self.baseline = baseline
        self.witnesses = witnesses
        self.disputed = set()

    def bind(self, identity, *, from_csv):
        name, cohort, prefecture = identity
        candidate_tuples = [(name, cohort, prefecture_key(prefecture))]
        if from_csv and len(name) > 1 and len(prefecture) == 1:
            candidate_tuples.append((name[:-1], cohort, prefecture_key(name[-1] + prefecture)))
        witnessed = {reg for key in candidate_tuples for reg in self.witnesses.get(key, ())}
        original = self.baseline.bind(identity, from_csv=from_csv)
        if not witnessed:
            return original
        compatible = {reg for n, t, p in candidate_tuples for reg in self.baseline.candidates(n, t)
                      if p in self.baseline.prefectures[reg]}
        matches = witnessed | compatible
        # Existing registry disagreements, including a conflicting cohort for a
        # registered ID, require a separate investigation.
        if len(matches) != 1:
            self.disputed.add((identity, from_csv))
            return None
        reg = next(iter(matches))
        current_cohort = self.baseline.cohorts.get(reg)
        if current_cohort not in (None, cohort):
            self.disputed.add((identity, from_csv))
            return None
        return reg


def add_archives(census, root, index):
    for path in checked_blobs(root / "monthly-provenance.json", root / "monthly"):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                try:
                    key = monthly_key(row["race_id"], row["date"], row["race_no"])
                except ValueError:
                    census.invalid["monthly_malformed_race_row"] += 1
                    continue
                if not census.bounds[0] <= key[:8] <= census.bounds[1]:
                    continue
                field = {}
                if row["banum"] in tuple("123456789") and str(row["player_name"]).strip():
                    if "欠車" not in str(row["term"]) and row["rank"].strip() not in ("欠", "欠車", "欠場"):
                        car = int(row["banum"])
                        field[car] = _bind(index, row["player_name"], row["term"], row["pref"], True, census, key, car)
                        if field[car] is None and not census.entries[key].get("programme", {}).get(car):
                            census.unresolved_signatures[key].add((name_key(row["player_name"]), row["term"].strip(),
                                                                  name_key(row["pref"])))
                census.register(key, "monthly", field)
    for path in checked_blobs(root / "db-provenance.json", root):
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
            for table, detail in (("races", ""), ("entries", ", kumiban, racer_name, kyu, prefecture")):
                rows = conn.execute(f"SELECT race_date, venue_code, rno {detail} FROM {table} "
                                    "WHERE race_date BETWEEN ? AND ?", census.bounds)
                for day, venue, number, *entry in rows:
                    key = compact_id(f"{day}{venue}{number:02d}")
                    field = {}
                    if entry:
                        car, name, term, prefecture = entry
                        if "欠車" not in str(term):
                            field[car] = _bind(index, name, term, prefecture, False, census, key, car)
                    census.register(key, "sqlite", field)
            # A full entry/result identity join recovers incident races whose finish
            # order was deliberately excluded from the ranking study.
            statement = """
                SELECT e.race_date, e.venue_code, e.rno, e.kumiban, e.racer_name, r.racer_name, r.rank
                FROM entries e LEFT JOIN results r USING (race_date,venue_code,rno,kumiban)
                WHERE e.race_date BETWEEN ? AND ?
                ORDER BY e.race_date,e.venue_code,e.rno,e.kumiban
            """
            orphan_results = set(conn.execute("""
                SELECT DISTINCT r.race_date,r.venue_code,r.rno FROM results r
                LEFT JOIN entries e USING (race_date,venue_code,rno,kumiban)
                WHERE r.race_date BETWEEN ? AND ? AND e.kumiban IS NULL
            """, census.bounds))
            for (day, venue, number), observations in groupby(conn.execute(statement, census.bounds), lambda row: row[:3]):
                key = compact_id(f"{day}{venue}{number:02d}")
                if "programme" in census.entries[key] or (day, venue, number) in orphan_results:
                    continue
                checked = starter_field(observations)
                if checked is None:
                    continue
                present, absent = checked
                census.confirmed_absent[key] = absent
                field = census.entries[key]["sqlite"]
                census.register(key, "verified_starters", {car: field.get(car) for car in present})


def starter_field(observations):
    present, absent = set(), set()
    for _day, _venue, _number, car, entry_name, result_name, place in observations:
        if car in present | absent or not name_key(entry_name) or name_key(entry_name) != name_key(result_name):
            return None
        if place in ("欠", "欠車", "欠場"):
            absent.add(car)
        elif place in tuple("123456789") + ("落", "失", "故", "棄"):
            present.add(car)
        else:
            return None
    if not 5 <= len(present) <= 9:
        return None
    return present, absent


def add_dated_entries(census, repo, revision, index):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full pinned entry archive commit is required")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], timeout=30)

    for filename in git("ls-tree", "--name-only", revision).decode().splitlines():
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.json", filename):
            continue
        day = date.fromisoformat(filename[:10])
        if not census.first <= day <= census.last:
            continue
        packet = json.loads(git("show", f"{revision}:{filename}"))
        if packet["date"] != day.isoformat():
            raise ValueError("Dated card and archive filename disagree")
        for race in packet["races"]:
            key = compact_id(race["race_id"])
            if key[:8] != day.strftime("%Y%m%d") or int(key[-2:]) != int(race["race_number"]):
                raise ValueError("Dated entry race identifier mismatch")
            census.register(key, "dated_entries", {})
            for row in race.get("entries", []):
                if row.get("is_absent") is True:
                    continue
                reg = str(row.get("rider_id") or "").zfill(6)
                name = name_key(row.get("rider_full_name") or row.get("rider_name"))
                if name not in index.names.get(reg, set()):
                    reg = None
                if reg and isinstance(row.get("term"), int) and row.get("prefecture"):
                    index.observe_exact_race((name, row["term"], name_key(row["prefecture"])), reg)
                census.register(key, "dated_entries", {row["car_number"]: reg})


def add_cards(census, path, expected):
    if digest(path) != expected:
        raise ValueError("Verified programme digest mismatch")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for key, _source, _groups, rows in json.load(stream):
            cars = {car: rider for car, rider, *_ in rows}
            if len(cars) != len(rows) or not 5 <= len(cars) <= 9:
                raise ValueError("Malformed verified full field")
            census.register(compact_id(key), "programme", cars)


def read_race_page(raw, canonical):
    doc = BeautifulSoup(raw, "lxml")
    links = doc.select('link[rel="canonical"][href]')
    if len(links) != 1 or links[0]["href"] != canonical:
        raise ValueError("Race page canonical identity mismatch")
    return doc


def _started(label):
    if re.fullmatch(r"[1-9](?:着)?", label) or label in ("落", "落棄", "失", "失格", "故", "故入", "棄", "棄権"):
        return True
    if label in ("欠", "欠車", "欠場"):
        return False
    raise ValueError("Unclassified race participation")


def _roster_row(field, car, person):
    if not re.fullmatch("[1-9]", car) or int(car) in field or not person[0]:
        raise ValueError("Duplicate/malformed public entry")
    field[int(car)] = person


class CancelledRace(ValueError):
    pass


def public_starters(key, kd_url, kd_raw, net_raw, *, witnesses=None):
    """Cross-check the source programme, participating cars, full names and linked profiles."""
    match = DETAIL.fullmatch(urlsplit(kd_url).path)
    parsed = urlsplit(kd_url)
    if parsed.scheme != "https" or parsed.netloc != "keirin.kdreams.jp" or not match:
        raise ValueError("Unrecognized race detail URL")
    if monthly_key(match.group(1), date.fromisoformat(key[:8]).isoformat(), key[-2:]) != key:
        raise ValueError("Race detail and expected key disagree")
    kd = read_race_page(kd_raw, kd_url)
    net = read_race_page(net_raw, f"https://keirin.netkeiba.com/race/result/?race_id={key.replace('-', '')}")
    field, results, registrations = {}, {}, {}
    entry_traits, net_traits = {}, {}
    tables = kd.select("table.racecard_table:not(.none)")
    if len(tables) != 1:
        raise ValueError("Unsupported KDreams entry table")
    for row in tables[0].select("tr"):
        rider = row.select_one("td.rider")
        if rider is not None:
            car = row.select_one("td.num")
            if car is None:
                raise ValueError("KDreams entry car missing")
            number = car.get_text(strip=True)
            full_name = name_key("".join(rider.find_all(string=True, recursive=False)))
            _roster_row(field, number, (full_name,))
            home = rider.select_one(".home")
            details = re.fullmatch(r"([^/]+)/[0-9]{1,2}/([0-9]{1,3})", name_key(home.get_text()) if home else "")
            if details:
                entry_traits[int(number)] = full_name, int(details[2]), prefecture_key(details[1])
    if (net.find(string=lambda t: t and t.strip() == "本レースは中止となりました")
            and any(tag.get_text(strip=True) == "中止" for tag in kd.select("li.bet .disabled"))
            and len(kd.select("table.result_table")) == 1):
        places = [cells[1].get_text(strip=True) for row in kd.select("table.result_table tr")
                  if len(cells := row.find_all("td", recursive=False)) >= 4]
        if places and not any(places):
            raise CancelledRace("Two sources reported cancellation")
    if len(kd.select("table.result_table")) != 1 or len(net.select("table.ResultRefund")) != 1:
        raise ValueError("Completed race result tables unavailable")
    for row in kd.select("table.result_table tr"):
        cells = row.find_all("td", recursive=False)
        if cells:
            if len(cells) < 4:
                raise ValueError("KDreams result row incomplete")
            _roster_row(results, cells[2].get_text(strip=True),
                        (name_key(cells[3].get_text(strip=True)), _started(cells[1].get_text(strip=True))))
    for row in net.select("table.ResultRefund tr.PlayerList"):
        cells = row.find_all("td", recursive=False)
        profiles = row.select("td.Player_Info a.Player01[href]")
        names = row.select("td.Player_Info .PlayerName")
        finish = row.select_one("td.Result_Num")
        if len(cells) < 4 or len(profiles) != 1 or len(names) != 1 or finish is None:
            raise ValueError("netkeirin result row incomplete")
        car = cells[2].get_text(strip=True)
        profile = re.fullmatch(r"https://keirin\.netkeiba\.com/db/profile/\?id=([0-9]{5,6})", profiles[0]["href"])
        if not profile or f"Waku{car}" not in cells[2].get("class", []):
            raise ValueError("Unverified linked rider/car identity")
        full_name = name_key(names[0].get_text(strip=True))
        _roster_row(registrations, car, (full_name, _started(finish.get_text(strip=True)), profile[1].zfill(6)))
        region, grade = row.select_one(".PlayerFrom span"), row.select_one(".PlayerClass")
        cohort = re.match(r"([0-9]{1,3})期", name_key(grade.get_text()) if grade else "")
        if region and cohort:
            spelling = prefecture_key(region.get_text())
            spelling = NET_SHORT_PREFECTURES.get(spelling, spelling)
            net_traits[int(car)] = full_name, int(cohort[1]), spelling
    if ({c: r[0] for c, r in results.items()} != {c: r[0] for c, r in field.items()}
            or results != {c: r[:2] for c, r in registrations.items()}):
        raise ValueError("Public programme and result registrants disagree")
    starters = {car: rider for car, (_, started, rider) in registrations.items() if started}
    if not 5 <= len(starters) <= 9 or len(set(starters.values())) != len(starters):
        raise ValueError("Incomplete or duplicate participating rider field")
    if witnesses is not None:
        for car, reg in starters.items():
            traits = entry_traits.get(car)
            if traits and traits == net_traits.get(car):
                witnesses[traits].add(reg)
    return starters, registrations.keys() - starters.keys()


def hydrate(census, cache, selected, limit, *, fetch=fetch_once, pause=time.sleep):
    cache.mkdir(mode=0o700, exist_ok=True, parents=True)
    paired = {path.name.split(".")[0] for path in cache.glob("*.kd.html.gz")
              if path.with_name(path.name.replace(".kd.", ".net.")).is_file()}
    requested = set(selected)
    if requested - census.links.keys():
        raise ValueError("A selected public race has no verified dated result index link")
    cached = sorted(paired & census.links.keys())
    pending = []
    seen = paired | requested
    if limit:
        # Prioritize footage without a roster, then partially identified fields.
        options = [(bool(row["riders"]), row["race_id"]) for row in census.records()
                   if row["race_detail_url"] and row["race_id"] not in seen
                   and (not row["roster_complete"] or any(rider["rider_id"] is None for rider in row["riders"]))]
        options.sort()
        if limit == -1:
            pending = [key for _, key in options]
        else:
            pending = [key for has_field, key in options if not has_field][:limit]
            available = {key: census.unresolved_signatures[key] for has_field, key in options
                         if has_field and census.unresolved_signatures.get(key)}
            frequencies = Counter(sig for signatures in available.values() for sig in signatures)
            covered = set()
            while available and len(pending) < limit:
                gain, key = max((sum(frequencies[sig] for sig in sigs - covered), k) for k, sigs in available.items())
                if not gain:
                    break
                pending.append(key)
                covered.update(available.pop(key))
            if len(pending) < limit:
                picked = set(pending)
                pending.extend([k for _, k in options if k not in picked][:limit-len(pending)])
    for key in dict.fromkeys([*cached, *sorted(requested), *pending]):
        kd_url, _ = census.links[key]
        pages = []
        for tag, url in (("kd", kd_url), ("net", f"https://keirin.netkeiba.com/race/result/?race_id={key.replace('-', '')}")):
            dest = cache / f"{key}.{tag}.html.gz"
            if not dest.exists():
                raw = fetch(url)
                save_capture(dest, raw)
                pause(1)
            with gzip.open(dest, "rb") as src:
                pages.append(src.read())
        census.public_receipts[key] = [sha256(page).hexdigest() for page in pages]
        try:
            riders, absent = public_starters(key, kd_url, *pages, witnesses=census.historical_witnesses)
        except CancelledRace:
            census.public_counts["two_source_cancelled"] += 1
            census.links[key] = (kd_url, True)
            census.register(key, "public_cancelled", {})
            continue
        except ValueError as exc:
            census.public_counts[str(exc)] += 1
            continue
        if key in census.confirmed_absent and census.confirmed_absent[key] != absent:
            census.public_counts["Absent-car source disagreement"] += 1
            continue
        census.confirmed_absent[key] = absent
        census.register(key, "public_starters", riders)
        census.public_counts["two_source_starter_fields"] += 1


def write_inventory(census, output):
    counts = Counter()
    populations = defaultdict(set)
    by_source = Counter()
    by_month = defaultdict(Counter)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=output.parent, delete=False, encoding="utf-8") as out:
        tmp = Path(out.name)
    try:
        with tmp.open("w", encoding="utf-8") as out:
            for row in census.records():
                out.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
                counts["races"] += 1
                counts[row["listing_status"]] += 1
                counts["roster_" + row["roster_status"]] += 1
                counts["event_" + row["event_status"]] += 1
                counts["roster_rows"] += len(row["riders"])
                known = {r["rider_id"] for r in row["riders"] if r["rider_id"]}
                counts["registered_roster_rows"] += len(known)
                counts["complete_registered_fields"] += row["roster_complete"] and len(known) == len(row["riders"])
                populations["registered_ids"].update(known)
                by_source.update(row["sources"])
                by_month[row["race_date"][:7]][row["listing_status"]] += 1
                if row["race_detail_url"] and not row["sources"]:
                    counts["listed_without_archive"] += 1
        os.link(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return {"from": census.first.isoformat(), "through": census.last.isoformat(),
            "days_requested": (census.last - census.first).days + 1, "daily_indices_valid": len(census.checked_days),
            "failed_dates": census.failed_days, "counts": dict(counts),
            "distinct_registered_ids": len(populations["registered_ids"]), "source_races": dict(by_source),
            "by_month": dict(by_month), "public_roster_verification": dict(census.public_counts),
            "two_source_identity_tuples": len(census.historical_witnesses),
            "calendar_receipts_sha256": sha256(json.dumps(census.calendar_receipts, sort_keys=True).encode()).hexdigest(),
            "public_roster_receipts_sha256": sha256(json.dumps(census.public_receipts, sort_keys=True).encode()).hexdigest(),
            "ambiguous_witness_tuples": sum(len(ids) > 1 for ids in census.historical_witnesses.values()),
            "input_exclusions": dict(census.invalid), "sha256": digest(output)}


def main():
    cmd = argparse.ArgumentParser(description=__doc__)
    cmd.add_argument("--first", type=date.fromisoformat, required=True)
    cmd.add_argument("--last", type=date.fromisoformat, required=True)
    cmd.add_argument("--calendar", type=Path, required=True, help="Dated YYYY-MM-DD.html.gz public result indices")
    cmd.add_argument("--fetch-missing-calendars", action="store_true", help="Use ordinary daily result pages and resume cached dates")
    cmd.add_argument("--dated-entry-repo", type=Path, help="Optional pinned daily entry-card Git archive")
    cmd.add_argument("--dated-entry-commit", help="Full commit of the daily entry archive")
    cmd.add_argument("--archive", type=Path, help="Local monthly and SQLite SHA manifest root")
    cmd.add_argument("--registry", type=Path)
    cmd.add_argument("--master", type=Path)
    cmd.add_argument("--cards", type=Path)
    cmd.add_argument("--cards-sha256")
    cmd.add_argument("--public-cache", type=Path, help="Private resumable source cache for two-source roster verification")
    cmd.add_argument("--public-races", type=int, default=0, help="Fetch this many additional unverified race rosters, or all with -1")
    cmd.add_argument("--public-race", action="append", default=[], help="Explicit YYYYMMDD-VV-RR for public roster refresh")
    cmd.add_argument("--summary", type=Path, help="Also save the aggregate JSON receipt (create once)")
    cmd.add_argument("--output", type=Path, required=True, help="Create-once private JSONL")
    args = cmd.parse_args()
    if args.output.exists() or (args.summary and (args.summary.exists() or args.summary == args.output)):
        cmd.error("Choose new distinct output and summary paths to preserve previous receipts")
    census = Census(args.first, args.last)
    if bool(args.cards) != bool(args.cards_sha256):
        cmd.error("Supply both verified study cards and their SHA-256")
    if args.cards:
        add_cards(census, args.cards, args.cards_sha256)
    if bool(args.dated_entry_repo) != bool(args.dated_entry_commit):
        cmd.error("Supply both dated entry archive and commit")
    defer_archive = args.archive and args.public_cache and not args.public_races
    if args.archive or args.dated_entry_repo:
        if not (args.registry and args.master):
            cmd.error("The archived entry identity join requires --registry and --master")
        index = IdentityIndex(json.loads(args.registry.read_bytes())["riders"], json.loads(args.master.read_bytes())["items"])
        if args.dated_entry_repo:
            add_dated_entries(census, args.dated_entry_repo, args.dated_entry_commit, index)
        if args.archive and not defer_archive:
            add_archives(census, args.archive, index)
    if args.fetch_missing_calendars:
        cache_calendars(args.calendar, args.first, args.last)
    census.add_calendars(args.calendar)
    if args.public_races < -1 or ((args.public_races or args.public_race) and not args.public_cache):
        cmd.error("Use --public-cache with --public-races N (or -1) or --public-race")
    if args.public_cache:
        hydrate(census, args.public_cache, args.public_race, args.public_races)
        if args.archive and (census.historical_witnesses or defer_archive):
            # Re-bind all archive rows. Block both sides of an ambiguous new
            # identity rather than keeping the prior assignment by accident.
            for sources in census.entries.values():
                sources.pop("monthly", None)
                sources.pop("sqlite", None)
                sources.pop("verified_starters", None)
            census.invalid.clear()
            add_archives(census, args.archive, WitnessedIdentityIndex(index, census.historical_witnesses))
    summary = json.dumps(write_inventory(census, args.output), ensure_ascii=False, sort_keys=True)
    if args.summary:
        with args.summary.open("x", encoding="utf-8") as output:
            output.write(summary + "\n")
    print(summary)


if __name__ == "__main__":
    main()
