"""Snapshot correctness using actual WAL databases; no network or private data."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from scripts.keirin_github_sqlite_snapshot import backup_sqlite, validate_snapshot, SnapshotError

class SnapshotTests(unittest.TestCase):
    def test_wal_transactions_survive_sqlite_backup_and_original_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'live.sqlite3'; target=Path(d)/'safe.sqlite3'
            con=sqlite3.connect(source); con.execute('pragma journal_mode=WAL')
            con.execute('create table forecasts(id text primary key,picks text)')
            con.execute('insert into forecasts values (?,?)',('fixture','1-2-3'))
            con.commit()
            backup_sqlite(source,target)
            self.assertEqual(validate_snapshot(target),{'integrity':'ok'})
            with sqlite3.connect(target) as copy:
                self.assertEqual(copy.execute('select * from forecasts').fetchall(),[('fixture','1-2-3')])
            self.assertEqual(con.execute('select count(*) from forecasts').fetchone()[0],1)
            con.close()
            self.assertEqual(target.stat().st_mode&0o777,0o600)
    def test_backup_never_overwrites_or_follows_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            s=Path(d)/'live.db'; t=Path(d)/'exists.db'; l=Path(d)/'link.db'
            with sqlite3.connect(s) as con:con.execute('create table test(n)')
            t.write_bytes(b'original')
            with self.assertRaises(SnapshotError):backup_sqlite(s,t)
            self.assertEqual(t.read_bytes(),b'original')
            l.symlink_to(s)
            with self.assertRaises(SnapshotError):backup_sqlite(l,Path(d)/'new.db')
            self.assertFalse((Path(d)/'new.db').exists())
    def test_missing_database_not_recreated_empty(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SnapshotError):backup_sqlite(Path(d)/'missing',Path(d)/'snapshot.db')
            self.assertFalse((Path(d)/'snapshot.db').exists())
    def test_non_sqlite_or_corrupt_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'corrupt.db'; p.write_bytes(b'not a sqlite database')
            with self.assertRaises(SnapshotError):validate_snapshot(p)

if __name__=='__main__':unittest.main()
