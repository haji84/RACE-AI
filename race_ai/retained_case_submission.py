"""Prospective retention-required profile of the sole local attempt store.

No private writer, new model, service, global registry or authenticated receipt.
Recorded callbacks remain claims; replay renews none. Whole wire stays in case.
"""
from functools import wraps
import json
import sqlite3

from . import permissioned_case_submission as core
from . import private_wire_retention as retention

CONTRACT = "RETAINED_V2"
C_SCHEMA = "RACE_AI_RETAINED_SUBMISSION_RESERVATION_V2"
E_SCHEMA = "RACE_AI_RETAINED_SUBMISSION_ADMISSION_V2"
C_ROW = "RACE_AI_RETAINED_RESERVATION_ROW_V2"
E_ROW = "RACE_AI_RETAINED_ADMISSION_ROW_V2"
ROW_FIELDS = ("reservation_row_sha256", "reservation_commit_guard_at", "retention_row_sha256", "retention_commit_guard_at")
SLOT_SCHEMA = "RACE_AI_PROSPECTIVE_COMPARISON_SLOT_V1"
COORDINATOR_SHA = core._sha(b"RACE_AI_RETAINED_V2_PRE_PUBLIC_FULL_SLOT_ASSIGNMENT_V1")
EXTRA_SQL = (
    "CREATE TABLE submission_reservation(id INTEGER PRIMARY KEY CHECK(id=1),json TEXT NOT NULL,sha256 TEXT NOT NULL)",
    "CREATE TABLE submission_retention(id INTEGER PRIMARY KEY CHECK(id=1),json TEXT NOT NULL,proof BLOB NOT NULL,sha256 TEXT NOT NULL)",
) + tuple("CREATE TRIGGER " + table + "_no_" + verb.lower() + " BEFORE " + verb + " ON " + table +
          " BEGIN SELECT RAISE(ABORT,'immutable submission'); END"
          for table in ("submission_reservation", "submission_retention") for verb in ("UPDATE", "DELETE"))
C_FIELDS = {"schema", "submission_contract", "slot", "assignment_ref", "base_manifest", "destination",
            "retention_policy", "coordinator_binding", "reserved_at", "wire_byte_count"}
E_FIELDS = {"schema", "reservation_sha256", "retention_request", "retention_request_sha256", "readback_descriptor",
            "receipt_claims", "receipt_proof_sha256", "readback_sha256", "readback_byte_count", "verdicts",
            "verification", "admitted_at", "reservation_row_sha256", "reservation_commit_guard_at"}


PRIVATE_CONTRACT = "PRIVATE_ACTION_V3"
P_FIELDS = ("private_action_sha256", "private_action_commit_guard_at")


def _version(contract):
    if contract not in (CONTRACT, PRIVATE_CONTRACT):
        core._fail()
    return 3 if contract == PRIVATE_CONTRACT else 2


def _schema(value, contract):
    return value[:-1] + str(_version(contract))


def _fields(contract):
    return ROW_FIELDS + (P_FIELDS if _version(contract) == 3 else ())


def _sql(contract):
    if _version(contract) == 3:
        from .private_retention_action import SQL
        return EXTRA_SQL + SQL
    return EXTRA_SQL


