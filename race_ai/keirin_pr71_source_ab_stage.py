"""PR71 A/B pre-cutoff staging using the EXACT existing four models.

A is the pinned legacy source mapping. B is a distinct-evidence research
mapping of the SAME prior snapshot. Each variant reuses the existing
FourModelRankLedger and existing result-revision scorer in a SEPARATE private
owner SQLite file, rather than inventing a second settlement engine or
overwriting the original single-race forecast. No external source GET, rights
grant, data extrapolation, odds, or actual stakes.

Partial A saved + B blocked is valid: this preserves an original baseline
without silently replacing missing B data with results or averages.
"""
from __future__ import annotations

from pathlib import Path

from .keirin_allowed_delivery import (
    DISTINCT_B_ID, assemble_permitted_pre_race,
)
from .keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from .keirin_pr71_four_model_rank import FourModelRankLedger
from .four_sport_model_suite import ALL_MODELS
from .keirin_result_delivery import utc

SCHEMA = "RACE_AI_KEIRIN_PR71_LEGACY_A_DISTINCT_B_STAGE_V1"


class KeirinEvidenceABError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise KeirinEvidenceABError(reason)


def stage_existing_four_models_a_b(
        delivery, owner_store_a, owner_store_b, *,
        grant_check, source_admission, checked_at):
    """Freeze A first; freeze B ONLY if B has its separate sourced inputs.

    Source_admission is the real independent per-source licensing callback;
    this function never claims it is authorized merely because the caller
    supplied a function. Its output is only operational research metadata.
    """
    require(isinstance(owner_store_a, PrivateKeirinStore) and
            isinstance(owner_store_b, PrivateKeirinStore),
            "TWO_OWNER_PRIVATE_SQLITE_STORES_REQUIRED")
    require(owner_store_a is not owner_store_b and
            Path(owner_store_a.path).resolve() !=
            Path(owner_store_b.path).resolve(),
            "DISTINCT_PRIVATE_VAULTS_REQUIRED")
    require(callable(grant_check) and callable(source_admission),
            "INDEPENDENT_SOURCE_ADMISSION_CALLBACKS_REQUIRED")
    require(type(checked_at) is str, "AWARE_CHECKED_AT_REQUIRED")
    a = assemble_permitted_pre_race(
        delivery, grant_check=grant_check, checked_at=checked_at)
    b = assemble_permitted_pre_race(
        delivery, grant_check=grant_check, checked_at=checked_at,
        feature_source_profile=DISTINCT_B_ID)
    rid = delivery["race"]["race_id"]
    require(a["status"]["race_id"] == rid and
            b["status"]["race_id"] == rid and
            a["status"]["checked_count"] ==
            b["status"]["checked_count"] and
            a["status"]["feature_source_profile"] == "legacy_a" and
            b["status"]["feature_source_profile"] == DISTINCT_B_ID,
            "SAME_EVENT_OR_AUDIT_MISMATCH")
    # Always perform the hard deadline check before writing into either DB.
    cutoff=utc(delivery["race"]["official_cutoff_at"])
    require(utc(checked_at) < cutoff and
            _checked_clock(owner_store_a.clock) < cutoff and
            _checked_clock(owner_store_b.clock) < cutoff,
            "A_B_NOT_BEFORE_CUTOFF")
    report={
        "schema":SCHEMA,
        "race_id":rid,
        "source_as_of":delivery["race"]["as_of"],
        "declared_cutoff_at":delivery["race"]["official_cutoff_at"],
        "model_ids":list(ALL_MODELS),
        "models_per_profile":4,
        "source_profile_A":"legacy_a",
        "source_profile_B":DISTINCT_B_ID,
        "input_A_status":a["status"]["state"],
        "input_B_status":b["status"]["state"],
        "input_A_missing":a["status"]["missing_model_inputs"],
        "input_B_missing":b["status"]["missing_model_inputs"],
        "A_immutable_rank_suite_sha256":None,
        "B_immutable_rank_suite_sha256":None,
        "A_immutable_source_sha256":None,
        "B_immutable_source_sha256":None,
        "A_persisted":False,
        "B_persisted":False,
        "source_grants_verifiable_only_externally":True,
        "not_model_training":True,
        "formal_improvement_claim":None,
        "real_world_hit_rate":None,
    }
    if a["private_snapshot"] is None:
        # Never produce even A when its full source, 347-factor, rights and
        # timing requirements have not passed.
        report["state"]="BLOCKED_A_AND_B"
        return report
    ledger_a=FourModelRankLedger(owner_store_a)
    ledger_a.freeze_once(
        a["private_snapshot"],source_admission=source_admission)
    read_a=ledger_a.read_suite(rid)
    require(read_a is not None and
            read_a["suite"]["model_count"] == 4,
            "A_FOUR_MODELS_NOT_READ_BACK")
    report["A_persisted"]=True
    report["A_immutable_rank_suite_sha256"]=read_a["suite"]["suite_sha256"]
    report["A_immutable_source_sha256"]=read_a["source_sha256"]
    if b["private_snapshot"] is None:
        report["state"]="A_FROZEN_B_BLOCKED_MISSING_SEPARATE_EVIDENCE"
        return report
    require(a["private_snapshot"]["race_id"] ==
            b["private_snapshot"]["race_id"] and
            a["private_snapshot"]["starters"] ==
            b["private_snapshot"]["starters"] and
            a["private_snapshot"]["as_of"] ==
            b["private_snapshot"]["as_of"] and
            a["private_snapshot"]["official_cutoff_at"] ==
            b["private_snapshot"]["official_cutoff_at"],
            "A_B_FORECAST_EVENT_OR_CUTOFF_CHANGED")
    ledger_b=FourModelRankLedger(owner_store_b)
    ledger_b.freeze_once(
        b["private_snapshot"],source_admission=source_admission)
    read_b=ledger_b.read_suite(rid)
    require(read_b is not None and
            read_b["suite"]["model_count"] == 4,
            "B_FOUR_MODELS_NOT_READ_BACK")
    require(read_a["source_sha256"] != read_b["source_sha256"] and
            read_a["suite"]["input_sha256"] !=
            read_b["suite"]["input_sha256"],
            "DISTINCT_SOURCE_PROFILE_MUST_PRODUCE_DIFFERENT_INPUT_HASH")
    report["B_persisted"]=True
    report["B_immutable_rank_suite_sha256"]=read_b["suite"]["suite_sha256"]
    report["B_immutable_source_sha256"]=read_b["source_sha256"]
    report["state"]="A_B_FOUR_MODELS_EACH_FROZEN_AND_READ_BACK"
    return report
