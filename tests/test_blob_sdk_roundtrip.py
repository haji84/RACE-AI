import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from race_ai.blob_sdk_roundtrip import upload_and_verify

DAY=date(2026,10,14)
KEY="race-ai/day/2026-10-14.json"

class FakeClient:
    def __init__(self):self.data={}
    def put(self,key,data,**kwargs):
        assert kwargs["access"]=="private"
        assert kwargs["add_random_suffix"] is False
        self.data[key]=data
        return {"pathname":key}
    def get(self,key,**kwargs):
        return {"stream":iter([self.data[key][:10],self.data[key][10:]])} if key in self.data else None

class BlobSdkRoundtripTests(unittest.TestCase):
    def test_exact_path_and_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Path(tmp)
            (store/"2026-10-14.json").write_text('{"date_jst":"2026-10-14","redistribution_authorized":true}',encoding="utf-8")
            report=upload_and_verify(FakeClient(),store,day=DAY,execute=True)
            self.assertEqual(report["pathname"],KEY)
            self.assertEqual(report["status"],"BLOB_ROUNDTRIP_VERIFIED")

    def test_dry_run_never_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Path(tmp)
            (store/"2026-10-14.json").write_text('{"date_jst":"2026-10-14","redistribution_authorized":true}',encoding="utf-8")
            client=FakeClient()
            report=upload_and_verify(client,store,day=DAY,execute=False)
            self.assertEqual(report["status"],"DRY_RUN")
            self.assertEqual(client.data,{})
