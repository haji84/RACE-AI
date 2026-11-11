"""Count real WINTICKET source coverage against the EXISTING PR71 347 gate.

No model estimates, new coefficients, rights grants or rider values leave this
module. The target race might still be genuinely pre-cutoff; source-availability
and independent provider publication/permission are separate requirements.
"""
from __future__ import annotations

from .keirin_preflight import CRITICAL_RACE, CRITICAL_RIDER, expected_keys
from .keirin_allowed_delivery import (
    MODEL_REQUIRED, ENV_REQUIRED, ENV_MAP, RIDER_MAP, RIDER_MAP_DISTINCT_B,
    PermittedDeliveryError, _convert,
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
    # The historical venue differential is a research-B-only source origin.
    # Legacy A treats venue compatibility as three unrelated source aliases;
    # counting a B-only prior as an A observation would silently change the
    # frozen baseline. Preserve the A accounting and the distinct B mapping.
    b_only_venue_evidence = partial.get('prior_venue_compatibility_input_evidence', {})
    if type(b_only_venue_evidence) is not dict:
        raise RealSourceGapError('B_ONLY_VENUE_SOURCE_EVIDENCE_INVALID')
    for key, info in b_only_venue_evidence.items():
        if (type(key) is not str or
                not key.startswith('rider/') or
                not key.endswith('/venue_and_distance_compatibility') or
                key not in keys or
                type(info) is not dict or info.get('value') != observed[key] or
                info.get('approved_for_pr71_input') is not False or
                info.get('independent_source_rights_verified') is not False):
            raise RealSourceGapError('B_ONLY_VENUE_SOURCE_EVIDENCE_INVALID')
    # A historical six-event finish-rank delta is a B-only research origin.
    # Do not reuse it as verified legacy-A rider strength or fill absent
    # acceleration, stamina or tactical behavior.
    b_only_form_evidence = partial.get('prior_recent_form_input_evidence', {})
    if type(b_only_form_evidence) is not dict:
        raise RealSourceGapError('B_ONLY_FORM_SOURCE_EVIDENCE_INVALID')
    for key, info in b_only_form_evidence.items():
        if (type(key) is not str or not key.startswith('rider/') or
                not key.endswith('/recent_strength_or_form_change') or
                key not in keys or key in b_only_venue_evidence or
                type(info) is not dict or info.get('value') != observed[key] or
                info.get('sample_n') != 6 or
                info.get('recent_sample_n') != 3 or
                info.get('baseline_sample_n') != 3 or
                info.get('approved_for_pr71_input') is not False or
                info.get('independent_source_rights_verified') is not False):
            raise RealSourceGapError('B_ONLY_FORM_SOURCE_EVIDENCE_INVALID')
    legacy_a_keys = keys-set(b_only_venue_evidence)-set(b_only_form_evidence)
    required_critical={
        *("race/"+key for key in CRITICAL_RACE),
        *(f"rider/{no}/{key}"
          for no in car_numbers for key in CRITICAL_RIDER),
    }
    observed_critical=required_critical & keys

    def count_required(mapping, source_keys):
        # Presence alone is not evidence of a usable numeric model input.
        # Reuse the existing rights-gated adapter's numeric conversion rules
        # for diagnostic validation only. This DOES NOT grant source rights,
        # source publication timestamps, completeness, or model inference.
        for no in car_numbers:
            for feature in MODEL_REQUIRED:
                field,transform=mapping[feature]
                key=f"rider/{no}/{field}"
                if key in source_keys:
                    try:
                        if transform=="count_rate":
                            raise PermittedDeliveryError(
                                "COUNT_RATE_DENOMINATOR_NOT_IN_PARTIAL_SOURCE")
                        _convert(observed[key],1,transform)
                    except (PermittedDeliveryError,ValueError,OverflowError,TypeError):
                        raise RealSourceGapError(
                            "SOURCE_MODEL_INPUT_VALUE_NOT_ADMISSIBLE") from None
        for feature in ENV_REQUIRED:
            field,transform=ENV_MAP[feature]
            key="race/"+field
            if key in source_keys:
                try:
                    if transform=="count_rate":
                        raise PermittedDeliveryError(
                            "COUNT_RATE_DENOMINATOR_NOT_IN_PARTIAL_SOURCE")
                    _convert(observed[key],1,transform)
                except (PermittedDeliveryError,ValueError,OverflowError,TypeError):
                    raise RealSourceGapError(
                        "SOURCE_MODEL_INPUT_VALUE_NOT_ADMISSIBLE") from None
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
            int(f"rider/{no}/{mapping[f][0]}" in source_keys)
            for no in car_numbers for f in MODEL_REQUIRED
        )+sum(int("race/"+ENV_MAP[f][0] in source_keys) for f in ENV_REQUIRED)
        # Group missing model input slots by the required source field name.
        # This is a PRIVATE/COUNT-ONLY acquisition plan: no athlete IDs,
        # source measurements, guessed values or invented rights grants.
        deficit={}
        for no in car_numbers:
            for feature in MODEL_REQUIRED:
                field=mapping[feature][0]
                if f"rider/{no}/{field}" not in source_keys:
                    deficit[field]=deficit.get(field,0)+1
        for feature in ENV_REQUIRED:
            field="race/"+ENV_MAP[feature][0]
            if field not in source_keys:
                deficit[field]=deficit.get(field,0)+1
        ranked_deficit=dict(sorted(
            deficit.items(),key=lambda entry:(-entry[1],entry[0])))
        if sum(ranked_deficit.values()) != slots-supplied:
            raise RealSourceGapError("MODEL_SOURCE_GAP_ACCOUNTING_MISMATCH")
        return {
            "missing_model_input_slots_by_source_field":ranked_deficit,
            "required_model_input_slots":slots,
            "source_observed_required_slots":supplied,
            "source_unobserved_required_slots":slots-supplied,
            "unique_required_origin_fields":len(all_required),
            "unique_required_origin_fields_observed":len(all_required&source_keys),
            "unique_required_origin_fields_missing":len(all_required-source_keys),
            "all_required_fields_observed":supplied==slots,
            "not_source_use_or_numeric_transform_admitted":True,
            "models_executed":0,
        }

    a=count_required(RIDER_MAP, legacy_a_keys)
    b=count_required(RIDER_MAP_DISTINCT_B, keys)
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
