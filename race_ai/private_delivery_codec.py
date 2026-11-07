"""Explicit, lossless JSON transport for existing private research deliveries.

This codec performs no model execution, file I/O, fetching, source admission,
timestamp witnessing or authorization. Existing hashes are compared, never
rewritten. Successful decoding proves local integrity only; rights, producer
execution, complete rankings and external freeze evidence require their own
existing validators. Ordinary V1 JSON is deliberately not repaired or accepted.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .comprehensive_four_sport_models import digest as legacy_digest, moment
from .four_sport_model_suite import ALL_MODELS, verify_suite


SCHEMA = "RACE_AI_PRIVATE_DELIVERY_TRANSPORT_V1"
MAX_WIRE_BYTES = 4 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 500000
MAX_STRING_BYTES = 16 * 1024
_DOMAIN = SCHEMA.encode("ascii") + b"\0"
_ERROR = "private delivery transport rejected"
_ENVELOPE_FIELDS = {"schema", "delivery_sha256", "body", "transport_sha256"}
_DELIVERY_FIELDS = {
    "schema", "race_id", "sport", "ingested_at", "source_payload_sha256",
    "policy_record_sha256", "feature_snapshot_sha256", "snapshot", "supplemental_evidence",
    "supplemental_features_used_by_models", "research_suite", "status",
    "source_terms_independently_verified_by_code", "official_prediction", "external_receipt",
    "can_count_in_hit_at_8", "automatic_betting", "delivery_sha256",
}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class PrivateDeliveryCodecError(ValueError):
    """An invalid transport is rejected without echoing private material."""


def _reject():
    raise PrivateDeliveryCodecError(_ERROR)


def _hex(value):
    return type(value) is str and len(value) == 64 and _HEX64.fullmatch(value) is not None


def _string(value):
    # Every UTF-8 character needs at least one byte. Reject an oversized
    # scalar before allocating its encoded copy; then check multibyte strings.
    if (type(value) is not str or len(value) > MAX_STRING_BYTES
            or len(value.encode("utf-8")) > MAX_STRING_BYTES):
        _reject()


class _Budget:
    def __init__(self):
        self.nodes = 0

    def visit(self, depth):
        self.nodes += 1
        if depth > MAX_DEPTH or self.nodes > MAX_NODES:
            _reject()


def _pack(value, budget, active, depth=0):
    budget.visit(depth)
    kind = type(value)
    if value is None:
        return ["null"]
    if kind is bool:
        return ["bool", value]
    if kind is int:
        return ["int", value]
    if kind is float:
        if not math.isfinite(value):
            _reject()
        return ["float", value]
    if kind is str:
        _string(value)
        return ["str", value]
    if kind not in (dict, list) or id(value) in active:
        _reject()
    active.add(id(value))
    try:
        if kind is list:
            return ["list", [_pack(item, budget, active, depth + 1) for item in value]]
        rows = []
        for key, item in value.items():
            if type(key) not in (str, int):
                _reject()
            rows.append([_pack(key, budget, active, depth + 1),
                         _pack(item, budget, active, depth + 1)])
        return ["dict", rows]
    finally:
        active.remove(id(value))


def _unpack(node, budget, depth=0):
    budget.visit(depth)
    if type(node) is not list or not node or type(node[0]) is not str:
        _reject()
    tag = node[0]
    if tag == "null":
        if len(node) != 1:
            _reject()
        return None
    if len(node) != 2:
        _reject()
    value = node[1]
    scalar = {"bool": bool, "int": int, "float": float, "str": str}
    if tag in scalar:
        if type(value) is not scalar[tag]:
            _reject()
        if tag == "float" and not math.isfinite(value):
            _reject()
        if tag == "str":
            _string(value)
        return value
    if type(value) is not list:
        _reject()
    if tag == "list":
        return [_unpack(item, budget, depth + 1) for item in value]
    if tag != "dict":
        _reject()
    restored = {}
    for pair in value:
        if type(pair) is not list or len(pair) != 2:
            _reject()
        key = _unpack(pair[0], budget, depth + 1)
        if type(key) not in (str, int) or key in restored:
            _reject()
        restored[key] = _unpack(pair[1], budget, depth + 1)
    return restored


def _canonical_bytes(document, *, newline):
    """Bound encoded allocation before joining or invoking legacy hashing."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False)
    used = 1 if newline else 0
    chunks = []
    for chunk in encoder.iterencode(document):
        encoded = chunk.encode("utf-8")
        used += len(encoded)
        if used > MAX_WIRE_BYTES:
            _reject()
        chunks.append(encoded)
    if newline:
        chunks.append(b"\n")
    return b"".join(chunks)


