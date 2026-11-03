"""One authorized, bounded, RAM-only real HTML parser parity diagnosis.

Only ONE official racelist GET, no raw HTML persisted, no predictions, no wagers.
This proves parsing of that one source version, not ongoing collection rights.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import hashlib, json, os, re, subprocess, sys, urllib.request

ROOT=Path(__file__).resolve().parents[1]
PR64=ROOT/"pr64-reference"
if not (PR64/"race_ai"/"official_racelist_adapter.py").is_file():
    raise SystemExit("PR64_FIXED_PARSER_NOT_INSTALLED")
sys.path.insert(0,str(PR64))
from race_ai.official_racelist_adapter import parse_official_racelist, endpoint, MAX_BYTES
from race_ai.tokuyama_day_worker import NoRedirects

JST=timezone(timedelta(hours=9))
DAY=date(2026,11,3)
VENUE="17"
RACE=4
TARGET=endpoint(DAY,VENUE,RACE)
OUT=ROOT/"parity_output"/"parity.json"

NODE=r"""
import {parseSchedule,parseRacelist} from './workers/boat_official_html.mjs';
let input='';
for await(const chunk of process.stdin) input+=chunk;
const {html,day,venue,race}=JSON.parse(input);
let out={js_status:'INVALID',js_code:'INVALID',boaters:[],cutoff_at:null};
try{
  const schedule=parseSchedule(html,day,venue);
  const six=parseRacelist(html,day,venue,race);
  out={js_status:'PARSED',js_code:'NONE',boaters:six,cutoff_at:schedule[race-1]?.cutoff_at??null};
}catch(e){
  // Do not print arbitrary captured text or racer names.
  const msg=String(e?.message??'');
  const safe=msg.match(/^[A-Z][A-Z0-9_]{2,65}/);
  out.js_code=safe?safe[0]:'UNCLASSIFIED_PARSER_FAILURE';
}
console.log(JSON.stringify(out));
"""

def write(status,**more):
    OUT.parent.mkdir(exist_ok=True)
    result=dict(schema="RACE_AI_BOAT_REAL_HTML_PARITY_V1",
                as_of=datetime.now(timezone.utc).isoformat(),
                race_id=f"20261103-{VENUE}-{RACE:02d}",
                source_gets=more.pop("source_gets",0),
                raw_official_html_saved=False,
                no_forecast_generated=True,
                no_result_scored=True,
                not_continuous_license_approval=True,
                status=status,**more)
    OUT.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2),encoding="utf-8")
    print(json.dumps({k:result.get(k) for k in
        ("status","race_id","source_gets","python_status","js_status","js_code","parity")},ensure_ascii=False))
    return result

def run():
    if os.environ.get("BOAT_HTML_PARITY_ONE_SHOT_REVIEWED")!="true":
        return write("OWNER_GATE_DISABLED")
    if datetime.now(JST).date()!=DAY:
        return write("DATE_WINDOW_PASSED_NO_GET")
    body=None
    try:
        req=urllib.request.Request(TARGET,headers={"Accept":"text/html",
            "User-Agent":"RACE-AI-owner-one-shot-parser-audit/1"})
        with urllib.request.build_opener(NoRedirects()).open(req,timeout=12) as response:
            body=response.read(MAX_BYTES+1)
            if (response.status!=200 or response.geturl()!=TARGET or
                not 0<len(body)<=MAX_BYTES or not
                (response.headers.get('Content-Type') or '').lower().startswith('text/html')):
                raise ValueError('OFFICIAL_HTTP_SHAPE_REJECTED')
        captured=datetime.now(timezone.utc).isoformat()
        digest=hashlib.sha256(body).hexdigest()
        try:
            official=parse_official_racelist(body,day=DAY,venue=VENUE,race_no=RACE,
                       source_url=TARGET,captured_at=captured)
            py_error=None
        except Exception as exc:
            official=None;py_error=type(exc).__name__
        try:
            node=subprocess.run(["node","--input-type=module","-e",NODE],cwd=ROOT,
                input=json.dumps(dict(html=body.decode("utf-8"),day="20261103",
                                     venue=VENUE,race=RACE)),text=True,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=12,check=False)
            js=json.loads(node.stdout) if node.returncode==0 else {"js_status":"NODE_EXEC_FAILED"}
        except (OSError,UnicodeError,ValueError,subprocess.TimeoutExpired):
            js={"js_status":"NODE_EXEC_FAILED"}
        diff=None
        if official and js.get("js_status")=="PARSED":
            ref=[(x["lane"],x["racer_registration_id"],x["national_win_rate"]) for x in official["boats"]]
            checked=[(x["lane"],x["registration_no"],x["national_win_rate"]) for x in js["boaters"]]
            diff={"lane_reg_rate_equal":ref==checked,
                "python_six":len(ref)==6,"js_six":len(checked)==6,
                "cutoff_equal":official["closed_at"]==js["cutoff_at"],
                "lane_only":sorted(x[0] for x in checked),
                "all_6_reg_match":sum(x[:2]==y[:2] for x,y in zip(ref,checked))}
        passing=diff is not None and diff["lane_reg_rate_equal"] and diff["cutoff_equal"]
        return write("REAL_HTML_PARITY_PASS" if passing else "REAL_HTML_PARITY_UNRESOLVED",
            source_gets=1,source_sha256=digest,source_captured_at=captured,
            python_status="PARSED" if official else "PARSER_REJECTED",
            python_error_class=py_error,js_status=js.get("js_status"),
            js_code=js.get("js_code"),parity=diff)
    except (OSError,ValueError,UnicodeError,TimeoutError) as exc:
        return write("SOURCE_UNAVAILABLE",source_gets=1,failure_class=type(exc).__name__)
    finally:
        body=None
if __name__=="__main__":run()
