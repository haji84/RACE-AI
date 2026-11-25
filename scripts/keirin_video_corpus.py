"""Maintain a private, resumable keirin film review ledger from verified local exports."""

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from itertools import groupby
from pathlib import Path


WHOLE_SCOPES = ("whole_race", "whole_final_lap")


def setup(db):
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    old = db.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name='starter_coverage'").fetchone()
    upgrade = ""
    if old and "eligible_review" not in old["sql"]:
        upgrade = "DROP VIEW IF EXISTS coverage; DROP VIEW starter_coverage;"
    db.executescript("BEGIN; " + upgrade + """
        CREATE TABLE IF NOT EXISTS race(
            id TEXT PRIMARY KEY, day TEXT NOT NULL, complete_roster INTEGER NOT NULL,
            event_status TEXT NOT NULL, url TEXT);
        CREATE TABLE IF NOT EXISTS starter(
            race TEXT REFERENCES race, car INTEGER, rider TEXT,
            PRIMARY KEY(race,car));
        CREATE TABLE IF NOT EXISTS media(
            race TEXT REFERENCES race, source TEXT, fingerprint TEXT, kind TEXT NOT NULL,
            receipt TEXT NOT NULL, PRIMARY KEY(race,source,fingerprint));
        CREATE TABLE IF NOT EXISTS review(
            race TEXT NOT NULL, car INTEGER NOT NULL, task TEXT NOT NULL,
            scope TEXT NOT NULL, level TEXT NOT NULL, entry TEXT NOT NULL,
            known INTEGER NOT NULL, PRIMARY KEY(race,car,task,scope,level),
            FOREIGN KEY(race,car) REFERENCES starter(race,car));
        CREATE TABLE IF NOT EXISTS review_history(entry TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS bounds(
            race TEXT, car INTEGER, scope TEXT, source TEXT, fingerprint TEXT,
            begin_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, entry TEXT NOT NULL,
            PRIMARY KEY(race,car,scope,source,fingerprint),
            FOREIGN KEY(race,car) REFERENCES starter(race,car),
            FOREIGN KEY(race,source,fingerprint) REFERENCES media(race,source,fingerprint));
        CREATE VIEW IF NOT EXISTS eligible_review AS
        SELECT v.* FROM review v
        WHERE NOT v.known OR (
            (v.level NOT IN ('whole_race','whole_final_lap') OR EXISTS(
                SELECT 1 FROM bounds b WHERE b.race=v.race AND b.car=v.car AND b.scope=v.scope
                AND b.source=json_extract(v.entry,'$.source_ref')
                AND b.fingerprint=json_extract(v.entry,'$.media_sha256')
                AND json_extract(v.entry,'$.start_ms')<=b.begin_ms
                AND json_extract(v.entry,'$.end_ms')>=b.end_ms))
            AND (json_extract(v.entry,'$.media_sha256') IS NOT NULL OR
                 (v.level='clip' AND (SELECT count(DISTINCT json_extract(f.value,'$.sha256'))
                  FROM json_each(v.entry,'$.evidence_frames') f)>=2)));
        CREATE VIEW IF NOT EXISTS starter_coverage AS
        SELECT s.race,s.car,s.rider,count(v.task) AS seen,
               sum(CASE WHEN v.level='whole_race' THEN 1 ELSE 0 END) AS whole_tasks,
               sum(CASE WHEN v.level='whole_final_lap' THEN 1 ELSE 0 END) AS lap_tasks
        FROM starter s LEFT JOIN eligible_review v ON v.race=s.race AND v.car=s.car AND v.known=1
        GROUP BY s.race,s.car;
        CREATE VIEW IF NOT EXISTS coverage AS
        SELECT r.*,count(s.car) AS starters,count(s.rider) AS registered,
               count(CASE WHEN s.seen>0 THEN 1 END) AS seen_starts,
               count(CASE WHEN s.whole_tasks=2 THEN 1 END) AS whole_starts,
               count(CASE WHEN s.lap_tasks=2 THEN 1 END) AS lap_starts,
               EXISTS(SELECT 1 FROM media m WHERE m.race=r.id) AS has_media
        FROM race r LEFT JOIN starter_coverage s ON s.race=r.id GROUP BY r.id;
        COMMIT;
    """)


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def valid_car(value):
    return type(value) is int and 1 <= value <= 9


