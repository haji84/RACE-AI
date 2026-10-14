"""Pure frontend ticket rules; real model execution through Node."""
from pathlib import Path
import shutil
import subprocess
import unittest

class UIModelTests(unittest.TestCase):
    def test_manual_ticket_accounting(self):
        if not shutil.which('node'):
            self.skipTest('node unavailable')
        root = Path(__file__).resolve().parents[1]
        subprocess.run(['node', str(root / 'tests/ui_model.test.js')], check=True)
