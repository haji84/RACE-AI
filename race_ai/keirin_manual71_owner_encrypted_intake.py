"""Private, SHA-pinned intake of the owner's Nov-17 71-race forecast.

The sealed envelope uses the already pinned PR102 RSA-OAEP/AES-256-GCM
helper. The public repository may contain implementation and tests, NEVER
raw forecast files or owner RSA private key. This is NOT a new source/forecast
authority, and does not grant result-provider rights. No network requests.
"""
from __future__ import annotations

import base64
import binascii
from hashlib import sha256, sha1
import importlib.util
import json
import os
from pathlib import Path
import zlib

SCHEMA = "RACE_AI_KEIRIN_OWNER_MANUAL71_BUNDLE_V1"
AAD = "RACE_AI_PRIVATE_KEIRIN:2026-11-17:MANUAL71_FORECAST_V1"
EXPECTED = {
    "forecast_v3.json": "4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68",
    "baseline_v2.json": "3bdb6930812cd00035f5591cc4a349aa171d49a1f1a709c44a2f2b990c233c59",
    "categories.html": "2c0ec7ed2f8b77b81e026ae162ba4b185abcc4d1983e624d08eef7e61c1cf11c",
    "template.html": "2c0ec7ed2f8b77b81e026ae162ba4b185abcc4d1983e624d08eef7e61c1cf11c",
}
MAX_FILE = 1_000_000


class ManualBundleError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ManualBundleError(code)


def sha(raw):
    return sha256(raw).hexdigest()


def pinned_helper(path):
    """Caller supplies checked-out, immutable PR102 path, not arbitrary code."""
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and p.name ==
         "keirin_private_sealed_payload.py", "PINNED_RSA_HELPER_REQUIRED")
    raw = p.read_bytes()
    need(len(raw) <= 15000 and sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest() == "2cf67ff4b297ad3711c1a8d03de9db966bf9096b",
         "PINNED_RSA_HELPER_BLOB_SHA_CHANGED")
    spec = importlib.util.spec_from_file_location("_pr102_private_seal", str(p))
    need(spec is not None and spec.loader is not None,
         "PINNED_RSA_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    need(callable(getattr(module, "seal_json", None)) and
         callable(getattr(module, "open_sealed_json", None)),
         "PINNED_RSA_HELPER_INCOMPLETE")
    return module


def package_files(files, *, expected=EXPECTED):
    """Validate REAL byte-identical originals; no guessed or rebuilt picks."""
    need(type(files) is dict and set(files) == set(expected),
         "FOUR_ORIGINAL_FILES_REQUIRED")
    output = {}
    for name, expected_sha in expected.items():
        raw = files[name]
        need(type(raw) is bytes and 0 < len(raw) <= MAX_FILE and
             sha(raw) == expected_sha, "PREDICTION_ORIGINAL_SHA_MISMATCH")
        output[name] = {
            "sha256": expected_sha,
            "bytes": len(raw),
            "zlib_b64": base64.b64encode(zlib.compress(raw, level=9)).decode("ascii"),
        }
    return {"schema": SCHEMA, "day_jst": "2026-11-17",
            "files": output, "raw_file_count": 4,
            "live_result_authenticated": False,
            "manual_predictions_are_pr71_models": False}


def _unzlib_limited(encoded):
    need(type(encoded) is str and 0 < len(encoded) <= 2_000_000,
         "BUNDLE_FILE_ENCODING_INVALID")
    try:
        raw = base64.b64decode(encoded, validate=True)
        stream = zlib.decompressobj()
        data = stream.decompress(raw, MAX_FILE + 1)
        need(stream.eof and not stream.unconsumed_tail and
             not stream.unused_data and len(data) <= MAX_FILE,
             "BUNDLE_DECOMPRESSION_BOUNDS")
        data += stream.flush()
        need(len(data) <= MAX_FILE, "BUNDLE_DECOMPRESSION_BOUNDS")
        return data
    except (binascii.Error, zlib.error):
        raise ManualBundleError("BUNDLE_COMPRESSION_INVALID") from None


def verify_payload(payload, *, expected=EXPECTED):
    need(type(payload) is dict and set(payload) == {
        "schema", "day_jst", "files", "raw_file_count",
        "live_result_authenticated", "manual_predictions_are_pr71_models"
    } and payload["schema"] == SCHEMA and
         payload["day_jst"] == "2026-11-17" and
         payload["raw_file_count"] == 4 and
         payload["live_result_authenticated"] is False and
         payload["manual_predictions_are_pr71_models"] is False,
         "INVALID_MANUAL71_BUNDLE_SCHEMA")
    rows = payload["files"]
    need(type(rows) is dict and set(rows) == set(expected),
         "BUNDLE_FILE_SET_INVALID")
    unpacked = {}
    for name, digest in expected.items():
        item = rows[name]
        need(type(item) is dict and set(item) == {
            "sha256", "bytes", "zlib_b64"
        } and item["sha256"] == digest and
             type(item["bytes"]) is int and 0 < item["bytes"] <= MAX_FILE,
             "BUNDLE_FILE_META_INVALID")
        raw = _unzlib_limited(item["zlib_b64"])
        need(len(raw) == item["bytes"] and sha(raw) == digest,
             "BUNDLE_ORIGINAL_SHA_MISMATCH")
        unpacked[name] = raw
    return unpacked


def make_envelope(raw_files, *, public_key, helper_path,
                  expected=EXPECTED):
    """Sealing is owner-side. Returns a private-content ciphertext envelope."""
    helper = pinned_helper(helper_path)
    payload = package_files(raw_files, expected=expected)
    return helper.seal_json(payload, public_key, aad=AAD)


def open_envelope(envelope, *, private_key, helper_path,
                  expected=EXPECTED):
    """Owner-authorized private runner only; never logs decrypted source."""
    helper = pinned_helper(helper_path)
    try:
        payload = helper.open_sealed_json(envelope, private_key, aad=AAD)
    except Exception:
        raise ManualBundleError("BUNDLE_AES_OR_RSA_AUTHENTICATION_FAILED") from None
    return verify_payload(payload, expected=expected)


def stage_private(raw_files, *, private_folder, public_workspace, expected=None):
    """Create four 0600 files atomically in a 0700 private temp directory.

    Caller MUST first verify its trusted main-runner context, and MUST supply
    an owner-private path outside GITHUB_WORKSPACE.
    """
    expected = EXPECTED if expected is None else expected
    base = Path(private_folder)
    workspace = Path(public_workspace).resolve()
    need(base.is_absolute() and not base.exists() and not base.is_symlink() and
         workspace != base.resolve() and workspace not in base.resolve().parents,
         "PRIVATE_OUTPUT_NOT_ISOLATED")
    need(type(raw_files) is dict and set(raw_files) == set(expected),
         "BUNDLE_FILE_SET_INVALID")
    for key, raw in raw_files.items():
        need(type(raw) is bytes and sha(raw) == expected[key],
             "PREDICTION_ORIGINAL_SHA_MISMATCH")
    made = []
    try:
        base.mkdir(mode=0o700, parents=False)
        base.chmod(0o700)
        for name in expected:
            target = base / name
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(target, flags, 0o600)
            made.append(target)
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw_files[name])
                handle.flush()
                os.fsync(handle.fileno())
        return {"state": "OWNER_MANUAL71_PRIVATE_SOURCE_STAGED",
                "private_files": 4,
                "forecast_sha256": expected["forecast_v3.json"],
                "result_source_verified": False}
    except Exception:
        for target in made:
            target.unlink(missing_ok=True)
        if base.exists():
            base.rmdir()
        raise
