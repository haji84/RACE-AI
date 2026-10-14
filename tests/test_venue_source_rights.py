import unittest
from race_ai.venue_source_rights import VENUES, PURPOSES, RightsRecord, decision_for, can_publish

class VenueRightsTests(unittest.TestCase):
    def test_all_24_venues_present(self):
        self.assertEqual(len(VENUES),24)
        self.assertEqual(len(set(VENUES)),24)

    def test_unknown_is_not_approved(self):
        for n in range(1,25):
            for purpose in PURPOSES:
                self.assertEqual(decision_for([],f"{n:02d}",purpose),"unknown")
                self.assertFalse(can_publish([],f"{n:02d}",purpose))

    def test_video_analysis_is_not_video_publication(self):
        record=RightsRecord("18","video_internal_analysis","allowed",
            "https://example.org/official-policy","2026-10-14T09:00:00+09:00",
            "verified-evidence-reference","independent-reviewer")
        self.assertEqual(decision_for([record],"18","video_internal_analysis"),"allowed")
        self.assertFalse(can_publish([record],"18","video_publish"))
        self.assertFalse(can_publish([record],"18","photo_publish"))

    def test_unsubstantiated_approval_rejected(self):
        record=RightsRecord("18","facts_publish","allowed","","","","")
        with self.assertRaises(ValueError):
            decision_for([record],"18","facts_publish")
