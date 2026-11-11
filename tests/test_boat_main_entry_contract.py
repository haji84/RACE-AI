"""Offline-only guard for reusing the existing BOAT P0/P1 owner worker.

This is a CI contract, not a prediction or authentication proof.
"""
from pathlib import Path
import unittest


class BoatMainEntryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] /
                      ".github/workflows/boat-nationwide-ab-one-shot.yml").read_text()

    def test_dispatch_is_only_normal_production_admission(self):
        source = self.source
        self.assertIn("  workflow_dispatch:", source)
        self.assertIn("github.event_name == 'workflow_dispatch'", source)
        self.assertIn("startsWith(github.event.head_commit.message, 'boat-grid-forward:')", source)
        self.assertIn("github.event_name == 'push' && startsWith(github.event.head_commit.message, 'saved-view:')", source)
        self.assertIn("boat-nationwide-cutoff-20261103", source)
        self.assertIn("cancel-in-progress: false", source)

    def test_same_immutable_original_and_existing_models(self):
        source = self.source
        for entry in (
            "scripts/first_p0_bootstrap.py capture-wait",
            "scripts/first_p0_bootstrap.py finalize",
            "scripts/github_existing_cycle.py restore",
            "scripts/boat_all_model_cycle bootstrap-current",
            "scripts/boat_all_model_cycle readback",
            "scripts/boat_private_original_vault capture",
            "scripts/boat_saved_view_feed --hydrate-originals",
            "./.github/actions/existing-model-round",
            "scripts/boat_source_control pack",
        ):
            with self.subTest(entry=entry):
                self.assertIn(entry, source)
        self.assertEqual(source.count("uses: ./.github/actions/existing-model-round"), 24)
        self.assertIn("RACE_AI_STATE_KEY: ${{ secrets.RACE_AI_STATE_KEY }}", source)

    def test_never_permits_new_result_scorer_or_dummy_model(self):
        self.assertEqual(self.source.count("  official_national:"), 1)
        self.assertEqual(self.source.count("  saved_view_publication:"), 1)
        self.assertEqual(self.source.count("  main_entry_contract:"), 1)
        self.assertNotIn("fake_forecast", self.source)
        self.assertNotIn("synthetic-result-writer", self.source)


if __name__ == "__main__":
    unittest.main()
