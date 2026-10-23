"""Offline BOATRACE official 3T HTML -> complete 120-quote display feed.

No HTTP requests, no provider access permission, no current-race prediction.
The selector was researched against public source structure: the second
div.table1 contains 20 rows * six td.oddsPoint values. HTML bytes from a
live future race have NOT been independently accepted in this branch.

Reject partial or unexpected layouts. The odds publication timestamp cannot
be inferred from the HTTP receipt or fetch time.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit

from .permissioned_source_delivery import PermissionPolicy, SourceDeliveryError
from .comprehensive_four_sport_models import moment

SOURCE_HOSTS = {"www.boatrace.jp", "boatrace.jp"}
SCHEMA = "RACE_AI_FULL_TRIFECTA_ODDS_V1"
MAX_HTML = 2 * 1024 * 1024
MISSING = {"", "-", "--", "－", "—", "欠場", "発売なし", "取消"}
ODDS_RX = re.compile(r"\d+(?:\.\d+)?\Z")


def event_from_url(url):
    if not isinstance(url, str) or len(url)>600:
        raise SourceDeliveryError("invalid official odds URL")
    p=urlsplit(url)
    if (p.scheme!="https" or p.hostname not in SOURCE_HOSTS or
        p.username or p.password or p.port not in (None,443) or
        p.path!="/owpc/pc/race/odds3t" or p.fragment):
        raise SourceDeliveryError("official odds URL must be the 3T page")
    query=parse_qs(p.query,keep_blank_values=True)
    if set(query)!={"hd","jcd","rno"} or any(len(v)!=1 for v in query.values()):
        raise SourceDeliveryError("odds URL query keys invalid")
    raw_day,venue,number=query["hd"][0],query["jcd"][0],query["rno"][0]
    if not re.fullmatch(r"20\d{6}",raw_day) or not re.fullmatch(r"(0[1-9]|1\d|2[0-4])",venue):
        raise SourceDeliveryError("odds date or venue invalid")
    if not number.isdecimal() or not 1<=int(number)<=12:
        raise SourceDeliveryError("race number invalid")
    try:
        day=datetime.strptime(raw_day,"%Y%m%d").date()
    except ValueError as exc:
        raise SourceDeliveryError("invalid event date") from exc
    return day.isoformat(),venue,int(number)


class _OddsTable(HTMLParser):
    """Collect oddsPoint cells only from a uniquely complete table1 block."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.div_depth=0
        self.table_stack=[]
        self.tables=[]
        self.cell=None

    def handle_starttag(self,tag,attrs):
        cls=dict(attrs).get("class","").split()
        if tag=="div":
            self.div_depth+=1
            if "table1" in cls:
                self.table_stack.append([self.div_depth,[]])
        if tag=="td" and "oddsPoint" in cls and self.table_stack:
            if self.cell is not None:
                raise SourceDeliveryError("nested odds values in malformed page")
            self.cell=[]

    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self,tag):
        if tag=="td" and self.cell is not None:
            self.table_stack[-1][1].append("".join(self.cell).strip())
            self.cell=None
        if tag=="div":
            if self.table_stack and self.table_stack[-1][0]==self.div_depth:
                self.tables.append(self.table_stack.pop()[1])
            self.div_depth-=1
            if self.div_depth<0:
                raise SourceDeliveryError("invalid nested HTML")

    def close(self):
        super().close()
        if self.cell is not None or self.table_stack:
            raise SourceDeliveryError("unclosed source odds table")


def _tickets():
    columns=[[(a,b,c) for b in range(1,7) if b!=a
              for c in range(1,7) if c!=a and c!=b]
             for a in range(1,7)]
    triples=[columns[col][row] for row in range(20) for col in range(6)]
    if len(triples)!=120 or len(set(triples))!=120:
        raise SourceDeliveryError("trifecta mapping invalid")
    return triples


