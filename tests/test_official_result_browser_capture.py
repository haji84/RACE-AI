"""Run the offline Node policy tests; no browser, provider or key access."""
from pathlib import Path
import subprocess
import unittest


class OfficialResultBrowserCaptureTests(unittest.TestCase):
    def test_offline_normal_ui_capture_contracts(self):
        root=Path(__file__).resolve().parents[1]
        run=subprocess.run(['node','--test','tests/official_result_browser_capture.test.cjs',
            'tests/official_result_prior_static_cache.test.cjs','tests/official_result_auto_selected_date.test.cjs','tests/official_result_auto_result_refresh.test.cjs','tests/official_result_auto_optional_refund.test.cjs',
            'tests/official_result_keirin_venue_label.test.cjs','tests/official_result_keirin_card_result.test.cjs','tests/official_future_browser_capture.test.cjs'],cwd=root,
            capture_output=True,text=True,timeout=45)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)


if __name__=='__main__':unittest.main()
