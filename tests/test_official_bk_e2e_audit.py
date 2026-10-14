import unittest
from datetime import date
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.official_bk_e2e_audit import audit_pair


def metadata(kind):
    return {"date_jst":"2026-10-14","kind":kind,
            "structural_entries":6,"races":1,"venue_count":1,
            "download_sha256":kind.lower()*64,
            "extracted_text_sha256":"a"*64,
            "retrieved_at":"2026-10-14T09:00:00+00:00",
            "status":"STRUCTURAL_ACCEPTED_REQUIRES_OFFICIAL_RECONCILIATION"}


class OfficialBKE2ETests(unittest.TestCase):
    @patch("race_ai.official_bk_e2e_audit.fetch_and_parse")
    def test_both_archive_metadata_only(self, fetch):
        fetch.side_effect=lambda day,kind,include_rows=False: metadata(kind)
        result=audit_pair(date(2026,10,14))
        self.assertEqual(result["results"]["B"]["boats"],6)
        self.assertEqual(result["results"]["K"]["boats"],6)
        self.assertNotIn("racer_registration_id",str(result))

    @patch("race_ai.official_bk_e2e_audit.fetch_and_parse")
    def test_partial_k_rejected(self, fetch):
        def response(day,kind,include_rows=False):
            value=metadata(kind)
            if kind=="K":
                value["structural_entries"]=5
            return value
        fetch.side_effect=response
        with self.assertRaises(SourceError):
            audit_pair(date(2026,10,14))
