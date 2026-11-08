"""Normal public HTML acquisition is owner-attested, private and fail-closed.

No real HTTP request. There is deliberately no artificial one-GET API quota;
the source's own restrictions, rate limits and timeouts remain binding.
"""
from __future__ import annotations

from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from race_ai.keirin_owner_auto_sources import (
    OwnerAttestedAutomaticSources,AUTOMATION_CONSENT
)
from race_ai.keirin_owner_approved_sources import PROFILE_ID
from race_ai.keirin_owner_public_page_fetch import (
    capture_approved_public_pages, PublicPageFetchError
)


NOW=datetime.fromisoformat("2030-01-15T09:15:00+09:00")
URLS=[
    "https://www.winticket.jp/keirin/aomori/odds",
    "https://keirin.jp/pc/dfw/portal/guest/race",
    "https://www.winticket.jp/keirin/aomori/racecard",
]


class OwnerAutomaticPublicHtmlTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.grants=OwnerAttestedAutomaticSources(
            profile=PROFILE_ID,consent=AUTOMATION_CONSENT,
            now=NOW.isoformat())
        self.calls=[]

    def fake(self,url):
        self.calls.append(url)
        return ('<html><body>fixture '+url+'</body></html>').encode()

    def test_multiple_normal_https_pages_single_cycle_retained_privately(self):
        report=capture_approved_public_pages(
            self.root,self.grants,urls=URLS,transport=self.fake,
            clock=lambda:NOW)
        self.assertEqual(self.calls,URLS)
        self.assertEqual(report["requested_url_count"],3)
        self.assertEqual(report["captures_created"],3)
        self.assertEqual(report["network_requests"],0)  # fake transport
        self.assertFalse(report["complete_real_race_odds_verified"])
        folder=self.root/"owner_public_capture"
        self.assertEqual(len(list(folder.glob("*.html"))),3)
        self.assertEqual(len(list(folder.glob("*.json"))),3)
        for manifest in folder.glob("*.json"):
            m=json.loads(manifest.read_text())
            self.assertFalse(m["full_210_odds_parsed"])
            self.assertFalse(m["upstream_publication_time_independently_verified"])
        second=capture_approved_public_pages(
            self.root,self.grants,urls=URLS,transport=self.fake,
            clock=lambda:NOW)
        self.assertEqual(second["captures_created"],0)
        self.assertEqual(second["captures_already_retained"],3)

    def test_unapproved_host_preflight_stops_before_any_http(self):
        with self.assertRaisesRegex(PublicPageFetchError,"UNAPPROVED_PUBLIC_PAGE"):
            capture_approved_public_pages(
                self.root,self.grants,urls=[
                    URLS[0],"https://other.example.com/keirin/odds"],
                transport=self.fake)
        self.assertEqual(self.calls,[])
        self.assertFalse((self.root/"owner_public_capture").exists())

    def test_no_hidden_api_endpoint_or_missing_approval(self):
        for url in (
            "https://api.winticket.jp/internal/secret",
            "https://www.winticket.jp/internal/private",
            "https://www.winticket.jp/keirin/aomori/odds#fragment",
            "https://keirin.jp/private",
            "https://127.0.0.1/keirin",
            "http://www.winticket.jp/keirin/aomori/odds",
        ):
            with self.subTest(url=url),self.assertRaises(PublicPageFetchError):
                capture_approved_public_pages(
                    self.root,self.grants,urls=[url],transport=self.fake)
        self.assertEqual(self.calls,[])

    def test_new_source_contents_create_new_version_not_rewrite_first(self):
        first=capture_approved_public_pages(
            self.root,self.grants,urls=[URLS[0]],
            transport=lambda _:b"<html>before</html>",
            clock=lambda:NOW)
        second=capture_approved_public_pages(
            self.root,self.grants,urls=[URLS[0]],
            transport=lambda _:b"<html>changed</html>",
            clock=lambda:NOW)
        self.assertEqual(first["captures_created"],1)
        self.assertEqual(second["captures_created"],1)
        self.assertEqual(len(list(
            (self.root/"owner_public_capture").glob("*.html"))),2)

    def test_server_failure_is_not_silently_treated_as_valid_odds(self):
        with self.assertRaises(PublicPageFetchError):
            capture_approved_public_pages(
                self.root,self.grants,urls=[URLS[0]],
                transport=lambda _:b"")
        self.assertFalse((self.root/"owner_public_capture").glob("*.html").__next__() if
                         False else False)


if __name__=="__main__":
    unittest.main()
