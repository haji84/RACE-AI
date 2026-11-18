"""Normalize two actual public racecard formats into A/B automatic forecasts.

Inputs are owner-captured, SHA-matched, date/race-bound *ordinary public
HTML or published table text*. No hidden endpoints, no remote GET, no
conversion of provider-internal player IDs into official athlete IDs.

- netkeirin entry table supplies actual printed paper marks, score, H, B,
  last-four-month first-place percentage and rider style.
- Kdreams visible race-detail supplies published cutoff and explicitly
  printed lineup / predicted formation.
- Both source byte receipts and capture times are retained. If either
  format is ambiguous or conflicts with the target race, HOLD.

This is a SOURCE ADAPTER, not an official cutoff attestation, a prediction
probability calibration or a grant of rights to scrape either provider.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from unicodedata import normalize
from urllib.parse import urlsplit, parse_qs
import re
import json

from . import keirin_nationwide_auto_generator as auto

JST=timezone(timedelta(hours=9))
SCHEMA="RACE_AI_KEIRIN_PRE_RACE_TWO_PUBLIC_PAGES_ADAPTER_V1"
MARK_TABLE = re.compile(r"^\s*[1-9]\s*\|")
TABLE_SEP=re.compile(r"^[-:| \t]+$")
CLOCK=re.compile(r"(?<![0-9])([01]?[0-9]|2[0-3]):([0-5][0-9])(?![0-9])")
TOKENS=re.compile(r"([1-9])\s*(先行|押え先|追込|追上|自在|単騎|追走|番手)")
FORM=re.compile(r"並び予想は\s*([0-9\s\-／/]+)")
GAP=re.compile(r"\s+")


class PublicPageNormalizeError(ValueError):
    pass


def need(ok,reason):
    if not ok:
        raise PublicPageNormalizeError(reason)


def _time(x):
    try:
        return auto.when(x)
    except (auto.AutomaticForecastError,ValueError,TypeError):
        raise PublicPageNormalizeError("CAPTURE_TIME_INVALID") from None


def _text(raw):
    need(type(raw) is bytes and 1<=len(raw)<=9_000_000,
         "OWNER_PAGE_BYTES_MISSING_OR_LARGE")
    try:
        value=raw.decode("utf-8")
    except UnicodeDecodeError:
        raise PublicPageNormalizeError("OWNER_PAGE_NOT_UTF8") from None
    if "<html" in value.lower() or "<table" in value.lower():
        # HTML layout; extract visible td/th cells, not script/style text.
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(value,"html.parser")
        for node in soup(["script","style","noscript"]):
            node.decompose()
        rows=[]
        for tr in soup.find_all("tr"):
            # Direct descendants only, not nested unrelated tables.
            cells=tr.find_all(["td","th"],recursive=False)
            if cells:
                rows.append(" | ".join(x.get_text(" ",strip=True) for x in cells))
        body=soup.get_text(" ",strip=True)
        return value,body,rows
    return value,value,[x.strip().strip("|") for x in value.splitlines()
                        if "|" in x]


def _url_role(url,who,rid):
    auto._url(url)
    u=urlsplit(url)
    if who=="net":
        need(u.hostname=="keirin.netkeiba.com" and
             u.path=="/race/entry/" and
             parse_qs(u.query).get("race_id")==[rid],
             "NETKEIRIN_ORDINARY_RACECARD_RACE_ID_MISMATCH")
    else:
        need(u.hostname=="keirin.kdreams.jp" and
             u.path.startswith("/") and "/racedetail/" in u.path and
             u.path.endswith("/") and
             rid[:8] in u.path and rid[8:10] in u.path and
             u.path[-3:-1]==rid[10:12],
             "KDREAMS_RACE_DETAIL_ID_MISMATCH")


def _mark(raw,n):
    m=raw.strip()
    if m in ("", "--", "-", "100", "消", "無", "未選択"):
        return "UNMARKED"
    if m in ("◎","本命"):
        return 1
    if m in ("○","◯","対抗"):
        return 2
    if m in ("▲","単穴"):
        return 3
    if m in ("△","☆","注","×","✕","押"):
        return 4
    try:
        rank=int(m)
    except ValueError:
        raise PublicPageNormalizeError("SOURCE_PAPER_MARK_UNKNOWN") from None
    need(1<=rank<=n,"PAPER_MARK_OUT_OF_BOUNDS")
    return rank


def _style(value):
    value=normalize("NFKC",value)
    if "逃" in value:return "NIGE"
    if "両" in value:return "ALLROUND"
    if "追" in value:return "MARK"
    return "UNKNOWN"


def _float(value,*,lo,hi):
    try:
        x=float(value.strip().replace("%",""))
    except ValueError:
        raise PublicPageNormalizeError("PUBLISHED_NUMERIC_ROW_INVALID") from None
    need(lo<=x<=hi and x==x,"PUBLISHED_NUMERIC_OUT_OF_RANGE")
    return x


def _count(value):
    try:
        num=int(value.strip())
    except ValueError:
        raise PublicPageNormalizeError("PUBLISHED_H_B_NOT_INTEGER") from None
    need(0<=num<=99,"PUBLISHED_H_B_OUT_OF_RANGE")
    return num


def parse_netkeirin(*,raw,source_url,race_id,captured_at):
    """Printed 23-field paper-mark racecard only. Unsupported layouts HOLD."""
    _url_role(source_url,"net",race_id)
    _time(captured_at)
    _,_,rows=_text(raw)
    found={}
    for row in rows:
        parts=[normalize("NFKC",p).strip() for p in row.strip().split("|")]
        # Table: frame/car/checkbox/paper/athlete/points/style/S/H/B/
        # escape/makuri/sashi/mark/1st/2nd/3rd/other/win/2nd/3rd/gear/comment
        if len(parts)!=23 or not re.fullmatch(r"[1-9]",parts[1]):
            continue
        try:
            car=int(parts[1])
            if not 1<=car<=9:
                continue
            mark=_mark(parts[3],9)
            points=_float(parts[5],lo=0,hi=150)
            home=_count(parts[8]);back=_count(parts[9])
            win=_float(parts[18],lo=0,hi=100)/100
            need(parts[4] and len(parts[4])<=160,
                 "RIDER_NAME_ON_SOURCE_REQUIRED")
            need(parts[6] and len(parts[6])<=10,
                 "SOURCE_STYLE_REQUIRED")
        except PublicPageNormalizeError:
            # If it resembles a rider row but is malformed, reject page.
            raise
        need(car not in found,"NETKEIRIN_DUPLICATE_CAR")
        found[car]={
            "car":car,
            "athlete_id":None,  # provider-local ID is not official registration.
            "mark_rank":mark,
            "competition_points":points,
            # Win rate is a literal last-four-month observed percentage.
            # It is NOT an inference about the last two appearances.
            "recent_form_score":win,
            "h_count":home,"b_count":back,"style":_style(parts[6])}
    need(5<=len(found)<=9 and
         set(found)==set(range(1,len(found)+1)),
         "NETKEIRIN_COMPLETE_SOURCED_ENTRANTS_MISSING")
    return [found[n] for n in sorted(found)]


def parse_kdreams(*,raw,source_url,race_id,captured_at):
    """Visible bracket-style line only, no inferred groups from flattened cars."""
    _url_role(source_url,"k",race_id)
    _time(captured_at)
    _,text,_rows=_text(raw)
    # Separate the actual race header from site navigation / result pages.
    need("並び予想" in text and
         ("投票締切" in text or "締切" in text),
         "KDREAMS_VISIBLE_LINE_OR_CUTOFF_MISSING")
    cutoff_area=re.search(
        r"(?:投票締切|締切)\s*([0-9]{1,2}:[0-9]{2})",text)
    need(cutoff_area is not None,"KDREAMS_PUBLISHED_CUTOFF_CLOCK_MISSING")
    end_hour,end_minute=map(int,cutoff_area.group(1).split(":"))
    need(0<=end_hour<=23 and 0<=end_minute<=59,
         "KDREAMS_CUTOFF_TIME_INVALID")
    cutoff=f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}T{end_hour:02d}:{end_minute:02d}:00+09:00"
    # Markup is often "← 3先行 5追込 6追込 4押え先 1追込 7押え先 2追込".
    # Start a group ONLY at an explicit "先行 / 押え先 / 自在".
    section=text.split("並び予想",1)[1]
    section=section.split("レース評",1)[0].split("予想担当",1)[0]
    section=section.replace("←"," ")
    matches=list(TOKENS.finditer(section))
    groups=[]
    if matches:
        covered=GAP.sub("",section[:matches[0].start()])
        need(covered in ("","：",":"),"KDREAMS_LINE_PREFIX_AMBIGUOUS")
        for match in matches:
            car=int(match.group(1))
            role=match.group(2)
            if role in ("先行","押え先","自在","単騎","追上"):
                groups.append([car])
            else:
                need(bool(groups),"KDREAMS_FOLLOWER_WITHOUT_LEADER")
                groups[-1].append(car)
    else:
        # Alternative explicit slash form e.g. "並び予想は 3-5-6／4-1／7-2"
        seq=FORM.search("並び予想"+section)
        need(seq is not None,"KDREAMS_EXPLICIT_LINE_GROUPS_MISSING")
        groups=[
            [int(x) for x in re.findall(r"[1-9]",g)]
            for g in re.split("[／/]",seq.group(1))
            if g.strip()]
    all_cars=sum(groups,[])
    need(5<=len(all_cars)<=9 and
         set(all_cars)==set(range(1,len(all_cars)+1)) and
         len(set(all_cars))==len(all_cars),
         "KDREAMS_LINE_NOT_ALL_REAL_CARS")
    grade_text=normalize("NFKC",text[:text.index("並び予想")])
    # Extract visible race class/stage; never synthesize a program rule.
    if "ガールズ" in grade_text or "L級" in grade_text:
        competition="GIRLS"
    elif "チャレンジ" in grade_text:
        competition="CHALLENGE"
    elif "S級" in grade_text:
        competition="S"
    elif "A級" in grade_text:
        competition="A1_A2"
    else:
        raise PublicPageNormalizeError("KDREAMS_RACE_CLASS_NOT_IN_SOURCE")
    # The stage is descriptive only, no generic inferred promotion rule.
    if "決勝" in grade_text:
        stage="FINAL"
    elif "準決" in grade_text:
        stage="SEMI_FINAL"
    elif "一般" in grade_text:
        stage="GENERAL"
    elif "予選" in grade_text:
        stage="PRELIMINARY"
    elif "特選" in grade_text:
        stage="SELECTION"
    else:
        stage="OTHER"
    if competition=="GIRLS":
        need(all(len(g)==1 for g in groups),
             "GIRLS_UNKNOWN_FIXED_LINE_STRUCTURE")
    return {"cutoff_at":cutoff,"line_groups":groups,
            "competition":competition,"round_stage":stage}


def merge_pre_race_pages(*,race_id,netkeirin_raw,netkeirin_url,
                         netkeirin_captured_at,kdreams_raw,kdreams_url,
                         kdreams_captured_at,created_at):
    """Two captured public sources, strict same-race identity and provenance."""
    riders=parse_netkeirin(raw=netkeirin_raw,source_url=netkeirin_url,
                          race_id=race_id,captured_at=netkeirin_captured_at)
    bracket=parse_kdreams(raw=kdreams_raw,source_url=kdreams_url,
                          race_id=race_id,captured_at=kdreams_captured_at)
    now=_time(created_at)
    seen_net=_time(netkeirin_captured_at)
    seen_kd=_time(kdreams_captured_at)
    need(max(seen_net,seen_kd)<=now,
         "SOURCE_NOT_COLLECTED_BEFORE_NORMALIZATION")
    need(len(riders)==sum(map(len,bracket["line_groups"])),
         "NETKEIRIN_AND_KDREAMS_RIDER_COUNT_DISAGREE")
    as_of=max(seen_net,seen_kd).isoformat()
    def source(kind,url,raw,at):
        return {"kind":kind,"url":url,
                "bytes_sha256":sha256(raw).hexdigest(),
                "captured_at":at}
    roster=source("RACECARD",netkeirin_url,netkeirin_raw,netkeirin_captured_at)
    page=source("LINE",kdreams_url,kdreams_raw,kdreams_captured_at)
    packet={
        "schema":auto.SCHEMA,"race_id":race_id,"as_of":as_of,
        "published_cutoff_at":bracket["cutoff_at"],
        "cutoff_source":{
            "url":kdreams_url,
            "bytes_sha256":sha256(kdreams_raw).hexdigest(),
            "captured_at":kdreams_captured_at},
        "source_pages":[roster,source("MARKS",netkeirin_url,
                                      netkeirin_raw,netkeirin_captured_at),page],
        "competition":bracket["competition"],
        "round_stage":bracket["round_stage"],
        "round_rule":None,
        "line_groups":bracket["line_groups"],
        "riders":riders,
    }
    auto.validate_snapshot(packet,computed_at=created_at)
    return {
        "schema":SCHEMA,
        "source_packet":packet,
        "packet_sha256":auto.digest(packet),
        "netkeirin_sha256":sha256(netkeirin_raw).hexdigest(),
        "kdreams_sha256":sha256(kdreams_raw).hexdigest(),
        "provider_H_B_definition_not_cross_conflated":True,
        "recent_form_is_observed_last_four_month_win_rate_proxy":True,
        "true_athlete_registration_ids_from_this_pair_verified":False,
        "organizer_actual_close_instant_independently_verified":False,
        "no_new_forecast_generated_during_normalization":True,
    }
