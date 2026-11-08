"""Owner approved personal-use WINTICKET/KEIRIN.JP sources, no live HTTP."""
from __future__ import annotations

import unittest
from race_ai.keirin_owner_approved_sources import (
    PROFILE_ID, PROFILE_HOSTS, OwnerApprovedSourceError,
    approved_source_hosts, classify_owner_source, owner_approved_source_profile
)
from race_ai.keirin_owner_manual import (
    PERSONAL_MARKER, PersonalOwnerObservations
)


class OwnerSourceProfileTests(unittest.TestCase):
    def test_approved_sites_allow_private_locally_saved_observations(self):
        grants = PersonalOwnerObservations(
            source_hosts=approved_source_hosts(PROFILE_ID),
            now="2030-01-15T09:12:00+09:00")
        for origin in (
            "https://keirin.jp/pc/dfw/portal/guest/race/",
            "https://www.keirin.jp/pc/",
            "https://www.winticket.jp/keirin/aomori/racecard/",
            "https://winticket.jp/keirin/aomori/odds/"
        ):
            self.assertEqual(
                classify_owner_source(origin),
                "OWNER_APPROVED_PRIVATE_MANUAL_REFERENCE_ONLY")
            self.assertTrue(grants.allowed(origin,PERSONAL_MARKER,"analysis"))
            self.assertTrue(grants.allowed(
                origin,PERSONAL_MARKER,"private_retention"))
            self.assertFalse(grants.allowed(
                origin,PERSONAL_MARKER,"automated_fetch"))
            self.assertFalse(grants.allowed(
                origin,PERSONAL_MARKER,"public_redistribution"))

    def test_no_subdomain_spoofing_other_sites_or_unapproved_paths(self):
        grants=PersonalOwnerObservations(
            source_hosts=PROFILE_HOSTS,now="2030-01-15T09:12:00+09:00")
        for origin in (
            "https://winticket.jp.evil.example/keirin",
            "https://notwinticket.jp/keirin",
            "https://evil.keirin.jp/race",
            "https://keirin.kdreams.jp/",
            "https://www.winticket.jp.evil.test",
            "http://www.winticket.jp/keirin",
            "https://user:password@keirin.jp/pc",
            "https://www.winticket.jp:444/keirin"
        ):
            self.assertNotEqual(
                classify_owner_source(origin),
                "OWNER_APPROVED_PRIVATE_MANUAL_REFERENCE_ONLY")
            self.assertFalse(grants.allowed(origin,PERSONAL_MARKER,"analysis"))

    def test_profile_not_a_provider_machine_fetch_licence(self):
        p=owner_approved_source_profile()
        self.assertEqual(p["source_ids"],["keirin_official","winticket"])
        self.assertEqual(p["source_hosts"],list(PROFILE_HOSTS))
        self.assertFalse(p["direct_html_machine_fetch_authorized"])
        self.assertFalse(p["third_party_api_authorized"])
        self.assertFalse(p["commercial_or_redistribution_authorized"])
        self.assertFalse(p["real_forecast_or_pre_cutoff_witness_proven"])

    def test_owner_manual_profile_runs_without_any_provider_request(self):
        import contextlib
        import io
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import os
        from scripts.keirin_permissioned_owner_agent import main
        with TemporaryDirectory() as folder:
            path=Path(folder)
            stdout=io.StringIO()
            # CI GitHub runners are intentionally rejected as owner stores.
            # This unit case simulates an already protected owner-local disk.
            with patch.dict(os.environ,
                            {"GITHUB_ACTIONS":"false","GITHUB_WORKSPACE":""}):
                with patch(
                    "scripts.keirin_permissioned_owner_agent.fetch_licensed_export_once",
                    side_effect=AssertionError("MUST_NOT_USE_REMOTE_PROVIDER")):
                    with contextlib.redirect_stdout(stdout):
                        status=main([
                            "--db", str(path/"owner.sqlite3"),
                            "--inbox", str(path),
                            "--personal-manual",
                            "--owner-private-use-confirmed",
                            "--owner-approved-source-profile", PROFILE_ID
                        ])
            self.assertEqual(status,0,stdout.getvalue())
            report=json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertEqual(report["provider_network_requests"],0)
            self.assertFalse(report["automatic_provider_fetch"])
            self.assertTrue(report["owner_self_attested_private_only"])
            self.assertFalse(report["provider_permission_inferred_from_personal_use"])
            self.assertFalse(report["official_pre_cutoff_witness"])

    def test_profile_conflict_and_machine_mode_are_rejected(self):
        import contextlib
        import io
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from scripts.keirin_permissioned_owner_agent import main
        with TemporaryDirectory() as folder:
            path=Path(folder)
            common=["--db",str(path/"owner.sqlite3"),
                    "--inbox",str(path),
                    "--owner-approved-source-profile",PROFILE_ID]
            for options in (
                common + ["--personal-manual","--owner-private-use-confirmed",
                          "--personal-source-host","other.example"],
                common + ["--operator-reviewed-licenses"],
            ):
                with self.subTest(options=options),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(options),2)
                self.assertFalse((path/"owner.sqlite3").exists())

    def test_other_profile_rejected(self):
        with self.assertRaises(OwnerApprovedSourceError):
            approved_source_hosts("all_sites_machine_fetch_approved")


if __name__=="__main__":
    unittest.main()