def _safe(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            core._fail("RETAINED_SUBMISSION_REJECTED")
    return call


def _hash(schema, value):
    return retention._hash(schema, value)


def _copy(value):
    return retention._copy(value)


def _same(left, right):
    return retention._raw(left) == retention._raw(right)


def _response(c=None, e=None, reason=None, rows=None):
    contract = c["submission_contract"] if c else CONTRACT
    value = {"status": "DENIED" if reason else "RETENTION_RECORDED" if e else "RESERVATION_RECORDED",
             "reasons": [reason] if reason else [], **retention._flags()}
    if c:
        value.update(reservation_sha256=_hash(_schema(C_SCHEMA, c["submission_contract"]), c), reservation=c, base_binding=c["coordinator_binding"])
    if e:
        value.update(retention_request_sha256=e["retention_request_sha256"],
                     retention_admission_sha256=_hash(_schema(E_SCHEMA, c["submission_contract"]), e), retention_request=e["retention_request"], evidence=e)
    if rows:
        value.update({key: rows[key] if e or key in ROW_FIELDS[:2] else None for key in _fields(contract)})
    return value


def _candidate(attempt, case_path, expected, branch, pin, private, store):
    if not callable(private) or not callable(store):
        return None
    return core._entry(attempt, case_path, expected, branch, pin, private, store, candidate_only=True)


def _reservation(base, loaded, slot, assignment, destination, policy, at, contract=CONTRACT):
    _version(contract)
    slot, destination, policy = map(_copy, (slot, destination, policy))
    retention._exact(slot, {"schema", "scope_ref", "race_id", "race_revision", "as_of_utc", "model_ids"})
    retention._ref(assignment)
    retention._ref(slot["scope_ref"])
    race = loaded["delivery"]["snapshot"]["race"]
    if (slot["schema"] != SLOT_SCHEMA or slot["race_id"] != loaded["request"]["race_id"]
            or type(slot["race_revision"]) is not int or slot["race_revision"] != race["race_revision"]
            or slot["model_ids"] != list(core.case.MODELS) or core._time(slot["as_of_utc"]) != core._time(race["as_of"])):
        core._fail()
    slot["as_of_utc"] = core._time(slot["as_of_utc"]).isoformat()
    binding = {"schema": retention.BASE, "scope": "PRE_PUBLIC_BASE_ONLY", "coordinator_ref": assignment,
        "contract_sha256": (COORDINATOR_SHA if contract == CONTRACT else core._sha(b"RACE_AI_RETAINED_V3_PRE_PUBLIC_FULL_SLOT_PRIVATE_ACTION_V1")), "case_request_sha256": loaded["request_sha256"],
        "wire_sha256": loaded["wire_sha256"], "ordered_plans_sha256": _hash("RACE_AI_RETENTION_ORIGINAL_PLANS_V1", loaded["plans"]),
        "destination_sha256": _hash("RACE_AI_RETENTION_DESTINATION_V1", destination)}
    binding["base_binding_sha256"] = _hash(retention.BASE, binding)
    settings = retention._settings(destination, policy, binding)
    if settings is None or retention._request(loaded, settings) is None:
        core._fail()
    if contract == PRIVATE_CONTRACT:
        from .private_retention_action import _destination
        _destination(destination)
    at = core._time(at).isoformat()
    if not core._time(loaded["persisted_at"]) <= core._time(at) < core._time(base["sales_cutoff_at"]):
        core._fail()
    return _copy({"schema": _schema(C_SCHEMA, contract), "submission_contract": contract, "slot": slot, "assignment_ref": assignment,
        "base_manifest": base, "destination": destination, "retention_policy": policy,
        "coordinator_binding": binding, "reserved_at": at, "wire_byte_count": len(loaded["wire"])})


def _check_c(c, base, loaded):
    retention._exact(c, C_FIELDS)
    expected = _reservation(base, loaded, c["slot"], c["assignment_ref"], c["destination"], c["retention_policy"], c["reserved_at"], c["submission_contract"])
    if not _same(c, expected):
        core._fail()


def _request(c, loaded):
    return retention._request(loaded, retention._settings(c["destination"], c["retention_policy"], c["coordinator_binding"]))


def _check_e(c, e, proof, loaded, rows):
    contract = c["submission_contract"]
    retention._exact(e, E_FIELDS | (set(P_FIELDS) if contract == PRIVATE_CONTRACT else set()))
    if type(proof) is not bytes or not 0 < len(proof) <= core.LIMIT:
        core._fail()
    request = _request(c, loaded)
    descriptor = retention._evidence_metadata(e["readback_descriptor"], retention.READBACK, retention.READBACK_FIELDS)
    receipt = retention._evidence_metadata(e["receipt_claims"], retention.RECEIPT, retention.RECEIPT_FIELDS)
    retention._evidence_links(request, descriptor, receipt)
    verdicts = dict.fromkeys(("source_storage", "owner_destination", "coordinator"), True)
    if (e["schema"] != _schema(E_SCHEMA, contract) or e["reservation_sha256"] != _hash(_schema(C_SCHEMA, c["submission_contract"]), c)
            or not _same(e["retention_request"], request) or e["retention_request_sha256"] != _hash(retention.REQUEST, request)
            or e["receipt_proof_sha256"] != core._sha(proof) or e["readback_sha256"] != loaded["wire_sha256"]
            or type(e["readback_byte_count"]) is not int or e["readback_byte_count"] != len(loaded["wire"])
            or not _same(e["verdicts"], verdicts) or descriptor is None or receipt is None):
        core._fail()
    if any(e[key] != rows[key] for key in ROW_FIELDS[:2] + (P_FIELDS if contract == PRIVATE_CONTRACT else ())):
        core._fail()
    verification = e["verification"]
    expected = {"schema": retention.EVIDENCE, "status": "ADMITTED_BY_CALLBACK", "case_request_sha256": loaded["request_sha256"],
        "request_sha256": e["retention_request_sha256"], "wire_sha256": loaded["wire_sha256"], "wire_byte_count": len(loaded["wire"]),
        "readback_descriptor_sha256": _hash(retention.READBACK, descriptor), "receipt_claims_sha256": _hash(retention.RECEIPT, receipt),
        "receipt_proof_sha256": core._sha(proof), "observed_at": verification["observed_at"], "whole_wire_equal": True,
        "protected_readback_admitted_by_callback": True, "receipt_admitted_by_callback": True, "reasons": [], **retention._flags()}
    if (not _same(verification, expected) or not core._time(rows["private_action_commit_guard_at"] if contract == PRIVATE_CONTRACT else rows["reservation_commit_guard_at"]) <= core._time(receipt["committed_at"])
            <= core._time(descriptor["observed_at"]) <= core._time(verification["observed_at"])
            <= core._time(e["admitted_at"]) < core._time(request["sales_cutoff_at"])):
        core._fail()


def _manifest(c, e, rows=None):
    contract = c["submission_contract"]
    return core._copy({**c["base_manifest"], "schema": _schema(core.RETAINED_SCHEMA, contract), "reservation": c,
        "reservation_sha256": _hash(_schema(C_SCHEMA, c["submission_contract"]), c), "retention_request_sha256": e["retention_request_sha256"] if e else None,
        "retention_admission_sha256": _hash(_schema(E_SCHEMA, c["submission_contract"]), e) if e else None,
        **(rows or dict.fromkeys(_fields(contract)))}, core.LIMIT)


def _envelope(schema, key, value, guard):
    return _copy({"schema": schema, key: value, "commit_guard_at": guard})


def _rows(db, base, loaded, expected=None, contract=CONTRACT):
    if not db.in_transaction or not core._identity(db, contract):
        core._fail()
    result, rows = [], dict.fromkeys(_fields(contract))
    for table in ("submission_reservation", "submission_retention"):
        extra = ",typeof(proof),length(proof)" if table == "submission_retention" else ""
        sizes = db.execute("SELECT id,typeof(json),length(CAST(json AS BLOB)),typeof(sha256),length(CAST(sha256 AS BLOB))" + extra + " FROM " + table).fetchmany(2)
        if (len(sizes) > 1 or table == "submission_reservation" and len(sizes) != 1
                or any(row[:2] != (1, "text") or not 0 < row[2] <= core.LIMIT or row[3:5] != ("text", 64)
                       or len(row) == 7 and (row[5] != "blob" or not 0 < row[6] <= core.LIMIT) for row in sizes)):
            core._fail()
        row = db.execute("SELECT json,sha256" + (",proof" if extra else "") + " FROM " + table).fetchone()
        if row is None:
            result.append((None, None))
            continue
        obj = _copy(json.loads(row[0]))
        schema, key, prefix = (_schema(C_ROW, contract), "reservation", "reservation") if table == "submission_reservation" else (_schema(E_ROW, contract), "evidence", "retention")
        if retention._raw(obj).decode() != row[0] or row[1] != _hash(schema, obj):
            core._fail()
        retention._exact(obj, {"schema", key, "commit_guard_at"})
        if obj["schema"] != schema or core._time(obj["commit_guard_at"]).isoformat() != obj["commit_guard_at"]:
            core._fail()
        rows[prefix + "_row_sha256"], rows[prefix + "_commit_guard_at"] = row[1], obj["commit_guard_at"]
        result.append((obj[key], row[2] if extra else None))
    (c, _), (e, proof) = result
    if c["submission_contract"] != contract:
        core._fail()
    _check_c(c, base, loaded)
    if not core._time(c["reserved_at"]) <= core._time(rows["reservation_commit_guard_at"]) < core._time(base["sales_cutoff_at"]):
        core._fail()
    if expected is not None and expected != _hash(_schema(C_SCHEMA, c["submission_contract"]), c):
        core._fail()
    if contract == PRIVATE_CONTRACT:
        from .private_retention_action import _stored
        action = _stored(db, c, loaded, rows)
        if action:
            rows.update(private_action_sha256=_hash(action["schema"], action), private_action_commit_guard_at=action["commit_guard_at"])
        if e is not None and action is None:
            core._fail()
    if e is not None:
        _check_e(c, e, proof, loaded, rows)
        if not core._time(e["admitted_at"]) <= core._time(rows["retention_commit_guard_at"]) < core._time(base["sales_cutoff_at"]):
            core._fail()
    if e is None and any(db.execute("SELECT 1 FROM " + table).fetchone() for table in
                         ("submission_manifest", "submission_intents", "submission_evidence")):
        core._fail()
    return c, e, proof, rows


def _open(path, private, writable=False):
    if not core.case._private(path, private, "PRE_OPEN"):
        core._fail()
    db = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=30, isolation_level=None)
    try:
        if not core.case._private(path, private, "POST_OPEN"):
            core._fail()
        return db
    except BaseException:
        db.close()
        raise


