import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[1]/"web/api/blob-probe.py"
spec=importlib.util.spec_from_file_location("blob_probe",PATH)
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ProbeAuthorizationTests(unittest.TestCase):
    def test_no_secret_rejected(self):
        with patch.dict(os.environ,{"VERCEL_ENV":"preview"},clear=True):
            self.assertFalse(probe.authorized({"X-Race-AI-Probe-Secret":""}))

    def test_production_rejected_even_with_secret(self):
        secret="a"*40
        with patch.dict(os.environ,{"VERCEL_ENV":"production","RACE_AI_PROBE_SECRET":secret},clear=True):
            self.assertFalse(probe.authorized({"X-Race-AI-Probe-Secret":secret}))

    def test_preview_secret_required(self):
        secret="a"*40
        with patch.dict(os.environ,{"VERCEL_ENV":"preview","RACE_AI_PROBE_SECRET":secret},clear=True):
            self.assertFalse(probe.authorized({"X-Race-AI-Probe-Secret":"wrong"}))
            self.assertTrue(probe.authorized({"X-Race-AI-Probe-Secret":secret}))
