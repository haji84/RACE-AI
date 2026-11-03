"""Report real Oct-24 BOAT race admission gaps against pinned PR71 model.

Reads a small official-source observation and the actual model's frozen feature
inventory. Does not normalize fictitious values or create a prediction.
"""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import race_ai
REFERENCE=ROOT/"pr71-contract-reference/race_ai"
if not (REFERENCE/"comprehensive_four_sport_models.py").is_file():
    raise RuntimeError("pinned PR71 research checkout unavailable")
race_ai.__path__.append(str(REFERENCE))
from race_ai.comprehensive_four_sport_models import (
    COMMON_REQUIRED,SPORT_REQUIRED,ENV_COMMON,ENV_SPORT)

def main():
    facts=json.loads((ROOT/"docs/evidence/2026-10-24-biwako-1r-official-facts.json").read_text())
    day=json.loads((ROOT/"docs/evidence/2026-10-24-biwako-12r-official-schedule.json").read_text())
    if (facts["schema"]!="RACE_AI_OFFICIAL_BOAT_FACT_OBSERVATION_V1"
        or day["event_date_jst"]!=facts["event_date_jst"]
        or len(facts["entrant_registration_numbers"])!=6
        or len(day["scheduled_close_jst"])!=12
        or facts["scheduled_sales_cutoff_at"]!="2026-10-24T10:24:00+09:00"
        or day["scheduled_close_jst"][0]!="10:24"):
        raise RuntimeError("real observation consistency mismatch")
    required_runner=tuple(COMMON_REQUIRED)+tuple(SPORT_REQUIRED["boat"])
    required_env=tuple(ENV_COMMON)+tuple(ENV_SPORT["boat"])
    if len(required_runner)!=len(set(required_runner)) or len(required_env)!=len(set(required_env)):
        raise RuntimeError("duplicate model required inputs")
    # The real source record contains only race identity, six official
    # registration numbers, advertised deadline and race type/distance.
    # NONE of these are PR71's [0,1] normalized, provenance-stamped scores.
    standardized_present=set()
    required=set(required_runner)|set(required_env)
    unknown_standardized=sorted(required-standardized_present)
    report={
        "schema":"RACE_AI_REAL_BOAT_MODEL_INPUT_GATE_V1",
        "observed_real_race_id":"boat:2026-10-24:boatrace-jcd-11:1",
        "reference_model_version":"PINNED_PR71_NOT_UPDATED",
        "real_source_facts_observed":True,
        "entrant_count":6,
        "race_count_advertised_at_single_venue":12,
        "mandatory_runner_standardized_fields_each":len(required_runner),
        "mandatory_race_environment_fields":len(required_env),
        "required_standardized_observations_total":6*len(required_runner)+len(required_env),
        "supplied_normalized_feature_observations":0,
        "missing_standardized_feature_keys":unknown_standardized,
        "actual_official_cutoff_confirmed":False,
        "automated_provider_fetch_verified":False,
        "source_use_review_complete":False,
        "model_prediction_executed":False,
        "status":"BLOCKED_MISSING_DOCUMENTED_PRE_CUTOFF_FEATURES",
    }
    if report["required_standardized_observations_total"]<=0:
        raise RuntimeError("incomplete pinned model inventory")
    print(json.dumps(report,ensure_ascii=False,sort_keys=True))
    print("REAL_PUBLIC_FACTS_ACCEPTED_AS_AUDIT_ONLY; NO_REAL_FORECAST_FREEZE_OR_SETTLEMENT")
    return 0
if __name__=="__main__":raise SystemExit(main())
