"""Source-only WINTICKET index structural diagnostics; no public rider/odds.

Discover *which public link templates* an actual public day page contains
and whether its SSR race->schedule links carry a verifiable public schedule
identifier. Never construct or try an undocumented API endpoint.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
import argparse
import json
import re

from race_ai.keirin_owner_public_page_fetch import network_page_once
from race_ai.keirin_winticket_embedded_odds import read_preloaded_json


class PublicLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            href=dict(attrs).get("href")
            if type(href) is str:
                self.hrefs.append(href)


def structure(html,source_url):
    text=html.decode("utf-8","strict")
    h=PublicLinks();h.feed(text)
    shapes=Counter()
    for href in h.hrefs:
        url=urlsplit(urljoin(source_url,href))
        if url.hostname not in ("www.winticket.jp","winticket.jp"):
            continue
        segments=[p for p in url.path.split("/") if p]
        if not segments or segments[0]!="keirin":
            continue
        # Only regular public paths. Do not publish any individual URLs.
        signature="/"+"/".join(
            "N" if s.isdigit() else s if
            s in ("keirin","odds","racecard","raceresult","schedule")
            else "X" for s in segments[:7])
        shapes[signature]+=1
    root=read_preloaded_json(html)
    datasets=Counter()
    first_collection_keys={}
    schedule_values_structure=Counter()
    schedules=Counter()
    matches=Counter()
    races=0
    for q in root.get("tanStackQuery",{}).get("queries",[]):
        if type(q) is not dict:continue
        state=q.get("state")
        if type(state) is not dict:continue
        data=state.get("data")
        if type(data) is not dict:continue
        for k,v in data.items():
            if type(v) is list and (k in ("races","schedules","venues",
                                         "stadiums","events","racecards")):
                datasets[k]+=len(v)
                if v and type(v[0]) is dict:
                    first_collection_keys[k]=sorted(v[0])
                if k=="schedules":
                    for item in v:
                        if type(item) is not dict:continue
                        for field,val in item.items():
                            if type(val) in (str,int):
                                raw=str(val)
                                if raw.isdigit() and 8<=len(raw)<=14:
                                    schedule_values_structure[
                                        field+":numeric"+str(len(raw))]+=1
        rows=data.get("races")
        if type(rows) is not list:continue
        for row in rows:
            if type(row) is not dict:continue
            races+=1
            sid=row.get("scheduleId")
            rid=row.get("id")
            fmt="str" if type(sid) is str else "int" if type(sid) is int else "other"
            val=str(sid)
            schedules[f"{fmt}:{len(val)}chars:digits={val.isdigit()}"]+=1
            if type(rid) is str and re.fullmatch(r"[0-9]{12}",rid):
                if val.endswith(rid[2:4]) or val.startswith(rid[2:4]):
                    matches["schedule_id_has_venue_prefix_or_suffix"]+=1
                if rid[4:] in val:
                    matches["schedule_id_contains_event_date"]+=1
    return {
        "schema":"RACE_AI_WINTICKET_PUBLIC_DAY_INDEX_STRUCTURE_ONLY_V1",
        "public_keirin_href_count":sum(shapes.values()),
        "path_template_counts":dict(shapes.most_common(18)),
        "ssr_named_collection_counts":dict(datasets),
        "ssr_first_collection_item_key_names":first_collection_keys,
        "ssr_schedule_numeric_field_formats":
            dict(schedule_values_structure),
        "ssr_race_count":races,
        "ssr_schedule_id_format_histogram":dict(schedules),
        "ssr_schedule_date_venue_format_matches":dict(matches),
        "url_values_or_rider_data_logged":False,
        "undocumented_endpoint_calls":0,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True)
    args=p.parse_args(argv)
    url="https://www.winticket.jp/keirin/odds/"+args.date.replace("-","")
    try:out=structure(network_page_once(url),url)
    except Exception:
        out={"schema":"RACE_AI_WINTICKET_PUBLIC_DAY_INDEX_STRUCTURE_ONLY_V1",
             "status":"STRUCTURE_NOT_AVAILABLE"}
    print(json.dumps(out,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
