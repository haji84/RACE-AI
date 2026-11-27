"""Resume a private text ledger of public-player checks, without fetching media."""

import argparse
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from scripts.keirin_video_archive_index import official, replay_id
from scripts.keirin_video_census import DETAIL, compact_id, monthly_key
from scripts.keirin_video_corpus import output_file, pack, sha, valid_car
from scripts.keirin_video_sources import WINTICKET_DETAIL, WINTICKET_HOST


YENJOY = re.compile(r"/yenjoy/keirin-kaisai/race-card/result/(\d{10})/(\d{14})/(\d{1,2})/")
STATES = ("failed", "playback_only", "unreadable", "observed")
PHASES = ("back", "corner")
FOLLOWER_FIELDS = ("_second_car", "_nearest_follower_car", "_runner_up")
PHASE_FIELDS = {phase + field for phase in PHASES for field in ("_car", "_seconds", *FOLLOWER_FIELDS)}


def race_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{12}|[0-9]{8}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("invalid race identifier")
    return compact_id(value.replace("-", ""))


def source_key(url):
    """Bind the specific result/digest page to its actual meeting day and race."""
    if isinstance(url, str) and official(url):
        if key := replay_id(url):
            return key
        bits = urlsplit(url)
        match = YENJOY.fullmatch(bits.path)
        if match and match[2].startswith(match[1]) and not bits.query and not bits.fragment:
            identifier = match[2] + match[3].zfill(2)
        else:
            match = DETAIL.fullmatch(bits.path)
            if not match or bits.query not in ("", "pageType=showResult") or bits.fragment:
                raise ValueError("expected a public page for a single race")
            identifier = match[1]
        return monthly_key(identifier, identifier[2:10], int(identifier[-2:]))
    raise ValueError("expected a KDreams race source")


def _winticket_playback_key(url):
    """Resolve a manually viewed result link using the meeting code and day number."""
    if not isinstance(url, str):
        return None
    bits = urlsplit(url)
    if bits.netloc != WINTICKET_HOST:
        return None
    match = WINTICKET_DETAIL.fullmatch(bits.path)
    if not match or url != f"https://{WINTICKET_HOST}{bits.path}":
        raise ValueError("expected a public WINTICKET result page for a single race")
    _, opened, venue, meeting_day, race = match.groups()
    day = date.fromisoformat(opened) + timedelta(days=int(meeting_day) - 1)
    return compact_id(f"{day:%Y%m%d}{venue}{int(race):02d}")


def read_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        if path.name.endswith((".jsonl", ".jsonl.gz")):
            for line in stream:
                if line.strip():
                    yield json.loads(line)
        else:
            value = json.load(stream)
            yield from value if isinstance(value, list) else [value]


def check_roster(key, cars, complete_field):
    if complete_field is not None and not set(cars) <= {int(n) for n in complete_field.split(",") if n}:
        raise ValueError(f"observed car is absent from the complete roster: {key}")


def validate_note(row, complete_field=None):
    key = race_key(row.get("race_id") or row.get("race"))
    if "race" in row and race_key(row["race"]) != key:
        raise ValueError(f"conflicting identifiers: {key}")
    if "race_date" in row and date.fromisoformat(row["race_date"]).strftime("%Y%m%d") != key[:8]:
        raise ValueError(f"conflicting record date: {key}")
    url = row.get("source_url") or row.get("source_ref")
    winticket_key = _winticket_playback_key(url)
    if (winticket_key or source_key(url)) != key:
        raise ValueError(f"wrong race source: {key}")
    if winticket_key is not None and ("adjudication" in row or PHASE_FIELDS.intersection(row)):
        raise ValueError(f"WINTICKET manual notes only record viewing status: {key}")
    lengths = [row[name] for name in ("duration_seconds", "player_duration_seconds", "duration_s")
               if row.get(name) is not None]
    if any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in lengths):
        raise ValueError(f"invalid replay duration: {key}")
    labels = {}
    reported_cars = set()
    for phase in PHASES:
        car = row.get(phase + "_car")
        number = row.get(phase + "_seconds")
        if car is not None and not valid_car(car):
            raise ValueError(f"invalid {phase} car: {key}")
        if number is not None and (type(number) not in (float, int) or not math.isfinite(number) or number < 0):
            raise ValueError(f"invalid {phase} playback time: {key}")
        if number is not None and lengths and number > min(lengths):
            raise ValueError(f"{phase} outside replay duration: {key}")
        followers = [row[phase + field] for field in FOLLOWER_FIELDS if row.get(phase + field) is not None]
        if any(not valid_car(n) or n == car for n in followers) or len(set(followers)) > 1:
            raise ValueError(f"invalid {phase} following car: {key}")
        if car is not None or followers:
            if number is None:
                raise ValueError(f"missing {phase} playback time: {key}")
            reported_cars.update(followers)
            if car is not None:
                labels[phase] = car
                reported_cars.add(car)
    check_roster(key, reported_cars, complete_field)
    if (row.get("back_seconds") is not None and row.get("corner_seconds") is not None
            and row["back_seconds"] >= row["corner_seconds"]):
        raise ValueError(f"reversed phase times: {key}")
    state = row.get("status", "observed" if reported_cars else None)
    if state not in STATES or bool(reported_cars) != (state == "observed"):
        raise ValueError(f"specify the actual viewing status and observed positions: {key}")
    if not any(isinstance(row.get(k), str) and row[k].strip()
               for k in ("evidence", "observation", "notes", "observation_basis", "reason")):
        raise ValueError(f"missing observation or failure reason: {key}")
    return key, state, labels


