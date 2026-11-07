"""Independent official up-to-three-race results versus nationwide PRE-CUTOFF A/B artifact.

Read original GitHub Actions artifact (never rerank or change forecast);
require server-created-at before each official cutoff and original sha readback.
Fetch only post-close official result and identity per race, <=6 GET total.
No Vercel, model retraining, automatic wagers or public raw data writes.
"""
from __future__ import annotations

from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sys
from urllib import error,request

ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/"pr64-reference"
if not (PIN/"race_ai"/"official_race_updates.py").is_file():
    raise SystemExit("PINNED_PR64_RESULT_ADAPTER_REQUIRED")
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(PIN))

from race_ai.official_racelist_adapter import parse_official_racelist, endpoint, JST, MAX_BYTES
from race_ai.official_race_updates import parse_update, endpoint as update_endpoint
from race_ai.tokuyama_day_worker import NoRedirects
from race_ai.core import SourceError
import race_ai
race_ai.__path__.insert(0,str(ROOT/"race_ai"))
from race_ai.boat_ab_result_audit import score_pair
from race_ai.boat_result_date_policy import is_past_or_current_result_day
from race_ai.boat_historical_result_roster import validate_historical_result_roster

OUT=ROOT/"boat_national_result_output"
RUN_ID=41575766782
ARTIFACT_ID=13202833722
FORECAST_SHA="bcea16257ddf2a713c138458757a6d79067b6d2f2e0cf806a32fc527270a2d6d"
requests_used=0
GET_LIMIT=6


def output(rows, reason):
    OUT.mkdir(exist_ok=True)
    packet={
        "schema":"RACE_AI_BOAT_NATIONAL_3R_RESULT_AUDIT_V1",
        "official_results":rows,
        "status":reason,
        "as_of":datetime.now(timezone.utc).isoformat(),
        "frozen_run_id":RUN_ID,
        "frozen_artifact_id":ARTIFACT_ID,
        "frozen_forecast_json_sha256":FORECAST_SHA,
        "official_source_requests_used":requests_used,
        "past_predictions_untouched":True,
        "model_coefficients_unchanged":True,
        "research_only":True,
        "v e r c e l".replace(" ",""):False,
        "actual_purchases":False,
    }
    (OUT/"result.json").write_text(json.dumps(packet,ensure_ascii=False,sort_keys=True,
        separators=(",",":"),allow_nan=False),encoding="utf-8")
    print(json.dumps({"status":reason,"requests_used":requests_used,"results":[
        {key:r.get(key) for key in ("race_id","state","official_top3","payout_per_100_yen",
                                  "actual_man_shu")}
        for r in rows]},ensure_ascii=False))
    return packet


def get(url):
    global requests_used
    if requests_used>=GET_LIMIT:raise SourceError("SOURCE_REQUEST_LIMIT")
    requests_used+=1
    req=request.Request(url,headers={"Accept":"text/html",
                                     "User-Agent":"RACE-AI-research-nationwide-result/1.0"})
    with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
        body=response.read(MAX_BYTES+1)
        if (response.status!=200 or response.geturl()!=url
                or not 0<len(body)<=MAX_BYTES
                or not (response.headers.get("content-type") or "").lower().startswith("text/html")):
            raise SourceError("OFFICIAL_RESULT_HTTP_INVALID")
    return body,datetime.now(timezone.utc),hashlib.sha256(body).hexdigest()


