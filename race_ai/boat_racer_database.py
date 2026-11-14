"""All-racer, source-versioned research SQLite. Default storage is memory only.

Serialize ONLY into the existing AES-GCM handoff for public GitHub storage.
Separate from forecast originals and model state. A fresh restore is available
only at its actual read time; it cannot establish historical publication.
"""
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
import sqlite3

from .actions_contract import stamp
from .teiai_history import need,racer_number
from .boat_racer_term import extract_term,parse_term,term_info
from .teiai_official_reconciliation import official_day
from .official_lzh_extract import extract_daily_lzh
from .official_archive_probe import official_url

SCHEMA='RACE_AI_ALL_BOAT_RACERS_V1'
MAX_DB=8*1024*1024
JST=timezone(timedelta(hours=9))
DDL='''
PRAGMA foreign_keys=ON;
PRAGMA trusted_schema=OFF;
CREATE TABLE meta(schema TEXT NOT NULL);
CREATE TABLE sources(id INTEGER PRIMARY KEY, sha TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
 logical_key TEXT NOT NULL, url TEXT NOT NULL, captured_at TEXT NOT NULL, raw BLOB NOT NULL);
CREATE TABLE racers(source_id INTEGER NOT NULL REFERENCES sources(id), racer_id TEXT NOT NULL,
 term TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(source_id,racer_id));
CREATE INDEX racer_lookup ON racers(racer_id,term);
CREATE TABLE courses(source_id INTEGER NOT NULL, racer_id TEXT NOT NULL, course INTEGER NOT NULL,
 document TEXT NOT NULL, PRIMARY KEY(source_id,racer_id,course),
 FOREIGN KEY(source_id,racer_id) REFERENCES racers(source_id,racer_id));
CREATE TABLE starts(source_id INTEGER NOT NULL REFERENCES sources(id), race_id TEXT NOT NULL,
 lane INTEGER NOT NULL, racer_id TEXT NOT NULL, document TEXT NOT NULL,
 PRIMARY KEY(source_id,race_id,lane));
CREATE INDEX history_lookup ON starts(racer_id,race_id);
'''


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


