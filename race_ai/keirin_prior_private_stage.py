"""Owner-private, create-once replay packet for observed historical KEIRIN inputs.

This is a staging/readback adapter for the EXISTING PR71 historical equations,
not a predictor, data licence, official timestamp witness, or model admission.
All actual rider identities, source URLs, per-race results and candidate values
remain in a private directory outside the public GitHub checkout.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re

from .keirin_result_delivery import canonical
from .keirin_permissioned_owner import _write_private_once, LicenseDeliveryError
from .keirin_winticket_prior_events import (
    PriorSourceError, observed_prior_candidates, _utc,
)

SCHEMA = "RACE_AI_KEIRIN_PRIVATE_HISTORICAL_CANDIDATES_V1"
MAX_BYTES = 2_000_000
HEX = re.compile(r"^[0-9a-f]{64}$")


def need(ok, reason):
    if not ok:
        raise PriorSourceError(reason)


def private_research_packet(reference, events, derived, *, racecard_sha256,
                            day_index_sha256, as_of):
    """Recompute all candidate evidence before accepting a private packet."""
    need(type(reference) is dict and type(events) is list and
         type(derived) is dict and type(as_of) is str,
         "PRIOR_PRIVATE_PACKET_SHAPE_INVALID")
    need(type(racecard_sha256) is str and HEX.fullmatch(racecard_sha256) and
         type(day_index_sha256) is str and HEX.fullmatch(day_index_sha256),
         "PRIOR_PRIVATE_ORIGINAL_SHA_REQUIRED")
    target = reference.get("target")
    riders = reference.get("rider_ids")
    refs = reference.get("references")
    need(type(target) is dict and type(riders) is list and
         len(riders) in (7, 9) and len(set(riders)) == len(riders) and
         type(refs) is list and len(refs) <= 2000 and
         len(events) <= 100, "PRIOR_PRIVATE_TARGET_OR_ROSTER_INVALID")
    need(_utc(target["as_of"]) <= _utc(as_of) < _utc(target["cutoff"]),
         "PRIOR_PRIVATE_AFTER_TARGET_CUTOFF")
    lookup = {}
    for record in refs:
        need(type(record) is dict and
             set(record) == {"race_id", "url", "rider_ids"} and
             type(record["race_id"]) is str and
             type(record["url"]) is str and
             type(record["rider_ids"]) is list and
             set(record["rider_ids"]) <= set(riders),
             "PRIOR_REFERENCE_NOT_SOURCE_JOINED")
        rid = record["race_id"]
        need(rid not in lookup, "DUPLICATED_PAST_REFERENCE")
        lookup[rid] = record["url"]
    for event in events:
        need(type(event) is dict and
             event.get("race_id") in lookup and
             event.get("result_source_url") == lookup[event["race_id"]] and
             type(event.get("result_source_sha256")) is str and
             HEX.fullmatch(event["result_source_sha256"]) and
             any(row.get("rider_id") in riders
                 for row in event.get("starters", [])
                 if type(row) is dict),
             "PAST_RESULT_NOT_BOUND_TO_CAPTURED_REFERENCE")
    # The original equations must agree byte-for-byte with the candidate
    # record. A caller cannot swap scores, samples, lineage or a later as-of.
    recomputed = observed_prior_candidates(reference, events, as_of=as_of)
    need(derived == recomputed and
         derived.get("source_rights_independently_verified") is False and
         derived.get("model_input_admitted") is False and
         derived.get("forecasts_created") == 0 and
         set(derived["riders"]) == set(riders),
         "PRIOR_CANDIDATE_REPLAY_OR_ADMISSION_CONFLICT")
    for row in derived["riders"].values():
        for feature in row["features"].values():
            need(feature["approved_for_pr71_input"] is False,
                 "PRIOR_CANDIDATE_CANNOT_SELF_APPROVE")
    packet = {
        "schema": SCHEMA,
        "target_race_id": target["race_id"],
        "racecard_original_sha256": racecard_sha256,
        "day_index_original_sha256": day_index_sha256,
        "source_reference": reference,
        "prior_events": events,
        "candidate_snapshot": derived,
        "calculated_as_of": as_of,
        "permission_to_run_PR71": False,
        "independent_source_publication_witness": False,
        "provider_automated_training_rights_verified": False,
        "real_forecast_frozen": False,
        "provider_http_requests": 0,
    }
    need(len(canonical(packet)) <= MAX_BYTES,
         "PRIVATE_RESEARCH_PACKET_TOO_LARGE")
    return packet


def _private_root(root):
    p = Path(root).expanduser()
    need(p.is_absolute() and p.is_dir() and not p.is_symlink(),
         "OWNER_PRIVATE_RESEARCH_ROOT_REQUIRED")
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        public = Path(workspace).resolve()
        private = p.resolve()
        need(private != public and public not in private.parents,
             "PUBLIC_GIT_CHECKOUT_PRIVATE_RESULTS_FORBIDDEN")
    return p


def read_private_research_packet(path, *, expected_sha256):
    """Independent SHA and deterministic formula replay, never an approval."""
    p = Path(path)
    need(type(expected_sha256) is str and HEX.fullmatch(expected_sha256) and
         p.is_file() and not p.is_symlink() and
         0 < p.stat().st_size <= MAX_BYTES,
         "PRIVATE_PRIOR_REPLAY_OR_SIZE_INVALID")
    raw = p.read_bytes()
    need(sha256(raw).hexdigest() == expected_sha256,
         "PRIVATE_PRIOR_PACKET_SHA_MISMATCH")
    try:
        record = json.loads(raw.decode("utf-8"))
        need(type(record) is dict and record.get("schema") == SCHEMA,
             "PRIVATE_PRIOR_PACKET_SCHEMA_MISMATCH")
        expected = private_research_packet(
            record["source_reference"], record["prior_events"],
            record["candidate_snapshot"],
            racecard_sha256=record["racecard_original_sha256"],
            day_index_sha256=record["day_index_original_sha256"],
            as_of=record["calculated_as_of"],
        )
        need(record == expected and canonical(record) == raw,
             "PRIVATE_PRIOR_PACKET_CHANGED_OR_NOT_CANONICAL")
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise PriorSourceError("PRIVATE_PRIOR_PACKET_REPLAY_FAILED") from exc
    return record


def stage_owner_private_prior_research(root, packet):
    """Create-once under an existing owner-private root; return only counts/SHA.

    A GitHub-hosted temporary file is NOT a durable encrypted Git generation.
    This function never pushes data, writes public artifacts, or authorizes
    source rights. A separately approved AES process must handle retention.
    """
    owner = _private_root(root)
    need(type(packet) is dict and packet.get("schema") == SCHEMA,
         "PRIOR_PACKET_REQUIRED")
    verified = private_research_packet(
        packet["source_reference"], packet["prior_events"],
        packet["candidate_snapshot"],
        racecard_sha256=packet["racecard_original_sha256"],
        day_index_sha256=packet["day_index_original_sha256"],
        as_of=packet["calculated_as_of"],
    )
    need(packet == verified, "PRIOR_UNVERIFIED_PACKET_NOT_ALLOWED")
    digest = sha256(canonical(packet)).hexdigest()
    folder = owner / "keirin_prior_research"
    need(not folder.is_symlink(), "PRIOR_PRIVATE_DIR_SYMLINK_FORBIDDEN")
    folder.mkdir(mode=0o700, exist_ok=True)
    need(folder.is_dir() and not folder.is_symlink(),
         "PRIOR_PRIVATE_FOLDER_INVALID")
    target = folder / (digest + ".json")
    try:
        existed = not _write_private_once(target, packet)
    except LicenseDeliveryError as exc:
        raise PriorSourceError("PRIVATE_PRIOR_CREATE_ONCE_CONFLICT") from exc
    readback = read_private_research_packet(target, expected_sha256=digest)
    need(readback == packet, "PRIVATE_PRIOR_READBACK_NOT_EQUAL")
    candidate_count = sum(
        feature["candidate_value"] is not None
        for row in packet["candidate_snapshot"]["riders"].values()
        for feature in row["features"].values()
    )
    return {
        "schema": "RACE_AI_PRIVATE_PRIOR_RESEARCH_READBACK_V1",
        "state": "PRIVATE_RESEARCH_REPLAY_VERIFIED_NOT_MODEL_APPROVED",
        "private_packet_sha256": digest,
        "new_private_packet": not existed,
        "past_results_preserved": len(packet["prior_events"]),
        "candidate_feature_values": candidate_count,
        "public_plaintext_written": False,
        "production_aes_archived": False,
        "official_predictions_generated": False,
        "approved_for_pr71_input": False,
    }
