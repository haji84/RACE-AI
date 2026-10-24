"""One-shot same-day B-LITE *unadmitted* research shadow, NOT an official prediction.

Uses only published numerical FACTS observed in a bounded official B download.
Never invents published_at/sample_n/rights. Does NOT call B-LITE validate_snapshot
or claim an admitted evidence-based model. Frozen results require separate GitHub
proof and MUST NOT count toward formal Hit@8.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib, json, math, os, sys
from pathlib import Path
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import race_ai
PARSER = ROOT/"pr64-parser-reference"/"race_ai"
if PARSER.is_dir():
    race_ai.__path__.append(str(PARSER))

from race_ai.boat_sparse_shadow_models import LITE_ID, BASE_WEIGHTS, _distribution, _stable_hash

RACE = "20261024-11-11"
DAY = "2026-10-24"
EXPECTED_REGISTRATIONS = ("4512","4144","4550","5319","4746","3874")
CUTOFF = "2026-10-24T15:09:00+09:00"
SOURCE = "https://www1.mbrace.or.jp/od2/B/202610/b261024.lzh"
BRANCH = "refs/heads/p0-b-live-shadow-20261024"
ADMIT = "ONE-BOAT-B-RESEARCH-20261024"
MAX_BYTES = 4_000_000


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kw):
        raise ValueError("redirect is not supported")


def main():
    env=os.environ
    if (env.get("GITHUB_EVENT_NAME")!="push" or env.get("GITHUB_REF")!=BRANCH
        or env.get("RACE_AI_RESEARCH_ONE_SHOT")!=ADMIT
        or len(env.get("GITHUB_SHA",""))!=40):
        print("UNADMITTED_ONE_SHOT_INVOCATION")
        return 2
    now=datetime.now(timezone.utc)
    if now >= datetime.fromisoformat(CUTOFF):
        print("NO_FORECAST_AFTER_SCHEDULED_CUTOFF")
        return 2
    try:
        from race_ai.official_lzh_extract import extract_daily_lzh
        from race_ai.core import parse_b
        from race_ai.official_b_snapshot_adapter import program_details
        opener=build_opener(RejectRedirect(),HTTPSHandler())
        with opener.open(Request(SOURCE,method="GET",
            headers={"Accept":"application/octet-stream",
                     "User-Agent":"RACE-AI-one-day-personal-research-shadow/1"}),
            timeout=10) as response:
            if response.status!=200 or response.geturl()!=SOURCE:
                raise ValueError("unexpected official response")
            raw=response.read(MAX_BYTES+1)
        if not 25<=len(raw)<=MAX_BYTES or raw[2:7] not in (
                b"-lh0-",b"-lh1-",b"-lh4-",b"-lh5-",b"-lh6-",b"-lh7-"):
            raise ValueError("unknown B archive")
        source_sha=hashlib.sha256(raw).hexdigest()
        expanded=extract_daily_lzh(raw,"B261024.TXT")
        entrants=parse_b(expanded,DAY)
        details,closing=program_details(expanded,date(2026,10,24))
        if closing.get(RACE)!=CUTOFF or len(entrants)!=len(details):
            raise ValueError("B schedule/detail completeness mismatch")
        roster=sorted((x["lane"],x["racer_id"]) for x in entrants if x["race_id"]==RACE)
        if roster!=list(enumerate(EXPECTED_REGISTRATIONS,1)):
            raise ValueError("first-party roster mismatch")
        weights=BASE_WEIGHTS
        strengths={}
        for lane in range(1,7):
            item=details.get((RACE,lane))
            if item is None or item["racer_registration_id"]!=EXPECTED_REGISTRATIONS[lane-1]:
                raise ValueError("missing or mismatched entrant")
            vals={
                "ability":item["national_win_rate"]/10,
                "course_compatibility":item["local_win_rate"]/10,
                "motor_form":item["motor_top2_rate"]/100,
            }
            if any(type(v) not in (int,float) or not math.isfinite(v)
                   or not 0<=v<=1 for v in vals.values()):
                raise ValueError("out-of-range published numeric fact")
            score=math.fsum(weights[k]*vals[k] for k in weights)/math.fsum(weights.values())
            strengths[lane]=math.exp(2*score)
        choices=_distribution(strengths)
        if (len(choices)!=120 or len({tuple(c) for c,_ in choices})!=120
            or len({tuple(c) for c,_ in choices[:8]})!=8
            or not math.isclose(math.fsum(v for _,v in choices),1,rel_tol=0,abs_tol=1e-9)):
            raise ValueError("invalid normalized full trifecta universe")
        if datetime.now(timezone.utc)>=datetime.fromisoformat(CUTOFF):
            raise ValueError("result not generated before scheduled cutoff")
        report={
            "schema":"RACE_AI_ONE_SHOT_UNADMITTED_B_LITE_RESEARCH_PREVIEW_V1",
            "race_id":"boat:2026-10-24:boatrace-jcd-11:11",
            "model_id":LITE_ID,
            "model_version":"0.1.0-UNTRAINED",
            "not_same_as_verified_B_LITE_model_input":True,
            "official_prediction":False,
            "formal_hit_at_8_eligible":False,
            "source_url":SOURCE,
            "source_archive_sha256":source_sha,
            "source_numeric_fields":["national_win_rate","local_win_rate","motor_top2_rate"],
            "source_published_at":None,
            "source_sample_n":None,
            "source_rights_verified":False,
            "source_use":"ONE_SHOT_RESEARCH_PROVISIONAL",
            "source_rows_retained":False,
            "odds_used":False,
            "official_result_used":False,
            "scheduled_cutoff_at":CUTOFF,
            "created_at_runner_clock_unattested":datetime.now(timezone.utc).isoformat(),
            "candidate_count":120,
            "ordered_top8":[list(c) for c,_ in choices[:8]],
            "full_ranking_digest":_stable_hash([{"ticket":list(c),"score":v} for c,v in choices]),
            "trained":False,
            "calibrated":False,
            "external_pre_cutoff_receipt":None,
            "future_result":None,
            "status":"RESEARCH_UNADMITTED_PREVIEW_NOT_FORMAL_FORECAST"
        }
        report["prediction_sha256"]=_stable_hash(report)
        print(json.dumps(report,sort_keys=True,ensure_ascii=False))
        return 0
    except Exception as exc:
        # Never dump extracted source text or racer/player data.
        print(json.dumps({"schema":"RACE_AI_RESEARCH_PREVIEW_FAILURE_V1",
                          "status":"NO_RESEARCH_PREVIEW","error_type":type(exc).__name__,
                          "official_prediction":False,"prediction_sha256":None,
                          "source":"BOAT_RACE_OFFICIAL_B","race_id":"boat:2026-10-24:boatrace-jcd-11:11"}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
