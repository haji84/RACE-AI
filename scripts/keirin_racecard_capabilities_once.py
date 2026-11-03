"""Two bounded one-time page-shape probes, no racer/payout data in logs.

Technical contract probe only. Does not produce a prediction or access a paid
API, persist raw pages, retry, or override publisher's access restrictions.
"""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from unicodedata import normalize
from hashlib import sha256
from collections import Counter
import json
import re

PAGES={
 "pre_race_7r":"https://keirin.kdreams.jp/odawara/racedetail/3620261101030007/",
 "result_1r":"https://keirin.kdreams.jp/odawara/raceresult/3620261101030001/",
 "result_1r_detail":"https://keirin.kdreams.jp/odawara/racedetail/3620261101030001/?pageType=showResult",
}
FIELDS=("出走表","競走得点","勝率","２連対率","2連対率","３連対率","3連対率",
        "ライン","車番","選手名","着順","3連単","締切","発走","払戻","配当",
        "本日","7車","9車")
MAX_BYTES=800_000
class BlockRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError("redirect_not_allowed")
class Strip(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.skip=0;self.text=[];self.tr=0;self.td=0;self.th=0
 def handle_starttag(self,tag,attrs):
  if tag in ("script","style","noscript"):self.skip+=1
  if tag=="tr":self.tr+=1
  if tag=="td":self.td+=1
  if tag=="th":self.th+=1
 def handle_endtag(self,tag):
  if tag in ("script","style","noscript"):self.skip=max(0,self.skip-1)
 def handle_data(self,data):
  if not self.skip:self.text.append(data)

def one(label,url):
 out={"page":label,"source_url":url,"status":None,"records_saved":0,
      "predictions_generated":0,"original_final_result_verified":False}
 u=urlsplit(url)
 if u.scheme!="https" or u.hostname!="keirin.kdreams.jp":
  out["error"]="INVALID_SOURCE_HOST";return out
 req=Request(url,method="GET",headers={"Accept":"text/html",
       "Accept-Language":"ja","User-Agent":"RACE-AI-one-shot-source-shape/1"})
 client=build_opener(BlockRedirect(),HTTPSHandler())
 try:
  with client.open(req,timeout=9) as r:
   out["status"]=r.status
   if r.status!=200 or r.geturl()!=url:
    out["error"]="NOT_EXACT_200";return out
   ct=r.headers.get("Content-Type","").lower()
   if "text/html" not in ct:
    out["error"]="NOT_HTML";return out
   b=r.read(MAX_BYTES+1)
 except HTTPError as e:out["status"]=e.code;out["error"]="HTTP";return out
 except (URLError,TimeoutError,ValueError,OSError) as e:out["error"]=type(e).__name__;return out
 if not 0<len(b)<=MAX_BYTES:
  out["error"]="BODY_SIZE";return out
 try:body=b.decode("utf-8")
 except UnicodeDecodeError:out["error"]="UTF8";return out
 parser=Strip();parser.feed(body)
 text=normalize("NFKC"," ".join(parser.text))
 out.update({
  "source_sha256":sha256(b).hexdigest(),"bytes":len(b),
  "visible_chars":len(text),"table_row_count":parser.tr,
  "table_cell_count":parser.td,"table_header_count":parser.th,
  "field_occurrence_counts":{f:text.count(f) for f in FIELDS},
  "visible_day_marker":any(f in text for f in ("2026/11/03","2026年11月3日","2026年11月03日")),
  "single_race_number_marker":bool(re.search(r"(?<!\d)0?7\s*R",text)) if label=="pre_race_7r"
  else bool(re.search(r"(?<!\d)0?1\s*R",text)),
 })
 return out

if __name__=="__main__":
 report={"schema":"RACE_AI_KEIRIN_PAGE_SHAPE_RESEARCH_V1",
         "requests_max":3,"rights_to_automate_not_inferred":True,
         "pages":[one(key,url) for key,url in PAGES.items()]}
 print(json.dumps(report,ensure_ascii=False,sort_keys=True))
