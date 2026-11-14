"""Discover nationwide KEIRIN races from ordinary WINTICKET listing anchors.

No venue-count hardcode: 0..N venues or 1..12 races each day, discovered from
the actually displayed racecard/results indexes. Validate calendar date,
meeting start, race number, and exact result URL before browser video capture.
This file performs no HTTP, video capture, label inference or wagers.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

JST=timezone(timedelta(hours=9))
SCHEMA="RACE_AI_KEIRIN_DAILY_PUBLIC_RACE_DISCOVERY_V1"
SOURCE_RACECARD="https://www.winticket.jp/keirin/racecard/"
SOURCE_RESULTS="https://www.winticket.jp/keirin/results/"
RACE_PATH=re.compile(
    r"^/keirin/([a-z][a-z-]{1,32})/(racecard|raceresult)/(\d{8})(\d{2})/(\d{1,2})/(\d{1,2})/?$")
SHA=re.compile(r"^[a-f0-9]{64}$")

class CatalogError(ValueError): pass

def require(ok,why):
    if not ok:raise CatalogError(why)

def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,
        separators=(",",":"),allow_nan=False)

def digest(x):
    return sha256(canonical(x).encode("utf-8")).hexdigest()

def _date(text):
    require(type(text) is str and
            bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}",text)),
            "DATE_FORMAT_REQUIRED")
    try:return date.fromisoformat(text)
    except ValueError:raise CatalogError("INVALID_DATE") from None

def validate_index(day, index):
    d=_date(day)
    require(type(index) is dict and set(index)=={
        "source_url","heading","links"},"INVALID_PAGE_METADATA_SHAPE")
    require(index["source_url"] in (SOURCE_RACECARD,SOURCE_RESULTS),
            "UNKNOWN_OFFICIAL_SOURCE_INDEX")
    header=re.search(r"本日\s*(\d{4})年(\d{1,2})月(\d{1,2})日",index["heading"])
    require(bool(header),"NO_TODAY_DATE_HEADER")
    shown=date(*(int(x) for x in header.groups()))
    require(shown==d,"PAGE_IS_NOT_REQUESTED_JST_DATE")
    require(type(index["links"]) is list and len(index["links"])<=800,
            "INVALID_PAGE_LINK_COUNT")
    return d

def _record(day, link):
    require(type(link) is dict and set(link)=={"href","text"},
            "INVALID_LINK_SHAPE")
    target=link["href"]
    require(type(target) is str,"INVALID_LINK_URL")
    parsed=urlsplit(target)
    if parsed.scheme!="https" or parsed.netloc!="www.winticket.jp":
        return None
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    m=RACE_PATH.fullmatch(parsed.path)
    if m is None:return None
    slug,segment,meet,jo_code,meet_day,number=m.groups()
    start=_date(f"{meet[:4]}-{meet[4:6]}-{meet[6:]}")
    day_number=int(meet_day)
    n=int(number)
    require(1<=day_number<=8 and 1<=n<=12,
            "INVALID_MEETING_DAY_OR_RACE_NUMBER")
    require(start+timedelta(days=day_number-1)==day,
            "RACE_MEETING_DATE_MISMATCH")
    require(1<=int(jo_code)<=99,"INVALID_VELODROME_CODE")
    expected=f"https://www.winticket.jp/keirin/{slug}/{segment}/{meet}{jo_code}/{day_number}/{n}"
    require(target.rstrip("/")==expected,
            "RACE_PATH_NOT_CANONICAL")
    race_id=f"{day:%Y%m%d}{jo_code}{n:02d}"
    return {
        "race_id":race_id,"venue_slug":slug,
        "venue_code":int(jo_code),
        "meet_start_jst":start.isoformat(),
        "meet_day":day_number,"race_no":n,
        "source_kind":segment,
        "canonical_result_url":
            f"https://www.winticket.jp/keirin/{slug}/raceresult/{meet}{jo_code}/{day_number}/{n}",
    }

def combine(day_jst,indexes):
    """A found racecard is a *scheduled candidate*, not video proof.

    The result-list anchor is useful metadata, but a video isn't eligible
    for training until a real browser player ended and independent evidence
    has been checked. Test/Train cohort is fixed *before seeing results*.
    """
    day=_date(day_jst)
    require(type(indexes) is list and len(indexes)==2,
            "BOTH_SOURCE_INDEXES_REQUIRED")
    by_race={}
    for index in indexes:
        validate_index(day_jst,index)
        for link in index["links"]:
            row=_record(day,link)
            if row is None:continue
            if row["source_kind"]=="racecard" and index["source_url"]!=SOURCE_RACECARD:
                continue
            if row["source_kind"]=="raceresult" and index["source_url"]!=SOURCE_RESULTS:
                continue
            rid=row["race_id"]
            old=by_race.setdefault(rid,{
                k:v for k,v in row.items() if k!="source_kind"})
            require(old["canonical_result_url"]==row["canonical_result_url"],
                    "RACE_ID_CONFLICT_BETWEEN_LINKS")
            old["listed_on_"+row["source_kind"]+"_index"]=True
    require(by_race,"NO_RACE_ANCHORS_VISIBLE")
    for row in by_race.values():
        row.setdefault("listed_on_racecard_index",False)
        row.setdefault("listed_on_raceresult_index",False)
        # Holdout selection is deterministic and uses only the identity.
        # Source discovery never reads outcomes or video pixels.
        bucket=int(sha256((day_jst+":"+row["race_id"]).encode()).hexdigest(),16)%5
        row["cohort"]=("UNSEEN_VIDEO_HOLDOUT" if bucket==0
                       else "TRAIN_CANDIDATE")
        row["video_captured"]=False
        row["video_player_verified"]=False
        row["rider_tactical_labels_approved"]=False
    rows=sorted(by_race.values(),key=lambda r:(r["venue_code"],r["race_no"]))
    output={
        "schema":SCHEMA,"date_jst":day_jst,
        "discovery_from_live_index_date":True,
        "source_urls":[SOURCE_RACECARD,SOURCE_RESULTS],
        "discovered_venue_count":len({r["venue_code"] for r in rows}),
        "discovered_race_count":len(rows),
        "discovered_all_on_page_not_proven_full_japan_coverage":True,
        "results_used_to_allocate_cohort":False,
        "all_laps_verified":False,
        "rights_scope_owner_reported_only":True,
        "races":rows,
    }
    output["manifest_sha256"]=digest(output)
    return output

def assess_daily_manifest(doc,*,target_day_jst):
    require(type(doc) is dict and doc.get("schema")==SCHEMA,
            "MANIFEST_SCHEMA_INVALID")
    require(doc.get("date_jst")==target_day_jst,"WRONG_DAY_MANIFEST")
    require(doc.get("manifest_sha256")==digest({
        k:v for k,v in doc.items() if k!="manifest_sha256"}),
        "MANIFEST_DIGEST_MISMATCH")
    require(doc.get("discovered_race_count")==len(doc.get("races",[]))>0,
            "EMPTY_OR_MISMATCHED_DAILY_MANIFEST")
    require(len({r["race_id"] for r in doc["races"]})==len(doc["races"]),
            "DUPLICATE_DAILY_RACE")
    return doc
