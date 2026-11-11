"""Historical keirin source triage: detect count conflicts and hindsight leakage.

No source GET, no rider score invention, no video decoding, no credential/rights
claims. Research-only; read actual past data privately, keep raw data out of
public GitHub. Resurfacing and nearby station weather are contextual, not
athlete-specific track fitness or a same-day pre-cutoff forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
import math

SCHEMA = "RACE_AI_KEIRIN_HISTORICAL_CONTEXT_GATES_V1"


class HistoricalContextError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise HistoricalContextError(message)


def aware(value):
    require(type(value) is str, "SOURCE_TIMESTAMP_REQUIRED")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        require(parsed.utcoffset() is not None, "SOURCE_TIMEZONE_REQUIRED")
        return parsed.astimezone(timezone.utc)
    except (ValueError,TypeError) as exc:
        raise HistoricalContextError("SOURCE_TIMESTAMP_INVALID") from exc


def compare_racecard_samples(rows, *, race_id, first_source_url, other_source_url):
    """Do not impute win/place stats when denominators differ between sources.

    Starts can include unclassified statuses, cancellations or distinct
    lookback conventions. A discrepancy is NOT proof that either provider
    is wrong, nor that the missing observations are losses.
    """
    require(type(race_id) is str and len(race_id)==12
            and race_id.isdigit() and type(rows) is list
            and len(rows) in (7,9) and
            type(first_source_url) is str and first_source_url.startswith("https://")
            and type(other_source_url) is str and other_source_url.startswith("https://"),
            "RACECARD_SOURCE_IDENTITY_REQUIRED")
    by_n={}
    for p in rows:
        require(type(p) is dict and set(p)=={
            "number","first_reported_starts","other_reported_starts",
            "other_wins","other_seconds","other_thirds","other_unplaced"
        }, "UNRELIABLE_RACECARD_ROW_SHAPE")
        n=p["number"]
        vals=[p[k] for k in ("first_reported_starts","other_reported_starts",
            "other_wins","other_seconds","other_thirds","other_unplaced")]
        require(type(n) is int and 1<=n<=9 and n not in by_n
                and all(type(v) is int and v>=0 for v in vals)
                and vals[0]>=1 and vals[1]>=1,
                "DUPLICATED_OR_INVALID_RACECARD_SAMPLES")
        counted=sum(vals[2:])
        require(counted <= vals[1], "OTHER_FINISH_COUNTS_EXCEED_STARTS")
        by_n[n]={
            "first_source_starts":vals[0],
            "other_source_starts":vals[1],
            "other_source_finish_counts_total":counted,
            "different_source_starts":vals[0]!=vals[1],
            "unknown_other_finish_status_count":vals[1]-counted,
            "other_provider_starts_accounted":vals[1]==counted,
            "cross_source_denominator_matched":vals[0]==vals[1],
            "candidate_win_rate_other_source":vals[2]/vals[1],
            "candidate_top3_rate_other_source":sum(vals[2:5])/vals[1],
        }
    require(sorted(by_n)==list(range(1,len(rows)+1)),
            "RACECARD_ROSTER_NOT_COMPLETE")
    mismatched=sum(r["different_source_starts"] for r in by_n.values())
    residual=sum(r["unknown_other_finish_status_count"] for r in by_n.values())
    return {
        "schema":SCHEMA,
        "race_id":race_id,
        "providers_cited":[first_source_url,other_source_url],
        "riders_checked":len(rows),
        "denominators_disagree_count":mismatched,
        "uncategorized_finish_statuses_count":residual,
        "rider_summaries_by_number":by_n,
        "rate_candidates_not_source_admitted":True,
        "source_publication_before_target_cutoff_independently_proven":False,
        "reason_for_residual_finishes_verified":False,
        "same_definition_and_time_window_proven":False,
        "safe_to_merge_sources_into_pr71_without_review":False,
        "state":"HOLD_SOURCE_DENOMINATOR_DEFINITION" if
            (mismatched or residual) else "ARITHMETICALLY_CONSISTENT_ASOF_UNVERIFIED",
    }


def contextual_track_geometry(record, *, race_cutoff):
    """Immutable venue facts, not rider-specific bank_fit and no new ratio."""
    require(type(record) is dict and set(record)=={
        "venue","source_url","source_document_date",
        "track_length_m","straight_length_m","center_cant_deg",
        "home_width_m","surface_resurfaced_month",
    } and record["venue"]=="松山"
        and type(record["source_url"]) is str
        and record["source_url"].startswith("https://"),
        "VENUE_SOURCE_UNSUPPORTED")
    cutoff=aware(race_cutoff)
    try:
        source_date=date.fromisoformat(record["source_document_date"])
        resurfaced=datetime.strptime(
            record["surface_resurfaced_month"],"%Y-%m").date()
    except (ValueError,TypeError) as exc:
        raise HistoricalContextError("VENUE_DATE_OR_MONTH_INVALID") from exc
    # Compare publication *dates*, never invent hour/minute of publication
    # or exact resurfacing day. Require entire resurfacing month to precede.
    local_cutoff=cutoff.astimezone(timezone(timedelta(hours=9))).date()
    require(source_date < local_cutoff and
            (resurfaced.year,resurfaced.month) <
                (local_cutoff.year,local_cutoff.month),
            "VENUE_METADATA_CREATED_AFTER_RACE")
    for k in ("track_length_m","straight_length_m","center_cant_deg",
              "home_width_m"):
        require(type(record[k]) in (int,float) and
                math.isfinite(record[k]) and record[k]>0,
                "VENUE_GEOMETRY_INVALID")
    require(record["track_length_m"]==400.0
            and record["straight_length_m"]==58.6
            and 30 <= record["center_cant_deg"] <= 40,
            "VENUE_GEOMETRY_OUTSIDE_VERIFIED_MATSUYAMA")
    return {
        "schema":SCHEMA,"venue":"松山",
        "physical_track_context":{k:record[k] for k in (
            "track_length_m","straight_length_m","center_cant_deg",
            "home_width_m")},
        "surface_resurfaced_prior_to_race":True,
        "source_date_before_target_race":True,
        "rider_bank_fit_source_observed":False,
        "pr71_bank_steepness_normalization_preagreed":False,
        "pr71_rider_bank_fit_admitted":False,
        "pre_race_static_geometry_research_candidate":True,
    }


def classify_weather_evidence(*, issued_or_initialised_at, first_available_at,
                              forecast_valid_at, race_cutoff,
                              provider_availability_attested=False,
                              weather_kind="archived_model_forecast"):
    """Weather run time is NOT the provider's publication/release time.

    A station reading after race, ERA5 retrospective reanalysis, or current
    weather page is forbidden as prediction input. A historic forecast run
    with unverified publication time remains RESEARCH_ASOF_CANDIDATE_ONLY.
    """
    init=aware(issued_or_initialised_at)
    valid=aware(forecast_valid_at)
    cutoff=aware(race_cutoff)
    if weather_kind!="archived_model_forecast":
        return {"kind":weather_kind,"research_context":True,
                "asof_model_feature_accepted":False,
                "reason":"POST_RACE_OBSERVATION_NOT_ORIGINAL_FORECAST"}
    avail=aware(first_available_at) if first_available_at else None
    require(init <= valid and cutoff <= valid+timedelta(hours=1),
            "WEATHER_RUN_OR_VALIDITY_UNRELATED_TO_RACE")
    passed = (avail is not None and init<=avail<cutoff and
              provider_availability_attested is True)
    return {
        "kind":weather_kind,
        "weather_run_initialised_before_cutoff":init<cutoff,
        "actual_first_publication_time_verified":passed,
        "release_timing_attestation_claimed":passed,
        "asof_model_feature_accepted":False,
        "research_asof_candidate_only":init<cutoff,
        "legal_source_rights_and_independent_witness_external":True,
        "reason":("PRE_CUTOFF_RELEASE_TIME_CONSISTENT_NOT_AUTHENTICATED"
                  if passed else "WEATHER_MODEL_INIT_NOT_EVIDENCE_OF_PUBLIC_RELEASE"),
    }


def classify_prior_race_video(*, video_race_end_at, target_cutoff_at,
                              video_first_available_at=None,
                              source_rights_verified=False,
                              actual_frames_available=False,
                              replay_segments_identified=False):
    """Only older race footage may TRAIN features for a later target race."""
    race_end=aware(video_race_end_at)
    cutoff=aware(target_cutoff_at)
    availability=aware(video_first_available_at) if video_first_available_at else None
    eligible=(race_end<cutoff and availability is not None and
              availability<cutoff and source_rights_verified is True and
              actual_frames_available is True and
              replay_segments_identified is True)
    return {
        "historical_video_happened_before_target":race_end<cutoff,
        "video_publication_before_target_proven":
            availability is not None and availability<cutoff,
        "rights_to_process_verified":source_rights_verified is True,
        "actual_frames_inspected":actual_frames_available is True,
        "replay_segments_and_duplicate_frames_checked":
            replay_segments_identified is True,
        "eligible_as_historical_training_candidate":eligible,
        "measured_acceleration_mps2":None,
        "measured_stamina_score":None,
        "real_previous_race_lap_1_4_frame_grounding":False,
        "result_race_same_as_target_forbidden":not race_end<cutoff,
        "status":"VIDEO_EVIDENCE_READY_FOR_LABEL_REVIEW" if eligible else
                 "VIDEO_EVIDENCE_HOLD",
    }
