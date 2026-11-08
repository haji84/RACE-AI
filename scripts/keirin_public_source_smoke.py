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
