"""Run the existing Worker refund path offline; no network or deployment."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RefundReplayNodeTest(unittest.TestCase):
    def test_verified_refund_last_race_and_fresh_process_replay(self):
        result = subprocess.run(
            ['node', '--test', 'tests/boat_refund_replay.test.mjs'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=45, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == '__main__':
    unittest.main()
