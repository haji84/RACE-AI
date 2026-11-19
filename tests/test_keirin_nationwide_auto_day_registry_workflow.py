"""Synthetic workflow wiring checks; never performs a provider GET or model prediction.

The 2026-11-19 goal needs an *observed* current-day roster, not the
previous day's fixed cohort. This tests that the source registration feeder
actually runs before A/B and a missing/invalid date stays HOLD.
"""
from pathlib import Path
import unittest


WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/keirin-nationwide-ab-auto.yml")


class LiveDayRegistryWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = WORKFLOW.read_text(encoding="utf-8")
        cls.owner = text.split("  owner-auto-generate:\n", 1)[1].split(
            "  independent-cipher-readback:\n", 1)[0]

    def test_future_day_registration_precedes_capture_and_forecast(self):
        block = self.owner
        self.assertLess(block.index("python -m scripts.keirin_register_public_day"),
                        block.index("python -m scripts.keirin_capture_public_two_sources"))
        self.assertLess(block.index("python -m scripts.keirin_capture_public_two_sources"),
                        block.index("python -m scripts.keirin_nationwide_auto_forecast"))
        self.assertIn('if [ "$day" != \'2026-11-18\' ]', block)
        self.assertIn('--day "$day"', block)
        self.assertIn('PARTIAL_PUBLIC_LINKS_NATIONAL_UNIVERSE_UNVERIFIED', block)

    def test_forecast_and_artifacts_require_checked_current_day(self):
        block = self.owner
        self.assertIn("id: registry_gate", block)
        self.assertIn('doc.get("day_jst")!=day', block)
        self.assertIn("registered_race_ids(doc)", block)
        self.assertIn("HOLD_CURRENT_JST_DAY_REGISTRY_MISSING", block)
        self.assertIn("HOLD_CURRENT_DAY_REGISTRY_INVALID", block)
        self.assertIn("ready: ${{ steps.registry_gate.outputs.ready }}", block)
        self.assertIn(
            "if: steps.registry_gate.outputs.ready == 'true' && "
            "vars.RACE_AI_AB_PUBLIC_CAPTURE_ENABLED == 'true'", block)
        self.assertGreaterEqual(
            block.count("if: steps.registry_gate.outputs.ready == 'true'"), 3)

    def test_research_pr_cannot_silently_become_production(self):
        block = self.owner
        self.assertIn("github.ref == 'refs/heads/main'", block)
        self.assertIn(
            "vars.RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED == 'true'", block)
        self.assertIn("github.event_name == 'schedule'", block)
        self.assertIn('retention-days: 21', block)


if __name__ == "__main__":
    unittest.main()
