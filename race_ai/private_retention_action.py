"""One irreversible private action in the existing owner; no default writer.

Local callback readback is not independent retention evidence or authority.
Only a normally returned COMMIT owns the one injected create invocation.
"""
from functools import wraps
import json
import re
import sqlite3

from . import permissioned_case_submission as core
from . import retained_case_submission as owner
from . import private_wire_retention as retention

CONTRACT = "PRIVATE_ACTION_V3"
CANDIDATE = "RACE_AI_PRIVATE_RETENTION_ACTION_V3"
ROW = "RACE_AI_PRIVATE_RETENTION_ACTION_ROW_V3"
CLAIM = "RACE_AI_PRIVATE_RETENTION_ACTION_CLAIM_V3"
RESULT = "RACE_AI_PRIVATE_RETENTION_ACTION_RESULT_V3"
ADAPTER = {
    "schema": "RACE_AI_PRIVATE_RETENTION_LOCAL_ADAPTER_V1",
    "destination_contract": "LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1",
    "runtime_scope": "EXPLICIT_INJECTED_LOCAL_TEST_CANDIDATE_ONLY",
    "source_commit_sha40": "9aeb2b425de9d05a44cb31f72a242a5111ada80a",
    "vault_module_sha256": "383264d3a676e04fc91a6c4956ef79d5bda709a09f6ad5b03e0d6062b6891024",
    "vault_schema_sha256": "950646a723ba6b6fed4446084a9f1510fb18b1540dcc0c5c5ff1cba0eae41b0c",
    "native_test_adapter_sha256": "04c26b80e27110b891e297a0d615cf99e9db84446f4d1ee978274f64f88db215"}
FALSE_FLAGS = ("independent_retention_proof", "full_private_payload_retention_verified", "source_rights_verified",
    "producer_execution_authenticated", "coordinator_authenticated", "global_exactly_once_verified",
    "cloned_store_protection_verified", "official_prediction", "eligible_for_hit_at_8")
ADMISSIONS = ("source_storage", "owner_destination", "coordinator", "cutoff", "roster", "private_action",
              "private_adapter", "path", "store")
SQL = ("CREATE TABLE submission_private_action(id INTEGER PRIMARY KEY CHECK(id=1),json TEXT NOT NULL,sha256 TEXT NOT NULL)",) + tuple(
    "CREATE TRIGGER submission_private_action_no_" + verb.lower() + " BEFORE " + verb +
    " ON submission_private_action BEGIN SELECT RAISE(ABORT,'immutable submission'); END" for verb in ("UPDATE", "DELETE")) + (
    "CREATE TRIGGER submission_private_action_no_replace BEFORE INSERT ON submission_private_action WHEN EXISTS(SELECT 1 FROM submission_private_action WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'immutable submission'); END",)


def _fail():
    raise ValueError("PRIVATE_RETENTION_ACTION_REJECTED") from None


def _safe(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            _fail()
    return call


def _copy(value, limit=core.LIMIT):
    """Bound exact integers before the unchanged retention walk calls abs()."""
    count, active = 0, set()
    def walk(node, depth=0):
        nonlocal count
        count += 1
        if depth > 24 or count > 100000:
            _fail()
        kind = type(node)
        if kind is int:
            if node < -10**15 or node > 10**15:
                _fail()
        elif kind in (dict, list):
            if len(node) > 100000 or id(node) in active:
                _fail()
            active.add(id(node))
            if kind is dict:
                for key, item in node.items():
                    if type(key) is not str:
                        _fail()
                    walk(key, depth + 1)
                    walk(item, depth + 1)
            else:
                for item in node:
                    walk(item, depth + 1)
            active.remove(id(node))
        elif kind is str:
            if len(node) > 16384:
                _fail()
        elif node is not None and kind not in (bool, float):
            _fail()
    walk(value)
    return retention._copy(value, limit)


def _declaration(value):
    value = _copy(value)
    if not owner._same(value, ADAPTER):
        _fail()
    return value


def _call(function, *args, **kwargs):
    if not callable(function):
        return False
    owned = [_copy(v) if type(v) in (dict, list) else v for v in args]
    before = [retention._raw(v) if type(v) in (dict, list) else None for v in owned]
    verdict = function(*owned, **kwargs)
    try:
        unchanged = all(raw is None or raw == retention._raw(_copy(v)) for raw, v in zip(before, owned))
    except Exception:
        return False  # Invalid callback mutation is denial, with no large serialization.
    return verdict is True and unchanged


def _stage(path, c, private, store, stage):
    return (core.case._private(path, private, stage) and _call(store, path, c, stage=stage)
            and core.case._path(path) == path)


def _destination(destination):
    if (destination["adapter_contract_sha256"] != retention._hash(ADAPTER["schema"], ADAPTER)
            or type(destination["destination_ref"]) is not str
            or re.fullmatch(r"local-private-vault-[a-z0-9-]{1,64}", destination["destination_ref"]) is None
            or re.fullmatch(r"[\x20-\x7e]{1,128}", destination["owner_scope_ref"]) is None
            or destination["owner_scope_ref"].strip() != destination["owner_scope_ref"]):
        _fail()


def _utc(value):
    if (type(value) is not str or len(value) > 32 or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value) is None):
        _fail()
    core._time(value)


