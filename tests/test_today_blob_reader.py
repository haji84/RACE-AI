import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]/"web/api/today.py"
spec=importlib.util.spec_from_file_location("race_today_api",MODULE)
api=importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

class TodayBlobReaderTests(unittest.TestCase):
    def test_unapproved_never_reads_blob(self):
        with patch.dict(os.environ,{"RACE_AI_FEED_APPROVED":"0"},clear=True):
            status,data=api.load_feed()
            self.assertEqual(status,503)
            self.assertEqual(data["error"],"FEED_NOT_APPROVED")

    def test_arbitrary_host_rejected(self):\n        with patch.dict(os.environ,{"RACE_AI_FEED_APPROVED":"1",\n             "VERCEL_OIDC_TOKEN":"fixture-token",\n             "RACE_AI_BLOB_BASE_URL":"https://example.org"},clear=True):\n            status,data=api.load_feed()\n            self.assertEqual(status,503)\n            self.assertEqual(data["error"],"FEED_STORE_NOT_CONFIGURED")\n\n    def test_missing_store_configuration(self):
        with patch.dict(os.environ,{"RACE_AI_FEED_APPROVED":"1"},clear=True):
            status,data=api.load_feed()
            self.assertEqual(status,503)
            self.assertEqual(data["error"],"FEED_STORE_NOT_CONFIGURED")
