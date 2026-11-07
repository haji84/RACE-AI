"""Opt-in short-lived encrypted cache with global durable request reservations.

No scheduled caller, production key generation, plaintext export or automatic
reinitialization. Keep the DB outside the checkout; restore it before any GET.
Three GETs per JST day is our conservative cap, NOT a published numeric quota.
No inline retries. All processes must share this ledger (cross-run restore and
concurrency are deployment gates). Existing prediction stores are untouched.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .permissioned_source_delivery import NoRedirect
from .source_retry_policy import SourceWait, plan_http_wait, wait_active
from .teiai_history import BASE, MAX_BYTES, need

JST=timezone(timedelta(hours=9))
URL_PATTERN=re.compile(re.escape(BASE)+r'/api/(?:racer/[0-9]{4}/(?:results/)?|race/[0-9]{8}/(?:0[1-9]|1[0-9]|2[0-4])/(?:[1-9]|1[0-2])/)$')
SCHEMA='TEIAI_PRIVATE_CACHE_V1'


def _time(value):
    t=datetime.fromisoformat(value.replace('Z','+00:00'))
    need(t.utcoffset() is not None,'TEIAI_CLOCK_INVALID');return t


def _location(path):
    path=Path(path).resolve()
    need(not any((p/'.git').exists() for p in path.parents),'TEIAI_CACHE_MUST_BE_OUTSIDE_REPOSITORY')
    return path


class HistoryCache:
    @classmethod
    def initialize(cls,path,key,*,clock=None):
        """Explicit one-time setup only. Never call to recover missing state."""
        path=_location(path);need(type(key) is bytes and len(key)==32,'TEIAI_STATE_KEY_REQUIRED')
        # Exclusive create prevents concurrent initializers resetting a ledger.
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        now=(clock or (lambda:datetime.now(timezone.utc)))()
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE meta(schema TEXT NOT NULL, expires_at TEXT NOT NULL, auth TEXT NOT NULL);
                CREATE TABLE attempts(id INTEGER PRIMARY KEY, at TEXT NOT NULL, day TEXT NOT NULL,
                  url TEXT NOT NULL, status TEXT NOT NULL, wait_json TEXT);
                CREATE TABLE versions(id INTEGER PRIMARY KEY, url TEXT NOT NULL, captured_at TEXT NOT NULL,
                  sha TEXT NOT NULL, payload BLOB NOT NULL);
            ''')
            db.execute('INSERT INTO meta VALUES (?,?,?)',(SCHEMA,(now+timedelta(days=7)).isoformat(),''))
            auth_key=hmac.digest(key,b'TEIAI_PRIVATE_CACHE_LEDGER_V1','sha256')
            db.execute('UPDATE meta SET auth=?',(cls._signature(db,auth_key),))
        return cls(path,key,clock=clock)

    def __init__(self,path,key,*,clock=None):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.path=_location(path)
        need(self.path.is_file() and type(key) is bytes and len(key)==32,'TEIAI_EXISTING_CACHE_AND_KEY_REQUIRED')
        self.aes=AESGCM(key);self.auth_key=hmac.digest(key,b'TEIAI_PRIVATE_CACHE_LEDGER_V1','sha256');self.clock=clock or (lambda:datetime.now(timezone.utc))

    @staticmethod
    def _signature(db,key):
        # Bind quota, retention, reservations and every encrypted revision, not
        # just the URL requested next. Local HMAC cannot detect rollback to an
        # older authentic whole-DB backup; independent handoff proof is required.
        mac=hmac.new(key,digestmod='sha256')
        for query in ('SELECT schema,expires_at FROM meta',
                      'SELECT id,at,day,url,status,wait_json FROM attempts ORDER BY id',
                      'SELECT id,url,captured_at,sha,payload FROM versions ORDER BY id'):
            mac.update(query.encode())
            for row in db.execute(query):
                values=[hashlib.sha256(v).hexdigest() if isinstance(v,bytes) else v for v in row]
                mac.update(json.dumps(values,separators=(',',':')).encode());mac.update(b'\n')
        return mac.hexdigest()

    @contextmanager
    def _db(self):
        # mode=rw prevents a missing handoff from becoming an empty DB.
        db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                db.execute('BEGIN IMMEDIATE')
                need(db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'TEIAI_CACHE_CORRUPT')
                signed=db.execute('SELECT auth FROM meta').fetchall()
                need(len(signed)==1 and hmac.compare_digest(signed[0][0],self._signature(db,self.auth_key)),
                     'TEIAI_CACHE_AUTHENTICATION_FAILED')
                yield db
                db.execute('UPDATE meta SET auth=?',(self._signature(db,self.auth_key),))
        finally:db.close()

    def _read(self,row,url,at):
        from cryptography.exceptions import InvalidTag
        _,captured,sha,payload=row
        try:
            doc=json.loads(self.aes.decrypt(payload[:12],payload[12:],(url+'|'+captured+'|'+sha).encode()))
            raw=base64.b64decode(doc['raw'],validate=True)
            need(hashlib.sha256(raw).hexdigest()==sha and doc['source_url']==url
                 and doc['captured_at']==captured and _time(captured)<=_time(doc['save_started_at'])<=at,
                 'TEIAI_CACHE_HASH_OR_CLOCK_INVALID')
        except (InvalidTag,ValueError,KeyError,TypeError,UnicodeError) as exc:
            raise ValueError('TEIAI_CACHE_AUTHENTICATION_FAILED') from exc
        doc['raw']=raw
        # Conservative availability observation on authenticated cache read.
        doc['stored_at']=self.clock().isoformat()
        return doc

    def fetch(self,url,*,allow_source,opener=None,opener_override=None,refresh=False):
        need(type(url) is str and URL_PATTERN.fullmatch(url),'TEIAI_ENDPOINT_NOT_ALLOWED')
        need(callable(allow_source) and all(allow_source(url,p) is True
             for p in ('collection','private_storage','analysis')),'TEIAI_SOURCE_RIGHTS_REQUIRED')
        at=self.clock();need(at.utcoffset() is not None,'TEIAI_CLOCK_INVALID')
        try:
            with self._db() as db:
                meta=db.execute('SELECT * FROM meta').fetchall()
                need(len(meta)==1 and meta[0][0]==SCHEMA,'TEIAI_CACHE_SCHEMA_INVALID')
                need(at<_time(meta[0][1]),'TEIAI_RETENTION_REVIEW_REQUIRED')
                latest=db.execute('SELECT id,captured_at,sha,payload FROM versions WHERE url=? ORDER BY id DESC LIMIT 1',(url,)).fetchone()
                if latest:
                    doc=self._read(latest,url,at)
                    if not refresh:return doc
                previous=db.execute('SELECT status,wait_json FROM attempts ORDER BY id DESC LIMIT 1').fetchone()
                if previous and previous[0]!='OK':
                    wait=json.loads(previous[1]);
                    if wait_active(wait,at):raise SourceWait(wait['reason'],wait['retry_at'],state=wait['state'])
                day=at.astimezone(JST).date().isoformat()
                count=db.execute('SELECT count(*) FROM attempts WHERE day=?',(day,)).fetchone()[0]
                if count>=3:
                    tomorrow=datetime.combine(at.astimezone(JST).date()+timedelta(days=1),datetime.min.time(),JST)
                    raise SourceWait('TEIAI_DAILY_LIMIT',tomorrow.isoformat(),state='RATE_LIMIT_WAIT')
                # A crashed in-flight request cannot be retried automatically.
                pending=plan_http_wait(403,{},at);pending['reason']='TEIAI_INTERRUPTED_REQUEST_REVIEW'
                request_id=db.execute('INSERT INTO attempts(at,day,url,status,wait_json) VALUES (?,?,?,?,?)',
                                     (at.isoformat(),day,url,'RESERVED',json.dumps(pending))).lastrowid
        except sqlite3.Error as exc:raise ValueError('TEIAI_CACHE_UNAVAILABLE') from exc
        client=opener_override or opener or build_opener(NoRedirect())
        try:
            with client.open(Request(url,headers={'User-Agent':'RACE-AI-personal-history-research/1',
                                                  'Accept':'text/csv, application/json'}),timeout=25) as res:
                need(res.status==200 and res.geturl()==url,'TEIAI_HTTP_RESPONSE_REJECTED')
                expected='text/csv' if url.endswith('/results/') else 'application/json'
                need(res.headers.get('Content-Type','').split(';')[0].strip().lower()==expected,'TEIAI_CONTENT_TYPE_CHANGED')
                raw=res.read(MAX_BYTES+1)
                need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES,'TEIAI_RESPONSE_SIZE_INVALID')
            captured=self.clock();stored=self.clock()
            need(at<=captured<=stored,'TEIAI_CLOCK_REGRESSION')
            sha=hashlib.sha256(raw).hexdigest()
            doc=dict(source_url=url,raw=base64.b64encode(raw).decode(),source_sha256=sha,
                     captured_at=captured.isoformat(),save_started_at=stored.isoformat(),published_at=None)
            nonce=os.urandom(12);cipher=nonce+self.aes.encrypt(nonce,json.dumps(doc).encode(),
                                                          (url+'|'+doc['captured_at']+'|'+sha).encode())
            with self._db() as db:
                db.execute('INSERT INTO versions(url,captured_at,sha,payload) VALUES (?,?,?,?)',
                           (url,doc['captured_at'],sha,cipher))
                db.execute('UPDATE attempts SET status=?, wait_json=NULL WHERE id=?',('OK',request_id))
            doc['raw']=raw;doc['stored_at']=self.clock().isoformat();return doc
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as exc:
            status=exc.code if isinstance(exc,HTTPError) else (None if isinstance(exc,(URLError,TimeoutError,OSError)) else 400)
            wait=plan_http_wait(status,getattr(exc,'headers',{}),self.clock())
            with self._db() as db:
                db.execute('UPDATE attempts SET status=?,wait_json=? WHERE id=?',('FAILED',json.dumps(wait),request_id))
            if isinstance(exc,ValueError):raise
            raise SourceWait(wait['reason'],wait['retry_at'],state=wait['state']) from None