def _vault(c, loaded, rows):
    _destination(c["destination"])
    _utc(rows["reservation_commit_guard_at"])
    _utc(c["retention_policy"]["retain_until"])
    wire = loaded["wire"]
    if type(wire) is not bytes or not 0 < len(wire) <= retention.WIRE_LIMIT:
        _fail()
    request = owner._request(c, loaded)
    result = {"schema": "RACE_AI_LOCAL_PRIVATE_WIRE_CLAIM_V1", "destination_contract": ADAPTER["destination_contract"],
        "destination_ref": c["destination"]["destination_ref"], "owner_ref": c["destination"]["owner_scope_ref"],
        "request_sha256": loaded["request_sha256"], "wire_sha256": loaded["wire_sha256"],
        "delivery_sha256": loaded["delivery_sha256"], "model_source_sha40": loaded["request"]["model_source_sha40"],
        "retention_request_sha256": retention._hash(retention.REQUEST, request),
        "reservation_sha256": retention._hash(owner._schema(owner.C_SCHEMA, CONTRACT), c),
        **{key: rows[key] for key in owner.ROW_FIELDS[:2]}, "retain_until": c["retention_policy"]["retain_until"],
        "protection_policy": "LOCAL_INSERT_ONLY_SQL_V1", "wire_bytes": len(wire),
        "chunk_sha256": [core._sha(wire[i:i + 524288]) for i in range(0, len(wire), 524288)]}
    return _copy(result, 8192)


def _locator(claim):
    return retention._hash("RACE_AI_LOCAL_PRIVATE_WIRE_LOCATOR_V1", claim)


def _candidate(c, loaded, rows, at):
    claim = _vault(c, loaded, rows)
    if not core._time(rows["reservation_commit_guard_at"]) <= core._time(at) < core._time(c["base_manifest"]["sales_cutoff_at"]):
        _fail()
    return _copy({"schema": CANDIDATE, "submission_contract": CONTRACT,
        "action_kind": "CREATE_LOCAL_PRIVATE_WHOLE_WIRE", "phase": "PRE_PRIVATE_INTENT",
        "case_request_sha256": loaded["request_sha256"], "reservation_sha256": claim["reservation_sha256"],
        **{key: rows[key] for key in owner.ROW_FIELDS[:2]}, "retention_request_sha256": claim["retention_request_sha256"],
        "vault_claim": claim, "vault_locator": _locator(claim), "private_adapter_declaration": _declaration(ADAPTER),
        "candidate_at": at, "window": {"through_cutoff_at": c["base_manifest"]["sales_cutoff_at"],
            "retain_until": c["retention_policy"]["retain_until"], "purposes": list(core.case.PURPOSES)}})


def _stored(db, c, loaded, rows):
    sizes = db.execute("SELECT id,typeof(json),length(CAST(json AS BLOB)),typeof(sha256),length(CAST(sha256 AS BLOB)) FROM submission_private_action").fetchmany(2)
    if (len(sizes) > 1 or any(r[:2] != (1, "text") or not 0 < r[2] <= core.LIMIT or r[3:] != ("text", 64) for r in sizes)):
        _fail()
    if not sizes:
        return None
    text, digest = db.execute("SELECT json,sha256 FROM submission_private_action").fetchone()
    obj = _copy(json.loads(text))
    retention._exact(obj, {"schema", "action", "admissions", "commit_guard_at"})
    action = obj["action"]
    if (retention._raw(obj).decode() != text or not core.case._hex(digest) or digest != retention._hash(ROW, obj)
            or obj["schema"] != ROW or not owner._same(obj["admissions"], dict.fromkeys(ADMISSIONS, True))
            or not owner._same(action, _candidate(c, loaded, rows, action["candidate_at"]))
            or core._time(action["candidate_at"]).isoformat() != action["candidate_at"]
            or core._time(obj["commit_guard_at"]).isoformat() != obj["commit_guard_at"]
            or not core._time(action["candidate_at"]) <= core._time(obj["commit_guard_at"]) < core._time(c["base_manifest"]["sales_cutoff_at"])):
        _fail()
    return obj


