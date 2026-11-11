"""Offline proof: main only registers the existing release workflow.

Not a live forecast, result settlement or source authorization.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
NAME=".github/workflows/boat-nationwide-ab-one-shot.yml"
WORKFLOW=(ROOT/NAME).read_text(encoding="utf8")


class BoatOwnerRegistryTest(unittest.TestCase):
    def test_same_exact_name_and_workflow_dispatch_input_as_released_owner(self):
        self.assertIn("name: BOAT nationwide cutoff-ordered A/B research (no Vercel)", WORKFLOW)
        self.assertIn("  workflow_dispatch:", WORKFLOW)
        self.assertIn("options: [existing-owner-p0-p1]", WORKFLOW)
        self.assertIn("production/boat-p0-p1-20261111", WORKFLOW)
        self.assertIn("11b905a7bf011baffdc0e8bcc5b568355d6e41b1", WORKFLOW)

    def test_default_main_cannot_issue_unaudited_predictions(self):
        self.assertIn("github.ref == 'refs/heads/main'", WORKFLOW)
        self.assertIn("HOLD_OWNER_P0_P1_RELEASE_REF_REQUIRED", WORKFLOW)
        self.assertIn("exit 2", WORKFLOW)
        self.assertNotIn("  schedule:", WORKFLOW)
        self.assertNotIn("  push:", WORKFLOW)

    def test_main_registry_is_not_another_model_or_result_engine(self):
        for prohibited in (
            "RACE_AI_STATE_KEY", "secrets.", "github.token", "actions: write",
            "boat_all_model_cycle", "racer_intraday_refresh", "gh api",
            "boat_saved_view_feed", "first_p0_bootstrap",
            "scripts.github_existing_cycle", "score_models", "forecast_round",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, WORKFLOW)
        self.assertEqual(WORKFLOW.count("  never_issue_from_main:"), 1)
        self.assertEqual(WORKFLOW.count("  source_free_registry_contract:"), 1)


if __name__=="__main__":
    unittest.main()
