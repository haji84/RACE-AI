"""Resolve current BOAT race cutoffs without confusing start delays with deadlines.

This is an offline decision on already authenticated, saved official inputs.
No source GET, result-driven rescheduling, model scoring, old forecast changes,
or claim that an actual voting-close instant was observed.
"""
from datetime import datetime, timedelta
import re

from .boat_deadline_queue import JST, _instant
from .boat_observation_context import _identity
from .boat_active_exhibition import SCHEMA as BEFORE_SCHEMA
from .boat_official_program import SCHEMA as PROGRAM_SCHEMA

RACE = re.compile(r"20[0-9]{6}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")


def _hold(reason, old, later=None):
    return dict(status="HOLD_CUTOFF_"+reason, effective_cutoff_at=None,
                originally_scheduled_cutoff_at=old,
                proposed_cutoff_at=later, cutoff_revision=None)


def resolve_cutoff(schedule, program, beforeinfo, *, now, margin_seconds=210):
    """Confirm an amended planned closing clock from TWO dated official pages.

    For extensions, the selected-race official page must explicitly announce a
    schedule change. A shorter later-source deadline can be used conservatively
    even if the page lacks the announcement. In either case the two original
    source captures must occur BEFORE THE EARLIER DEADLINE and allow the real
    forecast/save margin. Otherwise HOLD. Original morning B never overwritten.

    This verifies the *announced planned cutoff*, not actual voting close.
    An independently authenticated P1-vs-P0 model audit must separately admit
    a supported revision before counting its external save as on time.
    """
    if type(schedule) is not dict or type(program) is not dict or type(beforeinfo) is not dict:
        raise ValueError("BOAT_CUTOFF_REVISION_INPUT_INVALID")
    old=schedule.get("cutoff_at"); later=program.get("closed_at")
    try:
        rid=schedule["race_id"]
        if type(rid) is not str or not RACE.fullmatch(rid):
            raise ValueError()
        original=_instant(old)
        proposed=_instant(later)
        check=_instant(now)
        if type(margin_seconds) is not int or not 0<=margin_seconds<=900:
            raise ValueError()
        if (original.utcoffset()!=timedelta(hours=9) or
            proposed.utcoffset()!=timedelta(hours=9) or
            original.astimezone(JST).strftime("%Y%m%d")!=rid[:8] or
            proposed.astimezone(JST).strftime("%Y%m%d")!=rid[:8]):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return _hold("INVALID_CLOCK_OR_IDENTITY",old,later)
    if original==proposed:
        return dict(status="UNCHANGED_OFFICIAL_CUTOFF",
                    effective_cutoff_at=original.isoformat(),
                    originally_scheduled_cutoff_at=old,
                    proposed_cutoff_at=later,cutoff_revision=None)
    try:
        source_captured=_instant(schedule["schedule_captured_at"])
        program_captured=_instant(program["captured_at"])
        before_captured=_instant(beforeinfo["captured_at"])
        if not(source_captured<=program_captured<=before_captured<=check):
            raise ValueError()
        if not (type(schedule.get("source_sha256")) is str and
                SHA.fullmatch(schedule["source_sha256"])):
            raise ValueError()
        if not (program.get("schema")==PROGRAM_SCHEMA and
                program.get("status")=="OFFICIAL_BODY_IDENTITY_VERIFIED" and
                program.get("body_identity_verified") is True and
                program.get("race_id")==rid and
                program.get("date_jst")==rid[:4]+"-"+rid[4:6]+"-"+rid[6:8]):
            raise ValueError()
        ps=program["source"]
        if not (type(program.get("source_sha256")) is str and
                SHA.fullmatch(program["source_sha256"]) and
                ps.get("sha256")==program["source_sha256"] and
                ps.get("source_url")==program["source_url"] and
                _instant(ps["captured_at"])==program_captured):
            raise ValueError()
        if not (beforeinfo.get("schema")==BEFORE_SCHEMA and
                beforeinfo.get("body_identity_verified") is True and
                beforeinfo.get("information_phase")=="pre_race" and
                beforeinfo.get("race_id")==rid):
            raise ValueError()
        ctx=beforeinfo["context"]
        bs=ctx["source"]
        if not (type(beforeinfo.get("source_sha256")) is str and
                SHA.fullmatch(beforeinfo["source_sha256"]) and
                bs.get("sha256")==beforeinfo["source_sha256"] and
                bs.get("source_url")==beforeinfo["source_url"] and
                _instant(bs["captured_at"])==before_captured):
            raise ValueError()
        if not (_identity(program["source_url"],"racelist") ==
                _identity(beforeinfo["source_url"],"beforeinfo") ==
                (rid[:8],rid[9:11],int(rid[12:14]))):
            raise ValueError()
        if not (_instant(beforeinfo["closed_at"])==proposed and
                _instant(ctx["source_cutoff_at"])==proposed and
                ctx.get("race_id")==rid and ctx.get("status")=="PARSED"):
            raise ValueError()
        # A correct source, obtained after either earlier cutoff, cannot
        # retrospectively authorize a pre-close forecast or amended receipt.
        safe=min(original,proposed)
        if not (source_captured<safe and program_captured<safe and
                before_captured<safe and check+timedelta(seconds=margin_seconds)<safe):
            return _hold("EARLY_DEADLINE_NOT_PROVEN_OPEN",old,later)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return _hold("DUAL_SOURCE_IDENTITY_OR_CLOCK_UNVERIFIED",old,later)

    change_noticed=program.get("schedule_change_notice") is True
    if proposed>original and not change_noticed:
        return _hold("EXTENSION_WITHOUT_OFFICIAL_CHANGE_NOTICE",old,later)
    seconds=int((proposed-original).total_seconds())
    decision=dict(status="VERIFIED_PRE_CLOSE_CUTOFF_REVISION",
        effective_cutoff_at=proposed.isoformat(),
        originally_scheduled_cutoff_at=original.isoformat(),
        proposed_cutoff_at=proposed.isoformat(),
        cutoff_revision=dict(schema="BOAT_PRE_CLOSE_CUTOFF_REVISION_V1",
            race_id=rid,original_cutoff_at=original.isoformat(),
            revised_cutoff_at=proposed.isoformat(),change_seconds=seconds,
            official_change_notice=change_noticed,
            evidence_basis=("OFFICIAL_NOTICE_AND_TWO_SOURCE_AGREEMENT" if change_noticed else
                            "CONSERVATIVE_EARLIER_TWO_SOURCE_AGREEMENT"),
            original_schedule_captured_at=source_captured.isoformat(),
            original_schedule_source_sha256=schedule["source_sha256"],
            program_captured_at=program_captured.isoformat(),
            program_source_sha256=program["source_sha256"],
            beforeinfo_captured_at=before_captured.isoformat(),
            beforeinfo_source_sha256=beforeinfo["source_sha256"],
            actual_voting_close_verified=False,actual_start_verified=False,
            original_forecast_modified=False,independent_aes_save_verified=False))
    return decision
