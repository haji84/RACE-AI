"""Single BOAT A/B freeze index shared across the nationwide and Miyajima pilots.

This is a deduplication guard, NOT independent proof that Github artifacts
still exist. Actual preclosing acceptance continues to require Github
server-side saved_at, original ZIP/JSON SHA-256 and readback for EACH run.
Never reissue a previously frozen race under a new pilot just because a
different chat or run was invoked.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re

from .boat_ab_shadow import MODEL_IDS, _time

SCHEMA="RACE_AI_BOAT_OWNER_PROSPECTIVE_INDEX_V1"
FIELDS={"race_id","cutoff_at","run_id","artifact_id","server_created_at",
        "zip_sha256","json_sha256","bundle_sha256"}
HEX=re.compile(r"[0-9a-f]{64}\Z")
RID=re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
MAX_INDEX_BYTES=100_000
MAX_ENTRIES=288


def load_original_race_ids(index_path: str | Path, *, as_of: str) -> frozenset[str]:
    """Fail closed on corrupted original index rather than claiming a new freeze.

    Each race gets one externally stored ORIGINAL A/B research bundle. Official
    result corrections belong in separate result revisions. An existing index
    row cannot be an excuse to claim a new accuracy hit.
    """
    observed=_time(as_of).astimezone(timezone.utc)
    raw=Path(index_path).read_bytes()
    if not 1<=len(raw)<=MAX_INDEX_BYTES:
        raise ValueError("bounded original freeze index required")

    def unique_pairs(pairs):
        out={}
        for key,value in pairs:
            if key in out:
                raise ValueError("duplicate index JSON key")
            out[key]=value
        return out

    doc=json.loads(raw,object_pairs_hook=unique_pairs,parse_constant=lambda x:
                   (_ for _ in ()).throw(ValueError("nonfinite index")))
    if not isinstance(doc,dict) or set(doc)!={"schema","scope","model_ids","source_note","entries"}:
        raise ValueError("exact index contract required")
    if (doc["schema"]!=SCHEMA or doc["scope"]!="SELECTED_RACES_NOT_ALL_NATIONAL"
            or doc["model_ids"]!=list(MODEL_IDS)
            or not isinstance(doc["source_note"],str)
            or not isinstance(doc["entries"],list)
            or len(doc["entries"])>MAX_ENTRIES):
        raise ValueError("index model or scope mismatch")
    found=set()
    batch={}
    for record in doc["entries"]:
        if not isinstance(record,dict) or set(record)!=FIELDS:
            raise ValueError("index original reference incomplete")
        rid=record["race_id"]
        m=RID.fullmatch(rid) if isinstance(rid,str) else None
        if m is None or rid in found:
            raise ValueError("repeated or malformed original race id")
        found.add(rid)
        cutoff=_time(record["cutoff_at"])
        saved=_time(record["server_created_at"])
        if (cutoff.utcoffset()!=timedelta(hours=9)
                or cutoff.strftime("%Y%m%d")!=m.group(1)
                or saved.astimezone(timezone.utc)>observed
                or not saved+timedelta(seconds=120)<cutoff):
            raise ValueError("index forecast outside original preclose gate")
        for key in ("zip_sha256","json_sha256","bundle_sha256"):
            digest=record[key]
            if not isinstance(digest,str) or HEX.fullmatch(digest) is None:
                raise ValueError("original SHA absent")
        run,artifact=record["run_id"],record["artifact_id"]
        if type(run) is not int or run<=0 or type(artifact) is not int or artifact<=0:
            raise ValueError("valid GitHub artifact identity required")
        key=(run,artifact)
        common=(saved,record["zip_sha256"],record["json_sha256"])
        if key in batch and batch[key]!=common:
            raise ValueError("same batch artifact has contradictory source identity")
        batch[key]=common
    return frozenset(found)
