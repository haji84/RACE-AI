"""Single-run first-party source availability research for other three sports.

This is NOT an unattended watcher or permission for ongoing access.
Exactly three known first-party URLs only, one bounded GET each, no redirects,
no retry, no stored third-party HTML, no downloaded images/video, no odds.
Do not confuse a printed help legend (試走T) with an actual trial observation,
JRA ordinary racecard with bodyweight announcement, or a keirin schedule
with a rider-introduction/confirmed line feed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from unicodedata import normalize
import hashlib
import json
import os
import re
import sys

SCHEMA="RACE_AI_NONBOAT_FIRSTPARTY_FORMAT_RESEARCH_V1"
BRANCH="refs/heads/p0-nonboat-3source-format-20261024"
TOKEN="ONE_OFFICIAL_THREE_SPORT_GET_20261024"
MAX_BODY=900_000
# Only URLs verified by first-party-oriented public discovery. Their presence
# does not prove permission to harvest or that a video is legally analyzable.
TARGETS=(
    ("autorace", "https://autorace.jp/race_info/Program/isesaki/2026-10-24"),
    ("horse", "https://app.jra.jp/JRADB/accessD.html?CNAME=sw01dde0108202604081220261024%2F4B"),
    ("keirin", "https://keirin.jp/pc/raceschedule"),
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("only exact first-party URLs allowed")

class VisibleText(HTMLParser):
    """Strip scripts/style and keep only visible-ish local text."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignore=0
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style","noscript","template"}:self.ignore+=1
    def handle_endtag(self,tag):
        if tag in {"script","style","noscript","template"} and self.ignore:
            self.ignore-=1
    def handle_data(self,data):
        if self.ignore==0:self.parts.append(data)
    def text(self):
        return normalize("NFKC"," ".join(self.parts))

def analyze_content(sport, raw):
    """No per-competitor figures leave this audit and no predictions created.

    Strong negative evidence is useful: a cancelled auto race is NOT trial
    published; a keirin schedule is NOT rider presentation published.
    """
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BODY:
        raise ValueError("bounded raw official HTML required")
    page=VisibleText()
    try:
        decoded=raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"status":"UNVERIFIED_CHARSET","presentation_available":False,
                "participant_identity_verified":False}
    page.feed(decoded)
    text=page.text()
    if sport=="autorace":
        date_seen=any(x in text for x in ("2026/10/24","2026-10-24","2026年10月24日"))
        # WARNING: AUTORACE.JP embeds a default cancelled-race panel as
        # template text in pages that ALSO show genuine trial times.
        # An unscoped phrase is never proof of a specific race cancellation.
        cancel_template=("該当レースの開催は中止となりました" in text
                         or "開催は中止となりました" in text)
        generic_legend="試走タイム" in text or "試走T" in text
        return {"status":"AUTO_GENERIC_PAGE_RACE_STATUS_UNVERIFIED",
                "event_day_marker_present":date_seen,
                "cancel_marker_present":cancel_template,
                "cancel_template_not_evidence_for_current_race":True,
                "race_scoped_cancel_verified":False,
                "generic_trial_help_present":generic_legend,
                "current_race_trial_numeric_verified":False,
                "presentation_available":False,
                "participant_identity_verified":False}
    if sport=="horse":
        date_seen=("2026年10月24日" in text or "2026/10/24" in text)
        venue_seen=("京都" in text)
        race_number_seen=bool(re.search(r"(?<!\d)12\s*R(?:ace)?\b|12レース",text,re.I))
        # A bodyweight marker is proof of text only, not row/horse-ID linkage.
        weight_word="馬体重" in text
        announced="発表済" in text
        return {"status":("JRA_RACECARD_ANNOUNCEMENT_MARKER_UNLINKED"
                          if announced and date_seen and venue_seen and race_number_seen
                          else "JRA_RACECARD_NO_ATTESTED_BODYWEIGHT_PUBLICATION"),
                "date_marker_present":date_seen,
                "venue_marker_present":venue_seen,
                "race_number_marker_present":race_number_seen,
                "weight_column_or_word_present":weight_word,
                "explicit_announced_word_present":announced,
                "bodyweight_rows_with_horse_ids_verified":False,
                "paddock_video_observed":False,
                "presentation_available":False,
                "participant_identity_verified":False}
    if sport=="keirin":
        return {"status":"KEIRIN_SCHEDULE_ONLY_NOT_RIDER_PRESENTATION",
                "schedule_label_present":"開催日程" in text,
                "rider_introduction_record_present":False,
                "actual_lines_verified":False,
                "presentation_available":False,
                "participant_identity_verified":False}
    raise ValueError("unsupported sport")

