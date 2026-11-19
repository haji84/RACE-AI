"""Encrypted official-source revisions in the existing GitHub history branch.

Only authenticated ciphertext and a strict hash/time receipt enter Git. Source
documents, result details, score reports and the owner's view stay encrypted
to the existing pinned owner key. Cipher readback does not claim decryption
or independently establish the truth of source documents.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import keirin_nationwide_auto_storage as storage
from . import keirin_nationwide_cipher_history as archive

ROOT = "state/keirin/ab/official-results/v1"
SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_EVIDENCE_ENCRYPTED_V1"
RECEIPT = "RACE_AI_KEIRIN_OFFICIAL_EVIDENCE_GIT_RECEIPT_V1"
MAX_PLAINTEXT_BYTES = 16 * 1024 * 1024
MAX_CIPHER_BYTES = 24 * 1024 * 1024
MAX_RECEIPT_BYTES = 16 * 1024
DEFAULT_DAY_READ_BYTES = 64 * 1024 * 1024
MAX_DAY_READ_BYTES = 128 * 1024 * 1024
MAX_DAY_REVISIONS = 1000
SHA = re.compile(r"^[0-9a-f]{64}$")
HEADER_FIELDS = frozenset({
    "schema", "day_jst", "observed_at", "owner_RSA_SPKI_sha256",
    "evidence_plaintext_sha256", "report_sha256",
})
ENVELOPE_FIELDS = HEADER_FIELDS | {
    "aesgcm_nonce_b64", "rsa_oaep_sha256_wrapped_key_b64",
    "ciphertext_b64", "ciphertext_sha256",
}
RECEIPT_FIELDS = frozenset({
    "schema", "day_jst", "cipher_sha256", "evidence_plaintext_sha256",
    "observed_at", "report_sha256",
})


class OfficialRunHistoryError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise OfficialRunHistoryError(code)


def _day(day):
    _need(type(day) is str, "EVIDENCE_DAY_INVALID")
    try:
        _need(date.fromisoformat(day).isoformat() == day,
              "EVIDENCE_DAY_INVALID")
    except ValueError:
        raise OfficialRunHistoryError("EVIDENCE_DAY_INVALID") from None
    return day


def _when(value):
    _need(type(value) is str, "EVIDENCE_OBSERVATION_CLOCK_INVALID")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(at.utcoffset() is not None, "EVIDENCE_OBSERVATION_CLOCK_INVALID")
    except ValueError:
        raise OfficialRunHistoryError("EVIDENCE_OBSERVATION_CLOCK_INVALID") from None
    return at


def _canonical(value):
    try:
        return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OfficialRunHistoryError("EVIDENCE_JSON_INVALID") from None


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "EVIDENCE_DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def _json(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               OfficialRunHistoryError("EVIDENCE_NONFINITE_JSON")))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OfficialRunHistoryError("EVIDENCE_JSON_INVALID") from None
    _need(_canonical(value) == raw, "EVIDENCE_CANONICAL_BYTES_REQUIRED")
    return value


def _sha(value):
    return sha256(value).hexdigest()


def _report_bytes(report, day):
    # This object is encrypted, never copied to a public receipt or log.
    _need(type(report) is dict and report.get("day_jst") == day,
          "EVIDENCE_REPORT_DAY_MISMATCH")
    raw = _canonical(report)
    _need(len(raw) <= MAX_PLAINTEXT_BYTES, "EVIDENCE_REPORT_TOO_LARGE")
    return raw


def _b64(value):
    _need(type(value) is str, "EVIDENCE_BASE64_INVALID")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise OfficialRunHistoryError("EVIDENCE_BASE64_INVALID") from None


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(), label=None)


def _aad(envelope):
    return _canonical({key: envelope[key] for key in HEADER_FIELDS})


def _checked_cipher(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_CIPHER_BYTES,
          "EVIDENCE_CIPHER_BYTES_INVALID_OR_TOO_LARGE")
    doc = _json(raw)
    _need(type(doc) is dict and set(doc) == ENVELOPE_FIELDS and
          doc["schema"] == SCHEMA and
          doc["owner_RSA_SPKI_sha256"] == storage.PINNED_OWNER_SPKI_SHA256,
          "EVIDENCE_CIPHER_SCHEMA_OR_OWNER_INVALID")
    _day(doc["day_jst"])
    _when(doc["observed_at"])
    for key in ("evidence_plaintext_sha256", "report_sha256", "ciphertext_sha256"):
        _need(type(doc[key]) is str and SHA.fullmatch(doc[key]),
              "EVIDENCE_DIGEST_INVALID")
    nonce, wrapped, cipher = (_b64(doc[key]) for key in (
        "aesgcm_nonce_b64", "rsa_oaep_sha256_wrapped_key_b64", "ciphertext_b64"))
    _need(len(nonce) == 12 and 384 <= len(wrapped) <= 2048 and
          16 < len(cipher) <= MAX_PLAINTEXT_BYTES + 16 and
          _sha(cipher) == doc["ciphertext_sha256"],
          "EVIDENCE_CIPHER_SHA_OR_LENGTH_INVALID")
    return doc


def seal_evidence(payload, owner_public_pem, day, observed_at):
    """Seal an entire private revision with a new AES key/nonce; no disk I/O."""
    _day(day)
    _when(observed_at)
    _need(type(payload) is dict and payload.get("day_jst", day) == day,
          "EVIDENCE_PRIVATE_PAYLOAD_DAY_INVALID")
    report_raw = _report_bytes(payload.get("safe_report"), day)
    raw = _canonical(payload)
    _need(len(raw) <= MAX_PLAINTEXT_BYTES, "EVIDENCE_PRIVATE_PAYLOAD_TOO_LARGE")
    public = storage.checked_public_key(owner_public_pem)
    envelope = {
        "schema": SCHEMA, "day_jst": day, "observed_at": observed_at,
        "owner_RSA_SPKI_sha256": storage.PINNED_OWNER_SPKI_SHA256,
        "evidence_plaintext_sha256": _sha(raw), "report_sha256": _sha(report_raw),
    }
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, raw, _aad(envelope))
    envelope.update({
        "aesgcm_nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "rsa_oaep_sha256_wrapped_key_b64": base64.b64encode(
            public.encrypt(key, _oaep())).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
        "ciphertext_sha256": _sha(ciphertext),
    })
    sealed = _canonical(envelope)
    _checked_cipher(sealed)
    return sealed


def decrypt_evidence(raw, owner_private_pem):
    """Authenticate and return the private payload in memory for its owner."""
    envelope = _checked_cipher(raw)
    _need(type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 20000,
          "EVIDENCE_OWNER_PRIVATE_PEM_REQUIRED")
    try:
        key = serialization.load_pem_private_key(owner_private_pem, password=None)
    except (ValueError, TypeError):
        raise OfficialRunHistoryError("EVIDENCE_OWNER_PRIVATE_PEM_INVALID") from None
    _need(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 3072,
          "EVIDENCE_OWNER_RSA_PRIVATE_KEY_REQUIRED")
    public_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    _need(_sha(public_der) == storage.PINNED_OWNER_SPKI_SHA256,
          "EVIDENCE_OWNER_PRIVATE_PIN_MISMATCH")
    try:
        aes = key.decrypt(_b64(envelope["rsa_oaep_sha256_wrapped_key_b64"]), _oaep())
        _need(len(aes) == 32, "EVIDENCE_AES_256_KEY_REQUIRED")
        plain = AESGCM(aes).decrypt(_b64(envelope["aesgcm_nonce_b64"]),
                                    _b64(envelope["ciphertext_b64"]), _aad(envelope))
    except (ValueError, InvalidTag):
        raise OfficialRunHistoryError("EVIDENCE_DECRYPTION_FAILED") from None
    _need(len(plain) <= MAX_PLAINTEXT_BYTES and
          _sha(plain) == envelope["evidence_plaintext_sha256"],
          "EVIDENCE_PRIVATE_SHA_MISMATCH")
    payload = _json(plain)
    _need(type(payload) is dict and
          payload.get("day_jst", envelope["day_jst"]) == envelope["day_jst"],
          "EVIDENCE_PRIVATE_PAYLOAD_DAY_INVALID")
    _need(_sha(_report_bytes(payload.get("safe_report"), envelope["day_jst"])) ==
          envelope["report_sha256"], "EVIDENCE_REPORT_SHA_MISMATCH")
    return payload


def _refs(day, digest):
    _day(day)
    _need(type(digest) is str and SHA.fullmatch(digest), "EVIDENCE_DIGEST_INVALID")
    stem = f"{ROOT}/{day}/{digest}"
    return stem + ".sealed.json", stem + ".receipt.json"


def _read_at(repo, head, day, digest):
    cipher_path, receipt_path = _refs(day, digest)
    stored = archive.read_blob_bytes(repo, head, cipher_path, max_bytes=MAX_CIPHER_BYTES)
    record = archive.read_blob_bytes(repo, head, receipt_path, max_bytes=MAX_RECEIPT_BYTES)
    _need((stored is None) == (record is None), "EVIDENCE_ARCHIVE_PAIR_INCOMPLETE")
    if stored is None:
        return None
    raw = stored
    envelope = _checked_cipher(raw)
    receipt = _json(record)
    _need(type(receipt) is dict and
          set(receipt) in (RECEIPT_FIELDS, RECEIPT_FIELDS | {"producer_run_id"}) and
          receipt["schema"] == RECEIPT and receipt["day_jst"] == day and
          receipt["cipher_sha256"] == _sha(raw) and
          receipt["evidence_plaintext_sha256"] == digest ==
          envelope["evidence_plaintext_sha256"] and envelope["day_jst"] == day and
          receipt["observed_at"] == envelope["observed_at"] and
          receipt["report_sha256"] == envelope["report_sha256"],
          "EVIDENCE_ARCHIVE_RECEIPT_OR_SHA_MISMATCH")
    if "producer_run_id" in receipt:
        _need(type(receipt["producer_run_id"]) is str and
              archive.RUN.fullmatch(receipt["producer_run_id"]),
              "EVIDENCE_PRODUCER_RUN_INVALID")
    return {"receipt": receipt, "raw_cipher": raw}


def read_revisions(*, repo, day, synthetic_local=False,
                   max_total_bytes=DEFAULT_DAY_READ_BYTES,
                   max_revisions=MAX_DAY_REVISIONS):
    """Read an intact day in observation order within explicit memory bounds.

    Check revision count and total immutable blob sizes before loading any
    ciphertext. An oversized day is a HOLD, never a truncated history.
    """
    _day(day)
    _need(type(max_total_bytes) is int and 1 <= max_total_bytes <= MAX_DAY_READ_BYTES and
          type(max_revisions) is int and 1 <= max_revisions <= MAX_DAY_REVISIONS,
          "EVIDENCE_DAY_READ_LIMIT_INVALID")
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    head = archive._refresh(repo)
    prefix = f"{ROOT}/{day}/"
    _, names = archive._cmd(repo, "--no-replace-objects", "ls-tree", "-r", "--name-only",
                           head, "--", prefix)
    digests = set()
    for path in names.splitlines():
        _need(path.startswith(prefix), "EVIDENCE_ARCHIVE_DAY_PATH_MISMATCH")
        name = path[len(prefix):]
        match = re.fullmatch(r"([0-9a-f]{64})\.(sealed|receipt)\.json", name)
        _need(match is not None, "EVIDENCE_ARCHIVE_UNKNOWN_FILE")
        digests.add(match.group(1))
        _need(len(digests) <= max_revisions, "EVIDENCE_DAY_REVISION_LIMIT_EXCEEDED")
    total_bytes = 0
    for digest in sorted(digests):
        cipher_path, receipt_path = _refs(day, digest)
        for path, bound in ((cipher_path, MAX_CIPHER_BYTES), (receipt_path, MAX_RECEIPT_BYTES)):
            status, size = archive._cmd(repo, "--no-replace-objects", "cat-file", "-s",
                                        f"{head}:{path}", okay=True)
            _need(status == 0, "EVIDENCE_ARCHIVE_PAIR_INCOMPLETE")
            _need(size.isascii() and size.isdecimal() and len(size) <= 18 and
                  0 < int(size) < bound, "EVIDENCE_DAY_BLOB_SIZE_INVALID")
            total_bytes += int(size)
            _need(total_bytes <= max_total_bytes, "EVIDENCE_DAY_READ_BUDGET_EXCEEDED")
    revisions = [_read_at(repo, head, day, digest) for digest in sorted(digests)]
    _need(all(row is not None for row in revisions), "EVIDENCE_ARCHIVE_MISSING")
    return sorted(revisions, key=lambda row: (
        _when(row["receipt"]["observed_at"]), row["receipt"]["evidence_plaintext_sha256"]))


def _create_parent(tree, relative):
    parent = tree
    for component in Path(relative).parts[:-1]:
        parent /= component
        _need(not parent.is_symlink(), "EVIDENCE_ARCHIVE_SYMLINK_PROHIBITED")
        parent.mkdir(exist_ok=True)


def append_revision(*, repo, day, raw_cipher, safe_report, synthetic_local=False):
    """Create a revision by plaintext SHA; preserve exact existing originals.

    A repeated payload encrypted with new randomness returns the original
    receipt and original ciphertext SHA. Report/source contents are never
    copied to the receipt. No branch creation, reset or forced push occurs.
    """
    _day(day)
    envelope = _checked_cipher(raw_cipher)
    _need(envelope["day_jst"] == day, "EVIDENCE_ARCHIVE_DAY_MISMATCH")
    _need(_sha(_report_bytes(safe_report, day)) == envelope["report_sha256"],
          "EVIDENCE_REPORT_SHA_MISMATCH")
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    digest = envelope["evidence_plaintext_sha256"]
    cipher_path, receipt_path = _refs(day, digest)
    receipt = {
        "schema": RECEIPT, "day_jst": day, "cipher_sha256": _sha(raw_cipher),
        "evidence_plaintext_sha256": digest, "observed_at": envelope["observed_at"],
        "report_sha256": envelope["report_sha256"],
    }
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id is not None:
        _need(archive.RUN.fullmatch(run_id), "EVIDENCE_PRODUCER_RUN_INVALID")
        receipt["producer_run_id"] = run_id
    for _ in range(3):
        head = archive._refresh(repo)
        existing = _read_at(repo, head, day, digest)
        if existing is not None:
            _need(existing["receipt"]["report_sha256"] == envelope["report_sha256"],
                  "EVIDENCE_EXISTING_REPORT_SHA_MISMATCH")
            return dict(existing["receipt"],
                        state="IDENTICAL_EVIDENCE_ALREADY_ARCHIVED_NO_NEW_WRITE",
                        readback_head=head)
        with TemporaryDirectory(prefix="keirin-official-cipher-") as temp:
            tree = Path(temp) / "tree"
            archive._cmd(repo, "worktree", "add", "--detach", str(tree), head)
            try:
                _create_parent(tree, cipher_path)
                for relative, content in ((cipher_path, raw_cipher),
                                          (receipt_path, _canonical(receipt))):
                    target = tree / relative
                    _need(not target.exists() and not target.is_symlink(),
                          "EVIDENCE_CREATE_ONCE_REQUIRED")
                    with target.open("xb") as stream:
                        stream.write(content)
                archive._cmd(tree, "add", "--", cipher_path, receipt_path)
                archive._cmd(tree, "-c", "user.name=RACE-AI", "-c",
                             "user.email=race-ai@users.noreply.github.com",
                             "commit", "-m", f"archive(keirin): encrypted official revision {day}")
                new_head = archive._cmd(tree, "rev-parse", "HEAD")[1]
                status, _ = archive._cmd(tree, "push", "origin",
                                        f"HEAD:refs/heads/{archive.BRANCH}", okay=True)
            finally:
                archive._cmd(repo, "worktree", "remove", "--force", str(tree), okay=True)
        if status == 0:
            rechecked = archive._refresh(repo)
            stored = _read_at(repo, rechecked, day, digest)
            _need(stored is not None and stored["raw_cipher"] == raw_cipher and
                  stored["receipt"] == receipt, "EVIDENCE_POST_WRITE_READBACK_MISMATCH")
            ancestor, _ = archive._cmd(repo, "merge-base", "--is-ancestor",
                                       new_head, rechecked, okay=True)
            _need(ancestor == 0, "EVIDENCE_WRITE_NOT_ANCESTOR_OF_READBACK")
            return dict(receipt, state="ENCRYPTED_EVIDENCE_REVISION_GIT_READBACK_OK",
                        write_commit=new_head, readback_head=rechecked)
    raise OfficialRunHistoryError("EVIDENCE_CONCURRENT_GIT_RETRY_EXHAUSTED")
