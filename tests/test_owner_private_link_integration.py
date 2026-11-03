"""Synthetic-only PR72 integration of a real filesystem reader callback.

Fictional source authorization and receipt verifier MUST NEVER be reused as
production proof. Tests assert that score and official completeness stay null.
"""
from hashlib import sha256
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from race_ai.owner_private_file_reader import OwnerPrivateFileReader
from race_ai.official_private_receipt_link import link_protected_receipts

DAY = "2031-01-05"
RACE = "boat:2031-01-05:v-boat:1"
CUTOFF = "2031-01-05T11:00:00+09:00"
WIRE = b'{"schema":"fictional_forecast","picks":["1-2-3"]}'


def fixtures():
    bridge = {
        "schema": "RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1",
        "mode": "OFFLINE_RESEARCH_COVERAGE_LINK",
        "event_date_jst": DAY,
        "official_completeness_verified": False,
        "source_rights_verified": False,
        "external_pre_cutoff_receipts_verified": False,
        "formal_hit_at_8_all": None,
        "records": [
            {"race_id": RACE, "sport": "boat", "venue": "v-boat",
             "race_no": 1, "archive_slots": [], "ledger_no_forecast_reason": None}
        ],
    }
    source = {
        "race_id": RACE, "source_id": "test-only", "source_sha256": "a"*64,
        "permission_ref": "fictional-only", "published_at": "2031-01-05T08:00:00+09:00",
        "observed_at": "2031-01-05T08:30:00+09:00", "official_cutoff_at": CUTOFF,
    }
    original_sha = sha256(WIRE).hexdigest()
    name = sha256((RACE + "\0m1\0" + original_sha).encode()).hexdigest()
    forecast = {
        "race_id": RACE, "model_id": "m1", "model_version": "v1", "stage": "P0",
        "original_wire_sha256": original_sha,
        "original_generated_at": "2031-01-05T10:00:00+09:00",
        "private_persisted_at": "2031-01-05T10:01:00+09:00",
        "private_ref": "owner:one", "cutoff_at": CUTOFF,
        "github_receipt": {"run_id": 123,
                           "path": f"audit/freezes/{DAY}/{name}.json"},
        "provenance": "PROSPECTIVE_PROTECTED_OWNER_ORIGINAL",
    }
    return bridge, [source], [forecast]


def fake_source_attestor(src):
    return {
        "race_id": src["race_id"], "source_sha256": src["source_sha256"],
        "permission_ref": src["permission_ref"],
        "cutoff_at": src["official_cutoff_at"],
        "admitted_uses": ["schedule", "pre_race", "private_retention"],
    }


def fake_validator(wire, item):
    return {
        "race_id": item["race_id"], "model_id": item["model_id"],
        "model_version": item["model_version"], "stage": item["stage"],
        "wire_sha256": sha256(wire).hexdigest(), "top8_count": 1,
    }


class OwnerReaderLinkIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "original.json").write_bytes(WIRE)
        self.reader = OwnerPrivateFileReader(
            self.root, {"owner:one": ("original.json", sha256(WIRE).hexdigest())})

    def run_link(self, **overrides):
        bridge, sources, forecasts = fixtures()
        with patch("race_ai.race_bound_freeze_receipt.verify_bound_receipt",
                   return_value=True) as witness:
            report = link_protected_receipts(
                bridge, sources, forecasts,
                source_attestor=overrides.get("attestor", fake_source_attestor),
                protected_reader=overrides.get("reader", self.reader),
                forecast_validator=fake_validator,
                trusted_legacy_verifier=lambda *a, **kw: True,
                github_fetch=lambda url: {},
            )
        return report, witness

    def test_real_local_file_callback_reaches_existing_pr72_linker(self):
        result, witness = self.run_link()
        row = result["records"][0]["private_checks"][0]
        self.assertEqual(row["status"],
                         "CALLBACK_BOUND_PROOFS_REQUIRE_INDEPENDENT_OPERATOR_AUDIT")
        self.assertTrue(row["protected_original_sha_checked"])
        self.assertTrue(row["external_receipt_checked"])
        witness.assert_called_once()
        self.assertIsNone(result["formal_hit_at_8_all"])
        self.assertFalse(result["all_official_races_verified"])
        self.assertNotIn("1-2-3", str(result))

    def test_fake_source_without_permission_must_not_read_private_file(self):
        blocked_reader = Mock(side_effect=AssertionError("must not read"))
        result, witness = self.run_link(attestor=None, reader=blocked_reader)
        self.assertEqual(result["records"][0]["private_checks"][0]["status"],
                         "SOURCE_GATE_BLOCKED")
        blocked_reader.assert_not_called()
        witness.assert_not_called()

    def test_file_modified_since_pin_fails_before_external_receipt(self):
        (self.root / "original.json").write_bytes(b"changed")
        result, witness = self.run_link()
        self.assertEqual(result["records"][0]["private_checks"][0]["status"],
                         "PRIVATE_READBACK_OR_VALIDATION_ERROR")
        witness.assert_not_called()
        self.assertEqual(result["external_receipts_checked"], 0)


if __name__ == "__main__":
    unittest.main()
