"""Discover real day-wide race detail links from publicly linked Kdreams pages.

Only follow visible ordinary <a href> links in the actual daily and
meeting racecard HTML. NEVER invent meeting start dates, meeting-day
indexes or unlinked detail pages. netkeirin entry URL is a *candidate*
public query shape; its authenticity is established only by subsequent
bounded GET and full page/roster admission in two_source_normalizer.

Unknown venues / races remain HOLD in the frozen national roster.
No provider anticrawl evasion, hidden endpoint, result access or wagering.
"""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
from unicodedata import normalize
from urllib.parse import urljoin,urlsplit
import re
import json
import argparse
import os

from . import keirin_capture_public_two_sources as capture
from .keirin_nationwide_auto_forecast import registered_race_ids

SCHEMA=capture.SCHEMA
RECEIPT="RACE_AI_KEIRIN_KDREAMS_LINK_DISCOVERY_V1"
CALENDAR="https://keirin.kdreams.jp/kaisai/{year:04d}/{month:02d}/{day:02d}/"
CARD=re.compile(
    r"^/[a-z0-9-]+/racecard/([0-9]{2})(20[0-9]{6})([0-9]{2})00/$")
DETAIL=re.compile(
    r"^/[a-z0-9-]+/racedetail/([0-9]{2})(20[0-9]{6})([0-9]{2})00([0-9]{2})/$")


class DayLinksError(ValueError):
    pass


def need(ok,reason):
    if not ok:
        raise DayLinksError(reason)


def _day_id(begin,index):
    try:
        if not 1<=int(index)<=7:
            return None
        return (datetime.strptime(begin,"%Y%m%d").date()+
                timedelta(days=int(index)-1)).strftime("%Y%m%d")
    except (ValueError,OverflowError):
        return None


def linked_racecards(html,*,base_url,day):
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(html,"html.parser")
    cards={}
    for a in soup.find_all("a",href=True):
        href=urljoin(base_url,a["href"])
        url=urlsplit(href)
        if url.scheme!="https" or url.hostname!="keirin.kdreams.jp":
            continue
        item=CARD.fullmatch(url.path)
        if not item:
            continue
        code,begin,index=item.groups()
        if _day_id(begin,index)!=day.replace("-",""):
            continue
        # Racecard URLs are taken from a REAL calendar href, never guessed.
        # Same visible meeting link can carry different UI tracking query
        # parameters. Compare actual documented path, not click-tracker.
        canonical=f"https://keirin.kdreams.jp{url.path}"
        if code in cards and cards[code]!=canonical:
            raise DayLinksError("CONFLICTING_MEETING_CODES_FOR_SAME_VENUE")
        cards[code]=canonical
    return cards


def linked_details(html,*,base_url,day,venue):
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(html,"html.parser")
    urls={}
    for a in soup.find_all("a",href=True):
        href=urljoin(base_url,a["href"])
        u=urlsplit(href)
        if u.scheme!="https" or u.hostname!="keirin.kdreams.jp":
            continue
        item=DETAIL.fullmatch(u.path)
        if not item:
            continue
        code,begin,index,number=item.groups()
        if code!=venue or _day_id(begin,index)!=day.replace("-",""):
            continue
        rid=day.replace("-","")+code+number
        canonical=f"https://keirin.kdreams.jp{u.path}"
        if rid in urls and urls[rid]!=canonical:
            raise DayLinksError("CONFLICTING_DETAIL_LINKS")
        urls[rid]=canonical
    return urls


def linked_cutoff_hints(html,*,base_url,day,venue):
    """Only the closing clock printed in the same real linked-race row.

    A hint orders acquisition; it never certifies the organizer's cutoff.
    Missing or unsupported clock markup stays unknown, never the start time.
    """
    from bs4 import BeautifulSoup
    details=linked_details(html,base_url=base_url,day=day,venue=venue)
    by_url={url:rid for rid,url in details.items()}
    soup=BeautifulSoup(html,"html.parser")
    hints={}
    for li in soup.select("ul.racecard_list > li"):
        anchors=li.select("p.race > a[href]")
        if len(anchors)!=1:
            continue
        url=urlsplit(urljoin(base_url,anchors[0]["href"]))
        if url.scheme!="https" or url.hostname!="keirin.kdreams.jp":
            continue
        rid=by_url.get("https://keirin.kdreams.jp"+url.path)
        if rid is None:
            continue
        values=[]
        for dt in li.select("div.header dl > dt"):
            label=normalize("NFKC",dt.get_text("",strip=True))
            if label not in ("締切","投票締切"):
                continue
            dd=dt.find_next_sibling()
            if dd is not None and dd.name=="dd":
                values.append(normalize("NFKC",dd.get_text("",strip=True)))
        if len(values)!=1 or not re.fullmatch(r"(?:[01]?[0-9]|2[0-3]):[0-5][0-9]",values[0]):
            continue
        hour,minute=map(int,values[0].split(":"))
        hint=f"{day}T{hour:02d}:{minute:02d}:00+09:00"
        need(rid not in hints or hints[rid]==hint,
             "CONFLICTING_PUBLISHED_CUTOFF_HINTS")
        hints[rid]=hint
    return hints


