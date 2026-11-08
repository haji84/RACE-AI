"""Run source-free six-way Node contracts from the existing Python CI discovery.

No secrets, no provider GET, no changes to workflow/cron or production model.
"""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BoatSixWayNodeContractTests(unittest.TestCase):
    def _node(self, filename, marker):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "TZ": "UTC",
        }
        result = subprocess.run(
            ["node", filename],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=50,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            msg="source-free Node contract failed: " + result.stderr[-1200:],
        )
        self.assertIn(marker, result.stdout)

    def test_120_ticket_overlay_standalone(self):
        self._node(
            "tests/boat_six_way_probability_overlay.test.cjs",
            "SIX_WAY_OVERLAY_SYNTHETIC_PASS",
        )

    def test_local_six_course_research_view_standalone(self):
        self._node(
            "tests/boat_six_course_tactical_view.test.cjs",
            "Source-free 6-course view contract PASS",
        )

    def test_grade_transition_research_standalone(self):
        self._node(
            "tests/boat_grade_transition_research.test.cjs",
            "GRADE_TRANSITION_RESEARCH_SYNTHETIC_PASS",
        )


if __name__ == "__main__":
    unittest.main()
