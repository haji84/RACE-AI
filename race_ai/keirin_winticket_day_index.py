"""Discover WINTICKET day roster from ordinary public HTML, not an API.

Never guesses venue slugs, meeting dates or cutoff times. Independent checks:
ordinary <a href> race links must agree with the page's SSR races[] ID set.
Partial index, disputed race IDs or missing cutoff are logged as incomplete,
never treated as a nationwide complete real-data feed.
"""
from __future__ import annotations

from datetime import datetime,date,timedelta,timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin,urlsplit

from .keirin_winticket_embedded_odds import read_preloaded_json

INDEX=re.compile(r"^/keirin/odds/([0-9]{8})/?$")
RACE=re.compile(
    r"^/keirin/([a-z][a-z0-9-]{2,30})/odds/"
    r"([0-9]{8})([0-9]{2})/([1-3])/([1-9][0-9]?)$"
)
SITE_ID=re.compile(r"^([0-9]{2})([0-9]{2})(20[0-9]{6})$")


class WinticketDayIndexError(ValueError):
    pass


def need(ok,reason):
    if not ok:raise WinticketDayIndexError(reason)


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            data=dict(attrs)
            href=data.get("href")
            if type(href) is str and len(href)<=2048:
                self.hrefs.append(href)


def _url_race(href,*,source,day):
    item=urlsplit(urljoin(source,href))
    if not (item.scheme=="https" and item.hostname in
            ("winticket.jp","www.winticket.jp") and
            item.username is None and item.password is None and
            item.port is None and not item.query and not item.fragment):
        return None
    match=RACE.fullmatch(item.path)
    if match is None:return None
    slug,begin,venue,meeting_day,no=match.groups()
    try:
        start=datetime.strptime(begin,"%Y%m%d").date()
        dated=start+timedelta(days=int(meeting_day)-1)
    except ValueError:
        return None
    if dated!=day:return None
    race_id=f"{dated:%Y%m%d}{venue}{int(no):02d}"
    return race_id,item.geturl()


def _provider_race(item,day):
    if type(item) is not dict:return None
    mid=item.get("id")
    if type(mid) is not str:return None
    match=SITE_ID.fullmatch(mid)
    if match is None:return None
    number,venue,yyyymmdd=match.groups()
    if yyyymmdd!=day.strftime("%Y%m%d"):return None
    no=int(number)
    if not (1<=no<=12 and 1<=int(venue)<=99):
        return None
    need(item.get("number")==no,
         "PUBLISHED_RACE_NUMBER_CONFLICTS_WITH_SOURCE_ID")
    rid=f"{yyyymmdd}{venue}{no:02d}"
    def decode_time(v):
        try:
            if type(v) is int and 1_500_000_000<v<2_400_000_000:
                return datetime.fromtimestamp(v,timezone.utc)
            if type(v) is str:
                t=datetime.fromisoformat(v.replace("Z","+00:00"))
                if t.utcoffset() is not None:return t.astimezone(timezone.utc)
        except (ValueError,TypeError,OverflowError):
            pass
        return None
    cutoff=decode_time(item.get("closeAt"))
    start=decode_time(item.get("startAt"))
    return {
        "race_id":rid,
        "venue_code":int(venue),
        "race_no":no,
        "public_close_at_utc":cutoff.isoformat() if cutoff else None,
        "public_start_at_utc":start.isoformat() if start else None,
        "published_entrant_count":item.get("entriesNumber") if type(
            item.get("entriesNumber")) is int else None,
    }


