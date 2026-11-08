"""Stage immutable, source-grounded partial-research picks on new live races.

No network requests. This does NOT alter the existing PR71 immutable original
or make formal forecasting/Hit@8 claims. Shadow records are private files.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from .keirin_real_rider_shadow import (
    MODEL, SparseRealForecastError, forecast_from_real_observations,
    save_private_shadow_once,
)
from .keirin_result_delivery import canonical, utc


class ShadowIntakeError(ValueError):
    pass


def stage_sourced_shadows(inbox, *, grant_check, now, max_sources=150):
    """Evaluate real pre-race observations as a separate shadow research model.

    Read only each source delivered into private raw/. If full PR71 inputs
    exist, its separate pipeline still runs. Never inject fake 'required'
    PR71 features or tamper with an existing frozen forecast.
    """
    root=Path(inbox).expanduser()
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ShadowIntakeError("PRIVATE_INBOX_REQUIRED")
    source=root/"raw"
    if not source.is_dir() or source.is_symlink():
        raise ShadowIntakeError("PRIVATE_SOURCE_DIR_REQUIRED")
    dest=root/"shadow_pre"
    dest.mkdir(mode=0o700,exist_ok=True)
    if dest.is_symlink():
        raise ShadowIntakeError("SYMLINKED_OUTPUT_DIR_NOT_ALLOWED")
    candidates=sorted(source.glob("*.json"))
    if len(candidates)>max_sources:
        raise ShadowIntakeError("TOO_MANY_PRIVATE_SOURCES")
    found=set()
    states=Counter()
    for p in candidates:
        if p.is_symlink() or p.stat().st_size>2_000_000:
            states["source_untrusted_or_too_large"]+=1
            continue
        try:
            packet=json.loads(p.read_text(encoding="utf-8"))
            if packet.get("schema")!="RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1":
                states["not_a_supported_pre_race_source"]+=1
                continue
            race=packet["race"]
            rid=race["race_id"]
            if not isinstance(rid,str) or not rid or len(rid)>200:
                states["source_untrusted_or_too_large"]+=1
                continue
            key=sha256((rid+"|"+MODEL).encode("utf-8")).hexdigest()
            out=dest/(key+".json")
            if out.exists():
                states["already_shadow_saved"]+=1
                continue
            # There can be multiple revisions for a race. Select only
            # the earliest *complete and checked* one that still has
            # a live cutoff. Never silently regenerate after outcome.
            if rid in found:
                states["second_race_candidate_not_overwritten"]+=1
                continue
            try:
                forecast=forecast_from_real_observations(
                    packet,grant_check=grant_check,issued_at=now)
            except (SparseRealForecastError,KeyError,TypeError,ValueError):
                states["real_input_missing_or_after_cutoff"]+=1
                continue
            save_private_shadow_once(out,forecast)
            found.add(rid)
            states["private_shadow_research_saved"]+=1
        except (OSError,KeyError,TypeError,ValueError):
            states["source_untrusted_or_too_large"]+=1
    return {
        "schema":"RACE_AI_KEIRIN_SOURCE_GROUNDED_SHADOW_STAGE_V1",
        "counts":dict(sorted(states.items())),
        "all_races_checked_in_private_source_files":len(candidates),
        "model_id":MODEL,
        "source_network_requests":0,
        "official_PR71_forecasts_generated":0,
        "formal_hit_at_8_measured":False,
        "auto_bet":False,
    }
