"""Offline owner-private import verifies captured bytes before parsing."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest

try:
    importer=importlib.import_module('scripts.boat_context_import')
except ModuleNotFoundError:importer=None

class CapturedContextImportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importer,'private supplemental captured-source import is missing')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        os.chmod(self.root,0o700)
        (self.root/'source.html').write_bytes(b'captured official source')
        os.chmod(self.root/'source.html',0o600)
        meta=dict(status=200,file='source.html',url='https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=12&jcd=12&hd=20300401',sha256=hashlib.sha256(b'captured official source').hexdigest(),acquired_at='2030-04-01T09:00:00Z')
        (self.root/'source.json').write_text(json.dumps(meta));os.chmod(self.root/'source.json',0o600)

    def test_changed_original_rejected_before_parser(self):
        (self.root/'source.html').write_bytes(b'different bytes')
        with self.assertRaisesRegex(ValueError,'SOURCE_CAPTURE_HASH_MISMATCH'):
            importer.read_capture(self.root,'source.json')

    def test_private_source_has_original_clock_and_hash(self):
        raw,source=importer.read_capture(self.root,'source.json')
        self.assertEqual(raw,b'captured official source')
        self.assertEqual(source['acquired_at'],'2030-04-01T09:00:00Z')

    def test_relative_escape_and_symlink_are_rejected(self):
        with self.assertRaises((ValueError,OSError)):
            importer.read_capture(self.root,'../source.json')
        (self.root/'symlink.json').symlink_to(self.root/'source.json')
        with self.assertRaises((ValueError,OSError)):
            importer.read_capture(self.root,'symlink.json')
