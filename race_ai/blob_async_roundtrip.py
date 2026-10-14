"""Async private Blob upload/readback verifier with exact day-key and SHA.

Client is injected for offline tests; real cloud calls require an authorized
Vercel Blob SDK client with access to the Preview private store.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib
import inspect
import json
from .blob_key import day_blob_key
from .day_feed_store import read_current_snapshot

MAX_BYTES=6_000_000


async def resolve(value):
    return await value if inspect.isawaitable(value) else value


async def read_bounded(stream):
    if stream is None:
        raise ValueError("missing Blob stream")
    if isinstance(stream,(bytes,bytearray)):
        if len(stream)>MAX_BYTES:raise ValueError("oversized Blob")
        return bytes(stream)
    chunks=[]
    size=0
    if hasattr(stream,"__aiter__"):
        async for chunk in stream:
            if not isinstance(chunk,bytes):raise ValueError("invalid Blob chunk")
            size+=len(chunk)
            if size>MAX_BYTES:raise ValueError("oversized Blob")
            chunks.append(chunk)
    else:
        for chunk in stream:
            if not isinstance(chunk,bytes):raise ValueError("invalid Blob chunk")
            size+=len(chunk)
            if size>MAX_BYTES:raise ValueError("oversized Blob")
            chunks.append(chunk)
    return b"".join(chunks)


async def verify_private_day(client, store: Path, *, day: date,
                             execute: bool=False) -> dict:
    data=read_current_snapshot(store,today=day)
    key=day_blob_key(day)
    raw=(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    expected=hashlib.sha256(raw).hexdigest()
    if not execute:
        return {"status":"DRY_RUN","pathname":key,"sha256":expected}
    result=await resolve(client.put(key,raw,access="private",
                                    content_type="application/json",
                                    add_random_suffix=False,overwrite=True))
    pathname=result.get("pathname") if isinstance(result,dict) else getattr(result,"pathname",None)
    if pathname!=key:raise ValueError("upload key mismatch")
    response=await resolve(client.get(key,access="private"))
    if response is None:raise ValueError("Blob not found")
    status=response.get("status_code",response.get("statusCode")) if isinstance(response,dict) else getattr(response,"status_code",getattr(response,"statusCode",None))
    if status is not None and status!=200:raise ValueError("unexpected Blob response")
    stream=response.get("stream") if isinstance(response,dict) else getattr(response,"stream",None)
    payload=await read_bounded(stream)
    if hashlib.sha256(payload).hexdigest()!=expected:
        raise ValueError("readback SHA mismatch")
    return {"status":"BLOB_ASYNC_ROUNDTRIP_VERIFIED","pathname":key,
            "sha256":expected,"bytes":len(payload)}
