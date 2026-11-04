"""One local saved-input operation over the existing sixteen native families.

No source fetching, loop, scheduler, remote submission, receipt creation or
model promotion. Exact native originals and every returned slot are retained
in additive tables of the existing private SQLite journal. A local commit is
NOT an independent pre-cutoff witness, source grant or official result.

``at`` is the trusted caller's current clock, injectable for offline tests;
there is deliberately no CLI accepting a historical generation clock.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from . import existing_model_dispatch as native
from .autorace_private_store import LocalPrivateJournal
from .private_cycle_capture import _parent_handle
from .private_delivery_codec import _pack, _unpack, _Budget, _canonical_bytes

SCHEMA = "RACE_AI_PRIVATE_DISPATCH_OPERATION_V1"
_WIRE = "RACE_AI_PRIVATE_DISPATCH_TYPED_WIRE_V1"
_ERROR = "PRIVATE_DISPATCH_OPERATION_REJECTED"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_KEY_FIELDS = ("sport", "race_id", "stage", "model_id")
_PURPOSES = ("analysis", "private_storage", "private_derived")


class PrivateDispatchError(ValueError):
    """Fail closed without exposing private paths, source data or tickets."""


def _need(condition):
    if not condition:
        raise PrivateDispatchError(_ERROR)


def _wire(value):
    """Reuse the existing bounded pure typed codec; never repair native hashes."""
    try:
        body = _pack(value, _Budget(), set())
        document = {"schema": _WIRE, "body": body}
        document["wire_sha256"] = hashlib.sha256(_canonical_bytes(document, newline=False)).hexdigest()
        return _canonical_bytes(document, newline=True)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise PrivateDispatchError(_ERROR) from None


def _unwire(raw):
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= 4 * 1024 * 1024)
        def pairs(items):
            out = {}
            for key, value in items:
                _need(key not in out)
                out[key] = value
            return out
        document = json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda _: _need(False))
        _need(type(document) is dict and set(document) == {"schema", "body", "wire_sha256"}
              and document["schema"] == _WIRE)
        unsigned = {k:v for k,v in document.items() if k != "wire_sha256"}
        _need(hashlib.sha256(_canonical_bytes(unsigned, newline=False)).hexdigest() == document["wire_sha256"]
              and _canonical_bytes(document, newline=True) == raw)
        value = _unpack(document["body"], _Budget())
        _need(_wire(value) == raw)
        return value
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise PrivateDispatchError(_ERROR) from None


def _key(slot):
    version = slot.get("model_version")
    _need(version is None or type(version) is str and 0 < len(version) <= 128)
    return (*(slot[k] for k in _KEY_FIELDS), json.dumps(version, ensure_ascii=False))


def _native_scope(slot):
    scope = slot.get("scope")
    _need(scope in ("SYNTHETIC_ONLY", "OPERATOR_SUPPLIED_RESEARCH"))
    scopes = [container["scope"] for container in
              (slot.get("prediction", {}), slot.get("native_context") or {}) if "scope" in container]
    _need(all(value == scope for value in scopes))
    return bool(scopes)


def _identity(info):
    return info.st_dev, info.st_ino


def _private_file(info):
    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
          info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600)


_TABLES = """
CREATE TABLE IF NOT EXISTS dispatch_originals(
 sport TEXT NOT NULL, race_id TEXT NOT NULL, stage TEXT NOT NULL,
 model_id TEXT NOT NULL, model_version TEXT NOT NULL, wire BLOB NOT NULL,
 PRIMARY KEY(sport,race_id,stage,model_id,model_version));
