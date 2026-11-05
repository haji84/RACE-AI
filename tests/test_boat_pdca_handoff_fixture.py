import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HandoffFixtureTests(unittest.TestCase):
    def test_two_process_encrypted_handoff_scores_revisions_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            base=[sys.executable,'-m','scripts.boat_pdca_handoff_fixture']
            fixture_env=dict(os.environ,GITHUB_ACTIONS='true',GITHUB_RUN_ID='12345',
                EXPECTED_PRODUCER_RUN_ID='12345',
                EXPECTED_PRODUCER_SHA=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
            fixture_env.pop('GITHUB_OUTPUT',None)
            produced=subprocess.run(base+['produce','--work',str(root/'producer'),'--artifact',str(root/'artifact')],capture_output=True,text=True,env=fixture_env)
            self.assertEqual(produced.returncode,0,produced.stderr+produced.stdout)
            proof=json.loads(produced.stdout)
            self.assertTrue(proof['synthetic_only'])
            consumed=subprocess.run(base+['consume','--work',str(root/'consumer'),'--artifact',str(root/'artifact'),
                '--expected-cipher-sha256',proof['cipher_sha256']],capture_output=True,text=True,env=fixture_env)
            self.assertEqual(consumed.returncode,0,consumed.stderr+consumed.stdout)
            report=json.loads(consumed.stdout)
            self.assertEqual(report['pairs'],2)
            self.assertEqual(report['result_revisions'],2)
            self.assertEqual(report['scorings'],2)
            self.assertTrue(report['original_bytes_preserved'])
            self.assertFalse(report['real_data_operation_verified'])
            self.assertFalse(report['accuracy_improvement_proven'])
            self.assertEqual(set(p.name for p in (root/'artifact').iterdir()),{'state.enc','proof.json','handoff-proof.json'})
            forged=subprocess.run(base+['consume','--work',str(root/'foreign'),'--artifact',str(root/'artifact'),
                '--expected-cipher-sha256',proof['cipher_sha256']],capture_output=True,text=True,
                env=dict(fixture_env,EXPECTED_PRODUCER_RUN_ID='54321'))
            self.assertNotEqual(forged.returncode,0)
            self.assertIn('SYNTHETIC_PRODUCER_IDENTITY_MISMATCH',forged.stderr)
