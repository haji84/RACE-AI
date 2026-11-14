"""Compare actual official result with the EXACT earlier A/B GitHub artifact.

One result, no re-prediction, no Vercel, no wagers. The original artifact
is downloaded read-only, server-created timestamp verified independently.
"""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib,json,os,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PIN=ROOT/"pr64-reference"
if not (PIN/"race_ai"/"official_race_updates.py").exists():
    raise SystemExit("PINNED_PR64_RESULT_PARSER_REQUIRED")
sys.path.insert(0,str(PIN))
from race_ai.official_racelist_adapter import parse_official_racelist,endpoint,JST
from race_ai.official_race_updates import parse_update,endpoint as result_endpoint
from race_ai.core import SourceError
from scripts import boat_actual_one_shot_probe as source
import importlib.util
spec=importlib.util.spec_from_file_location("ab_result_audit",ROOT/"race_ai"/"boat_ab_result_audit.py")
# The pure audit module uses relative imports, so expose the PR71 root race_ai
# package path just for these two frozen research modules.
import race_ai
race_ai.__path__.insert(0,str(ROOT/"race_ai"))
from race_ai.boat_ab_result_audit import score_pair

DAY=date(2026,11,3);VENUE="17";RACE=2;RACE_ID="20261103-17-02"
EXPECTED_JSON_SHA256="2666d0de2a0cbda26835a5e738f70b72f242f0862c6e2a6ce0af704ba4e2caff"
EXPECTED_CUTOFF="2026-11-03T10:55:00+09:00"
EXPECTED_RUN_ID=41561946057
OUT=ROOT/"boat_ab_result_output"

def emit(state,**kwargs):
    OUT.mkdir(exist_ok=True)
    report={"schema":"RACE_AI_BOAT_AB_REAL_RESULT_PILOT_V1","status":state,
            "race_id":RACE_ID,"original_run_id":EXPECTED_RUN_ID,
            "original_artifact_file_sha256":EXPECTED_JSON_SHA256,
            "forecast_recreated_after_result":False,
            "source_gets":source.calls,"purchase_decision":"NO_BET",**kwargs}
    (OUT/"result.json").write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,
                 separators=(",",":"),allow_nan=False),encoding="utf-8")
    print(json.dumps({k:report.get(k) for k in
          ("status","race_id","official_top3","source_gets","official_trifecta_payout_per_100_yen")},ensure_ascii=False))
    return report

def main():
    source.calls=0
    now=datetime.now(timezone.utc)
    if now.astimezone(JST).date()!=DAY or now<datetime.fromisoformat(EXPECTED_CUTOFF)+timedelta(seconds=100):
        return emit("WAITING_RESULT_OR_DATE")
    if os.environ.get("RACE_AI_AB_RESULT_SOURCE_REVIEWED")!="true":
        return emit("OFFICIAL_RESULT_PERMISSION_MISSING")
    original_path=ROOT/"ab_input"/"pair.json"
    try:
        content=original_path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=EXPECTED_JSON_SHA256:
            raise ValueError("IMMUTABLE_GITHUB_ORIGINAL_FILE_HASH_CHANGED")
        original=json.loads(content)
        created_at=os.environ.get("RACE_AI_AB_GITHUB_CREATED_AT")
        if not created_at or datetime.fromisoformat(created_at.replace("Z","+00:00"))>=datetime.fromisoformat(EXPECTED_CUTOFF):
            raise ValueError("GITHUB_SERVER_SAVE_NOT_PRE_CUTOFF")
        if original.get("race_id")!=RACE_ID or original.get("cutoff_at")!=EXPECTED_CUTOFF:
            raise ValueError("FROZEN_RACE_MISMATCH")
    except (OSError,ValueError,KeyError,TypeError) as error:
        return emit("FORECAST_FROZEN_ORIGINAL_UNVERIFIED",error_type=type(error).__name__)
    try:
        program_url=endpoint(DAY,VENUE,RACE)
        program_raw,at,program_hash=source.fetch(program_url)
        program=parse_official_racelist(program_raw,day=DAY,venue=VENUE,race_no=RACE,
                      source_url=program_url,captured_at=at.isoformat())
        if program["race_id"]!=RACE_ID or program["closed_at"]!=EXPECTED_CUTOFF:
            raise ValueError("RESULT_PROGRAM_CLOCK_CONFLICT")
        result_url=result_endpoint(DAY,VENUE,RACE,"raceresult")
        raw,captured,result_hash=source.fetch(result_url)
        official=parse_update(raw,kind="raceresult",day=DAY,venue=VENUE,race_no=RACE,
               source_url=result_url,captured_at=captured.isoformat(),entries=program["boats"])
        data=official.get("data")
        if official["status"]!="AVAILABLE" or not isinstance(data,dict) or data.get("finish_confirmed") is not True:
            return emit("OFFICIAL_RESULT_PENDING_OR_UNSUPPORTED",source_sha256=result_hash)
        if data.get("status")!="settled" or data.get("refund_boats") or data.get("refunds") not in ([],None):
            return emit("OFFICIAL_RESULT_SPECIAL_OR_REFUNDED",source_sha256=result_hash)
        triple=data.get("top3")
        if (not isinstance(triple,list) or len(triple)!=3
                or any(type(x) is not int or x not in range(1,7) for x in triple)
                or len(set(triple))!=3):
            return emit("OFFICIAL_TOP3_UNVERIFIED",source_sha256=result_hash)
        payout=[x["payout_per_100_yen"] for x in data.get("payouts",[])
                if x.get("bet_type")=="trifecta" and x.get("combination")==triple]
        comparison=score_pair(original,"-".join(map(str,triple)),captured.isoformat(),created_at)
        return emit("INDEPENDENT_OFFICIAL_AB_PDCA_VERIFIED",
            official_top3="-".join(map(str,triple)),official_trifecta_payout_per_100_yen=payout[0] if len(payout)==1 else None,
            result_source_url=result_url,result_source_sha256=result_hash,
            result_captured_at=captured.isoformat(),program_source_sha256=program_hash,
            frozen_artifact_server_saved_at=created_at,
            paired_comparison=comparison,
            model_auto_promoted=False,
            next_race_action="KEEP_A_AND_B_AS_SEPARATE_RESEARCH_MODELS_UNTIL_FUTURE_UNSEEN_EVALUATIONS")
    except (SourceError,OSError,ValueError,KeyError,TypeError,UnicodeError,TimeoutError) as err:
        return emit("OFFICIAL_RESULT_NOT_VERIFIED",error_type=type(err).__name__)


if __name__=="__main__":
    main()