def _load(path, base, loaded, private, store, expected=None, contract=CONTRACT):
    if not path.exists():
        return None
    db = _open(path, private)
    try:
        db.execute("BEGIN")
        if not core._identity(db, contract):
            return None
        c, e, proof, rows = _rows(db, base, loaded, expected, contract)
        manifest = _manifest(c, e, rows)
        if not core._stage(path, manifest, private, store, "POST_OPEN"):
            core._fail()
        core._read(db, manifest, loaded)
        db.execute("COMMIT")
        return c, e, proof, rows
    finally:
        db.close()


def _entry(path, base, loaded, expected, private, store, contract=CONTRACT, expected_private_action_sha256=None):
    if not core.case._hex(expected):
        core._fail()
    values = _load(path, base, loaded, private, store, expected, contract)
    if values is None:
        core._fail()
    if contract == PRIVATE_CONTRACT and (not core.case._hex(expected_private_action_sha256) or values[3]["private_action_sha256"] != expected_private_action_sha256):
        core._fail()
    return path, _manifest(values[0], values[1], values[3]), loaded


def _prerequisite(db, manifest, loaded):
    if loaded is None:
        core._fail()
    c, e, _, rows = _rows(db, manifest["reservation"]["base_manifest"], loaded, manifest["reservation_sha256"], manifest["reservation"]["submission_contract"])
    if not _same(manifest, _manifest(c, e, rows)):
        core._fail()
    return {"admitted_at": rows["retention_commit_guard_at"] if e else rows.get("private_action_commit_guard_at") or rows["reservation_commit_guard_at"]}


