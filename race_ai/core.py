"""Offline import of official B/K extracted text and as-of-safe analytics.

No network fetch, video scraping, betting or unsourced mechanical labels.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS provenance (
 sha TEXT PRIMARY KEY, kind TEXT NOT NULL, file_name TEXT NOT NULL,
 published_at TEXT, captured_at TEXT NOT NULL, imported_at TEXT NOT NULL,
 verified_official INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS starts (
 race_id TEXT NOT NULL, lane INTEGER NOT NULL CHECK(lane BETWEEN 1 AND 6),
 racer_id TEXT NOT NULL, course INTEGER NOT NULL CHECK(course BETWEEN 1 AND 6),
 st REAL, st_status TEXT NOT NULL, finish INTEGER,
 race_at TEXT NOT NULL, published_at TEXT NOT NULL, captured_at TEXT NOT NULL,
 sha TEXT NOT NULL REFERENCES provenance(sha),
 PRIMARY KEY(race_id,lane,sha)
);
CREATE INDEX IF NOT EXISTS ix_starts_racer ON starts(racer_id,race_at);
CREATE TABLE IF NOT EXISTS programs (
 race_id TEXT NOT NULL, lane INTEGER NOT NULL, racer_id TEXT NOT NULL,
 published_at TEXT, captured_at TEXT NOT NULL, sha TEXT NOT NULL REFERENCES provenance(sha),
 PRIMARY KEY(race_id,lane,sha)
);
CREATE TABLE IF NOT EXISTS exhibition (
 race_id TEXT NOT NULL, lane INTEGER NOT NULL CHECK(lane BETWEEN 1 AND 6),
 metric TEXT NOT NULL CHECK(metric IN ('display','lap','turn','straight','start_exhibition')),
 value REAL, missing_reason TEXT,
 published_at TEXT, captured_at TEXT NOT NULL, sha TEXT NOT NULL REFERENCES provenance(sha),
 PRIMARY KEY(race_id,lane,metric,captured_at,sha),
 CHECK ((value IS NULL) != (missing_reason IS NULL))
);
CREATE TABLE IF NOT EXISTS entry_evidence (
 event_id TEXT PRIMARY KEY, race_id TEXT NOT NULL,
 challenger TEXT NOT NULL, defender TEXT NOT NULL,
 event_type TEXT NOT NULL CHECK(event_type IN ('attempt','resistance','displacement','deep_inside')),
 outcome TEXT CHECK(outcome IN ('yes','no','unknown')),
 evidence_level TEXT NOT NULL CHECK(evidence_level IN ('HUMAN_REVIEWED','VERIFIED_VIDEO','UNKNOWN')),
 clip_ref TEXT, reviewer TEXT, rights_confirmed INTEGER NOT NULL,
 published_at TEXT, captured_at TEXT NOT NULL, sha TEXT NOT NULL REFERENCES provenance(sha)
);
"""

class SourceError(ValueError):
    """Reject invalid/unproven data rather than silently fabricating history."""


def utc(value: str) -> str:
    """Canonical UTC timestamp, rejecting naive dates/times."""
    if not isinstance(value, str):
        raise SourceError('timestamp must be ISO-8601 with timezone')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise SourceError('invalid ISO timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SourceError('timezone required')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds')


