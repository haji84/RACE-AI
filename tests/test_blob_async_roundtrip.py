import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from race_ai.blob_async_roundtrip import read_bounded,verify_private_day

DAY=date(2026,10,14)
class AsyncClient:
    def __init__(self):self.objects={}
    async def put(self,key,raw,**kwargs):
        assert kwargs["access"]=="private"
        assert kwargs["add_random_suffix"] is False
        self.objects[key]=raw
        return {"pathname":key}
    async def get(self,key,**kwargs):
        async def stream():
            yield self.objects[key][:7]
            yield self.objects[key][7:]
        return {"status_code":200,"stream":stream()}

class AsyncBlobTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_content_bytes(self):
        from types import SimpleNamespace
        class Client(AsyncClient):
            async def get(self, key, **kwargs):
                self.read_options = kwargs
                return SimpleNamespace(content=self.objects[key], status_code=200)
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            (store/'2026-10-14.json').write_text('{"date_jst":"2026-10-14","redistribution_authorized":true}', encoding='utf-8')
            client = Client()
            result = await verify_private_day(client, store, day=DAY, execute=True)
            self.assertEqual(result['status'], 'BLOB_ASYNC_ROUNDTRIP_VERIFIED')
            self.assertIs(client.read_options.get('use_cache'), False)

    async def test_async_stream(self):
        async def chunks():
            yield b"abc"
            yield b"def"
        self.assertEqual(await read_bounded(chunks()),b"abcdef")

    async def test_private_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Path(tmp)
            (store/"2026-10-14.json").write_text('{"date_jst":"2026-10-14","redistribution_authorized":true}',encoding="utf-8")
            result=await verify_private_day(AsyncClient(),store,day=DAY,execute=True)
            self.assertEqual(result["status"],"BLOB_ASYNC_ROUNDTRIP_VERIFIED")
            self.assertEqual(result["pathname"],"race-ai/day/2026-10-14.json")

    async def test_oversize_stream_rejected(self):
        async def chunks():
            yield b"x"*6_000_001
        with self.assertRaises(ValueError):
            await read_bounded(chunks())
