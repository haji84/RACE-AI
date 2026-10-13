"""Release-shell invariants; structural tests, NOT browser E2E proof."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")


class MobileShellTests(unittest.TestCase):
    def test_forthcoming_modules_explicit(self):
        for sport in ('data-sport="horse"', 'data-sport="cycle"', 'data-sport="auto"'):
            self.assertIn(sport, HTML)
        self.assertIn("Coming soon...", HTML)
        self.assertIn('data-sport="boat"', HTML)

    def test_no_remote_data_access_in_frontend(self):
        self.assertIn("connect-src 'none'", HTML)
        self.assertNotIn("fetch(", JS)
        self.assertNotIn("XMLHttpRequest", JS)
        self.assertNotIn("localStorage", JS)
        # A URL-prefix check is permitted; actual network calls are not.
        self.assertNotIn("sendBeacon(", JS)
        self.assertNotIn("new WebSocket(", JS)
        self.assertIn("file.text()", JS)

    def test_prediction_gated(self):
        self.assertIn("予想・買い目はまだ公開対象外", HTML)
        self.assertIn("未取得", JS)

    def test_xss_safety_basic(self):
        self.assertIn("textContent", JS)
        self.assertNotIn("innerHTML", JS)
        self.assertIn("replaceChildren", JS)

    def test_provenance_and_schema_guard(self):
        self.assertIn("first_observed_at", JS)
        self.assertIn("source_sha256", JS)
        self.assertIn("source_url", JS)
        self.assertIn("races !== count", JS)
        self.assertIn("6_000_000", JS)

    def test_javascript_syntax_when_node_available(self):
        if not shutil.which("node"):
            self.skipTest("node unavailable")
        subprocess.run(["node", "--check", str(ROOT / "web" / "app.js")], check=True)

    def test_mobile_responsive_layout(self):
        self.assertIn('name="viewport"', HTML)
        self.assertIn("@media(max-width:640px)", CSS)


if __name__ == "__main__":
    unittest.main()
