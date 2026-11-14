"""Private local SQLite storage for AUTORACE A/B research; not external attestation.

No official site access, production scheduler, provider rights grant, cloud
backup, encryption or independent server time. The database must live OUTSIDE
the public repository. Uncertain writes are never retried automatically.
"""
import json
import os
import re
import sqlite3
import stat
from pathlib import Path
from .comprehensive_four_sport_models import digest
from .autorace_ab_pdca import PHASES

HEX = re.compile(r"[0-9a-f]{64}\Z")


def canonical(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > 2_000_000:
        raise ValueError("PRIVATE_RECORD_TOO_LARGE")
    return raw


class LocalPrivateJournal:
    """Local atomic single-writer reservations and revisioned audit append."""

    def __init__(self, db_path):
        # POSIX owner-only permissions are mandatory. Windows ACL validation
        # is not implemented; refuse storage rather than claim privacy.
        if os.name != "posix":
            raise ValueError("PLATFORM_PRIVATE_ACL_UNVERIFIED")
        self.path = Path(db_path).absolute()
        directory = self.path.parent
        if directory.is_symlink() or self.path.is_symlink():
            raise ValueError("UNSAFE_SYMLINK")
        if not directory.exists():
            directory.mkdir(mode=0o700)
        if not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise ValueError("DIRECTORY_NOT_PRIVATE")
        if self.path.exists() and (not self.path.is_file() or
                stat.S_IMODE(self.path.stat().st_mode) & 0o077):
            raise ValueError("DATABASE_NOT_PRIVATE")
        old = os.umask(0o077)
        try:
            with self.connect() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS forecasts(
                  race_id TEXT NOT NULL, phase TEXT NOT NULL, model_id TEXT NOT NULL,
                  forecast_sha TEXT NOT NULL, state TEXT NOT NULL,
                  wire BLOB, receipt BLOB,
                  PRIMARY KEY(race_id,phase,model_id));
                CREATE TABLE IF NOT EXISTS audits(
                  race_id TEXT NOT NULL, revision INTEGER NOT NULL, sha TEXT NOT NULL,
                  previous_sha TEXT, wire BLOB NOT NULL,
                  PRIMARY KEY(race_id,revision));
                """)
        finally:
            os.umask(old)
        if stat.S_IMODE(self.path.stat().st_mode) & 0o077:
            raise ValueError("DATABASE_NOT_PRIVATE")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=3000")
        return db

    def _key(self, race, phase, model):
        if not isinstance(race, str) or not 8 <= len(race) <= 200 or phase not in PHASES:
            raise ValueError("INVALID_RACE_OR_PHASE")
        if not isinstance(model, str) or not 1 <= len(model) <= 128:
            raise ValueError("INVALID_MODEL")
        return race, phase, model

    def readback(self, race, phase, model):
        with self.connect() as db:
            row = db.execute("SELECT state FROM forecasts WHERE race_id=? AND phase=? AND model_id=?",
                             self._key(race,phase,model)).fetchone()
        return {"state": row[0] if row else "ABSENT"}

    def claim(self, race, phase, forecast):
        key = self._key(race, phase, forecast.get("model_id"))
        if forecast.get("race_id") != race or forecast.get("phase") != phase or (
            forecast.get("prediction_sha256") != digest({
                k:v for k,v in forecast.items() if k!="prediction_sha256"})):
            raise ValueError("UNVERIFIED_FORECAST")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur = db.execute("INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?,?,?)",
                             (*key, forecast["prediction_sha256"], "CLAIMED",None,None))
            db.commit()
        return {"state":"CREATED" if cur.rowcount else "EXISTS"}

    def submit_once(self, race, phase, forecast):
        key = self._key(race,phase,forecast.get("model_id"))
        if forecast.get("prediction_sha256") != digest({
                k:v for k,v in forecast.items() if k!="prediction_sha256"}):
            raise ValueError("FORECAST_HASH_CHANGED")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cur=db.execute("UPDATE forecasts SET state='UNRESOLVED_POST',wire=? "
                           "WHERE race_id=? AND phase=? AND model_id=? AND "
                           "forecast_sha=? AND state='CLAIMED' AND wire IS NULL",
                           (canonical(forecast),*key,forecast["prediction_sha256"]))
            db.commit()
        if cur.rowcount != 1:
            raise ValueError("UNCERTAIN_OR_DUPLICATE_POST")
        return {"state":"SUBMITTED"}

    def original(self,race,phase,model):
        with self.connect() as db:
            row=db.execute("SELECT wire FROM forecasts WHERE race_id=? AND phase=? AND model_id=?",
                           self._key(race,phase,model)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def attest(self,race,phase,forecast,receipt,independent_verifier):
        """External verifier must authenticate receipt provenance and pre-cutoff time."""
        key=self._key(race,phase,forecast.get("model_id"))
        if not callable(independent_verifier) or independent_verifier(
            race, phase, forecast, receipt) is not True:
            return False
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT wire,state FROM forecasts WHERE race_id=? AND phase=? AND model_id=?",
                           key).fetchone()
            if not row or row!=(canonical(forecast),"UNRESOLVED_POST"):
                db.rollback()
                return False
            cur=db.execute("UPDATE forecasts SET state='VERIFIED',receipt=? "
                           "WHERE race_id=? AND phase=? AND model_id=? AND state='UNRESOLVED_POST'",
                           (canonical(receipt),*key))
            db.commit()
        return cur.rowcount==1

    def latest_audit(self,race):
        with self.connect() as db:
            r=db.execute("SELECT revision,sha,previous_sha,wire FROM audits "
                         "WHERE race_id=? ORDER BY revision DESC LIMIT 1",(race,)).fetchone()
        if not r: return None
        return {"race_id":race,"revision":r[0],"sha256":r[1],
                "previous_sha256":r[2],"report":json.loads(r[3])}

    def append_audit(self,record):
        if set(record)!={"race_id","revision","report","sha256","previous_sha256"} or (
            record["sha256"]!=digest(record["report"])):
            raise ValueError("AUDIT_HASH")
        rid=record["race_id"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prev=db.execute("SELECT revision,sha FROM audits WHERE race_id=? "
                            "ORDER BY revision DESC LIMIT 1",(rid,)).fetchone()
            if record["revision"]!=(prev[0]+1 if prev else 1) or (
                record["previous_sha256"]!=(prev[1] if prev else None)):
                db.rollback()
                raise ValueError("INVALID_AUDIT_REVISION")
            db.execute("INSERT INTO audits VALUES(?,?,?,?,?)",
                       (rid,record["revision"],record["sha256"],
                        record["previous_sha256"],canonical(record["report"])))
            db.commit()
        return True

    def read_audit(self,race,revision):
        with self.connect() as db:
            r=db.execute("SELECT sha,previous_sha,wire FROM audits "
                         "WHERE race_id=? AND revision=?",(race,revision)).fetchone()
        return {"race_id":race,"revision":revision,"sha256":r[0],
                "previous_sha256":r[1],"report":json.loads(r[2])} if r else None
