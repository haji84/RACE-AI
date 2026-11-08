"""Stage two same-race, pre-cutoff research forecasts from PR101 owner files.

An owner-controlled raw source -> PR101 immutable shadow_pre -> owner-provided
full trifecta odds -> PR103 variable selection -> append-only private SQLite
pair. Never fetch a site, guess an absent rider feature or copy private bytes
to public GitHub Actions artifacts/logs.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from .keirin_owner_sqlite import PrivateKeirinStore
from .keirin_result_delivery import canonical, utc
from .keirin_real_rider_shadow import (
    forecast_from_real_observations, SparseRealForecastError
)
from .keirin_shadow_variable_pair import (
    ShadowVariablePairLedger, ShadowPairError, choose_shadow_variable,
    checked_shadow, fingerprint
)
from .keirin_variable_selection import ODDS_SCHEMA


class ShadowPairIntakeError(ValueError):
    pass


def _read_private_json(path):
    require_path=Path(path)
    if require_path.is_symlink() or not require_path.is_file() or (
            not 0 < require_path.stat().st_size <= 2_000_000):
        raise ShadowPairIntakeError("UNSAFE_OR_MISSING_PRIVATE_JSON")
    def unique(pairs):
        seen={}
        for k,v in pairs:
            if k in seen:
                raise ShadowPairIntakeError("DUPLICATE_SOURCE_JSON_KEY")
            seen[k]=v
        return seen
    return json.loads(require_path.read_text(encoding="utf-8"),
                      object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(
                          ShadowPairIntakeError("NONFINITE_JSON_NUMBER")))


def stage_shadow_variable_pairs(inbox, store, *, grant_check, now, max_files=150):
    """Attempt only prospective first-time A/B, never back-date an old result."""
    root=Path(inbox).expanduser()
    if not (root.is_absolute() and root.is_dir()
            and not root.is_symlink()
            and isinstance(store,PrivateKeirinStore)
            and callable(grant_check)):
        raise ShadowPairIntakeError("PRIVATE_INPUT_DB_AND_GRANTS_REQUIRED")
    now_dt=utc(now)
    state=Counter()
    ledger=ShadowVariablePairLedger(store)
    source=root/"raw"
    shadows=root/"shadow_pre"
    odds=root/"odds"
    for directory in (source,shadows):
        if not directory.is_dir() or directory.is_symlink():
            raise ShadowPairIntakeError("SOURCE_OR_SHADOW_STAGE_MISSING")
    if odds.is_symlink():
        raise ShadowPairIntakeError("SYMLINKED_ODDS_STAGE")
    if not odds.exists():
        odds.mkdir(mode=0o700)
    if not odds.is_dir():
        raise ShadowPairIntakeError("INVALID_ODDS_STAGE")
    if type(max_files) is not int or not 1<=max_files<=150:
        raise ShadowPairIntakeError("INVALID_INPUT_BATCH_LIMIT")

    def candidates(folder):
        discovered=list(folder.glob("*.json"))
        fresh=[]
        for file in discovered:
            if file.is_symlink():
                state["rejected_symlink"]+=1
                continue
            fresh.append((file.stat().st_mtime_ns,str(file),file))
        fresh.sort(reverse=True)
        if len(fresh)>max_files:
            state["older_files_outside_bounded_window"]+=len(fresh)-max_files
        return [p for _,_,p in fresh[:max_files]]

    # Build the private, source-hash-indexed map without exposing source bytes.
    raw_by_sha={}
    for file in candidates(source):
        try:
            packet=_read_private_json(file)
            if type(packet) is dict and packet.get("schema")==(
                    "RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1"):
                raw_by_sha[fingerprint(packet)]=packet
        except (ValueError,TypeError,OSError):
            state["invalid_raw_packet"]+=1
    by_race={}
    for file in candidates(shadows):
        try:
            original=_read_private_json(file)
            checked_shadow(original)
            rid=original["race_id"]
            if rid in by_race:
                state["duplicate_shadow_race_refused"]+=1
                continue
            by_race[rid]=original
        except (ValueError,TypeError,OSError):
            state["invalid_shadow"]+=1
    for file in candidates(odds):
        try:
            ticket_prices=_read_private_json(file)
            if type(ticket_prices) is not dict or (
                    ticket_prices.get("schema")!=ODDS_SCHEMA):
                state["unsupported_odds_schema"]+=1
                continue
            rid=ticket_prices.get("race_id")
            if type(rid) is not str or not rid:
                state["invalid_odds_race_id"]+=1
                continue
            shadow=by_race.get(rid)
            if shadow is None:
                state["matching_prospective_shadow_missing"]+=1
                continue
            stored=ledger.read_pair(rid)
            if stored is not None:
                if (stored["shadow"]["research_sha256"]==
                        shadow["research_sha256"] and
                    fingerprint(ticket_prices)==fingerprint(stored["odds"])):
                    state["already_frozen_identical"]+=1
                else:
                    state["post_freeze_source_or_odds_conflict"]+=1
                continue
            if (utc(shadow["declared_cutoff"])-now_dt).total_seconds()<=65:
                state["missed_official_cutoff"]+=1
                continue
            packet=raw_by_sha.get(shadow["input_sha256"])
            if packet is None or packet.get("race",{}).get("race_id")!=rid:
                state["original_raw_snapshot_missing_or_changed"]+=1
                continue
            # Re-check full PR101 admission, source observations and all
            # 347/437 statuses against the exact frozen original timestamp.
            replay=forecast_from_real_observations(
                packet,grant_check=grant_check,
                issued_at=shadow["generated_at"])
            if replay!=shadow:
                state["source_shadow_recompute_mismatch"]+=1
                continue
            selected=choose_shadow_variable(
                shadow,ticket_prices,decided_at=now_dt.isoformat(),
                odds_allowed=grant_check)
            event=ledger.freeze_pair_once(
                shadow,selected,ticket_prices,source_packet=packet)
            state["dual_prospective_forecasts_saved" if event==(
                "CREATED_PAIR_ONCE") else "already_frozen_identical"]+=1
        except (ShadowPairError,SparseRealForecastError,ValueError,
                TypeError,KeyError,OSError):
            state["source_odds_or_pair_rejected"]+=1
    replay=ledger.replay_all()
    return {
        "schema":"RACE_AI_KEIRIN_OWNER_REAL_SHADOW_VARIABLE_STAGE_V1",
        "states":dict(sorted(state.items())),
        "owner_raw_packets_indexed":len(raw_by_sha),
        "owner_source_grounded_shadows_seen":len(by_race),
        "saved_dual_pairs_total":replay["saved_dual_forecast_races"],
        "reference_comparisons_settled":replay["settled_compared_races"],
        "unseen_older_files":state["older_files_outside_bounded_window"],
        "data_rights_independently_certified":False,
        "independent_pre_cutoff_timestamp_verified":False,
        "estimated_probabilities_calibrated":False,
        "formal_roi":None,
        "provider_network_requests":0,
        "automatic_betting":False,
    }
