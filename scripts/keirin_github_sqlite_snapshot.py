"""Consistent SQLite snapshots for encrypted GitHub handoff. No cloud dependency."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat

MAX_BYTES=8*1024*1024
class SnapshotError(ValueError):pass

def _source(path):
    p=Path(path)
    try:
        info=p.lstat()
        if not stat.S_ISREG(info.st_mode) or not 16<=info.st_size<=MAX_BYTES:
            raise SnapshotError('REGULAR_BOUNDED_SQLITE_REQUIRED')
        with p.open('rb') as stream:
            if stream.read(16)!=b'SQLite format 3\x00':
                raise SnapshotError('SQLITE_HEADER_INVALID')
    except OSError:
        raise SnapshotError('SQLITE_SOURCE_UNAVAILABLE') from None
    return p

def validate_snapshot(path):
    p=_source(path)
    try:
        with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as con:
            con.execute('PRAGMA trusted_schema=OFF')
            if con.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:
                raise SnapshotError('SQLITE_INTEGRITY_FAILED')
    except sqlite3.Error:
        raise SnapshotError('SQLITE_INTEGRITY_FAILED') from None
    return {'integrity':'ok'}

def backup_sqlite(source,target):
    source=_source(source); target=Path(target)
    created=False
    try:
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
        os.close(fd); created=True
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True,timeout=3) as src:
            src.execute('PRAGMA trusted_schema=OFF')
            with sqlite3.connect(target,timeout=3) as dest:
                src.backup(dest)
                dest.execute('PRAGMA journal_mode=DELETE')
                dest.execute('PRAGMA synchronous=FULL')
        validate_snapshot(target)
        with target.open('rb') as stream:os.fsync(stream.fileno())
    except (OSError,sqlite3.Error,SnapshotError):
        if created:target.unlink(missing_ok=True)
        raise SnapshotError('CONSISTENT_CREATE_ONLY_BACKUP_FAILED') from None
    return {'status':'CONSISTENT_SQLITE_BACKUP_CREATED','bytes':target.stat().st_size}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('backup','validate'));p.add_argument('source');p.add_argument('target',nargs='?')
    a=p.parse_args()
    try:
        if a.action=='backup':
            if not a.target:raise SnapshotError('DESTINATION_REQUIRED')
            result=backup_sqlite(a.source,a.target)
        else:result=validate_snapshot(a.source)
        print(json.dumps(result));return 0
    except SnapshotError as e:
        print(json.dumps({'status':'SQLITE_HANDOFF_FAILED_CLOSED','reason':str(e)}));return 2
if __name__=='__main__':raise SystemExit(main())