def run():
    global requests_used
    requests_used=0
    if os.environ.get("RACE_AI_NATIONAL_RESULT_OWNER_REVIEWED")!="true":
        return output([],"RIGHTS_REVIEW_REQUIRED")
    original=ROOT/"national_source"/"national.json"
    if not original.is_file() or original.stat().st_size>250000:
        return output([],"ORIGINAL_FORECAST_MISSING")
    raw=original.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FORECAST_SHA:
        return output([],"FORECAST_HASH_REJECTED")
    frozen=json.loads(raw)
    pairs=frozen.get("paired_forecasts")
    if (frozen.get("schema")!="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1"
            or frozen.get("state")!="FORECASTS_GENERATED_NEED_ARTIFACT_CLOCK_VERIFICATION"
            or not isinstance(pairs,list) or not (1<=len(pairs)<=3)):
        return output([],"FREEZE_SET_INVALID")
    # The original ZIP was separately authenticated before this script runs.
    # A historical result can use only the sealed pre-close six-racer shadow
    # already present in that same ZIP, never a reconstructed/new forecast.
    shadows=frozen.get("additional_official_feature_shadows",[])
    if not isinstance(shadows,list) or any(not isinstance(x,dict) or not isinstance(x.get("race_id"),str) for x in shadows):
        return output([],"FROZEN_SHADOW_INDEX_INVALID")
    shadow_by_id={x["race_id"]:x for x in shadows}
    if len(shadow_by_id)!=len(shadows):
        return output([],"DUPLICATE_FROZEN_SHADOW_INDEX")
    saved_at=os.environ.get("RACE_AI_NATIONAL_GITHUB_CREATED_AT")
    try: saved=datetime.fromisoformat(saved_at.replace("Z","+00:00"))
    except (AttributeError,ValueError):return output([],"ARTIFACT_SERVER_CLOCK_UNVERIFIED")
    results=[]
    blocked_source=False
    for pair in pairs:
        if blocked_source:
            results.append({"race_id":pair["race_id"],"state":"SOURCE_4XX_STOP_NO_REQUEST"})
            continue
        rid=pair["race_id"]
        closing=datetime.fromisoformat(pair["cutoff_at"])
        if not isinstance(rid,str) or not re.fullmatch(r"\d{8}-(0[1-9]|1\d|2[0-4])-(0[1-9]|1[0-2])",rid):
            results.append({"race_id":rid,"state":"INVALID_RACE_ID"});continue
        if not saved<closing:
            results.append({"race_id":rid,"state":"NOT_PRE_CLOSE_FROZEN"});continue
        if datetime.now(timezone.utc)<=closing+timedelta(seconds=90):
            results.append({"race_id":rid,"state":"OFFICIAL_RESULT_WAIT_AFTER_CUTOFF"});continue
        # Historical result rechecks are valid after JST midnight. The
        # independent pre-close original and exact official identity checks
        # below still apply; future event dates remain forbidden.
        if not is_past_or_current_result_day(rid[:8],datetime.now(timezone.utc)):
            results.append({"race_id":rid,"state":"FUTURE_RACE_DATE"});continue
        day=date(int(rid[:4]),int(rid[4:6]),int(rid[6:8]))
        venue=rid[9:11]
        number=int(rid[-2:])
        phase="START"
        try:
            historical=day<datetime.now(timezone.utc).astimezone(JST).date()
            roster_proof=None
            if historical:
                if rid not in shadow_by_id:
                    results.append({"race_id":rid,"state":"HISTORIC_PRE_CLOSE_ROSTER_MISSING"})
                    continue
                # PR64 racelist parser forbids D+1 captures, intentionally.
                # Do not lie about the fetch time or change pinned PR64.
                # The original sealed C-lite supplies the preclose six IDs.
                program_sha=pair["program_source_sha256"]
                result_url=update_endpoint(day,venue,number,"raceresult")
                phase="HISTORIC_RESULT_GET"
                source,observed,source_sha=get(result_url)
                phase="HISTORIC_RESULT_PARSE"
                result=parse_update(source,kind="raceresult",day=day,venue=venue,
                     race_no=number,source_url=result_url,captured_at=observed.isoformat(),
                     entries=None)
                if result.get("body_identity_verified") is not True or result.get("closed_at")!=pair["cutoff_at"]:
                    raise SourceError("HISTORIC_RESULT_CONTEXT_NOT_VERIFIED")
                data=result.get("data")
                if (result.get("status")=="AVAILABLE" and isinstance(data,dict)
                        and data.get("finish_confirmed") is True):
                    phase="HISTORIC_ROSTER_CROSSCHECK"
                    roster_proof=validate_historical_result_roster(
                        pair,shadow_by_id[rid],result,saved_at)
            else:
                phase="CURRENT_RACELIST_GET"
                url=endpoint(day,venue,number)
                raw_program,obs_program,program_sha=get(url)
                phase="CURRENT_RACELIST_PARSE"
                program=parse_official_racelist(raw_program,day=day,venue=venue,
                    race_no=number,source_url=url,captured_at=obs_program.isoformat())
                if program["closed_at"]!=pair["cutoff_at"] or program["race_id"]!=rid:
                    raise SourceError("OFFICIAL_PROGRAM_CHANGED")
                result_url=update_endpoint(day,venue,number,"raceresult")
                phase="CURRENT_RESULT_GET"
                source,observed,source_sha=get(result_url)
                phase="CURRENT_RESULT_PARSE"
                result=parse_update(source,kind="raceresult",day=day,venue=venue,
                     race_no=number,source_url=result_url,captured_at=observed.isoformat(),
                     entries=program["boats"])
                data=result.get("data")
            if (isinstance(data,dict) and data.get("status") in ("cancelled","no_contest","postponed")
                    and data.get("confirmed") is True):
                results.append({"race_id":rid,"state":"OFFICIAL_RESULT_CANCELLED_OR_NO_CONTEST",
                    "official_outcome_status":data["status"],
                    "official_source_sha256":source_sha,
                    "result_captured_at":observed.isoformat(),
                    "excluded_from_normal_hit8_and_roi":True})
                continue
            phase="RESULT_SETTLEMENT_CHECK"
            if result.get("status")!="AVAILABLE" or not isinstance(data,dict) or data.get("finish_confirmed") is not True:
                results.append({"race_id":rid,"state":"OFFICIAL_RESULT_NOT_FINAL",
                      "result_source_sha256":source_sha});continue
            if data.get("status")!="settled" or data.get("refund_boats") or data.get("refunds") not in ([],None):
                results.append({"race_id":rid,"state":"OFFICIAL_RESULT_REFUND_OR_SPECIAL",
                      "result_source_sha256":source_sha});continue
            triple=data.get("top3")
            if (not isinstance(triple,list) or len(triple)!=3 or
                    any(type(x) is not int or x not in range(1,7) for x in triple)
                    or len(set(triple))!=3):
                results.append({"race_id":rid,"state":"OFFICIAL_TOP3_UNVERIFIED"});continue
            payout=[p["payout_per_100_yen"] for p in data.get("payouts",[])
                    if p.get("bet_type")=="trifecta" and p.get("combination")==triple]
            if len(payout)!=1 or type(payout[0]) is not int:
                results.append({"race_id":rid,"state":"TRIFECTA_OFFICIAL_PAYOUT_UNVERIFIED"});continue
            # Settled trifecta does NOT imply an ordinary six-finisher race.
            # A capsize/disqualification can coexist with a confirmed 3T payout,
            # and must remain a separately flagged outcome, not silently enter
            # normal no-incident Hit@8, Brier or ROI denominators.
            finishes=data.get("results")
            if not isinstance(finishes,list) or len(finishes)!=6 or {x.get("lane") for x in finishes}!=set(range(1,7)):
                raise SourceError("OFFICIAL_FINISH_DISPOSITIONS_INCOMPLETE")
            unusual=[{"lane":x["lane"],"finish_status":x.get("finish_status")}
                     for x in finishes if x.get("finish_status")!="FINISHED"]
            if unusual:
                results.append({
                    "race_id":rid,"state":"OFFICIAL_RESULT_ABNORMAL_FINISH_SEPARATE",
                    "official_top3":"-".join(map(str,triple)),
                    "payout_per_100_yen":payout[0],
                    "actual_man_shu":payout[0]>=10000,
                    "abnormal_finish_dispositions":unusual,
                    "official_source_sha256":source_sha,
                    "result_captured_at":observed.isoformat(),
                    "program_source_sha256":program_sha,
                    "historical_roster_identity":roster_proof,
                    "excluded_from_normal_hit8_and_roi":True,
                })
                continue
            pair_original={
               "schema":"RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
               "status":"REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
               "race_id":rid,"cutoff_at":pair["cutoff_at"],
               "result_used":False,"paired_forecast":pair,
            }
            winner="-".join(map(str,triple))
            scores=score_pair(pair_original,winner,observed.isoformat(),saved_at)
            results.append({
                "race_id":rid,"state":"INDEPENDENT_AB_RESULT_VERIFIED",
                "official_top3":winner,"payout_per_100_yen":payout[0],
                "actual_man_shu":payout[0]>=10000,
                "official_source_sha256":source_sha,
                "result_captured_at":observed.isoformat(),
                "program_source_sha256":program_sha,
                "historical_roster_identity":roster_proof,
                "paired_comparison":scores,
                "both_missed_man_shu":payout[0]>=10000 and all(
                      m["hit_at_8"]==0 for m in scores["models"]),
            })
        except error.HTTPError as ex:
            blocked_source=400<=ex.code<500
            results.append({"race_id":rid,"state":"OFFICIAL_RESULT_SAFE_STOP",
                            "failure_class":"HTTPError","failure_phase":phase,
                            "http_status":ex.code})
        except (SourceError,ValueError,TypeError,OSError,error.URLError,TimeoutError,UnicodeError,KeyError) as ex:
            results.append({"race_id":rid,"state":"OFFICIAL_RESULT_SAFE_STOP",
                            "failure_class":type(ex).__name__,
                            "failure_phase":phase})
    status="SOME_RESULTS_VERIFIED" if any(r["state"]=="INDEPENDENT_AB_RESULT_VERIFIED" for r in results) else "OFFICIAL_RESULTS_PENDING_OR_UNVERIFIED"
    return output(results,status)


if __name__=="__main__":
    run()
