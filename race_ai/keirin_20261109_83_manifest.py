"""Immutable 2026-11-09 JST nationwide KEIRIN clip calendar.

83 races in eight venues, grounded in WINTICKET public daily race calendar
and venue racecards as of the morning of Nov 9. Racecard start times are
provisional; official delays/cancellations must override selection. This is
a publicly auditable research manifest, not a legal rights grant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

SCHEMA="RACE_AI_KEIRIN_20261109_NATIONWIDE_83_V1"
JST=timezone(timedelta(hours=9))
DATE="20261109"
# slug, Japanese venue, jo code, meet start YYYYMMDD, meet day, starts JST
VENUES=(
 ("aomori","青森",12,"20261108",2,
  ("08:50","09:10","09:31","09:52","10:13","10:34","10:55")),
 ("kochi","高知",74,"20261107",3,
  ("11:13","11:37","12:03","12:30","12:57","13:24",
   "13:51","14:18","14:45","15:14","15:43","16:19")),
 ("takeo","武雄",84,"20261109",1,
  ("11:05","11:29","11:54","12:21","12:48","13:15",
   "13:42","14:09","14:36","15:04","15:34","16:07")),
 ("yahiko","弥彦",21,"20261107",3,
  ("11:21","11:45","12:12","12:39","13:06","13:33",
   "14:00","14:27","14:54","15:24","15:55")),
 ("matsudo","松戸",31,"20261109",1,
  ("15:49","16:13","16:37","17:01","17:25","17:50",
   "18:16","18:42","19:08","19:34","20:01","20:30")),
 ("utsunomiya","宇都宮",24,"20261108",2,
  ("16:01","16:25","16:49","17:13","17:37","18:03",
   "18:29","18:55","19:21","19:47","20:15")),
 ("matsuyama","松山",75,"20261108",2,
  ("20:40","21:00","21:20","21:40","22:00","22:20",
   "22:40","23:00","23:20")),
 ("nara","奈良",53,"20261108",2,
  ("20:50","21:10","21:30","21:50","22:10","22:30",
   "22:50","23:10","23:30")),
)
SOURCE_CALENDAR=(
 "https://www.winticket.jp/keirin/racecard/",
 "https://www.keirin.jp/sp/raceschedule",
 "https://keirinhex.jp/races/20261109/",
)
SOURCE_VENUE_PAGES=(
 "https://www.winticket.jp/keirin/utsunomiya/",
 "https://www.winticket.jp/keirin/nara/",
 "https://www.winticket.jp/keirin/matsuyama/",
)
def canonical(v):
 return json.dumps(v,ensure_ascii=False,sort_keys=True,
                   separators=(",",":"),allow_nan=False)
def digest(v):
 return hashlib.sha256(canonical(v).encode("utf-8")).hexdigest()

def manifest():
 items=[]
 for slug,venue,code,meeting,day,starts in VENUES:
  for n,at in enumerate(starts,1):
   start=datetime.fromisoformat(f"2026-11-09T{at}:00+09:00")
   rid=f"{DATE}{code:02d}{n:02d}"
   # 1 race in 5 is reserved before any real video/score is consulted;
   # a TEST must not inform training or tuning. Not an official prediction.
   cohort=("UNSEEN_VIDEO_HOLDOUT" if n % 5==0
           else "TRAIN_CANDIDATE")
   items.append({
     "race_id":rid,"venue_slug":slug,"venue":venue,
     "race_no":n,"meeting_day":day,
     "meeting_id":f"{meeting}{code:02d}",
     "scheduled_start_jst":start.isoformat(),
     "minimum_clip_attempt_jst":(start+timedelta(minutes=5)).isoformat(),
     "url":f"https://www.winticket.jp/keirin/{slug}/raceresult/"
            f"{meeting}{code:02d}/{day}/{n}",
     "date":"2026年11月9日",
     "cohort":cohort,
     "expected_source":"WINTICKET_PAST_RESULT_BROWSER_VIDEO",
     "full_four_laps_assumed":False,
     "actual_start_verified":False,
     "result_available_verified":False,
   })
 assert len(items)==83
 assert len({x["race_id"] for x in items})==83
 assert len({x["url"] for x in items})==83
 return {
  "schema":SCHEMA,"date_jst":"2026-11-09",
  "venues":8,"scheduled_races":83,
  "status":"SCHEDULED_UNTIL_INDIVIDUALLY_VERIFIED",
  "source_pages":list(SOURCE_CALENDAR+SOURCE_VENUE_PAGES),
  "start_times_not_official_live_delay_proof":True,
  "results_used_to_choose_training_holdouts":False,
  "races":sorted(items,key=lambda r:(r["scheduled_start_jst"],r["race_id"])),
 }
