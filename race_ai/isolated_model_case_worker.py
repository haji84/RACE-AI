"""Fixed offline child/bootstrap helpers. Recorded decisions are not source grants.

Frames: uint32 network length then exact bytes. READY fields are schema/profile/
pin/manifest_sha256; RESULT adds request_sha256/delivery_sha256/wire_sha256/
wire_bytes. No private input is read before the closed verified map and READY.
"""
import hashlib
import importlib.abc
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
from datetime import datetime, timezone

PROJECT = Path(__file__).absolute().parent.parent
BUNDLE = PROJECT / "pr71-max8-reference"
MANIFEST_PATH = PROJECT / "config" / "pr71-max8-reference-manifest.json"
MANIFEST_SHA = "6116f1eb3e4746e496b041dce3161dab8421811ddd300b444302787325371c8c"
PIN = "db075c203704d2b30df5742ce8458a43932696a4"
PROFILE = "MAX8_COMPLETE_UNIVERSE"
REQUEST = "RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2"
CONTROL = "RACE_AI_ISOLATED_CASE_CONTROL_V1"
READY = "RACE_AI_ISOLATED_CASE_READY_V1"
RESULT = "RACE_AI_ISOLATED_CASE_RESULT_V1"
HEADER_LIMIT, CONTROL_LIMIT, WIRE_LIMIT = 4096, 2 * 1024 * 1024, 4 * 1024 * 1024
PURPOSES = ("analysis", "private_storage", "private_derived")
FIELDS = {"schema", "case_id", "race_id", "ledger", "source_payload_sha256", "policy_record_sha256",
    "feature_snapshot_sha256", "as_of", "sales_cutoff_at", "expected_model_ids", "expected_model_versions",
    "model_source_sha40", "executor_source_sha40", "input_evidence_ref", "cutoff_evidence_ref",
    "model_declaration_evidence_ref"}
IDS = ("multisport-factor-interaction-v1", "multisport-scenario-ensemble-v1",
       "multisport-conditional-duel-v1", "multisport-race-trajectory-v1")


def _reject():
    raise ValueError("ISOLATED_MODEL_REJECTED") from None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hex(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _stamp(value):
    if type(value) is not str:
        _reject()
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.utcoffset() is None:
        _reject()
    return at.astimezone(timezone.utc)


def _nodes(value):
    count, active = 0, set()
    def walk(node, depth):
        nonlocal count
        count += 1
        if depth > 24 or count > 100000:
            _reject()
        kind = type(node)
        if kind is str:
            if len(node) > 16384 or len(node.encode("utf-8")) > 16384:
                _reject()
        elif kind is float:
            if not math.isfinite(node):
                _reject()
        elif kind is int:
            if abs(node) > 10**15:
                _reject()
        elif kind in (dict, list):
            if id(node) in active:
                _reject()
            active.add(id(node))
            if kind is dict:
                for key, item in node.items():
                    if type(key) is not str:
                        _reject()
                    walk(key, depth + 1)
                    walk(item, depth + 1)
            else:
                for item in node:
                    walk(item, depth + 1)
            active.remove(id(node))
        elif node is not None and kind is not bool:
            _reject()
    walk(value, 0)


def _dump(value, limit):
    _nodes(value)
    parts, used = [], 0
    for text in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).iterencode(value):
        raw = text.encode("utf-8")
        used += len(raw)
        if used > limit:
            _reject()
        parts.append(raw)
    return b"".join(parts)


def _json(raw, limit, canonical=True):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        _reject()
    def pairs(rows):
        obj = {}
        for key, value in rows:
            if key in obj:
                _reject()
            obj[key] = value
        return obj
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: _reject())
    _nodes(value)
    if canonical and _dump(value, limit) != raw:
        _reject()
    return value


def _read_public(path, limit):
    if str(path).startswith(("\\\\", "//")):
        _reject()
    target = None
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            _reject()
        if ancestor == path:
            target = info
        elif not stat.S_ISDIR(info.st_mode):
            _reject()
    if target is None or not stat.S_ISREG(target.st_mode) or target.st_nlink != 1 or target.st_size > limit:
        _reject()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_nlink) != (target.st_dev, target.st_ino, 1):
            _reject()
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        _reject()
    return raw


class _Verified(dict):
    def __init__(self, modules, files):
        super().__init__(modules)
        self.files = files  # Retain all63 checked blobs; only29 are executable.


def _bundle():
    raw = _read_public(MANIFEST_PATH, 65536)
    if _sha(raw) != MANIFEST_SHA:
        _reject()
    manifest = _json(raw, 65536, canonical=False)
    files = manifest["files"]
    if (manifest.get("schema") != "RACE_AI_MAX8_REFERENCE_MANIFEST_V1" or manifest.get("pin") != PIN
            or manifest.get("byte_representation") != "EXACT_GIT_BLOB_LF" or type(files) is not list or len(files) != 63):
        _reject()
    names, total = set(), 0
    for entry in files:
        if (type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}
                or type(entry["path"]) is not str or re.fullmatch(r"(?:race_ai|tests)/[a-z0-9_.]+\.(?:py|mjs|cjs)", entry["path"]) is None
                or entry["path"] in names or type(entry["bytes"]) is not int or not 0 <= entry["bytes"] <= 65536
                or not _hex(entry["sha256"])):
            _reject()
        names.add(entry["path"])
        total += entry["bytes"]
    if total > 512 * 1024:
        _reject()
    modules, retained = {}, {}
    for entry in files:
        raw = _read_public(BUNDLE / entry["path"], entry["bytes"])
        if len(raw) != entry["bytes"] or _sha(raw) != entry["sha256"]:
            _reject()
        retained[entry["path"]] = raw
        if entry["path"].startswith("race_ai/") and entry["path"].endswith(".py"):
            name = entry["path"][:-3].replace("/", ".")
            name = "race_ai" if name == "race_ai.__init__" else name
            modules[name] = raw
    if len(modules) != 29 or "race_ai" not in modules:
        _reject()
    return _Verified(modules, retained)


