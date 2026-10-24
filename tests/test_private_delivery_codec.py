"""Opt-in transport tests: all sources, races and permissions are fictional."""
import copy
import hashlib
import importlib
import json
import math
from pathlib import Path
import struct
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

from race_ai.comprehensive_four_sport_models import canonical, digest
from race_ai.four_sport_model_suite import ALL_MODELS, verify_suite
from race_ai.permissioned_source_delivery import deliver, _private_write
from tests.test_permissioned_source_delivery import AT, gate, raw_feed


SCHEMA = "RACE_AI_PRIVATE_DELIVERY_TRANSPORT_V1"
_FIXTURES = {}


def fixture(sport="boat"):
    if sport not in _FIXTURES:
        _FIXTURES[sport] = deliver(raw_feed(sport), gate(), at=AT, persist=False)
    return copy.deepcopy(_FIXTURES[sport])


def rehash(delivery, *, snapshot_links=False):
    """Prepare self-consistent fictional attacks; the codec must never do this."""
    suite = delivery["research_suite"]
    if snapshot_links:
        snapshot_hash = digest(delivery["snapshot"])
        delivery["feature_snapshot_sha256"] = snapshot_hash
        suite["input_sha256"] = snapshot_hash
        for model in suite["models"].values():
            model["snapshot_sha256"] = snapshot_hash
    for model in suite["models"].values():
        model["prediction_sha256"] = digest({k: v for k, v in model.items()
                                              if k != "prediction_sha256"})
    suite["suite_sha256"] = digest({k: v for k, v in suite.items() if k != "suite_sha256"})
    delivery["delivery_sha256"] = digest({k: v for k, v in delivery.items()
                                          if k != "delivery_sha256"})


def wire(document):
    unsigned = {k: v for k, v in document.items() if k != "transport_sha256"}
    document["transport_sha256"] = hashlib.sha256(
        SCHEMA.encode("ascii") + b"\0" + canonical(unsigned).encode("utf-8")).hexdigest()
    return (canonical(document) + "\n").encode("utf-8")


def member(node, key):
    for key_node, value_node in node[1]:
        if key_node == ["str", key]:
            return value_node
    raise AssertionError("fictional typed member missing")


class PrivateDeliveryCodecTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("race_ai.private_delivery_codec"),
                             "approved opt-in private delivery codec is missing")
        self.codec = importlib.import_module("race_ai.private_delivery_codec")

    def test_all_four_actual_suites_roundtrip_without_hash_or_order_changes(self):
        for sport, n in (("boat", 6), ("keirin", 7), ("autorace", 8), ("horse", 18)):
            with self.subTest(sport=sport):
                original = fixture(sport)
                before = copy.deepcopy(original)
                raw = self.codec.serialize_private_delivery(original)
                restored = self.codec.deserialize_private_delivery(
                    raw, expected_delivery_sha256=original["delivery_sha256"])
                self.assertLessEqual(len(raw), 4 * 1024 * 1024)
                self.assertEqual(restored, before)
                self.assertEqual(original, before)
                self.assertEqual(canonical(restored), canonical(original))
                self.assertEqual(tuple(restored["research_suite"]["models"]), ALL_MODELS)
                self.assertTrue(verify_suite(restored["research_suite"]))
                self.assertEqual(raw, self.codec.serialize_private_delivery(restored))
                for name in ALL_MODELS:
                    model = restored["research_suite"]["models"][name]
                    self.assertEqual(model["candidate_count"], n * (n - 1) * (n - 2))
                    self.assertEqual(len(model["ordered_top8"]), 8)
                    self.assertEqual(model["prediction_sha256"],
                                     original["research_suite"]["models"][name]["prediction_sha256"])
                    self.assertTrue(all(type(k) is int for k in model["missing_optional_by_participant"]))
                self.assertFalse(restored["can_count_in_hit_at_8"])
                self.assertFalse(restored["source_terms_independently_verified_by_code"])
                self.assertIsNone(restored["external_receipt"])

    def test_transport_hash_has_its_own_schema_domain_and_canonical_bytes(self):
        original = fixture()
        raw = self.codec.serialize_private_delivery(original)
        document = json.loads(raw)
        self.assertEqual(set(document), {"schema", "delivery_sha256", "body", "transport_sha256"})
        self.assertEqual(document["schema"], SCHEMA)
        self.assertEqual(document["delivery_sha256"], original["delivery_sha256"])
        unsigned = {k: v for k, v in document.items() if k != "transport_sha256"}
        expected = hashlib.sha256(SCHEMA.encode("ascii") + b"\0" +
                                  canonical(unsigned).encode("utf-8")).hexdigest()
        self.assertEqual(document["transport_sha256"], expected)
        self.assertNotEqual(expected, original["delivery_sha256"])
        self.assertEqual(raw, (canonical(document) + "\n").encode("utf-8"))

    def test_scalar_types_negative_zero_subnormals_and_unicode_survive_exactly(self):
        original = fixture()
        probe = [None, False, True, 0, 1, 1.0, -0.0, 5e-324, 1.7976931348623157e308,
                 "日本語/é/e\u0301/\u0000/😀"]
        original["research_suite"]["models"][ALL_MODELS[0]]["transport_probe"] = probe
        rehash(original)
        raw = self.codec.serialize_private_delivery(original)
        restored = self.codec.deserialize_private_delivery(raw)
        actual = restored["research_suite"]["models"][ALL_MODELS[0]]["transport_probe"]
        for expected, value in zip(probe, actual):
            self.assertIs(type(value), type(expected))
            if type(value) is float:
                self.assertEqual(struct.pack("!d", value), struct.pack("!d", expected))
            else:
                self.assertEqual(value, expected)
        self.assertEqual(math.copysign(1.0, actual[6]), -1)

    def test_decode_uses_fresh_containers_without_claiming_alias_graph_preservation(self):
        original = fixture()
        shared = {"fictional": [1, 2]}
        original["research_suite"]["models"][ALL_MODELS[0]]["transport_probe"] = [shared, shared]
        rehash(original)
        restored = self.codec.deserialize_private_delivery(self.codec.serialize_private_delivery(original))
        actual = restored["research_suite"]["models"][ALL_MODELS[0]]["transport_probe"]
        self.assertEqual(actual, [shared, shared])
        self.assertIsNot(actual[0], actual[1])
        actual[0]["fictional"].append(3)
        self.assertEqual(actual[1]["fictional"], [1, 2])
        self.assertEqual(shared["fictional"], [1, 2])

    def test_caller_expected_delivery_hash_is_optional_but_never_guessed(self):
        original = fixture()
        raw = self.codec.serialize_private_delivery(original)
        self.assertEqual(self.codec.deserialize_private_delivery(raw)["delivery_sha256"],
                         original["delivery_sha256"])
        for expected in ("e" * 64, "", "a" * 63, True, 1, "A" * 64):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.codec.deserialize_private_delivery(raw, expected_delivery_sha256=expected)

    def test_known_delivery_root_and_false_promotion_flags_are_required(self):
        changes = [("official_prediction", True), ("can_count_in_hit_at_8", True),
                   ("source_terms_independently_verified_by_code", True),
                   ("automatic_betting", True), ("supplemental_features_used_by_models", True),
                   ("external_receipt", {"fake": "authority"}), ("schema", "UNKNOWN"),
                   ("status", "FROZEN"), ("unknown", False)]
        for key, value in changes:
            original = fixture()
            original[key] = value
            rehash(original)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.codec.serialize_private_delivery(original)
        original = fixture()
        del original["source_payload_sha256"]
        rehash(original)
        with self.assertRaises(ValueError):
            self.codec.serialize_private_delivery(original)

    def test_rehashed_cross_race_or_cross_model_identity_links_fail(self):
        for location, key, value in (("delivery", "race_id", "boat:2030-01-15:other:1"),
                                     ("suite", "sport", "horse"),
                                     ("model", "race_id", "boat:2030-01-15:other:1"),
                                     ("model", "model_id", "wrong-model"),
                                     ("model", "as_of", "2030-01-15T09:11:00+09:00"),
                                     ("model", "race_revision", True),
                                     ("suite", "official_prediction", True)):
            original = fixture()
            suite = original["research_suite"]
            selected = original if location == "delivery" else suite if location == "suite" else suite["models"][ALL_MODELS[0]]
            selected[key] = value
            rehash(original)
            with self.subTest(location=location, key=key), self.assertRaises(ValueError):
                self.codec.serialize_private_delivery(original)

    def test_hash_chain_mutations_fail_without_rewriting_claimed_hashes(self):
        for location in ("delivery", "snapshot", "suite", "model"):
            original = fixture()
            if location == "delivery":
                original["delivery_sha256"] = "e" * 64
            elif location == "snapshot":
                original["snapshot"]["race"]["race_kind"] = "changed"
                rehash(original)
            elif location == "suite":
                original["research_suite"]["suite_sha256"] = "e" * 64
                original["delivery_sha256"] = digest({k: v for k, v in original.items() if k != "delivery_sha256"})
            else:
                original["research_suite"]["models"][ALL_MODELS[0]]["prediction_sha256"] = "e" * 64
                suite = original["research_suite"]
                suite["suite_sha256"] = digest({k: v for k, v in suite.items() if k != "suite_sha256"})
                original["delivery_sha256"] = digest({k: v for k, v in original.items() if k != "delivery_sha256"})
            before = copy.deepcopy(original)
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.codec.serialize_private_delivery(original)
            self.assertEqual(original, before)

    def test_decoded_original_and_envelope_delivery_hash_must_agree(self):
        document = json.loads(self.codec.serialize_private_delivery(fixture()))
        document["delivery_sha256"] = "e" * 64
        with self.assertRaises(ValueError):
            self.codec.deserialize_private_delivery(wire(document))

    def test_rehashed_transport_cannot_hide_original_payload_tampering(self):
        document = json.loads(self.codec.serialize_private_delivery(fixture()))
        member(document["body"], "status")[1] = "forged-secret-status"
        with self.assertRaises(ValueError) as caught:
            self.codec.deserialize_private_delivery(wire(document))
        self.assertNotIn("forged-secret-status", str(caught.exception))

    def test_noncanonical_json_and_wrong_wire_checksum_are_rejected(self):
        raw = self.codec.serialize_private_delivery(fixture())
        document = json.loads(raw)
        bad = [raw[:-1], raw + b"\n", b" " + raw,
               json.dumps(document, indent=2).encode(), b"\xef\xbb\xbf" + raw,
               raw.replace(b"fictional-venue", b"fictional-venuE", 1)]
        for changed in bad:
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                self.codec.deserialize_private_delivery(changed)

    def test_duplicate_json_members_unknown_envelopes_and_wire_types_fail(self):
        raw = self.codec.serialize_private_delivery(fixture())
        duplicated = b'{"schema":"' + SCHEMA.encode() + b'",' + raw[1:]
        with self.assertRaises(ValueError):
            self.codec.deserialize_private_delivery(duplicated)
        document = json.loads(raw)
        document["schema"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            self.codec.deserialize_private_delivery(wire(document))
        document = json.loads(raw)
        document["unknown"] = None
        with self.assertRaises(ValueError):
            self.codec.deserialize_private_delivery(wire(document))
        for wrong_type in (raw.decode(), bytearray(raw), memoryview(raw), None):
            with self.subTest(kind=type(wrong_type)), self.assertRaises(ValueError):
                self.codec.deserialize_private_delivery(wrong_type)

    def test_invalid_typed_tags_arities_key_types_and_duplicates_fail(self):
        base = json.loads(self.codec.serialize_private_delivery(fixture()))
        malformed = [["unknown", None], ["null", None], ["bool", 1], ["int", True],
                     ["float", 1], ["float", "0x1.0p+0"], ["str", 1],
                     ["list", {}], ["dict", [[["bool", True], ["null"]]]],
                     ["dict", [[["str", "x"], ["null"]], [["str", "x"], ["null"]]]],
                     ["dict", [[["int", 1], ["null"]], [["int", 1], ["null"]]]]]
        for body in malformed:
            document = copy.deepcopy(base)
            document["body"] = body
            with self.subTest(tag=body[0]), self.assertRaises(ValueError):
                self.codec.deserialize_private_delivery(wire(document))

    def test_resource_and_type_rejections_precede_legacy_hashing(self):
        class CustomDict(dict):
            pass

        bad_values = [float("nan"), float("inf"), (1, 2), b"private", object(),
                      {True: "private"}, {1.0: "private"}, CustomDict(), "あ" * 6000]
        for value in bad_values:
            original = fixture()
            original["supplemental_evidence"].append(value)
            with self.subTest(kind=type(value)), patch.object(
                    self.codec, "legacy_digest", side_effect=AssertionError("legacy hash must not run")):
                with self.assertRaises(ValueError):
                    self.codec.serialize_private_delivery(original)
        cyclic = fixture()
        cyclic["supplemental_evidence"].append(cyclic)
        deep = fixture()
        nested = deep["supplemental_evidence"]
        for _ in range(40):
            child = []
            nested.append(child)
            nested = child
        nodes = fixture()
        nodes["supplemental_evidence"] = [None] * 500001
        for original in (cyclic, deep, nodes):
            with patch.object(self.codec, "legacy_digest", side_effect=AssertionError("legacy hash must not run")):
                with self.assertRaises(ValueError):
                    self.codec.serialize_private_delivery(original)

    def test_repeated_large_string_tree_stops_streaming_before_large_allocation(self):
        original = fixture()
        original["supplemental_evidence"] = ["x" * 16384] * 1024  # 16MiB wire from one string.
        tracemalloc.start()
        try:
            with patch.object(self.codec, "legacy_digest", side_effect=AssertionError("legacy hash must not run")):
                with self.assertRaises(ValueError):
                    self.codec.serialize_private_delivery(original)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 12 * 1024 * 1024)

    def test_oversized_scalar_is_rejected_before_utf8_allocation_and_legacy_hash(self):
        original = fixture()
        oversized = "x" * (8 * 1024 * 1024)  # Allocate caller input before tracing.
        original["supplemental_evidence"].append(oversized)
        tracemalloc.start()
        try:
            with patch.object(self.codec, "legacy_digest", side_effect=AssertionError("legacy hash must not run")):
                with self.assertRaises(ValueError):
                    self.codec.serialize_private_delivery(original)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024 * 1024)

    def test_decoder_wire_and_tree_limits_precede_legacy_hashing(self):
        original_raw = self.codec.serialize_private_delivery(fixture())
        base = json.loads(original_raw)
        deep = ["null"]
        for _ in range(40):
            deep = ["list", [deep]]
        bad = [b"x" * (4 * 1024 * 1024 + 1)]
        for body in (["str", "x" * 16385], deep, ["float", float("inf")]):
            document = copy.deepcopy(base)
            document["body"] = body
            if body[0] == "float":
                changed = json.dumps(document, allow_nan=True).encode()
            else:
                changed = wire(document)
            bad.append(changed)
        for changed in bad:
            with patch.object(self.codec, "legacy_digest", side_effect=AssertionError("legacy hash must not run")):
                with self.assertRaises(ValueError):
                    self.codec.deserialize_private_delivery(changed)

    def test_plain_v1_files_are_not_implicitly_repaired_and_default_writer_is_unchanged(self):
        original = fixture()
        expected = (canonical(original) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fictional-private-v1.json"
            _private_write(output, original)
            self.assertEqual(output.read_bytes(), expected)
            with self.assertRaises(ValueError):
                self.codec.deserialize_private_delivery(output.read_bytes())
        self.assertEqual(original["schema"], "RACE_AI_PRIVATE_DELIVERY_V1")


if __name__ == "__main__":
    unittest.main()
