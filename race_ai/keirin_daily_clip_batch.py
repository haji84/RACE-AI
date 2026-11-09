"""Bound daily race results into small, non-overlapping recording batches.

Only sources actually listed on the WINTICKET result index are candidates.
The player itself must still prove normal public playback and natural end.
Persisted owner-only Library readback is a separately attested stop condition.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import re

from .keirin_daily_public_catalog import (
    assess_daily_manifest,CatalogError
)

PROGRESS_SCHEMA="RACE_AI_KEIRIN_DAILY_LIBRARY_READBACK_V1"
HEX=re.compile(r"^[0-9a-f]{64}$")
VENUE_JA={
 "hakodate":"函館","aomori":"青森","iwakidaira":"いわき平",
 "yahiko":"弥彦","maebashi":"前橋","toride":"取手","utsunomiya":"宇都宮",
 "omiya":"大宮","seibuen":"西武園","keiokaku":"京王閣","tachikawa":"立川",
 "matsudo":"松戸","chiba":"千葉","kawasaki":"川崎","hiratsuka":"平塚",
 "odawara":"小田原","ito":"伊東","shizuoka":"静岡",
 "nagoya":"名古屋","gifu":"岐阜","ogaki":"大垣","toyohashi":"豊橋",
 "toyama":"富山","matsusaka":"松阪","yokkaichi":"四日市",
 "fukui":"福井","nara":"奈良","mukomachi":"向日町",
 "wakayama":"和歌山","kishiwada":"岸和田",
 "tamano":"玉野","hiroshima":"広島","hofu":"防府",
 "takamatsu":"高松","komatsushima":"小松島","kochi":"高知",
 "matsuyama":"松山",
 "kokura":"小倉","kurume":"久留米","takeo":"武雄",
 "sasebo":"佐世保","beppu":"別府","kumamoto":"熊本",
}

class BatchError(ValueError):pass
def check(ok,code):
    if not ok: raise BatchError(code)

def readback_ids(progress,*,day_jst):
    """Only independently verified private Library receipts can suppress retries."""
    if progress is None:return set()
    check(type(progress) is dict and set(progress)=={
        "schema","date_jst","receipts"},"INVALID_DURABLE_LEDGER")
    check(progress["schema"]==PROGRESS_SCHEMA,"INVALID_DURABLE_LEDGER_VERSION")
    if progress["date_jst"]!=day_jst:return set()
    receipts=progress["receipts"]
    check(type(receipts) is list and len(receipts)<=180,
          "INVALID_RETAINED_RECEIPTS")
    seen=set()
    for rec in receipts:
        check(type(rec) is dict and set(rec)=={
            "race_id","recording_sha256","library_artifact_path",
            "library_byte_readback_verified"
        },"INVALID_RETENTION_RECEIPT")
        rid=rec["race_id"]
        check(type(rid) is str and re.fullmatch(
                r"\d{8}\d{2}\d{2}",rid) and rid.startswith(day_jst.replace("-","")),
                "RETENTION_WRONG_RACE_DAY")
        check(type(rec["recording_sha256"]) is str and
              bool(HEX.fullmatch(rec["recording_sha256"])),
              "RETENTION_SOURCE_HASH_REQUIRED")
        check(rec["library_artifact_path"].startswith(
            f"/RACE-AI/KeirinVideo/{day_jst}/"),
            "RETENTION_NOT_IN_PRIVATE_DAY")
        check(rec["library_byte_readback_verified"] is True,
              "RETENTION_NOT_INDEPENDENTLY_READ_BACK")
        check(rid not in seen,"DUPLICATED_RETENTION_RACE")
        seen.add(rid)
    return seen

def select(manifest, *,progress=None,max_races=24):
    day_jst=manifest.get("date_jst")
    assess_daily_manifest(manifest,target_day_jst=day_jst)
    check(type(max_races) is int and 1<=max_races<=30,
          "UNBOUNDED_RECORDING_BATCH")
    archived=readback_ids(progress,day_jst=day_jst)
    source=[r for r in manifest["races"] if r["listed_on_raceresult_index"]]
    candidates=[r for r in source if r["race_id"] not in archived]
    # Keep deterministic finite batches; cannot silently treat a capped list
    # as all video recorded or all scheduled races covered.
    selected=candidates[:max_races]
    d=date.fromisoformat(day_jst)
    for row in selected:
        if row["venue_slug"] not in VENUE_JA:
            raise BatchError("VENUE_NOT_YET_IN_VERIFIED_MAPPING")
    return {
       "day_jst":day_jst,
       "races_visible_on_result_index":len(source),
       "durably_archived_with_attested_readback":len(archived),
       "candidates_waiting_after_result_page":len(candidates),
       "selected": [{
            "race_id":r["race_id"],
            "url":r["canonical_result_url"],
            "venue":VENUE_JA[r["venue_slug"]],
            "date":f"{d.year}年{d.month}月{d.day}日",
            "race_no":r["race_no"],
            "cohort":r["cohort"],
            } for r in selected],
       "not_selected_due_to_wave_cap":max(0,len(candidates)-len(selected)),
       "eligible_for_learning_from_video_button_alone":False,
       "official_forecast_modified":False,
    }
