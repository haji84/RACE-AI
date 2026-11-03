"""Single, bounded, public-source technical discovery check (not a collector).

Reads only two known home/index pages once each. Prints counts/booleans,
NOT raw site content, user data, tickets, odds, or player information.
No retries, redirects, copied HTML, unattended execution or paid login.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
import hashlib
import json
import re

SOURCES = (
    ("netkeirin_index","https://keirin.netkeiba.com/race/"),
    ("navi_index","https://www.keirin-mobile.jp/"),
)
LIMIT = 650_000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect refused")

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]
        self.text=[]
        self.ignore=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script","style","noscript"):
            self.ignore+=1
        if tag=="a":
            attrs=dict(attrs)
            if attrs.get("href"):
                self.links.append(attrs["href"])
    def handle_endtag(self, tag):
        if tag in ("script","style","noscript"):
            self.ignore=max(0,self.ignore-1)
    def handle_data(self, data):
        if not self.ignore:
            self.text.append(data)

def inspect(name,url):
    out={"source":name,"url":url,
         "http_status":None,"content_length":None,
         "contains_event_day_marker":False,
         "found_distinct_race_ids":0,
         "found_distinct_venue_links":0,
         "can_extract_future_race_identity":False,
         "no_raw_source_retained":True}
    client=build_opener(NoRedirect(),HTTPSHandler())
    request=Request(url,method="GET",headers={
        "User-Agent":"RACE-AI-private-research-one-time-format-probe/1",
        "Accept":"text/html",
        "Accept-Language":"ja",
    })
    try:
        with client.open(request,timeout=8) as r:
            out["http_status"]=r.status
            if r.geturl()!=url or r.status!=200:
                out["error"]="HTTP_IDENTITY_UNVERIFIED"
                return out
            media=r.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            if media not in ("text/html","application/xhtml+xml"):
                out["error"]="INVALID_MIME"
                return out
            body=r.read(LIMIT+1)
    except HTTPError as e:
        out["http_status"]=e.code
        out["error"]="HTTP_STATUS"
        return out
    except (TimeoutError,URLError,OSError,ValueError) as e:
        out["error"]=type(e).__name__
        return out
    if not 0<len(body)<=LIMIT:
        out["error"]="BODY_SIZE_LIMIT"
        return out
    out["content_length"]=len(body)
    out["sha256"]=hashlib.sha256(body).hexdigest()
    try:
        html=body.decode("utf-8")
    except UnicodeDecodeError:
        try:
            html=body.decode("cp932")
        except UnicodeDecodeError:
            out["error"]="CHARSET_UNSUPPORTED"
            return out
    parser=LinkParser()
    parser.feed(html)
    links=[urljoin(url, v) for v in parser.links]
    race_ids=set()
    venue_refs=set()
    for link in links:
        p=urlsplit(link)
        if p.hostname not in ("keirin.netkeiba.com","www.keirin-mobile.jp"):
            continue
        match=re.search(r"race_id=(\d{12})",p.query)
        if match:
            race_ids.add(match.group(1))
        if "/races/" in p.path or "jcode=" in p.query or "/race/" in p.path:
            venue_refs.add((p.hostname,p.path[:90]))
    out["found_distinct_race_ids"]=len(race_ids)
    out["found_distinct_venue_links"]=len(venue_refs)
    from datetime import datetime, timezone, timedelta
    jst=datetime.now(timezone(timedelta(hours=9)))
    visible=" ".join(parser.text)
    out["contains_event_day_marker"]=any(s in visible for s in (
        jst.strftime("%Y年%m月%d日"),jst.strftime("%Y-%m-%d"),
        f"{jst.month}月{jst.day}日"))
    out["can_extract_future_race_identity"]=bool(race_ids)
    # A list of race IDs is source content too: report only a count.
    return out

def main():
    values=[inspect(name,url) for name,url in SOURCES]
    print(json.dumps({"schema":"RACE_AI_KEIRIN_SOURCE_TECHNICAL_CHECK_V1",
                      "unattended_polling_enabled":False,
                      "provider_requests_max":len(SOURCES),
                      "official_results_authenticated":False,
                      "daily_coverage_verified":False,
                      "sources":values},ensure_ascii=False,sort_keys=True))
if __name__=="__main__":
    main()