class RacerDatabase:
    def __init__(self,*,clock=None):
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.db=sqlite3.connect(':memory:');self.db.executescript(DDL)
        self.db.execute('INSERT INTO meta VALUES (?)',(SCHEMA,));self.db.commit()
        self.opened_at=self.clock();self.available={}
        for table in ('sources','racers','courses','starts'):
            for action in ('UPDATE','DELETE'):
                self.db.execute(f"CREATE TRIGGER immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'IMMUTABLE_SOURCE_HISTORY'); END")
        self.db.commit()

    def _source(self,raw,kind,key,url,captured_at):
        need(type(raw) is bytes,'RACER_SOURCE_BYTES_REQUIRED')
        need(stamp(captured_at)<=self.clock(),'RACER_SOURCE_FROM_FUTURE')
        sha=hashlib.sha256(raw).hexdigest()
        prior=self.db.execute('SELECT id,kind,logical_key,url FROM sources WHERE sha=?',(sha,)).fetchone()
        last=self.db.execute('SELECT id,captured_at FROM sources WHERE kind=? AND logical_key=? ORDER BY id DESC LIMIT 1',(kind,key)).fetchone()
        if prior:
            need(prior[1:]==(kind,key,url),'RACER_SOURCE_IDENTITY_CONFLICT')
            need(last[0]==prior[0] or stamp(captured_at)<stamp(last[1]),'RACER_REVERTING_REVISION_REVIEW_REQUIRED')
            return prior[0],False
        need(last is None or stamp(last[1])<=stamp(captured_at),'RACER_REVISION_CLOCK_REGRESSION')
        source_id=self.db.execute('INSERT INTO sources(sha,kind,logical_key,url,captured_at,raw) VALUES (?,?,?,?,?,?)',
                                 (sha,kind,key,url,captured_at,raw)).lastrowid
        return source_id,True

    def import_term(self,raw,*,term,source_url,captured_at):
        need(source_url==term_info(term)['source_url'],'RACER_TERM_URL_IDENTITY')
        rows=parse_term(extract_term(raw,term=term),term=term)
        with self.db:
            source_id,new=self._source(raw,'TERM',term,source_url,captured_at)
            if new:
                for row in rows:
                    self.db.execute('INSERT INTO racers VALUES (?,?,?,?)',(source_id,row['racer_id'],term,_json({k:v for k,v in row.items() if k!='courses'})))
                    self.db.executemany('INSERT INTO courses VALUES (?,?,?,?)',
                        [(source_id,row['racer_id'],c['course'],_json(c)) for c in row['courses']])
        self.available.setdefault(source_id,self.clock())
        return dict(source_sha256=hashlib.sha256(raw).hexdigest(),racer_count=len(rows),new_source=new)

    def import_results(self,raw,*,day,source_url,captured_at):
        d=date.fromisoformat(day);need(source_url==official_url(d,'K'),'RACER_K_URL_IDENTITY')
        parsed=official_day(extract_daily_lzh(raw,f'K{d:%y%m%d}.TXT'),day=day)
        need(d<=stamp(captured_at).astimezone(JST).date(),'RACER_K_FROM_FUTURE')
        with self.db:
            source_id,new=self._source(raw,'K',day,source_url,captured_at)
            if new:self.db.executemany('INSERT INTO starts VALUES (?,?,?,?,?)',
                [(source_id,r['race_id'],r['lane'],r['racer_id'],_json(r)) for r in parsed['rows']])
        self.available.setdefault(source_id,self.clock())
        return dict(source_sha256=hashlib.sha256(raw).hexdigest(),start_count=len(parsed['rows']),new_source=new)

    def _admit(self,source_id,as_of,allow_source):
        at=stamp(as_of);need(at>=self.opened_at and at>=self.available[source_id],'RACER_SAVED_OR_RESTORED_AFTER_AS_OF')
        url,captured=self.db.execute('SELECT url,captured_at FROM sources WHERE id=?',(source_id,)).fetchone()
        need(stamp(captured)<=at,'RACER_CAPTURE_AFTER_AS_OF')
        need(callable(allow_source) and allow_source(url,'OFFICIAL_DOWNLOAD_PERSONAL_RESEARCH','analysis') is True,
             'RACER_ANALYSIS_PERMISSION_REQUIRED')

    def _latest_sources(self,kind,as_of):
        at=stamp(as_of);need(at>=self.opened_at,'RACER_SAVED_OR_RESTORED_AFTER_AS_OF')
        latest={}
        for sid,key,captured in self.db.execute('SELECT id,logical_key,captured_at FROM sources WHERE kind=? ORDER BY id DESC',(kind,)):
            if key not in latest and stamp(captured)<=at and self.available[sid]<=at:latest[key]=sid
        return latest

    def lookup(self,racer_id,*,as_of,allow_source=None):
        racer_number(racer_id)
        sources=self._latest_sources('TERM',as_of)
        if not sources:return None
        source_id=sources[max(sources)]
        self._admit(source_id,as_of,allow_source)
        row=self.db.execute('SELECT document FROM racers WHERE source_id=? AND racer_id=?',(source_id,racer_id)).fetchone()
        if row is None:return None
        doc=json.loads(row[0])
        need(date.fromisoformat(doc['period_end'])<stamp(as_of).astimezone(JST).date(),'RACER_TERM_RESULTS_NOT_AVAILABLE')
        doc['courses']=[json.loads(r[0]) for r in self.db.execute('SELECT document FROM courses WHERE source_id=? AND racer_id=? ORDER BY course',(source_id,racer_id))]
        return doc

    def history(self,racer_id,*,before_day,as_of,allow_source=None):
        racer_number(racer_id);day=date.fromisoformat(before_day)
        need(day<=stamp(as_of).astimezone(JST).date(),'RACER_HISTORY_TARGET_AFTER_AS_OF')
        sources=self._latest_sources('K',as_of)
        rows=self.db.execute('SELECT t.source_id,t.document,s.logical_key FROM starts t JOIN sources s ON s.id=t.source_id '
                            'WHERE racer_id=? ORDER BY race_id',(racer_id,)).fetchall()
        result=[]
        for source_id,raw,source_day in rows:
            if date.fromisoformat(source_day)>=day or sources.get(source_day)!=source_id:continue
            self._admit(source_id,as_of,allow_source);result.append(json.loads(raw))
        return result

    def summary(self):
        def count(sql):return self.db.execute(sql).fetchone()[0]
        return dict(schema=SCHEMA,sources=count('SELECT count(*) FROM sources'),
            term_racers=count('SELECT count(*) FROM racers WHERE source_id=(SELECT id FROM sources WHERE kind=\'TERM\' ORDER BY logical_key DESC,id DESC LIMIT 1)'),
            term_versions=count('SELECT count(*) FROM racers'),course_rows=count('SELECT count(*) FROM courses'),
            history_starts=count('SELECT count(*) FROM starts'),history_racers=count('SELECT count(DISTINCT racer_id) FROM starts'),
            known_racer_ids=count('SELECT count(*) FROM (SELECT racer_id FROM racers UNION SELECT racer_id FROM starts)'),
            all_career_history_complete=False,current_active_registry_complete=False,
            formal_backtest_eligible=False,production_promoted=False)

    def serialize(self):
        self.db.commit();raw=self.db.serialize();need(len(raw)<=MAX_DB,'RACER_DB_SIZE_LIMIT');return raw

    @classmethod
    def restore(cls,raw,*,expected_sha256,clock=None):
        need(type(raw) is bytes and 16<=len(raw)<=MAX_DB and raw.startswith(b'SQLite format 3\0')
             and hashlib.sha256(raw).hexdigest()==expected_sha256,'RACER_DB_HASH_OR_SIZE_INVALID')
        restored=cls(clock=clock);restored.db.deserialize(raw)
        restored.db.execute('PRAGMA trusted_schema=OFF');restored.db.execute('PRAGMA foreign_keys=ON')
        need(restored.db.execute('PRAGMA quick_check').fetchall()==[('ok',)]
             and restored.db.execute('PRAGMA foreign_key_check').fetchall()==[]
             and restored.db.execute('SELECT schema FROM meta').fetchall()==[(SCHEMA,)],'RACER_DB_INTEGRITY_FAILED')
        restored.opened_at=restored.clock()
        restored.available={row[0]:restored.opened_at for row in restored.db.execute('SELECT id FROM sources')}
        return restored
