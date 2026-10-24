"""Serve the exact audited historical aggregate, never replay or acquire sources.

This pin identifies one published evidence artifact. Adding observations requires
a separately audited snapshot and an explicit code change, not a request query.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path

REPORT_SHA256 = '77c93e07046721de8cead6ef21515f7d190601db63b92abfaee82c43f95e20d6'
AUDITED_AT = datetime.fromisoformat('2026-10-16T02:16:37.318964+00:00')
REPORT_PATH = Path(__file__).resolve().parent / 'data/archived-cohort-20261016-ce380fb6.json'


class SnapshotUnavailable(ValueError):
    """The pinned artifact or its already completed audit is unavailable."""


def load_snapshot(*, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None or now < AUDITED_AT:
        raise SnapshotUnavailable()
    try:
        raw = REPORT_PATH.read_bytes()
    except OSError as exc:
        raise SnapshotUnavailable() from exc
    # Exact bytes authenticate the original JSON, its research gates and clocks.
    # This is artifact integrity, not a new replay of the original probability files.
    if len(raw) != 7173 or hashlib.sha256(raw).hexdigest() != REPORT_SHA256:
        raise SnapshotUnavailable()
    return raw
