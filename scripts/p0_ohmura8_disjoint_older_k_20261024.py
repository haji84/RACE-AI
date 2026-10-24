"""Eight previously UNSAMPLED historical K dates, exact six current entrants.

This is NOT a retrial of Oct09-Oct23. Only Oct01-Oct08 sources are accessed,
at most one GET per source day in a manually triggered job. The six entrant
registration IDs are pinned from the Oct24 official Ohmura8 racecard and
must not be auto-transferred to another race. Raw K rows never leave memory.
Neither legal rights nor source original-publication timestamp is attested.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, date, timezone
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import hashlib,json,os,sys,re,math

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
PIN=ROOT/"pr64-parser-reference"/"race_ai"
if PIN.is_dir() and str(PIN) not in race_ai.__path__:race_ai.__path__.append(str(PIN))
from scripts.p0_real_b_k_pr71_history_join_20261024 import parse_prior_K_preserving_complete_races

DAYS=tuple(f"2026-10-{i:02d}" for i in range(1,9))
RACE="20261024-24-08"
CUTOFF="2026-10-24T18:45:00+09:00"
RACE_CARD="https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261024&jcd=24&rno=8"
# Verified against official racecard in this run's design review, NOT scraped
# or claimed to be independently time certified by this script.
RACERS=("4263","4110","4919","4530","3907","5431")
REF="refs/heads/p0-ohmura8-disjoint-older-k-20261024"
TOKEN="OCT01_TO_OCT08_UNSAMPLED_K_ONCE"
MAX=4_000_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise ValueError("redirect forbidden")

def audit(*, env=None,opener=None,extractor=None,parser=None,clock=None):
    e=os.environ if env is None else env
    if(e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=REF
       or e.get("RACE_AI_K8_OLDER_ONE_SHOT")!=TOKEN
       or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("unadmitted historical K date tranche")
    now=clock() if clock else datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise RuntimeError("aware clock required")
    if now>=datetime.fromisoformat(CUTOFF):
        raise RuntimeError("cannot claim prospective old-K audit post cutoff")
    data={
        "schema":"RACE_AI_OHMURA8_DISTINCT_OLDER_K_BLOCK_V1",
        "race_id":RACE,
        "race_card_url":RACE_CARD,
        "source_dates":list(DAYS),
        "source_dates_prior_15day_overlap_count":len(set(DAYS)&
                                      set(f"2026-10-{d:02d}" for d in range(9,24))),
        "intended_get_limit":len(DAYS),
        "GET_attempts":0,
        "auto_polling":False,
        "retained_raw_archive":False,
        "republication_of_athlete_records":False,
        "official_source_publication_verified":False,
        "model_use_rights_verified":False,
        "source_racecard_identity_attested_at_runtime":False,
        "existing_PR71_coefficients_modified":False,
        "existing_PR71_FULL_forecast_executed":False,
        "official_prediction":False,
        "eligible_for_formal_hit8":False,
        "status":"UNVERIFIED"
    }
    try:
        from race_ai.official_lzh_extract import extract_daily_lzh
        from race_ai.core import parse_k
        extractor=extractor or extract_daily_lzh
        parser=parser or parse_k
        client=opener or build_opener(NoRedirect(),HTTPSHandler())
        entries=defaultdict(list)
        receipts=[]
        for day in DAYS:
            d=date.fromisoformat(day)
            if d>=date(2026,10,9):raise ValueError("old K window overlap or future")
            url=f"https://www1.mbrace.or.jp/od2/K/{d:%Y%m}/k{d:%y%m%d}.lzh"
            data["GET_attempts"]+=1
            with client.open(Request(url,headers={"Accept":"application/octet-stream",
                            "User-Agent":"RACE-AI-one-off-nonoverlapping-K-research/1"},method="GET"),timeout=10) as response:
                if response.status!=200 or response.geturl()!=url:
                    raise ValueError("K source URL/status invalid")
                raw=response.read(MAX+1)
            if not 25<=len(raw)<=MAX or raw[2:7] not in (b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
                raise ValueError("invalid K archive header/size")
            clear=extractor(raw,f"K{d:%y%m%d}.TXT")
            if not isinstance(clear,bytes) or not 0<len(clear)<=MAX:
                raise ValueError("K uncompressed budget")
            try:
                rows=parser(clear,day)
                excluded=0
                empties=0
                status="STRICT_WHOLE_DAY"
            except ValueError:
                try:
                    rows,excluded,empties=parse_prior_K_preserving_complete_races(clear,day,parser)
                    status="STRICT_PER_RACE_PARTIAL"
                except (ValueError,UnicodeError,ImportError):
                    rows=[]
                    excluded=None
                    empties=None
                    status="QUARANTINED_UNPARSEABLE_DAY"
            receipts.append({"day":day,"sha256":hashlib.sha256(raw).hexdigest(),
                             "accepted_rows":len(rows),"excluded_races":excluded,
                             "empty_venue_blocks":empties,"status":status})
            for row in rows:
                rid=row.get("race_id")
                if not isinstance(rid,str) or not rid.startswith(day.replace("-","")+"-"):
                    raise ValueError("K row cross-date mix")
                reg=row.get("racer_id")
                if reg not in RACERS:continue
                if row.get("st_status")!="OK" or type(row.get("finish")) is not int or not 1<=row["finish"]<=6:
                    continue
                st=row.get("st")
                if type(st) not in (int,float) or not math.isfinite(st) or not 0<=st<=1:
                    raise ValueError("K numeric ST inconsistent")
                entries[reg].append((rid,row["lane"]))
        by_lane=[len(set(entries[x])) for x in RACERS]
        summary={
            "source_summaries":receipts,
            "accepted_K_entrant_rows_total":sum(r["accepted_rows"] for r in receipts),
            "selected_6_racers_additional_K_counts_by_lane":by_lane,
            "selected_6_racers_additional_K_counts_sorted":sorted(by_lane),
            "minimal_new_K_count_across_six":min(by_lane),
            # Baseline window 10/09..23 proved each of six has >=3.
            # Only if every racer gains >=2 from a DISJOINT date window
            # can we soundly infer a new lower bound of >=5 for everyone.
            "previous_fifteen_K_window_minimum_proven":3,
            "combined_at_least_five_can_be_deduced_without_RACER_CROSS_RUN_STATE":
                min(by_lane)+3>=5,
            "cross_run_racer_specific_join_performed":False,
            "individual_source_values_persisted":False,
            "preview_display_joined":False,
            "preview_ST_joined":False,
            "wind_wave_joined":False,
            "status":"OLDER_DISTINCT_K_ROWS_OBSERVED_NOT_MODEL_ADMITTED"}
        data.update(summary)
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,ImportError,KeyError,RuntimeError) as e:
        data["status"]="OLDER_DISTINCT_K_SOURCE_UNVERIFIED"
        data["error_type"]=type(e).__name__
        if isinstance(e,HTTPError):data["http_status"]=e.code
    data["runtime_finished_at_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return data

def main():
    try:r=audit()
    except RuntimeError:
        print("UNADMITTED_SOURCE");return 2
    print(json.dumps(r,sort_keys=True,ensure_ascii=False))
    return 0 if r["status"]=="OLDER_DISTINCT_K_ROWS_OBSERVED_NOT_MODEL_ADMITTED" else 2
if __name__=="__main__":raise SystemExit(main())
