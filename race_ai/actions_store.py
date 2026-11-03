"""Append-only SQLite test double. Never a production store or trusted clock.

Design reused from PR64 prediction.py immutable triggers and original-first
idempotency: prior receipts survive retries, result corrections append versions.
SQLite transactions/backup are exercised on real files/processes in synthetic CI.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from .actions_contract import ContractError, canonical, digest, stamp, validate_snapshot, forecast, race_key

SCHEMA="""
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
 kind TEXT NOT NULL, body TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_immutable_update BEFORE UPDATE ON events
 BEGIN SELECT RAISE(ABORT,'immutable events'); END;
CREATE TRIGGER IF NOT EXISTS events_immutable_delete BEFORE DELETE ON events
 BEGIN SELECT RAISE(ABORT,'immutable events'); END;
CREATE TABLE IF NOT EXISTS leases(scope TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clock_state(id INTEGER PRIMARY KEY CHECK(id=1), at TEXT NOT NULL);
"""

class SyntheticJournal:
    def __init__(self,path,clock=None):
        self.path=Path(path)
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.db=sqlite3.connect(str(path),timeout=10,isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        try:
            self.verify()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _now(self):
        value=self.clock()
        if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ContractError("aware synthetic clock required")
        value=value.astimezone(timezone.utc)
        last=self.db.execute("SELECT at FROM clock_state WHERE id=1").fetchone()
        if last and value<stamp(last[0]):
            raise ContractError("clock rollback")
        self.db.execute("INSERT INTO clock_state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET at=excluded.at",(value.isoformat(),))
        return value

    def events(self,kind=None):
        rows=self.db.execute("SELECT kind,body FROM events ORDER BY seq").fetchall()
        return [json.loads(body) for k,body in rows if kind is None or kind==k]

    def verify(self):
        prev="0"*64
        previous_at=None
        snapshots={}
        result_revisions={}
        for expected,row in enumerate(self.db.execute("SELECT seq,event_key,kind,body,previous_hash,event_hash FROM events ORDER BY seq"),1):
            seq,key,kind,body,previous,sha=row
            try: value=json.loads(body)
            except ValueError as exc: raise ContractError("journal corrupt JSON") from exc
            if seq!=expected or previous!=prev or canonical(value)!=body or digest([seq,key,kind,value,previous])!=sha:
                raise ContractError("journal chain integrity failed")
            if value.get("scope")!="SYNTHETIC_ONLY":
                raise ContractError("non-synthetic journal")
            at=stamp(value["recorded_at"])
            if value.get("kind")!=kind or previous_at and at<previous_at:
                raise ContractError("journal kind/clock mismatch")
            previous_at=at
            payload=value["payload"]
            if kind=="race":
                validate_snapshot(payload,require_features=False)
                snapshots[(race_key(payload),payload["revision"])]=payload
            elif kind=="freeze":
                s=validate_snapshot(payload["snapshot"])
                if canonical(forecast(s))!=canonical(payload["prediction"]) or not stamp(s["as_of"])<=at<stamp(s["sales_cutoff_at"]):
                    raise ContractError("invalid restored freeze")
            elif kind=="result":
                s=snapshots.get((payload["race_key"],payload["race_revision"]))
                if (s is None or payload["snapshot_hash"]!=s["snapshot_hash"]
                    or at<stamp(s["scheduled_start_at"])
                    or type(payload["revision"]) is not int
                    or payload["revision"]!=result_revisions.get(payload["race_key"],0)+1
                    or payload["source"]!="synthetic://official-result"
                    or payload["status"] not in ("final","void","pending","unsupported")):
                    raise ContractError("invalid restored result identity/revision")
                winners=payload["winning_combinations"]
                ids={r["participant"] for r in s["participants"]}
                if (not isinstance(winners,list) or (payload["status"]=="final")!=bool(winners)
                    or any(not isinstance(w,list) or len(w)!=3 or len(set(w))!=3
                           or any(type(p) is not int or p not in ids for p in w) for w in winners)
                    or len({tuple(w) for w in winners})!=len(winners)):
                    raise ContractError("invalid restored winning combinations")
                result_revisions[payload["race_key"]]=payload["revision"]
            elif kind=="no_forecast":
                if ((payload["race_key"],payload["race_revision"]) not in snapshots
                    or payload["reason"] not in ("MISSING_FEATURES","MISSED_DEADLINE","SOURCE_BLOCKED")):
                    raise ContractError("invalid restored no-forecast")
            else:
                raise ContractError("unknown journal kind")
            prev=sha
        highwater=self.db.execute("SELECT at FROM clock_state WHERE id=1").fetchone()
        if previous_at and (not highwater or stamp(highwater[0])<previous_at):
            raise ContractError("missing/backward restored clock")
        return prev

    def _before_commit(self):
        pass

    def _append(self,kind,key,payload,check=None,run_id="synthetic-fixture"):
        payload=json.loads(canonical(payload))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old=self.db.execute("SELECT body FROM events WHERE event_key=?",(key,)).fetchone()
            if old:
                value=json.loads(old[0])
                if canonical(value["payload"])!=canonical(payload) or value["kind"]!=kind:
                    raise ContractError("conflicting idempotency key")
                self.db.execute("COMMIT")
                return value
            now=self._now()
            if check: check(now)
            self._before_commit()
            # A second sample detects a deadline crossing during work before commit.
            commit_time=self._now()
            if check: check(commit_time)
            body={"kind":kind,"payload":payload,"recorded_at":commit_time.isoformat(),
                  "scope":"SYNTHETIC_ONLY","external_time_attested":False,"origin_run_id":run_id}
            last=self.db.execute("SELECT seq,event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq,prev=(last[0]+1,last[1]) if last else (1,"0"*64)
            self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                            (seq,key,kind,canonical(body),prev,digest([seq,key,kind,body,prev])))
            self.db.execute("COMMIT")
            return body
        except BaseException:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise

    def discover(self,snapshot):
        s=validate_snapshot(snapshot,require_features=False)
        def check(now):
            if stamp(s["as_of"])>now:
                raise ContractError("snapshot not yet observed by store")
            prior=self.latest_race(race_key(s))
            if prior and s["revision"]<=prior["revision"]:
                raise ContractError("stale race revision")
        return self._append("race",f'race:{race_key(s)}:{s["revision"]}',s,check)

    def latest_race(self,key):
        rows=[r["payload"] for r in self.events("race") if race_key(r["payload"])==key]
        return rows[-1] if rows else None

    def freeze(self,snapshot,prediction,*,run_id):
        s=validate_snapshot(snapshot)
        expected=forecast(s)
        if canonical(expected)!=canonical(prediction):
            raise ContractError("prediction changed or hash invalid")
        prediction=expected
        if not isinstance(run_id,str) or not run_id or len(run_id)>128:
            raise ContractError("run identity required")
        def check(now):
            if self.latest_race(race_key(s))!=s:
                raise ContractError("race changed; latest revision required")
            if s["status"]!="scheduled" or not s["trifecta_offered"]:
                raise ContractError("race unavailable")
            if not stamp(prediction["generated_at"])<=now<stamp(s["sales_cutoff_at"]):
                raise ContractError("actual synthetic persistence must precede sales cutoff")
        # run_id is operational metadata, not a key allowing duplicate predictions.
        receipt=self._append("freeze",f'freeze:{race_key(s)}:{s["revision"]}:{prediction["model"]["version"]}',
                             {"snapshot":s,"prediction":prediction},check,run_id=run_id)
        return {"prediction_hash":prediction["prediction_hash"],"persisted_at":receipt["recorded_at"],
                "external_time_attested":False,"official_prediction":False}

    def no_forecast(self,snapshot,reason):
        s=validate_snapshot(snapshot,require_features=False)
        if reason not in ("MISSING_FEATURES","MISSED_DEADLINE","SOURCE_BLOCKED"):
            raise ContractError("explicit no-forecast reason required")
        def check(now):
            if not any(canonical(event["payload"])==canonical(s) for event in self.events("race")):
                raise ContractError("no-forecast must bind an exact discovered snapshot")
        return self._append("no_forecast",f'no_forecast:{race_key(s)}:{s["revision"]}',
                            {"race_key":race_key(s),"race_revision":s["revision"],"reason":reason},check)

    def result(self,snapshot,*,revision,status,winning_combinations):
        s=validate_snapshot(snapshot,require_features=False)
        if type(revision) is not int or revision<1 or status not in ("final","void","pending","unsupported"):
            raise ContractError("explicit simulated official status/revision required")
        if not isinstance(winning_combinations,list) or status=="final" and not winning_combinations:
            raise ContractError("official winning combinations required")
        ids={r["participant"] for r in s["participants"]}
        if status!="final" and winning_combinations:
            raise ContractError("non-final result must not assert winners")
        for order in winning_combinations:
            if not isinstance(order,list) or len(order)!=3 or any(type(p) is not int or p not in ids for p in order) or len(set(order))!=3:
                raise ContractError("invalid official trifecta")
        if len({tuple(order) for order in winning_combinations})!=len(winning_combinations):
            raise ContractError("duplicate official trifecta")
        payload={"race_key":race_key(s),"race_revision":s["revision"],"revision":revision,"status":status,
                 "winning_combinations":winning_combinations,"source":"synthetic://official-result",
                 "snapshot_hash":s["snapshot_hash"]}
        def check(now):
            if not any(event["payload"]==s for event in self.events("race")):
                raise ContractError("result must bind an exact discovered snapshot")
            if now<stamp(s["scheduled_start_at"]):
                raise ContractError("result unavailable before scheduled start")
            priors=[r["payload"] for r in self.events("result") if r["payload"]["race_key"]==race_key(s)]
            if revision!=(priors[-1]["revision"]+1 if priors else 1):
                raise ContractError("result revision gap/rollback")
        return self._append("result",f'result:{race_key(s)}:{revision}',payload,check)

    def claim(self,scope,owner,ttl):
        if not isinstance(scope,str) or not scope or not isinstance(owner,str) or not owner or type(ttl) is not int or not 1<=ttl<=300:
            raise ContractError("bounded lease required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            now=self._now()
            last=self.db.execute("SELECT owner,expires_at FROM leases WHERE scope=?",(scope,)).fetchone()
            if last and last[0]!=owner and stamp(last[1])>now:
                raise ContractError("lease owned by another run")
            self.db.execute("INSERT INTO leases VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at",
                            (scope,owner,(now+timedelta(seconds=ttl)).isoformat()))
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction: self.db.execute("ROLLBACK")
            raise

    def backup(self,path):
        self.verify()
        target=Path(path)
        if target.exists(): raise ContractError("backup must not overwrite an existing file")
        out=sqlite3.connect(str(target))
        try: self.db.backup(out)
        finally: out.close()
