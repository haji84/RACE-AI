"""Four-sport pre-race presentation publication trigger (NO MODEL CHANGES).

Boat exhibition, autorace trial run, keirin rider introduction (line show),
horse paddock. JRA race-day bodyweight release is a distinct pre-race trigger
and MUST NEVER be relabelled a completed paddock inspection.

This is an offline identity/as-of gate. An observation of official publishing
is neither an upstream first-publication-time certificate nor permission to
fetch, reuse, learn, redistribute, or infer from third-party video.
"""
from __future__ import annotations
from datetime import datetime
from dataclasses import dataclass
import math
import re

SCHEMA="RACE_AI_FOUR_SPORT_PRESENTATION_TRIGGER_V1"
SPORTS=("boat","keirin","autorace","horse")
# Exact allowed trigger kinds, NOT interchangeable and no numeric inference.
TRIGGERS={
    "boat":frozenset({"exhibition"}),
    "autorace":frozenset({"trial_run"}),
    "keirin":frozenset({"rider_introduction"}),
    "horse":frozenset({"paddock","race_day_bodyweight"}),
}
CAPTURE={
    "boat":"FIRST_PARTY_STRUCTURED_BEFOREINFO_AVAILABLE",
    "autorace":"OFFICIAL_STRUCTURED_TRIAL_TIME_CAPTURE_REQUIRED",
    "keirin":"OFFICIAL_VERIFIED_RIDER_INTRODUCTION_OR_LINE_RECORD_REQUIRED",
    "horse":"OFFICIAL_PADDOCK_EVIDENCE_OR_RACE_DAY_BODYWEIGHT_RELEASE_REQUIRED",
}
# Bodyweight release and paddock are two independent events.
# Optional features in original PR71 stay optional; nothing is remapped to a
# required feature or imputed because an image, screen, or movie exists.
IDENTITY=re.compile(r"[a-zA-Z0-9:_-]{8,200}\Z")
HEX=re.compile(r"[0-9a-f]{64}\Z")
MARKET_TERMS=("odds","payout","dividend","popularity","market","winning_combo",
              "actual_finish","race_result")
ALLOWED_SOURCE_STATES=("PENDING","AVAILABLE","PARTIAL","UNAVAILABLE","ERROR")

class PresentationEvidenceError(ValueError):
    pass

