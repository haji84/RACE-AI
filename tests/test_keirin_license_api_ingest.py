"""Only simulated source transport. No live HTTP or real license claims."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_licensed_api_ingest import (
    EXPORT_SCHEMA, LicenseDeliveryError, fetch_licensed_export_once
)
from race_ai.keirin_permissioned_owner import (
    load_operator_grants, stage_permissioned_deliveries
)
import test_keirin_permissioned_owner as prior
from test_keirin_permissioned_owner import data, NOW


class LicenseApiFetchTests(unittest.TestCase):
    def setUp(self):
        prior.LicensedSourceStageTests.setUp(self)
        self.endpoint = "https://example.invalid/fictional-feed/api/daily"

    def tearDown(self):
        prior.LicensedSourceStageTests.tearDown(self)

    def grant(self):
        return prior.LicensedSourceStageTests.grant(self)

    def allow_fetch(self):
        value = json.loads(self.manifest.read_text())
        value["grants"][0]["purposes"].append("automated_fetch")
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        return load_operator_grants(self.manifest, now=NOW)

    def batch(self, packets=None):
        return json.dumps({
            "schema": EXPORT_SCHEMA,
            "bundle_id": "FIXTURE_APPROVED_BUNDLE",
            "deliveries": [data()] if packets is None else packets
        }).encode("utf-8")

    def test_without_machine_fetch_license_no_network_even_if_offline_allowed(self):
        requests = []
        with self.assertRaisesRegex(LicenseDeliveryError,
                                    "AUTOMATED_SOURCE_ACCESS_NOT_AUTHORIZED"):
            fetch_licensed_export_once(
                self.root, self.grant(),
                endpoint=self.endpoint, rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                transport=lambda *args: requests.append(args) or self.batch()
            )
        self.assertEqual(requests, [])

    def test_exact_approved_api_one_request_and_private_delivery(self):
        granted = self.allow_fetch()
        calls = []
        def fake_once(url, token):
            calls.append((url, token))
            return self.batch()
        report = fetch_licensed_export_once(
            self.root, granted, endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            token="FAKE_TEST_TOKEN", transport=fake_once
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(report["http_requests"], 0)  # injected transport
        self.assertEqual(report["provider_packets_created"], 1)
        self.assertEqual(len(list((self.root/"raw").glob("*.json"))), 1)
        result = stage_permissioned_deliveries(self.root, granted, now=NOW)
        self.assertEqual(result["new_pre_race_inputs"], 1)
        replay = fetch_licensed_export_once(
            self.root, granted, endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY", transport=fake_once
        )
        self.assertEqual(replay["provider_packets_already_present"], 1)
        self.assertEqual(replay["provider_packets_created"], 0)

    def test_unapproved_domain_ip_and_wrong_rights_never_fetch(self):
        granted = self.allow_fetch()
        calls = []
        fake = lambda *_: calls.append(1) or self.batch()
        for url, rights in [
            ("https://example.invalid.evil.net/fictional-feed/api/daily",
             "FICTIONAL_TEST_RIGHTS_ONLY"),
            ("http://example.invalid/fictional-feed/api/daily",
             "FICTIONAL_TEST_RIGHTS_ONLY"),
            ("https://127.0.0.1/fictional-feed/api/daily",
             "FICTIONAL_TEST_RIGHTS_ONLY"),
            (self.endpoint, "FAKE_OTHER_RIGHTS")
        ]:
            with self.assertRaises(LicenseDeliveryError):
                fetch_licensed_export_once(
                    self.root, granted,
                    endpoint=url, rights_ref=rights, transport=fake)
        self.assertEqual(calls, [])

    def test_rakuten_api_never_requested_even_with_approved_other_feed(self):
        requests = []
        with self.assertRaisesRegex(LicenseDeliveryError, "RAKUTEN_SOURCE_EXCLUDED"):
            fetch_licensed_export_once(
                self.root, self.allow_fetch(),
                endpoint="https://keirin.kdreams.jp/fictional-feed/api/daily",
                rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                transport=lambda *_: requests.append(1) or self.batch()
            )
        self.assertEqual(requests, [])

    def test_invalid_json_denied_without_partial_raw_files(self):
        granted = self.allow_fetch()
        with self.assertRaises(LicenseDeliveryError):
            fetch_licensed_export_once(
                self.root, granted, endpoint=self.endpoint,
                rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                transport=lambda *_: b'{"schema": "wrong"}'
            )
        self.assertEqual(list((self.root/"raw").glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
