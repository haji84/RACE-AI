"""Venue-first offline race-list adapter for BOATRACE Tokuyama.

Only parses supplied, lawfully obtained HTML. No network requests, automatic
scraping, storage, publication or claim of redistribution permission.
The venue's race index supplies lane/name, not verified registration IDs.
"""
from __future__ import annotations
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs
import re
import unicodedata

from .core import SourceError


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[]
        self.table=None
        self.row=None
        self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="table":
            self.table=[]
        elif tag=="tr" and self.table is not None:
            self.row=[]
        elif tag in ("th","td") and self.row is not None:
            self.cell=[]
        elif tag=="br" and self.cell is not None:
            self.cell.append(" ")
    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append("".join(self.cell).strip())
            self.cell=None
        elif tag=="tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row=None
        elif tag=="table" and self.table is not None:
            self.tables.append(self.table)
            self.table=None


def parse_tokuyama_race_index(html: str, *, day: date, source_url: str) -> dict:
    u=urlsplit(source_url)
    q=parse_qs(u.query)
    if (u.scheme!="https" or u.hostname not in
        ("www.boatrace-tokuyama.jp","boatrace-tokuyama.jp")
        or u.path!="/modules/raceinfo/"
        or q.get("page")!=["index_raceindex"]
        or q.get("targetday")!=[day.strftime("%Y%m%d")]):
        raise SourceError("unexpected venue page or day")
    parser=TableParser()
    parser.feed(html)
    found=[]
    for table in parser.tables:
        for row in table:
            cells=[unicodedata.normalize("NFKC",v).strip() for v in row]
            if not cells or not re.fullmatch(r"(?:[1-9]|1[0-2])R",cells[0]):
                continue
            if len(cells)!=7:
                raise SourceError("race row does not have six lanes")
            number=int(cells[0][:-1])
            if not all(cells[1:]):
                raise SourceError("missing racer name")
            found.append({"race_id":f"{day:%Y%m%d}-18-{number:02d}",
                          "boats":[{"lane":i,"name":name,"racer_registration_id":None,
                                    "motor_no":None} for i,name in enumerate(cells[1:],1)]})
    numbers=[int(x["race_id"][-2:]) for x in found]
    if not found or len(numbers)!=len(set(numbers)):
        raise SourceError("no races or duplicate race rows")
    return {"date_jst":day.isoformat(),"venue":"18",
            "source_url":source_url,"status":"OFFLINE_STRUCTURAL_ONLY",
            "races":sorted(found,key=lambda r:r["race_id"]),
            "missing_fields":["racer_registration_id","motor_no","closed_at"],
            "redistribution_authorized":False}