CREATE TABLE IF NOT EXISTS dispatch_operations(
 operation_id INTEGER PRIMARY KEY, wire BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS dispatch_operation_slots(
 operation_id INTEGER NOT NULL REFERENCES dispatch_operations(operation_id),
 ordinal INTEGER NOT NULL, wire BLOB NOT NULL,
 PRIMARY KEY(operation_id,ordinal));
CREATE TRIGGER IF NOT EXISTS dispatch_originals_no_update BEFORE UPDATE ON dispatch_originals
 BEGIN SELECT RAISE(ABORT,'immutable dispatch originals'); END;
CREATE TRIGGER IF NOT EXISTS dispatch_originals_no_delete BEFORE DELETE ON dispatch_originals
 BEGIN SELECT RAISE(ABORT,'immutable dispatch originals'); END;
CREATE TRIGGER IF NOT EXISTS dispatch_operations_no_update BEFORE UPDATE ON dispatch_operations
 BEGIN SELECT RAISE(ABORT,'immutable dispatch operations'); END;
CREATE TRIGGER IF NOT EXISTS dispatch_operations_no_delete BEFORE DELETE ON dispatch_operations
 BEGIN SELECT RAISE(ABORT,'immutable dispatch operations'); END;
CREATE TRIGGER IF NOT EXISTS dispatch_slots_no_update BEFORE UPDATE ON dispatch_operation_slots
 BEGIN SELECT RAISE(ABORT,'immutable dispatch operation slots'); END;
CREATE TRIGGER IF NOT EXISTS dispatch_slots_no_delete BEFORE DELETE ON dispatch_operation_slots
 BEGIN SELECT RAISE(ABORT,'immutable dispatch operation slots'); END;
"""


class PrivateDispatchJournal(LocalPrivateJournal):
    """Additive native-slot storage; old AUTORACE tables and APIs stay intact.

The existing 0700 parent must be outside Git. Directory traversal uses the
existing no-follow directory-FD guard. Replaced/missing databases, hardlinks,
ancestor symlinks and permissive modes fail closed, including after opening.
"""

    def __init__(self, db_path):
        try:
            _need(os.name == "posix" and Path("/proc/self/fd").is_dir())
            self.path = Path(db_path).expanduser()
            _need(self.path.is_absolute() and ".." not in self.path.parts and
                  _NAME.fullmatch(self.path.name) is not None)
            with _parent_handle(self.path.parent) as parent:
                directory = os.fstat(parent)
                _need(directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700)
                self._directory_identity = _identity(directory)
                try:
                    fd = os.open(self.path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
                except FileExistsError:
                    fd = os.open(self.path.name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    info = os.fstat(fd)
                    _private_file(info)
                    self._database_identity = _identity(info)
                finally:
                    os.close(fd)
            super().__init__(self.path)
            with self.connect() as db:
                db.executescript(_TABLES)
        except (ValueError, OSError, sqlite3.Error):
            raise PrivateDispatchError(_ERROR) from None

    @contextmanager
    def connect(self):
        db = None
        try:
            with _parent_handle(self.path.parent) as parent:
                directory = os.fstat(parent)
                _need(_identity(directory) == self._directory_identity and
                      directory.st_uid == os.getuid() and stat.S_IMODE(directory.st_mode) == 0o700)
                fd = os.open(self.path.name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    _private_file(before)
                    _need(_identity(before) == self._database_identity)
                    for suffix in ("-journal", "-wal", "-shm"):
                        try:
                            sidecar = os.stat(self.path.name + suffix, dir_fd=parent, follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        _private_file(sidecar)
                    # Parent FD stays live until the SQLite connection closes.
                    uri = "file:/proc/self/fd/" + str(parent) + "/" + self.path.name + "?mode=rw"
                    db = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
                    after = os.stat(self.path.name, dir_fd=parent, follow_symlinks=False)
                    _private_file(after)
                    _need(_identity(after) == _identity(before))
                    db.execute("PRAGMA journal_mode=DELETE")
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("PRAGMA foreign_keys=ON")
                    db.execute("PRAGMA busy_timeout=10000")
                    yield db
                finally:
                    if db is not None:
                        db.close()
                    os.close(fd)
        except OSError:
            raise PrivateDispatchError(_ERROR) from None

    def _originals(self, db):
        records = db.execute("SELECT sport,race_id,stage,model_id,model_version,wire "
                             "FROM dispatch_originals ORDER BY sport,race_id,stage,model_id,model_version").fetchall()
        _need(len(records) <= 100000)
        originals = []
        for row in records:
            value = _unwire(row[-1])
            _need(_key(value) == row[:5])
            _native_scope(value)
            originals.append(value)
        # Validate every version, including records outside the current request.
        schedule = {}
        for slot in originals:
            key = slot["race_id"], slot["stage"]
            row = {k:slot[k] for k in ("race_id", "sport", "stage", "cutoff_at")}
            _need(key not in schedule or schedule[key] == row)
            schedule[key] = row
        native._original_index(originals, list(schedule.values()))
        return originals

    def originals(self):
        """Return the complete exact original inventory, with no inference."""
        with self.connect() as db:
            return self._originals(db)

    def read_operation(self, operation_id):
        _need(type(operation_id) is int and operation_id > 0)
        with self.connect() as db:
            found = db.execute("SELECT wire FROM dispatch_operations WHERE operation_id=?",
                               (operation_id,)).fetchone()
            _need(found is not None)
            report = _unwire(found[0])
            slots = db.execute("SELECT ordinal,wire FROM dispatch_operation_slots WHERE operation_id=? "
                               "ORDER BY ordinal", (operation_id,)).fetchall()
            _need([r[0] for r in slots] == list(range(report.pop("stored_slot_count"))))
            report["dispatch"]["slots"] = [_unwire(r[1]) for r in slots]
            inventory = {_key(row):row for row in self._originals(db)}
            references = report["dispatch"].pop("retained_original_keys")
            report["dispatch"]["retained_originals"] = [deepcopy(inventory[tuple(key)]) for key in references]
            return report


def _same_original(left, right):
    # Reuse status/reason are observations of the immutable native original.
    ignored = {"status", "reason", "external_receipt_verified", "official_prediction"}
    return {k:v for k,v in left.items() if k not in ignored} == {
        k:v for k,v in right.items() if k not in ignored}


def _admit_import(slot, payloads, row, clock, authorize):
    """Check a native input commitment and source uses without model execution.

Some legacy outputs commit only selected source hashes, rather than the full
native arguments. Such outputs cannot establish the necessary import binding
here; no synthetic commitment is added to repair them.
"""
    try:
        embedded = _native_scope(slot)
        if slot["scope"] == "SYNTHETIC_ONLY" and embedded:
            return
        group = next(group for group, ids in native.GROUPS if slot["model_id"] in ids)
        payload = payloads[slot["race_id"]][slot["stage"]][
            "shared" if group == "shared_learned" else group]
        _need(type(payload) is dict and native._scope(group, payload) == slot["scope"])
        # A saved generation timestamp is historical evidence, never a request
        # to generate now. Check source/race identity against the actual clock.
        binding = {k:v for k,v in payload.items() if k != "generated_at"}
        native._bind(group, binding, row, clock)
        native._authorize(group, payload, authorize)
        prediction = slot["prediction"]
        if group in ("shared", "shared_learned", "boat_full", "boat_observed"):
            _need(prediction.get("snapshot_sha256", prediction.get("input_sha256")) ==
                  native.digest(payload["snapshot"]))
            if group == "shared_learned":
                model = payload["learned_model"]
                _need(prediction.get("model_sha256") == model.get("model_sha256") ==
                      native.digest({k:v for k,v in model.items() if k != "model_sha256"}))
        elif group == "autorace_personal":
            _need(prediction.get("input_sha256") == native.digest(payload["snapshot"]))
        elif group == "boat_ab":
            _need(slot["native_context"].get("source_sha256") == native.digest(payload["source"]))
        else:
            _need(False)
    except (ValueError, TypeError, KeyError, StopIteration, AttributeError, OverflowError):
        raise PrivateDispatchError("UNVERIFIED_ORIGINAL_STORAGE_EVIDENCE") from None


def run_saved_inputs(journal, schedule, inputs, *, at, allow_source=None, originals=()):
    """Dispatch and commit one explicit saved-input batch, without source I/O.

All originals are read under BEGIN IMMEDIATE before any model executes. The
same transaction preserves every model version and every returned status slot.
The caller supplies explicit stages and its true current time. Analysis and
both private uses must be independently admitted before real native inference.

    First-import real originals require their matching saved native inputs and
    all three source uses. Legacy outputs without a complete native input
    commitment fail as UNVERIFIED_ORIGINAL_STORAGE_EVIDENCE, never regenerate.
    Already-admitted journal originals remain readable without model execution.
"""
    _need(isinstance(journal, PrivateDispatchJournal))
    clock = native._time(at)
    rows, payloads, imported = deepcopy(schedule), deepcopy(inputs), deepcopy(list(originals))
    _need(type(rows) is list and type(payloads) is dict and len(rows) <= 20000)
    _need(all(type(row) is dict and {"race_id", "sport", "stage", "cutoff_at"} <= set(row)
              and row["stage"] in native.STAGES and row["sport"] in native.SPORTS for row in rows))
    def admitted(ref, rights, purpose):
        if purpose != "analysis" or not callable(allow_source):
            return False
        try:
            return all(allow_source(ref, rights, use) is True for use in _PURPOSES)
        except (ValueError, TypeError, OSError):
            return False
    with journal.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            saved = journal._originals(db)
            selected = {(row["race_id"], row["stage"]):row for row in rows}
            known = {_key(slot):slot for slot in saved}
            # An omitted earlier seller race must not reset its whole-day cap.
            days = {native._time(row["cutoff_at"]).astimezone(native.JST).date().isoformat()
                    for row in rows if row["sport"] == "boat" and row["stage"] == "P0"}
            for slot in saved:
                if slot["model_id"] == "seller-shadow-v1-20261104" and slot["prediction"]["date"] in days:
                    _need((slot["race_id"], slot["stage"]) in selected)
            native._original_index(imported, rows)
            for slot in imported:
                key = _key(slot)
                if key in known:
                    _need(_same_original(known[key], slot))
                else:
                    _admit_import(slot, payloads, selected[(slot["race_id"], slot["stage"])], clock, admitted)
                    db.execute("INSERT INTO dispatch_originals VALUES(?,?,?,?,?,?)", (*key, _wire(slot)))
                    known[key] = slot
            eligible = [slot for slot in known.values() if (slot["race_id"], slot["stage"]) in selected]
            report = native.dispatch(rows, payloads, now=clock, allow_source=admitted, originals=eligible)
            report["schedule"] = deepcopy(rows)
            for slot in report["slots"]:
                if slot["status"] != "GENERATED_UNATTESTED":
                    continue
                key = _key(slot)
                _need(key not in known)
                db.execute("INSERT INTO dispatch_originals VALUES(?,?,?,?,?,?)", (*key, _wire(slot)))
                known[key] = slot
            next_id = db.execute("SELECT COALESCE(MAX(operation_id),0)+1 FROM dispatch_operations").fetchone()[0]
            output = dict(schema=SCHEMA, operation_id=next_id, dispatch=report,
                source_requests=0, local_commit_only=True, independent_freeze_verified=False,
                official_results_authenticated=False, all_models_operational=False,
                production_operation=False, originals_overwritten=False, automatic_model_promoted=False)
            metadata = deepcopy(output)
            slots = metadata["dispatch"].pop("slots")
            retained = metadata["dispatch"].pop("retained_originals")
            metadata["dispatch"]["retained_original_keys"] = [list(_key(slot)) for slot in retained]
            metadata["stored_slot_count"] = len(slots)
            db.execute("INSERT INTO dispatch_operations VALUES(?,?)", (next_id, _wire(metadata)))
            for ordinal, slot in enumerate(slots):
                db.execute("INSERT INTO dispatch_operation_slots VALUES(?,?,?)", (next_id, ordinal, _wire(slot)))
            db.commit()
            return output
        except BaseException:
            db.rollback()
            raise
