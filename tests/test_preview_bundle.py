import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from race_ai.preview_bundle import package_preview

JST=ZoneInfo("Asia/Tokyo")


class PreviewBundleTests(unittest.TestCase):
    def fixture(self, root):
        web=root/"web"
        web.mkdir()
        for name in ("index.html","app.js","style.css","ui-model.js"):
            (web/name).write_text("fixture "+name,encoding="utf-8")
        day=datetime.now(JST).date().isoformat()
        source=root/"snapshot.json"
        source.write_text(json.dumps({
            "date_jst":day,"source_url":"https://example.org/authorized",
            "source_sha256":"a"*64,"first_observed_at":datetime.now(JST).isoformat(),
            "venues":[{"venue":"18","races":[{"race_id":day.replace("-","")+"-18-01",
                "boats":[{"lane":i,"racer_registration_id":str(4000+i),"motor_no":None}
                         for i in range(1,7)]}]}]}),encoding="utf-8")
        approval=root/"approval.json"
        approval.write_text(json.dumps({
            "redistribution_authorized":True,"source_url":"https://example.org/authorized",
            "evidence_reference":"synthetic-test-only","reviewed_by":"test"}),encoding="utf-8")
        return web,source,approval

    def test_authorized_fixture_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            web,source,approval=self.fixture(root)
            output=root/"build"
            package_preview(web,source,approval,output)
            self.assertTrue((output/"index.html").exists())
            self.assertEqual((output/"ui-model.js").read_text(),"fixture ui-model.js")
            data=json.loads((output/"data/today.json").read_text(encoding="utf-8"))
            self.assertEqual(data["races"],1)
            self.assertIsNone(data["venues"][0]["races"][0]["boats"][0]["motor_no"])

    def test_no_rights_no_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            web,source,approval=self.fixture(root)
            approval.write_text("{}",encoding="utf-8")
            output=root/"build"
            with self.assertRaises(ValueError):
                package_preview(web,source,approval,output)
            self.assertFalse(output.exists())

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            web,source,approval=self.fixture(root)
            output=root/"build"
            output.mkdir()
            with self.assertRaises(ValueError):
                package_preview(web,source,approval,output)
