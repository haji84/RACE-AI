import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/"web/api/blob-probe.py"
sys.path.insert(0,str(PATH.parent))
# Unit tests exercise endpoint gating without requiring external JWT package.
verifier_stub=types.ModuleType("github_oidc")
verifier_stub.verify_github_oidc=lambda token: (_ for _ in ()).throw(ValueError("unverified"))
sys.modules["github_oidc"]=verifier_stub
spec=importlib.util.spec_from_file_location("blob_probe",PATH)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ProbeAuthorizationTests(unittest.TestCase):
    def test_no_bearer_rejected(self):
        with patch.dict(os.environ,{"VERCEL_ENV":"preview"},clear=True):
            self.assertFalse(probe.authorized({}))

    def test_production_rejected(self):
        with patch.dict(os.environ,{"VERCEL_ENV":"production"},clear=True):
            with patch.object(probe,"verify_github_oidc",return_value={}):
                self.assertFalse(probe.authorized({"Authorization":"Bearer example"}))

    def test_invalid_oidc_rejected(self):
        with patch.dict(os.environ,{"VERCEL_ENV":"preview"},clear=True):
            with patch.object(probe,"verify_github_oidc",side_effect=ValueError("invalid")):
                self.assertFalse(probe.authorized({"Authorization":"Bearer example"}))

    def test_valid_oidc_in_preview(self):
        with patch.dict(os.environ,{"VERCEL_ENV":"preview"},clear=True):
            with patch.object(probe,"verify_github_oidc",return_value={}):
                self.assertTrue(probe.authorized({"Authorization":"Bearer example"}))
