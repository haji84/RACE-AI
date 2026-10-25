"""One cooperative local attempt store; no default transport or global proof.

Exact-action callbacks must authorize through the original official cutoff.
Their booleans do not authenticate rights, producer execution, store freshness,
transport internals, private cloud retention or protection against cloned DBs.
"""
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

from . import permissioned_model_case as case
from .append_only_freeze_writer import submit_anchor
from .github_witness_resolution import resolve_anchor_witness

SCHEMA = "RACE_AI_PERMISSIONED_SUBMISSION_MANIFEST_V1"
RESULT = "RACE_AI_PERMISSIONED_SUBMISSION_RESULT_V1"
CLAIM = "RACE_AI_PERMISSIONED_SUBMISSION_CLAIM_V1"
REPO = "haji84/RACE-AI"
BASE = "https://api.github.com/repos/" + REPO
APPLICATION_ID = 0x52415355
LIMIT = 65536
KINDS = ("PUT_COMMIT", "NORMAL_ACK", "WITNESS")
GATES = ("source", "cutoff", "roster", "release", "transport", "store", "path")
SQL = (
    "CREATE TABLE submission_manifest(id INTEGER PRIMARY KEY CHECK(id=1),json TEXT NOT NULL,sha256 TEXT NOT NULL)",
    "CREATE TABLE submission_intents(position INTEGER PRIMARY KEY CHECK(position BETWEEN 1 AND 4),json TEXT NOT NULL,sha256 TEXT NOT NULL)",
    "CREATE TABLE submission_evidence(position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 4),kind TEXT NOT NULL,json TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(position,kind))",
) + tuple("CREATE TRIGGER " + table + "_no_" + verb.lower() + " BEFORE " + verb + " ON " + table +
          " BEGIN SELECT RAISE(ABORT,'immutable submission'); END"
          for table in ("submission_manifest", "submission_intents", "submission_evidence") for verb in ("UPDATE", "DELETE"))


class SubmissionError(ValueError):
    """Sanitized invalid authority, private store or submission evidence."""


def _fail(code="SUBMISSION_REJECTED"):
    raise SubmissionError(code) from None


def _raw(value):
    return case._canonical(value).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(kind, value):
    return _sha(("RACE_AI_PERMISSIONED_SUBMISSION_" + kind + "_V1\0").encode() + _raw(value))


def _copy(value, limit=case.MAX_REQUEST):
    result = case._bounded_copy(value)
    if len(_raw(result)) > limit:
        _fail()
    return result


def _call(function, *args, **kwargs):
    if not callable(function):
        return False
    owned = [_copy(v) if type(v) in (dict, list) else v for v in args]
    before = [_raw(v) if type(v) in (dict, list) else None for v in owned]
    try:
        result = function(*owned, **kwargs)
        return result is True and all(old is None or old == _raw(_copy(v)) for old, v in zip(before, owned))
    except Exception:
        _fail("AUTHORITY_CALLBACK_FAILED")


def _time(value):
    try:
        return case._stamp(value)
    except Exception:
        _fail("INVALID_SUBMISSION_TIME")


def _tracked_clock(clock):
    previous = None
    def sample():
        nonlocal previous
        value = clock()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            _fail("SUBMISSION_CLOCK_REVERSED")
        value = value.astimezone(timezone.utc)
        if previous is not None and value < previous:
            _fail("SUBMISSION_CLOCK_REVERSED")
        previous = value
        return value
    return sample


def _now(clock, previous=None, cutoff=None):
    try:
        value = clock()
        if not isinstance(value, datetime) or value.utcoffset() is None:
            _fail()
        value = value.astimezone(timezone.utc).isoformat()
        if previous is not None and _time(value) < _time(previous):
            _fail()
        if cutoff is not None and _time(value) >= _time(cutoff):
            _fail("MISSED_DEADLINE")
        return value
    except Exception:
        _fail("INVALID_OR_CLOSED_SUBMISSION_CLOCK")


