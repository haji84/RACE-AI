"""Public final control must be read by the exact producer, not main imports."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import boat_recovery_dispatch_gate as gate
from scripts import boat_main_dispatch_gate as base

class IsolatedReaderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(gate,'read_pinned_control'),'Pinned fresh-process control reader is absent')
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        pkg=self.root/'race_ai';pkg.mkdir();(pkg/'__init__.py').write_text('')
        (pkg/'github_continuous_supervisor.py').write_text('''import os
class GitHubCLI:
    def final_control(self, run):
        assert 'RACE_AI_STATE_KEY' not in os.environ
        assert 'RACE_AI_ORIGINAL_VAULT_ENABLED' not in os.environ
        return {'previous_run_id':run['id'],'from_pinned_reader':True}
''')
        subprocess.run(['git','init',str(self.root)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=fixture','-c','user.email=fixture@example.invalid',
                        'commit','-m','fixture'],check=True,capture_output=True)
        self.head=subprocess.check_output(['git','-C',str(self.root),'rev-parse','HEAD']).decode().strip()

    def test_fresh_process_uses_pinned_package_and_never_passes_owner_key(self):
        with patch.object(base,'RELEASE_SHA',self.head),patch.dict(os.environ,
                RACE_AI_STATE_KEY='synthetic-not-a-real-key',RACE_AI_ORIGINAL_VAULT_ENABLED='true'):
            result=gate.read_pinned_control({'id':99},reader_root=self.root)
        self.assertEqual(result,{'previous_run_id':99,'from_pinned_reader':True})

    def test_wrong_checkout_never_runs_the_reader(self):
        with patch.object(base,'RELEASE_SHA','0'*40):
            with self.assertRaises(ValueError):gate.read_pinned_control({'id':99},reader_root=self.root)

if __name__=='__main__':unittest.main()
