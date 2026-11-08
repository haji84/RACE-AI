"""Local-only authorized delivery inbox for the existing KEIRIN owner spool.

There is intentionally NO web client, site scraper, vendor API or implicit
licence. An owner-held, SHA-checked source-authorisation document is mandatory.
A file and the owner's grant assertion are not independent legal proof: the
issuer, scope and current validity must be confirmed out-of-band.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .keirin_allowed_delivery import assemble_permitted_pre_race
from .keirin_result_delivery import canonical, utc

MANIFEST = "RACE_AI_KEIRIN_OPERATOR_LICENSE_MANIFEST_V1"
MAX_GRANTS = 30
MAX_DOC_BYTES = 1_000_000
MAX_JSON_BYTES = 2_000_000
MAX_RAW_FILES = 200
PURPOSES = frozenset({
    "schedule", "pre_race", "analysis", "model_inference", "private_retention"
})


class LicenseDeliveryError(ValueError):
    pass


def _need(test, why):
    if not test:
        raise LicenseDeliveryError(why)


def _private_file(path, size_limit):
    p = Path(path).expanduser()
    _need(p.is_absolute() and p.is_file() and not p.is_symlink(),
          "TRUSTED_PRIVATE_FILE_REQUIRED")
    _need(0 < p.stat().st_size <= size_limit,
          "PRIVATE_FILE_SIZE_INVALID")
    return p


def _read_json(path):
    raw = _private_file(path, MAX_JSON_BYTES).read_bytes()
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise LicenseDeliveryError("PRIVATE_JSON_INVALID") from None


def _digest_document(path, expectation):
    p = _private_file(path, MAX_DOC_BYTES)
    _need(type(expectation) is str and len(expectation) == 64 and
          sha256(p.read_bytes()).hexdigest() == expectation,
          "LICENSE_DOCUMENT_DIGEST_MISMATCH")
    return p


def _valid_prefix(value):
    if type(value) is not str or len(value) > 256:
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and bool(u.hostname) and u.port is None and
                u.username is None and u.password is None and
                not u.query and not u.fragment and u.path.endswith("/"))
    except ValueError:
        return False


class OperatorLicenseGrants:
    """A mechanical safeguard, NEVER an independent legal determination."""

    def __init__(self, manifest, *, now):
        self.now = utc(now)
        self.bundle_id = None
        self.grants = []
        _need(type(manifest) is dict and set(manifest) == {
            "schema", "bundle_id", "grants",
        } and manifest["schema"] == MANIFEST and
              type(manifest["bundle_id"]) is str and
              1 <= len(manifest["bundle_id"]) <= 128 and
              type(manifest["grants"]) is list and
              1 <= len(manifest["grants"]) <= MAX_GRANTS,
              "LICENSE_MANIFEST_INVALID")
        self.bundle_id = manifest["bundle_id"]
        for row in manifest["grants"]:
            _need(type(row) is dict and set(row) == {
                "source_url_prefix", "rights_ref", "purposes",
                "valid_from", "valid_until", "license_document_path",
                "license_document_sha256"
            }, "GRANT_SHAPE_INVALID")
            _need(_valid_prefix(row["source_url_prefix"]) and
                  type(row["rights_ref"]) is str and
                  1 <= len(row["rights_ref"]) <= 256 and
                  type(row["purposes"]) is list and
                  set(row["purposes"]) == PURPOSES and
                  len(row["purposes"]) == len(PURPOSES),
                  "GRANT_SCOPE_INVALID")
            _need(utc(row["valid_from"]) <= self.now < utc(row["valid_until"]),
                  "GRANT_EXPIRED_OR_NOT_YET_VALID")
            # Do not store licence paperwork or private data in the repository.
            _digest_document(row["license_document_path"],
                             row["license_document_sha256"])
            self.grants.append(row)

    def allowed(self, source_url, rights_ref, purpose):
        if purpose not in PURPOSES or type(source_url) is not str:
            return False
        try:
            u = urlsplit(source_url)
            if u.scheme != "https" or u.username or u.password or u.port:
                return False
            for row in self.grants:
                prefix = urlsplit(row["source_url_prefix"])
                if (u.hostname == prefix.hostname and
                    u.path.startswith(prefix.path) and
                    rights_ref == row["rights_ref"] and
                    purpose in row["purposes"]):
                    return True
        except ValueError:
            return False
        return False

    def certificate(self, snapshot, intent):
        """Owner evidence check, not a provider signature or timestamp proof."""
        from .keirin_preflight import audit_pre_race
        _need(snapshot.get("permission_ref") == self.bundle_id and
              intent.get("permission_ref") == self.bundle_id,
              "BUNDLE_PERMISSION_MISMATCH")
        facts = snapshot["facts"]
        evidence = facts["pr71_evidenced_snapshot"]
        from hashlib import sha256
        actual = sha256(canonical(evidence)).hexdigest()
        verdict = audit_pre_race(
            facts["keirin_pre_race_audit_v1"],
            race_id=intent["race_id"],
            starters=snapshot["starters"],
            cutoff_at=intent["official_cutoff_at"],
            snapshot_as_of=snapshot["as_of"],
            issued_at=self.now.isoformat(),
            evidence_sha256=actual,
        )
        _need(verdict["full_forecast_gate_passed"],
              "ATTESTATION_CORE_AUDIT_FAILED")
        # Both model inputs and all verified audit provenance must be licensed.
        for row in facts["keirin_pre_race_audit_v1"]["items"]:
            if row["status"] == "verified":
                _need(all(self.allowed(row["source_url"], row["rights_ref"], p)
                          for p in PURPOSES),
                      "ATTESTATION_SOURCE_RIGHTS_MISMATCH")
        original = sha256(canonical(snapshot)).hexdigest()
        _need(intent["pre_race_snapshot_sha256"] == original,
              "ATTESTATION_SNAPSHOT_SHA_MISMATCH")
        return {
            "race_id": intent["race_id"],
            "source_sha256": original,
            "permission_ref": self.bundle_id,
            "official_cutoff_at": intent["official_cutoff_at"],
            "verified_purposes": [
                "schedule", "pre_race", "private_retention", "model_inference"
            ],
            "valid_until": intent["official_cutoff_at"],
        }


def load_operator_grants(path, *, now):
    return OperatorLicenseGrants(_read_json(path), now=now)


def _write_private_once(path, value):
    p = Path(path)
    _need(p.parent.is_dir() and not p.parent.is_symlink(),
          "PRIVATE_TARGET_FOLDER_NOT_READY")
    raw = canonical(value)
    if isinstance(raw, bytes):
        data = raw
    elif isinstance(raw, str):
        data = raw.encode("utf-8")
    else:
        raise LicenseDeliveryError("CANONICAL_OUTPUT_INVALID")
    _need(len(data) <= MAX_JSON_BYTES, "OUTPUT_SIZE_EXCEEDED")
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _need(not p.is_symlink() and p.is_file() and p.read_bytes() == data,
              "PRIVATE_IMMUTABILITY_CONFLICT")
        return False
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            p.unlink()
        except OSError:
            pass
        raise
    return True


def stage_permissioned_deliveries(inbox, grants, *, now):
    """Import at most 200 already-delivered local JSON files; NO HTTP calls.

    Invalid/insufficient packets are counted, never turned into a forecast or
    falsely scored as a loss. Only verified pre-race snapshots enter /pre.
    """
    root = Path(inbox).expanduser()
    _need(root.is_absolute() and root.is_dir() and not root.is_symlink(),
          "PRIVATE_INBOX_REQUIRED")
    for name in ("raw", "pre", "audit"):
        p = root / name
        if not p.exists():
            p.mkdir(mode=0o700)
        _need(p.is_dir() and not p.is_symlink(), "PRIVATE_SUBDIR_REQUIRED")
    incoming = sorted((root / "raw").glob("*.json"))
    _need(len(incoming) <= MAX_RAW_FILES, "RAW_FILE_LIMIT")
    counts = {"new_pre_race_inputs": 0, "already_staged": 0,
              "blocked_or_invalid_inputs": 0, "inspected_deliveries": 0}
    now_utc = utc(now)
    for file in incoming:
        try:
            bundle = _read_json(file)
            _need(bundle.get("race", {}).get("permission_ref") ==
                  grants.bundle_id,
                  "BUNDLE_ID_NOT_AUTHORIZED")
            asof = utc(bundle["race"]["as_of"])
            cutoff = utc(bundle["race"]["official_cutoff_at"])
            _need(asof <= now_utc < cutoff,
                  "SOURCE_AFTER_CUTOFF_OR_NOT_YET_AVAILABLE")
            packet = assemble_permitted_pre_race(
                bundle, grant_check=grants.allowed,
                checked_at=now_utc.isoformat(),
            )
            key = sha256(canonical({
                "race_id": bundle["race"]["race_id"],
                "as_of": bundle["race"]["as_of"],
                "delivery_digest": sha256(canonical(bundle)).hexdigest()
            })).hexdigest()
            # Store audit privately even if the information is incomplete.
            _write_private_once(root / "audit" / (key + ".json"),
                                packet["audit"])
            counts["inspected_deliveries"] += 1
            if packet["private_snapshot"] is None:
                counts["blocked_or_invalid_inputs"] += 1
                continue
            made = _write_private_once(root / "pre" / (key + ".json"),
                                       packet["private_snapshot"])
            counts["new_pre_race_inputs" if made else "already_staged"] += 1
        except (LicenseDeliveryError, OSError, ValueError, TypeError, KeyError):
            counts["blocked_or_invalid_inputs"] += 1
    return {
        "schema": "RACE_AI_KEIRIN_PERMISSIONED_STAGE_SUMMARY_V1",
        **counts, "provider_network_requests": 0,
        "source_rights_legally_certified_by_code": False,
        "source_data_published_to_github": False,
    }
