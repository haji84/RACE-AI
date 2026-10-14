"""Trusted worker handoff: normalize and stage approved day snapshots.

No automatic official-site collection or cloud upload is performed. A separate
authorized collector must supply source bytes, rights evidence and timestamps.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path
from .day_feed_store import write_day_snapshot
from .github_archive_export import prepare_archive


def stage_for_distribution(*, store: Path, github_export: Path,
                           snapshot: dict, approval: dict,
                           day: date, archive_allowed: bool,
                           archive_evidence: str) -> dict:
    saved=write_day_snapshot(store,snapshot,approval,today=day)
    report={"date_jst":day.isoformat(),"local_snapshot":str(saved),
            "blob_upload":"PENDING_EXTERNAL_AUTHORIZED_WORKER",
            "github_archive":"NOT_REQUESTED"}
    if archive_allowed:
        exported=prepare_archive(store,github_export,day=day,
                                 archive_allowed=True,
                                 evidence_reference=archive_evidence)
        report["github_archive"]=exported
    return report
