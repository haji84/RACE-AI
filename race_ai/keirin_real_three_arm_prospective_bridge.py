"""Conservative handoff from verified six-phase research to three-arm evaluation.

Research branch only. A stays the existing PR71 saved original; B and C remain
separate private sidecars. Private local SHA readback is NOT encrypted Git
persistence, independent runner proof or formal forward scoring.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

from . import keirin_line_cohesion as line
from . import keirin_line_three_arm_audit as audit
from . import keirin_round_motivation as round_context
from . import keirin_round_six_phase_rank as six

SCHEMA = "RACE_AI_KEIRIN_RESEARCH_THREE_ARM_PREPARE_V1"


def _hold(rid, reason, *, stage_only=None):
    return {
        "schema": SCHEMA, "race_id": rid, "state": "HOLD",
        "reason": reason, "stage_only": stage_only, "stage_plus_line": None,
        "can_freeze_three_arm": False, "formal_accuracy_proven": False,
        "readback_or_official_result_verified": False,
    }


def prepare(*, context, original, plans, priors, athlete_ids_by_car,
            real_reviewed_line_history, line_config, computed_at,
            verify_pr71_original=None, verify_rider_identity=None,
            verify_historical_video_label=None):
    """Call existing B/C engine, never create a label from results or lineup."""
    rid = context.get("race_id") if type(context) is dict else None
    try:
        round_context.checked_context(context)
        need_original = (callable(verify_pr71_original) and
                         verify_pr71_original(original) is True)
        if not need_original:
            return _hold(rid, "NO_INDEPENDENT_PR71_ORIGINAL")
        if type(real_reviewed_line_history) is not list:
            return _hold(rid, "LINE_HISTORY_INPUT_NOT_A_VERIFIED_LIST")
        if type(athlete_ids_by_car) is not dict or not callable(verify_rider_identity):
            return _hold(rid, "CURRENT_VERIFIED_RIDER_IDS_REQUIRED")
        stage_only = six.forecast_shadow(
            context=context, snapshot=original, plans=plans, priors=priors,
            independently_verified_parent=verify_pr71_original)
        if stage_only.get("state") != "STAGE_CONDITIONED_SIX_PHASE_RESEARCH_ONLY":
            return _hold(rid, "STAGE_SIX_PHASE_FORECAST_UNAVAILABLE",
                         stage_only=stage_only)
        if not real_reviewed_line_history:
            return _hold(rid, "NO_INDEPENDENTLY_REVIEWED_PRIOR_LINE_EVENTS",
                         stage_only=stage_only)
        if not callable(verify_historical_video_label):
            return _hold(rid, "INDEPENDENT_HISTORICAL_VIDEO_READER_REQUIRED",
                         stage_only=stage_only)
        for entry in real_reviewed_line_history:
            # A public predicted-line row cannot be passed as a true ride.
            line.validate_label(entry)
            if verify_historical_video_label(entry) is not True:
                return _hold(rid, "HISTORICAL_LABEL_NOT_EXTERNALLY_AUTHENTICATED",
                             stage_only=stage_only)
        study = line.forecast_with_pair_evidence(
            context=context, snapshot=original, plans=plans, priors=priors,
            history=real_reviewed_line_history,
            athlete_ids_by_car=athlete_ids_by_car, config=line_config,
            independently_verify_label=verify_historical_video_label,
            independently_verify_identity=verify_rider_identity,
            independently_verify_original=verify_pr71_original,
            computed_at=computed_at)
        if study.get("state") != "RESEARCH_STAGE_PLUS_LINE":
            return _hold(rid, "HOLD_NO_ADMITTED_PAIR_WEIGHT_CHANGE",
                         stage_only=stage_only)
        before, after = study["stage_only"], study["stage_plus_line"]
        if before["parent_prediction_sha256"] != after["parent_prediction_sha256"]:
            return _hold(rid, "TRIPLET_PARENT_ORIGINAL_MISMATCH",
                         stage_only=stage_only)
        return {
            "schema": SCHEMA, "race_id": rid, "state": "RESEARCH_READY_FOR_PRIVATE_SIDE_CAR_FREEZE",
            "reason": None,
            "baseline_prediction_sha256": original["baseline_prediction_sha256"],
            "parent_input_sha256": original["input_sha256"],
            "stage_only": before,
            "stage_plus_line": after,
            "line_label_history_sha256": study["conditioning"]["private_history_sha256"],
            "line_study": study,
            "can_freeze_three_arm": True,
            "formal_accuracy_proven": False,
            "readback_or_official_result_verified": False,
        }
    except (line.LineHistoryError, round_context.RoundError, six.TacticalRoundError,
            KeyError, TypeError, ValueError):
        return _hold(rid, "UNVERIFIED_OR_INVALID_THREE_ARM_SOURCE_INPUT")


def freeze_two_shadows_once(prepared, *, private_dir):
    """Create B/C private 0600 sidecars and read bytes back in one job.

    Does NOT encrypt or persist anything across runners. Caller must later
    use existing owner-authorized AES storage and independent fresh runner.
    """
    if type(prepared) is not dict or prepared.get("state") != "RESEARCH_READY_FOR_PRIVATE_SIDE_CAR_FREEZE":
        raise ValueError("THREE_ARM_NOT_READY_FOR_PRE_CUTOFF_FREEZE")
    folder = Path(private_dir)
    if (not folder.is_dir() or folder.is_symlink() or
            folder.stat().st_mode & 0o077 != 0):
        raise ValueError("PRIVATE_0700_DIRECTORY_REQUIRED")
    rid = prepared["race_id"]
    sha = {}
    made = []
    for name in ("stage_only", "stage_plus_line"):
        record = prepared[name]
        if (record["race_id"] != rid or record["parent_prediction_sha256"] !=
                prepared["baseline_prediction_sha256"] or
                record["pre_race_input_sha256"] != prepared["parent_input_sha256"]):
            raise ValueError("THREE_ARM_INPUT_OR_PARENT_SHA_MISMATCH")
    try:
        for name in ("stage_only", "stage_plus_line"):
            path = folder / (name + ".json")
            if path.exists() or path.is_symlink():
                raise ValueError("CREATE_ONCE_SIDE_CAR_ALREADY_EXISTS")
            raw = six.canonical(prepared[name]) + b"\n"
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                         getattr(os, "O_NOFOLLOW", 0), 0o600)
            made.append(path)
            with os.fdopen(fd, "wb") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            if path.read_bytes() != raw:
                raise ValueError("PRIVATE_SIDE_CAR_SHA_READBACK_MISMATCH")
            sha[name] = sha256(raw).hexdigest()
        return {
            "schema": "RACE_AI_KEIRIN_LOCAL_TWO_RESEARCH_SIDECARS_V1",
            "race_id": rid,
            "baseline_prediction_sha256": prepared["baseline_prediction_sha256"],
            "stage_only_file_sha256": sha["stage_only"],
            "stage_plus_line_file_sha256": sha["stage_plus_line"],
            "private_local_readback": True,
            "existing_baseline_original_not_rewritten": True,
            "aes_gcm_persisted_across_runners": False,
            "independent_second_runner_sha_confirmed": False,
            "official_settlement_confirmed": False,
        }
    except (OSError, ValueError):
        for path in made:
            path.unlink(missing_ok=True)
        raise


def score_after_independent_archive_readback(*, frozen_original, line_study,
                                             original_receipt, round_receipt,
                                             line_receipt, context, result,
                                             verify_original=None, verify_round=None,
                                             verify_line=None, verify_video_labels=None,
                                             verify_result=None):
    """One comparison only AFTER all original/history/result verifiers pass."""
    return audit.compare_three(
        original=frozen_original, line_study=line_study,
        original_receipt=original_receipt, round_receipt=round_receipt,
        line_receipt=line_receipt, event_context=context, result=result,
        verify_original=verify_original, verify_round=verify_round,
        verify_line=verify_line, verify_video_labels=verify_video_labels,
        verify_result=verify_result)


def prepare_from_signed_tactical_packets(*, context, original, plans, priors,
                                        athlete_ids_by_car, signed_tactical_packets,
                                        line_config, computed_at,
                                        verify_pr71_original=None,
                                        verify_rider_identity=None,
                                        verify_owner_source_video=None,
                                        verify_roster_id_mapping=None,
                                        verify_independent_signed_reviewers=None):
    """Research-only end-to-end path: signed real video -> C history -> B/C.

    No unsigned or inferred data can be silently promoted. Each trusted
    verifier is a private owner-controlled implementation, never an
    application-supplied "independent=True" flag or AI-created test key.
    """
    from . import keirin_observed_follow_admission as intake
    rid=context.get("race_id") if type(context) is dict else None
    if type(signed_tactical_packets) is not list:
        return _hold(rid,"SIGNED_TACTICAL_PACKET_BATCH_REQUIRED")
    if not signed_tactical_packets:
        return prepare(
            context=context,original=original,plans=plans,priors=priors,
            athlete_ids_by_car=athlete_ids_by_car,
            real_reviewed_line_history=[],line_config=line_config,
            computed_at=computed_at,
            verify_pr71_original=verify_pr71_original,
            verify_rider_identity=verify_rider_identity)
    approved=[]
    try:
        for packet in signed_tactical_packets:
            item=intake.admit_for_C(
                packet=packet,
                verify_owner_source_video=verify_owner_source_video,
                verify_roster_id_mapping=verify_roster_id_mapping,
                verify_independent_signed_reviewers=verify_independent_signed_reviewers)
            approved.append(item["private_historical_label"])
    except (intake.FollowAdmissionError, KeyError, ValueError, TypeError):
        return _hold(rid,"HOLD_HISTORICAL_VIDEO_OR_SIGNED_REVIEW_NOT_VERIFIED")
    by_sha={row["label_sha256"]:row for row in approved}
    if len(by_sha)!=len(approved):
        return _hold(rid,"DUPLICATED_SIGNED_TACTICAL_HISTORY_LABEL")
    def trusted_admitted_label(row):
        try:
            # Matching the exact admitted SHA prevents a different row from
            # inheriting a previously verified receipt.
            line.validate_label(row)
            return (by_sha.get(row["label_sha256"])==row)
        except (line.LineHistoryError,KeyError,TypeError):
            return False
    result=prepare(
        context=context,original=original,plans=plans,priors=priors,
        athlete_ids_by_car=athlete_ids_by_car,
        real_reviewed_line_history=approved,line_config=line_config,
        computed_at=computed_at,
        verify_pr71_original=verify_pr71_original,
        verify_rider_identity=verify_rider_identity,
        verify_historical_video_label=trusted_admitted_label)
    result["signed_historical_packets_admitted"]=len(approved)
    result["historical_video_sha_verification_delegated_to_private_runner"]=True
    result["independent_human_label_claim_without_external_review"]=False
    return result
