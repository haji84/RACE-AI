"""RAM-only PR64 Python / Worker JS same-source parity for program, exhibition, result.

Three individually bounded official GETs, no raw HTML files, no predictions,
no outcome retrofits, no wagers. A single observed parity is not a source license.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib, json, os, subprocess, sys, time, urllib.request
ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/"pr64-reference"
sys.path.insert(0,str(REFERENCE))
from race_ai.official_racelist_adapter import endpoint,parse_official_racelist,MAX_BYTES
from race_ai.official_race_updates import endpoint as update_endpoint,parse_update
from race_ai.tokuyama_day_worker import NoRedirects
DAY=date(2026,11,3)
JST=timezone(timedelta(hours=9))
VENUE="17";RACE=4
OUT=ROOT/"parity_output"/"triad.json"
NODE=r"""
import {parseRacelist,parseSchedule,parseExhibition,parseResultDetails} from './workers/boat_official_html.mjs';
let line='';for await(const c of process.stdin)line+=c;
const p=JSON.parse(line),result={};
const code=e=>String(e?.message||'UNKNOWN').match(/^[A-Z][A-Z0-9_]{3,100}/)?.[0]??'INVALID';
let r;
try{
 r=parseRacelist(p.program,p.day,p.venue,p.race);
 result.program={ok:true,cutoff_at:parseSchedule(p.program,p.day,p.venue)[p.race-1].cutoff_at,
  racers:r.map(x=>[x.lane,x.registration_no,x.national_win_rate])};
}catch(e){result.program={ok:false,code:code(e)};}
if(r){
 try{
  const b=parseExhibition(p.before,p.day,p.venue,p.race,r);
  result.exhibition={ok:true,six:b.map(x=>[x.lane,x.registration_no,x.exhibition_time_seconds])};
 }catch(e){result.exhibition={ok:false,code:code(e)};}
 try{
  const data=parseResultDetails(p.result,p.day,p.venue,p.race,r);
  result.result={ok:true,top3:data.top3,payout:data.payout_per_100_yen};
 }catch(e){result.result={ok:false,code:code(e)};}
}
console.log(JSON.stringify(result));
"""
def status(code,**extra):
 OUT.parent.mkdir(exist_ok=True)
 record={"schema":"RACE_AI_BOAT_REAL_HTML_TRIAD_PARITY_V1","race_id":"20261103-17-04",
         "status":code,"recorded_at":datetime.now(timezone.utc).isoformat(),
         "raw_html_persisted":False,"no_predictions_generated":True,
         "one_shot_not_continuous_license":True,**extra}
 OUT.write_text(json.dumps(record,sort_keys=True,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({"status":code,"race_id":record['race_id'],"parity":record.get('parity'),
                   "js":record.get('js'),"python":record.get('python')},ensure_ascii=False))
 return record
def run():
 if os.getenv("BOAT_HTML_TRIAD_REVIEWED")!="true":return status("OWNER_GATE_OFF",source_gets=0)
 if datetime.now(JST).date()!=DAY:return status("WRONG_DAY_NO_GET",source_gets=0)
 raw={};hashes={};records={}
 try:
  urls={"program":endpoint(DAY,VENUE,RACE),
        "before":update_endpoint(DAY,VENUE,RACE,"beforeinfo"),
        "result":update_endpoint(DAY,VENUE,RACE,"raceresult")}
  for kind,url in urls.items():
   req=urllib.request.Request(url,headers={"Accept":"text/html",
       "User-Agent":"RACE-AI-private-one-shot-html-validation/1.0"})
   with urllib.request.build_opener(NoRedirects()).open(req,timeout=12) as r:
    value=r.read(MAX_BYTES+1)
    if (r.status!=200 or r.geturl()!=url or not 0<len(value)<=MAX_BYTES
        or not (r.headers.get("Content-Type") or "").lower().startswith("text/html")):
     raise ValueError("SOURCE_RESPONSE_SHAPE")
   raw[kind]=value;hashes[kind]=hashlib.sha256(value).hexdigest()
   records[kind]=datetime.now(timezone.utc).isoformat()
   time.sleep(0.2)
  py={}
  try:
   program=parse_official_racelist(raw["program"],day=DAY,venue=VENUE,race_no=RACE,
      source_url=urls["program"],captured_at=records["program"])
   py["program"]={"ok":True,"cutoff":program["closed_at"],
      "six":[[x["lane"],x["racer_registration_id"],x["national_win_rate"]] for x in program["boats"]]}
   for kind,page in (("before","exhibition"),("result","result")):
    try:
     upd=parse_update(raw[kind],kind="beforeinfo" if kind=="before" else "raceresult",
        day=DAY,venue=VENUE,race_no=RACE,
        source_url=urls[kind],captured_at=records[kind],entries=program["boats"])
     data=upd.get("data")
     if kind=="before":
      six=[[x["lane"],x["racer_registration_id"],x["display_time"]] for x in data["boats"]] if data and isinstance(data.get("boats"),list) else None
      py[page]={"ok":upd.get("status")=="AVAILABLE" and bool(six),"six":six}
     else:
      combo=data.get("top3") if data else None
      payouts=[x for x in data.get("payouts",[]) if x.get("bet_type")=="trifecta" and x.get("combination")==combo] if data else []
      paid=payouts[0].get("payout_per_100_yen") if len(payouts)==1 else None
      py[page]={"ok":upd.get("status")=="AVAILABLE" and bool(data and data.get("finish_confirmed")),"top3":combo,"payout":paid}
    except Exception as exc:
     py[page]={"ok":False,"error_class":type(exc).__name__}
  except Exception as exc:
   py["program"]={"ok":False,"error_class":type(exc).__name__}
  try:
   node=subprocess.run(["node","--input-type=module","-e",NODE],cwd=ROOT,timeout=12,
    input=json.dumps({"program":raw["program"].decode("utf8"),
                      "before":raw["before"].decode("utf8"),
                      "result":raw["result"].decode("utf8"),
                      "day":"20261103","venue":VENUE,"race":RACE}),text=True,
    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
   js=json.loads(node.stdout) if node.returncode==0 else {"node":"ERROR"}
  except Exception:js={"node":"ERROR"}
  parity={
   "program":bool(py.get("program",{}).get("ok") and js.get("program",{}).get("ok")
       and py["program"]["six"]==js["program"].get("racers")
       and py["program"]["cutoff"]==js["program"].get("cutoff_at")),
   "exhibition":bool(py.get("exhibition",{}).get("ok") and js.get("exhibition",{}).get("ok")
       and py["exhibition"]["six"]==js["exhibition"].get("six")),
   "result":bool(py.get("result",{}).get("ok") and js.get("result",{}).get("ok")
       and py["result"]["top3"]==js["result"].get("top3")
       and (py["result"]["payout"] is None or py["result"]["payout"]==js["result"].get("payout")))}
  # Redact original identities and retain only verified equality flags.
  py_out={k:{"ok":v.get("ok"),"error_class":v.get("error_class"),"six_count":len(v.get("six") or []) if "six" in v else None} for k,v in py.items()}
  js_out={k:{"ok":v.get("ok"),"code":v.get("code"),"six_count":len(v.get("six") or []) if "six" in v else None} for k,v in js.items()}
  return status("ALL_THREE_MATCH" if all(parity.values()) else "PHASES_NOT_ALL_VERIFIED",
    source_gets=len(raw),source_sha256=hashes,captured_at=records,parity=parity,python=py_out,js=js_out)
 except Exception as exc:
  return status("SOURCE_OR_EXECUTION_FAILED",source_gets=len(raw)+1,failure_class=type(exc).__name__)
 finally:
  raw.clear()
if __name__=="__main__":run()
