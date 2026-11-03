"""Resumable authored synthetic research, with no external freeze authority.

Dependencies/callbacks are caller-audited trust interfaces. SYNTHETIC_ONLY is
a classification, not authentication of input origin or producer execution.
Factory work must be local and side-effect free; no exactly-once execution is
promised for a computation killed before its SQLite transaction commits.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3

from .append_only_freeze_writer import prepare_anchor
from .model_suite_settlement import audit_model_settlements
from .pr71_delivery_binding import bind_audit_to_delivery
from .proof_aware_settlement import _stamp, audit_settlement

SCHEMA = "RACE_AI_SYNTHETIC_ADVANCED_RUN_V1"
REPORT_SCHEMA = "RACE_AI_SYNTHETIC_ADVANCED_REPORT_V1"
MODEL_SOURCE_SHA40 = "ebe93f13062cf0461b81b924a5dc0482ada37b56"
SETTLEMENT_CONTRACT_BASE = "2a99473c4755932e2d395b9e785be4f4835aef99"
MODEL_IDS = ("multisport-factor-interaction-v1", "multisport-scenario-ensemble-v1",
             "multisport-conditional-duel-v1", "multisport-race-trajectory-v1")
VERSIONS = {name: "0.1.0-UNTRAINED" for name in MODEL_IDS}
GATES = ("admit_model_roster", "verify_result", "verify_cutoff", "verify_coverage")
DOMAIN = b"RACE_AI_SYNTHETIC_ADVANCED_JOURNAL_V1\0"
APPLICATION_ID = 0x52414941
JST = timezone(timedelta(hours=9))
SQL = """
CREATE TABLE IF NOT EXISTS advanced_events(
 seq INTEGER PRIMARY KEY,event_key TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,
 recorded_at TEXT NOT NULL,metadata TEXT NOT NULL,content BLOB NOT NULL,
 previous_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS advanced_events_no_update BEFORE UPDATE ON advanced_events
 BEGIN SELECT RAISE(ABORT,'immutable advanced events'); END;
CREATE TRIGGER IF NOT EXISTS advanced_events_no_delete BEFORE DELETE ON advanced_events
 BEGIN SELECT RAISE(ABORT,'immutable advanced events'); END;
CREATE TABLE IF NOT EXISTS advanced_clock(id INTEGER PRIMARY KEY CHECK(id=1),at TEXT NOT NULL);
"""


class OfflineRunError(ValueError):
    """Inconsistent local synthetic state must fail closed."""


def _fail():
    raise OfflineRunError("synthetic advanced journal rejected")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _copy(value):
    return json.loads(_canonical(value))


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _schema_objects(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                      "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value, domain=b""):
    return _sha(domain + _canonical(value).encode("utf-8"))


def _manifest(value):
    value = _copy(value)
    if (type(value) is not dict or set(value) != {"schema", "scope", "planned_as_of", "source_pins",
            "expected_model_ids", "expected_model_versions", "ledger", "jobs"}
            or value["schema"] != SCHEMA or value["scope"] != "SYNTHETIC_ONLY"
            or not _same(value["source_pins"], {"model": MODEL_SOURCE_SHA40,
                                        "settlement_contract_base": SETTLEMENT_CONTRACT_BASE})
            or not _same(value["expected_model_ids"], list(MODEL_IDS))
            or not _same(value["expected_model_versions"], VERSIONS)):
        _fail()
    planned = _stamp(value["planned_as_of"])
    ledger = value["ledger"]
    if (type(ledger) is not dict or set(ledger) != {"schema", "dataset_status", "event_date_jst", "records"}
            or ledger["schema"] != "RACE_AI_FORECAST_AUDIT_V1" or ledger["dataset_status"] != "AUDIT_ONLY"
            or type(ledger["records"]) is not list or len(ledger["records"]) != 8
            or type(value["jobs"]) is not list or len(value["jobs"]) != 8):
        _fail()
    if type(ledger["event_date_jst"]) is not str:
        _fail()
    day = date.fromisoformat(ledger["event_date_jst"])
    if day.isoformat() != ledger["event_date_jst"]:
        _fail()
    rows, numbers, model_ids = {}, {}, set()
    for row in ledger["records"]:
        if (type(row) is not dict or set(row) != {"race_id", "sport", "venue", "race_no",
                "sales_cutoff_at", "cutoff_verified", "prediction", "result"}
                or type(row["venue"]) is not str or not 1 <= len(row["venue"]) <= 80
                or type(row["race_no"]) is not int or row["race_no"] not in (1, 2)
                or row["sport"] not in ("boat", "keirin", "autorace", "horse_jra", "horse_local")
                or row["cutoff_verified"] is not False or row["prediction"] is not None or row["result"] is not None):
            _fail()
        sport = "horse" if row["sport"].startswith("horse_") else row["sport"]
        identity = f"{row['sport']}:{ledger['event_date_jst']}:{row['venue']}:{row['race_no']}"
        model_id = f"{sport}:{ledger['event_date_jst']}:{row['venue']}:{row['race_no']}"
        if identity != row["race_id"] or identity in rows or model_id in model_ids:
            _fail()
        if row["sales_cutoff_at"] is not None:
            if _stamp(row["sales_cutoff_at"]).astimezone(JST).date() != day:
                _fail()
        rows[identity] = row
        model_ids.add(model_id)
        numbers.setdefault(sport, []).append(row["race_no"])
    if set(numbers) != {"boat", "keirin", "autorace", "horse"} or any(sorted(x) != [1, 2] for x in numbers.values()):
        _fail()
    seen = set()
    for job in value["jobs"]:
        if type(job) is not dict or set(job) != {"race_id", "input_check"} or job["race_id"] not in rows or job["race_id"] in seen:
            _fail()
        seen.add(job["race_id"])
        check = job["input_check"]
        if check is not None:
            if (type(check) is not dict or set(check) != {"as_of", "source_payload_sha256",
                    "policy_record_sha256", "feature_snapshot_sha256"}
                    or any(type(check[k]) is not str or re.fullmatch(r"[0-9a-f]{64}", check[k]) is None
                           for k in check if k != "as_of") or _stamp(check["as_of"]) > planned):
                _fail()
            cutoff = rows[job["race_id"]]["sales_cutoff_at"]
            if cutoff is not None and _stamp(check["as_of"]) >= _stamp(cutoff):
                _fail()
    return value


class SyntheticModelJournal:
    def __init__(self, path, *, clock, codec, validate_snapshot, allow_source):
        self.clock, self.codec = clock, codec
        self.validate_snapshot, self.allow_source = validate_snapshot, allow_source
        self.db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        try:
            template = sqlite3.connect(":memory:")
            try:
                template.executescript(SQL)
                expected = _schema_objects(template)
            finally:
                template.close()
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("BEGIN IMMEDIATE")
            objects = _schema_objects(self.db)
            identity = (self.db.execute("PRAGMA application_id").fetchone()[0],
                        self.db.execute("PRAGMA user_version").fetchone()[0])
            if not objects and identity == (0, 0):
                # Individual DDL stays in this transaction; executescript would
                # implicitly commit and expose a partially initialized schema.
                for kind, name, table, statement in expected:
                    self.db.execute(statement)
                self.db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                self.db.execute("PRAGMA user_version=1")
            elif objects != expected or identity != (APPLICATION_ID, 1):
                _fail()
            self._load()
            self.db.execute("COMMIT")
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self._load()
            yield state
            commit_time = self._now()
            if state.get("commit_cutoff") is not None and _stamp(commit_time) >= _stamp(state["commit_cutoff"]):
                _fail()
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def _now(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.utcoffset() is None:
            _fail()
        now = now.astimezone(timezone.utc).isoformat()
        old = self.db.execute("SELECT at FROM advanced_clock WHERE id=1").fetchone()
        if old and _stamp(now) < _stamp(old[0]):
            _fail()
        self.db.execute("INSERT INTO advanced_clock VALUES(1,?) ON CONFLICT(id) DO UPDATE SET at=excluded.at", (now,))
        return now

    def _append(self, key, kind, at, metadata, content=b""):
        last = self.db.execute("SELECT seq,event_sha256 FROM advanced_events ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
        digest = _hash([seq, key, kind, at, metadata, _sha(content), previous], DOMAIN)
        self.db.execute("INSERT INTO advanced_events VALUES(?,?,?,?,?,?,?,?)",
                        (seq, key, kind, at, _canonical(metadata), content, previous, digest))

    def _check_delivery(self, manifest, job, delivery, saved=None):
        check = job["input_check"]
        if (check is None or any(delivery.get(k) != check[k] for k in check if k != "as_of")
                or delivery["snapshot"]["race"]["as_of"] != check["as_of"]
                or list(delivery["research_suite"]["models"]) != list(MODEL_IDS)):
            _fail()
        decisions = {}
        def source(source_ref, rights_ref, purpose):
            key = _hash([source_ref, rights_ref, purpose])
            if saved is None:
                accepted = callable(self.allow_source) and self.allow_source(source_ref, rights_ref, purpose) is True
            else:
                if type(saved) is not dict or key not in saved or type(saved[key]) is not bool:
                    _fail()
                accepted = saved[key]
            decisions[key] = accepted
            return accepted
        audit = audit_model_settlements(manifest["ledger"], [],
            [{"race_id": job["race_id"], "delivery": delivery}], [],
            expected_model_ids=MODEL_IDS, expected_model_versions=VERSIONS,
            expected_model_source_sha40=MODEL_SOURCE_SHA40,
            validate_snapshot=self.validate_snapshot, allow_source=source)
        if not audit["all_supplied_snapshots_admitted_by_callback"] or saved is not None and not _same(saved, decisions):
            _fail()
        return bind_audit_to_delivery(manifest["ledger"], delivery, race_id=job["race_id"]), decisions

    def _settle(self, state, gates=None, saved=None):
        decisions = {name: {} for name in GATES}
        if saved is not None and (type(saved) is not dict or set(saved) != set(GATES)):
            _fail()
        def checker(name):
            def check(argument):
                key = _hash(argument)
                if saved is None:
                    function = (gates or {}).get(name)
                    accepted = callable(function) and function(deepcopy(argument)) is True
                else:
                    if type(saved[name]) is not dict or key not in saved[name] or type(saved[name][key]) is not bool:
                        _fail()
                    accepted = saved[name][key]
                decisions[name][key] = accepted
                return accepted
            return check
        record = audit_model_settlements(state["manifest"]["ledger"], state["results"],
            [{"race_id": race, "delivery": value} for race, value in state["deliveries"].items()], [],
            expected_model_ids=MODEL_IDS, expected_model_versions=VERSIONS,
            expected_model_source_sha40=MODEL_SOURCE_SHA40,
            validate_snapshot=self.validate_snapshot,
            allow_source=lambda source, rights, purpose: state["sources"].get(_hash([source, rights, purpose])) is True,
            **{name: checker(name) for name in GATES})
        if saved is not None and not _same(saved, decisions):
            _fail()
        return record, decisions

    def _summaries(self, state):
        return [{"race_id": row["race_id"], **state["jobs"].get(row["race_id"],
            {"state": "NOT_RUN", "reason": None, "delivery_sha256": None,
             "prepared_anchor_count": 0, "generated_at": None, "persisted_at": None})}
            for row in state["manifest"]["ledger"]["records"]]

    def _report(self, state, settlement, simulated):
        jobs = self._summaries(state)
        report = {"schema": REPORT_SCHEMA, "scope": "SYNTHETIC_ONLY",
            "manifest_sha256": _hash(state["manifest"], SCHEMA.encode() + b"\0"),
            "basis_sha256": _hash(state["basis"]), "jobs": jobs,
            "prepared_anchor_count": sum(row["prepared_anchor_count"] for row in jobs),
            "simulation_gates_used": simulated, "external_time_attested": False,
            "official_prediction": False, "settlement": settlement}
        report["evaluation_sha256"] = _hash(report, REPORT_SCHEMA.encode() + b"\0")
        return report

    def _load(self):
        state = {"manifest": None, "jobs": {}, "deliveries": {}, "results": [], "basis": [], "sources": {}}
        previous, last_at, result_keys = "0" * 64, None, set()
        for expected, row in enumerate(self.db.execute("SELECT * FROM advanced_events ORDER BY seq"), 1):
            seq, key, kind, at, text, content, predecessor, digest = row
            metadata = json.loads(text)
            if (seq != expected or predecessor != previous or type(content) is not bytes
                    or _canonical(metadata) != text or (last_at is not None and _stamp(at) < _stamp(last_at))
                    or digest != _hash([seq, key, kind, at, metadata, _sha(content), predecessor], DOMAIN)):
                _fail()
            _stamp(at)
            if kind == "MANIFEST":
                if key != "manifest" or seq != 1 or content:
                    _fail()
                state["manifest"] = _manifest(metadata)
                if _stamp(at) < _stamp(metadata["planned_as_of"]):
                    _fail()
            elif state["manifest"] is None:
                _fail()
            elif kind in ("DELIVERY", "NO_FORECAST"):
                jobs = {job["race_id"]: job for job in state["manifest"]["jobs"]}
                race = metadata.get("race_id")
                if race not in jobs or key != "job:" + race or race in state["jobs"]:
                    _fail()
                job = jobs[race]
                cutoff = next(x["sales_cutoff_at"] for x in state["manifest"]["ledger"]["records"] if x["race_id"] == race)
                summary = {"state": kind, "reason": None, "delivery_sha256": None,
                           "prepared_anchor_count": 0, "generated_at": None, "persisted_at": None}
                if kind == "DELIVERY":
                    if set(metadata) != {"race_id", "delivery_sha256", "started_at", "generated_at", "persisted_at", "plans", "source_verdicts"}:
                        _fail()
                    delivery = self.codec.deserialize_private_delivery(content, expected_delivery_sha256=metadata["delivery_sha256"])
                    binding, sources = self._check_delivery(state["manifest"], job, delivery, metadata["source_verdicts"])
                    started, generated, persisted = map(_stamp, (metadata["started_at"], metadata["generated_at"], metadata["persisted_at"]))
                    if (cutoff is None or not _stamp(job["input_check"]["as_of"]) <= started <= generated <= persisted < _stamp(cutoff)
                            or _stamp(delivery["ingested_at"]) != started or metadata["persisted_at"] != at
                            or last_at is not None and started < _stamp(last_at)
                            or any(result["race_id"] == race for result in state["results"])
                            or not _same(metadata["plans"], [prepare_anchor(binding, name, metadata["generated_at"], at) for name in MODEL_IDS])):
                        _fail()
                    state["deliveries"][race] = delivery
                    state["sources"].update(sources)
                    summary.update(delivery_sha256=delivery["delivery_sha256"], prepared_anchor_count=4,
                                   generated_at=metadata["generated_at"], persisted_at=at)
                else:
                    reason = ("MISSING_INPUT" if job["input_check"] is None else
                              "CUTOFF_UNKNOWN" if cutoff is None else "MISSED_DEADLINE")
                    if (set(metadata) != {"race_id", "reason"} or content or metadata["reason"] != reason
                            or reason == "MISSED_DEADLINE" and _stamp(at) < _stamp(cutoff)):
                        _fail()
                    summary["reason"] = reason
                state["jobs"][race] = summary
            elif kind == "RESULT":
                race, revision = metadata.get("race_id"), metadata.get("revision_no")
                if content or key != f"result:{race}:{revision}" or key in result_keys:
                    _fail()
                audit_settlement(state["manifest"]["ledger"], state["results"] + [metadata], [])
                self._result_time(state, metadata, at)
                state["results"].append(metadata)
                result_keys.add(key)
            elif kind == "EVALUATION":
                if content or set(metadata) != {"report", "verdicts"}:
                    _fail()
                settlement, decisions = self._settle(state, saved=metadata["verdicts"])
                report = self._report(state, settlement, metadata["report"].get("simulation_gates_used"))
                if (type(report["simulation_gates_used"]) is not bool or not _same(report, metadata["report"])
                        or not report["simulation_gates_used"] and any(any(x.values()) for x in decisions.values())
                        or key != "evaluation:" + report["basis_sha256"] + ":" + report["evaluation_sha256"]):
                    _fail()
            else:
                _fail()
            if kind != "EVALUATION":
                state["basis"].append(digest)
            previous, last_at = digest, at
        highwater = self.db.execute("SELECT at FROM advanced_clock WHERE id=1").fetchone()
        if last_at and (not highwater or _stamp(highwater[0]) < _stamp(last_at)):
            _fail()
        return state

    def run(self, manifest, *, delivery_factory):
        manifest = _manifest(manifest)
        with self._transaction() as state:
            now = self._now()
            if state["manifest"] is not None and not _same(state["manifest"], manifest):
                _fail()
            if _stamp(now) < _stamp(manifest["planned_as_of"]):
                _fail()
            if state["manifest"] is None:
                self._append("manifest", "MANIFEST", now, manifest)
        rows = {row["race_id"]: row for row in manifest["ledger"]["records"]}
        ordered = sorted(manifest["jobs"], key=lambda job:
            (_stamp(rows[job["race_id"]]["sales_cutoff_at"]).timestamp()
             if rows[job["race_id"]]["sales_cutoff_at"] else float("inf"), job["race_id"]))
        for job in ordered:
            with self._transaction() as state:
                started = self._now()
                race, cutoff = job["race_id"], rows[job["race_id"]]["sales_cutoff_at"]
                if race in state["jobs"]:
                    continue
                reason = ("MISSING_INPUT" if job["input_check"] is None else "CUTOFF_UNKNOWN" if cutoff is None
                          else "MISSED_DEADLINE" if _stamp(started) >= _stamp(cutoff) else None)
                if reason:
                    self._append("job:" + race, "NO_FORECAST", started, {"race_id": race, "reason": reason})
                    continue
                if any(result["race_id"] == race for result in state["results"]):
                    _fail()
                delivery = delivery_factory(_copy(job), at=started)
                generated = self._now()
                wire = self.codec.serialize_private_delivery(delivery)
                decoded = self.codec.deserialize_private_delivery(wire, expected_delivery_sha256=delivery["delivery_sha256"])
                binding, sources = self._check_delivery(manifest, job, decoded)
                persisted = self._now()
                if (not _stamp(started) <= _stamp(generated) <= _stamp(persisted) < _stamp(cutoff)
                        or _stamp(decoded["ingested_at"]) != _stamp(started)):
                    _fail()
                metadata = {"race_id": race, "delivery_sha256": decoded["delivery_sha256"],
                    "started_at": started, "generated_at": generated, "persisted_at": persisted,
                    "source_verdicts": sources,
                    "plans": [prepare_anchor(binding, name, generated, persisted) for name in MODEL_IDS]}
                self._append("job:" + race, "DELIVERY", persisted, metadata, wire)
                state["commit_cutoff"] = cutoff
        with self._transaction() as state:
            self._now()
            return self._summaries(state)

    def _result_time(self, state, claim, at):
        if _stamp(claim["confirmed_at"]) > _stamp(at):
            _fail()
        cutoff = next(row["sales_cutoff_at"] for row in state["manifest"]["ledger"]["records"] if row["race_id"] == claim["race_id"])
        if claim["status"] == "FINAL" and cutoff is not None and _stamp(claim["confirmed_at"]) <= _stamp(cutoff):
            _fail()
        prior = state["jobs"].get(claim["race_id"])
        if prior and prior["state"] == "DELIVERY" and _stamp(claim["confirmed_at"]) < _stamp(prior["persisted_at"]):
            _fail()

    def add_results(self, claims):
        claims = _copy(claims)
        if type(claims) is not list or len(claims) > 100:
            _fail()
        with self._transaction() as state:
            if state["manifest"] is None:
                _fail()
            at, stored = self._now(), []
            old = {(result["race_id"], result["revision_no"]): result for result in state["results"]}
            for claim in claims:
                if (type(claim) is not dict or type(claim.get("race_id")) is not str
                        or type(claim.get("revision_no")) is not int):
                    _fail()
                identity = (claim["race_id"], claim["revision_no"])
                if identity in old:
                    audit_settlement(state["manifest"]["ledger"],
                        [claim if (item["race_id"], item["revision_no"]) == identity else item
                         for item in state["results"]], [])
                    if not _same(old[identity], claim):
                        _fail()
                    stored.append(old[identity])
                    continue
                audit_settlement(state["manifest"]["ledger"], state["results"] + [claim], [])
                self._result_time(state, claim, at)
                state["results"].append(claim)
                self._append(f"result:{identity[0]}:{identity[1]}", "RESULT", at, claim)
                old[identity] = claim
                stored.append(claim)
            return _copy(stored)

    def report(self, *, synthetic_gates=None):
        if synthetic_gates is not None and (type(synthetic_gates) is not dict or set(synthetic_gates) - set(GATES)):
            _fail()
        with self._transaction() as state:
            if state["manifest"] is None:
                _fail()
            at = self._now()
            settlement, decisions = self._settle(state, synthetic_gates)
            report = self._report(state, settlement, bool(synthetic_gates))
            key = "evaluation:" + report["basis_sha256"] + ":" + report["evaluation_sha256"]
            if not self.db.execute("SELECT 1 FROM advanced_events WHERE event_key=?", (key,)).fetchone():
                self._append(key, "EVALUATION", at, {"report": report, "verdicts": decisions})
            return report