def _stage(path, manifest, private, store, stage):
    try:
        return (case._private(path, private, stage)
                and _call(store, path, manifest, stage=stage) and case._path(path) == path)
    except Exception:
        _fail("PRIVATE_STORE_REJECTED")


def _entry(attempt_path, case_path, expected, branch, pin, private, store):
    if (not case._hex(expected) or not case._hex(pin, 40) or type(branch) is not str
            or not re.fullmatch(r"audit/freeze-[A-Za-z0-9._/-]{1,80}", branch)
            or ".." in branch or "//" in branch or branch.endswith("/")):
        _fail()
    if not callable(private) or not callable(store):
        return None
    try:
        original_path = case._path(case_path)
        if not case._private(original_path, private, "PRE_OPEN"):
            return None
        loaded = case.load_case(case_path, expected_request_sha256=expected, private_path_verifier=private)
        path = case._path(attempt_path)
        if path == case._path(case_path):
            _fail()
        request = loaded["request"]
        manifest = {"schema": SCHEMA, "case_request_sha256": expected,
            "case_wire_sha256": loaded["wire_sha256"], "case_delivery_sha256": loaded["delivery_sha256"],
            **{key: request[key] for key in ("source_payload_sha256", "policy_record_sha256", "feature_snapshot_sha256",
                                            "model_source_sha40", "sales_cutoff_at")},
            "case_executor_source_sha40": request["executor_source_sha40"], "submission_source_sha40": pin,
            "case_generated_at": loaded["generated_at"], "case_persisted_at": loaded["persisted_at"],
            "repository": REPO, "branch": branch, "models": []}
        for name, plan in zip(case.MODELS, loaded["plans"]):
            model = loaded["delivery"]["research_suite"]["models"][name]
            manifest["models"].append({"model_id": name, "model_version": model["model_version"],
                "prediction_sha256": model["prediction_sha256"], "plan": plan,
                "anchor_sha256": _sha(_raw(plan["anchor"]) + b"\n")})
        manifest = _copy(manifest, LIMIT)
        if not _stage(path, manifest, private, store, "PRE_OPEN"):
            return None
        return path, manifest, loaded
    except Exception:
        _fail("ORIGINAL_CASE_OR_STORE_REJECTED")


def _identity(db):
    template = sqlite3.connect(":memory:")
    try:
        for statement in SQL:
            template.execute(statement)
        expected = case._objects(template)
    finally:
        template.close()
    objects = case._objects(db)
    ids = (db.execute("PRAGMA application_id").fetchone()[0], db.execute("PRAGMA user_version").fetchone()[0])
    if not objects and ids == (0, 0):
        return False
    if objects != expected or ids != (APPLICATION_ID, 1):
        _fail("FOREIGN_SUBMISSION_STORE")
    return True


def _writer_result(model, commit):
    plan = model["plan"]
    return {"path": plan["path"], "commit_sha": commit, "prediction_sha256": model["prediction_sha256"],
        "model_race_id": plan["anchor"]["race_id"], "run_id": None, "external_server_time": None,
        "eligible_for_hit_at_8": False, "status": "COMMIT_EXISTS_BUT_PRE_CUTOFF_PROOF_UNVERIFIED"}


