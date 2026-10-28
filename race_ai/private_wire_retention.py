"""Pure whole-wire contract; no storage, transport, registry or real-cloud proof.

Source/owner/coordinator admission must cover the exact destination and declared
retention horizon. Supplied protected-readback/receipt capabilities remain
independent external trust; a fixture True creates no coordinator or receipt.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import re

from . import permissioned_model_case as case

REQUEST = "RACE_AI_PRIVATE_WIRE_RETENTION_REQUEST_V1"
BASE = "RACE_AI_RETENTION_PRE_PUBLIC_BASE_BINDING_V1"
READBACK = "RACE_AI_PRIVATE_WIRE_READBACK_V1"
RECEIPT = "RACE_AI_PRIVATE_WIRE_RETENTION_RECEIPT_V1"
HANDOFF = "RACE_AI_PRIVATE_WIRE_RETENTION_HANDOFF_V1"
EVIDENCE = "RACE_AI_PRIVATE_WIRE_RETENTION_EVIDENCE_RESULT_V1"
LIMIT = 65536
WIRE_LIMIT = 4 * 1024 * 1024
DEST_FIELDS = {"destination_ref", "owner_scope_ref", "adapter_contract_sha256", "max_wire_bytes"}
POLICY_FIELDS = {"policy_ref", "retain_until", "protection_policy_sha256", "immutability_policy_sha256"}
BASE_FIELDS = {"schema", "scope", "coordinator_ref", "contract_sha256", "case_request_sha256", "wire_sha256",
               "ordered_plans_sha256", "destination_sha256", "base_binding_sha256"}
REQUEST_FIELDS = {"schema", "operation", "case_request_sha256", "case_delivery_sha256", "wire_sha256", "wire_byte_count",
    "wire_transport_schema", "source_policy_sha256", "model_source_sha40", "models", "case_persisted_at",
    "sales_cutoff_at", "destination", "retention_policy", "coordinator_binding"}
READBACK_FIELDS = {"schema", "request_sha256", "destination_ref", "object_ref", "object_version", "wire_sha256",
    "wire_byte_count", "observed_at", "reader_attestation_ref"}
RECEIPT_FIELDS = {"schema", "request_sha256", "destination_ref", "object_ref", "object_version", "wire_sha256",
    "wire_byte_count", "committed_at", "retained_until", "protection_policy_sha256", "immutability_policy_sha256", "issuer_ref"}
FALSE_FLAGS = ("write_authority", "full_private_payload_retention_verified", "source_rights_verified",
    "producer_execution_authenticated", "coordinator_authenticated", "global_exactly_once_verified",
    "cloned_store_protection_verified", "official_prediction", "eligible_for_hit_at_8")


class PrivateRetentionError(ValueError):
    """Generic private contract rejection with no supplied material."""


def _fail():
    raise PrivateRetentionError("PRIVATE_RETENTION_REJECTED") from None


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(schema, value):
    return _sha(schema.encode("ascii") + b"\0" + _raw(value))


def _copy(value, limit=LIMIT):
    """Reviewed finite walk + bounded streaming before canonical copying."""
    count, active = 0, set()
    def walk(node, depth=0):
        nonlocal count
        count += 1
        kind = type(node)
        if depth > 24 or count > 100000:
            _fail()
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
    try:
        walk(value)
        chunks, used = [], 0
        for piece in json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).iterencode(value):
            raw = piece.encode("utf-8")
            used += len(raw)
            if used > limit:
                _fail()
            chunks.append(raw)
        return json.loads(b"".join(chunks))
    except Exception:
        _fail()


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        _fail()


def _ref(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,511}", value) is None:
        _fail()


def _hex(value, size=64):
    if not case._hex(value, size):
        _fail()


def _time(value):
    try:
        if type(value) is not str or len(value) > 64:
            _fail()
        return case._stamp(value)
    except Exception:
        _fail()


class _Clock:
    def __init__(self, clock):
        self.clock, self.previous = clock, None

    def now(self):
        try:
            at = self.clock()
            if not isinstance(at, datetime) or at.utcoffset() is None:
                _fail()
            at = at.astimezone(timezone.utc)
            if self.previous is not None and at < self.previous:
                _fail()
            self.previous = at
            return at.isoformat()
        except Exception:
            _fail()


def _call(function, *args, limits=None):
    if not callable(function):
        return False
    limits = limits or [LIMIT] * len(args)
    try:
        owned = [_copy(v, limit) if type(v) in (dict, list) else v for v, limit in zip(args, limits)]
        before = [_raw(v) if type(v) in (dict, list) else None for v in owned]
        passed = function(*owned)
        return passed is True and all(old is None or old == _raw(_copy(v, limit))
                                     for old, v, limit in zip(before, owned, limits))
    except Exception:
        _fail()


def _load(path, expected, private):
    if not callable(private):
        return None
    refused = False
    def gate(value, *, stage):
        nonlocal refused
        try:
            admitted = private(value, stage=stage) is True
            refused |= not admitted
            return admitted
        except Exception:
            _fail()
    try:
        return case.load_case(path, expected_request_sha256=expected, private_path_verifier=gate)
    except Exception:
        if refused:
            return None
        _fail()


def _settings(destination, policy, binding):
    if destination is None:
        return None
    destination = _copy(destination)
    _exact(destination, DEST_FIELDS)
    cap = destination["max_wire_bytes"]
    if type(cap) is not int or not 1 <= cap <= WIRE_LIMIT:
        return None
    for name in ("destination_ref", "owner_scope_ref"):
        _ref(destination[name])
    _hex(destination["adapter_contract_sha256"])
    if policy is None or binding is None:
        return None
    policy, binding = _copy(policy), _copy(binding)
    _exact(policy, POLICY_FIELDS)
    _ref(policy["policy_ref"])
    _time(policy["retain_until"])
    for name in ("protection_policy_sha256", "immutability_policy_sha256"):
        _hex(policy[name])
    _exact(binding, BASE_FIELDS)
    if binding["schema"] != BASE or binding["scope"] != "PRE_PUBLIC_BASE_ONLY":
        _fail()
    _ref(binding["coordinator_ref"])
    for name in BASE_FIELDS - {"schema", "scope", "coordinator_ref"}:
        _hex(binding[name])
    return destination, policy, binding


def _request(loaded, settings):
    destination, policy, binding = settings
    if len(loaded["wire"]) > destination["max_wire_bytes"]:
        return None
    original = loaded["request"]
    cutoff = original["sales_cutoff_at"]
    if _time(policy["retain_until"]) <= _time(cutoff):
        _fail()
    expected_base = {"schema": BASE, "scope": "PRE_PUBLIC_BASE_ONLY", "coordinator_ref": binding["coordinator_ref"],
        "contract_sha256": binding["contract_sha256"], "case_request_sha256": loaded["request_sha256"],
        "wire_sha256": loaded["wire_sha256"], "ordered_plans_sha256": _hash("RACE_AI_RETENTION_ORIGINAL_PLANS_V1", loaded["plans"]),
        "destination_sha256": _hash("RACE_AI_RETENTION_DESTINATION_V1", destination)}
    expected_base["base_binding_sha256"] = _hash(BASE, expected_base)
    if _raw(binding) != _raw(expected_base):
        _fail()
    models = loaded["delivery"]["research_suite"]["models"]
    return {"schema": REQUEST, "operation": "PRIVATE_WHOLE_WIRE_RETENTION",
        "case_request_sha256": loaded["request_sha256"], "case_delivery_sha256": loaded["delivery_sha256"],
        "wire_sha256": loaded["wire_sha256"], "wire_byte_count": len(loaded["wire"]),
        "wire_transport_schema": "RACE_AI_PRIVATE_DELIVERY_TRANSPORT_V1", "source_policy_sha256": original["policy_record_sha256"],
        "model_source_sha40": original["model_source_sha40"], "models": [{"model_id": name,
            "model_version": models[name]["model_version"], "prediction_sha256": models[name]["prediction_sha256"]} for name in case.MODELS],
        "case_persisted_at": loaded["persisted_at"], "sales_cutoff_at": cutoff,
        "destination": destination, "retention_policy": policy, "coordinator_binding": expected_base}


def _flags():
    return {"scope": "LOCAL_CONTRACT_CALLBACK_ATTESTED", **dict.fromkeys(FALSE_FLAGS, False)}


def _handoff(expected, request=None, at=None, reasons=(), wire=None):
    result = {"schema": HANDOFF, "status": "RETENTION_UNVERIFIED_DO_NOT_WRITE", "case_request_sha256": expected,
        "request_sha256": _hash(REQUEST, request) if request else None, "prepared_at": at,
        "reasons": sorted(set(reasons)), "handoff_admitted_by_callback": False, **_flags()}
    if wire is not None:
        result.update(status="NOT_SENT_NO_WRITE_AUTHORITY", handoff_admitted_by_callback=True, request=request, wire=wire)
    return result


def prepare_retention_handoff(case_path, *, expected_case_request_sha256, destination, retention_policy,
        coordinator_binding, clock, private_path_verifier=None, admit_source_storage=None,
        admit_owner_destination=None, admit_coordinator=None):
    _hex(expected_case_request_sha256)
    settings = _settings(destination, retention_policy, coordinator_binding)
    if settings is None:
        return _handoff(expected_case_request_sha256, reasons=["DESTINATION_POLICY_OR_COORDINATOR_NOT_DECLARED"])
    timer = _Clock(clock)
    timer.now()
    loaded = _load(case_path, expected_case_request_sha256, private_path_verifier)
    if loaded is None:
        return _handoff(expected_case_request_sha256, reasons=["PRIVATE_PATH_NOT_ADMITTED"])
    request = _request(loaded, settings)
    if request is None:
        return _handoff(expected_case_request_sha256, reasons=["WHOLE_WIRE_EXCEEDS_DESTINATION_CAP"])
    def current():
        at = timer.now()
        if _time(at) < _time(request["case_persisted_at"]):
            _fail()
        return at
    at = current()
    if _time(at) >= _time(request["sales_cutoff_at"]):
        return _handoff(expected_case_request_sha256, request, at, ["MISSED_DEADLINE"])
    checks = ((admit_source_storage, (request, loaded["delivery"]["snapshot"]), [LIMIT, case.MAX_REQUEST]),
              (admit_owner_destination, (request,), [LIMIT]),
              (admit_coordinator, (request, request["coordinator_binding"]), [LIMIT, LIMIT]))
    for checker, args, limits in checks:
        passed = _call(checker, *args, limits=limits)
        at = current()
        if not passed or _time(at) >= _time(request["sales_cutoff_at"]):
            return _handoff(expected_case_request_sha256, request, at, ["RETENTION_ADMISSION_OR_DEADLINE_DENIED"])
    at = current()
    if _time(at) >= _time(request["sales_cutoff_at"]):
        return _handoff(expected_case_request_sha256, request, at, ["MISSED_DEADLINE"])
    return _handoff(expected_case_request_sha256, request, at, wire=loaded["wire"])


def _evidence_metadata(value, schema, fields):
    if value is None:
        return None
    value = _copy(value)
    _exact(value, fields)
    if value["schema"] != schema or type(value["wire_byte_count"]) is not int or not 1 <= value["wire_byte_count"] <= WIRE_LIMIT:
        _fail()
    for name in ("request_sha256", "wire_sha256"):
        _hex(value[name])
    for name in ("destination_ref", "object_ref", "object_version"):
        _ref(value[name])
    if schema == READBACK:
        _ref(value["reader_attestation_ref"])
        _time(value["observed_at"])
    else:
        _ref(value["issuer_ref"])
        for name in ("protection_policy_sha256", "immutability_policy_sha256"):
            _hex(value[name])
        for name in ("committed_at", "retained_until"):
            _time(value[name])
    return value


def _evidence_links(expected, descriptor, receipt):
    """Pure original metadata links; no clock, authority callback or promotion."""
    for metadata in (descriptor, receipt):
        if metadata is not None and (metadata["request_sha256"] != _hash(REQUEST, expected)
                or metadata["destination_ref"] != expected["destination"]["destination_ref"]
                or metadata["wire_sha256"] != expected["wire_sha256"] or metadata["wire_byte_count"] != expected["wire_byte_count"]):
            _fail()
    if receipt:
        if (not _time(expected["case_persisted_at"]) <= _time(receipt["committed_at"]) < _time(expected["sales_cutoff_at"])
                or _time(receipt["retained_until"]) < _time(expected["retention_policy"]["retain_until"])
                or any(receipt[name] != expected["retention_policy"][name] for name in ("protection_policy_sha256", "immutability_policy_sha256"))):
            _fail()
    if descriptor and receipt and (any(descriptor[name] != receipt[name] for name in ("object_ref", "object_version"))
            or _time(descriptor["observed_at"]) < _time(receipt["committed_at"])):
        _fail()


def verify_retention_evidence(case_path, request, *, expected_case_request_sha256,
        expected_retention_request_sha256, readback_bytes, readback_descriptor, receipt_claims,
        receipt_proof, clock, private_path_verifier=None, admit_protected_readback=None,
        verify_independent_receipt=None):
    _hex(expected_case_request_sha256)
    _hex(expected_retention_request_sha256)
    if readback_bytes is not None and (type(readback_bytes) is not bytes or not 0 < len(readback_bytes) <= WIRE_LIMIT):
        _fail()
    if receipt_proof is not None and (type(receipt_proof) is not bytes or len(receipt_proof) > LIMIT):
        _fail()
    request = _copy(request)
    _exact(request, REQUEST_FIELDS)
    if request["schema"] != REQUEST or request["operation"] != "PRIVATE_WHOLE_WIRE_RETENTION":
        _fail()
    settings = _settings(request["destination"], request["retention_policy"], request["coordinator_binding"])
    descriptor = _evidence_metadata(readback_descriptor, READBACK, READBACK_FIELDS)
    receipt = _evidence_metadata(receipt_claims, RECEIPT, RECEIPT_FIELDS)
    timer = _Clock(clock)
    at = timer.now()
    result = {"schema": EVIDENCE, "status": "RETENTION_UNVERIFIED_DO_NOT_WRITE",
        "case_request_sha256": expected_case_request_sha256, "request_sha256": expected_retention_request_sha256,
        "wire_sha256": None, "wire_byte_count": None,
        "readback_descriptor_sha256": _hash(READBACK, descriptor) if descriptor else None,
        "receipt_claims_sha256": _hash(RECEIPT, receipt) if receipt else None,
        "receipt_proof_sha256": _sha(receipt_proof) if receipt_proof else None, "observed_at": at,
        "whole_wire_equal": False, "protected_readback_admitted_by_callback": False,
        "receipt_admitted_by_callback": False, "reasons": [], **_flags()}
    if settings is None:
        result["reasons"] = ["RETENTION_SETTINGS_NOT_ADMITTED"]
        return result
    loaded = _load(case_path, expected_case_request_sha256, private_path_verifier)
    if loaded is None:
        result["reasons"] = ["PRIVATE_PATH_NOT_ADMITTED"]
        return result
    expected = _request(loaded, settings)
    if expected is None or _raw(request) != _raw(expected) or _hash(REQUEST, expected) != expected_retention_request_sha256:
        _fail()
    result.update(wire_sha256=expected["wire_sha256"], wire_byte_count=expected["wire_byte_count"])
    _evidence_links(expected, descriptor, receipt)
    def observed():
        now = timer.now()
        if (_time(now) < _time(expected["case_persisted_at"])
                or descriptor and _time(descriptor["observed_at"]) > _time(now)
                or receipt and _time(receipt["committed_at"]) > _time(now)):
            _fail()
        result["observed_at"] = now
    observed()
    if readback_bytes is not None:
        if len(readback_bytes) != len(loaded["wire"]) or _sha(readback_bytes) != expected["wire_sha256"] or readback_bytes != loaded["wire"]:
            _fail()
        result.update(whole_wire_equal=True, status="WHOLE_BYTES_MATCH_UNVERIFIED")
        if descriptor:
            result["protected_readback_admitted_by_callback"] = _call(admit_protected_readback, request, descriptor)
            observed()
        if receipt and receipt_proof:
            result["receipt_admitted_by_callback"] = _call(verify_independent_receipt, request, receipt, receipt_proof)
            observed()
    if result["whole_wire_equal"] and result["protected_readback_admitted_by_callback"] and result["receipt_admitted_by_callback"]:
        result["status"] = "ADMITTED_BY_CALLBACK"
    else:
        result["reasons"] = ["PROTECTED_READBACK_OR_INDEPENDENT_RECEIPT_NOT_ADMITTED"]
    observed()
    return result
