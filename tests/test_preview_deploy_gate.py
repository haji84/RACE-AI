import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from race_ai.preview_deploy_gate import verify_preview_bundle

JST=ZoneInfo("Asia/Tokyo")


class PreviewDeployGateTests(unittest.TestCase):
    def fixture(self,root):
        bundle=root/"bundle"
        (bundle/"data").mkdir(parents=True)
        for name in ("index.html","app.js","style.css","ui-core.js","money.js"):
            (bundle/name).write_text("fixture",encoding="utf-8")
        day=datetime.now(JST).date().isoformat()
        (bundle/"data/today.json").write_text(json.dumps({
            "date_jst":day,"source_url":"https://example.org/test",
            "source_sha256":"a"*64,"first_observed_at":datetime.now(JST).isoformat(),
            "venues":[{"venue":"18","races":[{"race_id":day.replace("-","")+"-18-01",
                "boats":[{"lane":i,"racer_registration_id":str(4000+i),"motor_no":None}
                         for i in range(1,7)]}]}]}),encoding="utf-8")
        approval=root/"approval.json"
        approval.write_text(json.dumps({"redistribution_authorized":True,
            "source_url":"https://example.org/test",
            "evidence_reference":"synthetic-only","reviewed_by":"test"}),encoding="utf-8")
        return bundle,approval

    def test_preview_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,approval=self.fixture(Path(tmp))
            result=verify_preview_bundle(bundle,approval,target="preview",project="race-ai-preview")
            self.assertEqual(result["races"],1)
            with self.assertRaises(ValueError):
                verify_preview_bundle(bundle,approval,target="production",project="race-ai-preview")
            with self.assertRaises(ValueError):
                verify_preview_bundle(bundle,approval,target="preview",project="another-project")

    def test_missing_permission_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle,approval=self.fixture(Path(tmp))
            approval.write_text("{}",encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_preview_bundle(bundle,approval,target="preview",project="race-ai-preview")
