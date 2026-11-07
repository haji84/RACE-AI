"""Run the offline Node policy tests; no browser, provider or key access."""
from pathlib import Path
import subprocess
import unittest


class OfficialResultBrowserCaptureTests(unittest.TestCase):
    def test_offline_normal_ui_capture_contracts(self):
        root=Path(__file__).resolve().parents[1]
        run=subprocess.run(['node','--test','tests/official_result_browser_capture.test.cjs'],cwd=root,
            capture_output=True,text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)


if __name__=='__main__':unittest.main()
