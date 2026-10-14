import unittest
from datetime import date
from race_ai.blob_key import day_blob_key

class BlobKeyTests(unittest.TestCase):
    def test_exact_day_path(self):
        self.assertEqual(day_blob_key(date(2026,10,14)),"race-ai/day/2026-10-14.json")
    def test_invalid_day_rejected(self):
        with self.assertRaises(ValueError):
            day_blob_key("2026-10-14")
