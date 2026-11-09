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
    raw_races=[]
    raw_schedules=[]
    raw_venues=[]
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
                if k=="races":raw_races.extend(v)
                if k=="schedules":raw_schedules.extend(v)
                if k=="venues":raw_venues.extend(v)
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
    # Only count relationships among WINTICKET's published, individual
    # SSR schedule and venue identities. No private source values logged.
    from datetime import datetime,timedelta
    verified_schedules={}
    for record in raw_schedules:
        if type(record) is not dict:continue
        sid,cup,day,when=(record.get("id"),record.get("cupId"),
                          record.get("day"),record.get("date"))
        if not (type(sid) is str and type(cup) is str and
                type(day) is int and type(when) is str and
                len(sid)==len(cup)==10 and len(when)==8 and
                sid.isdigit() and cup.isdigit() and when.isdigit()
                and 1<=day<=3):continue
        try:
            first=datetime.strptime(cup[:8],"%Y%m%d").date()
            actual=datetime.strptime(when,"%Y%m%d").date()
        except ValueError:continue
        if first+timedelta(days=day-1)!=actual:continue
        if cup[-2:]!=sid[-2:] or sid[:8]!=when:continue
        verified_schedules[sid]=record
    venue_ids=set()
    for v in raw_venues:
        if type(v) is not dict:continue
        name=v.get("slug")
        no=v.get("id")
        if type(no) is int and 1<=no<=99 and type(name) is str and re.fullmatch(
            "[a-z][a-z0-9-]{2,30}",name):
            venue_ids.add(no)
    schedule_linked_race_count=0
    schedule_and_venue_linked_count=0
    for row in raw_races:
        if type(row) is not dict:continue
        sid=row.get("scheduleId")
        if type(sid) is not str or sid not in verified_schedules:continue
        schedule_linked_race_count+=1
        if type(row.get("id")) is str and len(row["id"])==12 and (
            int(sid[-2:]) in venue_ids):
            schedule_and_venue_linked_count+=1
    return {
        "schema":"RACE_AI_WINTICKET_PUBLIC_DAY_INDEX_STRUCTURE_ONLY_V1",
        "published_cup_date_day_schedule_validated_count":len(verified_schedules),
        "venue_id_and_slug_validated_count":len(venue_ids),
        "race_schedule_join_count":schedule_linked_race_count,
        "race_schedule_venue_join_count":schedule_and_venue_linked_count,
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
