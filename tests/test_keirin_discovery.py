"""Synthetic roster discovery tests. No provider network in unit tests."""
from datetime import date
import unittest

from race_ai.keirin_discovery import (
    DiscoveryError, discover_from_html, index_url, get_single_day
)

DAY="2026-11-03"
URL=index_url(DAY)

def doc(n=7):
    links=[]
    for i in range(1,n+1):
        links.append(f'<a href="/odawara/racedetail/362026110103{i:04d}/">race</a>')
    links.append('<a href="/odawara/racedetail/3620261101020001/">yesterday</a>')
    links.append('<a href="/odawara/racedetail/3620261101040001/">tomorrow</a>')
    return ("<html>"+ "".join(links)+"</html>").encode()

class TestDiscover(unittest.TestCase):
    def test_legacy_rakuten_live_get_is_disabled(self):
        with self.assertRaisesRegex(
                DiscoveryError, "RAKUTEN_LIVE_FETCH_DISABLED_BY_OWNER"):
            get_single_day(DAY)

    def test_day_url_is_strict(self):
        self.assertEqual(URL,"https://keirin.kdreams.jp/kaisai/2026/11/03/")
        with self.assertRaises(DiscoveryError):
            index_url("2026-02-30")

    def test_only_requested_day_and_no_duplicate(self):
        body=doc()
        result=discover_from_html(body,event_day=DAY,source_url=URL)
        self.assertEqual(result["race_count"],7)
        self.assertEqual(result["venue_race_counts"],{"36":7})
        self.assertEqual(result["races"][0]["race_id"],"202611033601")
        self.assertEqual(result["races"][-1]["race_id"],"202611033607")
        self.assertFalse(result["complete_national_coverage_verified"])
        self.assertFalse(result["official_cutoffs_verified"])

    def test_partial_sequence_is_rejected_not_called_zero(self):
        b='<a href="/x/racedetail/3620261101030002/">2R</a>'.encode()
        with self.assertRaisesRegex(DiscoveryError,"PARTIAL_OR_NONCONTIGUOUS"):
            discover_from_html(b,event_day=DAY,source_url=URL)

    def test_other_day_only_is_not_negative_evidence(self):
        b='<a href="/x/racedetail/3620261101020001/">old</a>'.encode()
        with self.assertRaisesRegex(DiscoveryError,"NO_VERIFIED_RACE_ROWS"):
            discover_from_html(b,event_day=DAY,source_url=URL)

    def test_wrong_domain_not_accepted(self):
        b='<a href="https://other.example/racedetail/3620261101030001/">bad</a>'.encode()
        with self.assertRaisesRegex(DiscoveryError,"NO_VERIFIED_RACE_ROWS"):
            discover_from_html(b,event_day=DAY,source_url=URL)

    def test_duplicate_href_does_not_duplicate_race(self):
        body=doc()+doc()
        result=discover_from_html(body,event_day=DAY,source_url=URL)
        self.assertEqual(result["race_count"],7)

    def test_source_identity_is_strict(self):
        with self.assertRaises(DiscoveryError):
            discover_from_html(doc(),event_day=DAY,
              source_url="https://keirin.kdreams.jp/kaisai/2026/11/02/")

if __name__=="__main__":
    unittest.main()
