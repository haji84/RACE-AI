"""One bounded *real* official K archive format audit (no model inference).

This is a single research transport/syntax check on the official downloadable
previous-day K results. K contains past OUTCOMES. It is never used to
retroactively predict its own races, and provider rights are not granted.
No raw/result rows or athlete data are copied to the public repo.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone, date
import hashlib,json,os,sys,re
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
PIN=ROOT/"pr64-parser-reference"/"race_ai"
if PIN.is_dir():
    race_ai.__path__.append(str(PIN))

URL="https://www1.mbrace.or.jp/od2/K/202610/k261023.lzh"
DAY="2026-10-23"
BRANCH="refs/heads/p0-k-readiness-20261024"
TOKEN="20261023-K-ONE-PARSE"
TARGET_REGISTRATIONS=("3712","3158","5187","3987","3977","4442")
MAX_BYTES=4_000_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kw):
        raise ValueError("K audit redirects disallowed")

def audit(*,env=None,opener=None,extractor=None,parser=None,clock=None):
    e=os.environ if env is None else env
    if (e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH
        or e.get("RACE_AI_K_ONE_SHOT")!=TOKEN or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("K parse audit admission absent")
    now=clock() if clock else datetime.now(timezone.utc)
    if now.tzinfo is None or now.date()<=date.fromisoformat(DAY):
        raise RuntimeError("cannot download current/future K result archives")
    result={"schema":"RACE_AI_REAL_K_ONE_DAY_FORMAT_AUDIT_V1","kind":"K",
            "source_date_jst":DAY,"source_url":URL,"provider_get_budget":1,
            "provider_get_attempts":0,"compressed_source_persisted":False,
            "uncompressed_result_rows_published":False,
            "prediction_executed":False,"official_prediction":False,
            "formal_hit_at_8_eligible":False,
            "source_purpose_rights_independently_verified":False,
            "source_original_published_at_verified":False,
            "model_feature_time_admitted":False,
            "all_required_five_prior_races_verified":False,
            "status":"NOT_FETCHED"}
    try:
        client=opener or build_opener(NoRedirect(),HTTPSHandler())
        result["provider_get_attempts"]=1
        req=Request(URL,method="GET",headers={"Accept":"application/octet-stream",
                    "User-Agent":"RACE-AI-one-off-K-structure-audit/1"})
        with client.open(req,timeout=10) as resp:
            result["http_status"]=getattr(resp,"status",None)
            result["http_date_hint_unverified"]=resp.headers.get("Date")
            result["http_last_modified_hint_unverified"]=resp.headers.get("Last-Modified")
            if result["http_status"]!=200 or resp.geturl()!=URL:
                raise ValueError("wrong response URL or status")
            raw=resp.read(MAX_BYTES+1)
        if not 25<=len(raw)<=MAX_BYTES or raw[2:7] not in (
            b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("K LZH signature/budget invalid")
        result["archive_bytes"]=len(raw)
        result["archive_sha256"]=hashlib.sha256(raw).hexdigest()
        if extractor is None:
            from race_ai.official_lzh_extract import extract_daily_lzh
            extractor=extract_daily_lzh
        expanded=extractor(raw,"K261023.TXT")
        if not isinstance(expanded,bytes) or not 0<len(expanded)<=MAX_BYTES:
            raise ValueError("K extracted text budget failed")
        result["extracted_text_sha256"]=hashlib.sha256(expanded).hexdigest()
        result["extracted_text_bytes"]=len(expanded)
        if parser is None:
            from race_ai.core import parse_k
            parser=lambda content:parse_k(content,DAY)
        rows=parser(expanded)
        if not isinstance(rows,list) or not rows:
            raise ValueError("K parser returned zero result entries")
        keys=set()
        states=Counter()
        places=Counter()
        venue_codes=set()
        by_racer=defaultdict(set)
        for row in rows:
            if not isinstance(row,dict):
                raise ValueError("K result row must be dict")
            rid,lane,pid=row.get("race_id"),row.get("lane"),row.get("racer_id")
            if not isinstance(rid,str) or not re.fullmatch(r"20261023-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])",rid):
                raise ValueError("K race/date/venue mismatch")
            if type(lane) is not int or not 1<=lane<=6 or not isinstance(pid,str) or not re.fullmatch(r"\d{4}",pid):
                raise ValueError("K entrant identity malformed")
            if (rid,lane) in keys:raise ValueError("duplicate race/lane K identity")
            keys.add((rid,lane))
            venue_codes.add(rid[9:11])
            st=row.get("st")
            status=row.get("st_status")
            if status not in ("OK","F","L","MISSING","ABSENT"):
                raise ValueError("invalid K ST disposition")
            if status=="OK" and (type(st) not in (int,float) or not 0<=st<=1):
                raise ValueError("invalid numeric K ST")
            if status!="OK" and st is not None:
                raise ValueError("F/L or absent ST must not be numeric")
            states[status]+=1
            rank=row.get("finish")
            if rank is not None:
                if type(rank) is not int or not 1<=rank<=6:raise ValueError("invalid K finish")
                places["finite_finish_count"]+=1
            else:places["unavailable_finish_count"]+=1
            by_racer[pid].add(rid)
        result.update({
            "parsed_entries":len(rows),
            "parsed_races":len({x[0] for x in keys}),
            "parsed_venues":len(venue_codes),
            "valid_start_time_count":states["OK"],
            "F_count":states["F"],"L_count":states["L"],
            "absent_or_missing_start_count":states["ABSENT"]+states["MISSING"],
            "finite_finish_count":places["finite_finish_count"],
            "unavailable_finish_count":places["unavailable_finish_count"],
            "distinct_racer_count":len(by_racer),
            "target_six_registrations_with_K_on_this_day":
                sum(pid in by_racer for pid in TARGET_REGISTRATIONS),
            "target_six_total_prior_K_race_occurrences":
                sum(len(by_racer.get(pid,set())) for pid in TARGET_REGISTRATIONS),
            "maximum_K_races_for_any_racer_in_this_single_day":
                max(map(len,by_racer.values())),
            "scope":"HISTORICAL_K_LAYOUT_AND_STATS_AUDIT_ONLY",
            "status":"REAL_K_FORMAT_ACCEPTED_NOT_MODEL_ADMITTED"
        })
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,ImportError) as exc:
        result["status"]="REAL_K_TRANSPORT_OR_PARSE_UNVERIFIED"
        result["error_type"]=type(exc).__name__
        if isinstance(exc,HTTPError):result["http_status"]=exc.code
        # Never log K row text, source names, athlete identities or exceptions.
    result["runner_clock_observation_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return result

def main():
    try:res=audit()
    except RuntimeError:
        print("K_ONE_SHOT_GATE_NOT_ADMITTED")
        return 2
    print(json.dumps(res,ensure_ascii=False,sort_keys=True))
    return 0 if res["status"]=="REAL_K_FORMAT_ACCEPTED_NOT_MODEL_ADMITTED" else 2

if __name__=="__main__":
    raise SystemExit(main())
