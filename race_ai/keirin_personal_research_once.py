"""Personal, private, one-race KEIRIN research comparison, no grant receipt.

A user-supplied candidate probe is checked against the untouched pre-race
research reference. No remote provider access is performed here. This mode
does NOT claim to validate commercial reuse, automatic site collection,
source authenticity, exact original forecast publication or formal Hit@8.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from hashlib import sha256

from .keirin_candidate_audit import research_audit_one, CandidateAuditError

MAX_REFERENCE_BYTES = 2 * 1024 * 1024
MAX_PROBE_BYTES = 256 * 1024


class PersonalResearchError(ValueError):
    pass


def read_private_json(path, *, limit):
    """Read one small operator-controlled file; refuse symlinked inputs."""
    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise PersonalResearchError("REGULAR_PRIVATE_INPUT_REQUIRED")
    if target.stat().st_size > limit:
        raise PersonalResearchError("INPUT_TOO_LARGE")
    raw = target.read_bytes()
    if not raw:
        raise PersonalResearchError("INPUT_EMPTY")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise PersonalResearchError("INVALID_JSON") from None
    return obj


def compare_personal_once(*, result_probe, original_reference,
                          race_id, cutoff_at, personal_scope):
    """Private research only. No provider licence token is demanded.

    The caller is responsible for source-specific website terms and lawful
    access; a personal-use declaration is NOT evidence of source permission
    for high-volume automation, redistribution or commercial use.
    """
    if personal_scope != "USER_PRIVATE_NONCOMMERCIAL_RESEARCH":
        raise PersonalResearchError("PERSONAL_NONCOMMERCIAL_SCOPE_REQUIRED")
    try:
        comparison = research_audit_one(
            result_probe, original_reference,
            race_id=race_id, cutoff_at=cutoff_at
        )
    except CandidateAuditError as exc:
        raise PersonalResearchError(str(exc)) from None
    return {
        "schema": "RACE_AI_KEIRIN_PERSONAL_ONE_RACE_V1",
        "scope": personal_scope,
        "user_private_use_no_individual_license_token_required": True,
        "provider_automated_fetch_rights_claimed": False,
        "rightsholder_permission_verified": False,
        "third_party_result_authenticated": False,
        "model_updated": False,
        "new_future_prediction_saved": False,
        "formal_hit_at_8_all": None,
        "research_comparison": comparison,
    }


def one_private_fetch_and_compare(*, original_reference, race_id, cutoff_at,
                                  ymd, venue_code, race_no, personal_scope,
                                  one_get_acknowledgement, route="legacy",
                                  opener=None):
    """One expressly requested personal GET, never a recurring collector.

    The website's own access terms still apply. This function neither
    invents a rightsholder grant nor disables access limitations.
    """
    from .keirin_mobile_one_shot import (
        ACK, probe_one, page_url, MobileProbeError
    )
    if personal_scope != "USER_PRIVATE_NONCOMMERCIAL_RESEARCH":
        raise PersonalResearchError("PERSONAL_NONCOMMERCIAL_SCOPE_REQUIRED")
    if one_get_acknowledgement != "USER_EXPLICIT_ONE_RESULT_GET":
        raise PersonalResearchError("ONE_GET_EXPLICIT_ACTION_REQUIRED")
    # Identity and original-before-deadline checks happen BEFORE source I/O.
    page_url(ymd, venue_code, race_no)
    expected_id = f"{ymd}{venue_code:02d}{race_no:02d}"
    if race_id != expected_id:
        raise PersonalResearchError("REQUESTED_RACE_ID_MISMATCH")
    if (type(original_reference) is not dict or
            type(original_reference.get("races")) is not list or
            len([x for x in original_reference["races"]
                 if type(x) is dict and x.get("id") == expected_id]) != 1):
        raise PersonalResearchError("REFERENCE_RACE_NOT_FOUND")
    from .keirin_result_delivery import utc
    try:
        if not utc(original_reference["stamp_jst"]) < utc(cutoff_at):
            raise PersonalResearchError("REFERENCE_NOT_PRE_CUTOFF")
    except (KeyError, TypeError, ValueError):
        raise PersonalResearchError("REFERENCE_TIME_INVALID") from None
    # The earlier single-page transport enforces one GET, 8 sec/500KB limit,
    # HTTPS exact host, no redirect, and no HTML retention.
    try:
        probe = probe_one(ymd, venue_code, race_no,
                          acknowledgement=ACK, route=route, opener=opener)
    except MobileProbeError:
        raise PersonalResearchError("ONE_PAGE_PROVIDER_UNAVAILABLE") from None
    return compare_personal_once(
        result_probe=probe, original_reference=original_reference,
        race_id=expected_id, cutoff_at=cutoff_at, personal_scope=personal_scope)

def save_private_once(document, output_path):
    """Create one 0600 file, never replace uncertain or old output."""
    target = Path(output_path)
    body = (json.dumps(document, ensure_ascii=False,
                       sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n").encode("utf-8")
    if len(body) > MAX_REFERENCE_BYTES:
        raise PersonalResearchError("OUTPUT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(str(target), flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise PersonalResearchError("CREATE_ONLY_OUTPUT_EXISTS") from None
    finally:
        if fd is not None:
            os.close(fd)
    return {"status": "PERSONAL_RESEARCH_SAVED_ONCE",
            "path": str(target), "sha256": sha256(body).hexdigest(),
            "bytes": len(body)}
