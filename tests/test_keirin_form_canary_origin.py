"""Invented GitHub metadata only; not a real canary acceptance receipt."""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
import unittest

from race_ai import keirin_github_origin_evidence as origin
from tests.test_keirin_github_origin_evidence import (
    API, CIPHER, DIGEST, HEAD, RUN_ID, archive_bytes, evidence_fixture, report_bytes)

RID = "202611208105"
FORM = b"synthetic conditioned ciphertext only"
FORM_SHA = sha256(FORM).hexdigest()
PARENT = "c"*64
COHORT = "d"*64


def fixture():
    producer, reader = evidence_fixture()
    for packet, role, job_name, artifact_prefix, member in (
            (producer, "producer", "form-canary-capture", "keirin-form-canary-receipt", "summary.json"),
            (reader, "readback", "form-canary-independent-readback", "keirin-form-canary-readback", "keirin-git-independent.json")):
        for section in ("run", "job", "artifact"):
            for key, value in packet[section].items():
                if type(value) is str:
                    packet[section][key] = value.replace("2026-11-18", "2026-11-20")
        packet["run"]["event"] = "push"
        packet["job"]["name"] = job_name
        packet["artifact"]["name"] = artifact_prefix + "-" + str(RUN_ID)
        row = {"race_id":RID, "cipher_sha256":DIGEST,
               "conditioned_cipher_sha256":FORM_SHA,
               "baseline_prediction_sha256":PARENT, "cohort_sha256":COHORT}
        if role == "producer":
            row["conditioned_state"] = "GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED"
            report = {"schema":"RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1",
                "day_jst":"2026-11-20", "new_A_B_sealed":1, "new_A_B_git_archived":1,
                "new_conditioned_A_B_git_archived":1, "new_encrypted_originals":[row]}
        else:
            row.update(state="SECOND_RUNNER_GITHUB_SHA_CONFIRMED",
                       conditioned_state="SECOND_RUNNER_CONDITIONED_GITHUB_SHA_CONFIRMED")
            report = {"schema":"RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1",
                "day_jst":"2026-11-20", "new_archived":1, "independently_verified":1,
                "independently_verified_conditioned":1, "paired_cipher_originals_verified":1,
                "records":[row]}
        replace_report(packet, member, report)
    return producer, reader


def replace_report(packet, member, report):
    packet["archive_bytes"] = archive_bytes(member, report_bytes(report))
    packet["artifact"]["digest"] = "sha256:" + sha256(packet["archive_bytes"]).hexdigest()
    packet["artifact"]["size_in_bytes"] = len(packet["archive_bytes"])


class FormCanaryOrigin(unittest.TestCase):
    def verify(self, **changes):
        self.assertTrue(callable(getattr(origin, "verify_conditioned_origin_evidence", None)))
        producer, reader = fixture()
        args = dict(race_id=RID, raw_baseline_cipher=CIPHER,
            expected_baseline_cipher_sha256=DIGEST, raw_conditioned_cipher=FORM,
            expected_conditioned_cipher_sha256=FORM_SHA,
            expected_baseline_prediction_sha256=PARENT, cohort_sha256=COHORT,
            official_cutoff_at="2026-11-20T17:07:00+09:00",
            expected_producer_run_id=str(RUN_ID), expected_producer_commit=HEAD,
            producer=producer, readback=reader)
        args.update(changes)
        return origin.verify_conditioned_origin_evidence(**args)

    def test_both_original_shas_bound_to_same_main_server_witness(self):
        proof = self.verify()
        self.assertEqual(proof["state"], "GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED")
        self.assertEqual(proof["cipher_sha256"], FORM_SHA)
        self.assertEqual(proof["baseline_cipher_sha256"], DIGEST)
        self.assertEqual(proof["cohort_sha256"], COHORT)
        self.assertFalse(proof["RSA_decryption_verified"])
        self.assertFalse(proof["official_result_verified"])

    def test_parent_cohort_raw_bytes_and_wrong_race_are_rejected(self):
        self.assertTrue(callable(getattr(origin, "verify_conditioned_origin_evidence", None)))
        for change in ({"raw_conditioned_cipher":FORM+b"different"},
                       {"cohort_sha256":"e"*64},
                       {"expected_baseline_prediction_sha256":"f"*64},
                       {"race_id":"202611208106"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(**change)

    def test_late_or_untrusted_jobs_cannot_prove_the_conditioned_original(self):
        self.assertTrue(callable(getattr(origin, "verify_conditioned_origin_evidence", None)))
        for change in ("late", "pr", "fork", "condition_missing"):
            producer, reader = fixture()
            if change == "late":
                reader["job"]["completed_at"] = "2026-11-20T08:05:56Z"
            elif change == "pr":
                producer["run"]["event"] = "pull_request"
            elif change == "fork":
                producer["run"]["head_repository"]["full_name"] = "other/RACE-AI"
            else:
                from io import BytesIO
                from zipfile import ZipFile
                with ZipFile(BytesIO(reader["archive_bytes"])) as z:
                    doc = json.loads(z.read("keirin-git-independent.json"))
                doc["records"][0]["conditioned_state"] = "HOLD_CONDITIONED_SECOND_RUNNER_READBACK"
                doc["independently_verified_conditioned"] = 0
                doc["paired_cipher_originals_verified"] = 0
                replace_report(reader, "keirin-git-independent.json", doc)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(producer=producer, readback=reader)

    def test_canary_window_allows_next_day_settlement_without_retrospective_capture(self):
        self.assertTrue(callable(getattr(origin, "form_canary_window", None)))
        for at, capture, settle in (
            ("2026-11-19T23:59:59+09:00", False, False),
            ("2026-11-20T17:05:55+09:00", True, False),
            ("2026-11-20T17:05:56+09:00", False, False),
            ("2026-11-20T17:07:00+09:00", False, True),
            ("2026-11-20T23:59:59+09:00", False, True),
            ("2026-11-21T00:00:00+09:00", False, True),
            ("2026-11-21T23:59:59+09:00", False, True),
            ("2026-11-21T14:59:59+00:00", False, True),
            ("2026-11-22T00:00:00+09:00", False, False)):
            with self.subTest(at=at):
                got = origin.form_canary_window(datetime.fromisoformat(at))
                self.assertEqual((got["capture"], got["settle"]), (capture, settle))


if __name__ == "__main__":
    unittest.main()
