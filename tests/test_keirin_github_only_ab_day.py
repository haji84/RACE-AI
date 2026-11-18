"""Source-free pipeline tests: do not mistake mocks for live coverage."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest

from scripts import keirin_github_only_ab_day as live
from scripts import keirin_github_only_ab_readback as readback


RID1 = "202611192601"
RID2 = "202611192602"
DAY = "2026-11-19"
CLOCK = lambda: datetime.fromisoformat("2026-11-18T16:00:00+00:00")


def example_manifest():
    return {"day_jst": DAY, "races": [
        {"race_id": RID1}, {"race_id": RID2}]}


class GithubOnlyABDay(unittest.TestCase):
    def setUp(self):
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.root.chmod(0o700)
        self.pub = self.root / "owner-public.pem"
        self.pub.write_bytes(b"public-test-placeholder")

    def test_selection_skips_already_frozen_without_changing_population(self):
        prior = {RID1: "a" * 64}
        eligible, remaining = live.select_unfrozen(example_manifest(), prior)
        self.assertEqual(remaining, 1)
        self.assertEqual([x["race_id"] for x in eligible["races"]], [RID2])
        self.assertEqual(len(example_manifest()["races"]), 2)

    def test_budget_limits_gets_but_no_national_coverage_claim(self):
        ids = [f"2026111926{r:02d}" for r in range(1, 11)]
        manifest = {"day_jst":DAY, "races":[{"race_id":x} for x in ids]}
        eligible, count = live.select_unfrozen(manifest, {}, max_races=8)
        self.assertEqual((len(eligible["races"]), count), (8,10))
        self.assertEqual(manifest["races"][9]["race_id"], ids[9])

    def test_yesterday_and_tomorrow_refuse_before_any_http_or_git(self):
        with patch.object(live, "archived_day") as history, \
             patch.object(live.registration, "register_day") as source:
            for wrong in ("2026-11-18", "2026-11-20"):
                with self.assertRaisesRegex(
                        live.GitHubOnlyDayError, "NO_RETROSPECTIVE"):
                    live.run_day(
                        day=wrong, workspace=self.root,
                        private_dir_path=self.root,
                        owner_public_pem=self.pub, clock=CLOCK)
            history.assert_not_called()
            source.assert_not_called()

    def test_mocked_one_race_archived_not_misreported_as_full_day(self):
        source = example_manifest()
        raw_cipher = b"synthetic-private-cipher-placeholder\n"
        sha = sha256(raw_cipher).hexdigest()
        registry = {"day_jst": DAY}

        def fake_generate(**kwargs):
            dest = kwargs["private_cipher_dir"] / (RID2 + ".sealed.json")
            dest.write_bytes(raw_cipher)
            return {"registered_races":2,"same_job_sealed":1,
                    "statuses":{"NO_FORECAST_INPUT_MISSING":1,
                                "A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH":1},
                    "records":[{"race_id":RID1,"ciphertext_local_created":False},
                               {"race_id":RID2,"ciphertext_local_created":True,
                                "cipher_file_sha256":sha}]}
        with patch.object(live, "archived_day", return_value={RID1:"a"*64}), \
             patch.object(live.registration, "register_day",
                          return_value=(registry,source,{})), \
             patch.object(live.collector, "capture_cycle",
                          return_value={"GET_pair_attempts":1,
                                        "normalized_private_cards":1,
                                        "states":{"PRIVATE_CARD_NORMALIZED":1}}) as get, \
             patch.object(live.generator, "registered_race_ids",
                          return_value=[RID1,RID2]), \
             patch.object(live.generator, "run_cycle",
                          side_effect=fake_generate), \
             patch.object(live.archive, "append_once",
                          return_value={"state":"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED"}) as write, \
             patch.dict(os.environ,
                        {"GITHUB_RUN_ID":"12345","GITHUB_SHA":"a"*40}):
            result = live.run_day(
                day=DAY, workspace=self.root,
                private_dir_path=self.root,
                owner_public_pem=self.pub, clock=CLOCK)
        self.assertEqual(get.call_args.kwargs["day_manifest"]["races"],
                         [{"race_id":RID2}])
        self.assertEqual(result["new_A_B_git_archived"],1)
        self.assertFalse(result["national_universe_verified"])
        self.assertEqual(result["official_results_scored"],0)
        self.assertEqual(result["already_frozen_prior"],1)
        self.assertEqual(write.call_args.kwargs["expected_cipher_sha256"],sha)
        self.assertNotIn("ranked_tickets", str(result))

    def test_readback_rejects_missing_verified_git_original(self):
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":1,
                  "new_encrypted_originals":[
                      {"race_id":RID2,"cipher_sha256":"a"*64}]}
        with patch.object(readback.archive,"read_original",
                          return_value={"state":"HOLD"}):
            with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                        "READBACK_NOT_VERIFIED"):
                readback.verify(report=report,repo=self.root)

    def test_readback_reports_nothing_official(self):
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":1,
                  "new_encrypted_originals":[
                      {"race_id":RID2,"cipher_sha256":"a"*64}]}
        with patch.object(readback.archive,"read_original",
                          return_value={
                              "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}):
            result = readback.verify(report=report,repo=self.root)
        self.assertEqual(result["independently_verified"], 1)
        self.assertFalse(result["RSA_private_decryption_verified"])
        self.assertFalse(result["organizer_result_verified"])

    def test_readback_rejects_duplicate_races(self):
        row = {"race_id":RID2,"cipher_sha256":"a"*64}
        report = {"schema":live.SCHEMA,"day_jst":DAY,
                  "new_A_B_git_archived":2,
                  "new_encrypted_originals":[row,row]}
        with patch.object(readback.archive,"read_original",
                          return_value={
                              "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"}):
            with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                        "DUPLICATE"):
                readback.verify(report=report,repo=self.root)


if __name__ == "__main__":
    unittest.main()