def attach_checkpoints(corpus, rows, path, complete_fields):
    for item in read_rows(path):
        if not item.get("checkpoints"):
            continue
        key, url = race_key(item["race_id"]), item["source_ref"]
        if source_key(url) != key or key not in rows:
            raise ValueError(f"previous observation belongs to another race: {key}")
        saved = corpus.execute(
            "SELECT receipt FROM media WHERE race=? AND source=? AND kind='frames'", (key, url)
        ).fetchone()
        if not saved:
            raise ValueError(f"no verified frame receipt for previous observation: {key}")
        frame_hashes = json.loads(saved[0])
        points = rows[key].setdefault("previous_checkpoints", [])
        for point in item["checkpoints"]:
            cars, at, fingerprint = point["ordered_front_cars"], point["at_ms"], point["sha256"]
            if (point["checkpoint"] not in ("home", "back", "corner") or not cars
                or not all(valid_car(c) for c in cars) or len(set(cars)) != len(cars)
                or type(at) is not int or at < 0 or not sha(fingerprint)
                or frame_hashes.get(str(at)) != fingerprint):
                raise ValueError(f"previous observation does not match its verified source: {key}")
            check_roster(key, cars, complete_fields.get(key))
            if point not in points:
                points.append(point)


def census_rows(corpus):
    rows = {}
    for key, day, event, url in corpus.execute("SELECT id,day,event_status,url FROM race"):
        rows[key] = {"race_id": key, "race_date": day, "in_census": True, "event_status": event,
                     "race_detail_url": url, "previous_media": [], "known_rider_reviews": 0}
    for key, source, kind in corpus.execute("SELECT DISTINCT race,source,kind FROM media ORDER BY race,source,kind"):
        rows[key]["previous_media"].append({"source_ref": source, "kind": kind})
    for key, count in corpus.execute("SELECT race,count(*) FROM eligible_review WHERE known=1 GROUP BY race"):
        rows[key]["known_rider_reviews"] = count
    return rows


def attach_archive(rows, path):
    for row in read_rows(path):
        key = race_key(row["race_id"])
        refs = row["published_replay_references"]
        if key not in rows or any(not sha(h) or replay_id(ref["url"]) != key for h, ref in refs.items()):
            raise ValueError(f"archive reference is outside its census or belongs to a different race: {key}")
        rows[key]["archived_replay_links"] = sorted({r["url"] for r in refs.values()})


def reduce_race(row, receipts):
    states = {r["status"] for r in receipts}
    held_phases = set()
    positions, followers = defaultdict(set), defaultdict(set)
    for point in row.get("previous_checkpoints", []):
        phase = point["checkpoint"]
        positions[phase].add(point["ordered_front_cars"][0])
        if len(point["ordered_front_cars"]) > 1:
            followers[phase].add(point["ordered_front_cars"][1])
    for receipt in receipts:
        entry = receipt["entry"]
        if entry.get("adjudication"):
            for phase in PHASES:
                if phase + "_car" in entry and entry[phase + "_car"] is None:
                    held_phases.add(phase)
        for phase in PHASES:
            followers[phase].update(entry[phase + f] for f in FOLLOWER_FIELDS if entry.get(phase + f) is not None)
        for phase, car in receipt["labels"].items():
            positions[phase].add(car)
    by_phase = {phase: sorted(cars) for phase, cars in sorted(positions.items())}
    following = {k: sorted(v) for k, v in sorted(followers.items()) if v}
    disputed = sorted({k for k, cars in by_phase.items() if len(cars) > 1 or k in held_phases}
                      | {k for k, cars in following.items() if len(cars) > 1})
    if disputed:
        status = "conflicting_observations"
    elif "observed" in states:
        status = "observed"
    elif row.get("event_status") == "cancelled_reported":
        status = "cancelled_reported"
    elif row.get("known_rider_reviews") or row.get("previous_checkpoints"):
        status = "prior_rider_review"
    elif "unreadable" in states:
        status = "unreadable"
    elif "playback_only" in states or row.get("previous_media"):
        status = "playback_only"
    elif "failed" in states:
        status = "failed"
    elif row.get("archived_replay_links"):
        status = "published_button"
    else:
        status = "calendar_only"
    row.update(status=status, reported_leaders=by_phase, reported_followers=following, disputed_phases=disputed, receipts=receipts)
    return status


