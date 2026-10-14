import unittest
from pathlib import Path
from race_ai.synthetic_preview_e2e import run


class SyntheticPreviewE2ETests(unittest.TestCase):
    def test_synthetic_end_to_end_bundle_and_gate(self):
        result=run(Path(__file__).resolve().parents[1]/"web")
        self.assertEqual(result["target"],"preview")
        self.assertEqual(result["races"],1)
        self.assertEqual(result["venues"],1)
        self.assertEqual(result["test_data"],"SYNTHETIC_ONLY_NOT_REAL_RACES")
