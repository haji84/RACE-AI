"""Offline source-link fixtures only: no provider GETs or real forecasts."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from race_ai import keirin_dynamic_nationwide_registry as dynamic
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_register_public_day as day

DAY = "2026-11-19"
CALENDAR = "https://keirin.kdreams.jp/kaisai/2026/11/19/"
C24 = "https://keirin.kdreams.jp/utsunomiya/racecard/24202611190100/"
C26 = "https://keirin.kdreams.jp/seibuen/racecard/26202611180200/"


class PublicDayRegistrationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name) / "raw"
        self.dir.mkdir(mode=0o700)
        self.calls = []
        self.calendar = (
            '<html><a href="/utsunomiya/racecard/24202611190100/">a</a>'
            '<a href="/seibuen/racecard/26202611180200/">b</a>'
            '</html>').encode()
        self.venue24 = (
            '<html><a href="/utsunomiya/racedetail/'
            '2420261119010001/">1R</a></html>').encode()
        self.venue26 = (
            '<html><a href="/seibuen/racedetail/'
            '2620261118020001/">1R</a>'
            '<a href="/seibuen/racedetail/'
            '2620261118020002/">2R</a></html>').encode()
        self.pages = {
            CALENDAR: self.calendar,
            C24: self.venue24,
            C26: self.venue26,
        }

    def fetch(self, url):
        self.calls.append(url)
        return self.pages[url]

    def register(self, **extra):
        return day.register_day(
            day_jst=DAY, private_raw_dir=self.dir,
            fetch=self.fetch,
            clock=lambda: datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc),
            **extra)

    def test_future_day_reads_real_linked_race_numbers_not_fixed_79(self):
        registry, manifest, safe = self.register()
        dynamic.checked_day(registry)
        self.assertEqual(
            [x["race_id"] for x in registry["races"]],
            ["202611192401", "202611192601", "202611192602"])
        self.assertEqual(safe["observed_races_registered"], 3)
        self.assertEqual(safe["linked_calendar_venues"], 2)
        self.assertEqual(safe["meeting_pages_attempted"], 2)
        self.assertEqual(registry["source_venues"][1]["grade"], "UNKNOWN")
        self.assertTrue(registry["national_universe_unverified_hold"])
        self.assertFalse(registry["nationwide_coverage_independently_verified"])
        self.assertFalse(safe["official_cutoff_verified"])
        self.assertEqual(safe["actual_forecasts_generated"], 0)
        self.assertEqual(manifest["schema"], capture.SCHEMA)
        self.assertEqual(manifest["races"][2]["cutoff_hint"], None)
        # Day 2 is calculated from the actual meeting-start date, not
        # fabricated from the race date. No direct detail URL was guessed.
        self.assertEqual(manifest["races"][1]["kdreams_url"],
                         "https://keirin.kdreams.jp/seibuen/racedetail/"
                         "2620261118020001/")
        self.assertEqual(self.calls, [CALENDAR, C24, C26])
        self.assertEqual(len(list(self.dir.glob("*.html"))), 3)

    def test_partial_meeting_limit_does_not_claim_complete_day(self):
        registry, manifest, safe = self.register(max_meetings=1)
        self.assertEqual(safe["uninspected_meeting_pages"], 1)
        self.assertEqual(registry["captured_race_count"], 1)
        self.assertEqual([x["race_id"] for x in manifest["races"]],
                         ["202611192401"])
        self.assertFalse(safe["national_universe_verified"])
        self.assertEqual(self.calls, [CALENDAR, C24])

    def test_denial_after_first_venue_stops_further_get_without_faking(self):
        old = self.fetch
        def block(url):
            if url == C26:
                self.calls.append(url)
                raise capture.SourceCaptureError(
                    "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
            return old(url)
        self.fetch = block
        registry, _, safe = self.register()
        self.assertEqual(registry["captured_race_count"], 1)
        self.assertTrue(safe["stopped_after_provider_error"])
        self.assertEqual(safe["page_errors"], 1)
        self.assertEqual(self.calls, [CALENDAR, C24, C26])
        self.assertFalse(safe["national_universe_verified"])

    def test_no_real_calendar_hrefs_holds_instead_of_inventing_urls(self):
        self.pages[CALENDAR] = b"<html><div>No day links</div></html>"
        with self.assertRaisesRegex(
                day.DayPublicRegistrationError,
                "DAY_NO_REAL_CALENDAR_MEETING_LINKS"):
            self.register()

    def test_wrong_day_and_invalid_budget_rejected_before_provider_get(self):
        with self.assertRaisesRegex(day.DayPublicRegistrationError,
                                    "DAY_JST_INVALID"):
            day.register_day(day_jst="2026-11-32",
                             private_raw_dir=self.dir, fetch=self.fetch)
        with self.assertRaisesRegex(day.DayPublicRegistrationError,
                                    "MEETING_GET_BUDGET_INVALID"):
            self.register(max_meetings=0)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
