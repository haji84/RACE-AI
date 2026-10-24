"""Strict offline parser for a verified individual race result table.

Requires the caller to supply the correct six-column mapping from a captured
HTML table. This deliberately does NOT assume an unverified official DOM layout.
No web requests, inferred actual courses, or rights claims.
"""
from __future__ import annotations
from html.parser import HTMLParser
from datetime import date
from urllib.parse import urlsplit,parse_qs
import re
import unicodedata
from .core import SourceError

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="table":self.table=[]
        elif tag=="tr" and self.table is not None:self.row=[]
        elif tag in ("td","th") and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip());self.cell=None
        elif tag=="tr" and self.row is not None and self.table is not None:
            self.table.append(self.row);self.row=None
        elif tag=="table" and self.table is not None:
            self.tables.append(self.table);self.table=None

def parse_individual_result(html: str, *, source_url: str, day: date,
                            race_no: int, column_map: dict, table_index: int) -> dict:
    u=urlsplit(source_url);q=parse_qs(u.query)
    if u.scheme!="https" or u.hostname not in ("www.boatrace.jp","www.boatrace-tokuyama.jp","boatrace-tokuyama.jp"):
        raise SourceError("unexpected official source")
    if not 1<=race_no<=12 or not isinstance(table_index,int) or table_index<0:
        raise SourceError("invalid race/table")
    # This accepts only explicitly declared race/date query identities.
    if q.get("hd")!=[day.strftime("%Y%m%d")] or q.get("rno")!=[str(race_no)] or q.get("jcd")!=["18"]:
        raise SourceError("source race identity not confirmed")
    parser=Tables();parser.feed(html)
    if table_index>=len(parser.tables):
        raise SourceError("verified result table not found")
    mapping={k:column_map.get(k) for k in ("finish","lane","registration","name","st")}
    if any(type(v) is not int or v<0 for v in mapping.values()) or len(set(mapping.values()))!=5:
        raise SourceError("column map missing or ambiguous")
    result=[];seen=set()
    for row in parser.tables[table_index]:
        if len(row)<=max(mapping.values()):continue
        cells=[unicodedata.normalize("NFKC",v).strip() for v in row]
        lane=cells[mapping["lane"]];reg=cells[mapping["registration"]]
        if not re.fullmatch("[1-6]",lane) or not re.fullmatch(r"\d{4}",reg):
            continue
        finish=cells[mapping["finish"]]
        if finish not in ("1","2","3","4","5","6","欠","転","落","沈","失","妨","不"):
            raise SourceError("unknown finish status")
        st=cells[mapping["st"]]
        if not re.fullmatch(r"(?:0?\.\d{2}|F\.?\d{0,2}|L\.?\d{0,2}|--)",st):
            raise SourceError("unknown ST format")
        key=int(lane)
        if key in seen:raise SourceError("duplicate lane")
        seen.add(key)
        result.append({"race_id":f"{day:%Y%m%d}-18-{race_no:02d}",
                       "lane":key,"racer_registration_id":reg,
                       "name":cells[mapping["name"]],
                       "finish":int(finish) if finish.isdecimal() else None,
                       "finish_status":finish if not finish.isdecimal() else "FINISHED",
                       "st":float(st) if re.fullmatch(r"0?\.\d{2}",st) else None,
                       "st_status":"OK" if re.fullmatch(r"0?\.\d{2}",st) else st,
                       "actual_course":None})
    if len(result)!=6 or seen!=set(range(1,7)):
        raise SourceError("six-lane result evidence incomplete")
    return {"race_id":f"{day:%Y%m%d}-18-{race_no:02d}",
            "source_url":source_url,"results":sorted(result,key=lambda r:r["lane"]),
            "actual_course_status":"UNKNOWN_REQUIRES_VERIFIED_START_ORDER",
            "status":"STRUCTURAL_PARSE_REQUIRES_REAL_HTML_VALIDATION"}
