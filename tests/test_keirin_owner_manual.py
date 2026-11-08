"""Fully offline owner-only source intake tests. All observations are invented.

No API, no licence agreement, no claim of provider-authenticated data.
"""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from race_ai.keirin_owner_manual import (
    PERSONAL_MARKER, PersonalOwnerObservations, PersonalOwnerError,
)
from race_ai.keirin_permissioned_owner import stage_permissioned_deliveries
from race_ai.keirin_private_spool import KeirinPrivateSpool
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.four_sport_model_suite import run_suite, verify_suite
from test_keirin_allowed_delivery import fixture, RID


NOW = "2030-01-15T09:15:00+09:00"


def manual_fixture():
    d = fixture(full=True)
    d["race"]["permission_ref"] = PERSONAL_MARKER
    for obs in d["observations"]:
        obs["rights_ref"] = PERSONAL_MARKER
    return d


class ManualOnlyTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        (self.root / "raw").mkdir()
        self.now = lambda: datetime.fromisoformat(
            "2030-01-15T09:16:00+09:00")
        self.grants = PersonalOwnerObservations(
            source_hosts=["example.invalid"], now=NOW)

    def deposit(self, obj):
        (self.root / "raw" / "owner-input.json").write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_self_captured_private_no_contract_required_for_offline_e2e(self):
        self.deposit(manual_fixture())
        report = stage_permissioned_deliveries(
            self.root, self.grants, now=NOW)
        self.assertEqual(report["new_pre_race_inputs"], 1)
        self.assertEqual(report["provider_network_requests"], 0)
        self.assertFalse(report["source_rights_legally_certified_by_code"])
        with PrivateKeirinStore(self.root/"owner.sqlite3", clock=self.now) as store:
            engine = KeirinPrivateSpool(
                store, clock=self.now, model_suite=run_suite,
                model_verifier=verify_suite,
                source_attestor=self.grants.certificate,
                source_observation_gate=self.grants.allowed,
                witness=None)
            tick = engine.tick(self.root)
            self.assertEqual(tick["private_forecasts_saved_this_tick"], 1,
                             tick)
            forecast = store.get_persisted_forecast(RID)
            self.assertEqual(len(forecast["forecast"]["top8"]), 8)
            self.assertFalse(forecast["external_receipt_verified"])
            prior = forecast["sha256"]
            self.assertEqual(engine.tick(self.root)[
                "private_forecasts_saved_this_tick"], 0)
            self.assertEqual(store.get_persisted_forecast(RID)["sha256"],
                             prior)

    def test_unknown_origin_not_accepted_even_manual(self):
        d = manual_fixture()
        d["observations"][0]["source_url"] = "https://unfamiliar.example/path"
        self.deposit(d)
        report = stage_permissioned_deliveries(
            self.root, self.grants, now=NOW)
        self.assertEqual(report["blocked_or_invalid_inputs"], 1)
        self.assertFalse(list((self.root/"pre").glob("*.json")))

    def test_machine_fetch_is_never_in_personal_permissions(self):
        self.assertFalse(self.grants.allowed(
            "https://example.invalid/a", PERSONAL_MARKER,
            "automated_fetch"))
        self.assertFalse(self.grants.allowed(
            "https://example.invalid/a", "SOME_PERSONAL_TEXT",
            "model_inference"))
        with self.assertRaises(PersonalOwnerError):
            PersonalOwnerObservations(
                source_hosts=["example.invalid@evil.example"], now=NOW)

    def test_non_rakuten_hosts_only_even_for_local_owner_data(self):
        for host in ("keirin.kdreams.jp", "kdreams.jp",
                     "www.rakuten.co.jp"):
            with self.subTest(host=host):
                with self.assertRaisesRegex(PersonalOwnerError, "RAKUTEN"):
                    PersonalOwnerObservations(source_hosts=[host], now=NOW)
        owner = PersonalOwnerObservations(
            source_hosts=["www.keirin.jp", "www.winticket.jp", "sp.oddspark.com"],
            now=NOW)
        self.assertTrue(owner.allowed(
            "https://www.keirin.jp/pc/raceschedule", PERSONAL_MARKER,
            "model_inference"))
        self.assertFalse(owner.allowed(
            "https://keirin.kdreams.jp/a", PERSONAL_MARKER, "analysis"))

    def test_missing_core_still_blocks_prediction(self):
        d = manual_fixture()
        d["observations"] = [
            o for o in d["observations"]
            if o["key"] != "race/line_order_all_riders"]
        self.deposit(d)
        result = stage_permissioned_deliveries(
            self.root, self.grants, now=NOW)
        self.assertEqual(result["blocked_or_invalid_inputs"], 1)
        self.assertEqual(len(list((self.root/"audit").glob("*.json"))),1)
        self.assertEqual(list((self.root/"pre").glob("*.json")), [])

    def test_personal_cli_no_licence_manifest_required(self):
        from scripts.keirin_permissioned_owner_agent import main
        # This test exercises the actual CLI with synthetic input and one-shot
        # execution. The CLI uses wall clock (2026 in CI); the fixed 2030
        # synthetic race MUST fail closed instead of fabricating a future source.
        import os
        from unittest.mock import patch
        # Isolate this local-process CLI test from the GitHub Actions
        # ephemeral-storage protection. Production guard stays unchanged.
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            self.assertEqual(main([
                "--db", str(self.root/"owner.sqlite3"), "--inbox", str(self.root),
                "--personal-manual", "--owner-private-use-confirmed",
                "--personal-source-host", "example.invalid",
            ]), 0)
        self.assertEqual(main([
            "--db", str(self.root/"owner.sqlite3"), "--inbox", str(self.root),
            "--personal-manual", "--owner-private-use-confirmed",
            "--personal-source-host", "example.invalid",
            "--provider-endpoint", "https://example.invalid/a",
            "--provider-rights-ref", PERSONAL_MARKER,
        ]), 2)


if __name__ == "__main__":
    unittest.main()
