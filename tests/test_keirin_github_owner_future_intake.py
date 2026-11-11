"""Offline GitHub schedule regression: no real data, no provider GET."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import json
import unittest

from scripts.keirin_github_owner_future_intake import (
    owner_future_public_intake, SCHEMA
)
from race_ai.keirin_owner_public_page_fetch import PublicPageFetchError
from tests.test_keirin_next_published_race_probe import (
    INDEX,CARD,ODDS,NOW,NextSourceProbeTests
)


class GitHubOwnerFutureIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        # The owner-persistent runner is explicitly acknowledged. The
        # synthetic fixture does not prove actual live runner connectivity.
        self.persist=patch.dict(os.environ,{
            "RACE_AI_PERSISTENT_PRIVATE_VOLUME":"ACKNOWLEDGED",
            "GITHUB_WORKSPACE":"",
        })
        self.persist.start()
        self.addCleanup(self.persist.stop)
        fixtures=NextSourceProbeTests()
        fixtures.setUp()
        self.files={INDEX:fixtures.index,CARD:fixtures.card,ODDS:fixtures.odds}
        self.calls=[]

    def get(self,url):
        self.calls.append(url)
        if url not in self.files:
            raise AssertionError("UNDECLARED_PROVIDER_SOURCE_REQUEST")
        return self.files[url]

    def test_future_source_card_and_210_prices_privately_staged_then_reused(self):
        report=owner_future_public_intake(
            self.root,fetch=self.get,clock=lambda:NOW,
            lookahead_minutes=90,max_races=1)
        self.assertEqual(self.calls,[INDEX,CARD,ODDS])
        self.assertEqual(report["schema"],SCHEMA)
        self.assertEqual(report["selected_in_this_cycle"],1)
        self.assertEqual(report["private_partial_racecards_staged"],1)
        self.assertEqual(report["private_full_odds_races_staged"],1)
        self.assertEqual(report["private_pending_or_incomplete"],0)
        self.assertFalse(report["pr71_four_models_run_here"])
        self.assertFalse(report["source_347_or_437_formal_gate_claimed"])
        self.assertFalse(report["provider_machine_rights_independently_verified"])
        self.assertNotIn("fictional-rider",str(report))
        self.assertNotIn("racePoint",str(report))
        self.assertEqual(
            len(list((self.root/"winticket_racecard_partial").glob("*.json"))),1)
        self.assertEqual(len(list((self.root/"odds").glob("*.json"))),1)
        odds=json.loads(next((self.root/"odds").glob("*.json")).read_text())
        self.assertEqual(len(odds["prices"]),210)
        for path in (self.root/"odds").glob("*.json"):
            self.assertEqual(path.stat().st_mode & 0o077,0)

    def test_repeated_source_keeps_immutable_original(self):
        first=owner_future_public_intake(
            self.root,fetch=self.get,clock=lambda:NOW,max_races=1)
        one=next((self.root/"winticket_racecard_partial").glob("*.json"))
        original=one.read_bytes()
        self.calls.clear()
        repeated=owner_future_public_intake(
            self.root,fetch=self.get,clock=lambda:NOW,max_races=1)
        self.assertEqual(first["private_partial_racecards_staged"],1)
        self.assertEqual(repeated["private_partial_racecards_staged"],0)
        self.assertEqual(one.read_bytes(),original)
        self.assertEqual(len(list((self.root/"odds").glob("*.json"))),1)

    def test_pending_odds_never_discards_early_private_racecard(self):
        def partially_published(url):
            self.calls.append(url)
            if url==ODDS:
                raise PublicPageFetchError("PUBLIC_PAGE_NOT_PUBLISHED_OR_GONE")
            return self.files[url]
        r=owner_future_public_intake(
            self.root,fetch=partially_published,clock=lambda:NOW,max_races=1)
        self.assertEqual(self.calls,[INDEX,CARD,ODDS])
        self.assertEqual(r["private_partial_racecards_staged"],1)
        self.assertEqual(r["private_full_odds_races_staged"],0)
        self.assertEqual(r["private_pending_or_incomplete"],1)
        self.assertEqual(r["source_job_state"],"SOURCE_ONLY_PARTIAL_OR_HOLD")
        self.assertFalse(r["pr71_four_models_run_here"])

    def test_no_eligible_cutoff_has_only_one_public_index_get(self):
        late=datetime.fromisoformat("2026-11-10T09:23:00+09:00")
        result=owner_future_public_intake(
            self.root,fetch=self.get,clock=lambda:late,max_races=1)
        self.assertEqual(self.calls,[INDEX])
        self.assertEqual(result["selected_in_this_cycle"],0)
        self.assertEqual(result["private_full_odds_races_staged"],0)

    def test_source_budget_and_nonowner_inbox_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"INVALID_PER_RUN_SOURCE_WORK_BUDGET"):
            owner_future_public_intake(
                self.root,fetch=self.get,clock=lambda:NOW,max_races=0)
        with self.assertRaisesRegex(ValueError,"EXISTING_OWNER_PRIVATE_INBOX_REQUIRED"):
            owner_future_public_intake(
                self.root/"not-a-real-private-folder",
                fetch=self.get,clock=lambda:NOW,max_races=1)
        self.assertEqual(self.calls,[])


if __name__=="__main__":
    unittest.main()