def extract_owner_winticket_day(html,*,source_url,event_day):
    need(type(html) is bytes and 0<len(html)<=8_000_000,
         "INDEX_HTML_BYTES_REQUIRED")
    try:day=date.fromisoformat(event_day)
    except (TypeError,ValueError):
        raise WinticketDayIndexError("JST_EVENT_DAY_INVALID") from None
    parts=urlsplit(source_url)
    need(parts.scheme=="https" and parts.hostname in
         ("winticket.jp","www.winticket.jp") and
         parts.username is None and parts.password is None and
         parts.port is None and not parts.query and not parts.fragment and
         INDEX.fullmatch(parts.path) and
         INDEX.fullmatch(parts.path).group(1)==day.strftime("%Y%m%d"),
         "EXACT_WINTICKET_DAY_INDEX_REQUIRED")
    links=Links()
    try:links.feed(html.decode("utf-8","strict"))
    except (UnicodeDecodeError,ValueError):
        raise WinticketDayIndexError("INDEX_HTML_NOT_VALID_UTF8") from None
    urls={}
    for href in links.hrefs:
        row=_url_race(href,source=source_url,day=day)
        if row is None:continue
        rid,url=row
        if rid in urls and urls[rid]!=url:
            raise WinticketDayIndexError("AMBIGUOUS_RACE_HREF")
        urls[rid]=url
    state=read_preloaded_json(html)
    cache=state.get("tanStackQuery")
    need(type(cache) is dict and type(cache.get("queries")) is list,
         "INDEX_SSR_QUERIES_REQUIRED")
    choices=[]
    for q in cache["queries"]:
        if type(q) is not dict or type(q.get("state")) is not dict:
            continue
        data=q["state"].get("data")
        if type(data) is not dict or type(data.get("races")) is not list:
            continue
        matched=[_provider_race(v,day) for v in data["races"]]
        matched=[m for m in matched if m]
        if matched:choices.append(matched)
    need(bool(choices),"INDEX_SSR_DATE_RACE_LIST_MISSING")
    # Distinct page caches may duplicate the same roster, but conflicting
    # versions of a venue/day must not be mixed to invent a schedule.
    presentations={}
    for rows in choices:
        keyed={x["race_id"]:x for x in rows}
        need(len(keyed)==len(rows),"DUPLICATE_RACE_ID_IN_SSR")
        code=json.dumps(sorted(rows,key=lambda z:z["race_id"]),
                        sort_keys=True,separators=(",",":"))
        presentations[sha256(code.encode()).hexdigest()]=keyed
    need(len(presentations)==1,"CONFLICTING_PUBLIC_DAY_ROSTERS")
    races=next(iter(presentations.values()))
    linked=sum(int(rid in urls) for rid in races)
    complete=(linked==len(races)
              and all(v["public_close_at_utc"] is not None and
                      v["public_start_at_utc"] is not None
                      for v in races.values()))
    result=[]
    for rid,v in sorted(races.items()):
        result.append({
            **v,
            "odds_public_url":urls.get(rid),
            "racecard_public_url":urls.get(rid).replace("/odds/","/racecard/",1)
                    if rid in urls else None,
        })
    return {
        "schema":"RACE_AI_KEIRIN_WINTICKET_DAY_DISCOVERY_SSR_V1",
        "event_day_jst":event_day,
        "index_html_sha256":sha256(html).hexdigest(),
        "published_ssr_race_count":len(races),
        "linked_races_verified":linked,
        "unlinked_race_count":len(races)-linked,
        "matching_public_ssr_and_href_coverage":complete,
        "complete_national_schedule_independently_verified":False,
        "official_cutoffs_independently_verified":False,
        "owner_machine_use_attested":True,
        "public_schedule_rows":result,
        "source_prediction_inputs_complete":False,
        "forecasts_created":0,
    }


def safe_day_index_summary(day):
    need(type(day) is dict and day.get("schema")==
         "RACE_AI_KEIRIN_WINTICKET_DAY_DISCOVERY_SSR_V1",
         "INVALID_OWNER_DAY_INDEX")
    return {k:day[k] for k in (
        "schema","event_day_jst","index_html_sha256",
        "published_ssr_race_count","linked_races_verified",
        "unlinked_race_count","matching_public_ssr_and_href_coverage",
        "complete_national_schedule_independently_verified",
        "official_cutoffs_independently_verified",
        "forecasts_created")}