def _witness(value, model, commit, manifest, recorded):
    keys = {"schema", "status", "receipt", "commit_sha", "model_race_id", "prediction_sha256",
        "external_server_time", "external_pre_cutoff_presence_verified", "eligible_for_hit_at_8",
        "source_rights_verified", "full_private_payload_retention_verified", "producer_execution_authenticated",
        "github_reads", "observed_at"}
    if (type(value) is not dict or set(value) != keys or value["schema"] != "RACE_AI_GITHUB_WITNESS_RESOLUTION_V1"
            or value["status"] != "EXTERNAL_FINGERPRINT_PRESENT_BEFORE_CUTOFF" or value["commit_sha"] != commit
            or value["model_race_id"] != model["plan"]["anchor"]["race_id"]
            or value["prediction_sha256"] != model["prediction_sha256"]
            or value["external_pre_cutoff_presence_verified"] is not True or type(value["github_reads"]) is not int
            or value["github_reads"] != 3 or any(value[k] is not False for k in
               ("eligible_for_hit_at_8", "source_rights_verified", "full_private_payload_retention_verified", "producer_execution_authenticated"))):
        _fail()
    receipt = value["receipt"]
    if (type(receipt) is not dict or set(receipt) != {"run_id", "path"}
            or type(receipt["run_id"]) is not int or not 1 <= receipt["run_id"] <= 10**15
            or receipt["path"] != model["plan"]["path"]
            or not _time(manifest["case_persisted_at"]) <= _time(value["external_server_time"]) < _time(manifest["sales_cutoff_at"])
            or not _time(value["external_server_time"]) <= _time(value["observed_at"]) <= _time(recorded)):
        _fail()


def _read(db, manifest):
    if not db.in_transaction:
        _fail()
    state = {"intents": {}, "evidence": {}, "latest": manifest["case_persisted_at"]}
    try:
        if not _identity(db):
            return state
        for table, maximum in (("submission_manifest", 1), ("submission_intents", 4), ("submission_evidence", 12)):
            extra = ",typeof(kind),length(CAST(kind AS BLOB))" if table == "submission_evidence" else ""
            sizes = db.execute("SELECT typeof(json),length(CAST(json AS BLOB)),typeof(sha256),length(CAST(sha256 AS BLOB))" + extra + " FROM " + table).fetchmany(maximum + 1)
            if (len(sizes) > maximum or table == "submission_manifest" and len(sizes) != 1
                    or any(row[0] != "text" or not 0 < row[1] <= LIMIT or row[2:4] != ("text", 64)
                           or len(row) == 6 and (row[4] != "text" or not 0 < row[5] <= 16) for row in sizes)):
                _fail()
        row = db.execute("SELECT id,json,sha256 FROM submission_manifest").fetchone()
        if row != (1, _raw(manifest).decode(), _hash("MANIFEST", manifest)):
            _fail()
        for position, text, digest in db.execute("SELECT position,json,sha256 FROM submission_intents ORDER BY position"):
            obj = json.loads(text)
            if (type(position) is not int or position != len(state["intents"]) + 1
                    or type(obj) is not dict or set(obj) != {"manifest_sha256", "model_id", "position", "recorded_at", "gates"}
                    or type(obj["position"]) is not int or obj["position"] != position
                    or obj["model_id"] != case.MODELS[position - 1]
                    or obj["manifest_sha256"] != _hash("MANIFEST", manifest)
                    or obj["gates"] != dict.fromkeys(GATES, True) or any(v is not True for v in obj["gates"].values())
                    or text != _raw(obj).decode() or digest != _hash("INTENT", obj)
                    or not _time(manifest["case_persisted_at"]) <= _time(obj["recorded_at"]) < _time(manifest["sales_cutoff_at"])):
                _fail()
            state["intents"][position] = (obj, digest)
        for position, kind, text, digest in db.execute("SELECT position,kind,json,sha256 FROM submission_evidence ORDER BY position,kind"):
            obj = json.loads(text)
            if (position not in state["intents"] or kind not in KINDS or type(obj) is not dict
                    or set(obj) != {"manifest_sha256", "intent_sha256", "recorded_at", "payload"}
                    or obj["manifest_sha256"] != _hash("MANIFEST", manifest)
                    or obj["intent_sha256"] != state["intents"][position][1]
                    or text != _raw(obj).decode() or digest != _hash("EVIDENCE", [position, kind, obj])
                    or _time(obj["recorded_at"]) < _time(state["intents"][position][0]["recorded_at"])):
                _fail()
            state["evidence"][(position, kind)] = obj
        for position, (intent, _) in state["intents"].items():
            if position > 1:
                previous = state["evidence"].get((position - 1, "NORMAL_ACK"))
                if previous is None or _time(intent["recorded_at"]) < _time(previous["recorded_at"]):
                    _fail()
            commit = state["evidence"].get((position, "PUT_COMMIT"))
            for kind in KINDS:
                evidence = state["evidence"].get((position, kind))
                if evidence is None:
                    continue
                payload = evidence["payload"]
                if commit is None or type(payload) is not dict:
                    _fail()
                commit_sha = commit["payload"].get("commit_sha")
                if not case._hex(commit_sha, 40) or set(commit["payload"]) != {"commit_sha"}:
                    _fail()
                if _time(evidence["recorded_at"]) < _time(commit["recorded_at"]):
                    _fail()
                if kind == "NORMAL_ACK" and not case._same(payload, {"commit_sha": commit_sha,
                        "writer_return_sha256": _sha(_raw(_writer_result(manifest["models"][position - 1], commit_sha)))}):
                    _fail()
                if kind == "WITNESS":
                    _witness(payload, manifest["models"][position - 1], commit_sha, manifest, evidence["recorded_at"])
        times = [manifest["case_persisted_at"]] + [v[0]["recorded_at"] for v in state["intents"].values()] + [v["recorded_at"] for v in state["evidence"].values()]
        state["latest"] = max(times, key=_time)
        return state
    except Exception:
        _fail("INVALID_SUBMISSION_STORE")


