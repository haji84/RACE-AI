"""Private BOAT journal and bounded AES-256-GCM SQLite handoff.

Uses the same cryptography AESGCM primitive as teiai_collection. No HTTP,
automatic key creation, plaintext upload, missing-state reset or model switch.
Restore requires a separately pinned ciphertext hash and complete expected
scope; a self-written manifest alone is not an independent receipt.
"""
import base64
from contextlib import closing
import gzip
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import sqlite3
import tempfile

from .actions_contract import digest
from .boat_history_store import wire,instant
from .boat_history_comparison import load_pair,read_freeze_receipt,score_pair,verify_pair
from scripts.boat_history_collect import private_root,save

SCHEMA='RACE_AI_BOAT_PDCA_ENCRYPTED_SQLITE_V1'
REPOSITORY_ID='1416489937'
VERSION=61106
MAX_PLAIN=256*1024*1024
MAX_CIPHER=128*1024*1024
PUBLIC_FIXTURE_KEY=hashlib.sha256(b'RACE_AI_PUBLIC_SYNTHETIC_FIXTURE_KEY_V1_NOT_FOR_REAL_DATA').digest()


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def scope_for(mode,generation,previous_cipher_sha256=None):
    need(mode in ('synthetic','production') and type(generation) is int and generation>=1,'STATE_SCOPE_INVALID')
    need(previous_cipher_sha256 is None if generation==1 else
         type(previous_cipher_sha256) is str and re.fullmatch('[a-f0-9]{64}',previous_cipher_sha256),
         'STATE_PREVIOUS_GENERATION_REQUIRED')
    return dict(schema=SCHEMA,repository_id=REPOSITORY_ID,mode=mode,generation=generation,
                previous_cipher_sha256=previous_cipher_sha256)


def state_key(mode,key=None):
    if key is None and mode=='synthetic':return PUBLIC_FIXTURE_KEY
    if key is None:
        try:key=base64.b64decode(os.environ.get('RACE_AI_STATE_KEY',''),validate=True)
        except ValueError:key=None
    need(type(key) is bytes and len(key)==32,'OWNER_STATE_KEY_REQUIRED')
    if mode=='production':
        need(key!=PUBLIC_FIXTURE_KEY and len(set(key))>=8,'OWNER_STATE_KEY_REQUIRED_NOT_PUBLIC_FIXTURE')
    return key


