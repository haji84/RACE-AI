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

    def test_reviewed_eff_origin_never_substitutes_for_current_reader_checkout(self):
        self._assert_historical_checkout_refused('eff296f6d54ad4be297d93e32f1ee0d4592ad9e3')

    def test_reviewed_m2_origin_never_substitutes_for_current_reader_checkout(self):
        self._assert_historical_checkout_refused('86b029ae5bddd5d4956497d8b32b2c92b8eec521')

    def test_reviewed_f553_origin_never_substitutes_for_current_reader_checkout(self):
        self._assert_historical_checkout_refused('f55351dce855177a51330f72c37d6238ba2c9e3e')

    def _assert_historical_checkout_refused(self,previous):
        with patch.object(base,'RELEASE_SHA','e'*40), \
             patch.object(gate.subprocess,'check_output',return_value=previous.encode()), \
             patch.object(gate.subprocess,'run') as child:
            with self.assertRaisesRegex(ValueError,'RECOVERY_PINNED_CONTROL_UNAVAILABLE'):
                gate.read_pinned_control({'id':99,'head_sha':previous},reader_root=self.root)
        child.assert_not_called()

    def test_gate_ci_checks_exact_dispatch_reader_separately_from_audit_reader(self):
        from scripts import boat_owner_evidence_audit as audit
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-main-recovery-contract.yml').read_text()
        gate_job,audit_job=source.split('\n  original_evidence:\n',1)
        self.assertIn('ref: '+base.RELEASE_SHA+', path: boat-owner-reader',gate_job)
        self.assertIn('ref: '+audit.OWNER_SHA+', path: boat-owner-reader',audit_job)


    def test_reviewed_bb_origin_never_substitutes_for_current_reader_checkout(self):
        self._assert_historical_checkout_refused(
            'bb49215034b779ea1493b35dd91e5c3ebfc04032')


if __name__=='__main__':unittest.main()
