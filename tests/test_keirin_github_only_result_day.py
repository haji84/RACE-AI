"""No network, keys or false official outcomes in these tests."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from scripts import keirin_github_only_result_day as results

DAY="2026-11-19"
RID="202611192601"
CLOCK=lambda: datetime.fromisoformat("2026-11-19T08:00:00+00:00")


class GitHubOnlyResultStudy(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.root.chmod(0o700)
        self.raw=self.root/"raw"
        self.raw.mkdir(mode=0o700)

    def test_requires_existing_frozen_prediction_before_result_GET(self):
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",return_value={}),\
             patch.object(results.registration,"register_day") as get:
            report=results.run_day(
                day=DAY,repo=self.root,private_raw_dir=self.raw,clock=CLOCK)
        get.assert_not_called()
        self.assertEqual(report["result_candidates"],0)
        self.assertEqual(report["officially_scored"],0)

    def test_result_does_not_go_backward_beyond_previous_day(self):
        with patch.object(results.archive,"_remote") as repo:
            with self.assertRaisesRegex(
                    results.live.GitHubOnlyDayError, "CURRENT_OR_PREVIOUS"):
                results.run_day(
                    day="2026-11-17",repo=self.root,
                    private_raw_dir=self.raw,clock=CLOCK)
            repo.assert_not_called()

    def test_not_yet_post_cutoff_is_not_polled(self):
        registry={"races":[{"race_id":RID}]}
        manifest={"races":[{"race_id":RID}]}
        cutoff=datetime.fromisoformat("2026-11-19T08:01:00+00:00")
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",
                          return_value={RID:"a"*64}),\
             patch.object(results.registration,"register_day",
                          return_value=(registry,manifest,{})),\
             patch.object(results.archive,"_refresh",
                          return_value="f"*40),\
             patch.object(results,"_published_cutoff",return_value=cutoff),\
             patch.object(results.result_poll,"poll") as poll:
            out=results.run_day(
                day=DAY,repo=self.root,
                private_raw_dir=self.raw,clock=CLOCK)
        poll.assert_not_called()
        self.assertEqual(out["result_candidates"],0)
        self.assertEqual(out["officially_scored"],0)

    def test_observed_provisional_result_can_be_archived_not_scored(self):
        registry={"races":[{"race_id":RID}]}
        manifest={"races":[{"race_id":RID}]}
        cutoff=datetime.fromisoformat("2026-11-19T06:00:00+00:00")
        observed={
            "race_id":RID,
            "state":"SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL",
            "qualifies_for_formal_settlement":False,
            "winning_triple":[7,3,4],
            "payout_per_100yen":5590}
        with patch.object(results.archive,"_remote",return_value=self.root),\
             patch.object(results.live,"archived_day",
                          return_value={RID:"a"*64}),\
             patch.object(results.registration,"register_day",
                          return_value=(registry,manifest,{})),\
             patch.object(results.archive,"_refresh",
                          return_value="f"*40),\
             patch.object(results,"_published_cutoff",return_value=cutoff),\
             patch.object(results,"_prior_research",return_value=[]),\
             patch.object(results.result_poll,"poll",return_value=observed),\
             patch.object(results,"_archive_result",
                          return_value="RESEARCH_REVISION_GIT_CREATE_ONCE_READBACK"):
            out=results.run_day(
                day=DAY,repo=self.root,private_raw_dir=self.raw,clock=CLOCK)
        self.assertEqual(out["result_candidates"],1)
        self.assertEqual(out["research_matches_persisted"],1)
        self.assertEqual(out["officially_scored"],0)
        self.assertFalse(out["official_primary_result_authenticated"])

    def test_provisional_receipt_refuses_false_official_flags(self):
        with self.assertRaisesRegex(
                results.live.GitHubOnlyDayError, "CANNOT_BE_ARCHIVED_AS_MATCHED"):
            results._archive_result(self.root,{
                "race_id":RID,"state":"SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL",
                "qualifies_for_formal_settlement":True,
                "winning_triple":[7,3,4],
                "payout_per_100yen":5590})


if __name__=="__main__":
    unittest.main()
