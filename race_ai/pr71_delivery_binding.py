"""PR72 source-index -> PR71 private research delivery join (pure offline).

This adapter never runs a model, fetches a provider, signs a timestamp,
declares source rights, or changes picks. A matching identity/hash merely
binds two *unverified* inputs; it is not independent pre-cutoff evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import re

SCHEMA = "RACE_AI_P0_SOURCE_MODEL_BINDING_V1"
LEDGER_SCHEMA = "RACE_AI_FORECAST_AUDIT_V1"
DELIVERY_SCHEMA = "RACE_AI_PRIVATE_DELIVERY_V1"
SUITE_SCHEMA = "RACE_AI_FOUR_SPORT_RESEARCH_SUITE_V1"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

class BindingError(ValueError):
    pass

def _digest(value):
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BindingError("non-canonical input") from exc
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def _stamp(value):
    if not isinstance(value,str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)",value):
        raise BindingError("timezone-aware complete timestamp required")
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise BindingError("invalid timestamp") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise BindingError("naive timestamp")
    return d.astimezone(timezone.utc)

def _hex(value):
    return isinstance(value,str) and HEX64.fullmatch(value) is not None

def _ticket(x, participants):
    return (isinstance(x,list) and len(x)==3 and
            all(type(v) is int and v in participants for v in x)
            and len(set(x))==3)

def _checked_suite(suite, snapshot, feature_digest):
    if not isinstance(suite,dict) or suite.get("schema")!=SUITE_SCHEMA:
        raise BindingError("expected PR71 research suite schema")
    if suite.get("scope")!="OPERATOR_SUPPLIED_RESEARCH" or suite.get("official_prediction") is not False:
        raise BindingError("only nonofficial research suite admitted")
    if suite.get("external_timestamp_receipts") is not None or suite.get("official_result") is not None:
        raise BindingError("delivery cannot self-attest external receipts or results")
    if suite.get("input_sha256")!=feature_digest or suite.get("race_id")!=snapshot["race"]["race_id"]:
        raise BindingError("suite identity/input mismatch")
    if suite.get("sport")!=snapshot["race"]["sport"] or suite.get("sales_cutoff_at")!=snapshot["race"]["sales_cutoff_at"]:
        raise BindingError("suite sport/cutoff mismatch")
    if suite.get("as_of")!=snapshot["race"]["as_of"]:
        raise BindingError("suite as-of mismatch")
    if suite.get("suite_sha256")!=_digest({k:v for k,v in suite.items() if k!="suite_sha256"}):
        raise BindingError("suite hash mismatch")
    models=suite.get("models")
    ids=suite.get("ranked_model_ids")
    if not isinstance(models,dict) or not 1<=len(models)<=8 or not isinstance(ids,list) or ids!=list(models):
        raise BindingError("model roster invalid")
    if suite.get("model_count")!=len(models):
        raise BindingError("model count mismatch")
    entrants={p["number"] for p in snapshot["participants"]}
    candidate_count=len(entrants)*(len(entrants)-1)*(len(entrants)-2)
    outputs=[]
    for model_id,model in models.items():
        if not isinstance(model_id,str) or not model_id or not isinstance(model,dict):
            raise BindingError("untrusted model entry")
        if (model.get("model_id")!=model_id or model.get("race_id")!=suite["race_id"]
            or model.get("sport")!=suite["sport"] or
            model.get("candidate_count")!=candidate_count or
            model.get("cutoff_at")!=suite["sales_cutoff_at"] or
            model.get("scope")!=suite["scope"] or
            model.get("snapshot_sha256",model.get("input_sha256"))!=feature_digest or
            model.get("odds_independent") is not True or
            model.get("official_prediction") is not False or
            model.get("external_pre_cutoff_receipt") is not None or
            model.get("official_result") is not None or
            model.get("prediction_sha256")!=_digest({k:v for k,v in model.items()
                                                    if k!="prediction_sha256"})):
            raise BindingError("model evidence/prediction mismatch")
        top8=model.get("ordered_top8")
        if not isinstance(top8,list) or len(top8)!=8 or any(not _ticket(x,entrants) for x in top8):
            raise BindingError("invalid top eight")
        if len({tuple(x) for x in top8})!=8:
            raise BindingError("duplicate top-eight tickets")
        candidates=model.get("candidates")
        if not isinstance(candidates,list) or len(candidates)!=candidate_count:
            raise BindingError("incomplete candidate universe")
        seen=set()
        ranked=[]
        for x in candidates:
            if not isinstance(x,dict) or set(x)!={"combination","score"} or not _ticket(x["combination"],entrants):
                raise BindingError("invalid full-ranking candidate")
            ticket=tuple(x["combination"])
            if ticket in seen:
                raise BindingError("duplicate candidate ticket")
            seen.add(ticket)
            v=x["score"]
            if type(v) not in (int,float) or not math.isfinite(v) or v<0:
                raise BindingError("invalid candidate score")
            ranked.append((ticket,float(v)))
        if not math.isclose(math.fsum(x[1] for x in ranked),1.0,rel_tol=0,abs_tol=1e-7):
            raise BindingError("candidate probability mass invalid")
        ranked.sort(key=lambda v:(-v[1],v[0]))
        if [list(x[0]) for x in ranked[:8]]!=top8:
            raise BindingError("top-eight not derived from candidates")
        outputs.append({"model_id":model_id,"prediction_sha256":model["prediction_sha256"],
                        "ordered_top8":top8,"candidate_count":candidate_count,
                        "external_freeze_verified":False})
    return outputs

def bind_audit_to_delivery(audit, delivery, *, race_id):
    """Find same race in saved Web/ZIP audit and PR71 private delivery.

    Never copies the underlying official HTML/CSV, model features or private
    source records into the public output. Return is a *handoff manifest*
    that is explicitly INELIGIBLE for proof, scoring and website publication.
    """
    if (not isinstance(audit,dict) or audit.get("schema")!=LEDGER_SCHEMA
        or audit.get("dataset_status")!="AUDIT_ONLY"):
        raise BindingError("expected source AUDIT_ONLY ledger")
    records=audit.get("records")
    if not isinstance(records,list) or not records or len(records)>10000:
        raise BindingError("invalid discovery ledger")
    if len({x.get("race_id") for x in records if isinstance(x,dict)})!=len(records):
        raise BindingError("duplicate race ID in discovery")
    selected=[x for x in records if isinstance(x,dict) and x.get("race_id")==race_id]
    if len(selected)!=1:
        raise BindingError("race missing or ambiguous in discovery ledger")
    row=selected[0]
    if (row.get("prediction") is not None or row.get("result") is not None
        or row.get("cutoff_verified") is not False):
        raise BindingError("discovery row cannot self-attest forecast, result or cutoff")
    if not isinstance(delivery,dict) or delivery.get("schema")!=DELIVERY_SCHEMA:
        raise BindingError("expected PR71 private delivery")
    if (delivery.get("delivery_sha256") != _digest({k:v for k,v in delivery.items()
                                                   if k!="delivery_sha256"})
        or not _hex(delivery.get("source_payload_sha256"))
        or not _hex(delivery.get("policy_record_sha256"))):
        raise BindingError("delivery checksum invalid")
    if (delivery.get("status")!="PRIVATE_RESEARCH_ONLY_NOT_EXTERNAL_FROZEN"
        or delivery.get("official_prediction") is not False
        or delivery.get("external_receipt") is not None
        or delivery.get("can_count_in_hit_at_8") is not False
        or delivery.get("source_terms_independently_verified_by_code") is not False):
        raise BindingError("untrusted delivery promotion flags")
    snap=delivery.get("snapshot")
    if not isinstance(snap,dict) or not isinstance(snap.get("race"),dict):
        raise BindingError("private feature snapshot missing")
    race=snap["race"]
    sport=row.get("sport")
    expected={"horse_jra":"horse","horse_local":"horse"}.get(sport,sport)
    if expected!=race.get("sport"):
        raise BindingError("sport family mismatch")
    expected_id=f"{sport}:{audit['event_date_jst']}:{row['venue']}:{row['race_no']}"
    if expected_id!=race_id:
        raise BindingError("noncanonical source race ID")
    # Canonical discovery IDs retain horse_jra/horse_local; PR71 model IDs
    # collapse both to horse. The translation is explicit and reversible;
    # model bytes and original prediction hashes are NEVER rewritten.
    model_race_id=(f"horse:{audit['event_date_jst']}:{row['venue']}:{row['race_no']}"
                   if sport in ("horse_jra","horse_local") else race_id)
    if (race.get("race_id")!=model_race_id or delivery.get("race_id")!=model_race_id
        or race.get("event_date_jst")!=audit.get("event_date_jst")
        or race.get("venue")!=row.get("venue")
        or delivery.get("sport")!=race.get("sport")):
        raise BindingError("race identity mismatch")
    # The PR71 model schema lacks a separate race_no. The canonical race ID
    # therefore owns that dimension; NEVER try to infer it from runner numbers.
    announced=row.get("sales_cutoff_at")
    if announced is not None and _stamp(announced)!=_stamp(race.get("sales_cutoff_at")):
        raise BindingError("announced versus model cutoff disagreement")
    if not (_stamp(race.get("as_of")) < _stamp(race.get("sales_cutoff_at"))):
        raise BindingError("prediction snapshot after cutoff")
    if _stamp(delivery.get("ingested_at")) < _stamp(race.get("as_of")):
        raise BindingError("delivery claims ingestion before source snapshot")
    participants=snap.get("participants")
    if not isinstance(participants,list) or not 3<=len(participants)<=18:
        raise BindingError("participants missing")
    numbers=[p.get("number") for p in participants if isinstance(p,dict)]
    if len(numbers)!=len(participants) or len(set(numbers))!=len(numbers) or any(type(x) is not int for x in numbers):
        raise BindingError("entrant roster invalid")
    fd=_digest(snap)
    if fd!=delivery.get("feature_snapshot_sha256"):
        raise BindingError("snapshot SHA mismatch")
    suite=delivery.get("research_suite")
    outputs=_checked_suite(suite,snap,fd)
    return {"schema":SCHEMA,"race_id":race_id,"model_race_id":model_race_id,
            "sport":sport,
            "event_date_jst":audit["event_date_jst"],"venue":row["venue"],
            "race_no":row["race_no"],
            "announced_cutoff_at":announced,
            "model_claimed_cutoff_at":race["sales_cutoff_at"],
            "source_audit_status":"AUDIT_ONLY",
            "source_audit_sha256":_digest(audit),
            "source_payload_sha256":delivery["source_payload_sha256"],
            "private_delivery_sha256":delivery["delivery_sha256"],
            "feature_snapshot_sha256":fd,
            "policy_record_sha256":delivery["policy_record_sha256"],
            "models":outputs,
            "source_access_reviewed_by_this_bridge":False,
            "source_terms_reviewed_by_this_bridge":False,
            "official_sales_cutoff_verified":False,
            "external_freeze_verified":False,
            "result_verified":False,
            "eligible_for_scoring":False,
            "eligible_for_website_publication":False,
            "publication_status":"BLOCKED_PENDING_EXTERNAL_EVIDENCE",
            "next_gates":["INDEPENDENT_SOURCE_AND_PURPOSE_RIGHTS",
                          "OFFICIAL_RACE_CUTOFF",
                          "SERVER_TIME_RECEIPT_WITH_RACE_ID_AND_MODEL_HASH",
                          "PROVIDER_RESULT_REFUND_AND_PAYOUT_REVISIONS"]}
