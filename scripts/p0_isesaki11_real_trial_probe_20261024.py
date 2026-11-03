"""Official Isesaki GII 11R trial-time ONE GET, before 19:48 JST planned cutoff.

The target full URL is based on observed first-party program convention.
This trial does not presume it is served; fails closed if rejected.
Do not log source HTML, competitors, prices, results, or any predictions.
"""
from __future__ import annotations
from datetime import datetime,timezone
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import json,os,re,sys
from race_ai.autorace_official_trial_adapter import parse_official_trial

URL="https://autorace.jp/race_info/Program/isesaki/2026-10-24_11"
CUTOFF="2026-10-24T19:48:00+09:00"
BRANCH="refs/heads/p0-isesaki11-trial-20261024"
TOKEN="ISESAKI_11R_TRIAL_ONESHOT_V1"
LIMIT=900_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):
        raise ValueError("unexpected provider redirect")

def probe(*,env=None,clock=None,opener=None):
    e=os.environ if env is None else env
    if(e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=BRANCH
       or e.get("RACE_AI_ISESAKI11_ONCE")!=TOKEN
       or re.fullmatch(r"[a-f0-9]{40}",e.get("GITHUB_SHA","")) is None):
        raise RuntimeError("one-shot official trial access gate not matched")
    now=clock() if clock else datetime.now(timezone.utc)
    cutoff=datetime.fromisoformat(CUTOFF)
    if now>=cutoff:
        return {"schema":"RACE_AI_OFFICIAL_AUTO_TRIAL_REAL_ONE_SHOT_V1",
                "status":"CUTOFF_PASSED_DONT_FETCH",
                "provider_GET_attempts":0,"model_executed":False}
    result={"schema":"RACE_AI_OFFICIAL_AUTO_TRIAL_REAL_ONE_SHOT_V1",
            "target_source_url":URL,"race_date":"2026-10-24",
            "venue":"isesaki","race_no":11,
            "scheduled_cutoff_at_unverified":CUTOFF,
            "provider_GET_budget":1,"provider_GET_attempts":0,
            "rights_for_automated_monitoring_verified":False,
            "original_upstream_first_publication_verified":False,
            "automatic_watcher_active":False,
            "original_html_persisted":False,"athlete_rows_published":False,
            "odds_or_result_used":False,"model_executed":False,
            "official_prediction":False,
            "status":"UNVERIFIED"}
    try:
        client=opener or build_opener(NoRedirect(),HTTPSHandler())
        result["provider_GET_attempts"]=1
        with client.open(Request(URL,method="GET",headers={
           "Accept":"text/html",
           "User-Agent":"RACE-AI-one-race-nonbetting-official-trial-audit/1"}),
           timeout=9) as resp:
            result["http_status"]=resp.status
            if resp.status!=200 or resp.geturl()!=URL:raise ValueError("source url or status")
            raw=resp.read(LIMIT+1)
        if not 0<len(raw)<=LIMIT:raise ValueError("HTML source size")
        captured=(clock() if clock else datetime.now(timezone.utc)).isoformat()
        report=parse_official_trial(raw,source_url=URL,race_day="2026-10-24",
                venue="isesaki",race_no=11,captured_at=captured,
                scheduled_cutoff_at=CUTOFF)
        result.update(report)
        result["status"]=("RACE_BOUND_NUMERIC_TRIAL_OBSERVED_RESEARCH_ONLY"
                          if report["race_identity_structurally_sufficient"] and
                          report["numeric_trial_car_count"]>0
                          else "NO_RACE_BOUND_NUMERIC_TRIAL_OBSERVED")
        result["source_parser_status"]=report["status"]
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,
            UnicodeError,ImportError) as exc:
        result["status"]="REAL_AUTORACE_SOURCE_OR_PARSER_UNVERIFIED"
        result["error_class"]=type(exc).__name__
        if isinstance(exc,HTTPError):result["http_status"]=exc.code
    result["runner_ended_at_unattested"]=(clock() if clock else datetime.now(timezone.utc)).isoformat()
    return result

def main():
    try:record=probe()
    except RuntimeError:
        print("NO_ONE_SHOT_AUTHORITY");return 2
    print(json.dumps(record,sort_keys=True,ensure_ascii=False))
    return 0 if record["status"] in ("RACE_BOUND_NUMERIC_TRIAL_OBSERVED_RESEARCH_ONLY", "NO_RACE_BOUND_NUMERIC_TRIAL_OBSERVED") else 2

if __name__=="__main__":
    sys.exit(main())
