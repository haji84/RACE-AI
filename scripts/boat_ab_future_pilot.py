"""Freeze two research models for one actual future BOAT race. No Vercel.
Source HTML remains memory-only. Artifact clock must be independently checked.
"""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import importlib.util,json,os,re,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PIN=ROOT/"pr64-reference"
if not (PIN/"race_ai"/"official_racelist_adapter.py").exists():
    raise SystemExit("PR64_PARSER_PIN_REQUIRED")
sys.path.insert(0,str(PIN))
from race_ai.official_racelist_adapter import Tree,Node,one,endpoint,JST,parse_official_racelist,numeric_tokens
from race_ai.official_race_updates import parse_update,endpoint as update_endpoint
from race_ai.core import SourceError
from scripts import boat_actual_one_shot_probe as previous

spec=importlib.util.spec_from_file_location("boat_ab_shadow",ROOT/"race_ai"/"boat_ab_shadow.py")
pair_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(pair_module)
VENUE="17"
OUT=ROOT/"boat_ab_output"
MAX_REQUESTS=3

def emit(reason,**kwargs):
    OUT.mkdir(exist_ok=True)
    data={"schema":"RACE_AI_BOAT_LIVE_AB_RESEARCH_V1","status":"NO_PAIR","reason":reason,
          "as_of":datetime.now(timezone.utc).isoformat(),"source_gets":previous.calls,
          "result_used":False,"models_calibrated":False,
          "github_artifact_preclose_verified":False,**kwargs}
    (OUT/"pair.json").write_text(json.dumps(data,sort_keys=True,ensure_ascii=False,
                                 separators=(",",":"),allow_nan=False),encoding="utf-8")
    print(json.dumps({k:data.get(k) for k in ("status","reason","race_id","cutoff_at","source_gets","model_count")},ensure_ascii=False))
    return data

def motor_top2(raw,entries):
    tree=Tree();tree.feed(raw.decode("utf-8"))
    if tree.invalid:raise SourceError("MOTOR_HTML_INVALID")
    frame=one(tree.root.find(css="contentsFrame1_inner"),"official content")
    detail=one(frame.find(css="is-tableFixed__3rdadd"),"official six racer frame")
    table=one(detail.find("table"),"official roster")
    bodies=list(table.find("tbody"))
    if len(bodies)!=6:raise SourceError("MOTOR_NOT_SIX_BODIES")
    bylane={x["lane"]:x for x in entries}
    found={}
    for body in bodies:
        tr=next(body.find("tr"),None)
        if tr is None:raise SourceError("MOTOR_NO_RACER_ROW")
        cols=[c for c in tr.children if isinstance(c,Node) and c.tag=="td"]
        if len(cols)<8 or not re.fullmatch("[1-6]",cols[0].text().strip()):
            raise SourceError("MOTOR_ROSTER_LAYOUT")
        lane=int(cols[0].text().strip())
        if lane in found or lane not in bylane:raise SourceError("MOTOR_DUPLICATE_LANE")
        tokens=cols[6].text().split()
        if len(tokens)!=3 or not tokens[0].isdigit() or int(tokens[0])!=bylane[lane]["motor_no"]:
            raise SourceError("MOTOR_NO_MISMATCH")
        rates=numeric_tokens(Node("stats",children=[" ".join(tokens[1:])]),2,maximum=100)
        if rates[0] is None or rates[1] is None:raise SourceError("MOTOR_RATE_NOT_PUBLISHED")
        found[lane]=float(rates[0])
    if set(found)!=set(range(1,7)):raise SourceError("MOTOR_INCOMPLETE")
    return found