def _transport_hash(unsigned):
    fingerprint = hashlib.sha256(_DOMAIN)
    fingerprint.update(_canonical_bytes(unsigned, newline=False))
    return fingerprint.hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _validate_delivery(delivery):
    """Check existing V1 integrity/identity, never issue a source permission."""
    if type(delivery) is not dict or set(delivery) != _DELIVERY_FIELDS:
        _reject()
    if (delivery["schema"] != "RACE_AI_PRIVATE_DELIVERY_V1"
            or delivery["status"] != "PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN"
            or delivery["external_receipt"] is not None
            or type(delivery["supplemental_evidence"]) is not list):
        _reject()
    for flag in ("supplemental_features_used_by_models", "source_terms_independently_verified_by_code",
                 "official_prediction", "can_count_in_hit_at_8", "automatic_betting"):
        if delivery[flag] is not False:
            _reject()
    for name in ("source_payload_sha256", "policy_record_sha256", "feature_snapshot_sha256",
                 "delivery_sha256"):
        if not _hex(delivery[name]):
            _reject()
    snapshot = delivery["snapshot"]
    suite = delivery["research_suite"]
    if (type(snapshot) is not dict or type(suite) is not dict
            or set(snapshot) != {"schema", "scope", "race", "participants", "environment"}
            or snapshot["schema"] != "RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1"
            or snapshot["scope"] != "OPERATOR_SUPPLIED_RESEARCH"):
        _reject()
    race = snapshot["race"]
    if type(race) is not dict:
        _reject()
    race_id, sport = race.get("race_id"), race.get("sport")
    if (type(race_id) is not str or not 8 <= len(race_id) <= 200
            or sport not in ("boat", "keirin", "autorace", "horse")
            or delivery["race_id"] != race_id or delivery["sport"] != sport
            or type(race.get("race_revision")) is not int or race["race_revision"] < 1):
        _reject()
    as_of = moment(race["as_of"])
    cutoff = moment(race["sales_cutoff_at"])
    if not as_of <= moment(delivery["ingested_at"]) < cutoff:
        _reject()
    if (suite.get("schema") != "RACE_AI_FOUR_SPORT_RESEARCH_SUITE_V1"
            or suite.get("scope") != snapshot["scope"] or suite.get("race_id") != race_id
            or suite.get("sport") != sport or suite.get("as_of") != race["as_of"]
            or suite.get("sales_cutoff_at") != race["sales_cutoff_at"]
            or type(suite.get("race_revision")) is not int
            or suite["race_revision"] != race["race_revision"]
            or suite.get("official_prediction") is not False
            or suite.get("external_timestamp_receipts") is not None
            or suite.get("official_result") is not None
            or suite.get("purchase_decision") != "NO_BET"
            or suite.get("rights_not_granted_by_runner") is not True
            or type(suite.get("model_count")) is not int or suite["model_count"] != len(ALL_MODELS)
            or suite.get("ranked_model_ids") != list(ALL_MODELS)
            or type(suite.get("models")) is not dict or tuple(suite["models"]) != ALL_MODELS):
        _reject()
    snapshot_hash = delivery["feature_snapshot_sha256"]
    if suite.get("input_sha256") != snapshot_hash:
        _reject()
    for name, model in suite["models"].items():
        if (type(model) is not dict or model.get("model_id") != name
                or type(model.get("model_version")) is not str or not 1 <= len(model["model_version"]) <= 128
                or model.get("race_id") != race_id or model.get("sport") != sport
                or model.get("scope") != snapshot["scope"] or model.get("as_of") != race["as_of"]
                or model.get("cutoff_at") != race["sales_cutoff_at"]
                or type(model.get("race_revision")) is not int
                or model["race_revision"] != race["race_revision"]
                or model.get("snapshot_sha256") != snapshot_hash
                or model.get("official_prediction") is not False
                or model.get("external_pre_cutoff_receipt") is not None
                or model.get("official_result") is not None or model.get("trained") is not False
                or model.get("odds_independent") is not True or model.get("purchase_decision") != "NO_BET"):
            _reject()
        if "input_sha256" in model and model["input_sha256"] != snapshot_hash:
            _reject()
    if (legacy_digest(snapshot) != snapshot_hash
            or legacy_digest({k: v for k, v in delivery.items() if k != "delivery_sha256"}) != delivery["delivery_sha256"]
            or not verify_suite(suite)):
        _reject()


