"""Linked public URL discovery is tested with synthetic page anchors ONLY."""
from pathlib import Path
import unittest

from scripts import keirin_discover_public_race_links as discover
from scripts import keirin_capture_public_two_sources as capture

CAL="https://keirin.kdreams.jp/kaisai/2026/11/18/"
CARD="https://keirin.kdreams.jp/utsunomiya/racecard/24202611170200/"
RIDS=["202611182401","202611182402","202611182403"]


def fixture():
    day=b"""<html><body><a href="/utsunomiya/racecard/24202611170200/">
    Utsunomiya Nov18 day two</a></body></html>"""
    meeting=b"""<html><body>
    <a href="/utsunomiya/racedetail/2420261117020001/">1R</a>
    <a href="/utsunomiya/racedetail/2420261117020002/">2R</a>
    <a href="/utsunomiya/racedetail/2420261117020003/">3R</a>
    </body></html>"""
    return {CAL:day,CARD:meeting}


class KdreamsDayLinkResearch(unittest.TestCase):
    def test_meeting_day_two_extracted_from_real_link_shape_no_fabrication(self):
        p=fixture()
        out=discover.discover(day_jst="2026-11-18",
            registered_ids=RIDS,fetch=lambda url:p[url])
        self.assertEqual(out["candidate_race_count"],3)
        self.assertEqual(out["unlinked_registered_race_count"],0)
        self.assertTrue(out["all_races_linked"])
        self.assertEqual([x["race_id"] for x in out["manifest"]["races"]],RIDS)
        self.assertEqual(out["manifest"]["races"][0]["kdreams_url"],
          "https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020001/")
        self.assertIsNone(out["manifest"]["races"][0]["cutoff_hint"])
        self.assertTrue(out["netkeirin_GET_candidates_not_yet_verified"])

    def test_cannot_invent_other_77_links_from_one_meeting(self):
        p=fixture()
        scope=RIDS+["202611183801","202611187401"]
        out=discover.discover(day_jst="2026-11-18",
                              registered_ids=scope,fetch=lambda url:p[url])
        self.assertEqual(out["candidate_race_count"],3)
        self.assertEqual(out["unlinked_registered_race_count"],2)
        self.assertFalse(out["all_races_linked"])
        self.assertTrue(out["unlinked_races_are_HOLD"])

    def test_other_day_meeting_cannot_be_spliced(self):
        p=fixture()
        p[CAL]=p[CAL].replace(b"24202611170200",b"24202611170100")
        out=discover.discover(day_jst="2026-11-18",
                              registered_ids=RIDS,fetch=lambda url:p[url])
        self.assertEqual(out["candidate_race_count"],0)
        self.assertEqual(out["unlinked_registered_race_count"],3)

    def test_unlinked_detail_cannot_be_constructed_from_missing_race_number(self):
        p=fixture()
        p[CARD]=p[CARD].replace(
            b'<a href="/utsunomiya/racedetail/2420261117020002/">2R</a>',b"")
        out=discover.discover(day_jst="2026-11-18",
                              registered_ids=RIDS,fetch=lambda url:p[url])
        self.assertEqual(out["candidate_race_count"],2)
        self.assertNotIn("202611182402",
                         {x["race_id"] for x in out["manifest"]["races"]})

    def test_duplicate_venue_meeting_conflicts_are_rejected(self):
        p=fixture()
        p[CAL]=p[CAL].replace(b"</body>",(
            b'<a href="/utsunomiya/racecard/24202611180100/">bad</a></body>'))
        # Day index 01 on Nov18 is another actual meeting from same venue.
        with self.assertRaisesRegex(discover.DayLinksError,"CONFLICTING_MEETING"):
            discover.discover(day_jst="2026-11-18",
                              registered_ids=RIDS,fetch=lambda url:p[url])

    def test_owner_untrusted_provider_error_stops_network_scan(self):
        p=fixture()
        attempts=[]
        def get(url):
            attempts.append(url)
            if url==CARD:
                raise capture.SourceCaptureError(
                    "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
            return p[url]
        out=discover.discover(day_jst="2026-11-18",
                              registered_ids=RIDS,fetch=get)
        self.assertEqual(attempts,[CAL,CARD])
        self.assertEqual(out["source_errors"],1)
        self.assertEqual(out["candidate_race_count"],0)


if __name__=="__main__":
    unittest.main()