def _summary(manifest=None, state=None, reasons=(), reads=0, recovery=False):
    state = state or {"intents": {}, "evidence": {}}
    models = []
    for position, name in enumerate(case.MODELS, 1):
        evidence = state["evidence"]
        commit = evidence.get((position, "PUT_COMMIT"))
        ack = (position, "NORMAL_ACK") in evidence
        witness = evidence.get((position, "WITNESS"))
        status = ("EXTERNAL_FINGERPRINT_PRESENT_BEFORE_CUTOFF" if witness else
                  "NORMAL_WRITE_READBACK_CONFIRMED_RECEIPT_PENDING" if ack else
                  "COMMIT_KNOWN_READBACK_UNVERIFIED" if commit else
                  "INTENT_CONSUMED_RECOVERY_ONLY" if position in state["intents"] else "NOT_ATTEMPTED")
        models.append({"model_id": name, "status": status, "commit_sha": commit["payload"]["commit_sha"] if commit else None,
                       "normal_acknowledged": ack, "witness": witness["payload"] if witness else None})
    barrier = any(p in state["intents"] and (p, "NORMAL_ACK") not in state["evidence"] for p in range(1, 5))
    status = ("STOPPED_RECOVERY_ONLY" if barrier else "READ_ONLY_RECOVERY" if recovery else
              "NORMAL_READBACKS_COMPLETE_RECEIPTS_PENDING" if all(x["normal_acknowledged"] for x in models) else "DENIED")
    return {"schema": RESULT, "status": status, "reasons": sorted(set(reasons)),
        "manifest_sha256": _hash("MANIFEST", manifest) if manifest else None, "models": models,
        "dispatch_barrier": barrier, "github_reads": reads, "scope": "LOCAL_STORE_CALLBACK_ATTESTED",
        **dict.fromkeys(("official_prediction", "eligible_for_hit_at_8", "source_rights_verified",
            "producer_execution_authenticated", "full_private_payload_retention_verified",
            "global_exactly_once_verified", "cloned_store_protection_verified"), False)}


def _inspect(path, manifest, private, store):
    if not path.exists():
        return {"intents": {}, "evidence": {}, "latest": manifest["case_persisted_at"]}
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None)
    try:
        if not _stage(path, manifest, private, store, "POST_OPEN"):
            _fail()
        db.execute("BEGIN")
        result = _read(db, manifest)
        db.execute("COMMIT")
        return result
    except Exception:
        _fail("SUBMISSION_STORE_REJECTED")
    finally:
        db.close()


