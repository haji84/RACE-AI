"""Prepare an authorized official B program for preview publishing.

Offline only. This module does not download data, authorize rights, or deploy.
The external worker must supply a verified extracted official B text and an
independently reviewed permission record before calling the publisher.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .official_b_snapshot_adapter import normalize_b_file
from .day_snapshot_publisher import publish


def prepare(*, source: Path, approval: Path, output: Path, day: date,
            source_url: str, observed_at: str) -> None:
    # Build in memory, never persist unapproved derived data.
    report = normalize_b_file(source, day=day, source_url=source_url,
                              observed_at=observed_at)
    # Reuse the publisher's full validation before writing to the target.
    # A temporary file is used only inside the same protected workspace.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        normalized = Path(tmp) / "normalized.json"
        normalized.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        publish(normalized, approval, output, today=day)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--observed-at", required=True)
    args = parser.parse_args()
    try:
        prepare(source=args.source, approval=args.approval, output=args.output,
                day=date.fromisoformat(args.date), source_url=args.source_url,
                observed_at=args.observed_at)
    except (ValueError, OSError, TypeError) as exc:
        print("SAFE_STOP: " + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
