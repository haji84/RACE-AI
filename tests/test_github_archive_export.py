import tempfile
import unittest
from datetime import date
from pathlib import Path
from race_ai.github_archive_export import prepare_archive

class GithubArchiveTests(unittest.TestCase):
    def test_unapproved_archive_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"archive.json"
            with self.assertRaises(ValueError):
                prepare_archive(Path(tmp),path,day=date(2026,10,14),
                                archive_allowed=False,evidence_reference="")
            self.assertFalse(path.exists())

    def test_no_existing_archive_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"archive.json"
            path.write_text("existing",encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_archive(Path(tmp),path,day=date(2026,10,14),
                                archive_allowed=True,evidence_reference="fixture")
            self.assertEqual(path.read_text(encoding="utf-8"),"existing")
