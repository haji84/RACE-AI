"""Opt-in OFFLINE NAR downloaded race ZIP / CSV intake.

The ZIP may contain historical payback CSV. Only racelist/horselist members
are read. No collection, model inference, actual cutoff proof, GitHub post,
or source-rights grant is performed here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from .nar_official_csv_adapter import stage_nar_csv, NarFormatError, MAX_BYTES
from .permissioned_source_delivery import (
    PermissionPolicy, SourceDeliveryError, read_json_bytes, _private_write
)


def unpack_nar_race_zip(data: bytes, *, event_date_jst: str):
    if type(data) is not bytes or not 0 < len(data) <= MAX_BYTES:
        raise NarFormatError("bounded official race ZIP required")
    stem = event_date_jst.replace("-", "")
    required = {stem + "_racelist.csv", stem + "_horselist.csv"}
    allowed = required | {stem + "_payback.csv"}
    extracted = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.infolist()
            if not 2 <= len(names) <= 3:
                raise NarFormatError("NAR ZIP archive member count invalid")
            seen = set()
            for info in names:
                if (info.filename not in allowed or info.filename in seen
                    or info.flag_bits & 1 or info.is_dir()
                    or info.file_size > MAX_BYTES or info.file_size < 0):
                    raise NarFormatError("unsafe/unknown/duplicate ZIP member")
                mode = (info.external_attr >> 16) & 0xffff
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise NarFormatError("nonregular ZIP member prohibited")
                seen.add(info.filename)
                if info.filename in required:
                    with archive.open(info) as f:
                        content = f.read(MAX_BYTES + 1)
                    if len(content) > MAX_BYTES or len(content) != info.file_size:
                        raise NarFormatError("ZIP member inflated beyond limit")
                    extracted[info.filename] = content
            if required != set(extracted):
                raise NarFormatError("required official race CSV members missing")
    except (zipfile.BadZipFile, EOFError, OSError, RuntimeError) as exc:
        raise NarFormatError("corrupt or unsupported official race ZIP") from exc
    return extracted[stem + "_racelist.csv"], extracted[stem + "_horselist.csv"]


def _read_bounded_local(path):
    """Bound files BEFORE materializing them in process memory."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise NarFormatError("local input unavailable") from exc
    if len(raw) > MAX_BYTES:
        raise NarFormatError("local input exceeds allowed byte budget")
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline, rights-gated NAR CSV preflight only")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--zip", dest="archive", help="operator-provided NAR race ZIP")
    inputs.add_argument("--racelist", help="extracted NAR racelist CSV")
    parser.add_argument("--horselist", help="extracted NAR horselist CSV (required with --racelist)")
    parser.add_argument("--policy", required=True, help="separately reviewed HMAC-authenticated policy")
    parser.add_argument("--source-ref", required=True, help="exact independently reviewed official source reference")
    parser.add_argument("--rights-ref", required=True)
    parser.add_argument("--observed-at", required=True, help="operator-reported capture time; not trusted server time")
    parser.add_argument("--event-date", required=True, help="YYYY-MM-DD JST")
    parser.add_argument("--venue", required=True)
    parser.add_argument("--race-number", required=True, type=int)
    parser.add_argument("--encoding", choices=("utf-8-sig", "cp932"), required=True)
    parser.add_argument("--header-mode", choices=("present", "absent"), required=True)
    parser.add_argument("--output", required=True, help="new PRIVATE file outside Git; must not exist")
    parser.add_argument("--key-env", default="RACE_AI_SOURCE_REVIEW_KEY")
    args = parser.parse_args(argv)
    try:
        if (args.archive and args.horselist) or (args.racelist and not args.horselist):
            raise NarFormatError("CSV input pair or ZIP input required, not mixed")
        now = datetime.now(timezone.utc).isoformat()
        doc = read_json_bytes(_read_bounded_local(args.policy))
        reviewer_key = os.environ.get(args.key_env, "").encode("utf-8")
        policy = PermissionPolicy(doc, reviewer_key, at=now)
        if args.archive:
            racelist, horselist = unpack_nar_race_zip(
                _read_bounded_local(args.archive),event_date_jst=args.event_date)
        else:
            racelist = _read_bounded_local(args.racelist)
            horselist = _read_bounded_local(args.horselist)
        stage = stage_nar_csv(
            racelist, horselist, policy, at=now,
            observed_at=args.observed_at, source_ref=args.source_ref,
            rights_ref=args.rights_ref, event_date_jst=args.event_date,
            venue=args.venue, race_no=args.race_number,
            encoding=args.encoding, has_header=args.header_mode=="present")
        _private_write(args.output, stage)
        # No participant names, credentials or protected raw material in logs.
        print(json.dumps({"race_id":stage["race_id"],"status":stage["status"],
                          "stage_sha256":stage["stage_sha256"],
                          "model_ready":False,"forecast_frozen":False},ensure_ascii=False))
        return 0
    except (NarFormatError, SourceDeliveryError, KeyError, OSError,
            TypeError, ValueError, zipfile.LargeZipFile) as exc:
        print("NAR_ADAPTER_BLOCKED: " + str(exc),file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
