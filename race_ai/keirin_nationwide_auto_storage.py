"""Owner-private RSA-OAEP-SHA256 + AES-256-GCM seal for automatic A/B.

A and B are separate authenticated ciphertexts, create-only and 0600,
inside an existing 0700 owner-private folder. The public code holds only a
public key fingerprint; private keys and racecard facts stay outside Git.

The matching verifier can be run by a *different* GitHub runner on ciphertext
alone. Ciphertext readback does NOT prove RSA decryption or independent
source/official result authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import base64
import json
import os
import stat
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import keirin_nationwide_auto_generator as model
from . import keirin_confidence as confidence

SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_AUTO_AB_ENCRYPTED_V1"
PINNED_OWNER_SPKI_SHA256 = (
    "1963d13558d115ce261f224b97d385bd09c65a70c91fb23237f91aa9840bb3a1"
)
MAX_INPUT_BYTES = 2_000_000
MAX_CIPHER_BYTES = 2_000_000


class AutoSealError(ValueError):
    pass


def need(test, reason):
    if not test:
        raise AutoSealError(reason)


def sha(value):
    return sha256(value).hexdigest()


def checked_public_key(data, *, expected_spki_sha=None):
    """An owner's existing RSA public key, not a new assistant-generated key."""
    if expected_spki_sha is None:
        expected_spki_sha = PINNED_OWNER_SPKI_SHA256
    need(type(data) is bytes and len(data) <= 20_000,
         "OWNER_RSA_PUBLIC_KEY_BYTES_REQUIRED")
    try:
        key = serialization.load_pem_public_key(data)
    except (ValueError, TypeError):
        raise AutoSealError("OWNER_PUBLIC_PEM_INVALID") from None
    need(isinstance(key, rsa.RSAPublicKey) and key.key_size >= 3072,
         "OWNER_RSA_MINIMUM_3072_BITS")
    der = key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    need(sha(der) == expected_spki_sha, "OWNER_PUBLIC_SPKI_PIN_MISMATCH")
    return key


def _arm_encrypt(key, prediction, snapshot, role, record_id, assessment=None):
    payload = {
        "schema": "RACE_AI_KEIRIN_NATIONWIDE_AB_PRIVATE_ARM_V1",
        "role": role,
        "race_id": record_id,
        "prediction": prediction[role],
        "generated_at": prediction["generated_at"],
        "pre_race_facts": snapshot,
        "pre_race_facts_sha256": prediction["source_facts_sha256"],
        "prediction_sha256": prediction["prediction_sha256"],
        "official_result_not_included": True,
    }
    if assessment is not None:
        payload["confidence_assessment"] = assessment
    raw = model.canonical(payload) + b"\n"
    need(len(raw) < MAX_INPUT_BYTES, "PRIVATE_ARM_TOO_LARGE")
    compressed = zlib.compress(raw, level=9)
    aes = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    aad = f"RACE_AI_AUTO_AB_V1|{record_id}|{role}|ZLIB".encode("ascii")
    cipher = AESGCM(aes).encrypt(nonce, compressed, aad)
    wrapped = key.encrypt(
        aes, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                          algorithm=hashes.SHA256(), label=None))
    return {
        "aad_ascii": aad.decode("ascii"),
        "aesgcm_nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "rsa_oaep_sha256_wrapped_key_b64": base64.b64encode(wrapped).decode("ascii"),
        "ciphertext_b64": base64.b64encode(cipher).decode("ascii"),
        "ciphertext_sha256": sha(cipher),
        "plaintext_sha256": sha(raw),
        "compressed_sha256": sha(compressed),
    }


def validate_cipher(envelope):
    """Public, independent SHA readback. No owner secret is needed."""
    need(type(envelope) is dict and envelope.get("schema") == SCHEMA,
         "AUTO_CIPHER_SCHEMA")
    rid = envelope.get("race_id")
    need(type(rid) is str and model.VENUE.fullmatch(rid) and
         envelope.get("owner_RSA_SPKI_sha256") == PINNED_OWNER_SPKI_SHA256 and
         envelope.get("original_source_sha256") and
         envelope.get("official_result_included") is False and
         envelope.get("official_cutoff_independently_attested") is False,
         "AUTO_CIPHER_PROVENANCE_INVALID")
    need(type(envelope.get("generated_at")) is str and
         type(envelope.get("sealed_at")) is str and
         model.when(envelope["generated_at"]) <= model.when(envelope["sealed_at"]) and
         (model.when(envelope["published_cutoff_at"]) -
          model.when(envelope["sealed_at"])).total_seconds() >= 65,
         "AUTO_CIPHER_PUBLISHED_CUTOFF_TIME_INVALID")
    sigs = set()
    for role in ("A", "B"):
        row = envelope.get(role)
        need(type(row) is dict and set(row) == {
            "aad_ascii", "aesgcm_nonce_b64",
            "rsa_oaep_sha256_wrapped_key_b64",
            "ciphertext_b64", "ciphertext_sha256", "plaintext_sha256",
            "compressed_sha256"},
             "AUTO_CIPHER_ROLE_FIELDS_INVALID")
        need(row["aad_ascii"] == f"RACE_AI_AUTO_AB_V1|{rid}|{role}|ZLIB",
             "AUTO_CIPHER_ROLE_AAD_MISMATCH")
        try:
            nonce = base64.b64decode(row["aesgcm_nonce_b64"], validate=True)
            wrap = base64.b64decode(
                row["rsa_oaep_sha256_wrapped_key_b64"], validate=True)
            cipher = base64.b64decode(row["ciphertext_b64"], validate=True)
        except (ValueError, KeyError):
            raise AutoSealError("AUTO_CIPHER_B64_INVALID") from None
        need(len(nonce) == 12 and len(wrap) >= 384 and
             16 < len(cipher) < MAX_CIPHER_BYTES and
             sha(cipher) == row["ciphertext_sha256"] and
             len(row["plaintext_sha256"]) == 64 and
             len(row["compressed_sha256"]) == 64,
             "AUTO_CIPHER_SHA_OR_LENGTH_INVALID")
        sigs.add((row["aesgcm_nonce_b64"],
                  row["rsa_oaep_sha256_wrapped_key_b64"]))
    need(len(sigs) == 2, "AUTO_A_B_MUST_USE_DISTINCT_NONCE_AND_KEY")
    return envelope