def _claim(manifest, position, phase, at):
    return {"schema": CLAIM, "manifest": manifest, "manifest_sha256": _hash("MANIFEST", manifest),
        "model_id": case.MODELS[position - 1], "position": position, "phase": phase, "checked_at": at,
        "plan": manifest["models"][position - 1]["plan"], "required_source_purposes": list(case.PURPOSES)}


def _admit(manifest, loaded, position, phase, at, callbacks, transport):
    claim = _claim(manifest, position, phase, at)
    row = next(r for r in loaded["request"]["ledger"]["records"] if r["race_id"] == loaded["request"]["race_id"])
    declarations = tuple((name, case.VERSIONS[name], case.MODEL_PIN) for name in case.MODELS)
    return all((_call(callbacks[0], claim, loaded["delivery"]["snapshot"]),
        _call(callbacks[1], claim, row), _call(callbacks[2], claim, declarations),
        _call(callbacks[3], claim), _call(callbacks[4], claim, transport)))


def _commit(db):
    try:
        db.execute("COMMIT")
    except Exception:
        _fail("LOCAL_COMMIT_UNCERTAIN_DO_NOT_WRITE")


def _evidence(db, path, manifest, position, kind, payload, clock, private, store):
    db.execute("BEGIN IMMEDIATE")
    state = _read(db, manifest)
    if position not in state["intents"] or (position, kind) in state["evidence"]:
        _fail()
    if not _stage(path, manifest, private, store, "POST_OPEN"):
        _fail()
    at = _now(clock, state["latest"])
    obj = {"manifest_sha256": _hash("MANIFEST", manifest), "intent_sha256": state["intents"][position][1],
           "recorded_at": at, "payload": _copy(payload)}
    db.execute("INSERT INTO submission_evidence VALUES(?,?,?,?)", (position, kind, _raw(obj).decode(), _hash("EVIDENCE", [position, kind, obj])))
    _read(db, manifest)
    if not _stage(path, manifest, private, store, "PRE_COMMIT"):
        _fail()
    _now(clock, at)
    _commit(db)


