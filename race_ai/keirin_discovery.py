"""Discover an entire KEIRIN race day from one dated index HTML snapshot.

Identity discovery only; not model authorization, a betting cutoff, or a
confirmed source licence. Extract only linked race identity. Each 16-digit
link: JJ YYYYMMDD DD RRRR (venue, meeting-start, meeting-day, race number).
Strictly map the meeting-day segment to the requested JST date.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import hashlib
import re

MAX_PAGE_BYTES=700_000
JST=timezone(timedelta(hours=9))
KREAM_HOST="keirin.kdreams.jp"
CODE=re.compile(r"(?<!\d)(\d{2})(20\d{6})(0[1-9])(\d{4})(?!\d)")
VENUE_RACE_MIN=1
MAX_RACE=12

class DiscoveryError(ValueError): pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DiscoveryError("SOURCE_REDIRECT_NOT_ALLOWED")

class ExtractLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key,value in attrs:
                if key == "href" and type(value) is str and len(value)<2048:
                    self.links.append(value)


def index_url(day):
    if type(day) is not str:
        raise DiscoveryError("DATE_REQUIRED")
    try:
        dt=date.fromisoformat(day)
        if dt.isoformat()!=day:
            raise ValueError()
    except ValueError:
        raise DiscoveryError("DATE_REQUIRED") from None
    return f"https://keirin.kdreams.jp/kaisai/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"


def discover_from_html(body, *, event_day, source_url):
    if type(body) is not bytes or not (1 <= len(body) <= MAX_PAGE_BYTES):
        raise DiscoveryError("PAGE_SIZE_INVALID")
    if source_url != index_url(event_day):
        raise DiscoveryError("SOURCE_IDENTITY_MISMATCH")
    try:
        doc=body.decode("utf-8",errors="strict")
    except UnicodeDecodeError:
        raise DiscoveryError("CHARSET_UNVERIFIED") from None
    links=ExtractLinks()
    links.feed(doc)
    day=date.fromisoformat(event_day)
    found={}
    for href in links.links:
        u=urlsplit(urljoin(source_url,href))
        if u.scheme!="https" or u.hostname!=KREAM_HOST or u.username or u.password:
            continue
        if not any("/"+kind+"/" in u.path for kind in ("racedetail","raceresult","racecard")):
            continue
        m=CODE.search(u.path)
        if not m:
            continue
        venue, meeting, meeting_day, raw_race=m.groups()
        try:
            begin=date.fromisoformat(f"{meeting[:4]}-{meeting[4:6]}-{meeting[6:]}")
        except ValueError:
            continue
        # Only races from the requested day, never previous/next series days.
        if begin+timedelta(days=int(meeting_day)-1)!=day:
            continue
        venue=int(venue)
        race=int(raw_race)
        if not (VENUE_RACE_MIN<=venue<=99 and 1<=race<=MAX_RACE):
            continue
        race_id=f"{event_day.replace('-','')}{venue:02d}{race:02d}"
        if race_id not in found:
            found[race_id]={"race_id":race_id,
                            "event_date_jst":event_day,
                            "venue_code":venue,"race_no":race,
                            "meeting_start":begin.isoformat(),
                            "meeting_day":int(meeting_day)}
        else:
            if found[race_id]["meeting_start"]!=begin.isoformat():
                raise DiscoveryError("AMBIGUOUS_MEETING_ID")
    by_venue={}
    for row in found.values():
        by_venue.setdefault(row["venue_code"],set()).add(row["race_no"])
    for _,numbers in by_venue.items():
        if numbers != set(range(1,max(numbers)+1)):
            raise DiscoveryError("PARTIAL_OR_NONCONTIGUOUS_RACE_ROSTER")
    # A page without races is not proof of a non-race day.
    if not found:
        raise DiscoveryError("NO_VERIFIED_RACE_ROWS")
    return {
        "schema":"RACE_AI_KEIRIN_DATED_DISCOVERY_V1",
        "source_url":source_url, "source_sha256":hashlib.sha256(body).hexdigest(),
        "event_date_jst":event_day,
        "races":sorted(found.values(),key=lambda r:(r["venue_code"],r["race_no"])),
        "race_count":len(found),
        "venue_count":len(by_venue),
        "venue_race_counts":dict(sorted((str(k),len(v)) for k,v in by_venue.items())),
        "complete_national_coverage_verified":False,
        "official_cutoffs_verified":False,
        "model_features_available":False,
        "source_use_rights_verified":False,
    }


def get_single_day(event_day, *, opener=None):
    """Historical parser only; live Rakuten GET disabled by explicit owner choice.

    A supplied injected opener can be used for isolated offline fixtures.
    No regular caller can accidentally fetch the excluded origin.
    """
    if opener is None:
        raise DiscoveryError("RAKUTEN_LIVE_FETCH_DISABLED_BY_OWNER")
    url=index_url(event_day)
    request=Request(url,method="GET",headers={
        "Accept":"text/html",
        "Accept-Language":"ja",
        "User-Agent":"RACE-AI-personal-daily-roster/1",
    })
    try:
        with opener.open(request,timeout=9) as response:
            if response.status!=200 or response.geturl()!=url:
                raise DiscoveryError("SOURCE_IDENTITY_OR_STATUS_INVALID")
            media=response.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            if media not in ("text/html","application/xhtml+xml"):
                raise DiscoveryError("SOURCE_MIME_INVALID")
            raw=response.read(MAX_PAGE_BYTES+1)
    except HTTPError as exc:
        raise DiscoveryError(f"SOURCE_HTTP_{exc.code}") from None
    except (URLError, OSError, TimeoutError) as exc:
        raise DiscoveryError("SOURCE_UNAVAILABLE_"+type(exc).__name__) from None
    return discover_from_html(raw,event_day=event_day,source_url=url)
