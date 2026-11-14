"""Offline, rights-scoped B archive bytes -> PR64 parser -> existing PR71 stage.

This module does not contact BOATRACE, grant collection rights, publish data,
run a model, or attest pre-cutoff time.  It requires an explicitly supplied
private archive plus separately reviewed extract/normalize callbacks from PR64.

The documented official B/K download entry points being accessible DOES NOT
establish that machine collection or historical retention is licensed.
"""
from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
import re

from .boat_b_program_bridge import HANDOFF_SCHEMA, stage_official_b_handoff
from .comprehensive_four_sport_models import digest
from .permissioned_source_delivery import PermissionPolicy, SourceDeliveryError, _https

B_STAGE_SCHEMA = "RACE_AI_OFFLINE_B_ARCHIVE_STAGE_V1"
B_ARCHIVE_MAX_BYTES = 4 * 1024 * 1024
B_TEXT_MAX_BYTES = 20 * 1024 * 1024
B_ENTRY = re.compile(r"B\d{6}\.TXT\Z")
B_SOURCE_HOST = "www1.mbrace.or.jp"


def _source(source_url):
    """The upstream approved source must be an official B archive URL."""
    from urllib.parse import urlsplit
    _https(source_url)
    parts = urlsplit(source_url)
    if (parts.hostname != B_SOURCE_HOST or
        not parts.path.startswith("/od2/B/") or
        not parts.path.lower().endswith(".lzh") or parts.query or parts.fragment):
        raise SourceDeliveryError("B_SOURCE_NOT_OFFICIAL_ARCHIVE_ENDPOINT")
    return source_url


def _read_bounded(path):
    file_path = Path(path)
    if not file_path.is_file() or file_path.is_symlink():
        raise SourceDeliveryError("B_ARCHIVE_SOURCE_FILE_NOT_REGULAR")
    with file_path.open("rb") as stream:
        archive = stream.read(B_ARCHIVE_MAX_BYTES + 1)
    if not 25 <= len(archive) <= B_ARCHIVE_MAX_BYTES:
        raise SourceDeliveryError("B_ARCHIVE_SIZE_INVALID")
    return archive


def stage_supplied_b_archive(archive_path, *, day, source_url, observed_at,
                             rights_ref, parser_ref, race_id, policy, now,
                             extract_lzh, normalize_b):
    """Stage one already available archive, never fetching the provider.

    `extract_lzh(raw, expected_name)` is PR64's reviewed safe extractor.
    `normalize_b(extracted_bytes, *, day, source_url, observed_at,
                 require_details, archive_sha256)` is PR64's B normalizer.
    Both callbacks are supplied by the operator, not imported across the
    unmerged PR64/PR71 branch boundary. These interfaces do not themselves
    establish a rightsholder's grant or a trusted source-capture timestamp.
    """
    if not isinstance(policy, PermissionPolicy):
        raise SourceDeliveryError("B_REVIEWED_PERMISSION_POLICY_REQUIRED")
    source_url = _source(source_url)
    for purpose in ("analysis", "private_storage", "private_derived"):
        if not policy.authorize(source_url, rights_ref, purpose):
            raise SourceDeliveryError("B_SOURCE_PERMISSION_NOT_ADMITTED:" + purpose)
    try:
        race_day = date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise SourceDeliveryError("B_JST_DAY_INVALID") from exc
    if race_day.isoformat() != day:
        raise SourceDeliveryError("B_JST_DAY_NOT_CANONICAL")
    name = "B" + race_day.strftime("%y%m%d") + ".TXT"
    if not B_ENTRY.fullmatch(name):
        raise SourceDeliveryError("B_EXPECTED_ENTRY_INVALID")
    if (not callable(extract_lzh) or not callable(normalize_b)
        or not isinstance(parser_ref, str)
        or not re.fullmatch(r"haji84/RACE-AI@[0-9a-f]{40}:official_b_snapshot_adapter", parser_ref)):
        raise SourceDeliveryError("B_REVIEWED_PR64_PARSER_CALLBACKS_REQUIRED")
    archive = _read_bounded(archive_path)
    archive_sha = hashlib.sha256(archive).hexdigest()
    # The real PR64 extractor validates LZH metadata, names, lengths and contents.
    extracted = extract_lzh(archive, name)
    if not isinstance(extracted, bytes) or not 0 < len(extracted) <= B_TEXT_MAX_BYTES:
        raise SourceDeliveryError("B_EXTRACTED_TEXT_SIZE_INVALID")
    text_sha = hashlib.sha256(extracted).hexdigest()
    parsed = normalize_b(
        extracted, day=race_day, source_url=source_url, observed_at=observed_at,
        require_details=True, archive_sha256=archive_sha)
    if not isinstance(parsed, dict) or (
        parsed.get("source_sha256") != archive_sha or
        parsed.get("extracted_text_sha256") != text_sha or
        parsed.get("source_hash_scope") != "downloaded_archive" or
        parsed.get("source_url") != source_url or
        parsed.get("date_jst") != day or
        parsed.get("first_observed_at") != observed_at):
        raise SourceDeliveryError("B_PARSED_ORIGINAL_BYTES_SHA_MISMATCH")
    handoff = {
        "schema": HANDOFF_SCHEMA,
        "parser_ref": parser_ref,
        "rights_ref": rights_ref,
        "extract": parsed,
    }
    stage = stage_official_b_handoff(handoff, policy, now=now, race_id=race_id)
    receipt = {
        "schema": B_STAGE_SCHEMA,
        "race_id": race_id,
        "event_date_jst": day,
        "source_url": source_url,
        "source_rights_ref": rights_ref,
        "source_review_policy_sha256": policy.document_sha256,
        "source_archive_sha256": archive_sha,
        "extracted_text_sha256": text_sha,
        "byte_length": len(archive),
        "parser_ref": parser_ref,
        "program_stage": stage,
        "official_b_bytes_independently_authenticated": False,
        "source_captured_at_independently_attested": False,
        "official_prediction": False,
        "external_freeze_receipt": None,
        "eligible_hit_at_8": False,
        "status": ("MISSED_DEADLINE_NOT_FROZEN" if stage["status"] == "MISSED_DEADLINE"
                   else "PRIVATE_B_ARCHIVE_PREFLIGHT_NOT_FROZEN"),
    }
    receipt["receipt_sha256"] = digest(receipt)
    return receipt
