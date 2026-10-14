"""Validate a preview bundle before a separately authorized Vercel deployment.

No Vercel token, API call, or deployment is performed by this module.
A trusted CI/deployer must separately check real redistribution rights and
target only the designated Preview project/environment.
"""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .day_snapshot_publisher import validate

JST=ZoneInfo("Asia/Tokyo")


def verify_preview_bundle(bundle: Path, approval: Path, *,
                          target: str, project: str, today=None) -> dict:
    if target != "preview" or project != "race-ai-preview":
        raise ValueError("production or unexpected project is forbidden")
    if not bundle.is_dir() or bundle.is_symlink():
        raise ValueError("bundle missing or symlinked")
    for name in ("index.html","app.js","style.css"):
        path=bundle/name
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing web asset")
    snapshot=bundle/"data"/"today.json"
    if not snapshot.is_file() or snapshot.is_symlink() or snapshot.stat().st_size > 6000000:
        raise ValueError("missing/oversized day snapshot")
    payload=json.loads(snapshot.read_text(encoding="utf-8"))
    evidence=json.loads(approval.read_text(encoding="utf-8"))
    verified=validate(payload,today=today or datetime.now(JST).date(),approval=evidence)
    if not verified.get("redistribution_authorized"):
        raise ValueError("redistribution not authorized")
    return {"target":target,"project":project,"date_jst":verified["date_jst"],
            "races":verified["races"],"venues":len(verified["venues"]),
            "status":"READY_FOR_SEPARATE_PERMISSION_AND_DEPLOYMENT_REVIEW"}
