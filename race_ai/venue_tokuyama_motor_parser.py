"""Parse supplied Tokuyama motor-allocation table HTML, offline only.

The operator must separately confirm page provenance, meet dates, and lawful
use. Do not infer that a matching name proves the right meeting.
"""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs
import re
import unicodedata
from .core import SourceError


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="tr": self.row=[]
        elif tag in ("td","th") and self.row is not None: self.cell=[]
        elif tag=="br" and self.cell is not None: self.cell.append(" ")
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip()); self.cell=None
        elif tag=="tr" and self.row is not None:
            self.rows.append(self.row); self.row=None


def parse_motor_allocation(html: str, *, source_url: str) -> list[dict]:
    u=urlsplit(source_url)
    q=parse_qs(u.query)
    if (u.scheme!="https" or u.hostname not in
        ("www.boatrace-tokuyama.jp","boatrace-tokuyama.jp")
        or u.path!="/modules/raceinfo/" or q.get("page")!=["index_timerank"]):
        raise SourceError("unexpected Tokuyama motor allocation source")
    parser=Rows(); parser.feed(html)
    result=[]; ids=set(); names=set()
    for row in parser.rows:
        values=[unicodedata.normalize("NFKC",v).strip() for v in row]
        # Ranking, registration, grade, name, motor, motor top2, boat, boat top2, precheck.
        if len(values)<9 or not re.fullmatch(r"[0-9]{4}",values[1]):
            continue
        registration=values[1]
        name=re.sub(r"\s+","",values[3])
        motor=values[4]
        if not name or not re.fullmatch(r"[0-9]{1,3}",motor) or not 1<=int(motor)<=999:
            raise SourceError("invalid motor allocation row")
        if registration in ids or name in names:
            raise SourceError("duplicate racer allocation")
        ids.add(registration); names.add(name)
        result.append({"racer_registration_id":registration,"name":name,
                       "motor_no":int(motor),"source_url":source_url})
    if not result:
        raise SourceError("no motor allocation rows parsed")
    return result
