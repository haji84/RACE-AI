"""Offline parser for Tokuyama official result-list payout table.

The result-list provides 3T/2T combinations and payouts, not a verified
six-racer finishing table. Never infer each racer's finish or actual course
from this page. Caller supplies captured HTML; this module never fetches.
"""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs
from datetime import date
import re
import unicodedata
from .core import SourceError

class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="tr": self.row=[]
        elif tag in ("td","th") and self.row is not None: self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip());self.cell=None
        elif tag=="tr" and self.row is not None:
            self.rows.append(self.row);self.row=None

def parse_result_list(html: str, *, source_url: str, day: date) -> dict:
    u=urlsplit(source_url);q=parse_qs(u.query)
    if (u.scheme!="https" or u.hostname not in
        ("www.boatrace-tokuyama.jp","boatrace-tokuyama.jp")
        or u.path!="/modules/raceinfo/" or q.get("page")!=["index_resultlist"]
        or q.get("resultday")!=[day.strftime("%Y%m%d")]):
        raise SourceError("unexpected result page/date")
    p=Rows();p.feed(html)
    races={}
    for row in p.rows:
        cells=[unicodedata.normalize("NFKC",v).strip() for v in row]
        if not cells or not re.fullmatch(r"(?:[1-9]|1[0-2])R",cells[0]):continue
        n=int(cells[0][:-1])
        if n in races or len(cells)<5:
            raise SourceError("duplicate or incomplete result row")
        def combo(value,count):
            value=re.sub(r"\s+","",value)
            parts=re.split(r"[-－ー‐–]",value)
            if len(parts)!=count or not all(re.fullmatch("[1-6]",x) for x in parts) or len(set(parts))!=count:
                raise SourceError("invalid winning combination")
            return [int(x) for x in parts]
        def payout(value):
            s=re.sub(r"[\s,円]","",value)
            if not s.isdecimal() or int(s)<=0:
                raise SourceError("invalid payout")
            return int(s)
        tri=combo(cells[1],3);dual=combo(cells[3],2)
        if dual!=tri[:2]:
            raise SourceError("2T and 3T order disagree")
        races[n]={"race_id":f"{day:%Y%m%d}-18-{n:02d}",
                  "trifecta_lanes":tri,"trifecta_payout_yen":payout(cells[2]),
                  "exacta_lanes":dual,"exacta_payout_yen":payout(cells[4]),
                  "note":cells[5] if len(cells)>5 else "",
                  "result_detail_verified":False}
    if not races:
        raise SourceError("no completed result rows")
    return {"date_jst":day.isoformat(),"venue":"18","source_url":source_url,
            "races":[races[k] for k in sorted(races)],
            "status":"PAYOUT_LIST_ONLY_NOT_FULL_FINISH_OR_COURSE",
            "redistribution_authorized":False}
