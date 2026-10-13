"""Persistent metadata-only official daily audit journal (no race content).

SQLite path MUST be durable persistent storage. CI temp path is ephemeral;
an uploaded Actions artifact is NOT a permanent database.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import date,datetime,timezone
from pathlib import Path
from .core import SourceError,utc

SCHEMA="""
CREATE TABLE IF NOT EXISTS daily_snapshots(
  day TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  venue_count INTEGER NOT NULL,
  race_count INTEGER NOT NULL,
  boat_count INTEGER NOT NULL,
  verification_status TEXT NOT NULL,
  metadata_sha256 TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY(day,source_kind,source_sha256)
);
"""


def append_report(db:sqlite3.Connection, report:dict)->dict:
    day=str(report.get("day_jst",""))
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise SourceError("invalid report day") from exc
    kind=report.get("source_kind")
    if kind!="OFFICIAL_B":
        raise SourceError("only official B motor report can enter this journal")
    digest=report.get("archive_sha256")
    if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise SourceError("official B source hash required")
    if report.get("status")!="OFFICIAL_B_MOTOR_COLUMNS_STRUCTURAL_CHECK_ONLY":
        raise SourceError("unexpected validation status")
    observed=utc(report.get("verified_at"))
    count=report.get("assigned_boat_rows")
    races=report.get("races")
    venues=report.get("venues")
    if any(type(x) is not int or x<=0 for x in (count,races,venues)) or count!=6*races or venues>24:
        raise SourceError("inconsistent day counts")
    # Only selected non-sensitive facts from official file, not full boats.
    canonical=json.dumps({
        "day":day,"kind":kind,"hash":digest,"observed_at":observed,
        "venues":venues,"races":races,"boats":count,"status":report["status"]
    },ensure_ascii=False,sort_keys=True).encode()
    metadata_sha=hashlib.sha256(canonical).hexdigest()
    db.execute(SCHEMA.replace("\n","\n")) if False else None
    db.executescript(SCHEMA)
    existing=db.execute("""SELECT metadata_sha256 FROM daily_snapshots
             WHERE day=? AND source_kind=? AND source_sha256=?""",
             (day,kind,digest)).fetchone()
    if existing and existing[0]!=metadata_sha:
        raise SourceError("same official source hash has conflicting metadata")
    with db:
        db.execute("""INSERT OR IGNORE INTO daily_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)""",
           (day,kind,digest,observed,venues,races,count,report["status"],
            metadata_sha,datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return dict(day_jst=day,source_sha256=digest,stored=True,immutable=True)


def journal_report(db:sqlite3.Connection)->dict:
    db.executescript(SCHEMA)
    rows=[dict(day_jst=r[0],kind=r[1],source_sha256=r[2],
               observed_at=r[3],venues=r[4],races=r[5],boat_rows=r[6],
               verification_status=r[7]) for r in db.execute("""SELECT day,source_kind,source_sha256,
                 observed_at,venue_count,race_count,boat_count,verification_status
                 FROM daily_snapshots ORDER BY day,observed_at""")]
    days=sorted({r['day_jst'] for r in rows})
    return dict(stored_days=len(days),dates=days,
        actual_scheduled_job_days_verified=0,
        status="METADATA_SNAPSHOTS_ONLY_NOT_LIVE_DAILY_OPERATION",
        note="Two distinct dates imported in one job do not prove two daily scheduled runs.",
        rows=rows)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",required=True)
    p.add_argument("--record",action="append",required=True,
                  help="file with official B derived metadata (can repeat)")
    p.add_argument("--output",default="motor-journal-status.json")
    a=p.parse_args()
    with sqlite3.connect(a.db) as db:
        for path in a.record:
            append_report(db,json.loads(Path(path).read_text(encoding="utf-8")))
        result=journal_report(db)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
