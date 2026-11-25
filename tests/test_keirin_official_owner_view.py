"""Offline local snapshot viewer: no providers, Git writes, or real owner keys."""
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import stat
import unittest

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_official_run_history as history
from scripts import keirin_official_owner_view as viewer
from tests.test_keirin_official_owner_report import examples


class OfflineOwnerView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        self.key_path = self.root / "existing-owner.pem"
        self.key_path.write_bytes(self.private)
        self.key_path.chmod(0o600)
        self.cipher = self.root / "owner-view.sealed.json"
        self.output = self.root / "owner-report.html"
        pin = patch.object(storage, "PINNED_OWNER_SPKI_SHA256", self.pin)
        pin.start()
        self.addCleanup(pin.stop)
        self.write_snapshot()

    def write_snapshot(self, schema="RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DAY_V1"):
        report, rows = examples()
        data = {"schema": schema, "day_jst": report["day_jst"],
                "safe_report": report, "owner_rows": rows,
                "private_source": "RAW_SOURCE_MUST_NOT_BE_RENDERED"}
        self.cipher.write_bytes(history.seal_evidence(
            data, self.public, report["day_jst"], "2026-11-19T18:00:00+09:00"))

    def invoke(self, **replace):
        args = {"cipher": self.cipher, "owner-private-pem": self.key_path,
                "out": self.output}
        args.update(replace)
        argv = [value for key, path in args.items() for value in ("--" + key, str(path))]
        output = StringIO()
        with redirect_stdout(output):
            status = viewer.main(argv)
        return status, output.getvalue()

    def test_actual_local_decrypt_render_creates_private_html_without_network_or_input_changes(self):
        before = (self.cipher.read_bytes(), self.key_path.read_bytes())
        with patch.object(history, "read_revisions", side_effect=AssertionError("network forbidden")), \
             patch.object(history.archive, "_cmd", side_effect=AssertionError("Git forbidden")):
            status, log = self.invoke()
        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        soup = BeautifulSoup(self.output.read_text(), "html.parser")
        _, expected_rows = examples()
        expected_ids = {row["race_id"] for row in expected_rows}
        ids_by_view = []
        for panel_id in ("races-venue", "races-cutoff"):
            panel = soup.find(id=panel_id)
            self.assertIsNotNone(panel)
            ids = [card["data-race-id"] for card in panel.select("article[data-race-id]")]
            self.assertEqual(len(ids), 4)
            self.assertEqual(len(set(ids)), 4)
            self.assertEqual(set(ids), expected_ids)
            ids_by_view.append(set(ids))
        self.assertEqual(ids_by_view[0], ids_by_view[1])
        self.assertEqual((self.cipher.read_bytes(), self.key_path.read_bytes()), before)
        self.assertNotIn("RAW_SOURCE_MUST_NOT_BE_RENDERED", self.output.read_text())
        self.assertNotIn("PRIVATE KEY", log)
        self.assertNotIn("ranked_tickets", log)
        self.assertNotIn("1-2-3", log)
        self.assertEqual(json.loads(log)["state"], "PRIVATE_OWNER_VIEW_CREATED")

    def test_delta_is_rejected_with_full_snapshot_code_and_no_output(self):
        self.write_snapshot("RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1")
        status, log = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn("FULL_SNAPSHOT_REQUIRED", log)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.write_text("existing private report")
        status, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertEqual(self.output.read_text(), "existing private report")

    def test_symlink_input_output_and_parent_are_rejected(self):
        key_link = self.root / "key-link.pem"
        key_link.symlink_to(self.key_path)
        status, _ = self.invoke(**{"owner-private-pem": key_link})
        self.assertEqual(status, 2)
        cipher_link = self.root / "cipher-link.json"
        cipher_link.symlink_to(self.cipher)
        status, _ = self.invoke(cipher=cipher_link)
        self.assertEqual(status, 2)
        target = self.root / "untouched.html"
        self.output.symlink_to(target)
        status, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertFalse(target.exists())
        self.output.unlink()
        directory = self.root / "actual-private"
        directory.mkdir(mode=0o700)
        alias = self.root / "alias-private"
        alias.symlink_to(directory, target_is_directory=True)
        status, _ = self.invoke(out=alias / "view.html")
        self.assertEqual(status, 2)
        self.assertEqual(list(directory.iterdir()), [])

    def test_world_readable_output_folder_and_private_key_are_rejected(self):
        public = self.root / "not-private"
        public.mkdir(mode=0o755)
        # mkdir's mode is filtered by the runner umask (0077 in Codex).
        # This negative fixture must actually be world-readable.
        public.chmod(0o755)
        status, _ = self.invoke(out=public / "view.html")
        self.assertEqual(status, 2)
        self.assertEqual(list(public.iterdir()), [])
        self.key_path.chmod(0o644)
        status, log = self.invoke()
        self.assertEqual(status, 2)
        self.assertIn("KEY_PERMISSIONS", log)
        self.assertFalse(self.output.exists())

    def test_public_workspace_output_is_refused_even_when_folder_mode_is_private(self):
        (self.root / ".git").mkdir()
        status, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertFalse(self.output.exists())

    def test_wrong_key_or_cipher_tampering_never_creates_partial_html(self):
        self.key_path.write_bytes(b"INVALID PRIVATE PEM CONTENT")
        status, log = self.invoke()
        self.assertEqual(status, 2)
        self.assertNotIn("INVALID PRIVATE PEM CONTENT", log)
        self.assertFalse(self.output.exists())
        self.key_path.write_bytes(self.private)
        self.cipher.write_bytes(self.cipher.read_bytes() + b"\n")
        status, _ = self.invoke()
        self.assertEqual(status, 2)
        self.assertFalse(self.output.exists())

    def test_argument_errors_do_not_echo_user_supplied_secret_text(self):
        output = StringIO()
        with redirect_stdout(output):
            status = viewer.main(["--unsupported", "PRIVATE_KEY_SENTINEL"])
        self.assertEqual(status, 2)
        self.assertNotIn("PRIVATE_KEY_SENTINEL", output.getvalue())


class ActualPipelineMetricIntegration(unittest.TestCase):
    def test_renderer_uses_actual_root_pipeline_scorecard_and_each_arms_stake(self):
        from tests.test_keirin_official_day_pipeline import OfficialCollectedSettlement
        from race_ai.keirin_official_owner_report import render_private_report
        case = OfficialCollectedSettlement()
        self.addCleanup(case.doCleanups)
        case.setUp()
        report, rows, _ = case.run_pipeline()
        soup = BeautifulSoup(render_private_report(report, rows), "html.parser")
        self.assertEqual(report["paired_A_B_scored"], 1)
        expected_keys = {"hit_at_1", "hit_at_all", "hit_at_1_rate", "hit_at_all_rate",
                         "stake_yen", "payout_yen", "virtual_roi", "virtual_profit_yen"}
        scored_row = next(row for row in rows if row["state"] == "AB_SETTLED_FROM_INDEPENDENT_RECEIPTS")
        for role, key in (("A", "A_existing"), ("B", "B_six_phase")):
            stats = report["scorecard"][key]
            self.assertTrue(expected_keys <= set(stats))
            panel = soup.select_one(f'#comparison [data-model="{role}"]')
            self.assertEqual({node["data-metric"] for node in panel.select("[data-metric]")}, expected_keys)
            self.assertNotIn("未集計", panel.text)
            self.assertEqual(panel.select_one('[data-metric="stake_yen"]').text,
                             f'{100 * len(scored_row[role]["ranked_tickets"]):,}円')


if __name__ == "__main__":
    unittest.main()