def load_race(db, row):
    key, day = row["race_id"], row["race_date"]
    if (
        not re.fullmatch(r"[0-9]{8}-[0-9]{2}-[0-9]{2}", key)
        or date.fromisoformat(day).strftime("%Y%m%d") != key[:8]
    ):
        raise ValueError("race identity/date mismatch")
    complete = row.get("roster_complete", False)
    if type(complete) is not bool:
        raise ValueError("roster_complete must be boolean")
    state = row.get("event_status", "unknown")
    existing = db.execute("SELECT * FROM race WHERE id=?", (key,)).fetchone()
    if (
        existing
        and existing["event_status"] not in ("unknown", state)
        and state != "unknown"
    ):
        raise ValueError(f"contradictory race status: {key}")
    riders = {r["car"]: r["rider_id"] for r in row["riders"]}
    ids = [v for v in riders.values() if v is not None]
    if (
        len(riders) != len(row["riders"])
        or len(ids) != len(set(ids))
        or any(not valid_car(c) for c in riders)
        or any(not isinstance(v, str) or not re.fullmatch(r"[0-9]{6}", v) for v in ids)
    ):
        raise ValueError(f"invalid roster: {key}")
    previous = dict(db.execute("SELECT car,rider FROM starter WHERE race=?", (key,)))
    if existing and (
        (complete and not previous.keys() <= riders.keys())
        or (existing["complete_roster"] and not riders.keys() <= previous.keys())
    ):
        raise ValueError(f"complete field conflicts with other roster: {key}")
    for car, rider in riders.items():
        if previous.get(car) and rider and previous[car] != rider:
            raise ValueError(f"conflicting starter identity: {key}/{car}")
    merged = [
        riders.get(car) or previous.get(car) for car in previous.keys() | riders.keys()
    ]
    registered = [rider for rider in merged if rider]
    if len(registered) != len(set(registered)):
        raise ValueError(f"duplicate rider after merging rosters: {key}")
    db.execute(
        """INSERT INTO race VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  complete_roster=max(complete_roster,excluded.complete_roster),
                  event_status=CASE WHEN excluded.event_status='unknown' THEN event_status ELSE excluded.event_status END,
                  url=coalesce(excluded.url,url)""",
        (key, day, complete, state, row.get("race_detail_url")),
    )
    db.executemany(
        """INSERT INTO starter VALUES(?,?,?) ON CONFLICT(race,car) DO UPDATE SET
                      rider=coalesce(excluded.rider,rider)""",
        ((key, c, r) for c, r in riders.items()),
    )


def census_key(db, row):
    key = row["race_id"]
    stored = db.execute("SELECT day FROM race WHERE id=?", (key,)).fetchone()
    if not stored or row["race_date"] != stored["day"]:
        raise ValueError(f"race not in the dated census: {key}")
    return key


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)


