"""Synthetic GitHub API metadata; no fixture is a real timestamp attestation."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import unittest
from zipfile import ZipFile, ZIP_DEFLATED


REPO = "haji84/RACE-AI"
REPO_ID = 1416489937
RUN_ID = 123456
HEAD = "a" * 40
RID = "202611182601"
CIPHER = b"synthetic immutable ciphertext, not a real forecast\n"
DIGEST = sha256(CIPHER).hexdigest()
API = f"https://api.github.com/repos/{REPO}"


def archive_bytes(member, content):
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(member, content)
    return stream.getvalue()


def report_bytes(document):
    return json.dumps(document, separators=(",", ":")).encode() + b"\n"


def evidence_fixture():
    run = {
        "id": RUN_ID, "url": f"{API}/actions/runs/{RUN_ID}",
        "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}",
        "repository": {"id": REPO_ID, "full_name": REPO},
        "head_repository": {"id": REPO_ID, "full_name": REPO},
        "head_branch": "main", "head_sha": HEAD, "event": "schedule",
        "path": ".github/workflows/keirin-nationwide-ab-auto.yml",
        "run_attempt": 1, "status": "completed", "conclusion": "success",
        "created_at": "2026-11-18T00:55:00Z",
        "run_started_at": "2026-11-18T00:55:10Z",
        "updated_at": "2026-11-18T01:04:00Z",
    }
    producer_report = {
        "schema": "RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1",
        "day_jst": "2026-11-18", "new_A_B_sealed": 1,
        "new_A_B_git_archived": 1,
        "new_encrypted_originals": [{"race_id": RID, "cipher_sha256": DIGEST}],
    }
    readback_report = {
        "schema": "RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1",
        "day_jst": "2026-11-18", "new_archived": 1,
        "independently_verified": 1,
        "RSA_private_decryption_verified": False,
        "organizer_result_verified": False,
        "records": [{"race_id": RID, "cipher_sha256": DIGEST,
                     "state": "SECOND_RUNNER_GITHUB_SHA_CONFIRMED"}],
    }
    packets = []
    for kind, job_id, artifact_id, started, created, completed, report, member in (
        ("producer", 1001, 2001, "00:56:00", "01:00:00", "01:01:00",
         producer_report, "summary.json"),
        ("readback", 1002, 2002, "01:02:00", "01:03:00", "01:04:00",
         readback_report, "keirin-git-independent.json"),
    ):
        stamp = lambda value: f"2026-11-18T{value}Z"
        payload = archive_bytes(member, report_bytes(report))
        job_name = ("github-only-owner-capture" if kind == "producer" else
                    "github-only-independent-archive-readback")
        artifact_prefix = ("keirin-github-only-ab-receipt" if kind == "producer"
                           else "keirin-github-only-ab-readback")
        job = {
            "id": job_id, "run_id": RUN_ID,
            "run_url": f"{API}/actions/runs/{RUN_ID}",
            "url": f"{API}/actions/jobs/{job_id}",
            "head_sha": HEAD, "head_branch": "main", "run_attempt": 1,
            "name": job_name, "status": "completed", "conclusion": "success",
            "started_at": stamp(started), "completed_at": stamp(completed),
            "labels": ["ubuntu-24.04"], "runner_id": job_id + 10000,
            "runner_name": f"GitHub Actions {job_id}",
        }
        artifact = {
            "id": artifact_id, "name": f"{artifact_prefix}-{RUN_ID}",
            "url": f"{API}/actions/artifacts/{artifact_id}",
            "archive_download_url": f"{API}/actions/artifacts/{artifact_id}/zip",
            "created_at": stamp(created), "updated_at": stamp(created),
            "size_in_bytes": len(payload), "expired": False,
            "digest": "sha256:" + sha256(payload).hexdigest(),
            "workflow_run": {"id": RUN_ID, "repository_id": REPO_ID,
                             "head_repository_id": REPO_ID,
                             "head_branch": "main", "head_sha": HEAD},
        }
        packets.append({"run": deepcopy(run), "job": job,
                        "artifact": artifact, "archive_bytes": payload})
    return packets


class GitHubOriginEvidence(unittest.TestCase):
    def setUp(self):
        self.producer, self.readback = evidence_fixture()

    def verify(self, **changes):
        try:
            from race_ai.keirin_github_origin_evidence import verify_origin_evidence
        except ImportError:
            self.fail("The GitHub server-evidence verifier is not implemented")
        arguments = {
            "race_id": RID, "raw_cipher": CIPHER,
            "expected_cipher_sha256": DIGEST,
            "official_cutoff_at": "2026-11-18T01:10:00Z",
            "expected_producer_run_id": str(RUN_ID),
            "expected_producer_commit": HEAD,
            "producer": self.producer, "readback": self.readback,
        }
        arguments.update(changes)
        return verify_origin_evidence(**arguments)

    def replace_report(self, packet, member, contents):
        packet["archive_bytes"] = archive_bytes(member, contents)
        packet["artifact"]["digest"] = (
            "sha256:" + sha256(packet["archive_bytes"]).hexdigest())
        packet["artifact"]["size_in_bytes"] = len(packet["archive_bytes"])

    def test_two_digest_bound_reports_prove_only_cipher_origin(self):
        verified = self.verify()
        self.assertEqual(verified["state"], "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED")
        self.assertEqual(verified["race_id"], RID)
        self.assertEqual(verified["cipher_sha256"], DIGEST)
        self.assertEqual(verified["latest_server_evidence_at"],
                         "2026-11-18T01:04:00+00:00")
        self.assertEqual(verified["minimum_margin_seconds"], 65)
        self.assertFalse(verified["RSA_decryption_verified"])
        self.assertFalse(verified["official_result_verified"])
        self.assertNotIn("archive_bytes", verified)

    def test_committer_and_envelope_times_cannot_replace_server_times(self):
        self.producer["run"]["head_commit"] = {
            "timestamp": "2020-01-01T00:00:00Z"}
        with self.assertRaisesRegex(ValueError, "PRE_CUTOFF"):
            self.verify(official_cutoff_at="2026-11-18T01:05:04Z")
        self.assertEqual(self.verify(official_cutoff_at="2026-11-18T01:05:05Z")
                         ["state"], "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED")

    def test_metadata_update_does_not_invalidate_immutable_artifact_bytes(self):
        self.readback["artifact"]["updated_at"] = "2026-11-18T01:11:00Z"
        self.assertEqual(self.verify()["latest_server_evidence_at"],
                         "2026-11-18T01:04:00+00:00")

    def test_late_successful_upload_job_cannot_backdate_its_artifact(self):
        self.readback["job"]["completed_at"] = "2026-11-18T01:11:00Z"
        with self.assertRaisesRegex(ValueError, "PRE_CUTOFF"):
            self.verify()

    def test_later_result_only_rerun_keeps_original_successful_job_evidence(self):
        self.producer["run"]["run_attempt"] = 2
        self.readback["run"]["run_attempt"] = 2
        self.producer["run"].update(status="in_progress", conclusion=None)
        self.readback["run"].update(status="in_progress", conclusion=None)
        self.assertEqual(self.verify()["state"], "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED")

    def test_invalid_attempt_or_different_head_never_inherits_original_proof(self):
        original = deepcopy(self.producer)
        for change in ({"run_attempt": 0}, {"run_attempt": 2},
                       {"head_sha": "b" * 40}):
            with self.subTest(change=change):
                self.producer = deepcopy(original)
                self.producer["job"].update(change)
                with self.assertRaises(ValueError):
                    self.verify()

    def test_bytes_and_metadata_digest_both_bind_the_receipt(self):
        with self.assertRaisesRegex(ValueError, "CIPHER"):
            self.verify(raw_cipher=CIPHER + b"changed")
        self.readback["archive_bytes"] += b"tampered"
        with self.assertRaisesRegex(ValueError, "ARTIFACT"):
            self.verify()

    def test_expected_archive_producer_cannot_be_swapped(self):
        for changes in ({"expected_producer_run_id": "999999"},
                        {"expected_producer_commit": "b" * 40}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify(**changes)

    def test_fork_branch_event_workflow_and_failed_job_rejected(self):
        changes = (
            ("run", "head_repository", {"id": 1, "full_name": "other/repo"}),
            ("run", "head_branch", "unreviewed"),
            ("run", "event", "pull_request"),
            ("run", "path", ".github/workflows/untrusted.yml"),
            ("job", "conclusion", "failure"),
            ("job", "run_id", 999999),
            ("artifact", "name", "other-artifact"),
        )
        original = deepcopy(self.producer)
        for section, field, value in changes:
            with self.subTest(section=section, field=field):
                self.producer = deepcopy(original)
                self.producer[section][field] = value
                with self.assertRaises(ValueError):
                    self.verify()

    def test_readback_is_a_distinct_job_without_assuming_runner_metadata_exists(self):
        del self.producer["job"]["runner_id"]
        del self.readback["job"]["runner_id"]
        self.assertEqual(self.verify()["state"], "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED")
        self.readback["job"]["id"] = self.producer["job"]["id"]
        self.readback["job"]["url"] = self.producer["job"]["url"]
        with self.assertRaises(ValueError):
            self.verify()

    def test_same_known_runner_cannot_claim_independence(self):
        self.readback["job"]["runner_id"] = self.producer["job"]["runner_id"]
        with self.assertRaisesRegex(ValueError, "INDEPENDENT"):
            self.verify()

    def test_readback_wrong_race_sha_or_count_does_not_verify(self):
        original = deepcopy(self.readback)
        with ZipFile(BytesIO(original["archive_bytes"])) as archive:
            report = json.loads(archive.read("keirin-git-independent.json"))
        for kind in ("race", "sha", "count", "duplicate"):
            with self.subTest(kind=kind):
                self.readback = deepcopy(original)
                altered = deepcopy(report)
                if kind == "race":
                    altered["records"][0]["race_id"] = "202611182602"
                elif kind == "sha":
                    altered["records"][0]["cipher_sha256"] = "0" * 64
                elif kind == "count":
                    altered["independently_verified"] = 0
                else:
                    altered["records"].append(deepcopy(altered["records"][0]))
                    altered["independently_verified"] = 2
                    altered["new_archived"] = 2
                self.replace_report(self.readback, "keirin-git-independent.json",
                                    report_bytes(altered))
                with self.assertRaises(ValueError):
                    self.verify()

    def test_duplicate_json_fields_and_wrong_zip_members_rejected(self):
        self.replace_report(self.readback, "keirin-git-independent.json",
                            b'{"schema":"one","schema":"two"}')
        with self.assertRaises(ValueError):
            self.verify()
        self.producer, self.readback = evidence_fixture()
        self.replace_report(self.readback, "../keirin-git-independent.json", b"{}")
        with self.assertRaises(ValueError):
            self.verify()


def legacy_fixture():
    """Simulated API responses around a PUBLIC encrypted original, no RSA key."""
    root = Path(__file__).resolve().parents[1]
    cipher = (root / "docs/evidence/2026-11-18/"
              "keirin_utsunomiya1r_real_auto_AB_sealed_v1.json").read_bytes()
    digest = sha256(cipher).hexdigest()
    rid = "202611182401"
    run_id = 44234778255
    head = "0251b92e9947a6257fbd110c162665d5e4186ee8"
    branch = "research/keirin-six-phase-score-20261114"
    producer, readback = evidence_fixture()
    producer_report = {
        "schema": "RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1",
        "day_jst": "2026-11-18", "registered_races": 2,
        "A_generated": 1, "B_generated": 1, "same_job_sealed": 1,
        "records": [
            {"race_id": rid, "ciphertext_local_created": True,
             "cipher_file_sha256": digest},
            {"race_id": "202611182402", "ciphertext_local_created": False},
        ],
    }
    readback_report = {
        "schema": "RACE_AI_KEIRIN_NATIONWIDE_AB_CIPHER_SECOND_RUNNER_V1",
        "day_jst": "2026-11-18", "registered_races": 2,
        "independent_cipher_file_shas_ok": 1,
        "records": [
            {"race_id": rid, "cipher_file_sha256": digest,
             "state": "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK"},
            {"race_id": "202611182402", "state": "HOLD_NO_CIPHER_TO_VERIFY"},
        ],
    }
    safe = {
        "schema": "RACE_AI_KEIRIN_REAL_SOURCE_ONE_RUN_AB_AES_RECEIPT_V1",
        "race_id": rid, "cipher_sha256": digest,
        "same_job_AES_created": True, "actual_result_scored": False,
    }
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("producer-summary.json", report_bytes(producer_report))
        archive.writestr("one-run-safe-summary.json", report_bytes(safe))
        archive.writestr(f"sealed/{rid}.sealed.json", cipher)
    producer["archive_bytes"] = stream.getvalue()
    readback["archive_bytes"] = archive_bytes(
        "keirin-real-independent-readback.json", report_bytes(readback_report))
    for packet, job_id, artifact_id, job_name, artifact_name in (
        (producer, 134568159169, 14396164775, "real-source-to-owner-aes-one-run",
         "keirin-real-202611182401-source-AB-AES-20261118"),
        (readback, 134568309504, 14396547442, "real-source-cipher-independent-runner",
         "keirin-real-202611182401-independent-A-B-SHA"),
    ):
        packet["run"].update(id=run_id, url=f"{API}/actions/runs/{run_id}",
                             event="pull_request", head_branch=branch, head_sha=head)
        packet["job"].update(id=job_id, run_id=run_id,
                             url=f"{API}/actions/jobs/{job_id}",
                             run_url=f"{API}/actions/runs/{run_id}", name=job_name,
                             head_branch=branch, head_sha=head)
        packet["artifact"].update(
            id=artifact_id, name=artifact_name,
            url=f"{API}/actions/artifacts/{artifact_id}",
            archive_download_url=f"{API}/actions/artifacts/{artifact_id}/zip",
            size_in_bytes=len(packet["archive_bytes"]),
            digest="sha256:" + sha256(packet["archive_bytes"]).hexdigest())
        packet["artifact"]["workflow_run"].update(
            id=run_id, head_branch=branch, head_sha=head)
    return cipher, producer, readback


class KnownLegacyOriginEvidence(unittest.TestCase):
    def setUp(self):
        self.cipher, self.producer, self.readback = legacy_fixture()

    def verify(self, **changes):
        try:
            from race_ai.keirin_github_origin_evidence import verify_known_utsunomiya_origin
        except ImportError:
            self.fail("The known legacy origin verifier is not implemented")
        arguments = {"raw_cipher": self.cipher,
                     "official_cutoff_at": "2026-11-18T11:45:00Z",
                     "producer": self.producer, "readback": self.readback}
        arguments.update(changes)
        return verify_known_utsunomiya_origin(**arguments)

    def test_original_archive_format_and_embedded_cipher_are_verified(self):
        receipt = self.verify()
        self.assertEqual(receipt["race_id"], "202611182401")
        self.assertEqual(receipt["producer_run_id"], 44234778255)
        self.assertEqual(receipt["cipher_sha256"],
                         "dffc7303bfb722f75671751cee9a6356258263ec59b630f9dbdc6fc7953b5dfb")

    def test_legacy_permission_does_not_extend_to_another_run_or_cipher(self):
        with self.assertRaises(ValueError):
            self.verify(raw_cipher=self.cipher + b"different")
        self.producer["job"]["id"] += 1
        with self.assertRaises(ValueError):
            self.verify()

    def test_hash_in_receipt_cannot_substitute_for_different_embedded_cipher(self):
        source = BytesIO(self.producer["archive_bytes"])
        changed = BytesIO()
        with ZipFile(source) as old, ZipFile(changed, "w") as new:
            for member in old.namelist():
                contents = old.read(member)
                if member.startswith("sealed/"):
                    contents += b"changed"
                new.writestr(member, contents)
        self.producer["archive_bytes"] = changed.getvalue()
        self.producer["artifact"]["digest"] = (
            "sha256:" + sha256(changed.getvalue()).hexdigest())
        with self.assertRaisesRegex(ValueError, "EMBEDDED_CIPHER"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
