"""Private one-case preparation, never a source grant, public writer or freeze.

Root must load the exact pinned PR71 modules. Authority callbacks and real OS
ACL checks are separately audited capabilities; test stubs are not real proof.
Committed preparation replays original bytes, not renewed source admission.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import sqlite3
import stat

from .append_only_freeze_writer import prepare_anchor
from .model_suite_settlement import audit_model_settlements
from .pr71_delivery_binding import bind_audit_to_delivery, _stamp as _binding_stamp
from .model_case_contracts import select as _select_contract

SCHEMA = "RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V1"
RESULT_SCHEMA = "RACE_AI_PERMISSIONED_MODEL_CASE_RESULT_V1"
DOMAIN = b"RACE_AI_PERMISSIONED_MODEL_CASE_CHECKPOINT_V1\0"
MODEL_PIN = "ebe93f13062cf0461b81b924a5dc0482ada37b56"
MODELS = ("multisport-factor-interaction-v1", "multisport-scenario-ensemble-v1",
          "multisport-conditional-duel-v1", "multisport-race-trajectory-v1")
VERSIONS = {name: "0.1.0-UNTRAINED" for name in MODELS}
APPLICATION_ID = 0x52414350
JST = timezone(timedelta(hours=9))
PURPOSES = ("analysis", "private_storage", "private_derived")
MAX_REQUEST = 1024 * 1024
MAX_SOURCE = 4 * 1024 * 1024
FIELDS = {"schema", "case_id", "race_id", "ledger", "source_payload_sha256",
    "policy_record_sha256", "feature_snapshot_sha256", "as_of", "sales_cutoff_at",
    "expected_model_ids", "expected_model_versions", "model_source_sha40", "executor_source_sha40",
    "input_evidence_ref", "cutoff_evidence_ref", "model_declaration_evidence_ref"}
SQL = (
    "CREATE TABLE permissioned_case(id INTEGER PRIMARY KEY CHECK(id=1),request_sha256 TEXT NOT NULL,"
    "metadata TEXT NOT NULL,wire BLOB NOT NULL,content_sha256 TEXT NOT NULL)",
    "CREATE TRIGGER permissioned_case_no_update BEFORE UPDATE ON permissioned_case "
    "BEGIN SELECT RAISE(ABORT,'immutable permissioned case'); END",
    "CREATE TRIGGER permissioned_case_no_delete BEFORE DELETE ON permissioned_case "
    "BEGIN SELECT RAISE(ABORT,'immutable permissioned case'); END",
)


class PermissionedCaseError(ValueError):
    """Invalid private evidence, path or immutable checkpoint."""


def _fail():
    raise PermissionedCaseError("permissioned case rejected") from None


def _stamp(value):
    try:
        return _binding_stamp(value)
    except (ValueError, TypeError):
        _fail()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value, domain=b""):
    return _sha(domain + _canonical(value).encode("utf-8"))


def _same(left, right):
    return _canonical(left) == _canonical(right)


def _profile(request):
    try:
        return _select_contract(request['schema'], request['model_source_sha40'])
    except (ValueError, KeyError, TypeError):
        _fail()


def _request_hash(request):
    return _hash(request, _profile(request).schema.encode('ascii') + b'\0')


def _hex(value, size=64):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(size) + "}", value) is not None


def _bounded_copy(value):
    count, active = 0, set()
    def walk(node, depth=0):
        nonlocal count
        count += 1
        if depth > 24 or count > 100000:
            _fail()
        kind = type(node)
        if kind is str:
            if len(node) > 16384 or len(node.encode("utf-8")) > 16384:
                _fail()
        elif kind is float:
            if not math.isfinite(node):
                _fail()
        elif kind is int:
            if abs(node) > 10**15:
                _fail()
        elif kind in (dict, list):
            if id(node) in active:
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
        elif node is not None and kind is not bool:
            _fail()
    walk(value)
    chunks, used = [], 0
    for piece in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).iterencode(value):
        raw = piece.encode("utf-8")
        used += len(raw)
        if used > MAX_REQUEST:
            _fail()
        chunks.append(raw)
    return json.loads(b"".join(chunks))


def _request(value):
    # Type and resource checks precede canonical copying and all legacy hashes.
    if type(value) is not dict or set(value) != FIELDS:
        _fail()
    value = _bounded_copy(value)
    _profile(value)
    if (type(value["case_id"]) is not str
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value["case_id"]) is None
            or not _same(value["expected_model_ids"], list(MODELS))
            or not _same(value["expected_model_versions"], VERSIONS)
            or not _hex(value["source_payload_sha256"])):
        _fail()
    for name in ("policy_record_sha256", "feature_snapshot_sha256", "executor_source_sha40"):
        if value[name] is not None and not _hex(value[name], 40 if name == "executor_source_sha40" else 64):
            _fail()
    for name in ("input_evidence_ref", "cutoff_evidence_ref", "model_declaration_evidence_ref"):
        if value[name] is not None and (type(value[name]) is not str or not 1 <= len(value[name]) <= 512):
            _fail()
    for name in ("as_of", "sales_cutoff_at"):
        if value[name] is not None:
            _stamp(value[name])
    ledger = value["ledger"]
    if (type(ledger) is not dict or ledger.get("schema") != "RACE_AI_FORECAST_AUDIT_V1"
            or ledger.get("dataset_status") != "AUDIT_ONLY" or type(ledger.get("records")) is not list
            or not 1 <= len(ledger["records"]) <= 10000 or type(ledger.get("event_date_jst")) is not str):
        _fail()
    try:
        day = date.fromisoformat(ledger["event_date_jst"])
    except ValueError:
        _fail()
    if day.isoformat() != ledger["event_date_jst"]:
        _fail()
    seen, selected, model_ids = set(), None, set()
    for row in ledger["records"]:
        if (type(row) is not dict or row.get("sport") not in ("boat", "keirin", "autorace", "horse_jra", "horse_local")
                or type(row.get("venue")) is not str or not 1 <= len(row["venue"]) <= 128
                or type(row.get("race_no")) is not int or not 1 <= row["race_no"] <= 99
                or row.get("cutoff_verified") is not False or row.get("prediction") is not None or row.get("result") is not None):
            _fail()
        identity = f"{row['sport']}:{day.isoformat()}:{row['venue']}:{row['race_no']}"
        model_id = re.sub(r"^horse_(?:jra|local):", "horse:", identity)
        if row.get("race_id") != identity or identity in seen or model_id in model_ids:
            _fail()
        seen.add(identity)
        model_ids.add(model_id)
        if row.get("sales_cutoff_at") is not None and _stamp(row["sales_cutoff_at"]).astimezone(JST).date() != day:
            _fail()
        if identity == value["race_id"]:
            selected = row
    if selected is None:
        _fail()
    if value["sales_cutoff_at"] is not None:
        if (_stamp(value["sales_cutoff_at"]).astimezone(JST).date() != day
                or selected.get("sales_cutoff_at") is None
                or _stamp(value["sales_cutoff_at"]) != _stamp(selected["sales_cutoff_at"])):
            _fail()
    return value


def _dependencies():
    return (importlib.import_module("race_ai.permissioned_source_delivery"),
            importlib.import_module("race_ai.private_delivery_codec"),
            importlib.import_module("race_ai.comprehensive_four_sport_models"))


def _lstat(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        _fail()


def _path(value):
    path = Path(value)
    # Reject remote/device paths lexically, before any possible filesystem probe.
    if str(path).startswith(("\\\\", "//")) or str(path.anchor).startswith("\\\\"):
        _fail()
    path = path.expanduser().absolute()
    if str(path).startswith(("\\\\", "//")) or str(path.anchor).startswith("\\\\"):
        _fail()
    if path.name in ("", ".", ".."):
        _fail()
    # A final-component lstat still follows its ancestors. Check each lexical
    # ancestor from the root before probing any descendant of that ancestor.
    for part in (*reversed(path.parents), path):
        info = _lstat(part)
        if info is None:
            if part != path:
                _fail()
        elif (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024
                or part == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)
                or part != path and not stat.S_ISDIR(info.st_mode)):
            _fail()
    resolved = path.parent.resolve(strict=True) / path.name
    for parent in (resolved.parent, *resolved.parent.parents):
        marker = parent / ".git"
        if _lstat(marker) is not None:
            _fail()
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(resolved) + suffix)
        info = _lstat(sidecar)
        if info is not None:
            if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 1024 or info.st_nlink != 1):
                _fail()
    return resolved


def _private(path, verifier, stage):
    return (callable(verifier) and verifier(path, stage=stage) is True and _path(path) == path)


def _objects(db):
    return db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()


def _identity(db):
    template = sqlite3.connect(":memory:")
    try:
        for statement in SQL:
            template.execute(statement)
        expected = _objects(template)
    finally:
        template.close()
    objects = _objects(db)
    identity = (db.execute("PRAGMA application_id").fetchone()[0], db.execute("PRAGMA user_version").fetchone()[0])
    if not objects and identity == (0, 0):
        return False
    if objects != expected or identity[0] != APPLICATION_ID or identity[1] not in (1, 2):
        _fail()
    return identity[1]


def _now(clock, previous=None):
    value = clock()
    if not isinstance(value, datetime) or value.utcoffset() is None:
        _fail()
    value = value.astimezone(timezone.utc).isoformat()
    if previous is not None and _stamp(value) < _stamp(previous):
        _fail()
    return value


def _entries(snapshot, supplemental):
    return ([item for participant in snapshot["participants"] for item in participant["features"].values()]
            + list(snapshot["environment"].values()) + supplemental)


def _source_decisions(snapshot, supplemental, authorize):
    decisions = {}
    for item in _entries(snapshot, supplemental):
        for purpose in PURPOSES:
            key = _hash([item["source_ref"], item["source_rights_ref"], purpose])
            accepted = authorize(item["source_ref"], item["source_rights_ref"], purpose) is True
            if not accepted:
                _fail()
            decisions[key] = accepted
    return decisions


def _policy_effective(policy, snapshot, supplemental, at):
    for item in _entries(snapshot, supplemental):
        grant = policy.grants[(item["source_ref"], item["source_rights_ref"])]
        if not _stamp(grant["checked_at"]) <= _stamp(at) < _stamp(grant["expires_at"]):
            return False
    return True


def _analysis_window(request, sources, admitted_start):
    return {'schema':'RACE_AI_MODEL_CASE_ANALYSIS_WINDOW_V1',
        'request_sha256':_request_hash(request),
        **{name:request[name] for name in ('source_payload_sha256','feature_snapshot_sha256','policy_record_sha256','input_evidence_ref')},
        'source_verdicts_sha256':_hash(sources), 'purposes':list(PURPOSES),
        'admitted_start':admitted_start, 'through_at':request['sales_cutoff_at']}


def _input_window_admitted(callback, request, snapshot, policy_sha, window):
    claimed, snap, claim = map(_bounded_copy,(request,snapshot,window))
    try:
        answer=callback(claimed,snap,policy_sha,analysis_window=claim)
        return (answer is True and _same(_bounded_copy(claimed),request)
            and _same(_bounded_copy(snap),snapshot) and _same(_bounded_copy(claim),window))
    except Exception:
        return False


def _v2_cutoff_admitted(callback, row):
    claim=_bounded_copy(row)
    try:
        return callback(claim) is True and _same(_bounded_copy(claim),row)
    except Exception:
        return False


def _v2_roster_admitted(callback, declaration):
    try:
        return callback(declaration) is True
    except Exception:
        return False


def _checked(request, metadata, wire):
    source, codec, models = _dependencies()
    profile = _profile(request)
    fields = {"request", "delivery_sha256", "wire_sha256", "started_at", "generated_at", "persisted_at", "plans", "source_verdicts"}
    if profile.version == 2:
        fields |= {'analysis_window','analysis_window_admitted_by_callback'}
    if (type(wire) is not bytes or not 0 < len(wire) <= MAX_SOURCE
            or set(metadata) != fields
            or not _same(request, metadata["request"]) or _sha(wire) != metadata["wire_sha256"]):
        _fail()
    delivery = codec.deserialize_private_delivery(wire, expected_delivery_sha256=metadata["delivery_sha256"])
    if (any(delivery[name] != request[name] for name in ("source_payload_sha256", "policy_record_sha256", "feature_snapshot_sha256"))
            or list(delivery["research_suite"]["models"]) != list(MODELS)):
        _fail()
    verdicts = metadata["source_verdicts"]
    if type(verdicts) is not dict or any(not _hex(key) or type(value) is not bool or value is not True for key, value in verdicts.items()):
        _fail()
    def saved(ref, rights, purpose):
        return verdicts.get(_hash([ref, rights, purpose])) is True
    class RecordedPolicy:
        authorize = staticmethod(saved)
    snapshot = delivery["snapshot"]
    models.validate(snapshot, allow_source=saved)
    extra = source._verify_supplemental(delivery["supplemental_evidence"], snapshot, RecordedPolicy(), at=metadata["started_at"])
    if not _same(verdicts, _source_decisions(snapshot, extra, saved)):
        _fail()
    if profile.version == 2:
        window = _bounded_copy(metadata['analysis_window'])
        if (metadata['analysis_window_admitted_by_callback'] is not True
                or not _same(window,_analysis_window(request,verdicts,window['admitted_start']))
                or not _stamp(request['as_of']) <= _stamp(window['admitted_start']) <= _stamp(metadata['started_at'])):
            _fail()
    audit = audit_model_settlements(request["ledger"], [], [{"race_id": request["race_id"], "delivery": delivery}], [],
        expected_model_ids=MODELS, expected_model_versions=VERSIONS, expected_model_source_sha40=profile.pin,
        validate_snapshot=models.validate, allow_source=saved, model_contract=profile.cardinality)
    if not audit["all_supplied_snapshots_admitted_by_callback"]:
        _fail()
    race = snapshot["race"]
    started, generated, persisted = map(_stamp, (metadata["started_at"], metadata["generated_at"], metadata["persisted_at"]))
    if (request["as_of"] is None or request["sales_cutoff_at"] is None
            or _stamp(race["as_of"]) != _stamp(request["as_of"])
            or _stamp(race["sales_cutoff_at"]) != _stamp(request["sales_cutoff_at"])
            or not _stamp(race["as_of"]) <= started <= generated <= persisted < _stamp(request["sales_cutoff_at"])
            or _stamp(delivery["ingested_at"]) != started):
        _fail()
    binding = bind_audit_to_delivery(request["ledger"], delivery, race_id=request["race_id"], model_contract=profile.cardinality)
    if not _same(metadata["plans"], [prepare_anchor(binding, name, metadata["generated_at"], metadata["persisted_at"]) for name in MODELS]):
        _fail()
    return delivery


def _read(db, expected_request_sha256):
    if not db.in_transaction:
        _fail()
    if not _identity(db):
        return None
    # Admit every variable-width column in SQLite before copying it to Python.
    # Both queries share the caller's read snapshot, including malicious TEXT in
    # the BLOB column and multibyte metadata whose character count is smaller.
    sizes = db.execute("SELECT id,typeof(request_sha256),length(CAST(request_sha256 AS BLOB)),"
        "typeof(metadata),length(CAST(metadata AS BLOB)),typeof(wire),length(CAST(wire AS BLOB)),"
        "typeof(content_sha256),length(CAST(content_sha256 AS BLOB)) FROM permissioned_case").fetchmany(2)
    if not sizes:
        return None
    if (len(sizes) != 1 or sizes[0][0] != 1 or sizes[0][1:3] != ("text", 64)
            or sizes[0][3] != "text" or not 0 < sizes[0][4] <= 2 * MAX_REQUEST
            or sizes[0][5] != "blob" or not 0 < sizes[0][6] <= MAX_SOURCE
            or sizes[0][7:9] != ("text", 64)):
        _fail()
    try:
        request_sha, text, wire, digest = db.execute(
            "SELECT request_sha256,metadata,wire,content_sha256 FROM permissioned_case WHERE id=1").fetchone()
        metadata = json.loads(text)
        if (type(metadata) is not dict or _canonical(metadata) != text
                or not _hex(request_sha) or not _hex(digest) or request_sha != expected_request_sha256
                ):
            _fail()
        request = _request(metadata["request"])
        profile = _profile(request)
        if (db.execute('PRAGMA user_version').fetchone()[0] != profile.version
                or digest != _hash([request_sha, metadata, _sha(wire)],profile.checkpoint_domain)
                or request_sha != _request_hash(request)):
            _fail()
        delivery = _checked(request, metadata, wire)
    except (ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
        _fail()
    return {**metadata, "request_sha256": request_sha, "wire": wire, "delivery": delivery}


def _summary(loaded):
    return {"schema": _profile(loaded['request']).result_schema, "status": "PREPARED_NOT_EXTERNAL_FROZEN",
        "case_id": loaded["request"]["case_id"], "request_sha256": loaded["request_sha256"],
        **{name: loaded[name] for name in ("delivery_sha256", "wire_sha256", "started_at", "generated_at", "persisted_at", "plans")},
        "models": [{"model_id": name, "model_version": model["model_version"], "prediction_sha256": model["prediction_sha256"]}
                   for name, model in loaded["delivery"]["research_suite"]["models"].items()],
        "source_admission_status": "CALLBACK_ATTESTED_UNLESS_INDEPENDENTLY_AUDITED",
        "official_prediction": False, "external_freeze_verified": False}


def _denied(request, reasons):
    return {"schema": _profile(request).result_schema, "status": "NO_FORECAST",
        "request_sha256": _request_hash(request),
        "source_payload_sha256": request["source_payload_sha256"], "reasons": sorted(set(reasons)),
        "official_prediction": False, "external_freeze_verified": False}


def _insert_case(db, request_sha, metadata, wire):
    db.execute("INSERT INTO permissioned_case VALUES(1,?,?,?,?)",
        (request_sha, _canonical(metadata), wire, _hash([request_sha, metadata, _sha(wire)], _profile(metadata['request']).checkpoint_domain)))


def load_case(path, *, expected_request_sha256, private_path_verifier=None):
    if not _hex(expected_request_sha256):
        _fail()
    path = _path(path)
    if not _private(path, private_path_verifier, "PRE_OPEN"):
        _fail()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None)
    try:
        if not _private(path, private_path_verifier, "POST_OPEN"):
            _fail()
        db.execute("BEGIN")
        loaded = _read(db, expected_request_sha256)
        if loaded is None:
            _fail()
        db.execute("COMMIT")
        return loaded
    finally:
        db.close()


def prepare_case(path, request, raw_feed, policy, *, clock, private_path_verifier=None,
                 verify_input=None, verify_cutoff=None, admit_model_roster=None):
    request = _request(request)
    profile = _profile(request)
    if type(raw_feed) is not bytes or not 0 < len(raw_feed) <= MAX_SOURCE or _sha(raw_feed) != request["source_payload_sha256"]:
        _fail()
    request_sha = _request_hash(request)
    nullable = ("policy_record_sha256", "feature_snapshot_sha256", "as_of", "sales_cutoff_at", "executor_source_sha40",
                "input_evidence_ref", "cutoff_evidence_ref", "model_declaration_evidence_ref")
    missing = ["MISSING_" + name.upper() for name in nullable if request[name] is None]
    if missing:
        return _denied(request, missing)
    path = _path(path)
    if not _private(path, private_path_verifier, "PRE_OPEN"):
        return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
    if path.exists():
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None)
        try:
            if not _private(path, private_path_verifier, "POST_OPEN"):
                return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
            db.execute("BEGIN")
            prior = _read(db, request_sha)
            db.execute("COMMIT")
            if prior is not None:
                return _summary(prior)
        finally:
            db.close()
    absent = [reason for function, reason in ((verify_input, "INPUT_NOT_ADMITTED"), (verify_cutoff, "CUTOFF_NOT_ADMITTED"),
              (admit_model_roster, "MODEL_DECLARATION_NOT_ADMITTED")) if not callable(function)]
    if absent:
        return _denied(request, absent)
    started = _now(clock)
    if _stamp(started) >= _stamp(request["sales_cutoff_at"]):
        return _denied(request, ["MISSED_DEADLINE"])
    source, codec, models = _dependencies()
    if not isinstance(policy, source.PermissionPolicy):
        return _denied(request, ["POLICY_NOT_ADMITTED"])
    if policy.document_sha256 != request["policy_record_sha256"]:
        _fail()
    try:
        feed = source.read_json_bytes(raw_feed)
    except (ValueError, RecursionError):
        _fail()
    if (type(feed) is not dict or set(feed) not in ({"schema", "snapshot"}, {"schema", "snapshot", "supplemental"})
            or feed["schema"] != source.FEED_SCHEMA or type(feed["snapshot"]) is not dict):
        _fail()
    source._reject_market(feed)
    snapshot = feed["snapshot"]
    if models.digest(snapshot) != request["feature_snapshot_sha256"]:
        _fail()
    try:
        extra = source._verify_supplemental(feed.get("supplemental", []), snapshot, policy, at=started)
        policy.check_snapshot(snapshot, needs_storage=True, supplemental=extra)
        models.validate(snapshot, allow_source=policy.authorize)
        if not _policy_effective(policy, snapshot, extra, started):
            return _denied(request, ["SOURCE_POLICY_NOT_EFFECTIVE"])
        sources = _source_decisions(snapshot, extra, policy.authorize)
    except (ValueError, KeyError, TypeError):
        return _denied(request, ["SOURCE_OR_FULL_INPUT_NOT_ADMITTED"])
    race = snapshot["race"]
    if (_stamp(race["as_of"]) != _stamp(request["as_of"]) or _stamp(race["as_of"]) > _stamp(started)
            or _stamp(race["sales_cutoff_at"]) != _stamp(request["sales_cutoff_at"])):
        _fail()
    row = next(item for item in request["ledger"]["records"] if item["race_id"] == request["race_id"])
    expected_id = re.sub(r"^horse_(?:jra|local):", "horse:", request["race_id"])
    expected_sport = "horse" if row["sport"].startswith("horse_") else row["sport"]
    if (race["race_id"] != expected_id or race["sport"] != expected_sport
            or race["venue"] != row["venue"] or race["event_date_jst"] != request["ledger"]["event_date_jst"]):
        _fail()
    count = len(snapshot["participants"])
    if profile.version == 1 and count * (count - 1) * (count - 2) < 8:
        # Pinned producers/binding require eight unique picks. N=3 support needs
        # a separately reviewed upstream contract; never infer or pad two picks.
        return _denied(request, ["PINNED_MODEL_CARDINALITY_UNSUPPORTED"])
    declaration = tuple((name, VERSIONS[name], profile.pin) for name in MODELS)
    denials = []
    window = _analysis_window(request,sources,started) if profile.version == 2 else None
    input_ok = (_input_window_admitted(verify_input,request,snapshot,policy.document_sha256,window)
                if profile.version == 2 else verify_input(_bounded_copy(request), _bounded_copy(snapshot), policy.document_sha256) is True)
    if not input_ok:
        denials.append("INPUT_NOT_ADMITTED")
    cutoff_ok = (_v2_cutoff_admitted(verify_cutoff,row) if profile.version == 2
                 else verify_cutoff(_bounded_copy(row)) is True)
    if not cutoff_ok:
        denials.append("CUTOFF_NOT_ADMITTED")
    roster_ok = (_v2_roster_admitted(admit_model_roster,declaration) if profile.version == 2
                 else admit_model_roster(declaration) is True)
    if not roster_ok:
        denials.append("MODEL_DECLARATION_NOT_ADMITTED")
    if denials:
        return _denied(request, denials)
    if profile.version == 2:
        from . import isolated_model_case_runtime as runtime
        try:
            runtime.preflight()
        except runtime.IsolatedModelError:
            return _denied(request,['PINNED_RUNTIME_NOT_AVAILABLE'])
        started = _now(clock,started)
        if _stamp(started) >= _stamp(request['sales_cutoff_at']):
            return _denied(request,['MISSED_DEADLINE'])
    if not _private(path, private_path_verifier, "PRE_OPEN"):
        return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        if not _private(path, private_path_verifier, "POST_OPEN"):
            return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        owned = _identity(db)
        if owned:
            if owned != profile.version:
                _fail()
            prior = _read(db, request_sha)
            if prior is not None:
                db.execute("COMMIT")
                return _summary(prior)
        else:
            for statement in SQL:
                db.execute(statement)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={profile.version}")
        started = _now(clock, started)
        if _stamp(started) >= _stamp(request["sales_cutoff_at"]):
            db.execute("ROLLBACK")
            return _denied(request, ["MISSED_DEADLINE"])
        if not _policy_effective(policy, snapshot, extra, started):
            db.execute("ROLLBACK")
            return _denied(request, ["SOURCE_POLICY_NOT_EFFECTIVE"])
        if profile.version == 2:
            def admit_private_input():
                edge = _now(clock, started)
                if (not _stamp(window['admitted_start']) <= _stamp(edge) < _stamp(request['sales_cutoff_at'])
                        or policy.document_sha256 != request['policy_record_sha256']
                        or not _policy_effective(policy,snapshot,extra,edge)
                        or not _same(sources,_source_decisions(snapshot,extra,policy.authorize))):
                    _fail()
                return edge
            try:
                wire, delivery_sha, started = runtime.produce(request,request_sha,raw_feed,sources,
                    started_at=started,admit_private_input=admit_private_input)
                delivery = codec.deserialize_private_delivery(wire,expected_delivery_sha256=delivery_sha)
            except Exception:
                _fail()
        else:
            delivery = source.deliver(raw_feed, policy, at=started, persist=True)
        generated = _now(clock, started)
        if profile.version == 1:
            wire = codec.serialize_private_delivery(delivery)
        binding = bind_audit_to_delivery(request["ledger"], delivery, race_id=request["race_id"],model_contract=profile.cardinality)
        persisted = _now(clock, generated)
        metadata = {"request": request, "delivery_sha256": delivery["delivery_sha256"], "wire_sha256": _sha(wire),
            "started_at": started, "generated_at": generated, "persisted_at": persisted, "source_verdicts": sources,
            "plans": [prepare_anchor(binding, name, generated, persisted) for name in MODELS]}
        if profile.version == 2:
            metadata.update(analysis_window=window,analysis_window_admitted_by_callback=True)
        _checked(request, metadata, wire)
        if not _private(path, private_path_verifier, "POST_OPEN"):
            db.execute("ROLLBACK")
            return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
        _insert_case(db, request_sha, metadata, wire)
        if not _private(path, private_path_verifier, "PRE_COMMIT"):
            db.execute("ROLLBACK")
            return _denied(request, ["PRIVATE_PATH_NOT_ADMITTED"])
        commit_time = _now(clock, persisted)
        if _stamp(commit_time) >= _stamp(request["sales_cutoff_at"]):
            _fail()
        if not _policy_effective(policy, snapshot, extra, commit_time):
            db.execute("ROLLBACK")
            return _denied(request, ["SOURCE_POLICY_NOT_EFFECTIVE"])
        db.execute("COMMIT")
        return _summary({**metadata, "request_sha256": request_sha, "delivery": delivery})
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
