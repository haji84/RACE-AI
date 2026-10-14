"""Extract meet dates from captured official Tokuyama HTML, fail closed.

This is an offline evidence parser, not a proof of provenance or permission.
The source URL and content must be captured by a separately authorized worker.
"""
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit
from .core import SourceError


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.hidden: self.hidden-=1
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)


def extract_meet(html: str, *, source_url: str, day: date) -> dict:
    u=urlsplit(source_url)
    if u.scheme!="https" or u.hostname not in ("www.boatrace-tokuyama.jp","boatrace-tokuyama.jp"):
        raise SourceError("unexpected official venue host")
    visible=Visible()
    visible.feed(html)
    text=unicodedata.normalize("NFKC"," ".join(visible.parts))
    # The official motor/entry pages show YYYY/MM/DD～YYYY/MM/DD.
    matches=re.findall(r"(20\d{2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\s*[（(][^）)]*[）)]\s*[～〜~-]\s*(20\d{2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})",text)
    intervals=set()
    for y,m,d,ey,em,ed in matches:
        start=date(int(y),int(m),int(d)); end=date(int(ey),int(em),int(ed))
        if start<=day<=end: intervals.add((start,end))
    if len(intervals)!=1:
        raise SourceError("missing or ambiguous official meet period")
    start,end=next(iter(intervals))
    return {"meet_id":f"18-{start:%Y%m%d}-{end:%Y%m%d}",
            "start_date":start.isoformat(),"end_date":end.isoformat(),
            "source_url":source_url,"identity_verified":False,
            "status":"HTML_EXTRACTED_REQUIRES_PROVENANCE_REVIEW"}
