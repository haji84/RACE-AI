"""Bounded real historical K => existing PR71 form adapter coverage audit.

ONE invocation: six prior K day archives + one same-day B (seven HTTPS GET
attempts max, no retries, no schedule). All decoded original bytes and athlete
rows are kept in memory only. The PR71 existing history rating routine is
executed only on authentic prior-race rows when at least five are available.
This does not attest original publication date, legal reuse, or FULL forecast.
"""
from __future__ import annotations
from datetime import datetime,date,timezone
from collections import defaultdict
from pathlib import Path
import hashlib,json,os,sys,re
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import re,unicodedata

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
for path in ("pr64-parser-reference","pr71-existing-reference"):
    p=ROOT/path/"race_ai"
    if p.is_dir() and str(p) not in race_ai.__path__:race_ai.__path__.append(str(p))

K_DAYS=("2026-10-18","2026-10-19","2026-10-20","2026-10-21","2026-10-22","2026-10-23")
B_DAY="2026-10-24"
TARGET="20261024-11-11"
BRANCH="refs/heads/p0-real-k-b-pr71-form-20261024"
TOKEN="ONE_HISTORICAL_SIX_K_B_PR71"
MAX_ARCHIVE=4_000_000
MAX_GETS=7

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_a,**_k):raise ValueError("upstream redirect forbidden")


def parse_prior_K_preserving_complete_races(raw, day, strict_parser):
    """Retain only fully verified six-boat K races; reject incomplete ones.

    Uses original PR64 parse_k() on each original header+race segment. This
    is a quarantine fallback for historical feature availability only, NOT
    official full-day settlement and never labels a canceled race complete.
    """
    from race_ai.core import _blocks, _ensure_day, SourceError
    if not isinstance(raw,bytes) or len(raw)>MAX_ARCHIVE:
        raise ValueError("bounded K text bytes required")
    normalized=unicodedata.normalize("NFKC",raw.decode("cp932"))
    if "STARTK" not in normalized[:200]:
        raise ValueError("K file start marker missing")
    output=[]
    rejected=0
    for venue, body in _blocks(normalized,"K"):
        if not 1<=venue<=24:
            raise ValueError("historical K venue invalid")
        _ensure_day(body,day)
        matches=list(re.finditer(r"(?m)^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m.*$",body,re.I))
        if not matches: raise ValueError("K venue has no recognizable race headers")
        races=set()
        for i,match in enumerate(matches):
            n=int(match.group(1))
            if not 1<=n<=12 or n in races:
                raise ValueError("duplicate or invalid original K race header")
            races.add(n)
            part=body[match.start():(matches[i+1].start() if i+1<len(matches) else len(body))]
            # Strict PR64 parse_k must still prove six unique lanes and
            # one race; any inconsistent race contributes zero feature rows.
            mini=(f"STARTK\n{venue:02d}KBGN\n"+part+
                  f"\n{venue:02d}KEND\n").encode("cp932")
            try:
                rows=strict_parser(mini,day)
                if len(rows)!=6 or {r["race_id"] for r in rows}!={f"{day.replace('-','')}-{venue:02d}-{n:02d}"}:
                    raise SourceError("per-race identity mismatch")
            except (SourceError,ValueError,UnicodeError):
                rejected+=1
                continue
            output.extend(rows)
    if not output:
        raise ValueError("no verified per-race historical K results")
    if len({(r["race_id"],r["lane"]) for r in output})!=len(output):
        raise ValueError("duplicate salvaged K result rows")
    return output,rejected

