"""One GitHub-hosted real BOAT exhibition smoke, Vercel-free, no purchases.

This is an explicitly bounded, one-shot provider observation that is NOT a
scheduler or PR64's cloud Blob publication. Output is an uncalibrated research
forecast. CI artifact creation time must separately predate cutoff before the
result qualifies as an externally timestamped freeze.
"""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import hashlib,itertools,json,math,os,re,sys,urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PREF=ROOT/"pr64-reference"
if not (PREF/"race_ai"/"official_race_updates.py").is_file():
    raise SystemExit("PINNED_PR64_PARSER_REQUIRED")
sys.path.insert(0,str(PREF))
from race_ai.official_racelist_adapter import parse_official_racelist,Tree,one,MAX_BYTES
from race_ai.official_race_updates import parse_update
from race_ai.tokuyama_day_worker import NoRedirects
from race_ai.core import SourceError
from race_ai.official_racelist_adapter import endpoint
from race_ai.official_race_updates import endpoint as update_endpoint

JST=timezone(timedelta(hours=9))
VENUE="17"
RACE_WINDOW=(210,1050) # seconds before verified program cutoff
GET_LIMIT=3
OUTPUT=ROOT/"pilot_output"
calls=0

def fetch(url):
    global calls
    if calls>=GET_LIMIT:raise ValueError("SOURCE_GET_LIMIT")
    calls+=1
    req=urllib.request.Request(url,headers={"Accept":"text/html","User-Agent":"RACE-AI-owner-reviewed-one-shot-proof/1.0"})
    with urllib.request.build_opener(NoRedirects()).open(req,timeout=12) as r:
        raw=r.read(MAX_BYTES+1)
        if r.status!=200 or r.url!=url or len(raw)>MAX_BYTES or not (r.headers.get("content-type") or "").lower().startswith("text/html"):
            raise ValueError("SOURCE_UNEXPECTED_RESPONSE")
    return raw,datetime.now(timezone.utc),hashlib.sha256(raw).hexdigest()

def schedule(raw,day,venue):
    tree=Tree();tree.feed(raw.decode("utf-8"))
    if tree.invalid:raise ValueError("HTML_INVALID")
    frame=one(tree.root.find(css="contentsFrame1_inner"),"body")
    choices=[t for t in frame.find("table") if "締切予定時刻" in t.text()]
    table=one(choices,"scheduled times")
    rows=list(one(table.find("tbody"),"time table body").find("tr"))
    line=one(rows,"times")
    fields=[x.text().strip() for x in line.find("td")]
    if len(fields)!=13 or fields[0]!="締切予定時刻":raise ValueError("SCHEDULE_CELLS_INVALID")
    result={}
    for r,part in enumerate(fields[1:],1):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",part):raise ValueError("SCHEDULE_TIME_INVALID")
        result[r]=datetime.fromisoformat(day.isoformat()+"T"+part+":00+09:00")
    return result

def status(**kw):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    value={"schema":"RACE_AI_REAL_BOAT_ONE_SHOT_V1","source_gets":calls,"venue_code":VENUE,"as_of":datetime.now(timezone.utc).isoformat(),
           "status":"NO_FORECAST", "research_only":True,"scores_calibrated":False,
           "github_artifact_created_before_cutoff_verified":False,"real_pre_cutoff_cloud_saved":False,**kw}
    (OUTPUT/"pilot.json").write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
    print(json.dumps({"status":value["status"],"race_id":value.get("race_id"),"reason":value.get("reason"),"failure_class":value.get("failure_class"),"source_gets":calls,"forecast_made":value.get("forecast_made",False)},ensure_ascii=False))
    return value

