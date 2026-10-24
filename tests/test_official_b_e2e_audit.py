import unittest
from datetime import date
from unittest.mock import patch

from race_ai.core import SourceError
from race_ai.official_b_e2e_audit import audit


class OfficialBE2EAuditTests(unittest.TestCase):
    @patch("race_ai.official_b_e2e_audit.fetch_and_parse")
    def test_structural_pass_metadata_only(self, fetch):
        fetch.return_value = {"kind":"B","date_jst":"2026-10-14",
            "structural_entries":6,"races":1,"venue_count":1,
            "download_sha256":"a"*64,"extracted_text_sha256":"b"*64,
            "retrieved_at":"2026-10-14T08:00:00+00:00"}
        result=audit(date(2026,10,14))
        self.assertEqual(result["boats"],6)
        self.assertNotIn("race_rows",result)

    @patch("race_ai.official_b_e2e_audit.fetch_and_parse")
    def test_incomplete_race_rejected(self, fetch):
        fetch.return_value={"kind":"B","date_jst":"2026-10-14",
            "structural_entries":5,"races":1,"venue_count":1}
        with self.assertRaises(SourceError):
            audit(date(2026,10,14))
