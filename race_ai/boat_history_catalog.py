"""Published official K inventory + bounded immutable monthly raw revisions.

No HTTP, no guessed endpoints, no model/state reset. Serialize each month only
through the existing AES-GCM checkpoint. Parse failures stay source gaps.
"""
from datetime import date
from html.parser import HTMLParser
import hashlib
import json
import re
import sqlite3

from .actions_contract import stamp
from .teiai_history import need,racer_number
from .boat_venue_history import VenueHistory
from .official_lzh_extract import extract_daily_lzh
from .teiai_official_reconciliation import official_day
from .source_retry_policy import wait_active

SCHEMA='RACE_AI_OFFICIAL_HISTORY_MONTH_V1'
MAX_DB=8*1024*1024


class _Fields(HTMLParser):
    def __init__(self,raw):
        super().__init__();self.months=[];self.days=[];self.feed(raw.decode('latin1'))
    def handle_starttag(self,tag,attrs):
        a={k.lower():v for k,v in attrs}
        if tag=='option' and re.fullmatch(r'[0-9]{6}',a.get('value') or ''):self.months.append(a['value'])
        if tag=='input' and (a.get('name') or '').upper()=='MDAY' and (a.get('type') or '').lower()=='radio':self.days.append(a.get('value'))


def _month(value):
    need(type(value) is str and re.fullmatch(r'[0-9]{6}',value),'HISTORY_MONTH_INVALID')
    return date(int(value[:4]),int(value[4:]),1)


def published_months(raw):
    need(type(raw) is bytes and 0<len(raw)<=200000,'HISTORY_MENU_SIZE_INVALID')
    need(re.search(rb'var\s+dir\s*=\s*[\'\"]/od2/K/[\'\"]',raw),'HISTORY_MENU_SOURCE_CHANGED')
    months=_Fields(raw).months
    need(months and len(months)==len(set(months)),'HISTORY_MENU_EMPTY_OR_DUPLICATE')
    for m in months:_month(m)
    return sorted(months)


def published_days(raw,*,month,not_after):
    d=_month(month);end=date.fromisoformat(not_after)
    need(type(raw) is bytes and 0<len(raw)<=200000,'HISTORY_MONTH_INDEX_SIZE_INVALID')
    expected=f'/od2/K/{month}/k{month[2:]}'.encode()
    need(re.search(rb'var\s+dir\s*=\s*[\'\"]'+re.escape(expected)+rb'[\'\"]',raw),'HISTORY_MONTH_INDEX_IDENTITY')
    days=_Fields(raw).days
    need(days and len(days)==len(set(days)),'HISTORY_DAY_INDEX_EMPTY_OR_DUPLICATE')
    found=[]
    for value in days:
        need(type(value) is str and re.fullmatch(r'[0-9]{2}',value),'HISTORY_DAY_VALUE_INVALID')
        actual=date(d.year,d.month,int(value))
        if actual<=end:found.append(actual.isoformat())
    return sorted(found)


