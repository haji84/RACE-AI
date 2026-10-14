"""Private Blob SDK adapter with exact day keys and explicit E2E checks.

The adapter accepts an SDK client to allow deterministic offline tests.
Real writes require an authorized operator and a configured private store.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib
import json

from .blob_key import day_blob_key
from .day_feed_store import read_current_snapshot

MAX_BYTES=6_000_000


def upload_and_verify(client, store: Path, *, day: date, execute: bool=False) -> dict:
    data=read_current_snapshot(store,today=day)
    key=day_blob_key(day)
    raw=(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    if len(raw)>MAX_BYTES:
        raise ValueError("oversized snapshot")
    expected=hashlib.sha256(raw).hexdigest()
    if not execute:
        return {"status":"DRY_RUN","pathname":key,"sha256":expected}
    uploaded=client.put(key,raw,access="private",
                        content_type="application/json",
                        add_random_suffix=False,overwrite=True)
    uploaded_path=uploaded.get("pathname") if isinstance(uploaded,dict) else getattr(uploaded,"pathname",None)
    if uploaded_path!=key:
        raise ValueError("Blob upload pathname mismatch")
    retrieved=client.get(key,access="private")
    if retrieved is None:
        raise ValueError("Blob readback missing")
    stream=retrieved.get("stream") if isinstance(retrieved,dict) else getattr(retrieved,"stream",None)
    if stream is None:
        raise ValueError("Blob SDK stream missing")
    if isinstance(stream,(bytes,bytearray)):
        payload=bytes(stream)
    else:
        chunks=[]
        total=0
        for chunk in stream:
            if not isinstance(chunk,bytes):
                raise ValueError("Blob SDK returned invalid stream chunk")
            total+=len(chunk)
            if total>MAX_BYTES:
                raise ValueError("Blob readback too large")
            chunks.append(chunk)
        payload=b"".join(chunks)
    if hashlib.sha256(payload).hexdigest()!=expected:
        raise ValueError("Blob readback content mismatch")
    return {"status":"BLOB_ROUNDTRIP_VERIFIED","pathname":key,"sha256":expected}
