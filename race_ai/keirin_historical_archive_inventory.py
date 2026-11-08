"""Owner-private historical source inventory; no fabricated PR71 inputs.

Only structural readiness. Do not equate legacy Top8, another model's 210
scores or sparse rider stats with the 12-per-rider+9-environment PR71 evidence.
The caller must additionally verify source rights, cutoff clocks, model-code
history, result authenticity and independent original forecast timestamps.
No actual entrant details or raw snapshots appear in the output.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256

from .comprehensive_four_sport_models import feature_inventory
from .keirin_preflight import expected_keys
from .keirin_result_delivery import canonical

SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_SOURCE_INVENTORY_V1"


class HistoricalInventoryError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise HistoricalInventoryError(code)


def inspect_archive_document(document):
    need(type(document) is dict, "HISTORICAL_ARCHIVE_DICT_REQUIRED")
    sha = sha256(canonical(document)).hexdigest()
    shape = document.get("schema")
    if (document.get("date_jst") == "2026-11-03"
            and document.get("source_version") == "20261103-am-reference-v1"
            and type(document.get("races")) is list):
        records = document["races"]
        need(1 <= len(records) <= 200 and
             all(type(r) is dict and
                 type(r.get("baseline_top8")) is list and
                 len(r["baseline_top8"]) == 8 for r in records),
             "LEGACY_EIGHT_PICK_RECORDS_INVALID")
        return {"source_kind":"LEGACY_TOP8_REFERENCE_ONLY",
                "historic_race_count":len(records),
                "full_other_model_rankings_present":False,
                "original_pr71_four_model_input_count":0,
                "ready_for_pr71_asof_comparison":False,
                "missing":"SOURCE_PRE_RACE_12_PER_RIDER_AND_9_ENV"}
    if (shape == "MATS2R_RESEARCH_SCENARIO_PREDICTION_V1"
            and type(document.get("all_210")) is list):
        need(len(document["all_210"]) == 210,
             "OTHER_MODEL_RANK_COUNT_UNEXPECTED")
        return {"source_kind":"OTHER_MODEL_210_RANK_RESEARCH",
                "historic_race_count":1,
                "full_other_model_rankings_present":True,
                "original_pr71_four_model_input_count":0,
                "ready_for_pr71_asof_comparison":False,
                "missing":"PR71_ORIGINAL_NORMALIZED_12_PER_RIDER_9_ENV"}
    if shape == "RACE_AI_KEIRIN_REAL_RIDER_SHADOW_ONE_SHOT_V1":
        rider_count=len(document.get("riders",[]))
        need(rider_count in (7,9),
             "LEGACY_SPARSE_RIDER_COUNT_INVALID")
        summary={"source_kind":"SPARSE_OBSERVED_RIDERS_NOT_PR71",
                "historic_race_count":1,
                "observed_riders":rider_count,
                "full_other_model_rankings_present":False,
                "original_pr71_four_model_input_count":0,
                "ready_for_pr71_asof_comparison":False,
                "missing":"PR71_347_FACTOR_AND_REQUIRED_MODEL_FEATURES"}
        # Only full archived numeric observations can be reconstructed.
        # Simple old placeholder fixtures remain explicitly unavailable.
        expected={"number","name","race_score","observed_4mo_starts",
                  "B_count","escape_count","makuri_count"}
        if (all(type(r) is dict and set(r)==expected for r in document["riders"])
                and "issued_at_jst" in document
                and "published_sales_cutoff_at" in document):
            from .keirin_historical_sparse_feature_probe import (
                HistoricalSparseProbeError, probe_saved_sparse_research
            )
            try:
                probe=probe_saved_sparse_research(document)["public_summary"]
            except (HistoricalSparseProbeError,ValueError,KeyError,TypeError):
                summary["strict_sparse_probe_status"]="BLOCKED_UNVERIFIED_SOURCE"
            else:
                summary["strict_sparse_probe_status"]="CANDIDATES_ONLY"
                summary["candidate_feature_counts"]=probe["counts"]
                summary["source_asof_independently_verified"]=False
                summary["source_rights_independently_verified"]=False
        else:
            summary["strict_sparse_probe_status"]="MISSING_NUMERIC_RAW_SOURCE"
        return summary
    if shape == "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1":
        evidence = document.get("facts",{}).get("pr71_evidenced_snapshot",{})
        participants=evidence.get("participants",[])
        racers=len(participants)
        need(racers in (7,9), "UNSUPPORTED_PR71_HISTORICAL_RIDER_COUNT")
        req=feature_inventory("keirin")
        rider_keys=set(req["common_required"]+req["sport_required"])
        environmental_keys=set(req["environment_required"])
        counts=Counter()
        for p in participants:
            f=p.get("features",{}) if type(p) is dict else {}
            for key in rider_keys:
                if key not in f: counts["missing_rider_required_observations"]+=1
        env=evidence.get("environment",{})
        missing_env=len(environmental_keys-set(env))
        audit=document.get("facts",{}).get("keirin_pre_race_audit_v1",{})
        n_checked=len(audit.get("items",[])) if type(audit) is dict else 0
        n_expected=len(expected_keys(document.get("starters",[])))
        full_shapes=(counts["missing_rider_required_observations"]==0 and
                     missing_env==0 and n_checked==n_expected)
        return {
            "source_kind":"PR71_SOURCE_SHAPE_AUDIT_REQUIRED",
            "historic_race_count":1,
            "model_required_observations_per_rider":len(rider_keys),
            "expected_required_rider_observations":racers*len(rider_keys),
            "missing_rider_required_observations":
                counts["missing_rider_required_observations"],
            "required_environment_observations":len(environmental_keys),
            "missing_environment_observations":missing_env,
            "factors_in_attached_audit":n_checked,
            "expected_factor_audit_count":n_expected,
            "complete_field_shapes_present":full_shapes,
            "eligible_for_real_model_replay_without_source_checks":False,
            "ready_for_pr71_asof_comparison":False,
            "missing":("VERIFY_RIGHTS_ASOF_CODE_VERSION_AND_EVIDENCE" if
                       full_shapes else "REQUIRED_PR71_INPUTS_MISSING")
        }
    return {"source_kind":"UNKNOWN_OR_RESULT_ONLY_ARCHIVE",
            "historic_race_count":0,
            "original_pr71_four_model_input_count":0,
            "ready_for_pr71_asof_comparison":False,
            "missing":"PR71_COHORT_SOURCE_MISSING"}


def private_batch_inventory(documents):
    need(type(documents) is list and 0 < len(documents) <= 200,
         "PRIVATE_HISTORICAL_DOCUMENT_LIST_REQUIRED")
    rows=[]
    for d in documents:
        row=inspect_archive_document(d)
        row["input_canonical_sha256"]=sha256(canonical(d)).hexdigest()
        rows.append(row)
    return {"schema":SCHEMA,
            "source_summaries":rows,
            "archived_historic_race_references":
                sum(r["historic_race_count"] for r in rows),
            "pr71_real_full_sources_admitted":0,
            "sparse_required_model_slots_reconstructed_as_candidates":sum(
                r.get("candidate_feature_counts",{}).get(
                    "required_candidates_normalized_not_admitted",0)
                for r in rows),
            "prospective_original_past_predictions_certified":0,
            "historical_asof_holdout_four_model_count":0,
            "invented_missing_inputs":0,
            "source_bytes_logged":False,
            "model_accuracy_claimed":False,
            "status":"HOLD_REQUIRED_ASOF_SOURCES_AND_INDEPENDENT_PROOFS"}