def _summary(p=None, status=None, reason=None, creates=0, reads=0, readback=None):
    a = p["action"] if p else None
    return {"schema": RESULT, "status": status or ("PRIVATE_ACTION_CONSUMED_READ_ONLY" if p else "DENIED"),
        "reasons": [reason] if reason else [], "scope": "LOCAL_CONTRACT_CALLBACK_ATTESTED",
        "private_action_consumed": p is not None, "private_action_sha256": retention._hash(ROW, p) if p else None,
        "private_action_candidate_sha256": retention._hash(CANDIDATE, a) if p else None,
        "private_action_commit_guard_at": p["commit_guard_at"] if p else None, "private_action": p,
        "vault_claim": a["vault_claim"] if p else None, "vault_locator": a["vault_locator"] if p else None,
        "create_calls": creates, "read_calls": reads, "readback": readback, **dict.fromkeys(FALSE_FLAGS, False)}


def _claim(a, p, phase, at):
    return {"schema": CLAIM, "phase": phase, "candidate": a, "candidate_sha256": retention._hash(CANDIDATE, a),
        "private_action_sha256": retention._hash(ROW, p) if p else None,
        "private_action_commit_guard_at": p["commit_guard_at"] if p else None, "checked_at": at}


def _prerequisite(c, loaded, rows, a):
    return {"reservation": c, "reservation_sha256": a["reservation_sha256"],
        **{key: rows[key] for key in owner.ROW_FIELDS[:2]}, "retention_request": owner._request(c, loaded),
        "retention_request_sha256": a["retention_request_sha256"], "vault_claim": a["vault_claim"],
        "vault_locator": a["vault_locator"], "private_adapter_declaration": a["private_adapter_declaration"]}


def _admit(path, c, loaded, rows, a, p, phase, at, gates, create):
    private, store, source, destination, coordinator, cutoff, roster, action, adapter = gates
    claim = _claim(a, p, phase, at)
    required = _prerequisite(c, loaded, rows, a)
    request = required["retention_request"]
    row = next(r for r in loaded["request"]["ledger"]["records"] if r["race_id"] == loaded["request"]["race_id"])
    declarations = tuple((m["model_id"], m["model_version"], loaded["request"]["model_source_sha40"])
                         for m in c["base_manifest"]["models"])
    decisions = [_call(source, request, loaded["delivery"]["snapshot"]), _call(destination, request),
        _call(coordinator, request, c["coordinator_binding"]), _call(cutoff, claim, row),
        _call(roster, claim, declarations), _call(action, claim, required),
        _call(adapter, claim, ADAPTER, create), _stage(path, c, private, store, "PRE_COMMIT")]
    return all(decisions)


def _operation(function, a, loaded, *, read=False):
    owned = _copy(a["vault_claim"], 8192)
    result = function(owned, a["vault_locator"] if read else loaded["wire"])
    if not owner._same(_copy(owned, 8192), a["vault_claim"]) or type(result) is not dict:
        _fail()
    fields = {"schema", "status", "scope", "locator", "claim", "wire", "wire_sha256", "wire_bytes", "chunk_count", "retention_status"} | set(FALSE_FLAGS)
    if len(result) != len(fields):
        _fail()
    retention._exact(result, fields)
    body = result["wire"]
    metadata = _copy({key: value for key, value in result.items() if key != "wire"})
    status = metadata["status"]
    if (status not in (("LOCAL_READBACK", "UNRESOLVED") if read else ("LOCAL_CREATED", "LOCAL_READBACK"))
            or any(metadata[key] is not False for key in FALSE_FLAGS)
            or metadata["schema"] != "RACE_AI_LOCAL_PRIVATE_WIRE_RESULT_V1" or metadata["scope"] != "LOCAL_ONLY"
            or metadata["retention_status"] != "RETENTION_UNVERIFIED" or metadata["locator"] != a["vault_locator"]
            or not owner._same(metadata["claim"], a["vault_claim"]) or metadata["wire_sha256"] != loaded["wire_sha256"]
            or type(metadata["wire_bytes"]) is not int or metadata["wire_bytes"] != len(loaded["wire"])
            or type(metadata["chunk_count"]) is not int or metadata["chunk_count"] != len(a["vault_claim"]["chunk_sha256"])
            or (body is not None if status == "UNRESOLVED" else type(body) is not bytes or body != loaded["wire"])):
        _fail()
    return {**metadata, "wire": body}


