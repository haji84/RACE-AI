"""Source-free post-exhibition BOAT P1 A/B candidate and independent receipt gates.

Existing owner Actions runner already binds official B and beforeinfo. This
module refuses to substitute display positions for race or preview courses and
refuses to call external sources, write originals, or claim independent receipt
authentication before a real GitHub upload/readback.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from math import fsum, isfinite
from hashlib import sha256
import json
import re
import subprocess
import shutil
from pathlib import Path

SCHEMA = "RACE_AI_BOAT_POST_EXHIBITION_AB_V1"
B_VARIANT = "B_SIX_COURSE_TACTICS"
SHA = re.compile(r"[a-f0-9]{64}\Z")
RACE = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
MODEL = "RACE_AI_BOAT_SIXWAY_OVERLAY_FROZEN_V1"
INPUT = "RACE_AI_BOAT_SIX_WAY_INTERACTIONS_V1"
JST = timezone(timedelta(hours=9))
MAX_WIRE = 512_000


def need(test, reason):
    if not test:
        raise ValueError("POST_EXHIBITION_AB_" + reason)


def clock(s):
    need(type(s) is str and len(s) <= 64, "AWARE_CLOCK_REQUIRED")
    try:
        out = datetime.fromisoformat(s.replace("Z", "+00:00"))
        need(out.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
        return out.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError):
        raise ValueError("POST_EXHIBITION_AB_AWARE_CLOCK_REQUIRED") from None


def digest(obj):
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()
    return sha256(data).hexdigest()


def normalized120(rows):
    need(type(rows) is list and len(rows) == 120, "ORIGINAL_120_REQUIRED")
    seen = set()
    scores = []
    for row in rows:
        need(type(row) is dict and {"ticket", "score"} <= set(row),
             "ORIGINAL_ROW_INVALID")
        ticket, score = row["ticket"], row["score"]
        need(type(ticket) is str and re.fullmatch(r"[1-6]-[1-6]-[1-6]", ticket)
             and len(set(ticket.split("-"))) == 3 and ticket not in seen
             and type(score) in (float, int) and isfinite(score) and score > 0,
             "ORIGINAL_TICKET_INVALID")
        seen.add(ticket)
        scores.append(score)
    need(abs(fsum(scores) - 1) < 1e-7, "ORIGINAL_NORMALIZATION_HOLD")
    return sorted(rows, key=lambda p: (-p["score"], p["ticket"]))


def _participant_map(beforeinfo):
    need(type(beforeinfo) is dict and beforeinfo.get("status") == "AVAILABLE"
         and beforeinfo.get("body_identity_verified") is True
         and beforeinfo.get("information_phase") == "pre_race"
         and type(beforeinfo.get("context")) is dict
         and beforeinfo["context"].get("status") == "PARSED"
         and beforeinfo["context"].get("roster_binding_status") == "VERIFIED",
         "OFFICIAL_EXHIBITION_SOURCE_HOLD")
    participants = beforeinfo["context"].get("participants")
    need(type(participants) is list and len(participants) == 6,
         "SIX_EXHIBITION_PARTICIPANTS_REQUIRED")
    mapping = {}
    for row in participants:
        lane, rid = row.get("lane"), row.get("registration_number")
        need(type(lane) is int and lane in range(1, 7) and lane not in mapping
             and type(rid) is str and re.fullmatch(r"[0-9]{4}", rid)
             and type(row.get("display_time")) in (int, float)
             and isfinite(row["display_time"]) and 4 < row["display_time"] < 12
             and type(row.get("tilt")) in (int, float)
             and isfinite(row["tilt"]) and -0.5 <= row["tilt"] <= 3
             and row.get("exhibition_st_status") in ("OK", "F", "L"),
             "EXHIBITION_MEASUREMENTS_INCOMPLETE")
        mapping[lane] = row
    need(len({p["registration_number"] for p in participants}) == 6,
         "EXHIBITION_RACER_DUPLICATE")
    return mapping


def _read_candidate(exhibition, baseline, context, frozen, *, at):
    now = clock(at)
    race = exhibition.get("race_id")
    match = RACE.fullmatch(race) if type(race) is str else None
    need(match and race == context.get("race_id") and race == baseline.get("race_id"),
         "RACE_IDENTITY_MISMATCH")
    cutoff = clock(exhibition["closed_at"])
    captured = clock(exhibition["captured_at"])
    need(cutoff.astimezone(JST).strftime("%Y%m%d") == match[1]
         and now.astimezone(JST).strftime("%Y%m%d") == match[1]
         and captured <= now < cutoff - timedelta(seconds=120),
         "EXHIBITION_OR_GENERATION_AFTER_CUTOFF")
    need(exhibition.get("source_sha256") and SHA.fullmatch(exhibition["source_sha256"])
         and context.get("schema") == INPUT
         and clock(context["as_of"]) == now
         and context.get("current_venue_rule_status") ==
             "CLAIMED_CURRENT_RECEIPT_REQUIRES_INDEPENDENT_AUTH",
         "TACTICAL_CONTEXT_HOLD")
    mapping = _participant_map(exhibition["beforeinfo"])
    need(exhibition["beforeinfo"]["race_id"] == race
         and clock(exhibition["beforeinfo"]["captured_at"]) <= now
         and exhibition["beforeinfo"]["source_sha256"] == exhibition["source_sha256"],
         "SOURCE_BYTES_OR_TIMING_MISMATCH")
    need(context.get("formation", {}).get("slow_count") in (1, 2, 3, 4, 5),
         "START_EXHIBITION_FORMATION_UNVERIFIED")
    entries = context.get("entry_tilt_cross_features")
    need(type(entries) is dict and set(entries) == {str(c) for c in range(1, 7)},
         "PROVISIONAL_ENTRY_COURSE_UNVERIFIED")
    formation = exhibition.get("formation_evidence")
    need(type(formation) is dict and formation.get("phase") == "start_exhibition"
         and formation.get("race_id") == race
         and formation.get("independently_source_verified") is True
         and type(formation.get("source_sha256")) is str
         and SHA.fullmatch(formation["source_sha256"])
         and clock(formation["captured_at"]) <= now
         and clock(formation["captured_at"]) < cutoff
         and formation.get("beforeinfo_source_sha256") == exhibition["source_sha256"]
         and type(formation.get("course_by_frame")) is dict
         and set(formation["course_by_frame"]) == {str(n) for n in range(1, 7)}
         and set(formation["course_by_frame"].values()) == set(range(1, 7)),
         "INDEPENDENT_EXHIBITION_COURSE_PROOF_MISSING")
    seen = set()
    for course in range(1, 7):
        row = entries[str(course)]
        frame = row.get("frame")
        need(type(frame) is int and frame in mapping and frame not in seen
             and row.get("racer_id") == mapping[frame]["registration_number"]
             and row.get("tilt_deg") == mapping[frame]["tilt"],
             "BOAT_FRAME_COURSE_OR_TILT_MISMATCH")
        seen.add(frame)
        # Start-exhibition phase order needs independently witnessed proof.
        # The public page's printed source-position number is insufficient.
        need(formation["course_by_frame"][str(frame)] == course,
             "EXHIBITION_COURSE_FORMATION_MISMATCH")
    need(type(frozen) is dict and frozen.get("schema") == MODEL
         and frozen.get("stage") == "P1" and frozen.get("frozen") is True
         and clock(frozen["trained_through"]) < now
         and race not in frozen.get("training_ids", []),
         "TRAINED_B_FROZEN_MODEL_REQUIRED")
    # The research score is a calibrated-unknown overlay, not a replacement A.
    a = baseline.get("prediction")
    need(type(a) is dict and type(baseline.get("physical_receipt")) is dict,
         "BASELINE_A_AND_RECEIPT_REQUIRED")
    original = baseline["physical_receipt"]
    need(type(original.get("source_sha256")) is str and SHA.fullmatch(original["source_sha256"])
         and clock(original["server_saved_at"]) < cutoff
         and clock(a["generated_at"]) <= clock(original["server_saved_at"])
         and clock(a["generated_at"]) <= now
         and clock(a["generated_at"]) >= captured
         and clock(original["server_saved_at"]) <= now
         and a.get("model_id") == "boat-display-rating-PL-reference-v1-UNVALIDATED",
         "A_ORIGINAL_PRE_CUTOFF_RECEIPT_REQUIRED")
    old_rank = normalized120(a.get("full_120"))
    for item in ["as_of", "cutoff_at"]:
        need(a.get(item) is not None, "A_CLOCKS_REQUIRED")
    need(clock(a["as_of"]) <= now and clock(a["cutoff_at"]) == cutoff
         and a.get("race_id") == race
         and old_rank[:8] == a.get("top8"),
         "A_TOP8_OR_CUTOFF_MISMATCH")
    need(context.get("qualifying_rank_and_point_gaps", {}).get("border_status") ==
         "CURRENT_RANK_ONLY_NOT_FINAL", "EVENT_QUALIFYING_BOARD_MISSING")
    return now, cutoff, old_rank, a


def create_candidate(exhibition, baseline, context, frozen, *, at, predictor):
    """Build B for the existing AES P1 sealing stage; does not save itself."""
    now, cutoff, original_120, a = _read_candidate(
        exhibition, baseline, context, frozen, at=at)
    need(callable(predictor), "SOURCE_FREE_PREDICTOR_REQUIRED")
    prepared = dict(stage="P1", cutoff_at=cutoff.isoformat(),
                    context=context,
                    baseline=dict(race_id=exhibition["race_id"],
                                  as_of=a["as_of"], full_120=original_120))
    b = predictor(prepared, frozen)
    need(type(b) is dict and b.get("schema") == "RACE_AI_BOAT_SIXWAY_OVERLAY_V1"
         and b.get("research_mode") == "EXPERIMENTAL_OVERLAY"
         and type(b.get("all_120")) is list and len(b["all_120"]) == 120,
         "B_PREDICTOR_INVALID")
    bdist = normalized120([dict(ticket=x["ticket"], score=x["probability"])
                           for x in b["all_120"]])
    need([x["ticket"] for x in bdist[:8]] ==
         [x["ticket"] for x in b["top8"]], "B_TOP8_DISTRIBUTION_MISMATCH")
    return dict(schema=SCHEMA, stage="P1", race_id=exhibition["race_id"],
                generated_at=now.isoformat(), cutoff_at=cutoff.isoformat(),
                source_sha256=exhibition["source_sha256"],
                A_original_sha256=baseline["physical_receipt"]["source_sha256"],
                A_prediction_sha256=digest(a),
                B_context_sha256=digest(context), B_model_sha256=digest(frozen),
                A_top8=[x["ticket"] for x in original_120[:8]],
                B_top8=[x["ticket"] for x in bdist[:8]],
                B_full120=bdist, source_get_count=0,
                actual_result_used=False, wagers_placed=False,
                independent_physical_save_readback=False,
                signed_source_authentication_proven_here=False)


def readback_candidate(c, receipt):
    """Validate later *actual* artifact metadata; no fictional save time."""
    need(type(c) is dict and c.get("schema") == SCHEMA
         and c.get("actual_result_used") is False, "CANDIDATE_INVALID")
    cutoff = clock(c["cutoff_at"])
    saved = clock(receipt["server_created_at"])
    need(clock(c["generated_at"]) <= saved < cutoff,
         "INDEPENDENT_SAVE_TOO_LATE")
    need(receipt.get("independently_authenticated") is True and
         receipt.get("payload_sha256") == digest(c) and
         type(receipt.get("artifact_id")) is int and receipt["artifact_id"] > 0,
         "INDEPENDENT_ARTIFACT_RECEIPT_MISSING")
    return dict(schema=SCHEMA, race_id=c["race_id"],
                state="B_ENCRYPTED_AND_RECEIPT_VERIFIED",
                server_saved_at=saved.isoformat(),
                payload_sha256=digest(c), artifact_id=receipt["artifact_id"],
                official_forecast=False, actual_result_used=False,
                external_source_authentication_separate=True)


def node_predict(record, frozen, *, script_path=None):
    """The exact source-free JS engine runs inside existing owner runner only."""
    expected = Path(__file__).with_name("boat_six_way_probability_overlay.cjs").resolve()
    script_path = Path(script_path or expected).resolve()
    need(script_path == expected and script_path.is_file(),
         "JS_ENGINE_PATH_INVALID")
    node = shutil.which("node")
    need(node is not None, "NODE_RUNTIME_UNAVAILABLE")
    payload = json.dumps({"record": record, "frozen": frozen},
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    need(len(payload.encode()) <= MAX_WIRE, "B_INPUT_BOUND")
    snippet = ("const m=require(process.argv[1]);let raw='';"
               "process.stdin.setEncoding('utf8');"
               "process.stdin.on('data',s=>raw+=s);"
               "process.stdin.on('end',()=>{const x=JSON.parse(raw);"
               "process.stdout.write(JSON.stringify(m.predict(x.record,x.frozen)))});")
    p = subprocess.run([node, "-e", snippet, str(script_path)],
                       input=payload, text=True, capture_output=True,
                       timeout=10, check=False, env={"PATH": "/usr/bin:/bin"})
    need(p.returncode == 0 and len(p.stdout.encode()) <= MAX_WIRE,
         "SOURCE_FREE_B_EXECUTION_FAILED")
    return json.loads(p.stdout)



def prepare_round(current, originals, baseline_receipt, research_by_race, *,
                  generated_at, predictor=node_predict):
    """Attach source-free B shadows to the EXISTING encrypted P1 round payload.

    Prepared inputs are private already-attested facts produced by a separate
    approved source owner. No automatic external fetch and no synthetic fill.
    Fail one physical race to HOLD without preventing other ready races.
    """
    need(type(current) is dict and type(originals) is list and
         type(research_by_race) is dict, "ROUND_INPUT_INVALID")
    need(set(research_by_race) <= set(current), "RESEARCH_RACE_NOT_IN_CURRENT_P1")
    now = clock(generated_at)
    results, holds = [], []
    for rid in sorted(current):
        if rid not in research_by_race:
            holds.append({"race_id": rid, "status": "HOLD_RESEARCH_FACTS_NOT_PREPARED"})
            continue
        item = current[rid]
        source = research_by_race[rid]
        need(type(source) is dict and set(source) == {
            "context", "frozen_model", "formation_evidence"},
            "PREPARED_SOURCE_FIELDS_INVALID")
        originals_A = [row for row in originals if
                       row.get("race_id") == rid and
                       row.get("model_id") ==
                       "boat-display-rating-PL-reference-v1-UNVALIDATED"]
        if len(originals_A) != 1 or baseline_receipt is None:
            holds.append({"race_id": rid, "status": "HOLD_INDEPENDENT_A_MISSING"})
            continue
        a = originals_A[0]
        p = dict(a["prediction"])
        p["generated_at"] = a["dispatch_generated_at"]
        p["as_of"] = a["dispatch_generated_at"]
        p["cutoff_at"] = a["cutoff_at"]
        p["race_id"] = rid
        before = item["beforeinfo"]
        exhibition = dict(
            race_id=rid, closed_at=item["program"]["closed_at"],
            source_sha256=before["source_sha256"],
            captured_at=before["captured_at"],
            beforeinfo=before,
            formation_evidence=source["formation_evidence"])
        original = dict(prediction=p,physical_receipt=dict(
            source_sha256=baseline_receipt["payload_sha256"],
            server_saved_at=baseline_receipt["created_at"]))
        try:
            shadow = create_candidate(
                exhibition,original,source["context"],source["frozen_model"],
                at=now.isoformat(),predictor=predictor)
            results.append(shadow)
        except (ValueError, KeyError, TypeError, OSError,
                subprocess.SubprocessError) as exc:
            # Private source may be incomplete or beyond the deadline.
            reason = str(exc)
            if not reason.startswith("POST_EXHIBITION_AB_"):
                reason = "POST_EXHIBITION_AB_RESEARCH_INPUT_OR_ENGINE_HOLD"
            holds.append({"race_id": rid,"status":reason[:120]})
    return dict(schema="RACE_AI_POST_EXHIBITION_AB_ENCRYPTED_ROUND_V1",
                generated_at=now.isoformat(),pairs=results,holds=holds,
                attempted=len(current),candidate_pairs=len(results),
                held_races=len(holds),source_provider_requests=0,
                originals_overwritten=False,actual_results_used=False)


def verify_round_readback(study, receipt):
    """Validate each independent GitHub artifact receipt after AES decrypt."""
    need(type(study) is dict and study.get("schema") ==
         "RACE_AI_POST_EXHIBITION_AB_ENCRYPTED_ROUND_V1"
         and study.get("source_provider_requests") == 0
         and study.get("originals_overwritten") is False,
         "ROUND_READBACK_CONTRACT_INVALID")
    seen = set()
    saved, late = 0, 0
    for pair in study["pairs"]:
        rid = pair.get("race_id")
        need(rid not in seen, "DUPLICATE_B_RACE_IN_ARTIFACT")
        seen.add(rid)
        try:
            readback_candidate(pair, receipt | {"payload_sha256": digest(pair)})
            saved += 1
        except ValueError as exc:
            if str(exc) == "POST_EXHIBITION_AB_INDEPENDENT_SAVE_TOO_LATE":
                late += 1
            else:
                raise
    need(len(study["pairs"]) == study["candidate_pairs"] and
         len(study["holds"]) == study["held_races"] and
         study["candidate_pairs"] + study["held_races"] == study["attempted"],
         "ROUND_READBACK_COUNTS_INVALID")
    return dict(schema=study["schema"],state="RESEARCH_AB_INDEPENDENT_READBACK",
                attempted_races=study["attempted"],
                b_saved_before_cutoff=saved,
                b_saved_after_cutoff_held=late,
                held_races=len(study["holds"]),source_provider_requests=0,
                old_forecast_originals_changed=False,
                production_promoted=False,
                official_results_used=False)
