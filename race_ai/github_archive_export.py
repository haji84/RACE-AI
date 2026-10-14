"""Prepare a GitHub archive of approved daily race facts without uploading.

This is a pure exporter: a separate authorized workflow may commit its output
to an approved repository. Never include raw media, credentials or unapproved
official-source payloads. GitHub is archival, not a live API backend.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
import hashlib
import json

from .day_feed_store import read_current_snapshot

ALLOWED_FIELDS=frozenset({"date_jst","source_url","source_sha256","first_observed_at",
                          "redistribution_authorized","venues","races",
                          "complete_six_boat_races"})


def prepare_archive(store: Path, destination: Path, *, day: date,
                    archive_allowed: bool, evidence_reference: str) -> dict:
    if archive_allowed is not True or not evidence_reference.strip():
        raise ValueError("GitHub archival permission not independently established")
    data=read_current_snapshot(store,today=day)
    if not data.get("redistribution_authorized"):
        raise ValueError("source cannot be republished")
    # Prevent unrelated/private fields being silently exported.
    unknown=set(data)-ALLOWED_FIELDS
    if unknown:
        raise ValueError("unreviewed archive fields: "+",".join(sorted(unknown)))
    if destination.exists() or destination.is_symlink():
        raise ValueError("archive path already exists")
    payload={"schema_version":1,"date_jst":day.isoformat(),
             "archive_evidence_reference":evidence_reference,
             "snapshot":data}
    encoded=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
    if len(encoded)>6_000_000:
        raise ValueError("archive too large")
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(encoded)
    return {"path":str(destination),"sha256":hashlib.sha256(encoded).hexdigest(),
            "bytes":len(encoded),"status":"READY_FOR_SEPARATE_GITHUB_REVIEW"}