def _values(path, base, loaded, private, store, expected):
    if not core.case._hex(expected):
        _fail()
    db = owner._open(path, private)
    try:
        db.execute("BEGIN")
        c, e, _, rows = owner._rows(db, base, loaded, expected, CONTRACT)
        manifest = owner._manifest(c, e, rows)
        if not _stage(path, c, private, store, "POST_OPEN"):
            return None
        core._read(db, manifest, loaded)
        p = _stored(db, c, loaded, rows)
        db.execute("COMMIT")
        return c, rows, p
    finally:
        db.close()


def _edge(path, base, loaded, expected, p, timer, previous, cutoff=None):
    """No admission callbacks after the last fresh clock and exact RO snapshot.

    Detect deterministic owner disappearance/replacement at this local boundary;
    this does not authenticate a hostile filesystem or exclude cloned stores.
    """
    if core.case._path(path) != path:
        _fail()
    before = core.case._lstat(path)
    if before is None:
        _fail()
    identity = (before.st_dev, before.st_ino)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None)
    try:
        db.execute("BEGIN")
        if not core._identity(db, CONTRACT):
            _fail()
        # Account for SQLite acquisition delay before sampling the final clock.
        core._now(timer, previous, cutoff)
        c, e, _, rows = owner._rows(db, base, loaded, expected, CONTRACT)
        actual = _stored(db, c, loaded, rows)
        if not owner._same(actual, p):
            _fail()
        core._read(db, owner._manifest(c, e, rows), loaded)
        db.execute("COMMIT")
    finally:
        db.close()
    after = core.case._lstat(path) if core.case._path(path) == path else None
    if after is None or (after.st_dev, after.st_ino) != identity:
        _fail()


@_safe
def consume_private_retention_action(attempt_path, case_path, *, expected_request_sha256,
        expected_reservation_sha256, expected_branch, submission_source_sha40, private_adapter_declaration=None,
        clock=None, private_path_verifier=None, admit_store=None, admit_source_storage=None,
        admit_owner_destination=None, admit_coordinator=None, verify_cutoff=None, admit_model_roster=None,
        admit_private_action=None, admit_private_adapter=None, private_create=None):
    entry = owner._candidate(attempt_path, case_path, expected_request_sha256, expected_branch,
        submission_source_sha40, private_path_verifier, admit_store)
    if entry is None:
        return _summary(reason="PRIVATE_STORE_NOT_ADMITTED")
    path, base, loaded = entry
    values = _values(path, base, loaded, private_path_verifier, admit_store, expected_reservation_sha256)
    if values is None:
        return _summary(reason="PRIVATE_STORE_NOT_ADMITTED")
    c, rows, p = values
    if p:
        if private_adapter_declaration is not None:
            _declaration(private_adapter_declaration)
        return _summary(p)
    gates = (private_path_verifier, admit_store, admit_source_storage, admit_owner_destination, admit_coordinator,
             verify_cutoff, admit_model_roster, admit_private_action, admit_private_adapter)
    if private_adapter_declaration is None or not all(callable(f) for f in (*gates, private_create, clock)):
        return _summary(reason="PRIVATE_ACTION_NOT_ADMITTED")
    _declaration(private_adapter_declaration)
    timer = core._tracked_clock(clock)
    at = core._now(timer, rows["reservation_commit_guard_at"], base["sales_cutoff_at"])
    a = _candidate(c, loaded, rows, at)
    if not _admit(path, c, loaded, rows, a, None, "PRE_PRIVATE_INTENT", at, gates, private_create):
        return _summary(reason="PRIVATE_ACTION_NOT_ADMITTED")
    db = owner._open(path, private_path_verifier, writable=True)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        c, _, _, rows = owner._rows(db, base, loaded, expected_reservation_sha256, CONTRACT)
        previous = _stored(db, c, loaded, rows)
        if previous:
            db.execute("ROLLBACK")
            return _summary(previous)
        at = core._now(timer, at, base["sales_cutoff_at"])
        if not _admit(path, c, loaded, rows, a, None, "PRE_PRIVATE_INTENT", at, gates, private_create):
            db.execute("ROLLBACK")
            return _summary(reason="PRIVATE_ACTION_NOT_ADMITTED")
        guard = core._now(timer, at, base["sales_cutoff_at"])
        p = _copy({"schema": ROW, "action": a, "admissions": dict.fromkeys(ADMISSIONS, True), "commit_guard_at": guard})
        db.execute("INSERT INTO submission_private_action VALUES(1,?,?)", (retention._raw(p).decode(), retention._hash(ROW, p)))
        core._commit(db)
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    calls = 0
    try:
        at = core._now(timer, p["commit_guard_at"], base["sales_cutoff_at"])
        if not _admit(path, c, loaded, rows, a, p, "PRE_PRIVATE_CREATE", at, gates, private_create):
            return _summary(p, reason="PRIVATE_CREATE_NOT_ADMITTED")
        _edge(path, base, loaded, expected_reservation_sha256, p, timer, at, base["sales_cutoff_at"])
        calls = 1
        result = _operation(private_create, a, loaded)
        return _summary(p, "LOCAL_PRIVATE_READBACK_UNVERIFIED", creates=calls, readback=result)
    except Exception:
        return _summary(p, reason="PRIVATE_CREATE_UNRESOLVED_DO_NOT_RETRY", creates=calls)


