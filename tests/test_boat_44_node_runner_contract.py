"""Run the source-free BOAT 44-factor private batch contract in CI."""
from pathlib import Path
import os
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Boat44NodeRunnerContract(unittest.TestCase):
    def test_private_predict_contract_without_secrets_or_network(self):
        proc = subprocess.run(
            ["node", "tests/boat_44_p1_private_predict.test.cjs"],
            cwd=ROOT,
            env={"PATH": os.environ.get("PATH", ""),
                 "LANG": "C.UTF-8", "TZ": "UTC"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=40,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("BOAT_44_PRIVATE_SYNTHETIC_CONTRACT_PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