def _action(manifest):
    c = manifest["reservation"]
    return {"schema": _schema("RACE_AI_RETAINED_SUBMISSION_ACTION_PREREQUISITE_V2", c["submission_contract"]), "reservation": c,
        **{key: manifest[key] for key in ("reservation_sha256", "retention_request_sha256", "retention_admission_sha256")},
        **{key: manifest[key] for key in _fields(c["submission_contract"])},
        "required_source_purposes": list(core.case.PURPOSES), "through_cutoff_at": manifest["sales_cutoff_at"],
        "retain_until": c["retention_policy"]["retain_until"]}


@_safe
def reserve_retained_case(attempt_path, case_path, *, expected_request_sha256, expected_branch,
        submission_source_sha40, slot, assignment_ref, destination, retention_policy, clock,
        private_path_verifier=None, admit_store=None, submission_contract=CONTRACT):
    contract = submission_contract
    _version(contract)
    entry = _candidate(attempt_path, case_path, expected_request_sha256, expected_branch, submission_source_sha40,
                       private_path_verifier, admit_store)
    if entry is None:
        return _response(reason="PRIVATE_STORE_NOT_ADMITTED")
    path, base, loaded = entry
    prior = _load(path, base, loaded, private_path_verifier, admit_store, contract=contract)
    if prior:
        c = prior[0]
        if not _same(c, _reservation(base, loaded, slot, assignment_ref, destination, retention_policy, c["reserved_at"], contract)):
            core._fail()
        return _response(c, rows=prior[3])
    timer = core._tracked_clock(clock)
    at = core._now(timer, loaded["persisted_at"], base["sales_cutoff_at"])
    c = _reservation(base, loaded, slot, assignment_ref, destination, retention_policy, at, contract)
    if not core._stage(path, _manifest(c, None), private_path_verifier, admit_store, "PRE_OPEN"):
        return _response(reason="ASSIGNMENT_NOT_ADMITTED")
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        if not core._stage(path, _manifest(c, None), private_path_verifier, admit_store, "POST_OPEN"):
            core._fail()
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if core._identity(db, contract):
            previous, _, _, rows = _rows(db, base, loaded, contract=contract)
            if not _same(previous, _reservation(base, loaded, slot, assignment_ref, destination, retention_policy, previous["reserved_at"], contract)):
                core._fail()
            if not core._stage(path, _manifest(previous, None, rows), private_path_verifier, admit_store, "POST_OPEN"):
                core._fail()
            db.execute("COMMIT")
            return _response(previous, rows=rows)
        for statement in core.SQL + _sql(contract):
            db.execute(statement)
        db.execute(f"PRAGMA application_id={core.APPLICATION_ID}")
        db.execute(f"PRAGMA user_version={_version(contract)}")
        if not core._stage(path, _manifest(c, None), private_path_verifier, admit_store, "PRE_COMMIT"):
            core._fail()
        guard = core._now(timer, at, base["sales_cutoff_at"])
        envelope = _envelope(_schema(C_ROW, contract), "reservation", c, guard)
        row_sha = _hash(_schema(C_ROW, contract), envelope)
        db.execute("INSERT INTO submission_reservation VALUES(1,?,?)", (retention._raw(envelope).decode(), row_sha))
        core._commit(db)
        rows = dict.fromkeys(_fields(contract))
        rows.update(reservation_row_sha256=row_sha, reservation_commit_guard_at=guard)
        return _response(c, rows=rows)
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _cached_inputs(c, e, proof, supplied, loaded):
    raw, descriptor, receipt, opaque = supplied
    if (type(raw) is not bytes or raw != loaded["wire"] or type(opaque) is not bytes or not 0 < len(opaque) <= core.LIMIT
            or opaque != proof or not _same(_copy(descriptor), e["readback_descriptor"])
            or not _same(_copy(receipt), e["receipt_claims"])):
        core._fail()


