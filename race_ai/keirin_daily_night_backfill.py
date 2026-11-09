"""Previous-day midnight recovery of public WINTICKET replay clips.

A day index changes at midnight. The prior day's already-sha-frozen public
racecard manifest remains usable for locating the same historical results
pages, but only after every race is safely in the past; never backdate
prediction A/B, invent results, or assume an embedded player exists.
"""
from __future__ import annotations
from datetime import datetime,timedelta
from .keirin_daily_public_catalog import JST,assess_daily_manifest
from .keirin_daily_clip_batch import select,VENUE_JA,readback_ids,BatchError

def select_night_backfill(previous_manifest,*,now,progress=None,max_races=24,temporary_captured_race_ids=None):
    if now.utcoffset() is None:
        raise BatchError("TIMEZONE_REQUIRED")
    local=now.astimezone(JST)
    if not (0<=local.hour<8):
        raise BatchError("OUTSIDE_MIDNIGHT_BACKFILL_WINDOW")
    prior=(local.date()-timedelta(days=1)).isoformat()
    assess_daily_manifest(previous_manifest,target_day_jst=prior)
    if type(max_races) is not int or not 1<=max_races<=30:
        raise BatchError("UNBOUNDED_BACKFILL_ATTEMPTS")
    retained=readback_ids(progress,day_jst=prior)
    temporary=temporary_captured_race_ids or set()
    if type(temporary) is not set or any(
       not str(x).startswith(prior.replace("-","")) for x in temporary):
        raise BatchError("BAD_PREVIOUS_DAY_TEMP_INDEX")
    candidates=[r for r in previous_manifest["races"]
                if r["race_id"] not in retained and
                r["race_id"] not in temporary]
    candidates.sort(key=lambda r:(r["venue_code"],r["race_no"]))
    selected=[]
    for x in candidates[:max_races]:
        if x["venue_slug"] not in VENUE_JA:
            raise BatchError("UNKNOWN_RACE_VENUE")
        d=local.date()-timedelta(days=1)
        selected.append({
          "race_id":x["race_id"],
          "url":x["canonical_result_url"],
          "venue":VENUE_JA[x["venue_slug"]],
          "date":f"{d.year}年{d.month}月{d.day}日",
          "race_no":x["race_no"],
          "cohort":x["cohort"],
        })
    return {
      "target_previous_day_jst":prior,
      "historical_manifest_sha256":previous_manifest["manifest_sha256"],
      "total_prior_day_races":len(previous_manifest["races"]),
      "private_readback_confirmed":len(retained),
      "temporary_artifact_races_not_durable":len(temporary),
      "unresolved_races":len(candidates),
      "attempt_candidates":selected,
      "capped_unprocessed_count":len(candidates)-len(selected),
      "training_label_claim":False,
      "retroactive_forecast_claim":False,
    }
