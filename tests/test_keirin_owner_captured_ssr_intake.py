"""Private WINTICKET SSR source-bridge tests, no live HTTP nor real rider data."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest

from race_ai.keirin_owner_auto_sources import (
    OwnerAttestedAutomaticSources,AUTOMATION_CONSENT
)
from race_ai.keirin_owner_approved_sources import PROFILE_ID
from race_ai.keirin_owner_public_page_fetch import (
    capture_approved_public_pages
)
from race_ai.keirin_owner_captured_ssr_intake import (
    stage_private_captured_winticket
)
from test_keirin_winticket_embedded_racecard import (
    fixture as card_fixture
)
from test_keirin_winticket_embedded_odds import (
    page as odds_fixture
)

CARD="https://www.winticket.jp/keirin/aomori/racecard/2026110812/2/3"
ODDS="https://www.winticket.jp/keirin/aomori/odds/2026110812/2/3"
NOW=datetime.fromisoformat("2026-11-09T08:55:16+09:00")


class CapturedSSRBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.grants=OwnerAttestedAutomaticSources(
            profile=PROFILE_ID,consent=AUTOMATION_CONSENT,
            now=NOW.isoformat())
        self.env=patch.dict(os.environ,{
            "GITHUB_ACTIONS":"false",
            "GITHUB_WORKSPACE":"",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def capture(self,urls=(CARD,ODDS),now=NOW):
        return capture_approved_public_pages(
            self.root,self.grants,urls=list(urls),
            transport=lambda u:card_fixture() if u==CARD else odds_fixture(),
            clock=lambda:now)

    def test_two_source_capture_to_complete_210_private_odds_and_partial_audit(self):
        self.capture()
        first=stage_private_captured_winticket(self.root)
        self.assertEqual(first["captured_html_seen"],2)
        self.assertEqual(first["source_races_seen"],1)
        self.assertEqual(first["full_odds_races_staged"],1)
        self.assertEqual(first["private_partial_racecards_staged"],1)
        self.assertEqual(first["incomplete_races"],0)
        self.assertEqual(first["network_requests"],0)
        self.assertEqual(first["forecasts_created"],0)
        odds=list((self.root/"odds").glob("*.json"))
        self.assertEqual(len(odds),1)
        self.assertEqual(len(json.loads(odds[0].read_text())["prices"]),210)
        part=list((self.root/"winticket_racecard_partial").glob("*.json"))
        self.assertEqual(len(part),1)
        audit=json.loads(part[0].read_text())
        self.assertFalse(audit["full_347_or_437_verified"])
        self.assertEqual(audit["registry_checked_count"],347)
        original=odds[0].read_bytes()
        second=stage_private_captured_winticket(self.root)
        self.assertEqual(second["full_odds_races_staged"],0)
        self.assertEqual(second["private_partial_racecards_staged"],0)
        self.assertEqual(odds[0].read_bytes(),original)

    def test_missing_racecard_never_stages_odds_or_forecasts(self):
        self.capture(urls=(ODDS,))
        res=stage_private_captured_winticket(self.root)
        self.assertEqual(res["incomplete_races"],1)
        self.assertEqual(res["full_odds_races_staged"],0)
        self.assertEqual(res["forecasts_created"],0)
        self.assertFalse((self.root/"odds").exists())

    def test_corrupted_html_sha_not_admitted(self):
        self.capture()
        bad=next((self.root/"owner_public_capture").glob("*.html"))
        bad.write_bytes(b"tampered")
        res=stage_private_captured_winticket(self.root)
        self.assertEqual(res["captured_unadmitted"],1)
        self.assertEqual(res["full_odds_races_staged"],0)
        self.assertEqual(res["forecasts_created"],0)

    def test_historical_capture_cannot_be_backdated_into_forecast(self):
        self.capture(now=datetime.fromisoformat("2026-11-09T09:35:00+09:00"))
        res=stage_private_captured_winticket(self.root)
        self.assertEqual(res["full_odds_races_staged"],0)
        self.assertGreaterEqual(res["incomplete_races"],1)
        self.assertEqual(res["forecasts_created"],0)


if __name__=="__main__":
    unittest.main()
