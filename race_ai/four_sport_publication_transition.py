"""Deterministic once-only transition between first-party presentation snapshots.

Trigger candidate is allowed only when two verified observations of the SAME
sport/race/kind prove PENDING -> AVAILABLE/PARTIAL *before the cutoff*.
No source polling or networking occurs here. Must be coupled to an approved
provider-specific official parser + purpose-rights ledger before automation.
A scheduled program or generic legend never authorizes this transition.
"""
from __future__ import annotations
from datetime import datetime
import hashlib
import json

from .four_sport_presentation_trigger import (
    PresentationEvidenceError,inspect_presentation_observation
)

SCHEMA="RACE_AI_PRESENTATION_PUBLICATION_TRANSITION_V1"

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

    Re-observing AVAILABLE does not emit an event twice. Transition digest can
    be saved by an operator-owned append-only store for idempotency after
    legitimate capture is separately permitted.
    """
    if not isinstance(already_issued,(list,set,tuple)):
        raise PresentationEvidenceError("issued event records required")
    before=inspect_presentation_observation(previous,now=now)
    after=inspect_presentation_observation(current,now=now)
    for key in ("sport","race_id","trigger_kind"):
        if before[key]!=after[key]:
            raise PresentationEvidenceError("cross-race or cross-sport event cannot transition")
    if _when(before["source_captured_at"])>_when(after["source_captured_at"]):
        raise PresentationEvidenceError("capture clock regressed")
    if before["scheduled_cutoff_at"]!=after["scheduled_cutoff_at"]:
        raise PresentationEvidenceError("provider cutoff revision needs separate ledger")
    candidate=(previous["source_status"]=="PENDING"
               and current["source_status"] in ("AVAILABLE","PARTIAL")
               and after["published_observed_trigger"])
    identity={"sport":after["sport"],"race_id":after["race_id"],
              "trigger_kind":after["trigger_kind"],
              "published_observation_sha256":after["source_sha256"],
              "captured_at":after["source_captured_at"],
              "scheduled_cutoff_at":after["scheduled_cutoff_at"]}
    key=hashlib.sha256(json.dumps(identity,sort_keys=True,
                                  separators=(",",":")).encode()).hexdigest()
    duplicate=key in already_issued
    return {
        "schema":SCHEMA,**identity,
        "old_status":before["source_observed_state"],
        "new_status":after["source_observed_state"],
        "transition_sha256":key,
        "newly_published_observed":bool(candidate),
        "would_enqueue_input_check":bool(candidate and not duplicate),
        "already_issued":duplicate,
        "source_rights_for_model_admitted":False,
        "full_PR71_features_admitted":False,
        "official_prediction":False,
        "provider_monitor_started":False,
        "original_provider_published_at_verified":False,
    }