def update(corpus_path, state_path, notes, index, output, checkpoints=None):
    inputs = {p.resolve() for p in (corpus_path, *notes, index, checkpoints) if p is not None}
    if state_path.resolve() in inputs or output.resolve() in inputs | {state_path.resolve()}:
        raise ValueError("use separate ledger, input, and export files")
    uri = corpus_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as corpus:
        rows = census_rows(corpus)
        complete_fields = dict(corpus.execute("""
            SELECT r.id,coalesce(group_concat(s.car),'') FROM race AS r
            LEFT JOIN starter AS s ON s.race=r.id WHERE r.complete_roster=1 GROUP BY r.id
        """))
        if checkpoints:
            attach_checkpoints(corpus, rows, checkpoints, complete_fields)
    if not rows:
        raise ValueError("empty census")
    first_day, last_day = min(rows)[:8], max(rows)[:8]
    if index:
        attach_archive(rows, index)
    aggregate = {"in_census": Counter(), "outside_window": Counter()}
    lock_path = state_path.with_name(state_path.name + ".lock")
    if lock_path.resolve() in inputs | {output.resolve()}:
        raise ValueError("ledger lock and data files must be separate")
    with lock_path.open("a") as lock, closing(sqlite3.connect(state_path, timeout=60)) as state:
        # Keep concurrent exports ordered even after the SQLite commit releases its writer lock.
        fcntl.flock(lock, fcntl.LOCK_EX)
        state.execute("BEGIN IMMEDIATE")
        state.execute("""CREATE TABLE IF NOT EXISTS public_player_note(
                      digest TEXT PRIMARY KEY, race TEXT NOT NULL, entry TEXT NOT NULL)""")
        for path in notes:
            for row in read_rows(path):
                key = race_key(row.get("race_id") or row.get("race"))
                _, status, _ = validate_note(row, complete_fields.get(key))
                if key in rows and rows[key]["event_status"] == "cancelled_reported" and status != "failed":
                    raise ValueError(f"viewing receipt contradicts cancelled race: {key}")
                body = pack(row)
                tag = hashlib.sha256(body.encode()).hexdigest()
                state.execute("INSERT OR IGNORE INTO public_player_note VALUES(?,?,?)", (tag, key, body))
        by_race = defaultdict(list)
        for tag, key, body in state.execute("SELECT digest,race,entry FROM public_player_note ORDER BY race,digest"):
            if key not in rows:
                if first_day <= key[:8] <= last_day:
                    raise ValueError(f"unknown race inside dated census: {key}")
                rows[key] = {"race_id": key, "race_date": date.fromisoformat(key[:8]).isoformat(), "in_census": False}
            note = json.loads(body)
            _, status, labels = validate_note(note, complete_fields.get(key))
            by_race[key].append({"sha256": tag, "status": status, "labels": labels, "entry": note})
        with output_file(output) as stream:
            for key, row in sorted(rows.items()):
                group = "in_census" if row["in_census"] else "outside_window"
                aggregate[group][reduce_race(row, by_race[key])] += 1
                stream.write(pack(row) + "\n")
            state.commit()
    return aggregate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="existing keirin_video_corpus SQLite, opened read-only")
    parser.add_argument("--state", type=Path, required=True, help="private SQLite for text receipts, reused on subsequent runs")
    parser.add_argument("--archive-index", type=Path, help="optional JSONL or JSONL.GZ from keirin_video_archive_index")
    parser.add_argument("--checkpoints", type=Path, help="optional previous media manifest with hash-bound visual checkpoints")
    parser.add_argument("--observations", type=Path, nargs="*", default=[], help="private JSON object/list or JSONL(.gz)")
    parser.add_argument("--output", type=Path, required=True, help="full private JSONL export")
    args = parser.parse_args()
    os.umask(0o077)
    summary = update(args.corpus, args.state, args.observations, args.archive_index, args.output, args.checkpoints)
    print(pack(summary))


if __name__ == "__main__":
    main()