def load_media(db, row):
    key = census_key(db, row)
    source, kind = row["source_ref"], row["kind"]
    if not source or row["status"] != "verified":
        raise ValueError(f"missing verified playback receipt: {key}")
    if kind == "frames":
        frames = {}
        for frame in row["frames"]:
            t, digest = frame["at_ms"], frame["sha256"]
            if (
                type(t) is not int
                or t < 0
                or not sha(digest)
                or (t in frames and frames[t] != digest)
            ):
                raise ValueError(f"invalid frame receipt: {key}")
            frames[t] = digest
        if not frames:
            raise ValueError(f"empty frame receipt: {key}")
        old = db.execute(
            "SELECT receipt FROM media WHERE race=? AND source=? AND fingerprint=?",
            (key, source, "frames"),
        ).fetchone()
        merged = json.loads(old["receipt"]) if old else {}
        for t, digest in frames.items():
            if str(t) in merged and merged[str(t)] != digest:
                raise ValueError(
                    f"frame conflicts with prior verified playback: {key}/{t}"
                )
            merged[str(t)] = digest
        fingerprint, receipt = "frames", merged
    elif kind in ("full", "clip"):
        fingerprint = row["sha256"]
        begin, duration = row["start_ms"], row["duration_ms"]
        if (
            not sha(fingerprint)
            or type(begin) is not int
            or begin < 0
            or type(duration) is not int
            or duration <= 0
            or row["coverage"] != "owner_declared_" + kind
        ):
            raise ValueError(f"invalid movie receipt: {key}")
        receipt = [begin, begin + duration]
        old = db.execute(
            "SELECT kind,receipt FROM media WHERE race=? AND source=? AND fingerprint=?",
            (key, source, fingerprint),
        ).fetchone()
        if old and (old["kind"] != kind or old["receipt"] != pack(receipt)):
            raise ValueError(f"movie clock or scope changed for existing bytes: {key}")
    else:
        raise ValueError(f"unknown media kind: {kind}")
    db.execute(
        """INSERT INTO media VALUES(?,?,?,?,?) ON CONFLICT(race,source,fingerprint)
                  DO UPDATE SET receipt=excluded.receipt""",
        (key, source, fingerprint, kind, pack(receipt)),
    )


def load_bounds(db, row):
    """Import separately observed car-specific start/final-H and goal timestamps."""
    key = census_key(db, row)
    car, scope = row["car"], row["scope"]
    fingerprint, source = row["media_sha256"], row["source_ref"]
    if (scope not in WHOLE_SCOPES or not valid_car(car) or not sha(fingerprint)
            or any(not isinstance(row.get(k), str) or not row[k].strip()
                   for k in ("reviewer", "note", "source_ref", "rider_id"))):
        raise ValueError("invalid full-window boundary evidence")
    starter = db.execute("SELECT rider FROM starter WHERE race=? AND car=?", (key, car)).fetchone()
    movie = db.execute("SELECT kind,receipt FROM media WHERE race=? AND source=? AND fingerprint=?",
                       (key, source, fingerprint)).fetchone()
    if not starter or starter["rider"] != row["rider_id"]:
        raise ValueError("unbound rider in window boundaries")
    if not movie or movie["kind"] not in ("clip", "full") or (scope == "whole_race" and movie["kind"] != "full"):
        raise ValueError("boundary source lacks the required movie coverage")
    begin, end = row["start_ms"], row["end_ms"]
    movie_begin, movie_end = json.loads(movie["receipt"])
    if type(begin) is not int or type(end) is not int or not movie_begin <= begin < end <= movie_end:
        raise ValueError("boundary outside verified movie")
    for old in db.execute("SELECT scope,begin_ms,end_ms FROM bounds WHERE race=? AND car=? AND source=? AND fingerprint=?",
                          (key, car, source, fingerprint)):
        if old["scope"] == scope:
            if (old["begin_ms"], old["end_ms"]) != (begin, end):
                raise ValueError("conflicting recorded boundaries")
        elif (end != old["end_ms"] or
              (scope == "whole_final_lap" and begin <= old["begin_ms"]) or
              (scope == "whole_race" and begin >= old["begin_ms"])):
            raise ValueError("recorded race and final-lap boundaries disagree")
    db.execute("INSERT OR IGNORE INTO bounds VALUES(?,?,?,?,?,?,?,?)",
               (key, car, scope, source, fingerprint, begin, end, pack(row)))