def discover(*,day_jst,registered_ids,fetch=None,clock=None,max_meetings=12):
    need(type(day_jst) is str and re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",day_jst),
         "DYNAMIC_DAY_NOT_VALID")
    day=datetime.strptime(day_jst,"%Y-%m-%d").date()
    need(type(registered_ids) is list and len(registered_ids)>0 and
         len(set(registered_ids))==len(registered_ids),
         "FROZEN_RACE_COHORT_REQUIRED")
    fetch=fetch or capture.fetch_once
    clock=clock or (lambda:datetime.now(timezone.utc))
    need(callable(fetch) and callable(clock) and
         type(max_meetings) is int and 1<=max_meetings<=20,
         "BOUNDED_DAY_SOURCE_DISCOVERY_REQUIRED")
    calendar=CALENDAR.format(year=day.year,month=day.month,day=day.day)
    data=fetch(calendar)
    observed=clock().astimezone(timezone.utc).isoformat()
    # A source list is NOT proof of all nationwide venues. Missing venues are
    # documented and not inferred from the pages that happened to respond.
    cards=linked_racecards(data,base_url=calendar,day=day_jst)
    required=set(rid[8:10] for rid in registered_ids)
    details={}
    cutoffs={}
    scanned=0
    errors=0
    for venue,url in sorted(cards.items()):
        if venue not in required:
            continue
        if scanned>=max_meetings:
            break
        scanned+=1
        try:
            html=fetch(url)
            links=linked_details(html,base_url=url,day=day_jst,venue=venue)
            details.update(links)
            cutoffs.update(linked_cutoff_hints(
                html,base_url=url,day=day_jst,venue=venue))
        except capture.SourceCaptureError as exc:
            errors+=1
            if str(exc) in ("PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                            "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
                            "PUBLIC_PROVIDER_UNAVAILABLE_STOP"):
                break
    known=set(registered_ids)
    rows=[]
    for rid in sorted(details):
        if rid not in known:
            continue
        # Only a GET candidate; no claim the netkeirin URL has been read.
        net=f"https://keirin.netkeiba.com/race/entry/?race_id={rid}"
        capture._allow_url(net,"net",rid)
        capture._allow_url(details[rid],"kd",rid)
        rows.append({
            "race_id":rid,
            "netkeirin_url":net,
            "kdreams_url":details[rid],
            # Only a visible per-race label supplies an ordering hint.
            "cutoff_hint":cutoffs.get(rid),
        })
    manifest={
        "schema":SCHEMA,"day_jst":day_jst,
        "races":rows,"source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY"}
    capture.manifest_check(manifest,registered_ids=registered_ids)
    return {
        "schema":RECEIPT,"day_jst":day_jst,
        "calendar_html_sha256":sha256(data).hexdigest(),
        "observed_at":observed,
        "registered_race_count":len(registered_ids),
        "candidate_race_count":len(rows),
        "unlinked_registered_race_count":len(known-{r["race_id"] for r in rows}),
        "meetings_linked_in_calendar":len(cards),
        "meeting_racecard_pages_attempted":scanned,
        "source_errors":errors,
        "all_races_linked":len(rows)==len(known),
        "unlinked_races_are_HOLD":True,
        "source_pages_observed_from_live_HREFs_only":True,
        "netkeirin_GET_candidates_not_yet_verified":True,
        "manifest":manifest,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--day",required=True)
    p.add_argument("--registry",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--safe-report",required=True)
    a=p.parse_args(argv)
    try:
        r=json.loads(Path(a.registry).read_text(encoding="utf-8"))
        result=discover(
            day_jst=a.day,registered_ids=registered_race_ids(r))
        dest=Path(a.manifest);summary=Path(a.safe_report)
        for x in (dest,summary):
            if not x.is_absolute() or x.exists() or x.is_symlink():
                raise DayLinksError("DISCOVERY_CREATE_ONCE_DESTINATION_REQUIRED")
        data=json.dumps(result["manifest"],sort_keys=True,
                        ensure_ascii=False,separators=(",",":")).encode()+b"\n"
        capture._write_once(dest,data)
        safe={k:v for k,v in result.items() if k!="manifest"}
        capture._write_once(summary,json.dumps(safe,sort_keys=True).encode()+b"\n")
        print(json.dumps({k:safe[k] for k in (
            "registered_race_count","candidate_race_count",
            "unlinked_registered_race_count","meeting_racecard_pages_attempted")},
            sort_keys=True))
        return 0
    except (DayLinksError,capture.SourceCaptureError,
            ValueError,TypeError,KeyError,OSError):
        print('{"state":"HOLD_NO_VERIFIED_NATIONAL_DAY_LINKS"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