class HistoryMonth:
    def __init__(self,*,month,index_raw,not_after,roster=()):
        self.month=month;days=published_days(index_raw,month=month,not_after=not_after)
        self.db=sqlite3.connect(':memory:');self.db.executescript('''
          PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF;
          CREATE TABLE meta(schema TEXT, month TEXT, not_after TEXT, index_raw BLOB, roster TEXT);
          CREATE TABLE expected(day TEXT PRIMARY KEY);
          CREATE TABLE archives(sha TEXT PRIMARY KEY, raw BLOB NOT NULL);
          CREATE TABLE observations(id INTEGER PRIMARY KEY, day TEXT NOT NULL REFERENCES expected(day),
            sha TEXT REFERENCES archives(sha), captured_at TEXT NOT NULL, state TEXT NOT NULL, reason TEXT, starts INTEGER);
          CREATE TABLE waits(id INTEGER PRIMARY KEY, document TEXT);
        ''')
        roster=sorted({racer_number(p) for p in roster})
        self.db.execute('INSERT INTO meta VALUES (?,?,?,?,?)',(SCHEMA,month,not_after,index_raw,json.dumps(roster)))
        self.db.executemany('INSERT INTO expected VALUES (?)',[(d,) for d in days]);self.db.commit()

    def _day(self,day):need(self.db.execute('SELECT 1 FROM expected WHERE day=?',(day,)).fetchone(),'HISTORY_UNLISTED_DAY')
    def _heads(self):
        return self.db.execute('SELECT day,sha,captured_at,state,reason,starts FROM observations o '
                               'WHERE id=(SELECT max(i.id) FROM observations i WHERE i.day=o.day) ORDER BY day').fetchall()

    def record(self,day,raw,*,captured_at):
        self._day(day);stamp(captured_at)
        need(type(raw) is bytes and 0<len(raw)<=16000000,'HISTORY_ARCHIVE_SIZE_INVALID')
        sha=hashlib.sha256(raw).hexdigest();last=self.db.execute('SELECT sha,captured_at FROM observations WHERE day=? ORDER BY id DESC LIMIT 1',(day,)).fetchone()
        if last and last[0]==sha:return False
        need(not last or stamp(last[1])<=stamp(captured_at),'HISTORY_OBSERVATION_CLOCK_REGRESSION')
        try:
            d=date.fromisoformat(day);parsed=official_day(extract_daily_lzh(raw,f'K{d:%y%m%d}.TXT'),day=day)
            state,reason,n='PARSED',None,len(parsed['rows'])
        except (ValueError,UnicodeError):state,reason,n='QUARANTINED','OFFICIAL_FORMAT_OR_SPECIAL_RESULT_UNSUPPORTED',0
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO archives VALUES (?,?)',(sha,raw))
            self.db.execute('INSERT INTO observations(day,sha,captured_at,state,reason,starts) VALUES (?,?,?,?,?,?)',(day,sha,captured_at,state,reason,n))
        return True

    def missing(self,day,*,captured_at,http_status):
        self._day(day);stamp(captured_at);need(http_status==404,'HISTORY_MISSING_REQUIRES_404')
        with self.db:self.db.execute('INSERT INTO observations(day,sha,captured_at,state,reason,starts) VALUES (?,NULL,?,?,?,0)',
                                    (day,captured_at,'MISSING','SOURCE_LISTED_BUT_404_NOT_PROVEN_NO_RACE'))

    def set_wait(self,document):
        with self.db:self.db.execute('INSERT INTO waits(document) VALUES (?)',(json.dumps(document) if document else None,))
    def active_wait(self,now):
        row=self.db.execute('SELECT document FROM waits ORDER BY id DESC LIMIT 1').fetchone()
        wait=json.loads(row[0]) if row and row[0] else None
        return wait if wait is not None and wait_active(wait,now) else None

    def pending(self):
        done={r[0] for r in self._heads()}
        return [d for (d,) in self.db.execute('SELECT day FROM expected ORDER BY day') if d not in done]

    def archives(self):
        for day,sha,captured,state,_,_ in self._heads():
            if state!='PARSED':continue
            raw=self.db.execute('SELECT raw FROM archives WHERE sha=?',(sha,)).fetchone()[0]
            need(hashlib.sha256(raw).hexdigest()==sha,'HISTORY_RAW_HASH_MISMATCH')
            yield dict(day=day,raw=raw,captured_at=captured,source_sha256=sha)

    def summary(self):
        heads=self._heads();states={s:sum(r[3]==s for r in heads) for s in ('PARSED','MISSING','QUARANTINED')}
        expected=self.db.execute('SELECT count(*) FROM expected').fetchone()[0]
        index_raw=self.db.execute('SELECT index_raw FROM meta').fetchone()[0]
        excluded=len(_Fields(index_raw).days)-expected
        return dict(schema=SCHEMA,month=self.month,listed_days=expected,parsed_days=states['PARSED'],
                    missing_days=states['MISSING'],quarantined_days=states['QUARANTINED'],pending_days=expected-len(heads),
                    revision_observations=self.db.execute('SELECT count(*) FROM observations').fetchone()[0],
                    unique_archive_bytes=self.db.execute('SELECT coalesce(sum(length(raw)),0) FROM archives').fetchone()[0],
                    excluded_listed_days=excluded,month_complete=expected>0 and states['PARSED']==expected and excluded==0,
                    all_available_period_complete=False,formal_backtest_eligible=False)

    def serialize(self):
        self.db.commit();raw=self.db.serialize();need(len(raw)<=MAX_DB,'HISTORY_MONTH_PARTITION_SIZE_LIMIT');return raw
    @classmethod
    def restore(cls,raw,*,expected_sha256,month):
        need(type(raw) is bytes and 16<=len(raw)<=MAX_DB and hashlib.sha256(raw).hexdigest()==expected_sha256
             and raw.startswith(b'SQLite format 3\0'),'HISTORY_MONTH_HASH_INVALID')
        obj=object.__new__(cls);obj.month=month;obj.db=sqlite3.connect(':memory:');obj.db.deserialize(raw)
        obj.db.execute('PRAGMA trusted_schema=OFF');obj.db.execute('PRAGMA foreign_keys=ON')
        need(obj.db.execute('PRAGMA quick_check').fetchall()==[('ok',)] and obj.db.execute('PRAGMA foreign_key_check').fetchall()==[], 'HISTORY_MONTH_DB_CORRUPT')
        need(obj.db.execute('SELECT schema,month FROM meta').fetchall()==[(SCHEMA,month)],'HISTORY_MONTH_SCOPE_MISMATCH')
        list(obj.archives());return obj