@_safe
def admit_case_retention(attempt_path, case_path, *, expected_request_sha256, expected_reservation_sha256,
        readback_bytes, readback_descriptor, receipt_claims, receipt_proof, clock, private_path_verifier=None,
        admit_store=None, admit_source_storage=None, admit_owner_destination=None, admit_coordinator=None,
        admit_protected_readback=None, verify_independent_receipt=None, submission_contract=CONTRACT,
        expected_private_action_sha256=None):
    contract = submission_contract
    _version(contract)
    path = core.case._path(attempt_path)
    if not callable(private_path_verifier) or not callable(admit_store) or not core.case._hex(expected_reservation_sha256):
        return _response(reason="PRIVATE_STORE_NOT_ADMITTED")
    loaded = core.case.load_case(case_path, expected_request_sha256=expected_request_sha256, private_path_verifier=private_path_verifier)
    # C supplies the immutable public target, rather than another caller R/M.
    db = _open(path, private_path_verifier)
    try:
        db.execute("BEGIN")
        if not core._identity(db, contract):
            core._fail()
        sizes = db.execute("SELECT typeof(json),length(CAST(json AS BLOB)) FROM submission_reservation").fetchmany(2)
        if len(sizes) != 1 or sizes[0][0] != "text" or not 0 < sizes[0][1] <= core.LIMIT:
            core._fail()
        base = _copy(json.loads(db.execute("SELECT json FROM submission_reservation").fetchone()[0]))["reservation"]["base_manifest"]
    finally:
        db.close()
    # Independently reconstruct the base from the actual original case.
    candidate = _candidate(path, case_path, expected_request_sha256, base["branch"], base["submission_source_sha40"], private_path_verifier, admit_store)
    _, base, loaded = candidate
    c, e, proof, rows = _load(path, base, loaded, private_path_verifier, admit_store, expected_reservation_sha256, contract)
    if contract == PRIVATE_CONTRACT and (not core.case._hex(expected_private_action_sha256) or rows["private_action_sha256"] != expected_private_action_sha256):
        core._fail()
    supplied = (readback_bytes, readback_descriptor, receipt_claims, receipt_proof)
    if e:
        _cached_inputs(c, e, proof, supplied, loaded)
        return _response(c, e, rows=rows)
    if (type(readback_bytes) is not bytes or not 0 < len(readback_bytes) <= retention.WIRE_LIMIT
            or type(receipt_proof) is not bytes or not 0 < len(receipt_proof) <= core.LIMIT):
        core._fail()
    descriptor = retention._evidence_metadata(readback_descriptor, retention.READBACK, retention.READBACK_FIELDS)
    receipt = retention._evidence_metadata(receipt_claims, retention.RECEIPT, retention.RECEIPT_FIELDS)
    timer = core._tracked_clock(clock)
    core._now(timer, rows["reservation_commit_guard_at"], base["sales_cutoff_at"])
    handoff = retention.prepare_retention_handoff(case_path, expected_case_request_sha256=expected_request_sha256,
        destination=c["destination"], retention_policy=c["retention_policy"], coordinator_binding=c["coordinator_binding"],
        clock=timer, private_path_verifier=private_path_verifier, admit_source_storage=admit_source_storage,
        admit_owner_destination=admit_owner_destination, admit_coordinator=admit_coordinator)
    if not handoff["handoff_admitted_by_callback"]:
        return _response(c, reason="RETENTION_NOT_ADMITTED", rows=rows)
    verification = retention.verify_retention_evidence(case_path, handoff["request"], expected_case_request_sha256=expected_request_sha256,
        expected_retention_request_sha256=handoff["request_sha256"], readback_bytes=readback_bytes, readback_descriptor=descriptor,
        receipt_claims=receipt, receipt_proof=receipt_proof, clock=timer, private_path_verifier=private_path_verifier,
        admit_protected_readback=admit_protected_readback, verify_independent_receipt=verify_independent_receipt)
    if verification["status"] != "ADMITTED_BY_CALLBACK":
        return _response(c, reason="RETENTION_NOT_ADMITTED", rows=rows)
    db = _open(path, private_path_verifier, writable=True)
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        current, existing, proof, rows = _rows(db, base, loaded, expected_reservation_sha256, contract)
        if existing:
            _cached_inputs(current, existing, proof, supplied, loaded)
            db.execute("COMMIT")
            return _response(current, existing, rows=rows)
        if not _same(c, current) or not core._stage(path, _manifest(c, None, rows), private_path_verifier, admit_store, "POST_OPEN"):
            core._fail()
        at = core._now(timer, rows["reservation_commit_guard_at"], base["sales_cutoff_at"])
        e = _copy({"schema": _schema(E_SCHEMA, contract), "reservation_sha256": expected_reservation_sha256,
            **{key: rows[key] for key in ROW_FIELDS[:2] + (P_FIELDS if contract == PRIVATE_CONTRACT else ())},
            "retention_request": handoff["request"], "retention_request_sha256": handoff["request_sha256"],
            "readback_descriptor": descriptor, "receipt_claims": receipt, "receipt_proof_sha256": core._sha(receipt_proof),
            "readback_sha256": core._sha(readback_bytes), "readback_byte_count": len(readback_bytes),
            "verdicts": dict.fromkeys(("source_storage", "owner_destination", "coordinator"), True),
            "verification": verification, "admitted_at": at})
        _check_e(c, e, receipt_proof, loaded, rows)
        if not core._stage(path, _manifest(c, e, rows), private_path_verifier, admit_store, "PRE_COMMIT"):
            core._fail()
        guard = core._now(timer, at, base["sales_cutoff_at"])
        envelope = _envelope(_schema(E_ROW, contract), "evidence", e, guard)
        row_sha = _hash(_schema(E_ROW, contract), envelope)
        db.execute("INSERT INTO submission_retention VALUES(1,?,?,?)", (retention._raw(envelope).decode(), receipt_proof, row_sha))
        core._commit(db)
        rows.update(retention_row_sha256=row_sha, retention_commit_guard_at=guard)
        return _response(c, e, rows=rows)
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


