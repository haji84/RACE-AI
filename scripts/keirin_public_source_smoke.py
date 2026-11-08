"""One-shot public KEIRIN race-page availability check from GitHub Actions.

Read-only HTTPS GET of user-approved ordinary PUBLIC WINTICKET/KEIRIN.JP
pages. Emits status/byte-size/SHA plus structural counts only. NEVER outputs
source HTML, rider details, odds, cookies, keys or provider response bytes.
No endpoint discovery or undocumented API requests. Respect HTTP 403/429.
This is NOT a betting model or a 210-price verified result.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
import re
import sys
from urllib import error, request
from urllib.parse import urlsplit

RACE_ID="202611091203"
CUTOFF="2026-11-09T09:26:00+09:00"
TARGETS=(
    ("winticket_day_index",
     "https://www.winticket.jp/keirin/odds/20261109"),
    ("winticket_aomori_3r_odds",
     "https://www.winticket.jp/keirin/aomori/odds/2026110812/2/3"),
    ("winticket_aomori_3r_racecard",
     "https://www.winticket.jp/keirin/aomori/racecard/2026110812/2/3"),
    ("keirin_jp_public_schedule",
     "https://keirin.jp/sp/raceschedule"),
)
MAX_HTML=8_000_000

class HtmlIndicators(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=0
        self.rows=0
        self.script_tags=0
        self.json_script_tags=0
        self.inputs=0

    def handle_starttag(self,tag,attrs):
        attr=dict(attrs)
        if tag=="table":
            self.tables+=1
        elif tag=="tr":
            self.rows+=1
        elif tag=="input":
            self.inputs+=1
        elif tag=="script":
            self.script_tags+=1
            if "json" in (attr.get("type","").lower()):
                self.json_script_tags+=1

class SourceProbeError(ValueError):
    pass

def require(ok,code):
    if not ok:
        raise SourceProbeError(code)

def validate_public_url(url):
    require(url in {item[1] for item in TARGETS},
            "NOT_OWNER_APPROVED_PUBLIC_PAGE")
    parts=urlsplit(url)
    require(parts.scheme=="https" and parts.username is None and
            parts.password is None and parts.port is None and
            not parts.fragment and
            parts.hostname in ("www.winticket.jp","keirin.jp"),
            "UNSAFE_URL")
    return url

def get_public_html_once(url):
    """No redirection, cookies, token, retry or proxy workaround."""
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            return None
    opener=request.build_opener(NoRedirect)
    req=request.Request(url,headers={
        "Accept":"text/html,application/xhtml+xml",
        "User-Agent":"RACE-AI-Public-Page-Availability-Probe/1.0",
    },method="GET")
    with opener.open(req,timeout=8) as response:
        if response.status!=200:
            raise SourceProbeError("NON_200")
        media=response.headers.get("Content-Type","").lower()
        require("text/html" in media or "application/xhtml+xml" in media,
                "NON_HTML_RESPONSE")
        body=response.read(MAX_HTML+1)
        require(0<len(body)<=MAX_HTML,"BODY_EMPTY_OR_TOO_BIG")
        return body

def preloaded_schema_only(text):
    """Inspect JSON paths/counts only, never return original values."""
    found=re.search(r'window\.__PRELOADED_STATE__\s*=\s*',text)
    if not found:
        return {"status":"NO_PRELOADED_STATE"}
    raw=text[found.end():].lstrip()
    decoder=json.JSONDecoder(
        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(
            "NONFINITE_SOURCE_JSON")))
    try:
        if raw.startswith("{"):
            tree,unused=decoder.raw_decode(raw)
            assignment_kind="object"
        elif raw.startswith("JSON.parse("):
            encoded,unused=decoder.raw_decode(raw[len("JSON.parse("):])
            if not isinstance(encoded,str):
                return {"status":"JSON_PARSE_WRAPPER_NOT_STRING"}
            tree=json.loads(encoded)
            assignment_kind="json_parse"
        else:
            return {"status":"UNKNOWN_PRELOADED_ASSIGNMENT"}
    except (ValueError,TypeError,RecursionError):
        return {"status":"PRELOADED_PARSE_FAILED"}
    if not isinstance(tree,dict):
        return {"status":"PRELOADED_NOT_OBJECT"}
    # Limit traversal to prevent giant nested source from occupying all CI.
    top_keys=[k for k in tree if isinstance(k,str) and
              re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{1,42}',k)]
    stack=[("",tree,0)]
    interesting=[]
    exact_210=[]
    exact_504=[]
    inspected=0
    while stack and inspected<120000:
        path,node,depth=stack.pop()
        inspected+=1
        if depth>11:
            continue
        if isinstance(node,dict):
            for key,value in list(node.items())[:900]:
                name=(key if isinstance(key,str) and
                      re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{1,42}',key)
                      else "[map-key]")
                child_path=(path+"."+name) if path else name
                is_candidate=any(term in name.lower() for term in (
                    "odds","trifecta","bet","race","payout"))
                if is_candidate and len(interesting)<65:
                    interesting.append({
                        "path":child_path,
                        "value_type":type(value).__name__,
                        "container_length":(
                            len(value) if isinstance(value,(dict,list))
                            else None),
                    })
                if depth<11 and isinstance(value,(list,dict)):
                    stack.append((child_path,value,depth+1))
        elif isinstance(node,list):
            if len(node)==210 and len(exact_210)<14:
                exact_210.append(path)
            if len(node)==504 and len(exact_504)<14:
                exact_504.append(path)
            for item in node[:900]:
                if isinstance(item,(dict,list)) and depth<11:
                    stack.append((path+"[*]",item,depth+1))
    odds_shape=[]
    queries=tree.get("tanStackQuery",{})
    query_list=queries.get("queries",[]) if isinstance(queries,dict) else []
    if isinstance(query_list,list):
        for query in query_list[:160]:
            if not isinstance(query,dict):
                continue
            state=query.get("state")
            data=state.get("data") if isinstance(state,dict) else None
            if not isinstance(data,dict):
                continue
            rows=data.get("trifecta")
            if not isinstance(rows,list) or len(rows) not in (210,504):
                continue
            def describe_one(record,depth=0):
                if isinstance(record,dict):
                    return {
                        str(k)[:48]:(
                            describe_one(v,depth+1) if depth<2
                            else type(v).__name__
                        )
                        for k,v in list(record.items())[:25]
                    }
                if isinstance(record,list):
                    return {
                        "array_length":len(record),
                        "first_element_shape":(
                            describe_one(record[0],depth+1)
                            if record and depth<2 else None),
                    }
                return type(record).__name__
            counts={}
            if all(isinstance(v,dict) for v in rows):
                names=set().union(*(set(v.keys()) for v in rows))
                for name in sorted(names)[:36]:
                    vals=[v.get(name) for v in rows]
                    counts[str(name)[:48]]={
                        "null_rows":sum(v is None for v in vals),
                        "numeric_rows":sum(type(v) in (int,float) for v in vals),
                        "str_rows":sum(isinstance(v,str) for v in vals),
                        "array_rows":sum(isinstance(v,list) for v in vals),
                        "dict_rows":sum(isinstance(v,dict) for v in vals),
                    }
            qkey=query.get("queryKey")
            from itertools import permutations
            import math
            combos=[]
            for item in rows:
                combo=item.get("key") if isinstance(item,dict) else None
                if (type(combo) is list and len(combo)==3 and
                    all(type(n) is int and 1<=n<=9 for n in combo)
                    and len(set(combo))==3):
                    combos.append(tuple(combo))
            starters=set(n for triple in combos for n in triple)
            universe=set(permutations(starters,3))
            numeric_valid=sum(
                isinstance(item,dict) and
                type(item.get("odds")) in (float,int) and
                math.isfinite(item["odds"]) and
                1 < item["odds"] < 1_000_000 and
                item["odds"]!=9999.9
                for item in rows
            )
            odds_str_matched=0
            for item in rows:
                if not isinstance(item,dict):
                    continue
                val=item.get("oddsStr")
                try:
                    if isinstance(val,str) and abs(
                        float(val.replace(",",""))-item.get("odds",float("nan"))
                    )<1e-5:
                        odds_str_matched+=1
                except (TypeError,ValueError):
                    pass
            all_ids=sorted({
                item.get("raceId") for item in rows
                if isinstance(item,dict) and isinstance(item.get("raceId"),str)
            })
            odd_time=data.get("oddsUpdatedAt")
            odds_shape.append({
                "source_race_ids":all_ids[:3],
                "odds_updated_at":odd_time if isinstance(odd_time,(int,str)) else None,
                "odds_updated_at_type":type(odd_time).__name__,
                "odds_delayed":data.get("oddsDelayed") if type(data.get("oddsDelayed")) is bool else None,
                "final_odds":data.get("finalOdds") if type(data.get("finalOdds")) is bool else None,
                "is_aggregated":data.get("isAggregated") if type(data.get("isAggregated")) is bool else None,
                "unique_valid_combinations":len(set(combos)),
                "matches_entire_permutation_universe":(
                    len(starters) in (7,9) and
                    set(combos)==universe and
                    len(combos)==len(universe)
                ),
                "starter_count_from_keys":len(starters),
                "valid_priced_rows":numeric_valid,
                "display_string_numeric_matches":odds_str_matched,
                "absent_true_rows":sum(
                    item.get("absent") is True for item in rows
                    if isinstance(item,dict)),
                "count":len(rows),
                "first_row_shape":describe_one(rows[0]) if rows else None,
                "field_type_histograms":counts,
                "query_key_shape":describe_one(qkey),
                "source_data_keys":[str(k)[:50] for k in list(data)[:28]],
            })
            if len(odds_shape)>=3:
                break
    return {
        "status":"PRELOADED_JSON_PARSED",
        "assignment_kind":assignment_kind,
        "top_key_names":top_keys[:38],
        "nodes_inspected":inspected,
        "traversal_truncated":bool(stack),
        "odds_and_race_key_paths":interesting,
        "array_length_210_paths":exact_210,
        "array_length_504_paths":exact_504,
        "trifecta_row_shapes":odds_shape,
        "full_210_prices_verified":False,
    }


def summarize_html(body):
    require(type(body) is bytes and 0<len(body)<=MAX_HTML,
            "SOURCE_BYTES_INVALID")
    text=body.decode("utf-8",errors="replace")
    analyzer=HtmlIndicators()
    analyzer.feed(text)
    analyzer.close()
    # Structural-only diagnostics: no public-source or rider payload is logged.
    marker_tokens = {
        "next_data": "__NEXT_DATA__",
        "next_flight": "self.__next_f.push",
        "nuxt": "__NUXT__",
        "ld_json": "application/ld+json",
        "trifecta_jp": "3連単",
        "trifecta_en": "trifecta",
        "odds_field": "odds",
        "decimal_odds": "decimal_odds",
        "odds_table": "OddsTable",
        "winning_triple": "triple",
    }
    markers={key:min(text.count(token),99999)
             for key,token in marker_tokens.items()}
    script_meta=[]
    class MetadataScripts(HTMLParser):
        def handle_starttag(self,tag,attrs):
            if tag == "script":
                d=dict(attrs)
                value={
                    "id":str(d.get("id",""))[:60],
                    "type":str(d.get("type",""))[:60],
                    "has_src":bool(d.get("src")),
                }
                if value not in script_meta and len(script_meta)<12:
                    script_meta.append(value)
    meta=MetadataScripts()
    meta.feed(text)
    # Look at inline script SHAPES only. No source data or odds values
    # are emitted to the public GitHub CI log.
    from collections import Counter
    script_bodies=[]
    class ScriptBodyShapes(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current=None
            self.attrs={}
            self.buffer=[]
        def handle_starttag(self,tag,attrs):
            if tag=="script":
                self.current="script"
                self.attrs=dict(attrs)
                self.buffer=[]
        def handle_data(self,data):
            if self.current=="script":
                self.buffer.append(data)
        def handle_endtag(self,tag):
            if tag=="script" and self.current=="script":
                body="".join(self.buffer)
                if len(body)>100:
                    script_bodies.append((self.attrs,body))
                self.current=None
                self.buffer=[]
    scripts=ScriptBodyShapes()
    scripts.feed(text)
    shape_rows=[]
    for attributes,script_body in sorted(
        script_bodies,key=lambda x:-len(x[1]))[:5]:
        key_counter=Counter(re.findall(
            r'["\x27]([A-Za-z_][A-Za-z0-9_]{2,45})["\x27]\s*:',
            script_body[:2_000_000]))
        shape_rows.append({
            "script_bytes":len(script_body.encode("utf-8")),
            "script_type":attributes.get("type",""),
            "script_id":attributes.get("id",""),
            "contains_odds_marker":"odds" in script_body.lower(),
            "odds_marker_count":script_body.lower().count("odds"),
            "javascript_assignment_names":list(dict.fromkeys(
                re.findall(r'(?:window|globalThis)\.([A-Za-z_$][A-Za-z0-9_$]{2,50})\s*=',
                           script_body[:1_000_000])))[:12],
            "json_key_name_samples":[k for k,v in key_counter.most_common(25)],
        })
    # Structural hints are deliberately NOT counted as 210 price records.
    return {
        "response_bytes":len(body),
        "response_sha256":sha256(body).hexdigest(),
        "html_table_count":analyzer.tables,
        "html_row_count":analyzer.rows,
        "script_count":analyzer.script_tags,
        "json_script_count":analyzer.json_script_tags,
        "page_structure_markers":markers,
        "script_shape_samples":script_meta,
        "inline_script_structural_shapes":shape_rows,
        "preloaded_structure":preloaded_schema_only(text),
        "input_count":analyzer.inputs,
        "contains_trifecta_label":("3連単" in text),
        "contains_aomori_label":("青森" in text),
        "odds_210_all_values_validated":False,
        "official_347_statuses_validated":False,
    }

def probe(*,fetcher=None,clock=None):
    receive=get_public_html_once if fetcher is None else fetcher
    now=(datetime.now(timezone.utc) if clock is None else clock())
    require(isinstance(now,datetime) and now.utcoffset() is not None,
            "AWARE_TIMESTAMP_REQUIRED")
    grouped_blocked=set()
    rows=[]
    for name,url in TARGETS:
        validate_public_url(url)
        host=urlsplit(url).hostname
        row={"source":name,"status":"NOT_OBSERVED"}
        if host in grouped_blocked:
            row["status"]="HOST_BLOCKED_EARLIER_RESPECT_ACCESS_CONTROL"
            rows.append(row)
            continue
        try:
            body=receive(url)
            row.update(summarize_html(body))
            row["status"]="PUBLIC_HTML_RECEIVED"
        except error.HTTPError as exc:
            row["status"]="HTTP_ERROR"
            row["http_status"]=exc.code
            if exc.code in (401,403,429):
                grouped_blocked.add(host)
        except (OSError,error.URLError,SourceProbeError,UnicodeError) as exc:
            row["status"]=(
                exc.args[0] if isinstance(exc,SourceProbeError)
                else "PUBLIC_HTTP_NOT_AVAILABLE"
            )
        row["observed_at_utc"]=(
            datetime.now(timezone.utc) if clock is None else clock()
        ).astimezone(timezone.utc).isoformat()
        rows.append(row)
    return {
        "schema":"RACE_AI_KEIRIN_PUBLIC_PAGE_READONLY_PROBE_V1",
        "race_id":RACE_ID,
        "target_cutoff_jst":CUTOFF,
        "started_at_utc":now.astimezone(timezone.utc).isoformat(),
        "observed_before_cutoff":now < datetime.fromisoformat(CUTOFF),
        "results":rows,
        "successful_public_html_pages":sum(
            r["status"]=="PUBLIC_HTML_RECEIVED" for r in rows),
        "independently_admitted_trifecta_210_count":0,
        "full_347_factor_preflight_verified":False,
        "trusted_main_owner_sqlite_readback_done":False,
        "actual_two_version_forecast_saved":False,
        "private_plaintext_uploaded":False,
    }

def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if args!=["--one-shot"]:
        print('{"status":"PUBLIC_PROBE_REQUIRES_EXPLICIT_ONE_SHOT"}')
        return 2
    try:
        report=probe()
        print(json.dumps(report,sort_keys=True,
                         separators=(",",":")))
        return 0
    except (SourceProbeError,ValueError,OSError,TypeError):
        print('{"status":"PUBLIC_PROBE_FAILED_CLOSED","predictions_saved":0}')
        return 2

if __name__=="__main__":
    raise SystemExit(main())
