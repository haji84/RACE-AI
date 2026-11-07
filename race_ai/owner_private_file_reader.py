"""Owner-local read-only original-byte reader for PR72's protected_reader.

This is a storage reader, NOT permission attestation, a signed-time receipt,
a forecast validator, or a formal scorer. No network calls or file writes.
Owner-controlled manifest and root must stay outside public GitHub.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

MAX_WIRE_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class OwnerReadbackError(ValueError):
    """Fail closed without leaking private material."""


def _fail():
    raise OwnerReadbackError("OWNER_PRIVATE_READBACK_REJECTED") from None


def _protected_root(root):
    p = Path(root).expanduser()
    try:
        if not p.is_absolute() or not p.is_dir() or p.is_symlink():
            _fail()
        p = p.resolve(strict=True)
        for parent in (p, *p.parents):
            if (parent / ".git").exists():
                _fail()
    except OSError:
        _fail()
    return p


def _filename(value):
    if (type(value) is not str or not 1 <= len(value) <= 240 or
            "\\" in value or "\x00" in value or ":" in value):
        _fail()
    p = Path(value)
    if (p.is_absolute() or not p.parts or
            any(v in ("", ".", "..") for v in p.parts) or ".git" in p.parts):
        _fail()
    return p


def _original_bytes(root, relative):
    path = root / relative
    try:
        for parent in (path.parent, *path.parent.parents):
            if parent == root.parent:
                break
            if parent.is_symlink():
                _fail()
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_WIRE_BYTES:
            _fail()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    opened.st_dev != before.st_dev or opened.st_ino != before.st_ino or
                    opened.st_size != before.st_size or opened.st_mtime_ns != before.st_mtime_ns):
                _fail()
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_WIRE_BYTES + 1)
            after_open = os.fstat(fd)
        finally:
            os.close(fd)
        after = path.lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if (len(raw) != before.st_size or identity(before) != identity(opened) or
                identity(before) != identity(after_open) or identity(before) != identity(after)):
            _fail()
        return raw
    except (OSError, ValueError):
        _fail()


class OwnerPrivateFileReader:
    """Inject this instance as protected_reader to PR72's receipt linker.

    manifest is an OWNER-PRIVATE mapping:
      private_ref -> (relative_filename, original_wire_sha256).
    It does not authorize a forecast, a data source or a cutoff.
    """

    def __init__(self, root, manifest):
        self.root = _protected_root(root)
        if type(manifest) is not dict or not 1 <= len(manifest) <= 100000:
            _fail()
        self.manifest = {}
        seen = set()
        for ref, descriptor in manifest.items():
            if type(ref) is not str or not _REF.fullmatch(ref):
                _fail()
            if (type(descriptor) not in (tuple, list) or len(descriptor) != 2 or
                    type(descriptor[1]) is not str or not _SHA.fullmatch(descriptor[1])):
                _fail()
            relative = _filename(descriptor[0])
            if str(relative) in seen:
                _fail()
            seen.add(str(relative))
            self.manifest[ref] = (relative, descriptor[1])

    def __call__(self, private_ref):
        if type(private_ref) is not str or private_ref not in self.manifest:
            _fail()
        relative, expected = self.manifest[private_ref]
        raw = _original_bytes(self.root, relative)
        if not hmac.compare_digest(sha256(raw).hexdigest(), expected):
            _fail()
        return raw


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def inspect_reference_bundle(reader, private_ref):
    """Research bundle only, never derives per-race original SHA/receipt."""
    raw = reader(private_ref)
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                         parse_constant=lambda _: _fail())
        if (type(obj) is not dict or set(obj) !=
                {"version", "stamp_jst", "calibrated", "officially_frozen", "core_sha256", "races"} or
                type(obj["calibrated"]) is not bool or type(obj["officially_frozen"]) is not bool or
                type(obj["version"]) is not str or not obj["version"] or
                type(obj["stamp_jst"]) is not str or
                type(obj["core_sha256"]) is not str or not _SHA.fullmatch(obj["core_sha256"]) or
                type(obj["races"]) is not list or not 1 <= len(obj["races"]) <= 100000):
            _fail()
        seen_ids = set()
        for race in obj["races"]:
            if (type(race) is not dict or set(race) != {"id", "ranked", "total"} or
                    type(race["id"]) is not str or not re.fullmatch(r"[0-9]{12}", race["id"]) or
                    race["id"] in seen_ids or type(race["ranked"]) is not list or
                    not 1 <= len(race["ranked"]) <= 8 or
                    type(race["total"]) not in (int, float) or not math.isfinite(race["total"])):
                _fail()
            seen_ids.add(race["id"])
            seen_picks = set()
            for ranked in race["ranked"]:
                if (type(ranked) is not dict or set(ranked) != {"pick", "p"} or
                        type(ranked["pick"]) is not str or
                        type(ranked["p"]) not in (int, float) or
                        not math.isfinite(ranked["p"]) or not 0 <= ranked["p"] <= 1):
                    _fail()
                parts = ranked["pick"].split("-")
                if (len(parts) != 3 or
                        any(not re.fullmatch(r"[1-9]", s) for s in parts) or
                        len(set(parts)) != 3 or ranked["pick"] in seen_picks):
                    _fail()
                seen_picks.add(ranked["pick"])
    except (UnicodeError, TypeError, ValueError, RecursionError):
        _fail()
    return {
        "schema": "RACE_AI_OWNER_PRIVATE_REFERENCE_READBACK_V1",
        "status": "OWNER_LOCAL_BUNDLE_BYTES_VERIFIED_RESEARCH_ONLY",
        "whole_bundle_sha256": sha256(raw).hexdigest(),
        "whole_bundle_bytes": len(raw),
        "reference_races": len(obj["races"]),
        "bundle_declares_officially_frozen": obj["officially_frozen"],
        "bundle_declares_calibrated": obj["calibrated"],
        "per_race_original_sha_verified": False,
        "external_pre_cutoff_receipts_verified": False,
        "official_source_rights_verified": False,
        "formal_hit_at_8_all": None,
        "forecast_originals_modified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        reader = OwnerPrivateFileReader(
            args.root, {"owner-research-bundle": (args.file, args.expected_sha256)})
        result = inspect_reference_bundle(reader, "owner-research-bundle")
    except OwnerReadbackError:
        print(json.dumps({"status": "REJECTED",
                          "reason": "OWNER_PRIVATE_READBACK_REJECTED",
                          "formal_hit_at_8_all": None}), file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2  # Research-only success must never be confused with formal admission.


if __name__ == "__main__":
    raise SystemExit(main())