def connect(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def source(db: sqlite3.Connection, kind: str, raw: bytes, name: str,
           published_at: str | None, captured_at: str, verified: bool = False) -> str:
    captured = utc(captured_at)
    published = utc(published_at) if published_at is not None else None
    if published is not None and published > captured:
        raise SourceError('published_at later than captured_at')
    digest = hashlib.sha256(raw).hexdigest()
    db.execute('INSERT OR IGNORE INTO provenance VALUES (?,?,?,?,?,?,?)',
               (digest, kind, name, published, captured,
                datetime.now(timezone.utc).isoformat(timespec='seconds'), int(verified)))
    return digest


def _decode(raw: bytes) -> str:
    try:
        return raw.decode('cp932')
    except UnicodeDecodeError as exc:
        raise SourceError('expected extracted CP932 B/K text, not LZH archive') from exc


def _race_id(day: str, venue: int, race_no: int) -> str:
    return f'{day.replace("-", "")}-{venue:02d}-{race_no:02d}'


def _blocks(text: str, kind: str):
    """Yield venue number plus its BGN/END block (K: xxKBGN, B: xxBBGN)."""
    pattern = re.compile(r'^\s*(\d{1,2})' + kind + r'BGN\s*$', re.MULTILINE)
    markers = list(pattern.finditer(text))
    if not markers:
        raise SourceError(f'no {kind}BGN blocks')
    for marker in markers:
        start = marker.end()
        end_match = re.search(r'^\s*(?:\d{1,2})?' + kind + r'END\s*$', text[start:], re.MULTILINE)
        if end_match is None:
            raise SourceError(f'unterminated {kind}BGN block')
        yield int(marker.group(1)), text[start:start + end_match.start()]


def _ensure_day(block: str, day: str) -> None:
    d = date.fromisoformat(day)
    # Headers are not uniform, but check full year when the standard K header appears.
    dates = re.findall(r'(20\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})', block[:1400])
    if dates and (d.year, d.month, d.day) not in [(int(y), int(m), int(n)) for y,m,n in dates]:
        raise SourceError('file header date does not match requested date')


def parse_k(raw: bytes, day: str) -> list[dict]:
    """Parse conservative six-boat records from official extracted K text."""
    text = _decode(raw)
    if 'STARTK' not in text[:200]:
        raise SourceError('not a K result text')
    output = []
    for venue, block in _blocks(text, 'K'):
        _ensure_day(block, day)
        race = None
        rows: list[dict] = []
        for line in block.splitlines() + ['99R H1800m']:
            header = re.match(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m', line, re.I)
            if header:
                if race is not None:
                    if len(rows) != 6 or {r['lane'] for r in rows} != set(range(1, 7)) or {r['course'] for r in rows} != set(range(1,7)):
                        raise SourceError(f'incomplete/nonunique result: {race}')
                    output.extend(rows)
                race = int(header.group(1))
                rows = []
                continue
            if race is None or not (1 <= race <= 12):
                continue
            # Official sample: 01  6 4034 name 56 47 6.82 5 0.09 1.50.3
            m = re.match(r'^\s*(\d{2}|F|L|欠|失|転|落|沈)\s+([1-6])\s+(\d{4})\s+.*?\s+\d{1,3}\s+\d{1,3}\s+\d\.\d{2}\s+([1-6])\s+((?:F|L)?(?:0?\.\d{2})|F|L|--)(?:\s|$)', line)
            if not m:
                continue
            rank, lane, racer_id, course, st_text = m.groups()
            status = 'OK' if re.fullmatch(r'0?\.\d{2}', st_text) else ('F' if st_text.startswith('F') else ('L' if st_text.startswith('L') else 'MISSING'))
            rows.append(dict(race_id=_race_id(day, venue, race), lane=int(lane), racer_id=racer_id,
                             course=int(course), st=float(st_text) if status == 'OK' else None,
                             st_status=status, finish=int(rank) if rank.isdecimal() else None,
                             race_at=day+'T00:00:00+00:00'))
    if not output:
        raise SourceError('no complete K race records')
    if len({(r['race_id'],r['lane']) for r in output}) != len(output):
        raise SourceError('duplicate K race entry')
    return output


def parse_b(raw: bytes, day: str) -> list[dict]:
    text = _decode(raw)
    if 'STARTB' not in text[:200]:
        raise SourceError('not a B program text')
    output = []
    for venue, block in _blocks(text, 'B'):
        _ensure_day(block, day)
        race = None
        race_rows: list[dict] = []
        for line in block.splitlines()+['99R H1800m']:
            header = re.match(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m', line, re.I)
            if header:
                if race is not None:
                    if len(race_rows)!=6 or {r['lane'] for r in race_rows}!=set(range(1,7)):
                        raise SourceError(f'incomplete B race: {venue}/{race}')
                    output.extend(race_rows)
                race=int(header.group(1)); race_rows=[]
                continue
            if race is None or not 1<=race<=12:
                continue
            m = re.match(r'^\s*([1-6])\s+(\d{4})(?!\d)',line)
            if m:
                lane, racer_id=m.groups()
                race_rows.append(dict(race_id=_race_id(day,venue,race),lane=int(lane),racer_id=racer_id))
    if not output:
        raise SourceError('no complete B program races')
    return output


def import_official(db: sqlite3.Connection, path: str | Path, kind: str,
                    day: str, published_at: str, captured_at: str) -> dict:
    if kind not in ('K','B'):
        raise SourceError('kind must be K or B')
    raw = Path(path).read_bytes()
    if raw[:2] == b'\x2d\x6c' or Path(path).suffix.lower()=='.lzh':
        raise SourceError('extract LZH safely to B/K .TXT first; never execute archives')
    records = parse_k(raw,day) if kind=='K' else parse_b(raw,day)
    with db:
        digest = source(db,kind,raw,Path(path).name,published_at,captured_at,True)
        for r in records:
            if kind=='K':
                db.execute('INSERT OR IGNORE INTO starts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (r['race_id'],r['lane'],r['racer_id'],r['course'],r['st'],r['st_status'],
                            r['finish'],r['race_at'],utc(published_at),utc(captured_at),digest))
            else:
                db.execute('INSERT OR IGNORE INTO programs VALUES (?,?,?,?,?,?)',
                           (r['race_id'],r['lane'],r['racer_id'],utc(published_at),utc(captured_at),digest))
    return dict(kind=kind,rows=len(records),sha256=digest,verified='header_and_structure_only')


def _asof_rows(db: sqlite3.Connection, asof: str, racer_id: str) -> list[sqlite3.Row]:
    cutoff=utc(asof)
    # exclude after-decision revisions; latest captured snapshot per (race, boat).
    return db.execute('''SELECT * FROM (
      SELECT s.*, ROW_NUMBER() OVER(PARTITION BY race_id,lane ORDER BY captured_at DESC,sha DESC) AS rn
      FROM starts s WHERE published_at<=? AND captured_at<=?
    ) WHERE rn=1 AND racer_id=? ORDER BY race_at DESC,race_id DESC''', (cutoff,cutoff,racer_id)).fetchall()


def summarize(rows: list[sqlite3.Row], count: int = 10) -> dict:
    selected=rows[:count]
    values=[r['st'] for r in selected if r['st_status']=='OK' and r['st'] is not None]
    return dict(requested=count,n=len(selected),valid_st=len(values),
                mean_st=round(mean(values),4) if values else None,
                median_st=round(median(values),4) if values else None,
                sd_st=round(pstdev(values),4) if values else None,
                first_rate=round(sum(r['finish']==1 for r in selected)/len(selected),4) if selected else None,
                top3_rate=round(sum(r['finish'] in (1,2,3) for r in selected)/len(selected),4) if selected else None,
                starts=[dict(race_id=r['race_id'],lane=r['lane'],course=r['course'],
                             st=r['st'],st_status=r['st_status'],finish=r['finish']) for r in selected])


def histories(db: sqlite3.Connection, racer_id: str, lane: int, course: int, asof: str) -> dict:
    if not re.fullmatch(r'\d{4}',racer_id) or lane not in range(1,7) or course not in range(1,7):
        raise SourceError('invalid racer/lane/course')
    rows=_asof_rows(db,asof,racer_id)
    return dict(racer_id=racer_id,asof=utc(asof),lane=lane,course=course,
                by_lane_10=summarize([r for r in rows if r['lane']==lane]),
                by_course_5=summarize([r for r in rows if r['course']==course],5),
                by_course_10=summarize([r for r in rows if r['course']==course],10),
                by_course_20=summarize([r for r in rows if r['course']==course],20),
                overall_10=summarize(rows))


def save_exhibition(db: sqlite3.Connection, payload: dict) -> dict:
    """Manual/licensed JSON feed only. Immutable snapshots with explicit provenance."""
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
    race_id=payload['race_id']
    published=payload.get('published_at')
    captured=utc(payload['captured_at'])
    metrics=payload['metrics']
    if not isinstance(metrics,list) or len(metrics)==0:
        raise SourceError('metrics must be a nonempty list')
    if not payload.get('rights_confirmed',False):
        raise SourceError('rights confirmation required for stored exhibition source')
    seen=set()
    for r in metrics:
        k=(r['lane'],r['metric'])
        if k in seen or r['lane'] not in range(1,7) or r['metric'] not in ('display','lap','turn','straight','start_exhibition'):
            raise SourceError('invalid/duplicate metric')
        seen.add(k)
        if (r.get('value') is None) == (r.get('missing_reason') is None):
            raise SourceError('value XOR missing_reason required')
        if r.get('value') is not None and (not math.isfinite(float(r['value'])) or float(r['value'])<0):
            raise SourceError('invalid measurement')
    with db:
        digest=source(db,'EXHIBITION',raw,payload.get('source_name','manual'),published,captured,False)
        for r in metrics:
            db.execute('INSERT OR IGNORE INTO exhibition VALUES (?,?,?,?,?,?,?,?)',
                       (race_id,r['lane'],r['metric'],r.get('value'),r.get('missing_reason'),
                        utc(published) if published else None,captured,digest))
    return dict(sha256=digest,rows=len(metrics))


def exhibition_asof(db: sqlite3.Connection, race_id: str, asof: str) -> list[dict]:
    cutoff=utc(asof)
    rows=db.execute('''SELECT * FROM (
       SELECT *,ROW_NUMBER() OVER(PARTITION BY lane,metric ORDER BY captured_at DESC,sha DESC) AS rn
       FROM exhibition WHERE race_id=? AND published_at IS NOT NULL
       AND published_at<=? AND captured_at<=?
    ) WHERE rn=1 ORDER BY lane,metric''',(race_id,cutoff,cutoff)).fetchall()
    return [dict(r) for r in rows]


def record_entry_evidence(db:sqlite3.Connection, payload:dict)->str:
    if not payload.get('rights_confirmed') or not payload.get('clip_ref') or not payload.get('reviewer'):
        raise SourceError('rights, clip_ref and reviewer required for factual entry-event labels')
    if payload.get('evidence_level') not in ('HUMAN_REVIEWED','VERIFIED_VIDEO'):
        raise SourceError('no inferred front-running labels')
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()
    published=payload.get('published_at')
    with db:
        digest=source(db,'ENTRY_VIDEO',raw,payload.get('source_name','annotated_video'),published,payload['captured_at'])
        db.execute('INSERT OR IGNORE INTO entry_evidence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            payload['event_id'],payload['race_id'],payload['challenger'],payload['defender'],
            payload['event_type'],payload.get('outcome','unknown'),payload['evidence_level'],
            payload['clip_ref'],payload['reviewer'],1,utc(published) if published else None,
            utc(payload['captured_at']),digest))
    return digest


def pair_summary(db:sqlite3.Connection, challenger:str, defender:str, asof:str)->dict:
    cutoff=utc(asof)
    rows=db.execute('''SELECT * FROM entry_evidence WHERE challenger=? AND defender=?
       AND published_at IS NOT NULL AND published_at<=? AND captured_at<=?
       AND event_type='attempt' AND outcome IN ('yes','no')''',
       (challenger,defender,cutoff,cutoff)).fetchall()
    n=len(rows)
    success=sum(r['outcome']=='yes' for r in rows)
    # Conservative prior is an illustrative uniform Beta(1,1), not empirically calibrated.
    return dict(challenger=challenger,defender=defender,n=n,observed_rate=success/n if n else None,
                smoothed_rate=(success+1)/(n+2),exploratory=n<10,prior='Beta(1,1); not calibrated')