def check_interval(db, key, row):
    start, end = row["start_ms"], row["end_ms"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("invalid observation interval")
    film = row.get("media_sha256")
    if film is not None and not sha(film):
        raise ValueError("invalid video fingerprint")
    media = db.execute(
        "SELECT * FROM media WHERE race=? AND source=? AND fingerprint=?",
        (key, row["source_ref"], film or "frames"),
    ).fetchone()
    if not media:
        raise ValueError(f"no matching verified film: {key}")
    receipt = json.loads(media["receipt"])
    if film:
        if not receipt[0] <= start < end <= receipt[1]:
            raise ValueError("annotation outside verified movie")
        if row["window_level"] == "whole_race" and media["kind"] != "full":
            raise ValueError("whole-race label requires a full replay")
        if row["window_level"] in WHOLE_SCOPES and row["value"] != "unknown":
            bounds = db.execute(
                "SELECT begin_ms,end_ms FROM bounds WHERE race=? AND car=? AND scope=? AND source=? AND fingerprint=?",
                (key, row["car"], row["scope"], row["source_ref"], film)).fetchone()
            if not bounds or not start <= bounds["begin_ms"] < bounds["end_ms"] <= end:
                raise ValueError("review must cover both independently recorded boundaries for this rider")
        return
    if row["window_level"] != "clip":
        raise ValueError(
            "discrete frames only support clip-window observations"
        )
    if row["value"] in ("no_attack", "no_target"):
        raise ValueError("an observed absence requires continuous playback")
    frames = row["evidence_frames"]
    times = [f["at_ms"] for f in frames]
    if (
        len(times) < 2
        or times != sorted(set(times))
        or times[0] != start
        or times[-1] != end
        or any(type(t) is not int for t in times)
        or (row["value"] != "unknown" and len({f["sha256"] for f in frames}) < 2)
        or any(receipt.get(str(f["at_ms"])) != f["sha256"] for f in frames)
    ):
        raise ValueError("frame hashes/clock do not match the verified interval")


def load_review(db, row):
    from scripts.keirin_video_rider_learning import ATTACK_PHASES, LEVELS, TARGETED_FOLLOW, label_values

    key = census_key(db, row)
    car, task, scope, level, value = (
        row[k] for k in ("car", "task", "scope", "window_level", "value")
    )
    if scope not in ATTACK_PHASES or level not in LEVELS:
        raise ValueError("unknown review window")
    if any(
        (scope == whole) != (level == whole)
        for whole in ("whole_final_lap", "whole_race")
    ):
        raise ValueError("incompatible scope and window level")
    known = value != "unknown"
    if task not in ("attack", "follow") or (
        known and value not in label_values(task, scope)
    ):
        raise ValueError("unknown observation type")
    roster = dict(db.execute("SELECT car,rider FROM starter WHERE race=?", (key,)))
    if not valid_car(car) or not roster.get(car) or row["rider_id"] != roster[car]:
        raise ValueError(f"unbound reviewed rider: {key}/{car}")
    target = row.get("target_car")
    if task == "follow" and value in TARGETED_FOLLOW:
        if (
            not valid_car(target)
            or target == car
            or not roster.get(target)
            or roster[target] != row.get("target_rider_id")
        ):
            raise ValueError("unbound followed rider")
    elif target is not None or row.get("target_rider_id") is not None:
        raise ValueError("unexpected follow target")
    for field in ("source_ref", "reviewer", "note") + (() if known else ("reason",)):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"missing review {field}")
    check_interval(db, key, row)
    signature = (key, car, task, scope, level)
    old = db.execute(
        "SELECT entry,known FROM eligible_review WHERE (race,car,task,scope,level)=(?,?,?,?,?)",
        signature,
    ).fetchone()
    if old and old["known"] and known:
        first = json.loads(old["entry"])
        if first["value"] != value or first.get("target_car") != target:
            raise ValueError(f"conflicting labels require adjudication: {signature}")
    encoded = pack(row)
    db.execute("INSERT OR IGNORE INTO review_history VALUES(?)", (encoded,))
    if old is None or (known and not old["known"]):
        db.execute(
            "INSERT OR REPLACE INTO review VALUES(?,?,?,?,?,?,?)",
            (*signature, encoded, known),
        )