def _time(text):
    if not isinstance(text,str):
        raise PresentationEvidenceError("timestamp required")
    try:dt=datetime.fromisoformat(text.replace("Z","+00:00"))
    except ValueError as exc:raise PresentationEvidenceError("invalid timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PresentationEvidenceError("aware timestamp required")
    return dt

def _prohibit_market(node):
    if isinstance(node,dict):
        for k,v in node.items():
            if any(word in str(k).lower() for word in MARKET_TERMS):
                raise PresentationEvidenceError("pre-race evidence mixed with market or result")
            _prohibit_market(v)
    elif isinstance(node,list):
        for v in node:_prohibit_market(v)

def inspect_presentation_observation(record, *, now):
    """Return a trigger observation without granting model admission.

    Required record:
      sport, race_id, trigger_kind, source_status, source_url,
      source_sha256, source_captured_at, scheduled_cutoff_at,
      race_identity_matched, participant_ids_matched,
      observed_feature_names, absent_feature_names.
    No 'published_at' invention: source first-publication time is unknown
    unless independently attested in a separate trusted ledger.
    No site URL is fabricated. Supplied sources must be reviewed externally.
    """
    keys=frozenset({
        "sport","race_id","trigger_kind","source_status","source_url",
        "source_sha256","source_captured_at","scheduled_cutoff_at",
        "race_identity_matched","participant_ids_matched",
        "observed_feature_names","absent_feature_names",
    })
    if not isinstance(record,dict) or frozenset(record)!=keys:
        raise PresentationEvidenceError("exact presentation observation contract required")
    _prohibit_market(record)
    sport=record["sport"]
    if sport not in SPORTS:
        raise PresentationEvidenceError("unknown sport")
    if record["trigger_kind"] not in TRIGGERS[sport]:
        raise PresentationEvidenceError("trigger belongs to different sport")
    if (not isinstance(record["race_id"],str)
        or IDENTITY.fullmatch(record["race_id"]) is None):
        raise PresentationEvidenceError("race identity invalid")
    if record["source_status"] not in ALLOWED_SOURCE_STATES:
        raise PresentationEvidenceError("unrecognized publication state")
    if (not isinstance(record["source_url"],str)
        or not record["source_url"].startswith("https://")
        or "@" in record["source_url"]):
        raise PresentationEvidenceError("source must be explicit HTTPS URL")
    if not isinstance(record["source_sha256"],str) or HEX.fullmatch(record["source_sha256"]) is None:
        raise PresentationEvidenceError("original source sha256 evidence missing")
    captured=_time(record["source_captured_at"])
    cutoff=_time(record["scheduled_cutoff_at"])
    now_t=_time(now) if isinstance(now,str) else now
    if not isinstance(now_t,datetime) or now_t.utcoffset() is None:
        raise PresentationEvidenceError("current aware time missing")
    if captured>now_t:
        raise PresentationEvidenceError("future capture cannot trigger")
    features=record["observed_feature_names"]
    missing=record["absent_feature_names"]
    if (not isinstance(features,list) or not isinstance(missing,list)
        or any(not isinstance(x,str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}",x)
               for x in features+missing)
        or len(features)!=len(set(features))
        or len(missing)!=len(set(missing))
        or set(features)&set(missing)):
        raise PresentationEvidenceError("ambiguous, duplicate or invented feature names")
    if any(any(term in name.lower() for term in MARKET_TERMS) for name in features+missing):
        raise PresentationEvidenceError("market or result feature cannot trigger prediction")
    verified=(record["race_identity_matched"] is True
              and record["participant_ids_matched"] is True)
    before_cutoff=captured<cutoff and now_t<cutoff
    published=record["source_status"] in ("AVAILABLE","PARTIAL")
    trigger=published and verified and before_cutoff
    missing_identity=not verified
    incomplete=bool(missing) or record["source_status"]=="PARTIAL"
    if not before_cutoff:
        state="CUTOFF_PASSED_OR_SOURCE_TOO_LATE"
    elif missing_identity:
        state="UNVERIFIED_RACE_OR_PARTICIPANT_IDENTITY"
    elif record["source_status"]=="PENDING":
        state="PRESENTATION_NOT_YET_PUBLISHED"
    elif record["source_status"] in ("UNAVAILABLE","ERROR"):
        state="PRESENTATION_SOURCE_UNAVAILABLE"
    elif incomplete:
        state="PRESENTATION_PUBLISHED_PARTIAL"
    else:
        state="PRESENTATION_PUBLISHED"
    return {
      "schema":SCHEMA,
      "sport":sport,"race_id":record["race_id"],
      "trigger_kind":record["trigger_kind"],
      "official_presentation_kind":CAPTURE[sport],
      "source_observed_state":record["source_status"],
      "status":state,
      "published_observed_trigger":trigger,
      "source_captured_at":record["source_captured_at"],
      "scheduled_cutoff_at":record["scheduled_cutoff_at"],
      "source_sha256":record["source_sha256"],
      "observed_feature_names":list(features),
      "absent_feature_names":list(missing),
      "partial_observation":incomplete,
      "source_first_published_at_independently_verified":False,
      "source_purpose_rights_independently_verified":False,
      "all_PR71_required_features_admitted":False,
      "PR71_model_executed":False,
      "official_prediction":False,
      "formal_hit_at_8_eligible":False,
    }

def select_published_candidate(records, *, now):
    """Earlier official scheduled cutoff first; never select post-cutoff.

    Caller supplies offline observations. No network, no scheduler, no
    automated rights grant and no prediction decision is made here.
    """
    if not isinstance(records,list):
        raise PresentationEvidenceError("observation list required")
    evaluations=[inspect_presentation_observation(r,now=now) for r in records]
    observed=[r for r in evaluations if r["published_observed_trigger"]]
    observed.sort(key=lambda x:(_time(x["scheduled_cutoff_at"]),x["race_id"],x["sport"]))
    return {
      "schema":SCHEMA,
      "checked":evaluations,
      "published_trigger_candidates":[{"sport":r["sport"],"race_id":r["race_id"],
                    "trigger_kind":r["trigger_kind"],
                    "status":r["status"]} for r in observed],
      "selected":({"sport":observed[0]["sport"],
                   "race_id":observed[0]["race_id"],
                   "trigger_kind":observed[0]["trigger_kind"]}
                  if observed else None),
      "model_input_admitted":False,
      "official_prediction":False,
    }
