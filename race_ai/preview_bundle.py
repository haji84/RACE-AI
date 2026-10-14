"""Prepare a static Vercel Preview bundle from a separately approved day snapshot.

Never uploads or fetches external data. The operator must deploy the resulting
directory only to a protected Preview environment. Source rights evidence must
be verified outside this tool; it is not inferred from JSON flags.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

from .day_snapshot_publisher import validate

JST = ZoneInfo("Asia/Tokyo")
STATIC = ("index.html", "app.js", "style.css", "ui-core.js", "money.js")


def package_preview(web: Path, snapshot: Path, approval: Path, output: Path, *,
                    today=None):
    today = today or datetime.now(JST).date()
    if output.resolve() == web.resolve() or output.resolve().is_relative_to(web.resolve()):
        raise ValueError("output must be separate from source web directory")
    if snapshot.stat().st_size > 6_000_000:
        raise ValueError("snapshot exceeds limit")
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    evidence = json.loads(approval.read_text(encoding="utf-8"))
    checked = validate(payload, today=today, approval=evidence)
    if not checked.get("redistribution_authorized"):
        raise ValueError("redistribution not approved")
    if output.exists():
        raise ValueError("output already exists; do not overwrite a live bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".race-preview-") as tmp:
        stage = Path(tmp) / "bundle"
        stage.mkdir()
        for name in STATIC:
            source = web / name
            if not source.is_file() or source.is_symlink():
                raise ValueError("missing or linked web asset: " + name)
            shutil.copyfile(source, stage / name)
        data = stage / "data"
        data.mkdir()
        (data / "today.json").write_text(
            json.dumps(checked, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8")
        stage.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser()
    for arg in ("web", "snapshot", "approval", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    try:
        package_preview(args.web, args.snapshot, args.approval, args.output)
    except (ValueError, OSError, TypeError) as exc:
        print("SAFE_STOP: " + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
