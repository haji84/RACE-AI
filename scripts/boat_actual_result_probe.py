"""Read-only official result check for one PRE-EXISTING GitHub artifact forecast.

No predictor is run, no old forecast is edited, no Vercel, no wagers.
Only actual official racelist + result after the verified 2026-11-03 cutoff.
"""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib,json,os,re,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/"pr64-reference"
if not (PIN/"race_ai"/"official_race_updates.py").is_file():
    raise SystemExit("PR64_PARSER_NOT_PINNED")
sys.path.insert(0,str(PIN))
from race_ai.official_racelist_adapter import parse_official_racelist,endpoint,MAX_BYTES
from race_ai.official_race_updates import parse_update,endpoint as update_endpoint
from race_ai.tokuyama_day_worker import NoRedirects
from race_ai.core import SourceError
JST=timezone(timedelta(hours=9))
DAY=date(2026,11,3);VENUE="17";NUMBER=1;RACE_ID="20261103-17-01"
CUTOFF=datetime.fromisoformat("2026-11-03T10:18:00+09:00")
FROZEN_TICKETS=("2-1-5","1-2-5","2-5-1","5-2-1","1-5-2","2-1-3","5-1-2","1-2-3")
FORECAST_SHA256="f353ce72e72daac9f4acf444b7a072d1474c90da4c8e2c40bf90342ac340046b"
FORECAST_ARTIFACT_ID=13193749273
FORECAST_ARTIFACT_CREATED="2026-11-03T01:03:09+00:00"
RESULT_OUTPUT=ROOT/"result_output"
calls=0
def finish(code,**data):
    RESULT_OUTPUT.mkdir(parents=True,exist_ok=True)
    result=dict(schema="RACE_AI_BOAT_ACTUAL_PDCA_ONE_SHOT_V1",status=code,race_id=RACE_ID,
        frozen_forecast_artifact_id=FORECAST_ARTIFACT_ID,
        frozen_forecast_json_sha256=FORECAST_SHA256,
        frozen_forecast_created_at=FORECAST_ARTIFACT_CREATED,
        frozen_cutoff_at=CUTOFF.isoformat(),
        frozen_picks=list(FROZEN_TICKETS),actual_official_result_observed=False,
        actual_purchase=False,prediction_recomputed_after_result=False,
        source_gets=calls,result_verified_at=datetime.now(timezone.utc).isoformat())
    result.update(data)
    (RESULT_OUTPUT/"result.json").write_text(json.dumps(result,sort_keys=True,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print(json.dumps({k:result.get(k) for k in ("status","race_id","source_gets","official_top3","hit_at_1","hit_at_8")},ensure_ascii=False))
def fetch(url):
    global calls
    if calls>=2:raise ValueError("SOURCE_GET_LIMIT")
    calls+=1
    request=urllib.request.Request(url,headers={"Accept":"text/html","User-Agent":"RACE-AI-owner-reviewed-result-single-readonly/1"})
    with urllib.request.build_opener(NoRedirects()).open(request,timeout=12) as r:
        raw=r.read(MAX_BYTES+1)
        if r.status!=200 or r.url!=url or not 0<len(raw)<=MAX_BYTES or not (r.headers.get("content-type") or "").lower().startswith("text/html"):
            raise ValueError("SOURCE_RESPONSE_INVALID")
    return raw,datetime.now(timezone.utc),hashlib.sha256(raw).hexdigest()
def run():
    now=datetime.now(timezone.utc)
    if now.astimezone(JST).date()!=DAY or now<CUTOFF+timedelta(seconds=90):
        return finish("NO_RESULT_EXPECTED_YET_OR_WRONG_DAY")
    if os.environ.get("BOAT_RESULT_ONE_SHOT_OWNER_APPROVED")!="true":
        return finish("SOURCE_REVIEW_NOT_ADMITTED")
    if datetime.fromisoformat(FORECAST_ARTIFACT_CREATED)>=CUTOFF:
        return finish("FROZEN_FORECAST_NOT_EARLIER_THAN_CUTOFF")
    try:
        listing_url=endpoint(DAY,VENUE,NUMBER)
        raw,captured,program_sha=fetch(listing_url)
        listed=parse_official_racelist(raw,day=DAY,venue=VENUE,race_no=NUMBER,source_url=listing_url,captured_at=captured.isoformat())
        if datetime.fromisoformat(listed["closed_at"])!=CUTOFF:
            raise ValueError("OFFICIAL_CUTOFF_CHANGED")
        result_url=update_endpoint(DAY,VENUE,NUMBER,"raceresult")
        result_raw,observed,result_sha=fetch(result_url)
        record=parse_update(result_raw,kind="raceresult",day=DAY,venue=VENUE,race_no=NUMBER,
            source_url=result_url,captured_at=observed.isoformat(),entries=listed["boats"])
        data=record.get("data")
        if record.get("status")!="AVAILABLE" or not isinstance(data,dict) or data.get("finish_confirmed") is not True:
            return finish("OFFICIAL_RESULT_NOT_FINAL_OR_UNSUPPORTED",
                observed_source_sha256=result_sha,official_result_state=record.get("status"))
        if data.get("status")!="settled" or data.get("refund_boats") or data.get("refunds") not in ([],None):
            return finish("OFFICIAL_SPECIAL_OR_REFUND_NOT_ADMITTED",
                observed_source_sha256=result_sha,official_result_state=data.get("status"))
        triple=data.get("top3")
        if not isinstance(triple,list) or len(triple)!=3 or set(triple)-set(range(1,7)) or len(set(triple))!=3:
            return finish("OFFICIAL_WINNING_COMBINATION_NOT_VERIFIED",observed_source_sha256=result_sha)
        if observed<CUTOFF:raise ValueError("RESULT_BECAME_PRE_RACE")
        combo="-".join(map(str,triple))
        payouts=[p for p in data.get("payouts",[]) if p.get("bet_type")=="trifecta" and p.get("combination")==triple]
        payout=payouts[0]["payout_per_100_yen"] if len(payouts)==1 else None
        return finish("OFFICIAL_RESULT_COMPARED_WITH_EARLIER_ARTIFACT",
            observed_source_sha256=result_sha,observed_source_url=result_url,
            observed_source_captured_at=observed.isoformat(),program_source_sha256=program_sha,
            actual_official_result_observed=True,official_top3=combo,
            official_trifecta_payout_per_100_yen=payout,
            hit_at_1=int(combo==FROZEN_TICKETS[0]),
            hit_at_8=int(combo in FROZEN_TICKETS),
            model_version="PR64-style-rating-display-PL-uncalibrated-readonly",
            pdca_status="ONE_RACE_VERIFIED_NOT_AUTO_TRAINED",next_race_model_auto_approved=False)
    except (SourceError,OSError,ValueError,TimeoutError,KeyError,TypeError,UnicodeError) as e:
        return finish("OFFICIAL_RESULT_SOURCE_INVALID_OR_UNAVAILABLE",failure_class=type(e).__name__)
if __name__=="__main__":run()
