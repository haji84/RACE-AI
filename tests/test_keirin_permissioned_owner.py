"""Owner-private permit manifest and offline automatic stage tests.

The "licence document" in this test is invented, NOT a real grant.
"""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_permissioned_owner import (
    MANIFEST, LicenseDeliveryError, load_operator_grants,
    stage_permissioned_deliveries
)
from race_ai.keirin_preflight import expected_keys

RID = "keirin:2030-01-15:fictional-venue:1"
ASOF = "2030-01-15T09:10:00+09:00"
CUTOFF = "2030-01-15T10:00:00+09:00"
NOW = "2030-01-15T09:15:00+09:00"
SOURCE = "https://example.invalid/fictional-feed/one"
RIGHTS = "FICTIONAL_TEST_RIGHTS_ONLY"


def data():
    from test_keirin_allowed_delivery import fixture
    d = fixture()
    for o in d["observations"]:
        o["source_url"] = SOURCE
        o["rights_ref"] = RIGHTS
    d["race"]["permission_ref"] = "FIXTURE_APPROVED_BUNDLE"
    return d


class LicensedSourceStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.joinpath("raw").mkdir(mode=0o700)
        self.evidence = self.root / "signed-license-evidence.txt"
        self.evidence.write_text("FICTION ONLY. Not a licence.", encoding="utf-8")
        manifest = {
            "schema": MANIFEST, "bundle_id": "FIXTURE_APPROVED_BUNDLE",
            "grants": [{
                "source_url_prefix": "https://example.invalid/fictional-feed/",
                "rights_ref": RIGHTS,
                "purposes": ["schedule", "pre_race", "analysis",
                             "model_inference", "private_retention"],
                "valid_from": "2030-01-01T00:00:00+09:00",
                "valid_until": "2030-02-01T00:00:00+09:00",
                "license_document_path": str(self.evidence),
                "license_document_sha256":
                    sha256(self.evidence.read_bytes()).hexdigest(),
            }],
        }
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def grant(self):
        return load_operator_grants(self.manifest, now=NOW)

    def deposit(self, content):
        (self.root / "raw" / "inbound.json").write_text(
            json.dumps(content, ensure_ascii=False), encoding="utf-8"
        )

    def test_exact_license_prefix_and_rights(self):
        g = self.grant()
        self.assertTrue(g.allowed(SOURCE, RIGHTS, "model_inference"))
        self.assertFalse(g.allowed("https://example.invalid.evil.net/fictional-feed/",
                                   RIGHTS, "analysis"))
        self.assertFalse(g.allowed("https://example.invalid/bad-route",
                                   RIGHTS, "analysis"))
        self.assertFalse(g.allowed(SOURCE, "UNAPPROVED", "analysis"))
        self.assertFalse(g.allowed(SOURCE, RIGHTS, "auto_bet"))

    def test_missing_or_modified_license_document_stops(self):
        self.evidence.write_text("different data", encoding="utf-8")
        with self.assertRaisesRegex(LicenseDeliveryError, "DIGEST"):
            self.grant()

    def test_expired_license_stops(self):
        with self.assertRaisesRegex(LicenseDeliveryError, "EXPIRED"):
            load_operator_grants(
                self.manifest, now="2030-03-01T12:00:00+09:00")

    def test_operator_local_batch_staged_once_then_existing_model(self):
        self.deposit(data())
        g = self.grant()
        first = stage_permissioned_deliveries(self.root, g, now=NOW)
        self.assertEqual(first["provider_network_requests"], 0)
        self.assertFalse(first["source_rights_legally_certified_by_code"])
        self.assertEqual(first["new_pre_race_inputs"], 1)
        self.assertEqual(len(list((self.root/"pre").glob("*.json"))), 1)
        self.assertEqual(len(list((self.root/"audit").glob("*.json"))), 1)
        persisted = json.loads(next((self.root/"pre").glob("*.json")).read_text())
        self.assertEqual(len(persisted["facts"]["keirin_pre_race_audit_v1"]["items"]),
                         len(expected_keys(list(range(1,8)))))
        self.assertEqual(persisted["race_id"], RID)
        second = stage_permissioned_deliveries(self.root, g, now=NOW)
        self.assertEqual(second["already_staged"], 1)
        self.assertEqual(second["new_pre_race_inputs"], 0)
        # The feature input is compatible with existing PR71, but no real
        # third-party rights have been verified in this test fixture.
        from race_ai.keirin_pr71_model_adapter import run_pr71_for_next_race
        from race_ai.four_sport_model_suite import run_suite, verify_suite
        result = run_pr71_for_next_race(
            persisted, run_suite=run_suite, verify_suite=verify_suite,
            source_admission=g.allowed,
            model_id="multisport-scenario-ensemble-v1",
            issued_at="2030-01-15T09:20:00+09:00",
        )
        self.assertEqual(len(result["top8"]), 8)

    def test_incomplete_input_audited_but_never_staged_as_prediction(self):
        d = data()
        d["observations"] = [
            row for row in d["observations"]
            if row["key"] != "race/line_order_all_riders"
        ]
        self.deposit(d)
        report = stage_permissioned_deliveries(self.root, self.grant(), now=NOW)
        self.assertEqual(report["blocked_or_invalid_inputs"], 1)
        self.assertEqual(len(list((self.root/"pre").glob("*.json"))), 0)
        self.assertEqual(len(list((self.root/"audit").glob("*.json"))), 1)

    def test_no_provider_rights_becomes_blocked_and_no_private_forecast(self):
        d = data()
        for row in d["observations"]:
            row["source_url"] = "https://unlicensed.invalid/path"
        self.deposit(d)
        report = stage_permissioned_deliveries(self.root, self.grant(), now=NOW)
        self.assertEqual(report["blocked_or_invalid_inputs"], 1)
        self.assertEqual(list((self.root/"pre").glob("*.json")), [])

    def test_raw_packet_after_race_is_not_retroactively_staged(self):
        self.deposit(data())
        report = stage_permissioned_deliveries(
            self.root, self.grant(), now="2030-01-15T10:02:00+09:00")
        self.assertEqual(report["blocked_or_invalid_inputs"], 1)
        self.assertEqual(list((self.root/"pre").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