def census_rows(db):
    """Stream the entire merged field, including races without any known rider."""
    joined = db.execute("""SELECT r.id, r.day, s.car, s.rider
                           FROM race r LEFT JOIN starter s ON s.race = r.id
                           ORDER BY r.id,s.car""")
    for (key, day), rows in groupby(joined, lambda row: (row["id"], row["day"])):
        yield {
            "race_id": key,
            "race_date": day,
            "riders": [
                {"car": row["car"], "rider_id": row["rider"]}
                for row in rows
                if row["car"] is not None
            ],
        }


def training_rows(db):
    for row in db.execute(
        "SELECT entry FROM eligible_review ORDER BY race,car,task,scope,level"
    ):
        yield json.loads(row["entry"])


def report(db):
    aggregate = db.execute("""SELECT count(*) races,min(day) first_race_date,max(day) last_race_date,
        coalesce(sum(starters),0) roster_rows, coalesce(sum(registered),0) roster_rows_with_id,
        count(CASE WHEN complete_roster=1 THEN 1 END) verified_rosters,
        count(CASE WHEN has_media THEN 1 END) races_with_verified_visual_evidence,
        count(CASE WHEN seen_starts>0 THEN 1 END) races_with_readable_starter,
        coalesce(sum(seen_starts),0) readable_starter_starts,
        count(CASE WHEN complete_roster AND starters>0 AND whole_starts=starters THEN 1 END) full_races,
        count(CASE WHEN complete_roster AND starters>0 AND lap_starts=starters THEN 1 END) full_field_final_lap_races
        FROM coverage""").fetchone()
    return {
        **dict(aggregate),
        "rider_ids": db.execute("SELECT count(DISTINCT rider) FROM starter").fetchone()[
            0
        ],
        "readable_rider_ids": db.execute(
            "SELECT count(DISTINCT s.rider) FROM starter s JOIN eligible_review v ON s.race=v.race AND s.car=v.car WHERE v.known"
        ).fetchone()[0],
        "continuous_media_races": db.execute(
            "SELECT count(DISTINCT race) FROM media WHERE kind IN ('full','clip')"
        ).fetchone()[0],
        "owner_declared_full_replay_races": db.execute(
            "SELECT count(DISTINCT race) FROM media WHERE kind='full'"
        ).fetchone()[0],
        "whole_window_bounds": db.execute("SELECT count(*) FROM bounds").fetchone()[0],
        "known_reviews_awaiting_valid_evidence": db.execute(
            "SELECT (SELECT count(*) FROM review) - (SELECT count(*) FROM eligible_review)").fetchone()[0],
        "unresolved_reviews": db.execute(
            "SELECT count(*) FROM review WHERE NOT known"
        ).fetchone()[0],
        "observations": dict(
            db.execute("SELECT task,count(*) FROM eligible_review WHERE known GROUP BY task")
        ),
        "by_month": [
            dict(month)
            for month in db.execute("""SELECT substr(day,1,7) AS month, count(*) AS races,
                sum(has_media) AS races_with_visual_evidence,
                count(CASE WHEN seen_starts>0 THEN 1 END) AS races_with_readable_starter,
                sum(seen_starts) AS readable_starter_starts
                FROM coverage GROUP BY substr(day,1,7) ORDER BY month""")
        ],
        "outcomes": dict(
            db.execute("SELECT event_status,count(*) FROM race GROUP BY event_status")
        ),
    }