def seal_once(*, snapshot, prediction, public_key_pem, path, sealed_at,
              expected_spki_sha=None, confidence_assessment=None):
    """No overwrite. Only an already-existing, private 0700 destination."""
    model.validate_snapshot(snapshot, computed_at=prediction["generated_at"])
    need(prediction["schema"] == model.PREDICTION and
         prediction["race_id"] == snapshot["race_id"] and
         prediction["source_facts_sha256"] == model.digest(snapshot) and
         prediction["prediction_sha256"] == model.digest({
             k:v for k,v in prediction.items() if k != "prediction_sha256"}),
         "PREDICTION_SOURCE_OR_DIGEST_MODIFIED")
    at = model.when(sealed_at)
    need(model.when(prediction["generated_at"]) <= at and
         (model.when(snapshot["published_cutoff_at"]) - at).total_seconds() >= 65,
         "SEAL_AFTER_OR_TOO_CLOSE_TO_PUBLISHED_CUTOFF")
    assessment = None
    if confidence_assessment is not None:
        assessment = confidence.checked_assessment(confidence_assessment,
            snapshot=snapshot, baseline=prediction, sealed_at=sealed_at)
    dest = Path(path)
    folder = dest.parent
    need(folder.is_dir() and not folder.is_symlink() and
         stat.S_IMODE(folder.stat().st_mode) == 0o700 and
         not dest.exists() and not dest.is_symlink() and
         not dest.name.startswith("."),
         "PRIVATE_CREATE_ONCE_DIRECTORY_REQUIRED")
    if expected_spki_sha is None:
        expected_spki_sha = PINNED_OWNER_SPKI_SHA256
    pub = checked_public_key(public_key_pem, expected_spki_sha=expected_spki_sha)
    # Research schema pins the existing owner fingerprint. Other keys may
    # be tested only by monkeypatching the pinned constant in source-free CI.
    need(expected_spki_sha == PINNED_OWNER_SPKI_SHA256,
         "OWNER_RSA_KEY_NOT_THE_REGISTERED_RESEARCH_KEY")
    info = {
        "schema": SCHEMA,
        "race_id": snapshot["race_id"],
        "generated_at": prediction["generated_at"],
        "sealed_at": sealed_at,
        "published_cutoff_at": snapshot["published_cutoff_at"],
        "original_source_sha256": prediction["source_facts_sha256"],
        "owner_RSA_SPKI_sha256": expected_spki_sha,
        "official_cutoff_independently_attested": False,
        "official_result_included": False,
        "cross_runner_RSA_decryption_attested": False,
        "research_only": True,
        "A": _arm_encrypt(pub, prediction, snapshot, "A", snapshot["race_id"], assessment),
        "B": _arm_encrypt(pub, prediction, snapshot, "B", snapshot["race_id"], assessment),
    }
    validate_cipher(info)
    data = model.canonical(info) + b"\n"
    need(len(data) < MAX_CIPHER_BYTES, "AUTO_CIPHER_OUTPUT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(dest, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        need(dest.read_bytes() == data,
             "PRIVATE_SEAL_SAME_JOB_READBACK_MISMATCH")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return {"race_id":snapshot["race_id"],
            "state":"PRIVATE_CIPHER_CREATE_ONCE_LOCAL_READBACK",
            "cipher_sha256":sha(data),"A_cipher_sha256":info["A"]["ciphertext_sha256"],
            "B_cipher_sha256":info["B"]["ciphertext_sha256"],
            "sealed_at":sealed_at,
            "independent_runner_readback":False,
            "independent_RSA_decryption_readback":False,
            "official_result_settled":False}


def readback_file(path, *, expected_sha):
    """Independent runner can check exact immutable file bytes, ciphertext only."""
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and p.stat().st_size < MAX_CIPHER_BYTES,
         "AUTO_CIPHER_FILE_NOT_FOUND_OR_OVERSIZE")
    raw = p.read_bytes()
    need(sha(raw) == expected_sha, "AUTO_CIPHER_FILE_SHA_MISMATCH")
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AutoSealError("AUTO_CIPHER_JSON_INVALID") from None
    validate_cipher(envelope)
    return {"schema": "RACE_AI_KEIRIN_AB_INDEPENDENT_CIPHER_READBACK_V1",
            "race_id": envelope["race_id"], "cipher_file_sha256":expected_sha,
            "A_cipher_sha256":envelope["A"]["ciphertext_sha256"],
            "B_cipher_sha256":envelope["B"]["ciphertext_sha256"],
            "ciphertext_integrity_rechecked":True,
            "RSA_decryption_and_real_source_unproven":True,
            "official_result_scored":False}