@_safe
def read_private_retention_action(attempt_path, case_path, *, expected_request_sha256,
        expected_reservation_sha256, expected_private_action_sha256, clock, private_path_verifier=None,
        admit_store=None, admit_private_reader=None, private_read=None):
    if not callable(private_path_verifier) or not callable(admit_store):
        return _summary(status="PRIVATE_READ_UNRESOLVED", reason="PRIVATE_STORE_NOT_ADMITTED")
    path = core.case._path(attempt_path)
    loaded = core.case.load_case(case_path, expected_request_sha256=expected_request_sha256, private_path_verifier=private_path_verifier)
    db = owner._open(path, private_path_verifier)
    try:
        db.execute("BEGIN")
        if not core._identity(db, CONTRACT):
            _fail()
        sizes = db.execute("SELECT typeof(json),length(CAST(json AS BLOB)) FROM submission_reservation").fetchmany(2)
        if len(sizes) != 1 or sizes[0][0] != "text" or not 0 < sizes[0][1] <= core.LIMIT:
            _fail()
        base = _copy(json.loads(db.execute("SELECT json FROM submission_reservation").fetchone()[0]))["reservation"]["base_manifest"]
    finally:
        db.close()
    entry = owner._candidate(path, case_path, expected_request_sha256, base["branch"], base["submission_source_sha40"], private_path_verifier, admit_store)
    if entry is None:
        return _summary(status="PRIVATE_READ_UNRESOLVED", reason="PRIVATE_STORE_NOT_ADMITTED")
    _, base, loaded = entry
    values = _values(path, base, loaded, private_path_verifier, admit_store, expected_reservation_sha256)
    if values is None:
        return _summary(status="PRIVATE_READ_UNRESOLVED", reason="PRIVATE_STORE_NOT_ADMITTED")
    c, rows, p = values
    if not p:
        return _summary(status="PRIVATE_READ_UNRESOLVED", reason="PRIVATE_ACTION_ABSENT")
    if not core.case._hex(expected_private_action_sha256) or expected_private_action_sha256 != retention._hash(ROW, p):
        _fail()
    if not callable(private_read) or not callable(admit_private_reader):
        return _summary(p, "PRIVATE_READ_UNRESOLVED", "PRIVATE_READER_NOT_ADMITTED")
    calls = 0
    try:
        timer = core._tracked_clock(clock)
        at = core._now(timer, p["commit_guard_at"])
        a = p["action"]
        if (not _call(admit_private_reader, _claim(a, p, "PRIVATE_READ_RECOVERY", at), _prerequisite(c, loaded, rows, a), private_read)
                or not _stage(path, c, private_path_verifier, admit_store, "POST_OPEN")):
            return _summary(p, "PRIVATE_READ_UNRESOLVED", "PRIVATE_READER_NOT_ADMITTED")
        _edge(path, base, loaded, expected_reservation_sha256, p, timer, at)
        calls = 1
        result = _operation(private_read, a, loaded, read=True)
        return _summary(p, "PRIVATE_READ_UNRESOLVED" if result["status"] == "UNRESOLVED" else "LOCAL_PRIVATE_READBACK_UNVERIFIED", reads=calls, readback=result)
    except Exception:
        return _summary(p, "PRIVATE_READ_UNRESOLVED", "PRIVATE_READ_UNRESOLVED", reads=calls)
