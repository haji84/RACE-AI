"""Owner-approved Nov 17 manual-71 ciphertext -> private Actions intake.

Runs only on the EXISTING haji84/RACE-AI protected main scheduler/dispatch.
Reuses the existing video RSA secret and immutable PR102 envelope helper.
No provider GET; no new secret; no auto betting; no plaintext source in logs.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from race_ai.keirin_manual71_owner_encrypted_intake import (
    EXPECTED, ManualBundleError, open_envelope, stage_private,
)

# SHA-256 of the exact 185773-byte, owner-authorized sealed attachment.
CIPHER_FILE_SHA256 = "164bd98caf06deb2308626d0f6343c074db9e85b9517378ac60119af21b3375e"
CIPHER_PAYLOAD_SHA256 = "d04e070ef10e92a0276f3a3d1633ebf0fc4d075bf3c9d206c5f1fc9a76315a4f"
# DER SubjectPublicKeyInfo of the existing PR102 RSA public key.
# Evaluated separately from the secret; prevents unintended cross-key reuse.
PUBLIC_SPKI_SHA256 = "1963d13558d115ce261f224b97d385bd09c65a70c91fb23237f91aa9840bb3a1"
CIPHER_RELATIVE = Path("docs/evidence/2026-11-17/keirin_owner_manual71_20261117_sealed_v1.json")
REPO = "haji84/RACE-AI"
REPO_ID = "1416489937"


def require_owner_runner(env):
    return (env.get("GITHUB_ACTIONS") == "true" and
            env.get("GITHUB_REPOSITORY") == REPO and
            env.get("GITHUB_REPOSITORY_ID") == REPO_ID and
            env.get("GITHUB_REF") == "refs/heads/main" and
            env.get("GITHUB_EVENT_NAME") in {"schedule", "workflow_dispatch"})


def _duplicates_reject(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ManualBundleError("DUPLICATE_ENVELOPE_KEY")
        obj[k] = v
    return obj


def _rsa_matching_public_key(private_pem, *, expected_public_sha=PUBLIC_SPKI_SHA256):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if type(private_pem) is not str or not private_pem or len(private_pem) > 10000:
        raise ManualBundleError("OWNER_RSA_SECRET_NOT_CONFIGURED")
    try:
        k = serialization.load_pem_private_key(private_pem.encode("utf-8"),
                                               password=None)
        if not isinstance(k, rsa.RSAPrivateKey) or k.key_size < 3072:
            raise ManualBundleError("OWNER_RSA_KEY_TYPE_REJECTED")
        der = k.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo)
    except (ValueError, TypeError):
        raise ManualBundleError("OWNER_RSA_SECRET_INVALID") from None
    if sha256(der).hexdigest() != expected_public_sha:
        raise ManualBundleError("OWNER_RSA_PUBLIC_KEY_NOT_PINNED")
    return private_pem.encode("utf-8")


def restore_existing_owner_bundle(*, env, workspace, helper, private_dir,
                                  expected_file_sha=CIPHER_FILE_SHA256,
                                  expected_cipher_sha=CIPHER_PAYLOAD_SHA256,
                                  expected_public_sha=PUBLIC_SPKI_SHA256,
                                  expected_originals=None):
    """Caller must run in trusted main; never create an unencrypted public file.

    No JSON/payout/rider data leaves this function. Absence of Secret => HOLD.
    """
    if not require_owner_runner(env):
        return {"state": "HOLD_NO_TRUSTED_MAIN_OWNER_RUN",
                "source_files": 0, "real_result_authenticated": False}
    if not env.get("RACE_AI_KEIRIN_PRIVATE_RSA_PEM"):
        return {"state": "HOLD_EXISTING_RSA_SECRET_UNCONFIGURED",
                "source_files": 0, "real_result_authenticated": False}
    ws = Path(workspace).resolve()
    cipher = ws / CIPHER_RELATIVE
    if (not ws.is_absolute() or not cipher.is_file() or cipher.is_symlink() or
            cipher.resolve() != ws / CIPHER_RELATIVE):
        raise ManualBundleError("SEALED_OWNER_BUNDLE_NOT_IN_REPOSITORY")
    raw = cipher.read_bytes()
    if not (0 < len(raw) <= 400000 and sha256(raw).hexdigest() == expected_file_sha):
        raise ManualBundleError("SEALED_OWNER_BUNDLE_SHA_CHANGED")
    try:
        envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates_reject)
    except (UnicodeError, ValueError):
        raise ManualBundleError("SEALED_OWNER_BUNDLE_JSON_INVALID") from None
    if (type(envelope) is not dict or
            envelope.get("ciphertext_sha256") != expected_cipher_sha or
            envelope.get("plaintext_embedded") is not False or
            envelope.get("source_is_private") is not True):
        raise ManualBundleError("SEALED_OWNER_BUNDLE_CIPHER_MISMATCH")
    key = _rsa_matching_public_key(
        env["RACE_AI_KEIRIN_PRIVATE_RSA_PEM"],
        expected_public_sha=expected_public_sha)
    expected = EXPECTED if expected_originals is None else expected_originals
    decoded = open_envelope(envelope, private_key=key, helper_path=helper,
                            expected=expected)
    staged = stage_private(decoded, private_folder=private_dir,
                           public_workspace=ws, expected=expected)
    return {"state": "OWNER_MANUAL71_PRIVATE_SOURCE_STAGED",
            "source_files": staged["private_files"],
            "forecast_sha256": staged["forecast_sha256"],
            "cipher_file_sha256": expected_file_sha,
            "result_source_verified": False,
            "real_result_authenticated": False}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--helper", required=True)
    ap.add_argument("--private-dir", required=True)
    args = ap.parse_args(argv)
    try:
        result = restore_existing_owner_bundle(
            env=os.environ, workspace=args.workspace, helper=args.helper,
            private_dir=args.private_dir)
        # Public log: state and cryptographic digest only, no plaintext.
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ManualBundleError, OSError, ValueError, TypeError):
        print('{"state":"HOLD_OWNER_MANUAL71_PRIVATE_INTAKE_REJECTED","source_files":0}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