def _odd(raw):
    v=raw.replace(",","").strip()
    if v in MISSING:
        return {"status":"UNAVAILABLE","decimal_odds":None}
    if not ODDS_RX.fullmatch(v):
        raise SourceDeliveryError("unexpected quoted odd or unrecognized missing value")
    try:
        num=Decimal(v)
    except InvalidOperation as exc:
        raise SourceDeliveryError("not a valid decimal odds value") from exc
    if not Decimal("1")<=num<=Decimal("10000000"):
        raise SourceDeliveryError("odds not within supported range")
    return {"status":"QUOTED","decimal_odds":float(num)}


def normalize_html(raw, *, source_url, race_id, venue_name,
                   cutoff_at, ingested_at, source_published_at=None,
                   policy=None, rights_ref=None):
    """Explicitly pre-approved source bytes -> read-only all-trifecta quotes.

    A provided source_published_at must be independently verified from
    upstream odds update metadata, NOT fabricated from HTTP Date or local now.
    """
    day,venue,rno=event_from_url(source_url)
    if race_id!=f"{day.replace('-','')}-{venue}-{rno:02d}":
        raise SourceDeliveryError("race identity does not match odds source")
    if not isinstance(venue_name,str) or not venue_name or len(venue_name)>120:
        raise SourceDeliveryError("venue name required")
    if not isinstance(policy,PermissionPolicy) or not isinstance(rights_ref,str):
        raise SourceDeliveryError("independent reviewed source rights missing")
    for purpose in ("analysis","private_storage","private_derived","odds_display"):
        if not policy.authorize(source_url,rights_ref,purpose):
            raise SourceDeliveryError("SOURCE_PERMISSION_NOT_ADMITTED:"+purpose)
    try:
        cutoff=moment(cutoff_at)
        received=moment(ingested_at)
        upstream=moment(source_published_at) if source_published_at is not None else None
    except (ValueError,TypeError) as exc:
        raise SourceDeliveryError("timestamp invalid") from exc
    if cutoff.date()!=received.astimezone(cutoff.tzinfo).date() and received>cutoff:
        # Historical ingestion is allowed only on the same event day for this
        # narrowly scoped real-time adapter. Offline history uses another path.
        raise SourceDeliveryError("historical odds require separate data contract")
    if cutoff.astimezone(__import__("datetime").timezone(__import__("datetime").timedelta(hours=9))).date().isoformat()!=day:
        raise SourceDeliveryError("cutoff/JST event day mismatch")
    if upstream is not None and upstream>received:
        raise SourceDeliveryError("upstream odds timestamp after local receipt")
    if type(raw) is not bytes or not 100<=len(raw)<=MAX_HTML:
        raise SourceDeliveryError("bounded HTML original required")
    try:
        decoded=raw.decode("utf-8",errors="strict")
    except UnicodeError as exc:
        raise SourceDeliveryError("unknown official page encoding") from exc
    parser=_OddsTable()
    parser.feed(decoded)
    parser.close()
    if len(parser.tables)<2 or len(parser.tables[1])!=120:
        raise SourceDeliveryError("official 3T table incomplete or layout changed")
    # Reject a duplicated 120-quote table in additional table1 blocks.
    if any(len(table)==120 for table in parser.tables[2:]):
        raise SourceDeliveryError("duplicated quoted table")
    tickets=_tickets()
    rows=[{"ticket":list(ticket),**_odd(value)}
          for ticket,value in zip(tickets,parser.tables[1])]
    return {
        "schema":SCHEMA,"source_status":"PROVIDER_REPORTED_UNVERIFIED",
        "sport":"boat","race_id":race_id,"venue":venue_name,
        "race_no":rno,"event_date_jst":day,"cutoff_at":cutoff_at,
        "source_published_at":source_published_at,"ingested_at":ingested_at,
        "source_url":source_url,
        "sales_status":"CLOSED_REPORTED" if received>=cutoff else "UNKNOWN",
        "participants":[1,2,3,4,5,6],"odds":rows,
    }