def audit(*,env=None,opener=None,clock=None,parse=analyze_content):
    env=os.environ if env is None else env
    if (env.get("GITHUB_EVENT_NAME")!="push" or env.get("GITHUB_REF")!=BRANCH
        or env.get("RACE_AI_NONBOAT_ONE_SHOT")!=TOKEN
        or not re.fullmatch(r"[0-9a-f]{40}",env.get("GITHUB_SHA",""))):
        raise RuntimeError("nonboat source audit must be separately one-shot admitted")
    client=opener or build_opener(NoRedirect(),HTTPSHandler())
    result={"schema":SCHEMA,"scope":"TECHNICAL_SOURCE_FORMAT_ONLY",
            "provider_GET_budget":3,"provider_GET_attempts":0,
            "persistent_monitoring_enabled":False,
            "source_permission_for_recurrent_access_verified":False,
            "source_license_for_model_features_verified":False,
            "official_publication_time_independently_verified":False,
            "raw_provider_html_persisted":False,"source_per_athlete_rows_republished":False,
            "video_or_photo_requested":False,"prediction_executed":False,
            "formal_hit_at_8_eligible":False,"sport_checks":[]}
    for sport,url in TARGETS:
        item={"sport":sport,"official_target":url,"http_status":None,
              "source_sha256":None,"source_bytes":None,
              "source_content_verified_for_model":False,
              "status":"NOT_OBSERVED"}
        try:
            result["provider_GET_attempts"]+=1
            request=Request(url,method="GET",headers={
                "Accept":"text/html",
                "User-Agent":"RACE-AI-one-shot-official-source-technical-check/1"})
            with client.open(request,timeout=8) as resp:
                item["http_status"]=getattr(resp,"status",None)
                if item["http_status"]!=200 or resp.geturl()!=url:
                    raise ValueError("incorrect final host/status")
                mime=resp.headers.get("Content-Type","").split(";",1)[0].strip().lower()
                if mime not in ("text/html","application/xhtml+xml"):
                    raise ValueError("unexpected content-type")
                data=resp.read(MAX_BODY+1)
            if not 0<len(data)<=MAX_BODY:
                raise ValueError("page oversized or empty")
            item["source_sha256"]=hashlib.sha256(data).hexdigest()
            item["source_bytes"]=len(data)
            item.update(parse(sport,data))
        except (HTTPError,URLError,TimeoutError,OSError,ValueError,UnicodeError,
                TypeError,KeyError) as exc:
            item["status"]="NO_ADMISSIBLE_FORMAT_RESULT"
            item["error_class"]=type(exc).__name__
            if isinstance(exc,HTTPError):item["http_status"]=exc.code
        # The only captured_at clock is the local GitHub runner; NOT original published_at.
        observed=clock() if clock else datetime.now(timezone.utc)
        if not isinstance(observed,datetime) or observed.utcoffset() is None:
            raise RuntimeError("aware runner clock required")
        item["captured_at_runner_unattested"]=observed.isoformat()
        result["sport_checks"].append(item)
    result["status"]="THREE_FIRSTPARTY_SOURCE_SURFACES_CHECKED_NOT_MODEL_ADMITTED"
    return result

def main():
    try:
        report=audit()
    except RuntimeError:
        print("NONBOAT_SOURCE_CHECK_REFUSED")
        return 2
    print(json.dumps(report,sort_keys=True,ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