def dispatch_prepared_case(attempt_path, case_path, *, expected_request_sha256, expected_branch,
        submission_source_sha40, clock, private_path_verifier=None, admit_store=None, verify_source=None,
        verify_cutoff=None, admit_model_roster=None, independent_release_check=None, admit_transport=None, transport=None):
    clock = _tracked_clock(clock)
    entry = _entry(attempt_path, case_path, expected_request_sha256, expected_branch, submission_source_sha40,
                   private_path_verifier, admit_store)
    if entry is None:
        return _summary(reasons=["PRIVATE_STORE_NOT_ADMITTED"])
    path, manifest, loaded = entry
    state = _inspect(path, manifest, private_path_verifier, admit_store)
    _now(clock, state["latest"])
    result = _summary(manifest, state)
    if result["dispatch_barrier"] or all(m["normal_acknowledged"] for m in result["models"]):
        return result
    callbacks = (verify_source, verify_cutoff, admit_model_roster, independent_release_check, admit_transport)
    if not all(callable(f) for f in (*callbacks, transport)):
        return _summary(manifest, state, ["ACTION_NOT_ADMITTED"])
    position = len(state["intents"]) + 1
    try:
        at = _now(clock, state["latest"], manifest["sales_cutoff_at"])
        if not _admit(manifest, loaded, position, "PRE_INTENT", at, callbacks, transport):
            return _summary(manifest, state, ["ACTION_NOT_ADMITTED"])
        if not _stage(path, manifest, private_path_verifier, admit_store, "PRE_OPEN"):
            return _summary(manifest, state, ["PRIVATE_STORE_NOT_ADMITTED"])
        _now(clock, at, manifest["sales_cutoff_at"])
    except SubmissionError:
        return _summary(manifest, state, ["ACTION_OR_DEADLINE_NOT_ADMITTED"])
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    reads = 0  # Wrapper GET invocations, not authenticated server/retry counts.
    try:
        if not _stage(path, manifest, private_path_verifier, admit_store, "POST_OPEN"):
            _fail()
        db.execute("PRAGMA synchronous=FULL")
        for position in range(position, 5):
            db.execute("BEGIN IMMEDIATE")
            owned = _identity(db)
            state = _read(db, manifest)
            if _summary(manifest, state)["dispatch_barrier"]:
                db.execute("ROLLBACK")
                return _summary(manifest, state, reads=reads)
            if position <= len(state["intents"]):
                db.execute("ROLLBACK")
                continue
            at = _now(clock, state["latest"], manifest["sales_cutoff_at"])
            if not _admit(manifest, loaded, position, "PRE_INTENT", at, callbacks, transport):
                _fail("ACTION_NOT_ADMITTED")
            if not _stage(path, manifest, private_path_verifier, admit_store, "POST_OPEN"):
                _fail()
            at = _now(clock, at, manifest["sales_cutoff_at"])
            if not owned:
                for statement in SQL:
                    db.execute(statement)
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
                db.execute("INSERT INTO submission_manifest VALUES(1,?,?)", (_raw(manifest).decode(), _hash("MANIFEST", manifest)))
            intent = {"manifest_sha256": _hash("MANIFEST", manifest), "model_id": case.MODELS[position - 1],
                      "position": position, "recorded_at": at, "gates": dict.fromkeys(GATES, True)}
            db.execute("INSERT INTO submission_intents VALUES(?,?,?)", (position, _raw(intent).decode(), _hash("INTENT", intent)))
            if not _stage(path, manifest, private_path_verifier, admit_store, "PRE_COMMIT"):
                _fail()
            edge = _now(clock, at, manifest["sales_cutoff_at"])
            _commit(db)  # Any error here leaves the writer uncalled, even if COMMIT actually succeeded.
            model, stage, broken, captured = manifest["models"][position - 1], 0, False, None
            raw = _raw(model["plan"]["anchor"]) + b"\n"
            url = BASE + "/contents/" + model["plan"]["path"]
            body = _raw({"message": "audit: create forecast hash fingerprint", "content": base64.b64encode(raw).decode(), "branch": expected_branch}) + b"\n"
            def guarded(given_url, method, data=None):
                nonlocal stage, broken, captured, edge, reads
                try:
                    if broken:
                        _fail()
                    if stage == 0 and (given_url, method, data) == (url, "PUT", body):
                        stage = 1  # Consume even when the transport/last gate later fails.
                        edge = _now(clock, edge, manifest["sales_cutoff_at"])
                        if not _admit(manifest, loaded, position, "PRE_PUT", edge, callbacks, transport):
                            _fail()
                        if not _stage(path, manifest, private_path_verifier, admit_store, "PRE_COMMIT"):
                            _fail()
                        edge = _now(clock, edge, manifest["sales_cutoff_at"])
                        response = transport(url, "PUT", body)
                        commit = response.get("commit", {}).get("sha") if type(response) is dict and type(response.get("commit")) is dict else None
                        if not case._hex(commit, 40):
                            _fail()
                        _evidence(db, path, manifest, position, "PUT_COMMIT", {"commit_sha": commit}, clock, private_path_verifier, admit_store)
                        captured = commit
                        return {"commit": {"sha": commit}}
                    if stage == 1 and captured is not None and (given_url, method, data) == (url + "?ref=" + captured, "GET", None):
                        stage = 2
                        reads += 1
                        response = transport(given_url, "GET", None)
                        if (type(response) is not dict or response.get("type") != "file" or response.get("encoding") != "base64"
                                or type(response.get("content")) is not str or len(response["content"]) > 100000):
                            _fail()
                        content = base64.b64decode("".join(response["content"].split()), validate=True)
                        if content != raw:
                            _fail()
                        return {"type": "file", "encoding": "base64", "content": base64.b64encode(content).decode()}
                    _fail()
                except Exception:
                    broken = True
                    _fail("GUARDED_SUBMISSION_STOPPED")
            original_plan = _copy(model["plan"])
            returned = submit_anchor(original_plan, expected_branch, "EXPLICIT_TRANSPORT_NO_CREDENTIAL", lambda plan: case._same(plan, model["plan"]), request=guarded)
            expected = _writer_result(model, captured)
            if broken or stage != 2 or captured is None or not case._same(original_plan, model["plan"]) or not case._same(returned, expected):
                _fail()
            _evidence(db, path, manifest, position, "NORMAL_ACK", {"commit_sha": captured,
                      "writer_return_sha256": _sha(_raw(expected))}, clock, private_path_verifier, admit_store)
        return _summary(manifest, _inspect(path, manifest, private_path_verifier, admit_store), reads=reads)
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        return _summary(manifest, _inspect(path, manifest, private_path_verifier, admit_store), ["SUBMISSION_STOPPED_DO_NOT_RETRY"], reads)
    finally:
        db.close()


