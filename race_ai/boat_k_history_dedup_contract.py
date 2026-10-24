"""Pre-race K history manifest and duplication/point-in-time gate.

This module never acquires or stores third-party archive bytes. It accepts
already available, independently admitted K observations and rejects
duplicates, future information, fabricated timestamps and invalid statuses.
Do not confuse a content-addressed manifest with a permission grant.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re

K_SCHEMA = "RACE_AI_K_HISTORY_EVIDENCE_MANIFEST_V1"
STATES = {"OK", "F", "L", "MISSING", "ABSENT"}
SHA = re.compile(r"[a-f0-9]{64}\Z")
RACE_ID = re.compile(r"(\d{8})-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])\Z")
HASH_FIELDS = ("kind", "event_date_jst", "source_url", "sha256",
               "captured_at", "published_at", "purpose_rights_ref",
               "admitted_for_history")
ROW_FIELDS = ("race_id", "lane", "racer_id", "course", "st", "st_status",
              "finish", "source_sha256", "published_at", "captured_at")

class HistoricalSourceError(ValueError):
    pass

def _time(value):
    if not isinstance(value, str):
        raise HistoricalSourceError("missing timestamp")
    try:
        moment=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise HistoricalSourceError("invalid timestamp") from exc
    if moment.utcoffset() is None:
        raise HistoricalSourceError("source timezone missing")
    return moment

def _fingerprint(value):
    payload=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def index_admitted_K_sources(sources, *, as_of, event_date_jst, assert_rights=None):
    """Return immutable-content index ONLY after independent origin/rights check.

    Existing K source days must be older than event day. Duplicate date+hash
    is collapsed. Conflicting hashes on one K date demand a revision contract
    and cannot be silently replaced; the caller must pin a separate version.
    """
    asof=_time(as_of)
    event=date.fromisoformat(event_date_jst)
    if not isinstance(sources,list) or len(sources)>60:
        raise HistoricalSourceError("bounded source manifests only")
    selected={}
    skipped_duplicates=0
    for item in sources:
        if not isinstance(item,dict) or set(item)!=set(HASH_FIELDS):
            raise HistoricalSourceError("invalid K source manifest fields")
        d=date.fromisoformat(item["event_date_jst"])
        if d>=event:
            raise HistoricalSourceError("target-day or future K results prohibited")
        if item["kind"]!="K" or not SHA.fullmatch(str(item["sha256"])):
            raise HistoricalSourceError("unverified K archive identity")
        if (not isinstance(item["source_url"],str)
            or item["source_url"]!=f"https://www1.mbrace.or.jp/od2/K/{d:%Y%m}/k{d:%y%m%d}.lzh"):
            raise HistoricalSourceError("source K URL/date mismatch")
        publication=_time(item["published_at"])
        capture=_time(item["captured_at"])
        if not publication<=capture<=asof:
            raise HistoricalSourceError("K source unavailable at prediction decision time")
        if item["admitted_for_history"] is not True:
            raise HistoricalSourceError("source K not independently admitted")
        if (not isinstance(item["purpose_rights_ref"],str)
            or not item["purpose_rights_ref"] or not callable(assert_rights)
            or assert_rights(item["source_url"],item["purpose_rights_ref"],
                             "historical_model_analysis") is not True):
            raise HistoricalSourceError("historical model purpose rights not verified")
        day=item["event_date_jst"]
        if day in selected:
            old=selected[day]
            if old["sha256"]!=item["sha256"]:
                raise HistoricalSourceError("conflicting same-day K revision")
            skipped_duplicates+=1
            continue
        selected[day]=item
    canonical=[selected[d] for d in sorted(selected)]
    return {"schema":K_SCHEMA, "source_count":len(canonical),
            "duplicate_exact_sources_skipped":skipped_duplicates,
            "source_dates":[row["event_date_jst"] for row in canonical],
            "source_sha256_by_day":{row["event_date_jst"]:row["sha256"] for row in canonical},
            "manifest_sha256":_fingerprint(canonical),
            "model_rights_verified_by_independent_callback":True,
            "source_publication_verified_by_caller_not_this_module":True,
            "forecast_generated":False}

def prior_rows_by_racer(rows, manifest, *, as_of, event_date_jst, racer_ids):
    """Deduplicate by prior race/lane, preserve F/L as nonnumeric and check K SHA.

    No fallback to today, false zero, same-day after event, or default value.
    A pair (race_id,lane) is unique; conflicting revisions block admission.
    """
    if not isinstance(manifest,dict) or manifest.get("schema")!=K_SCHEMA:
        raise HistoricalSourceError("validated K source manifest required")
    if not isinstance(rows,list) or len(rows)>100000:
        raise HistoricalSourceError("bounded prior K rows required")
    if (not isinstance(racer_ids,(set,tuple,list)) or len(racer_ids)!=6
        or any(not isinstance(v,str) or not re.fullmatch(r"\d{4}",v) for v in racer_ids)
        or len(set(racer_ids))!=6):
        raise HistoricalSourceError("exactly six stable registration IDs required")
    src=manifest["source_sha256_by_day"]
    asof=_time(as_of)
    event=date.fromisoformat(event_date_jst)
    results={r:[] for r in racer_ids}
    seen={}
    for r in rows:
        if not isinstance(r,dict) or set(r)!=set(ROW_FIELDS):
            raise HistoricalSourceError("invalid K result row schema")
        m=RACE_ID.fullmatch(r["race_id"]) if isinstance(r["race_id"],str) else None
        if m is None:raise HistoricalSourceError("K race_id invalid")
        day=date.fromisoformat(f"{m[1][:4]}-{m[1][4:6]}-{m[1][6:8]}")
        ds=day.isoformat()
        if day>=event or ds not in src or src[ds]!=r["source_sha256"]:
            raise HistoricalSourceError("unknown or target day source data")
        pub=_time(r["published_at"])
        cap=_time(r["captured_at"])
        if not pub<=cap<=asof:raise HistoricalSourceError("future K result leakage")
        lane=r["lane"]
        if type(lane) is not int or not 1<=lane<=6:
            raise HistoricalSourceError("invalid K result lane")
        pid=r["racer_id"]
        if not isinstance(pid,str) or not re.fullmatch(r"\d{4}",pid):
            raise HistoricalSourceError("K racer identity invalid")
        status=r["st_status"]
        if status not in STATES:raise HistoricalSourceError("unknown K ST status")
        st=r["st"]
        if status=="OK":
            if type(st) not in (float,int) or not math.isfinite(st) or not 0<=st<=1:
                raise HistoricalSourceError("valid K ST numeric missing")
        elif st is not None:raise HistoricalSourceError("F/L/absent cannot be numeric zero")
        pos=r["finish"]
        if pos is not None and (type(pos) is not int or not 1<=pos<=6):
            raise HistoricalSourceError("K finish invalid")
        key=(r["race_id"],lane)
        if key in seen:
            if seen[key]!=r:raise HistoricalSourceError("conflicting historical race revision")
            continue
        seen[key]=r
        if pid in results:
            results[pid].append(r)
    for pid in results:
        results[pid].sort(key=lambda item:item["race_id"],reverse=True)
    return results
