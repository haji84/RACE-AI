"""Owner-saved generated race predictions, independent of unfinished PR71 models.

The 2026-11-17 71R v3 JSON is a real owner-saved ChatGPT research output,
NOT an autonomous four-model PR71 forecast. This module validates the complete
raw file bytes, converts the race picks into source-neutral research inputs
and marks all non-attested cutoffs as unverified. It never turns planned start
into a confirmed sales cutoff or past-result hindsight into a forecast.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from . import keirin_round_motivation as round_context

SCHEMA = "RACE_AI_KEIRIN_EXISTING_GENERATED_FORECAST_SOURCE_V1"
KIND = "OWNER_SAVED_TACTICAL_71R_V3"
ACTIVE_SOURCE_ID = "existing-generated-keirin-research-v3"
HEX = re.compile(r"^[0-9a-f]{64}$")
SHORT_ID = re.compile(r"^([0-9]{2})-([0-9]{2})$")
CLOCK = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
JST = timezone(timedelta(hours=9))
PHASES = ("INITIAL", "BELL", "FINAL_HOME", "FINAL_BACK",
          "FOURTH_CORNER", "GOAL")


class AvailableSourceError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise AvailableSourceError(reason)


def _moment(value):
    try:
        return round_context._timestamp(value)
    except (round_context.RoundError, ValueError, TypeError):
        raise AvailableSourceError("ORIGINAL_SOURCE_CLOCK_INVALID") from None


def _cars(value):
    return (type(value) is list and len(value)==3 and
            all(type(v) is int and 1<=v<=9 for v in value) and
            len(set(value))==3)


def import_owner_71r_v3(raw_bytes, *, expected_source_sha256):
    """Read owner-private bytes; metadata is NOT an independent cutoff witness."""
    need(type(raw_bytes) is bytes and len(raw_bytes)<=4_000_000 and
         type(expected_source_sha256) is str and
         HEX.fullmatch(expected_source_sha256) and
         sha256(raw_bytes).hexdigest()==expected_source_sha256,
         "OWNER_GENERATED_FORECAST_BYTES_SHA_MISMATCH")
    try:
        doc=json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise AvailableSourceError("OWNER_GENERATED_FORECAST_JSON_INVALID") from None
    need(type(doc) is dict and doc.get("timezone")=="Asia/Tokyo" and
         type(doc.get("date")) is str and
         type(doc.get("races")) is list and 1<=len(doc["races"])<=120,
         "OWNER_71R_ROOT_SCHEMA_INVALID")
    try:
        day=datetime.strptime(doc["date"],"%Y-%m-%d").date()
    except ValueError:
        raise AvailableSourceError("OWNER_71R_DATE_INVALID") from None
    generated=doc.get("generated_at")
    observed=doc.get("original_pre_race_snapshot_time")
    need(type(generated) is str and type(observed) is str and
         _moment(observed)<=_moment(generated) and
         isinstance(doc.get("original_pre_race_snapshot_sha256"),str) and
         HEX.fullmatch(doc["original_pre_race_snapshot_sha256"]),
         "OWNER_71R_ORIGINAL_INPUT_SHA_OR_TIME_INVALID")
    need(doc.get("official_results_status") in ("NOT_CONNECTED",None) and
         doc.get("pre_race_rank_1_changed") in (False,None),
         "OWNER_71R_NOT_THE_REGISTERED_SOURCE_VERSION")
    parsed=[]
    seen=set()
    for row in doc["races"]:
        need(type(row) is dict and type(row.get("id")) is str and
             SHORT_ID.fullmatch(row["id"]) is not None and
             type(row.get("race")) is int and 1<=row["race"]<=12 and
             type(row.get("venue")) is str and
             type(row.get("start")) is str and CLOCK.fullmatch(row["start"]) and
             type(row.get("v3_publication_time")) is str and
             _moment(row["v3_publication_time"])==_moment(generated) and
             row.get("independent_cutoff_verified") is False,
             "OWNER_71R_ROW_ID_TIME_OR_CUTOFF_INVALID")
        venue,race=SHORT_ID.fullmatch(row["id"]).groups()
        need(int(race)==row["race"],"OWNER_71R_CAR_VENUE_RACE_MISMATCH")
        rid=day.strftime("%Y%m%d")+venue+race
        need(rid not in seen,"OWNER_71R_DUPLICATE_RACE")
        seen.add(rid)
        picks=row.get("ranked_picks")
        need(type(picks) is list and 1<=len(picks)<=12 and
             row.get("v3_count")==len(picks),
             "OWNER_71R_RANKED_TICKETS_MISSING")
        triples=[]
        for number,item in enumerate(picks,1):
            need(type(item) is dict and item.get("rank")==number and
                 _cars(item.get("cars")),
                 "OWNER_71R_RANK_OR_CAR_INVALID")
            triples.append(item["cars"])
        need(len({tuple(t) for t in triples})==len(triples),
             "OWNER_71R_DUPLICATE_COMBINATION")
        phase_notes=row.get("position_hypotheses")
        need(type(phase_notes) is list and len(phase_notes)==6 and
             all(type(x) is str and bool(x.strip()) for x in phase_notes),
             "OWNER_71R_SIX_PHASE_NOTES_REQUIRED")
        start=datetime.combine(
            day,datetime.strptime(row["start"],"%H:%M").time(),tzinfo=JST)
        # The planned start is for retrospective diagnostics ONLY.
        # It is NOT the official sales cutoff and never makes a race eligible.
        past_start=_moment(generated)>=start.astimezone(timezone.utc)
        need(row.get("expanded_after_planned_start") is past_start,
             "OWNER_71R_POST_START_MARKER_MISMATCH")
        parsed.append({
            "schema":SCHEMA,
            "race_id":rid,
            "venue":row["venue"],
            "race_number":row["race"],
            "source_kind":KIND,
            "source_forecast_document_sha256":expected_source_sha256,
            "input_snapshot_sha256":doc["original_pre_race_snapshot_sha256"],
            "original_input_observed_at":observed,
            "forecast_generated_at":generated,
            "planned_start_at":start.isoformat(),
            "forecast_after_planned_start":past_start,
            "ranked_tickets":triples,
            "six_phase_hypothesis_notes":{
                phase:text for phase,text in zip(PHASES,phase_notes)},
            "six_phase_notes_are_hypotheses_not_verified_positions":True,
            "official_cutoff_at":None,
            "official_cutoff_independently_authenticated":False,
            "official_result_authenticated":False,
            "formal_prospective_eligible":False,
        })
    return {
        "schema":"RACE_AI_KEIRIN_EXISTING_71R_IMPORT_SUMMARY_V1",
        "source_kind":KIND,
        "source_sha256":expected_source_sha256,
        "source_input_snapshot_sha256":doc["original_pre_race_snapshot_sha256"],
        "races":parsed,
        "race_count":len(parsed),
        "candidate_ticket_count":sum(len(x["ranked_tickets"]) for x in parsed),
        "generated_after_planned_start_count":sum(
            x["forecast_after_planned_start"] for x in parsed),
        "cutoff_attested_race_count":0,
        "autonomous_4model_forecast_count":0,
        "not_formal_forward_accuracy":True,
    }


def make_stage_snapshot_from_generated(*, record, context, official_line_receipt,
                                       starting_order, line_groups,
                                       verify_owner_original=None,
                                       verify_source_roster=None,
                                       verify_official_cutoff=None):
    """Supply the CURRENT six-phase engine without claiming a PR71 parent.

    Caller must independently verify original bytes, all starters/line source,
    scheduled cutoff and provenance. Without any witness this fails closed.
    """
    from . import keirin_round_six_phase_rank as six
    need(type(record) is dict and record.get("schema")==SCHEMA and
         record.get("source_kind")==KIND and
         not record.get("forecast_after_planned_start") and
         record.get("formal_prospective_eligible") is False,
         "OWNER_GENERATED_SOURCE_NOT_VALIDATED")
    round_context.checked_context(context)
    need(record["race_id"]==context["race_id"] and
         record["input_snapshot_sha256"]==context["parent_input_sha256"] and
         _moment(record["original_input_observed_at"])==_moment(context["as_of"]) and
         _moment(record["forecast_generated_at"])<=
             _moment(context["official_cutoff_at"])-timedelta(seconds=65),
         "OWNER_GENERATED_FORECAST_CUTOFF_OR_INPUT_MISMATCH")
    try:
        accepted=(callable(verify_owner_original) and
                  verify_owner_original(record) is True and
                  callable(verify_source_roster) and
                  verify_source_roster(official_line_receipt) is True and
                  callable(verify_official_cutoff) and
                  verify_official_cutoff(context) is True)
    except Exception:
        accepted=False
    need(accepted,"INDEPENDENT_GENERATED_ORIGINAL_ROSTER_AND_CUTOFF_REQUIRED")
    need(type(official_line_receipt) is dict and
         official_line_receipt.get("race_id")==context["race_id"] and
         official_line_receipt.get("source_input_sha256")==context["parent_input_sha256"] and
         type(official_line_receipt.get("observed_at")) is str and
         _moment(official_line_receipt["observed_at"])<=_moment(context["as_of"]),
         "GENERATED_LINE_INPUT_SOURCE_OR_TIME_MISMATCH")
    snapshot={
        "race_id":record["race_id"],
        "input_sha256":record["input_snapshot_sha256"],
        "baseline_model_id":ACTIVE_SOURCE_ID,
        "baseline_prediction_sha256":record["source_forecast_document_sha256"],
        "as_of":context["as_of"],
        "official_cutoff_at":context["official_cutoff_at"],
        "starting_order":starting_order,
        "line_groups":line_groups,
        "baseline_top12":record["ranked_tickets"],
    }
    six._lines(snapshot,context)
    return snapshot