def inflate(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as src:out=src.read(MAX_PLAIN+1)
    need(len(out)<=MAX_PLAIN,'STATE_DECOMPRESSED_BOUND_EXCEEDED')
    return out


def name_ok(name):
    p=PurePosixPath(name)
    need(type(name) is str and len(name)<=240 and not p.is_absolute() and
         all(v not in ('','..','.') for v in p.parts) and str(p)==name and '\\' not in name,
         'STATE_FILE_NAME_INVALID')


def sqlite_snapshot(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink(),'EXISTING_STATE_REQUIRED_NO_RESET')
    with tempfile.TemporaryDirectory(dir=path.parent,prefix='.sqlite-backup-') as d:
        target=Path(d)/'backup.sqlite';target.touch(mode=0o600)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:src.backup(dst)
        need(target.stat().st_size<=MAX_PLAIN,'STATE_DATABASE_BOUND_EXCEEDED')
        return target.read_bytes()


class PdcaState:
    @classmethod
    def create(cls,path,*,mode):
        scope_for(mode,1);path=Path(path).absolute();private_root(path.parent)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600);os.close(fd)
        with closing(sqlite3.connect(path)) as db:
            with db:
                db.executescript('''
                  CREATE TABLE meta(mode TEXT NOT NULL);
                  CREATE TABLE blobs(sha TEXT PRIMARY KEY,body BLOB NOT NULL);
                  CREATE TABLE files(name TEXT NOT NULL,sha TEXT NOT NULL,PRIMARY KEY(name,sha));
                  CREATE TABLE heads(name TEXT PRIMARY KEY,sha TEXT NOT NULL);
                  CREATE TABLE pairs(sha TEXT PRIMARY KEY,json_sha TEXT NOT NULL,receipt_sha TEXT NOT NULL);
                  CREATE TABLE results(race_id TEXT NOT NULL,captured_at TEXT NOT NULL,sha TEXT PRIMARY KEY,body TEXT NOT NULL,
                    UNIQUE(race_id,captured_at));
                  CREATE TABLE scores(pair_sha TEXT NOT NULL,result_sha TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(pair_sha,result_sha));
                ''')
                db.execute('INSERT INTO meta VALUES (?)',(mode,));db.execute(f'PRAGMA user_version={VERSION}')
        return cls(path)

    def __init__(self,path):
        path=Path(path).absolute()
        need(path.is_file() and not path.is_symlink(),'EXISTING_STATE_REQUIRED_NO_RESET')
        private_root(path.parent);need(not path.stat().st_mode&0o077,'PRIVATE_STATE_FILE_REQUIRED')
        self.path=path
        self.db=sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)
        try:
            need(self.db.execute('PRAGMA user_version').fetchone()==(VERSION,) and
                 self.db.execute('PRAGMA quick_check').fetchall()==[('ok',)],'STATE_SCHEMA_OR_INTEGRITY_INVALID')
            modes=self.db.execute('SELECT mode FROM meta').fetchall()
            need(len(modes)==1,'STATE_MODE_INVALID');self.mode=modes[0][0];scope_for(self.mode,1)
            self.verify_files()
        except Exception:self.db.close();raise

    def close(self):self.db.close()

    def verify_files(self):
        versions=set(self.db.execute('SELECT name,sha FROM files'))
        heads=dict(self.db.execute('SELECT name,sha FROM heads'))
        need(set(heads)=={name for name,_ in versions},'STATE_FILE_HEADS_INCOMPLETE')
        need(all((name,value) in versions for name,value in heads.items()),'STATE_FILE_HEAD_VERSION_MISMATCH')
        blobs={r[0] for r in self.db.execute('SELECT sha FROM blobs')}
        need(all(value in blobs for _,value in versions),'STATE_FILE_BLOB_MISSING')

    def _put(self,name,raw):
        name_ok(name);need(type(raw) is bytes and len(raw)<=MAX_PLAIN,'STATE_FILE_BOUND_EXCEEDED')
        ident=sha(raw)
        self.db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)',(ident,gzip.compress(raw,compresslevel=3,mtime=0)))
        self.db.execute('INSERT OR IGNORE INTO files VALUES (?,?)',(name,ident))
        self.db.execute('INSERT OR REPLACE INTO heads VALUES (?,?)',(name,ident))
        return ident

    def _get(self,ident):
        row=self.db.execute('SELECT body FROM blobs WHERE sha=?',(ident,)).fetchone()
        need(row is not None,'STATE_BLOB_MISSING');raw=inflate(row[0])
        need(sha(raw)==ident,'STATE_BLOB_HASH_MISMATCH');return raw

    def import_state(self,other):
        """Union an authenticated restored journal; preserve current heads.

        The caller authenticates the incoming checkpoint. No source permission
        or forecast admission is granted here. Conflicting immutable rows stop
        and roll back the whole import, including newly copied blobs/files.
        """
        need(isinstance(other,PdcaState) and self.mode==other.mode,'STATE_IMPORT_MODE_MISMATCH')
        self.verify_files();other.verify_files()
        for ident, in other.db.execute('SELECT sha FROM blobs'):other._get(ident)
        keys={'pairs':('sha',),'results':('sha',),'scores':('pair_sha','result_sha')}
        try:
            with self.db:
                for row in other.db.execute('SELECT * FROM blobs'):
                    self.db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)',row)
                self.db.executemany('INSERT OR IGNORE INTO files VALUES (?,?)',other.db.execute('SELECT * FROM files'))
                for table,columns in keys.items():
                    names=[v[1] for v in other.db.execute('PRAGMA table_info('+table+')')]
                    for row in other.db.execute('SELECT * FROM '+table):
                        values=tuple(row[names.index(k)] for k in columns)
                        old=self.db.execute('SELECT * FROM '+table+' WHERE '+' AND '.join(k+'=?' for k in columns),values).fetchone()
                        need(old is None or old==row,'STATE_IMPORT_IMMUTABLE_CONFLICT')
                        if old is None:self.db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',row)
                self.db.executemany('INSERT OR IGNORE INTO heads VALUES (?,?)',other.db.execute('SELECT * FROM heads'))
                self.verify_files()
        except sqlite3.IntegrityError:raise ValueError('STATE_IMPORT_IMMUTABLE_CONFLICT') from None
        return self.inventory()

    def retain_history(self,path,*,synthetic_fixture=False,captures=None):
        need(self.mode!='synthetic' or synthetic_fixture is True,'SYNTHETIC_HISTORY_FIXTURE_REQUIRED')
        raw=sqlite_snapshot(path)
        with self.db:
            self._put('history.sqlite',raw)
            if captures is not None:
                folder=Path(captures);private_root(folder)
                for p in sorted(folder.iterdir()):
                    need(not p.is_symlink() and p.is_file() and re.fullmatch(r'[BK][0-9]{8}(?:-[a-f0-9]{64}\.lzh|\.json)',p.name),
                         'STATE_CAPTURE_FILE_NOT_ALLOWED')
                    self._put('captures/'+p.name,p.read_bytes())

    def retain_pair(self,path):
        pair=load_pair(path);read_freeze_receipt(path,pair)
        need(self.mode!='synthetic' or all(pair[v]['snapshot']['scope']=='SYNTHETIC_ONLY' for v in ('baseline','history')),
             'SYNTHETIC_EXPORT_REFUSES_REAL_RESEARCH')
        raw=Path(path).read_bytes();receipt=Path(path).with_suffix('.receipt.json').read_bytes()
        ident=pair['pair_sha256'];old=self.db.execute('SELECT json_sha,receipt_sha FROM pairs WHERE sha=?',(ident,)).fetchone()
        need(old is None or old==(sha(raw),sha(receipt)),'STATE_PAIR_ORIGINAL_CONFLICT')
        with self.db:
            a=self._put(f'pairs/{ident}.json',raw);b=self._put(f'pairs/{ident}.receipt.json',receipt)
            self.db.execute('INSERT OR IGNORE INTO pairs VALUES (?,?,?)',(ident,a,b))
        return ident

    def retain_racers(self,path,*,synthetic_fixture=False):
        from .boat_racer_database import RacerDatabase
        need(self.mode!='synthetic' or synthetic_fixture is True,'SYNTHETIC_RACER_FIXTURE_REQUIRED')
        raw=sqlite_snapshot(path);verified=RacerDatabase.restore(raw,expected_sha256=sha(raw));verified.db.close()
        with self.db:self._put('racers.sqlite',raw)

    def score(self,pair_sha,observation,now):
        row=self.db.execute('SELECT json_sha FROM pairs WHERE sha=?',(pair_sha,)).fetchone()
        need(row is not None,'STATE_PAIR_NOT_FOUND');pair=verify_pair(json.loads(self._get(row[0])))
        need(observation['race_id']==pair['race_id'] and instant(observation['captured_at'])<=instant(now),'STATE_RESULT_IDENTITY_OR_TIME')
        body=wire(observation);ident=digest(observation);at=instant(observation['captured_at']).isoformat()
        # Validate result/cutoff/roster before retaining a scoring revision.
        score_pair(pair,observation,now)
        old=self.db.execute('SELECT sha FROM results WHERE race_id=? AND captured_at=?',(pair['race_id'],at)).fetchone()
        need(old is None or old[0]==ident,'STATE_RESULT_CAPTURE_CONFLICT')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO results VALUES (?,?,?,?)',(pair['race_id'],at,ident,body))
            selected=self.db.execute('SELECT sha,body FROM results WHERE race_id=? AND captured_at<=? ORDER BY captured_at DESC LIMIT 1',
                                     (pair['race_id'],instant(now).isoformat())).fetchone()
            ident=selected[0];report=score_pair(pair,json.loads(selected[1]),now)
            prior=self.db.execute('SELECT body FROM scores WHERE pair_sha=? AND result_sha=?',(pair_sha,ident)).fetchone()
            if prior is None:self.db.execute('INSERT INTO scores VALUES (?,?,?)',(pair_sha,ident,wire(report)))
            else:need(prior[0]==wire(report),'STATE_SCORE_REPLAY_CONFLICT')
        return dict(reused=prior is not None,result_revision_sha256=ident,report=report)

    def inventory(self):
        return dict(mode=self.mode,**{label:self.db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            for label,table in [('pairs','pairs'),('result_revisions','results'),('scorings','scores'),('retained_file_versions','files')]})

    def content_manifest(self):
        """Describe exact retained facts without exposing prediction/source bodies."""
        self.verify_files();blobs=[]
        for ident, in self.db.execute('SELECT sha FROM blobs ORDER BY sha'):
            self._get(ident)  # Also authenticate historical versions, not only heads.
            blobs.append(ident)
        rows=dict(schema=SCHEMA,mode=self.mode,blobs=blobs)
        for table,columns in (('files','name,sha'),('heads','name,sha'),('pairs','sha,json_sha,receipt_sha')):
            rows[table]=list(self.db.execute('SELECT '+columns+' FROM '+table+' ORDER BY '+columns))
        rows['results']=[(rid,at,ident,sha(body.encode())) for rid,at,ident,body in
            self.db.execute('SELECT race_id,captured_at,sha,body FROM results ORDER BY race_id,captured_at,sha')]
        rows['scores']=[(pair,result,sha(body.encode())) for pair,result,body in
            self.db.execute('SELECT pair_sha,result_sha,body FROM scores ORDER BY pair_sha,result_sha')]
        return rows

    def content_sha256(self):
        """Identify retained facts independent of SQLite layout or AEAD nonce."""
        return digest(self.content_manifest())

    def merge_from(self,source):
        """Append an authenticated frozen source, preserving existing active heads.

        Same logical filenames can denote different history databases. Every
        version remains retained; a source manifest preserves the incoming
        source's own head selection. This does not combine model inputs.
        Conflicting pair/capture/score identities stop instead of overwriting.
        """
        need(self is not source and self.mode==source.mode=='production','STATE_MERGE_PRODUCTION_REQUIRED')
        manifest=source.content_manifest();ident=digest(manifest)
        name='source-states/v1/'+ident+'/manifest.json'
        descriptor=(wire(dict(schema='RACE_AI_PDCA_SOURCE_V1',content_sha256=ident,content=manifest))+'\n').encode()
        with self.db:
            for key,body in source.db.execute('SELECT sha,body FROM blobs'):
                self.db.execute('INSERT OR IGNORE INTO blobs VALUES (?,?)',(key,body))
            for name_version,blob in source.db.execute('SELECT name,sha FROM files'):
                self.db.execute('INSERT OR IGNORE INTO files VALUES (?,?)',(name_version,blob))
            for table in ('pairs','results','scores'):
                existing=set(self.db.execute('SELECT * FROM '+table))
                for row in source.db.execute('SELECT * FROM '+table):
                    if row in existing:continue
                    try:self.db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in row)+')',row)
                    except sqlite3.IntegrityError:raise ValueError('STATE_MERGE_RECORD_CONFLICT_'+table.upper()) from None
                    existing.add(row)
            for filename,blob in source.db.execute('SELECT name,sha FROM heads'):
                self.db.execute('INSERT OR IGNORE INTO heads VALUES (?,?)',(filename,blob))
            prior=self.db.execute('SELECT sha FROM heads WHERE name=?',(name,)).fetchone()
            need(prior is None or prior==(sha(descriptor),),'STATE_MERGE_MANIFEST_CONFLICT')
            self._put(name,descriptor)
            self.verify_contribution(ident)
        return ident

    def verify_contribution(self,ident):
        need(type(ident) is str and re.fullmatch('[a-f0-9]{64}',ident),'STATE_SOURCE_ID_INVALID')
        name='source-states/v1/'+ident+'/manifest.json'
        row=self.db.execute('SELECT sha FROM heads WHERE name=?',(name,)).fetchone()
        need(row is not None,'STATE_SOURCE_MANIFEST_MISSING')
        raw=self._get(row[0]);need(len(raw)<=4*1024*1024,'STATE_SOURCE_MANIFEST_BOUND')
        descriptor=json.loads(raw);source=descriptor.get('content')
        need(set(descriptor)=={'schema','content_sha256','content'} and descriptor['schema']=='RACE_AI_PDCA_SOURCE_V1'
             and descriptor['content_sha256']==ident and digest(source)==ident and type(source) is dict,
             'STATE_SOURCE_MANIFEST_INVALID')
        current=self.content_manifest()
        need(set(source)==set(current) and source['schema']==SCHEMA and source['mode']==self.mode,
             'STATE_SOURCE_SCOPE_INVALID')
        for table in ('files','pairs','results','scores'):
            need({tuple(r) for r in source[table]}<={tuple(r) for r in current[table]},'STATE_SOURCE_RECORDS_MISSING')
        need(set(source['blobs'])<=set(current['blobs']),'STATE_SOURCE_BLOBS_MISSING')
        need({tuple(r) for r in source['heads']}<={tuple(r) for r in current['files']},'STATE_SOURCE_HEAD_VERSION_MISSING')
        return True

    def materialize(self,root):
        self.verify_files()
        root=private_root(root)
        for name,ident in self.db.execute('SELECT name,sha FROM heads ORDER BY name'):
            name_ok(name);p=root/name;private_root(p.parent);save(p,self._get(ident))

    def checkpoint(self,root,*,generation,previous_cipher_sha256=None,key=None):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        scope=scope_for(self.mode,generation,previous_cipher_sha256);key=state_key(self.mode,key)
        self.verify_files()
        raw=sqlite_snapshot(self.path);nonce=os.urandom(12)
        encrypted=AESGCM(key).encrypt(nonce,gzip.compress(raw,compresslevel=3,mtime=0),wire(scope).encode())
        envelope=(wire(dict(header=scope,nonce=base64.b64encode(nonce).decode(),ciphertext=base64.b64encode(encrypted).decode()))+'\n').encode()
        need(len(envelope)<=MAX_CIPHER,'STATE_CIPHERTEXT_BOUND_EXCEEDED')
        root=private_root(root);save(root/'state.enc',envelope)
        proof=dict(scope=scope,cipher_sha256=sha(envelope),synthetic_only=self.mode=='synthetic',plaintext_published=False)
        save(root/'proof.json',(wire(proof)+'\n').encode());return proof