def serialize_private_delivery(delivery):
    """Return opt-in canonical UTF-8 transport bytes ending in exactly one LF.

    Scalar tags are null/bool/int/float/str; containers are list/dict. Dictionary
    entries are ordered [keynode, valuenode] pairs with only str/exact-int keys.
    Cycles and custom objects are rejected. Repeated references become separate
    decoded containers; alias-graph preservation is deliberately not promised.
    """
    try:
        body = _pack(delivery, _Budget(), set())
        if type(delivery) is not dict or not _hex(delivery.get("delivery_sha256")):
            _reject()
        envelope = {"schema": SCHEMA, "delivery_sha256": delivery["delivery_sha256"],
                    "body": body, "transport_sha256": "0" * 64}
        # The complete typed wire must fit BEFORE any legacy digest. Streaming
        # stops at the cap even for a compact DAG repeating large strings.
        _canonical_bytes(envelope, newline=True)
        frozen = _unpack(body, _Budget())
        _validate_delivery(frozen)
        unsigned = {k: v for k, v in envelope.items() if k != "transport_sha256"}
        envelope["transport_sha256"] = _transport_hash(unsigned)
        return _canonical_bytes(envelope, newline=True)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise PrivateDeliveryCodecError(_ERROR) from None


def deserialize_private_delivery(raw, *, expected_delivery_sha256=None):
    """Strictly decode this transport, returning fresh original V1 containers.

    expected_delivery_sha256, when supplied by an independent caller, binds the
    requested identity. Without it, a valid transport is only self-consistent.
    Neither mode authenticates source rights, producer execution or time.
    No plain V1 JSON repair, model rehashing, implicit fallback or file I/O.
    """
    try:
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_WIRE_BYTES
                or expected_delivery_sha256 is not None and not _hex(expected_delivery_sha256)):
            _reject()
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                              parse_constant=lambda _: _reject())
        if (type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS
                or envelope["schema"] != SCHEMA or not _hex(envelope["delivery_sha256"])
                or not _hex(envelope["transport_sha256"])):
            _reject()
        delivery = _unpack(envelope["body"], _Budget())
        if _canonical_bytes(envelope, newline=True) != raw:
            _reject()
        unsigned = {k: v for k, v in envelope.items() if k != "transport_sha256"}
        if (_transport_hash(unsigned) != envelope["transport_sha256"]
                or expected_delivery_sha256 is not None
                and expected_delivery_sha256 != envelope["delivery_sha256"]):
            _reject()
        _validate_delivery(delivery)
        if delivery["delivery_sha256"] != envelope["delivery_sha256"]:
            _reject()
        return delivery
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        raise PrivateDeliveryCodecError(_ERROR) from None
