"""One FIRST-PARTY JRA Kyoto 12R racecard with explicit charset fallback.

JRA often serves Shift-JIS/CP932 HTML. Decode per source header or HTML
meta, never pretend an undecoded page is "not yet published". Detect page
identity and weight column/announced marker separately from current horse-
bound numeric body weights and actual paddock observations.

One manual GET, no retries, no video, no provider raw data stored/published,
no source permission asserted, no prediction and no post-cutoff freeze.
"""
from __future__ import annotations
from datetime import datetime, timezone
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import hashlib,json,os,re,sys,unicodedata
from scripts.p0_nonboat_official_format_probe_20261024 import VisibleText

SCHEMA="RACE_AI_JRA_ONE_RACECARD_CHARSET_AUDIT_V1"
URL="https://app.jra.jp/JRADB/accessD.html?CNAME=sw01dde0108202604081220261024%2F4B"
REF="refs/heads/p0-jra-charset-onerace-20261024"
TOKEN="JRA_KYOTO12_ONE_TEXT_ENCODING_CHECK"
MAX=800_000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise ValueError("redirect forbidden")

def decode_first_party(raw,header_charset):
    """Only supported Japanese encodings; return provenance of decoder choice."""
    match=re.search(rb"""(?i)charset\s*=\s*['"]?([a-z0-9_-]+)""",raw[:4000])
    meta=match.group(1).decode("ascii").lower() if match else None
    candidates=[("HTTP_CONTENT_TYPE",header_charset),("HTML_META",meta)]
    if not header_charset and not meta:
        candidates.extend([("STRICT_UTF8_FALLBACK","utf-8"),
                           ("STRICT_CP932_FALLBACK","cp932")])
    aliases={"shift_jis":"cp932","shift-jis":"cp932","sjis":"cp932",
             "windows-31j":"cp932","x-sjis":"cp932","utf-8":"utf-8",
             "utf8":"utf-8","cp932":"cp932","euc-jp":"euc_jp"}
    attempted=[]
    for reason,name in candidates:
        if not name:continue
        name=name.strip().lower()
        decoder=aliases.get(name)
        if decoder is None:
            attempted.append("UNSUPPORTED_DECLARED_CHARSET")
            continue
        try:
            text=raw.decode(decoder,errors="strict")
            return text,{"decoder":decoder,"decoder_source":reason,
                         "meta_declared":meta,
                         "content_type_charset":header_charset,
                         "charset_detection_status":"DECODED"}
        except UnicodeDecodeError:
            attempted.append(reason+":STRICT_DECODE_FAILED")
    return None,{"decoder":None,"decoder_source":None,"meta_declared":meta,
                 "content_type_charset":header_charset,
                 "charset_detection_status":"UNDECODED",
                 "failure_codes":attempted}

def inspect_jra_kyoto12(decoded):
    if decoded is None:
        return {"status":"NOT_DECODED","race_identity_from_body_verified":False,
                "horse_bound_current_weight_verified":False}
    parser=VisibleText()
    parser.feed(decoded)
    content=unicodedata.normalize("NFKC",parser.text())
    day="2026年10月24日" in content or "2026/10/24" in content
    venue="京都" in content
    race=bool(re.search(r"(?<!\d)12\s*R(?!\w)|12\s*レース",content,re.I))
    is_card="出馬表" in content
    announced="発表済" in content
    weight_word="馬体重" in content
    linked=day and venue and race and is_card
    return {"status":("RACECARD_IDENTITY_CONFIRMED_WEIGHT_RELEASE_UNVERIFIED"
                      if linked else "JRA_RACECARD_BODY_IDENTITY_INSUFFICIENT"),
            "day_in_body":day,"venue_in_body":venue,
            "race12_in_body":race,"racecard_marker_in_body":is_card,
            "bodyweight_field_present":weight_word,
            "official_announced_word_present":announced,
            "race_identity_from_body_verified":linked,
            "horse_bound_current_weight_verified":False,
            "first_publication_time_verified":False,
            "paddock_video_evidence_verified":False,
            "event_trigger_eligible_for_formal_model":False}

def audit(*,env=None,opener=None,clock=None):
    e=os.environ if env is None else env
    if (e.get("GITHUB_EVENT_NAME")!="push" or e.get("GITHUB_REF")!=REF or
        e.get("RACE_AI_JRA_CHARSET_ONE_SHOT")!=TOKEN or
        re.fullmatch(r"[0-9a-f]{40}",e.get("GITHUB_SHA","")) is None):
        raise RuntimeError("wrong one-shot JRA observation authority")
    out={"schema":SCHEMA,"source_url":URL,"race_scope":"JRA_20261024_KYOTO_12R",
         "one_GET_budget":1,"GET_attempts":0,
         "raw_html_stored":False,"horse_rows_republished":False,
         "provider_first_published_at_verified":False,
         "source_rights_verified":False,
         "unattended_monitoring_enabled":False,
         "official_prediction":False,
         "formal_hit_at_8_eligible":False}
    try:
        conn=opener or build_opener(NoRedirect(),HTTPSHandler())
        out["GET_attempts"]=1
        with conn.open(Request(URL,method="GET",headers={
             "Accept":"text/html",
             "User-Agent":"RACE-AI-one-time-official-JRA-charset-audit/1"}),timeout=8) as r:
            if r.status!=200 or r.geturl()!=URL:raise ValueError("unexpected provider URL/status")
            raw=r.read(MAX+1)
            mime=r.headers.get("Content-Type","")
        if not 0<len(raw)<=MAX:raise ValueError("invalid JRA HTML size")
        c=re.search(r"(?i)charset\s*=\s*([\w-]+)",mime)
        header=c.group(1).lower() if c else None
        text,decode_meta=decode_first_party(raw,header)
        out.update({"http_status":200,"source_bytes":len(raw),
            "source_sha256":hashlib.sha256(raw).hexdigest(),**decode_meta})
        out.update(inspect_jra_kyoto12(text))
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,UnicodeError) as exc:
        out["status"]="SOURCE_OR_FORMAT_UNVERIFIED"
        out["error_class"]=type(exc).__name__
        if isinstance(exc,HTTPError):out["http_status"]=exc.code
    captured=clock() if clock else datetime.now(timezone.utc)
    if captured.utcoffset() is None:raise RuntimeError("aware clock required")
    out["runner_captured_at_unattested"]=captured.isoformat()
    return out

def main():
    try:out=audit()
    except RuntimeError:
        print("ONE_SHOT_NOT_ALLOWED")
        return 2
    print(json.dumps(out,sort_keys=True,ensure_ascii=False))
    return 0 if out.get("status") not in ("NOT_DECODED","SOURCE_OR_FORMAT_UNVERIFIED") else 2

if __name__=="__main__":
    sys.exit(main())