def pending(db, *, stage=None, after="", limit=-1):
    # Resume by ordered race ID within a stage. Retrying without a cursor includes newly enriched rows.
    # Continuous acquisition also includes races for which only isolated frames exist.
    rows = db.execute(
        """SELECT id AS race_id,day AS race_date,url AS race_detail_url,starters,registered,
        seen_starts,starters-whole_starts AS open_starters,
        CASE WHEN :stage='identify' THEN 'identify' WHEN :stage='continuous' THEN 'continuous' WHEN NOT has_media THEN 'source'
             WHEN registered=0 THEN 'identify' ELSE 'review' END AS stage
        FROM coverage WHERE id>:after AND event_status!='cancelled_reported'
        AND NOT(complete_roster AND starters>0 AND whole_starts=starters)
        AND (:stage IS NOT 'continuous' OR NOT EXISTS(SELECT 1 FROM media m WHERE m.race=id AND m.kind IN ('clip','full')))
        AND (:stage IS NOT 'identify' OR NOT complete_roster OR registered<starters OR starters=0)
        AND (:stage IS NULL OR stage=:stage) ORDER BY id LIMIT :limit""",
        {"after": after, "stage": stage, "limit": limit},
    )
    yield from map(dict, rows)


def input_rows(path):
    with path.open(encoding="utf-8") as handle:
        for i, line in enumerate(handle, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as error:
                    raise ValueError(f"{path.name} line {i}: invalid JSON") from error


@contextmanager
def output_file(path):
    if path is None:
        yield sys.stdout
        return
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        tmp = Path(handle.name)
        try:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    add = commands.add_parser("ingest")
    for name in ("census", "media", "review"):
        add.add_argument("--" + name, type=Path, action="append", default=[])
    add.add_argument("--bounds", type=Path, action="append", default=[],
                     help="Private JSONL of independently observed, per-rider H-to-goal/start-to-goal boundaries")
    commands.add_parser("status")
    fit = commands.add_parser(
        "study", help="Score and refit the full private ledger by race day"
    )
    fit.add_argument("--profiles", type=Path, required=True)
    fit.add_argument("--report", type=Path, required=True)
    fit.add_argument(
        "--before", help="Use race days strictly before this JST calendar date"
    )
    export = commands.add_parser("labels")
    queue = commands.add_parser("queue")
    for cmd in (export, queue):
        cmd.add_argument("--out", type=Path, required=True)
    queue.add_argument(
        "--stage", choices=("source", "identify", "review", "continuous")
    )
    queue.add_argument("--after", default="")
    queue.add_argument("--limit", type=int, default=-1)
    args = parser.parse_args()
    os.umask(0o077)
    if (
        args.action == "study"
        and len({p.resolve() for p in (args.db, args.profiles, args.report)}) != 3
    ):
        parser.error("ledger, profiles and report require distinct paths")
    if getattr(args, "out", None) and args.out.resolve() == args.db.resolve():
        parser.error("output must differ from ledger")
    if args.action != "ingest" and not args.db.is_file():
        parser.error("existing ledger required")
    with sqlite3.connect(args.db, timeout=60) as db:
        setup(db)
        if args.action == "ingest":
            for fn, paths in (
                (load_race, args.census),
                (load_media, args.media),
                (load_bounds, args.bounds),
                (load_review, args.review),
            ):
                for path in paths:
                    for i, row in enumerate(input_rows(path), 1):
                        try:
                            fn(db, row)
                        except (
                            ValueError,
                            KeyError,
                            TypeError,
                            sqlite3.IntegrityError,
                        ) as error:
                            raise ValueError(
                                f"{path.name} record {i}: {error}"
                            ) from error
        elif args.action == "study":
            from scripts.keirin_video_rider_learning import study, write_outputs

            db.execute("BEGIN")
            result, profiles = study(
                census_rows(db), training_rows(db), before=args.before
            )
            write_outputs(
                result, profiles, profiles_path=args.profiles, report_path=args.report
            )
        elif args.action == "status":
            print(json.dumps(report(db), indent=2))
        else:
            rows = (
                training_rows(db)
                if args.action == "labels"
                else pending(db, stage=args.stage, after=args.after, limit=args.limit)
            )
            with output_file(args.out) as handle:
                for row in rows:
                    handle.write(pack(row) + "\n")


if __name__ == "__main__":
    main()