def run():
    previous.calls=0
    now=datetime.now(timezone.utc)
    date=now.astimezone(JST).date()
    if date.isoformat()!="2026-11-03":return emit("ONE_SHOT_WRONG_DAY")
    if os.environ.get("RACE_AI_AB_SOURCE_REVIEWED")!="true":return emit("NO_SOURCE_APPROVAL")
    try:
        idx_url=endpoint(date,VENUE,1)
        initial,ts,idxhash=previous.fetch(idx_url)
        parse_official_racelist(initial,day=date,venue=VENUE,race_no=1,
                   source_url=idx_url,captured_at=ts.isoformat())
        times=previous.schedule(initial,date,VENUE)
        now=datetime.now(timezone.utc)
        candidates=sorted((close,n) for n,close in times.items()
              if timedelta(seconds=180)<close-now<timedelta(minutes=22))
        if not candidates:
            return emit("NO_RACE_IN_SAFE_WINDOW",
                        next_cutoff_at=min((t.isoformat() for t in times.values() if t>now),default=None))
        close,n=candidates[0]
        rid=f"{date:%Y%m%d}-{VENUE}-{n:02d}"
        if previous.calls>=MAX_REQUESTS:raise SourceError("GET_BUDGET")
        url=endpoint(date,VENUE,n)
        program_raw,rt,program_hash=previous.fetch(url)
        program=parse_official_racelist(program_raw,day=date,venue=VENUE,race_no=n,
                                 source_url=url,captured_at=rt.isoformat())
        if program["race_id"]!=rid or datetime.fromisoformat(program["closed_at"])!=close:
            raise ValueError("PROGRAM_CUTOFF_OR_ID_CHANGED")
        if any(x["entry_status"]!="listed" for x in program["boats"]):
            return emit("WITHDRAWN_RACE",race_id=rid,cutoff_at=close.isoformat())
        motors=motor_top2(program_raw,program["boats"])
        before_url=update_endpoint(date,VENUE,n,"beforeinfo")
        preview_raw,pt,preview_hash=previous.fetch(before_url)
        observation=parse_update(preview_raw,kind="beforeinfo",day=date,venue=VENUE,race_no=n,
                    source_url=before_url,captured_at=pt.isoformat(),entries=program["boats"])
        if observation["status"]!="AVAILABLE" or observation["data"] is None:
            return emit("EXHIBITION_PENDING",race_id=rid,cutoff_at=close.isoformat())
        six=sorted(observation["data"]["boats"],key=lambda x:x["lane"])
        if len(six)!=6 or any(x["display_time"] is None for x in six):
            return emit("EXHIBITION_INCOMPLETE",race_id=rid,cutoff_at=close.isoformat())
        known={x["lane"]:x for x in program["boats"]}
        racers=[]
        for x in six:
            b=known[x["lane"]]
            if b["racer_registration_id"]!=x["racer_registration_id"]:
                raise ValueError("RACE_ROSTER_CHANGED")
            racers.append({"lane":x["lane"],"racer_id":x["racer_registration_id"],
                    "national_win_rate":b["national_win_rate"],
                    "exhibition_time_seconds":x["display_time"],
                    "motor_two_place_rate_percent":motors[x["lane"]]})
        source={"race_id":rid,"cutoff_at":close.isoformat(),
                "captured_at":max(rt,pt).isoformat(timespec="microseconds"),
                "program_source_sha256":program_hash,"beforeinfo_source_sha256":preview_hash,
                "boats":racers}
        generated=datetime.now(timezone.utc).isoformat(timespec="microseconds")
        paired=pair_module.build_pair(source,generated)
        return emit(None,status="REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                    race_id=rid,cutoff_at=close.isoformat(),model_count=2,
                    paired_forecast=paired,model_fixed_before_result=True,
                    source_urls={"program":url,"beforeinfo":before_url},
                    note="GitHub server artifact.created_at must be less than official cutoff; models uncalibrated.")
    except (SourceError,ValueError,OSError,KeyError,TypeError,UnicodeError,TimeoutError) as e:
        return emit("OFFICIAL_SOURCE_OR_MODEL_REJECTED",failure_class=type(e).__name__)

if __name__=="__main__":
    run()
