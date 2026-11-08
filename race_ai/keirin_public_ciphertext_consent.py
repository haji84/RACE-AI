"""Public-ciphertext scope of the owner's explicit 2026-11-09 consent.

This public, nonsecret record authorizes ONLY AES-256-GCM encrypted production
forecast SQLite under the existing GitHub state ref. It is NOT a provider
licence, proof of pre-cutoff capture, independent signature or permission to
publish plaintext. Trusted main archive runners must additionally verify the
actual producer, licensed source, complete odds and ciphertext readback.
"""
from __future__ import annotations

import json
from pathlib import Path


CONSENT_PATH="docs/evidence/2026-11-09/keirin_public_ciphertext_owner_consent_v1.json"
SCHEMA="RACE_AI_KEIRIN_OWNER_PUBLIC_CIPHERTEXT_CONSENT_V1"
STATUS="OWNER_CIPHERTEXT_PUBLICATION_APPROVED_PRODUCTION_BLOCKED_PENDING_FEED_AND_TRUSTED_RUNNER"
REPO="haji84/RACE-AI"
BRANCH="state/keirin-encrypted-history"
ALLOWED="AES-256-GCM-encrypted production forecast SQLite snapshots only"
RISKS={
    "future exposure if production key leaks",
    "ciphertext copies may persist in public Git history",
}
METADATA={
    "ciphertext existence",
    "ciphertext size",
    "Git commit and update timestamps",
}
BOOLEANS_FALSE={
    "source_independently_notarized",
    "plaintext_publication_allowed",
    "private_predictions_plaintext_publication_allowed",
    "plaintext_odds_or_rider_data_publication_allowed",
    "encryption_key_publication_allowed",
    "automatic_wagering_authorized",
    "paid_data_contract_authorized",
    "automated_unlicensed_data_collection_authorized",
}
BOOLEANS_TRUE={"source_license_requirements_unchanged"}


class ConsentError(ValueError):
    pass


def check_public_ciphertext_consent(doc):
    """Exact public scope. Never interpret this as a live-source grant."""
    if type(doc) is not dict:
        raise ConsentError("OWNER_CONSENT_OBJECT_REQUIRED")
    required={
        "schema","recorded_on_jst","source","source_independently_notarized",
        "target_repository","target_branch","allowed_material",
        "public_metadata_acknowledged","risks_acknowledged",
        "plaintext_publication_allowed",
        "private_predictions_plaintext_publication_allowed",
        "plaintext_odds_or_rider_data_publication_allowed",
        "encryption_key_publication_allowed",
        "automatic_wagering_authorized","paid_data_contract_authorized",
        "automated_unlicensed_data_collection_authorized",
        "source_license_requirements_unchanged",
        "production_mode_activation","status",
    }
    if set(doc)!=required:
        raise ConsentError("OWNER_CONSENT_FIELDS_INVALID")
    if not (
        doc["schema"]==SCHEMA
        and doc["recorded_on_jst"]=="2026-11-09"
        and doc["source"]=="explicit_owner_instruction_in_chat"
        and doc["target_repository"]==REPO
        and doc["target_branch"]==BRANCH
        and doc["allowed_material"]==ALLOWED
        and doc["status"]==STATUS
        and type(doc["risks_acknowledged"]) is list
        and set(doc["risks_acknowledged"])==RISKS
        and len(doc["risks_acknowledged"])==len(RISKS)
        and type(doc["public_metadata_acknowledged"]) is list
        and set(doc["public_metadata_acknowledged"])==METADATA
        and len(doc["public_metadata_acknowledged"])==len(METADATA)
        and all(doc[key] is False for key in BOOLEANS_FALSE)
        and all(doc[key] is True for key in BOOLEANS_TRUE)
    ):
        raise ConsentError("OWNER_CONSENT_SCOPE_OR_RISK_INVALID")
    return {
        "owner_public_ciphertext_consent":True,
        "scope":"AES_GCM_PRODUCTION_SQLITE_CIPHERTEXT_ONLY",
        "provider_machine_acquisition_rights_verified":False,
        "production_archiver_enabled":False,
        "independent_signature_present":False,
    }


def read_trusted_main_ciphertext_consent(repo):
    root=Path(repo).resolve()
    file=root/CONSENT_PATH
    if file.is_symlink() or not file.is_file() or not (
        100<=file.stat().st_size<=8192
    ):
        raise ConsentError("TRUSTED_MAIN_CONSENT_RECORD_MISSING")
    def unique(pairs):
        value={}
        for name,item in pairs:
            if name in value:
                raise ConsentError("OWNER_CONSENT_DUPLICATE_JSON_KEY")
            value[name]=item
        return value
    try:
        value=json.loads(file.read_text(encoding="utf-8"),
                         object_pairs_hook=unique)
    except (ValueError,UnicodeError):
        raise ConsentError("OWNER_CONSENT_JSON_INVALID") from None
    return check_public_ciphertext_consent(value)
