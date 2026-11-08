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


    def full_v2(self, *, mutate=None):
        from itertools import permutations
        from race_ai.keirin_licensed_api_ingest import EXPORT_SCHEMA_V2
        from race_ai.keirin_licensed_odds_export import SCHEMA as ODDS_V2
        original=data()
        odds={
            "schema":ODDS_V2,
            "race_id":original["race"]["race_id"],
            "official_cutoff_at":original["race"]["official_cutoff_at"],
            "published_at":"2030-01-15T09:14:00+09:00",
            "source_url":"https://example.invalid/fictional-feed/odds",
            "rights_ref":"FICTIONAL_TEST_RIGHTS_ONLY",
            "prices":[{"triple":list(t),"decimal_odds":100+i/10}
                      for i,t in enumerate(permutations(range(1,8),3))]
        }
        if mutate:
            mutate(odds)
        return json.dumps({
            "schema":EXPORT_SCHEMA_V2,
            "bundle_id":"FIXTURE_APPROVED_BUNDLE",
            "deliveries":[original],
            "odds_snapshots":[odds],
        }).encode("utf-8")

    def test_one_permitted_get_carries_full_210_odds_plus_real_shaped_pre_input(self):
        from race_ai.keirin_variable_selection import ODDS_SCHEMA
        granted=self.allow_fetch()
        calls=[]
        body=self.full_v2()
        first=fetch_licensed_export_once(
            self.root,granted,
            endpoint=self.endpoint,rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            transport=lambda *args:calls.append(args) or body)
        self.assertEqual(len(calls),1)
        self.assertEqual(first["provider_packets_created"],1)
        self.assertEqual(first["licensed_full_odds_staged"]["full_odds_created"],1)
        saved=list((self.root/"odds").glob("*.json"))
        self.assertEqual(len(saved),1)
        odds=json.loads(saved[0].read_text())
        self.assertEqual(odds["schema"],ODDS_SCHEMA)
        self.assertEqual(len(odds["prices"]),210)
        self.assertEqual(odds["captured_at"],granted.now.isoformat())
        self.assertEqual(len({tuple(v["triple"]) for v in odds["prices"]}),210)
        staged=stage_permissioned_deliveries(self.root,granted,now=NOW)
        self.assertEqual(staged["new_pre_race_inputs"],1)
        again=fetch_licensed_export_once(
            self.root,granted,endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            transport=lambda *args:calls.append(args) or body)
        self.assertEqual(again["licensed_full_odds_staged"][
            "full_odds_already_staged"],1)
        self.assertEqual(len(calls),2)
        self.assertEqual(saved[0].read_text(),
                         json.dumps(odds,sort_keys=True,separators=(",",":"),
                                    ensure_ascii=False))

    def test_missing_or_invalid_licensed_odds_never_promotes_raw_packet(self):
        granted=self.allow_fetch()
        cases=[
            lambda x:x["prices"].pop(),
            lambda x:x["prices"].append(x["prices"][0]),
            lambda x:x["prices"][0].update(decimal_odds=9999.9),
            lambda x:x.update(source_url="https://keirin.kdreams.jp/api"),
            lambda x:x.update(published_at="2030-01-15T09:16:00+09:00"),
            lambda x:x.update(race_id="keirin:2030-01-15:other:1"),
        ]
        for alter in cases:
            with self.subTest(alter=repr(alter)):
                body=self.full_v2(mutate=alter)
                with self.assertRaises(LicenseDeliveryError):
                    fetch_licensed_export_once(
                        self.root,granted,
                        endpoint=self.endpoint,
                        rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                        transport=lambda *_:body)
                self.assertEqual(len(list((self.root/"odds").glob("*.json"))),0)
                self.assertEqual(len(list((self.root/"raw").glob("*.json"))),0)

    def test_licensed_odds_polls_after_cutoff_preserve_first_capture_without_new_sidecar(self):
        granted=self.allow_fetch()
        body=self.full_v2()
        fetch_licensed_export_once(
            self.root,granted,endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            transport=lambda *_:body)
        archived=list((self.root/"odds").glob("*.json"))
        self.assertEqual(len(archived),1)
        first=archived[0].read_bytes()
        next_grant=load_operator_grants(
            self.manifest,now="2030-01-15T10:05:00+09:00")
        again=fetch_licensed_export_once(
            self.root,next_grant,endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            transport=lambda *_:body)
        self.assertEqual(again["licensed_full_odds_staged"][
            "full_odds_already_staged"],1)
        self.assertEqual(again["licensed_full_odds_staged"][
            "full_odds_created"],0)
        self.assertEqual(archived[0].read_bytes(),first)

    def test_licensed_odds_changed_after_first_save_is_never_rewritten(self):
        granted=self.allow_fetch()
        body=self.full_v2()
        fetch_licensed_export_once(
            self.root,granted,endpoint=self.endpoint,
            rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
            transport=lambda *_:body)
        file=next((self.root/"odds").glob("*.json"))
        frozen=file.read_bytes()
        def different(odds):
            odds["prices"][0]["decimal_odds"]=111.1
        altered=self.full_v2(mutate=different)
        with self.assertRaisesRegex(LicenseDeliveryError,
                                    "IMMUTABLE_CONFLICT"):
            fetch_licensed_export_once(
                self.root,granted,endpoint=self.endpoint,
                rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                transport=lambda *_:altered)
        self.assertEqual(file.read_bytes(),frozen)

    def test_v2_machine_permission_must_exist_before_any_transport(self):
        calls=[]
        with self.assertRaisesRegex(
                LicenseDeliveryError,
                "AUTOMATED_SOURCE_ACCESS_NOT_AUTHORIZED"):
            fetch_licensed_export_once(
                self.root,self.grant(),
                endpoint=self.endpoint,
                rights_ref="FICTIONAL_TEST_RIGHTS_ONLY",
                transport=lambda *args:calls.append(args) or self.full_v2())
        self.assertEqual(calls,[])


if __name__ == "__main__":
    unittest.main()
