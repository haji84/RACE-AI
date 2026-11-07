"""Capture only two owner-requested missing result pages, without scoring or prediction.

The existing result-only workflow retains result.json. Raw bodies stay in its
artifact, never in git or logs. This is a bounded source read, not a new model.
"""
from datetime import datetime,timezone
from pathlib import Path
import base64,hashlib,json,os,time,urllib.request

TARGETS=('20261104-10-10','20261104-19-10')
MAX_BYTES=2_000_000
ROOT=Path(__file__).resolve().parents[1]

class NoRedirects(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  return None

def result_url(race_id):
 if race_id not in TARGETS:raise ValueError('target is not owner-approved missing result')
 day,venue,race=race_id.split('-')
 return f'https://www.boatrace.jp/owpc/pc/race/raceresult?rno={int(race)}&jcd={venue}&hd={day}'

def encode_evidence(race_id,raw,captured_at):
 url=result_url(race_id)
 if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:raise ValueError('invalid source size')
 stamp=datetime.fromisoformat(captured_at.replace('Z','+00:00'))
 if stamp.tzinfo is None:raise ValueError('missing capture timezone')
 return dict(race_id=race_id,source_url=url,captured_at=captured_at,
             source_sha256=hashlib.sha256(raw).hexdigest(),byte_count=len(raw),
             body_base64=base64.b64encode(raw).decode('ascii'),parsed_result_verified=False)

def empty_report():
 return dict(schema='BOAT_TWO_MISSING_RESULT_RAW_V1',all_pages_captured=False,
             predictions_generated=False,originals_modified=False,source_get_limit=2,
             source_gets=0,pages=[],failures=[],actual_purchase=False)

def main():
 if os.environ.get('BOAT_RESULT_ONE_SHOT_OWNER_APPROVED')!='true':
  raise SystemExit('SOURCE_REVIEW_NOT_ADMITTED')
 now=datetime.now(timezone.utc)
 if not datetime(2026,11,4,14,tzinfo=timezone.utc)<=now<datetime(2026,11,6,tzinfo=timezone.utc):
  raise SystemExit('BOUNDED_HISTORICAL_CAPTURE_WINDOW_EXPIRED')
 report=empty_report()
 try:
  for race_id in TARGETS:
   url=result_url(race_id)
   report['source_gets']+=1
   request=urllib.request.Request(url,headers={'Accept':'text/html','User-Agent':'RACE-AI-owner-approved-result-reconciliation/1'})
   with urllib.request.build_opener(NoRedirects()).open(request,timeout=15) as response:
    raw=response.read(MAX_BYTES+1)
    if response.status!=200 or response.url!=url or not (response.headers.get('Content-Type') or '').lower().startswith('text/html'):
     raise ValueError('unexpected official response')
   report['pages'].append(encode_evidence(race_id,raw,datetime.now(timezone.utc).isoformat()))
   time.sleep(1)
  report['all_pages_captured']=len(report['pages'])==len(TARGETS)
 except (OSError,ValueError,TimeoutError) as error:
  # No retry or alternate endpoint after 4xx/429/source failure.
  report['failures'].append({'race_id':race_id,'error_class':type(error).__name__})
 output=ROOT/'result_output';output.mkdir(exist_ok=True)
 (output/'result.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True),encoding='utf-8')
 print(json.dumps({k:report[k] for k in ('all_pages_captured','source_gets','predictions_generated')}))
 if not report['all_pages_captured']:raise SystemExit(1)

if __name__=='__main__':main()
