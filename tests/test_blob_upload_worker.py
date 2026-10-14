import tempfile
import unittest
from datetime import date
from pathlib import Path
from race_ai.blob_upload_worker import upload_day

class BlobUploadWorkerTests(unittest.TestCase):
    def test_missing_snapshot_never_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                upload_day(Path(tmp),day=date(2026,10,14),scope="qq1130034-1738",execute=False)

    def test_scope_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                upload_day(Path(tmp),day=date(2026,10,14),scope="",execute=False)
