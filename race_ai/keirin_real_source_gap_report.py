"""Count real WINTICKET source coverage against the EXISTING PR71 347 gate.

No model estimates, new coefficients, rights grants or rider values leave this
module. The target race might still be genuinely pre-cutoff; source-availability
and independent provider publication/permission are separate requirements.
"""
from __future__ import annotations

from .keirin_preflight import CRITICAL_RACE, CRITICAL_RIDER, expected_keys
from .keirin_allowed_delivery import (
    MODEL_REQUIRED, ENV_REQUIRED, ENV_MAP, RIDER_MAP, RIDER_MAP_DISTINCT_B,
)
from .keirin_winticket_embedded_racecard import SCHEMA as PARTIAL_SCHEMA

SCHEMA="RACE_AI_KEIRIN_REAL_347_SOURCE_COVERAGE_GAP_V1"


class RealSourceGapError(ValueError):
    pass


def inspect_source_gaps(partial):
    if type(partial) is not dict or partial.get("schema")!=PARTIAL_SCHEMA:
        raise RealSourceGapError("ACTUAL_RACECARD_SOURCE_REQUIRED")
    riders=partial.get("riders")
    if type(riders) is not list or len(riders) not in (7,9):
        raise RealSourceGapError("EXACT_SEVEN_OR_NINE_RIDERS_REQUIRED")
    n=len(riders)
    car_numbers=[r.get("car_number") for r in riders if type(r) is dict]
    if car_numbers!=list(range(1,n+1)):
        raise RealSourceGapError("OBSERVED_SOURCE_RIDER_ORDER_INVALID")
    registry=set(expected_keys(car_numbers))
    observed=partial.get("direct_verified_fields")
    if type(observed) is not dict or not set(observed).issubset(registry):
        raise RealSourceGapError("SOURCE_FIELDS_NOT_IN_347_REGISTRY")
    claimed_verified=partial.get("verified_registry_keys")
    claimed_unavailable=partial.get("unavailable_registry_keys")
    if (type(claimed_verified) is not list or
            type(claimed_unavailable) is not list or
            any(type(k) is not str for k in
                claimed_verified+claimed_unavailable) or
            len(set(claimed_verified))!=len(claimed_verified) or
            len(set(claimed_unavailable))!=len(claimed_unavailable) or
            set(claimed_verified)!=set(observed) or
            set(claimed_unavailable)!=registry-set(observed) or
            partial.get("registry_checked_count")!=len(registry) or
            partial.get("registry_verified_count")!=len(observed) or
            partial.get("registry_unavailable_count")!=
                    len(registry)-len(observed) or
            partial.get("full_347_or_437_verified") is not
                    (len(observed)==len(registry))):
        raise RealSourceGapError("SOURCE_347_COUNTS_OR_KEYS_MISMATCH")
    keys=set(observed)
    required_critical={
        *("race/"+key for key in CRITICAL_RACE),
        *(f"rider/{no}/{key}"
          for no in car_numbers for key in CRITICAL_RIDER),
    }
    observed_critical=required_critical & keys

    def count_required(mapping):
        all_required=set()
        for no in car_numbers:
            for feature in MODEL_REQUIRED:
                raw,_=mapping[feature]
                all_required.add(f"rider/{no}/{raw}")
        for env in ENV_REQUIRED:
            raw,_=ENV_MAP[env]
            all_required.add("race/"+raw)
        # Many target features may reuse one source field in A, so count
        # target input slots separately from distinct source fields.
        slots=n*len(MODEL_REQUIRED)+len(ENV_REQUIRED)
        supplied=sum(
            int(f"rider/{no}/{mapping[f][0]}" in keys)
            for no in car_numbers for f in MODEL_REQUIRED
        )+sum(int("race/"+ENV_MAP[f][0] in keys) for f in ENV_REQUIRED)
        return {
            "required_model_input_slots":slots,
            "source_observed_required_slots":supplied,
            "source_unobserved_required_slots":slots-supplied,
            "unique_required_origin_fields":len(all_required),
            "unique_required_origin_fields_observed":len(all_required&keys),
            "unique_required_origin_fields_missing":len(all_required-keys),
            "all_required_fields_observed":supplied==slots,
            "not_source_use_or_numeric_transform_admitted":True,
            "models_executed":0,
        }

    a=count_required(RIDER_MAP)
    b=count_required(RIDER_MAP_DISTINCT_B)
    return {
        "schema":SCHEMA,
        "race_id":partial["race_id"],
        "entrant_count":n,
        "inspection_registry_total":len(registry),
        "source_observed_registry_count":len(keys),
        "not_source_observed_registry_count":len(registry)-len(keys),
        "required_critical_slots":len(required_critical),
        "source_observed_critical_slots":len(observed_critical),
        "source_unobserved_critical_slots":
            len(required_critical)-len(observed_critical),
        "model_A_source_coverage":a,
        "model_B_source_coverage":b,
        "source_observation_not_provider_publication_proof":True,
        "source_usage_rights_independently_verified":False,
        "owner_private_actual_prediction_frozen":False,
        "real_pr71_four_models_ran":False,
        "public_payload":"COUNTS_ONLY_NO_RIDER_NAMES_OR_SOURCE_NUMBERS",
        "decision":"HOLD_MISSING_SOURCE_EVIDENCE",
    }