def restore_state(cipher_path,output,*,expected_sha256,expected_scope,key=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cipher_path=Path(cipher_path);output=Path(output)
    need(not output.exists() and not output.is_symlink(),'STATE_RESTORE_MUST_NOT_OVERWRITE')
    need(cipher_path.is_file() and not cipher_path.is_symlink() and cipher_path.stat().st_size<=MAX_CIPHER,'STATE_CIPHER_BOUND_EXCEEDED')
    envelope=cipher_path.read_bytes();need(sha(envelope)==expected_sha256,'STATE_CIPHERTEXT_HASH_MISMATCH')
    scope=scope_for(expected_scope['mode'],expected_scope['generation'],expected_scope['previous_cipher_sha256'])
    need(scope==expected_scope,'STATE_EXPECTED_SCOPE_INVALID')
    try:
        doc=json.loads(envelope)
        need(set(doc)=={'header','nonce','ciphertext'} and doc['header']==scope,'STATE_SCOPE_MISMATCH')
        nonce=base64.b64decode(doc['nonce'],validate=True);cipher=base64.b64decode(doc['ciphertext'],validate=True)
        need(len(nonce)==12,'STATE_NONCE_INVALID')
        raw=inflate(AESGCM(state_key(scope['mode'],key)).decrypt(nonce,cipher,wire(scope).encode()))
    except ValueError:raise
    except Exception:raise ValueError('STATE_AUTHENTICATION_OR_COMPRESSION_FAILED') from None
    need(raw.startswith(b'SQLite format 3\0'),'STATE_SQLITE_REQUIRED')
    root=private_root(output.parent)
    with tempfile.TemporaryDirectory(dir=root,prefix='.state-restore-') as d:
        candidate=Path(d)/'verified.sqlite';save(candidate,raw)
        state=PdcaState(candidate)
        try:
            need(state.mode==scope['mode'],'STATE_DATABASE_MODE_MISMATCH')
            for ident, in state.db.execute('SELECT sha FROM blobs'):state._get(ident)
        finally:state.close()
        save(output,raw)
    return PdcaState(output)
