"""Future race live SSR probe tests use fictional HTML only; no network."""
from __future__ import annotations

from datetime import datetime
import unittest

from scripts.keirin_future_public_ssr_probe import public_future_race_probe
from race_ai.keirin_winticket_embedded_racecard import EmbeddedRacecardError
from test_keirin_winticket_embedded_racecard import fixture as card_page
from test_keirin_winticket_embedded_odds import page as odds_page

RACE="202611091203"
CARD="https://www.winticket.jp/keirin/aomori/racecard/2026110812/2/3"
ODDS="https://www.winticket.jp/keirin/aomori/odds/2026110812/2/3"
NOW=datetime.fromisoformat("2026-11-09T08:55:16+09:00")


class WinticketFutureSsrTest(unittest.TestCase):
    def test_exact_race_both_actual_shapes_and_210_prices_no_fake_forecast(self):
        called=[]
        def fetch(url):
            called.append(url)
            return card_page() if url==CARD else odds_page()
        receipt=public_future_race_probe(
            race_id=RACE,racecard_url=CARD,odds_url=ODDS,
            fetch=fetch,clock=lambda:NOW)
        self.assertEqual(called,[CARD,ODDS])
        self.assertEqual(receipt["status"],
                         "LIVE_TRIFECTA_PRICE_UNIVERSE_VERIFIED")
        self.assertTrue(receipt["actual_210_or_504_verified"])
        self.assertEqual(receipt["actual_full_trifecta_rows"],210)
        self.assertEqual(receipt["preflight_checked_items"],347)
        self.assertGreater(receipt["preflight_unavailable_items"],200)
        self.assertFalse(receipt["full_official_model_preflight"])
        self.assertFalse(receipt["two_version_prediction_saved"])
        self.assertNotIn("fictional-rider",str(receipt))
        self.assertNotIn("oddsStr",str(receipt))

    def test_post_cutoff_never_fetches_odds_or_stages_forecast(self):
        seen=[]
        def fetch(url):
            seen.append(url)
            return card_page() if url==CARD else odds_page()
        after=datetime.fromisoformat("2026-11-09T09:35:00+09:00")
        report=public_future_race_probe(
            race_id=RACE,racecard_url=CARD,odds_url=ODDS,
            fetch=fetch,clock=lambda:after)
        self.assertEqual(seen,[CARD])
        self.assertEqual(report["status"],
                         "RACECARD_PENDING_OR_CUTOFF_PASSED")
        self.assertFalse(report["actual_210_or_504_verified"])
        self.assertFalse(report["two_version_prediction_saved"])

    def test_venue_day_mismatch_refused_before_any_network_call(self):
        seen=[]
        with self.assertRaises(EmbeddedRacecardError):
            public_future_race_probe(
                race_id=RACE,
                racecard_url=CARD,
                odds_url="https://www.winticket.jp/keirin/aomori/odds/2026110812/3/3",
                fetch=lambda u:seen.append(u) or card_page(),
                clock=lambda:NOW)
        self.assertEqual(seen,[])


if __name__=="__main__":
    unittest.main()
