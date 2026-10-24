import tempfile
import unittest
from datetime import date
from pathlib import Path
from race_ai.feed_worker_handoff import stage_for_distribution

class WorkerHandoffTests(unittest.TestCase):
    def test_unapproved_input_cannot_be_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                stage_for_distribution(store=root/"store",github_export=root/"archive.json",
                    snapshot={"date_jst":"2026-10-14","venues":[]},
                    approval={},day=date(2026,10,14),
                    archive_allowed=False,archive_evidence="")
            self.assertFalse((root/"archive.json").exists())