@_safe
def dispatch_retained_case(attempt_path, case_path, *, expected_request_sha256, expected_reservation_sha256,
        expected_branch, submission_source_sha40, clock, private_path_verifier=None, admit_store=None, verify_source=None,
        verify_cutoff=None, admit_model_roster=None, independent_release_check=None, admit_transport=None,
        admit_retention_action=None, transport=None, submission_contract=CONTRACT,
        expected_private_action_sha256=None):
    contract = submission_contract
    _version(contract)
    entry = core._entry(attempt_path, case_path, expected_request_sha256, expected_branch, submission_source_sha40,
        private_path_verifier, admit_store, contract=contract, reservation_sha=expected_reservation_sha256, private_action_sha=expected_private_action_sha256)
    if entry is None or entry[1]["retention_admission_sha256"] is None:
        result = core._summary(entry[1] if entry else None, reasons=["DURABLE_RETENTION_NOT_ADMITTED"])
        result.update(schema=_schema("RACE_AI_PERMISSIONED_SUBMISSION_RESULT_V2", contract), **retention._flags())
        return result
    return core.dispatch_prepared_case(attempt_path, case_path, expected_request_sha256=expected_request_sha256,
        expected_branch=expected_branch, submission_source_sha40=submission_source_sha40, clock=clock,
        private_path_verifier=private_path_verifier, admit_store=admit_store, verify_source=verify_source,
        verify_cutoff=verify_cutoff, admit_model_roster=admit_model_roster, independent_release_check=independent_release_check,
        admit_transport=admit_transport, transport=transport, _submission_contract=contract, _expected_private_action_sha256=expected_private_action_sha256,
        _expected_reservation_sha256=expected_reservation_sha256, _admit_retention_action=admit_retention_action)
