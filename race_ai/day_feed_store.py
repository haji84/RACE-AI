"""Atomic approved-day snapshot store, independent of static deployments.

This storage module never fetches official data or grants redistribution
rights. A trusted publisher supplies independently reviewed approval records.
"""
from __future__ import annotations
from datetime import date,datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo
import json
import os

from .day_snapshot_publisher import validate

JST=ZoneInfo("Asia/Tokyo")


def write_day_snapshot(store: Path, payload: dict, approval: dict, *,
                       today: date | None=None) -> Path:
    today=today or datetime.now(JST).date()
    checked=validate(payload,today=today,approval=approval)
    if checked.get("redistribution_authorized") is not True:
        raise ValueError("publication rights not approved")
    store.mkdir(parents=True,exist_ok=True)
    destination=store / (today.isoformat()+".json")
    serialized=(json.dumps(checked,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
    if len(serialized)>6_000_000:
        raise ValueError("snapshot exceeds size limit")
    with NamedTemporaryFile(mode="wb",dir=store,prefix=".snapshot-",delete=False) as handle:
        temp=Path(handle.name)
        try:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    os.replace(temp,destination)
    return destination


def read_current_snapshot(store: Path, *, today: date | None=None) -> dict:
    today=today or datetime.now(JST).date()
    path=store / (today.isoformat()+".json")
    if path.is_symlink() or not path.is_file() or path.stat().st_size>6_000_000:
        raise ValueError("no current approved snapshot")
    data=json.loads(path.read_text(encoding="utf-8"))
    if data.get("date_jst")!=today.isoformat() or data.get("redistribution_authorized") is not True:
        raise ValueError("stale or unapproved snapshot")
    return data
