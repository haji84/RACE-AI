"""Deterministic publication candidates with explicitly versioned replay keys.

Trigger candidate is allowed only when two verified observations of the SAME
sport/race/kind prove PENDING -> AVAILABLE/PARTIAL *before the cutoff*.
No source polling or networking occurs here. Must be coupled to an approved
provider-specific official parser + purpose-rights ledger before automation.
A scheduled program or generic legend never authorizes this transition.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re

from .four_sport_presentation_trigger import (
    PresentationEvidenceError,inspect_presentation_observation
)

SCHEMA="RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V2"
ISSUED_KEY=re.compile(re.escape(SCHEMA)+r":[0-9a-f]{64}\Z")

def _when(text):
    if not isinstance(text,str):
        raise PresentationEvidenceError("timestamp missing")
    try:
        d=datetime.fromisoformat(text.replace("Z","+00:00"))
    except ValueError as e:raise PresentationEvidenceError("invalid time") from e
    if d.utcoffset() is None:raise PresentationEvidenceError("naive time")
    return d

def compare_first_party_snapshots(previous,current,*,now,already_issued=()):
    """Returns a purely candidate event; never promotes source rights/model input.

    Persist issued_event_key, not the bare transition_sha256. V2 identity
    excludes observation times, so recapture cannot bypass replay protection.
    Bare digests and V1 records fail closed: this function cannot safely
    migrate an issued-event ledger without its original complete evidence.
    Legitimate capture and an atomic append-only store remain caller gates.
    """
    if not isinstance(already_issued,(list,set,tuple)):
        raise PresentationEvidenceError("issued event records required")
    if any(not isinstance(key,str) or ISSUED_KEY.fullmatch(key) is None
           for key in already_issued):
        raise PresentationEvidenceError(
            "versioned V2 issued event keys required; legacy records need separate migration")
    before=inspect_presentation_observation(previous,now=now)
    after=inspect_presentation_observation(current,now=now)
    for key in ("sport","race_id","trigger_kind"):
        if before[key]!=after[key]:
            raise PresentationEvidenceError("cross-race or cross-sport event cannot transition")
    if _when(before["source_captured_at"])>_when(after["source_captured_at"]):
        raise PresentationEvidenceError("capture clock regressed")
    if _when(before["source_captured_at"])==_when(after["source_captured_at"]):
        raise PresentationEvidenceError("current capture must be strictly later")
    if before["scheduled_cutoff_at"]!=after["scheduled_cutoff_at"]:
        raise PresentationEvidenceError("provider cutoff revision needs separate ledger")
    publication_change=(previous["source_status"]=="PENDING"
                        and current["source_status"] in ("AVAILABLE","PARTIAL"))
    if publication_change and before["source_sha256"]==after["source_sha256"]:
        raise PresentationEvidenceError("unchanged source bytes cannot prove publication")
    candidate=(publication_change and after["published_observed_trigger"]
               and previous["race_identity_matched"] is True
               and previous["participant_ids_matched"] is True)
    identity={"sport":after["sport"],"race_id":after["race_id"],
              "trigger_kind":after["trigger_kind"],
              "published_observation_sha256":after["source_sha256"],
              "scheduled_cutoff_at":after["scheduled_cutoff_at"]}
    stable_identity={**identity,"schema":SCHEMA,
        "scheduled_cutoff_at":_when(after["scheduled_cutoff_at"]).astimezone(timezone.utc).isoformat()}
    key=hashlib.sha256(json.dumps(stable_identity,sort_keys=True,
                                  separators=(",",":")).encode()).hexdigest()
    issued_event_key=SCHEMA+":"+key
    duplicate=issued_event_key in already_issued
    return {
        "schema":SCHEMA,**identity,
        "old_status":before["source_observed_state"],
        "new_status":after["source_observed_state"],
        "previous_captured_at":before["source_captured_at"],
        "captured_at":after["source_captured_at"],
        "transition_sha256":key,
        "issued_event_key":issued_event_key,
        "newly_published_observed":bool(candidate),
        "would_enqueue_input_check":bool(candidate and not duplicate),
        "already_issued":duplicate,
        "source_rights_for_model_admitted":False,
        "full_PR71_features_admitted":False,
        "official_prediction":False,
        "provider_monitor_started":False,
        "original_provider_published_at_verified":False,
    }