def run():
    now=datetime.now(timezone.utc)
    day=now.astimezone(JST).date()
    if day.isoformat()!="2026-11-03":
        return status(reason="ONE_SHOT_DATE_NOT_2026_11_03")
    if os.environ.get("BOAT_ONE_SHOT_OWNER_APPROVED")!="true":
        return status(reason="SOURCE_REVIEW_NOT_ADMITTED")
    try:
        url=endpoint(day,VENUE,1)
        raw,captured,h=fetch(url)
        parse_official_racelist(raw,day=day,venue=VENUE,race_no=1,source_url=url,captured_at=captured.isoformat())
        times=schedule(raw,day,VENUE)
    except (SourceError,ValueError,OSError,TimeoutError,UnicodeError) as error:
        return status(reason="SCHEDULE_OR_SOURCE_INVALID",failure_class=type(error).__name__)
    now=datetime.now(timezone.utc)
    options=[(t,n) for n,t in times.items() if RACE_WINDOW[0]<(t-now).total_seconds()<RACE_WINDOW[1]]
    if not options:return status(reason="NO_SUITABLE_UPCOMING_RACE")
    closing,n=min(options)
    race_id=f"{day:%Y%m%d}-{VENUE}-{n:02d}"
    if closing<=datetime.now(timezone.utc)+timedelta(seconds=180):
        return status(reason="CUTOFF_MARGIN_BEFORE_SOURCE")
    try:
        link=endpoint(day,VENUE,n)
        race_raw,rt,rh=fetch(link)
        details=parse_official_racelist(race_raw,day=day,venue=VENUE,race_no=n,source_url=link,captured_at=rt.isoformat())
        if datetime.fromisoformat(details["closed_at"])!=closing:raise ValueError("CUTOFF_CHANGED")
        if any(row["entry_status"]!="listed" for row in details["boats"]):raise ValueError("WITHDRAWN")
        preview_url=update_endpoint(day,VENUE,n,"beforeinfo")
        preview_raw,pt,ph=fetch(preview_url)
        observation=parse_update(preview_raw,kind="beforeinfo",day=day,venue=VENUE,race_no=n,
            source_url=preview_url,captured_at=pt.isoformat(),entries=details["boats"])
        if observation["status"]!="AVAILABLE" or observation["data"] is None:
            return status(race_id=race_id,cutoff_at=closing.isoformat(),reason="EXHIBITION_PENDING_OR_PARTIAL",
                source_url=preview_url,source_sha256=ph,source_captured_at=pt.isoformat())
        six=sorted(observation["data"]["boats"],key=lambda row:row["lane"])
        if len(six)!=6 or any(row["display_time"] is None for row in six):
            return status(race_id=race_id,cutoff_at=closing.isoformat(),reason="EXHIBITION_TIMES_INCOMPLETE")
        if pt>=closing-timedelta(seconds=180):return status(race_id=race_id,reason="TOO_LATE_AFTER_FETCH")
        program={x["lane"]:x for x in details["boats"]}
        avg=math.fsum(x["display_time"] for x in six)/6
        strengths={}
        for row in six:
            prev=program[row["lane"]]
            if prev["racer_registration_id"]!=row["racer_registration_id"]:
                raise ValueError("ROSTER_MISMATCH")
            rate=prev["national_win_rate"]
            if rate is None:rate=1.0
            strengths[row["lane"]]=math.exp(max(-20,min(20,math.log(max(rate,.01))+avg-row["display_time"])))
        total=math.fsum(strengths.values())
        candidates=[]
        for a,b,c in itertools.permutations(range(1,7),3):
            pa=strengths[a]/total*strengths[b]/(total-strengths[a])*strengths[c]/(total-strengths[a]-strengths[b])
            candidates.append((f"{a}-{b}-{c}",pa))
        if len(candidates)!=120 or abs(math.fsum(p for _,p in candidates)-1)>1e-9:
            raise ValueError("MODEL_PROBABILITY_INVALID")
        candidates.sort(key=lambda x:(-x[1],x[0]))
        generated=datetime.now(timezone.utc)
        if closing-generated<timedelta(seconds=180):raise ValueError("CUTOFF_MARGIN_AFTER_COMPUTE")
        return status(status="REAL_SOURCE_FORECAST_CREATED_ARTIFACT_NOT_YET_VERIFIED",
            race_id=race_id,cutoff_at=closing.isoformat(),source_url=preview_url,
            source_sha256=ph,source_captured_at=pt.isoformat(),
            program_source_sha256=rh,program_captured_at=rt.isoformat(),
            generated_at=generated.isoformat(),model_id="PR64-style-rating-display-PL-uncalibrated-readonly",
            ordered_top8=[{"ticket":t,"score":p} for t,p in candidates[:8]],
            scores_sum_top8=math.fsum(p for _,p in candidates[:8]),forecast_made=True,
            note="Actual remote GitHub artifact created_at must be checked against cutoff; read-only one-shot, not private store.")
    except (SourceError,ValueError,OSError,TimeoutError,UnicodeError,KeyError,TypeError) as error:
        return status(reason="ACTUAL_RACE_SOURCE_OR_PREDICTION_REJECTED",race_id=race_id,
            cutoff_at=closing.isoformat(),failure_class=type(error).__name__)

if __name__=="__main__":run()