def audit(*,env=None,opener=None,extract=None,parse_k_fn=None,parse_b_fn=None,
          parse_details_fn=None,history_model=None,clock=None):
    e=os.environ if env is None else env
    if (e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH
        or e.get("RACE_AI_BK_JOIN_ONE_SHOT")!=TOKEN
        or len(e.get("GITHUB_SHA",""))!=40):
        raise RuntimeError("bounded cross-day archive audit not admitted")
    now=clock() if clock else datetime.now(timezone.utc)
    if now.tzinfo is None or now.astimezone(timezone.utc).date()<=date.fromisoformat(K_DAYS[-1]):
        raise RuntimeError("no K retrieval before prior K date passes")
    report={"schema":"RACE_AI_REAL_K_B_HISTORY_PR71_JOIN_V1",
            "program_day_jst":B_DAY,
            "prior_K_days_requested":list(K_DAYS),
            "target_race_id":TARGET,
            "provider_get_attempts":0,
            "provider_get_budget":MAX_GETS,
            "auto_schedule_enabled":False,
            "source_bytes_persisted":False,
            "individual_racer_data_logged":False,
            "underlying_source_publication_verified":False,
            "source_model_use_rights_independently_approved":False,
            "forecast_executed":False,
            "official_prediction":False,
            "formal_hit_at_8_eligible":False,
            "status":"NOT_STARTED"}
    client=opener or build_opener(NoRedirect(),HTTPSHandler())
    if extract is None:
        from race_ai.official_lzh_extract import extract_daily_lzh
        extract=extract_daily_lzh
    if parse_k_fn is None:
        from race_ai.core import parse_k
        parse_k_fn=parse_k
    if parse_b_fn is None:
        from race_ai.core import parse_b
        parse_b_fn=parse_b
    if parse_details_fn is None:
        from race_ai.official_b_snapshot_adapter import program_details
        parse_details_fn=program_details
    if history_model is None:
        from race_ai.boat_feature_adapter import _historical_past
        history_model=_historical_past
    def one(day,kind):
        if report["provider_get_attempts"]>=MAX_GETS:raise ValueError("one-shot request budget exhausted")
        d=date.fromisoformat(day)
        url=f"https://www1.mbrace.or.jp/od2/{kind}/{d:%Y%m}/{kind.lower()}{d:%y%m%d}.lzh"
        report["provider_get_attempts"]+=1
        req=Request(url,method="GET",headers={"Accept":"application/octet-stream",
                    "User-Agent":"RACE-AI-manually-triggered-bounded-archive-validation/1"})
        with client.open(req,timeout=10) as resp:
            if resp.status!=200 or resp.geturl()!=url:raise ValueError("provider status/URL mismatch")
            blob=resp.read(MAX_ARCHIVE+1)
            lm=resp.headers.get("Last-Modified")
        if not 25<=len(blob)<=MAX_ARCHIVE or blob[2:7] not in (
            b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("invalid/big official archive")
        clear=extract(blob,kind+f"{d:%y%m%d}".upper()+".TXT")
        if not isinstance(clear,bytes) or not 0<len(clear)<=MAX_ARCHIVE:
            raise ValueError("invalid extracted official archive")
        return clear,{"kind":kind,"event_day_jst":day,
             "archive_sha256":hashlib.sha256(blob).hexdigest(),
             "compressed_bytes":len(blob),
             "HTTP_last_modified_unverified":lm}
    try:
        past=defaultdict(list)
        kreceipts=[]
        for day in K_DAYS:
            clear,meta=one(day,"K")
            report["current_source_day_at_read"] = day
            try:
                rows=parse_k_fn(clear,day)
                rejected=0
                mode="PR64_WHOLE_K_PARSE"
            except ValueError:
                # Fail closed at the per-race level. Never invent results
                # or silently accept incomplete participant rosters.
                rows,rejected=parse_prior_K_preserving_complete_races(clear,day,parse_k_fn)
                mode="PR64_STRICT_PER_RACE_PARTIAL_HISTORY_ONLY"
            if not isinstance(rows,list) or not rows:raise ValueError("empty actual K")
            kreceipts.append({**meta,"parsed_rows":len(rows),
                "incomplete_K_races_excluded":rejected,"parser_mode":mode})
            for r in rows:
                rid=r.get("race_id")
                if (not isinstance(rid,str) or not rid.startswith(day.replace("-","")+"-")
                    or r.get("st_status") not in ("OK","F","L","ABSENT","MISSING")):
                    raise ValueError("invalid cross-day K identity/status")
                past[r["racer_id"]].append(r)
        report["K_source_aggregate_sha256"]=hashlib.sha256(json.dumps(
            [x["archive_sha256"] for x in kreceipts],separators=(",",":")).encode()).hexdigest()
        report["K_day_counts"]=[{"day":x["event_day_jst"],"parsed_rows":x["parsed_rows"],
             "compressed_bytes":x["compressed_bytes"],
             "archive_sha256":x["archive_sha256"],
             "incomplete_K_races_excluded":x["incomplete_K_races_excluded"],
             "parser_mode":x["parser_mode"],
             "http_last_modified_unverified":x["HTTP_last_modified_unverified"]}
             for x in kreceipts]
        clear,meta=one(B_DAY,"B")
        entrants=parse_b_fn(clear,B_DAY)
        details,deadlines=parse_details_fn(clear,date.fromisoformat(B_DAY))
        report["B_archive_sha256"]=meta["archive_sha256"]
        report["B_total_entrants"]=len(entrants)
        report["B_total_races"]=len(deadlines)
        if len(entrants)!=len(details) or TARGET not in deadlines:
            raise ValueError("B whole-file coverage or selected race identity mismatch")
        selected=sorted((r for r in entrants if r["race_id"]==TARGET),key=lambda r:r["lane"])
        if len(selected)!=6 or [r["lane"] for r in selected]!=list(range(1,7)):
            raise ValueError("target race B field not exactly six unique lanes")
        report["selected_race_six_B_identifiers_confirmed"]=True
        counts=[]
        full=0
        partial=0
        non_numeric=0
        synthetic_candidate_calculations=0
        for row in selected:
            pid=row["racer_id"]
            # PR64 K parser's immutable result format; order latest before
            # handing exact historic finishes and ST to PR71 original code.
            history=sorted(past.get(pid,()),key=lambda x:x["race_id"],reverse=True)
            clean=[]
            for r in history:
                if (r.get("st_status")=="OK" and type(r.get("st")) in (int,float)
                    and type(r.get("finish")) is int and 1<=r["finish"]<=6):
                    clean.append({"race_id":r["race_id"],
                                  "race_day":r["race_id"][:4]+"-"+r["race_id"][4:6]+"-"+r["race_id"][6:8],
                                  "finish_position":r["finish"],"start_seconds":r["st"]})
                else:non_numeric+=1
            counts.append(len(clean))
            if clean:partial+=1
            if len(clean)>=5:
                # Invoke PR71's existing, unmodified numeric history formula.
                # Do not supply result to a real model snapshot: original
                # publication/rights record has not been admitted.
                rating,consistency=history_model(clean[:30],B_DAY,now.isoformat())
                if not all(isinstance(v,(int,float)) and 0<=v<=100 for v in (rating,consistency)):
                    raise ValueError("PR71 history rating outside expected units")
                full+=1
                synthetic_candidate_calculations+=2
        report.update({
            "historical_K_unique_racer_ids":len(past),
            "target_race_valid_history_count_distribution_sorted":sorted(counts),
            "target_race_lanes_with_any_eligible_prior_K":partial,
            "target_race_lanes_with_at_least_5_valid_prior_K":full,
            "target_race_prior_K_nonnumeric_or_unsettled_rows":non_numeric,
            "real_prior_K_values_reached_existing_PR71_history_formula_count":
                synthetic_candidate_calculations,
            "actual_exhibition_observation_joined":False,
            "actual_weather_observation_joined":False,
            "source_terms_or_published_time_promotion":False,
            "formal_model_predicted_top8_count":0,
            "status":"REAL_HISTORICAL_K_B_PR71_FORM_CANDIDATES_NOT_ADMITTED",
        })
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,ImportError,
            KeyError,RuntimeError) as exc:
        report["status"]="REAL_K_B_JOIN_UNVERIFIED"
        report["error_type"]=type(exc).__name__
        # Historical archive has been discarded; only a safe day code and
        # exception TYPE are exposed, never athlete lines or source text.
        report["failed_source_date_jst"]=report.get("current_source_day_at_read")
        if isinstance(exc,HTTPError):report["http_status"]=exc.code
    report["runner_finished_at_claimed"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return report

def main():
    try:report=audit()
    except RuntimeError:
        print("NOT_ADMITTED");return 2
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))
    return 0 if report["status"]=="REAL_HISTORICAL_K_B_PR71_FORM_CANDIDATES_NOT_ADMITTED" else 2

if __name__=="__main__":raise SystemExit(main())