class _Closed(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, modules):
        self.modules = modules

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "race_ai" or fullname.startswith("race_ai."):
            if fullname not in self.modules:
                raise ImportError("UNLISTED_VERIFIED_MODULE") from None
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname == "race_ai")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = "<verified:" + module.__name__ + ">"
        if module.__name__ == "race_ai":
            module.__path__ = []
        exec(compile(self.modules[module.__name__], module.__file__, "exec", dont_inherit=True), module.__dict__)


def _install(modules):
    if any(name == "race_ai" or name.startswith("race_ai.") for name in sys.modules):
        _reject()
    sys.meta_path.insert(0, _Closed(modules))


def _read_exact(stream, size):
    pieces, used = [], 0
    while used < size:
        raw = stream.read(min(65536, size - used))
        if not raw:
            _reject()
        pieces.append(raw)
        used += len(raw)
    return b"".join(pieces)


def _frame(stream, limit):
    size = struct.unpack("!I", _read_exact(stream, 4))[0]
    if not 0 < size <= limit:
        _reject()
    return _read_exact(stream, size)


def _write_frame(stream, raw):
    for part in (struct.pack("!I", len(raw)), raw):
        offset = 0
        while offset < len(part):
            wrote = stream.write(part[offset:offset + 65536])
            if not wrote:
                _reject()
            offset += wrote
    stream.flush()


def _identity(schema):
    return {"schema": schema, "profile": PROFILE, "pin": PIN, "manifest_sha256": MANIFEST_SHA}


def _request(request, digest, raw, decisions):
    if (type(request) is not dict or set(request) != FIELDS or request["schema"] != REQUEST
            or request["model_source_sha40"] != PIN or request["expected_model_ids"] != list(IDS)
            or request["expected_model_versions"] != dict.fromkeys(IDS, "0.1.0-UNTRAINED")
            or not _hex(digest) or _sha(REQUEST.encode() + b"\0" + _dump(request, CONTROL_LIMIT)) != digest
            or type(raw) is not bytes or not 0 < len(raw) <= WIRE_LIMIT
            or _sha(raw) != request["source_payload_sha256"]
            or not _hex(request["policy_record_sha256"]) or not _hex(request["feature_snapshot_sha256"])
            or type(decisions) is not dict or not decisions
            or any(not _hex(key) or value is not True for key, value in decisions.items())):
        _reject()


def _run():
    modules = _bundle()
    _install(modules)
    _write_frame(sys.stdout.buffer, _dump(_identity(READY), HEADER_LIMIT))
    control = _json(_frame(sys.stdin.buffer, CONTROL_LIMIT), CONTROL_LIMIT)
    raw = _frame(sys.stdin.buffer, WIRE_LIMIT)
    if sys.stdin.buffer.read(1):
        _reject()
    if (type(control) is not dict or set(control) != {"schema", "profile", "pin", "manifest_sha256", "request",
            "request_sha256", "started_at", "policy_record_sha256", "source_verdicts"}
            or any(control.get(key) != value for key, value in _identity(CONTROL).items())):
        _reject()
    request, decisions = control["request"], control["source_verdicts"]
    _request(request, control["request_sha256"], raw, decisions)
    started = _stamp(control["started_at"])
    if (control["policy_record_sha256"] != request["policy_record_sha256"]
            or not _stamp(request["as_of"]) <= started < _stamp(request["sales_cutoff_at"])):
        _reject()
    from race_ai import permissioned_source_delivery as source
    from race_ai import private_delivery_codec as codec
    from race_ai.comprehensive_four_sport_models import digest
    feed = source.read_json_bytes(raw)
    _nodes(feed)
    snapshot = feed["snapshot"]
    if digest(snapshot) != request["feature_snapshot_sha256"]:
        _reject()
    entries = [item for row in snapshot["participants"] for item in row["features"].values()]
    entries += list(snapshot["environment"].values()) + feed.get("supplemental", [])
    expected = {_sha(_dump([item["source_ref"], item["source_rights_ref"], purpose], CONTROL_LIMIT))
                for item in entries for purpose in PURPOSES}
    if set(decisions) != expected:
        _reject()
    class RecordedPolicy:
        """Only original parent-admitted decisions; no child signature claim."""
        document_sha256 = request["policy_record_sha256"]
        check_snapshot = source.PermissionPolicy.check_snapshot
        def authorize(self, ref, rights, purpose):
            return decisions.get(_sha(_dump([ref, rights, purpose], CONTROL_LIMIT))) is True
    delivery = source.deliver(raw, RecordedPolicy(), at=started.isoformat(), persist=True)
    wire = codec.serialize_private_delivery(delivery)
    header = {**_identity(RESULT), "request_sha256": control["request_sha256"],
              "delivery_sha256": delivery["delivery_sha256"], "wire_sha256": _sha(wire), "wire_bytes": len(wire)}
    _write_frame(sys.stdout.buffer, _dump(header, HEADER_LIMIT))
    _write_frame(sys.stdout.buffer, wire)


if __name__ == "__main__":
    try:
        _run()
    except BaseException:
        sys.exit(1)
