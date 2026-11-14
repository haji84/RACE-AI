"""Daily WINTICKET 83-race clip coverage accounting (never grades prediction).

Merge separately sealed short-clip collection waves from an independent
83-race source manifest. Metadata alone does not attest permanent retention,
tactical labels, or calibrated model improvement. Only actual uploaded
ciphertext plus independent library readback can confer durable-video status.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re

from .keirin_20261109_83_manifest import manifest, digest as mdigest

SCHEMA="RACE_AI_KEIRIN_20261109_VIDEO_COVERAGE_AUDIT_V1"
WAVE_SCHEMA="RACE_AI_20261109_WINTICKET_CLIP_WAVE_V1"
HEX=re.compile(r"^[a-f0-9]{64}$")
class CoverageError(ValueError): pass

def require(ok,msg):
 if not ok: raise CoverageError(msg)

def canonical(d):
 return json.dumps(d,sort_keys=True,separators=(",",":"),
                   ensure_ascii=False,allow_nan=False)

def summarize(waves, *, independent_library_receipts=None):
 day=manifest()
 races={x["race_id"]:x for x in day["races"]}
 expected_hash=mdigest(day)
 successes={}
 attempted={}
 for idx,w in enumerate(waves):
  require(type(w) is dict and w.get("schema")==WAVE_SCHEMA,
          "INVALID_WAVE_SCHEMA")
  require(w.get("manifest_sha256")==expected_hash,"MANIFEST_HASH_MISMATCH")
  require(w.get("date_jst")=="2026-11-09","OTHER_DATE_MISROUTED")
  require(w.get("raw_footage_exported") is False,"PLAIN_MEDIA_EXPORTED")
  require(w.get("prediction_model_weights_changed") is False,
          "OFFICIAL_PREDICTION_WEIGHTS_CHANGED")
  rows=w.get("race_rows")
  require(type(rows) is list and len(rows)<=40,"INVALID_WAVE_ROWS")
  for row in rows:
   rid=row.get("race_id")
   require(rid in races,"RACE_NOT_IN_IMMUTABLE_MANIFEST")
   require(row.get("cohort")==races[rid]["cohort"],
           "HOLDOUT_COHORT_MISMATCH")
   attempted.setdefault(rid,[]).append(
      {"wave_index":idx,"status":row.get("status")})
   if row.get("status")!="ENCRYPTED_COMPLETE_PLAYER":continue
   sha=row.get("recording_sha256")
   require(type(sha) is str and bool(HEX.fullmatch(sha)),
           "ENCRYPTED_SUCCESS_MISSING_SCREEN_SHA256")
   require(row.get("player_ended") is True,
           "SCREEN_CAPTURE_END_NOT_PROVEN")
   require(type(row.get("player_duration_s")) in (int,float) and
           30<=row["player_duration_s"]<=600,
           "INVALID_SHORT_PLAYER_DURATION")
   successes.setdefault(rid,[]).append({
      "sha256":sha,"duration_s":row["player_duration_s"],
      "wave_index":idx})
 # Avoid treating duplicates within and across waves as more unique races.
 sha_to_race={}
 for rid,entries in successes.items():
  for e in entries:
   if e["sha256"] in sha_to_race:
    require(sha_to_race[e["sha256"]]==rid,
            "SAME_SCREEN_BYTES_SHARED_BETWEEN_DISTINCT_RACES")
   sha_to_race[e["sha256"]]=rid
 receipts=independent_library_receipts or []
 persisted=set()
 for receipt in receipts:
  require(type(receipt) is dict and set(receipt)=={
     "race_id","recording_sha256","ciphertext_sha256",
     "library_path","readback_verified"},"INVALID_PRIVATE_LIBRARY_RECEIPT")
  rid=receipt["race_id"]
  require(rid in successes,"PERSISTED_FILE_WITHOUT_VERIFIED_GITHUB_CAPTURE")
  require(receipt["recording_sha256"] in {
     e["sha256"] for e in successes[rid]},
     "PERSISTED_SOURCE_SHA_MISMATCH")
  require(type(receipt["ciphertext_sha256"]) is str and
          bool(HEX.fullmatch(receipt["ciphertext_sha256"])),
          "LIBRARY_CIPHERTEXT_HASH_REQUIRED")
  require(isinstance(receipt["library_path"],str) and
          receipt["library_path"].startswith(
              "/RACE-AI/KeirinVideo/2026-11-09/") and
          receipt["readback_verified"] is True,
          "LIBRARY_READBACK_NOT_PROVEN")
  persisted.add(rid)
 recorded=set(successes)
 uncovered=sorted(set(races)-recorded)
 result={
  "schema":SCHEMA,"date_jst":"2026-11-09",
  "venue_count":8,"scheduled_races":83,
  "total_wave_reports":len(waves),"attempted_unique_races":len(attempted),
  "encrypted_unique_races":len(recorded),
  "confirmed_private_library_races":len(persisted),
  "recorded_not_durable_races":len(recorded-persisted),
  "not_yet_recorded_races":len(uncovered),
  "unrecorded_race_ids":uncovered,
  "not_recorded_status":{
     rid:attempted.get(rid,[]) for rid in uncovered
  },
  "holdout_reserved_and_recorded":sum(
      races[rid]["cohort"]=="UNSEEN_VIDEO_HOLDOUT" for rid in recorded),
  "reviewed_verified_rider_events":0,
  "verified_video_model_improvement_races":0,
  "official_prediction_weights_modified":False,
  "coverage_not_claimed_as_accuracy":True,
 }
 result["audit_sha256"]=sha256(canonical(result).encode("utf-8")).hexdigest()
 return result
