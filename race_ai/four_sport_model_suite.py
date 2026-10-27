"""Single as-of snapshot -> four independent four-sport research forecasts.

Maintains separate, prospective model identities and ranks exactly the same
underlying participants. Does not claim collection rights, official forecast,
external persistence, calibration, true Hit@8, or betting readiness.
"""
from __future__ import annotations

from .comprehensive_four_sport_models import (
    predict as factor_predict, validate, MODEL_IDS as FACTOR_MODEL_IDS, digest
)
from .four_sport_matchup_models import (
    predict as matchup_predict, MODEL_IDS as MATCHUP_MODEL_IDS
)
from .four_sport_learning import forecast as learned_forecast, LEARNED_ID

SCHEMA = "RACE_AI_FOUR_SPORT_RESEARCH_SUITE_V1"
ALL_MODELS = FACTOR_MODEL_IDS + MATCHUP_MODEL_IDS


def run_suite(snapshot, *, allow_source=None, learned_model=None):
    """Run all model families; source checker defaults to deny for real input."""
    validated = validate(snapshot, allow_source=allow_source)
    n = len(validated["participants"])
    expected = n*(n-1)*(n-2)
    models = {
        **factor_predict(snapshot, allow_source=allow_source),
        **matchup_predict(snapshot, allow_source=allow_source),
    }
    if tuple(models) != ALL_MODELS:
        raise ValueError("research model roster changed without versioning")
    if learned_model is not None:
        models[LEARNED_ID] = learned_forecast(snapshot, learned_model, allow_source=allow_source)
    input_hash = validated["snapshot_sha256"]
    for name, prediction in models.items():
        if (prediction["model_id"] != name or
            prediction.get("snapshot_sha256",prediction.get("input_sha256")) != input_hash or
            prediction["race_id"] != snapshot["race"]["race_id"] or
            prediction["as_of"] != snapshot["race"]["as_of"] or
            prediction["cutoff_at"] != snapshot["race"]["sales_cutoff_at"] or
            prediction["candidate_count"] != expected or
            len(prediction["ordered_top8"]) != min(8, expected) or
            prediction["odds_independent"] is not True or
            prediction["official_prediction"] is not False or
            prediction["external_pre_cutoff_receipt"] is not None):
            raise ValueError("research model contract unsafe")
    record = {
        "schema":SCHEMA,
        "scope":snapshot["scope"],
        "sport":snapshot["race"]["sport"],
        "race_id":snapshot["race"]["race_id"],
        "race_revision":snapshot["race"]["race_revision"],
        "as_of":snapshot["race"]["as_of"],
        "sales_cutoff_at":snapshot["race"]["sales_cutoff_at"],
        "input_sha256":input_hash,
        "ranked_model_ids":list(models),
        "models":models,
        "model_count":len(models),
        "research_status":"RESEARCH_UNCALIBRATED_NOT_PERSISTED",
        "official_prediction":False,
        "external_timestamp_receipts":None,
        "official_result":None,
        "rights_not_granted_by_runner":True,
        "purchase_decision":"NO_BET",
    }
    record["suite_sha256"]=digest(record)
    return record


def verify_suite(record):
    """Pure local SHA check, not an independent timestamp or rights receipt."""
    if not isinstance(record,dict) or record.get("schema") != SCHEMA:
        return False
    if record.get("suite_sha256") != digest(
            {k:v for k,v in record.items() if k!="suite_sha256"}):
        return False
    models = record.get("models")
    if not isinstance(models,dict) or tuple(models) not in (ALL_MODELS,ALL_MODELS+(LEARNED_ID,)):
        return False
    if record.get("official_prediction") is not False or record.get("external_timestamp_receipts") is not None:
        return False
    for name, p in models.items():
        if (not isinstance(p,dict) or p.get("model_id") != name or
            p.get("snapshot_sha256",p.get("input_sha256")) != record.get("input_sha256") or
            p.get("prediction_sha256") != digest(
                {k:v for k,v in p.items() if k!="prediction_sha256"}) or
            p.get("official_prediction") is not False or
            p.get("external_pre_cutoff_receipt") is not None):
            return False
    return True