def recover_submission_attempts(attempt_path, case_path, *, expected_request_sha256, expected_branch,
        submission_source_sha40, clock, private_path_verifier=None, admit_store=None, admit_reader=None,
        github_fetch=None, trusted_legacy_verifier=None):
    clock = _tracked_clock(clock)
    entry = _entry(attempt_path, case_path, expected_request_sha256, expected_branch, submission_source_sha40,
                   private_path_verifier, admit_store)
    if entry is None:
        return _summary(reasons=["PRIVATE_STORE_NOT_ADMITTED"], recovery=True)
    path, manifest, loaded = entry
    state = _inspect(path, manifest, private_path_verifier, admit_store)
    _now(clock, state["latest"])
    known = [p for p in state["intents"] if (p, "PUT_COMMIT") in state["evidence"] and (p, "WITNESS") not in state["evidence"]]
    if not known:
        return _summary(manifest, state, recovery=True)
    if (not callable(github_fetch) or not callable(trusted_legacy_verifier)
            or not _call(admit_reader, manifest, github_fetch, trusted_legacy_verifier)):
        return _summary(manifest, state, ["READER_NOT_ADMITTED"], recovery=True)
    reads = 0
    db = None
    try:
        try:
            # Recovery may append evidence to an existing store, never create it.
            db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=30, isolation_level=None)
            if not _stage(path, manifest, private_path_verifier, admit_store, "POST_OPEN"):
                _fail()
            db.execute("BEGIN")
            state = _read(db, manifest)
            _now(clock, state["latest"])
            db.execute("COMMIT")
            db.execute("PRAGMA synchronous=FULL")
        except Exception:
            _fail("RECOVERY_STORE_REOPEN_REJECTED")
        known = [p for p in state["intents"] if (p, "PUT_COMMIT") in state["evidence"] and (p, "WITNESS") not in state["evidence"]]
        for position in known:
            model = manifest["models"][position - 1]
            commit = state["evidence"][(position, "PUT_COMMIT")]["payload"]["commit_sha"]
            def fetch(url):
                nonlocal reads
                reads += 1
                return github_fetch(url)
            try:
                witness = resolve_anchor_witness(_copy(model["plan"]), commit, manifest["case_persisted_at"],
                    expected_branch=expected_branch, github_fetch=fetch, trusted_legacy_verifier=trusted_legacy_verifier, clock=clock)
                _evidence(db, path, manifest, position, "WITNESS", witness, clock, private_path_verifier, admit_store)
            except Exception:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                return _summary(manifest, _inspect(path, manifest, private_path_verifier, admit_store), ["WITNESS_UNRESOLVED_DO_NOT_WRITE"], reads, True)
        return _summary(manifest, _inspect(path, manifest, private_path_verifier, admit_store), reads=reads, recovery=True)
    finally:
        if db is not None:
            db.close()
