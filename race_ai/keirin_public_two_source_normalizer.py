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


def _page(raw):
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
        return value,body,rows,soup
    return value,value,[x.strip().strip("|") for x in value.splitlines()
                        if "|" in x],None


def _text(raw):
    # Preserve the saved-page diagnostic's existing three-value interface.
    return _page(raw)[:3]


def _check_canonical(soup,source_url):
    """Bind a published canonical when present; old table text has none."""
    if soup is None:
        return
    links=[node for node in soup.find_all("link")
           if "canonical" in [str(x).lower() for x in node.get("rel",[])]]
    need(not links or (len(links)==1 and links[0].get("href")==source_url),
         "SOURCE_CANONICAL_URL_RACE_MISMATCH")


def _url_role(url,who,rid):
    auto._url(url)
    u=urlsplit(url)
    if who=="net":
        need(u.hostname=="keirin.netkeiba.com" and
             u.path=="/race/entry/" and
             parse_qs(u.query).get("race_id")==[rid],
             "NETKEIRIN_ORDINARY_RACECARD_RACE_ID_MISMATCH")
    else:
        # Kdreams detail IDs encode MEETING start and DAY INDEX, not
        # necessarily the race's own date (day two/three would fail a
        # naïve YYYYMMDD-in-URL check).
        item=re.fullmatch(
            r"/[a-z0-9-]+/racedetail/([0-9]{2})(20[0-9]{6})([0-9]{2})00([0-9]{2})/",
            u.path)
        try:
            if item is None:
                raise ValueError("details")
            code,begin,index,number=item.groups()
            day=datetime.strptime(begin,"%Y%m%d").date()+timedelta(
                days=int(index)-1)
            correct=(u.hostname=="keirin.kdreams.jp" and
                     1<=int(index)<=7 and code==rid[8:10] and
                     f"{day:%Y%m%d}"==rid[:8] and
                     number==rid[10:12])
        except (ValueError,OverflowError):
            correct=False
        need(correct,"KDREAMS_RACE_DETAIL_ID_MISMATCH")


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
    _,_,rows,soup=_page(raw)
    _check_canonical(soup,source_url)
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
        normalized={
            "car":car,
            "athlete_id":None,  # provider-local ID is not official registration.
            "mark_rank":mark,
            "competition_points":points,
            # Win rate is a literal last-four-month observed percentage.
            # It is NOT an inference about the last two appearances.
            "recent_form_score":win,
            "h_count":home,"b_count":back,"style":_style(parts[6])}
        if car in found:
            # Responsive desktop/mobile pages often repeat the exact same
            # racecard table. Admit strictly identical duplicate rows only.
            # Different identity/points/mark/H/B is NOT merged or averaged.
            need(found[car]==normalized,"NETKEIRIN_CONFLICTING_CAR_ROWS")
            continue
        found[car]=normalized
    need(5<=len(found)<=9 and
         set(found)==set(range(1,len(found)+1)),
         "NETKEIRIN_COMPLETE_SOURCED_ENTRANTS_MISSING")
    return [found[n] for n in sorted(found)]


def _scoped_kdreams(soup,*,race_id,starter_cars,competition_hint=None):
    """Use the selected race header and actual displayed line separators."""
    headers=soup.select("div.racecard_header")
    need(len(headers)==1,"KDREAMS_RACE_HEADER_AMBIGUOUS")
    header=headers[0]
    titles=header.select("h2.title > span.status")
    need(len(titles)==1,"KDREAMS_RACE_CLASS_NOT_IN_SOURCE")
    title=normalize("NFKC",titles[0].get_text(" ",strip=True))
    need(1<=len(title)<=160,"KDREAMS_RACE_CLASS_NOT_IN_SOURCE")
    cutoffs=[]
    for dt in header.select("dl.time > dt"):
        label=normalize("NFKC",dt.get_text("",strip=True))
        if label not in ("締切","投票締切"):
            continue
        dd=dt.find_next_sibling()
        need(dd is not None and dd.name=="dd",
             "KDREAMS_PUBLISHED_CUTOFF_CLOCK_MISSING")
        cutoffs.append(normalize("NFKC",dd.get_text("",strip=True)))
    need(len(cutoffs)==1 and re.fullmatch(r"[0-9]{1,2}:[0-9]{2}",cutoffs[0]),
         "KDREAMS_PUBLISHED_CUTOFF_CLOCK_MISSING")
    hour,minute=map(int,cutoffs[0].split(":"))
    need(0<=hour<=23 and 0<=minute<=59,"KDREAMS_CUTOFF_TIME_INVALID")
    cutoff=f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}T{hour:02d}:{minute:02d}:00+09:00"
    girls="ガールズ" in title or "L級" in title or competition_hint=="GIRLS"
    if girls:
        # Displayed positions are not permanent cooperative lines in L-class.
        need(type(starter_cars) is list and 5<=len(starter_cars)<=9 and
             len(set(starter_cars))==len(starter_cars) and
             all(type(car) is int and 1<=car<=9 for car in starter_cars),
             "GIRLS_ROSTER_REQUIRED_FOR_SOLO_RESEARCH")
        groups=[[car] for car in starter_cars]
    else:
        wraps=soup.select("div.line_position_inner") or soup.select("div.line_position")
        need(len(wraps)==1,"KDREAMS_EXPLICIT_LINE_GROUPS_MISSING")
        groups=[]
        group=[]
        for span in wraps[0].find_all("span",recursive=False):
            if "space" in span.get("class",[]):
                if group:
                    groups.append(group)
                    group=[]
                continue
            children=span.find_all("span",recursive=False)
            if children:
                number=normalize("NFKC",children[0].get_text("",strip=True))
                if re.fullmatch(r"[1-9]",number):
                    group.append(int(number))
        if group:
            groups.append(group)
    cars=sum(groups,[])
    need(5<=len(cars)<=9 and len(set(cars))==len(cars) and
         set(cars)==set(range(1,len(cars)+1)),
         "KDREAMS_LINE_NOT_ALL_REAL_CARS")
    competition=("GIRLS" if girls else "CHALLENGE" if "チャレンジ" in title else
                 "S" if "S級" in title else "A1_A2" if "A級" in title else competition_hint)
    need(competition is not None,"KDREAMS_RACE_CLASS_NOT_IN_SOURCE")
    stage=next((value for word,value in (
        ("準決","SEMI_FINAL"),("決勝","FINAL"),("一般","GENERAL"),
        ("予選","PRELIMINARY"),("特選","SELECTION")) if word in title),"OTHER")
    return {"cutoff_at":cutoff,"line_groups":groups,
            "competition":competition,"round_stage":stage}


def parse_kdreams(*,raw,source_url,race_id,captured_at,
                  starter_cars=None):
    """Published race DOM, with legacy saved visible-table/text support."""
    _url_role(source_url,"k",race_id)
    _time(captured_at)
    _,text,_rows,soup=_page(raw)
    _check_canonical(soup,source_url)
    if soup is not None and soup.select("div.racecard_header"):
        return _scoped_kdreams(soup,race_id=race_id,starter_cars=starter_cars)
    # Separate the actual race header from site navigation / result pages.
    need("投票締切" in text or "締切" in text,
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
    grade_text=normalize("NFKC",text.rsplit("並び予想",1)[0])
    # Girls racing has no fixed pre-race line. Kdreams may not show a
    # "並び予想" section at all. Do not fabricate temporary cooperation.
    solo_girls=("ガールズ" in grade_text or "L級" in grade_text)
    if "並び予想" not in text and solo_girls:
        need(type(starter_cars) is list and
             5<=len(starter_cars)<=9 and
             len(set(starter_cars))==len(starter_cars),
             "GIRLS_ROSTER_REQUIRED_FOR_SOLO_RESEARCH")
        groups=[[car] for car in starter_cars]
        section=""
        matches=[]
    else:
        need("並び予想" in text,
             "KDREAMS_EXPLICIT_LINE_GROUPS_MISSING")
        # The site navigation may contain an earlier "並び予想" anchor;
        # use the final race-detail section, not the first global menu hit.
        section=text.rsplit("並び予想",1)[1]
        section=section.split("レース評",1)[0].split("予想担当",1)[0]
        section=section.replace("←"," ")
        matches=list(TOKENS.finditer(section))
        groups=[]
    if matches:
        covered=normalize("NFKC",section[:matches[0].start()]).strip()
        # Plain non-numeric labels or punctuation are harmless; a prefix
        # containing car numbers may be a second, conflicting lineup.
        need(len(covered)<=60 and not any(c.isdigit() for c in covered),
             "KDREAMS_LINE_PREFIX_AMBIGUOUS")
        for match in matches:
            car=int(match.group(1))
            role=match.group(2)
            if role in ("先行","押え先","自在","単騎","追上"):
                groups.append([car])
            else:
                need(bool(groups),"KDREAMS_FOLLOWER_WITHOUT_LEADER")
                groups[-1].append(car)
    elif not (solo_girls and groups):
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
    # Extract visible race class/stage; never synthesize a program rule.
    # Navigation may mention unrelated "L級" or "ガールズ". A visible
    # challenge round label paired with a non-solo wheel formation is more
    # specific evidence than a site-wide navbar category.
    challenge_round=bool(re.search(
        r"チャレンジ(?:予選|一般|準決|決勝|選抜|特選)", grade_text))
    a_round=bool(re.search(
        r"A級(?:特一般|特選|準決勝?|決勝|一般|予選|特予)",grade_text))
    s_round=bool(re.search(
        r"S級(?:準決勝?|決勝|特選|一般|選抜|一次予選)",grade_text))
    if challenge_round and any(len(g)>1 for g in groups):
        competition="CHALLENGE"
    elif a_round and any(len(g)>1 for g in groups):
        competition="A1_A2"
    elif s_round and any(len(g)>1 for g in groups):
        competition="S"
    elif "ガールズ" in grade_text or "L級" in grade_text:
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
    if "準決" in grade_text:
        stage="SEMI_FINAL"
    elif "決勝" in grade_text:
        stage="FINAL"
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


def _selected_net_class(*,race_id,netkeirin_raw,netkeirin_url,netkeirin_captured_at,
                        kdreams_raw,kdreams_url,starter_cars):
    """Opt-in class fact from one current header, never history or rider grades."""
    _,_,_,net=_page(netkeirin_raw)
    _,_,_,kd=_page(kdreams_raw)
    if kd is None or not kd.select('div.racecard_header'):
        return None  # Keep the legacy saved-text adapter unchanged.
    headers=kd.select('div.racecard_header')
    need(len(headers)==1,'KDREAMS_RACE_HEADER_AMBIGUOUS')
    titles=headers[0].select('h2.title > span.status')
    need(len(titles)==1,'KDREAMS_RACE_CLASS_NOT_IN_SOURCE')
    kd_title=GAP.sub('',normalize('NFKC',titles[0].get_text(' ',strip=True)))
    kd_class=('GIRLS' if 'ガールズ' in kd_title or 'L級' in kd_title else
              'CHALLENGE' if 'チャレンジ' in kd_title else
              'S' if 'S級' in kd_title else 'A1_A2' if 'A級' in kd_title else None)
    names=net.select('.Race_Name') if net is not None else []
    if not names and kd_class is not None:
        return None  # An existing Kdreams class needs no new source dependency.
    need(len(names)==1,'NET_SELECTED_CLASS_HEADER_AMBIGUOUS')
    header=normalize('NFKC',names[0].get_text(' ',strip=True))
    need(1<=len(header)<=160,'NET_SELECTED_CLASS_HEADER_AMBIGUOUS')
    match=re.fullmatch(r'(A級チャレンジ|L級ガールズ|S級|A級|L級)(.+)',GAP.sub('',header))
    if match is None and kd_class is not None:
        return None  # No competing class fact; keep the original Kdreams packet.
    need(match is not None and not any(v in match[2] for v in
         ('S級','A級','L級','チャレンジ')),'NET_SELECTED_CLASS_NOT_EXPLICIT')
    prefix=match[1]
    competition=('CHALLENGE' if 'チャレンジ' in prefix else 'GIRLS' if 'L級' in prefix
                 else 'S' if prefix=='S級' else 'A1_A2')
    if kd_class==competition:
        return None  # Net supplies no missing class; preserve the existing packet.
    selected=names[0].find_parent('div',class_='RaceList_NameBox_inner')
    need(selected is not None and len(net.select('div.RaceList_NameBox_inner'))==1 and
         len(selected.select('.Race_Name'))==1,'NET_SELECTED_CLASS_SCOPE_REQUIRED')
    wrapper=selected.find_parent('div',class_='RaceList_NameBox')
    active=wrapper.select('a.Active') if wrapper is not None else []
    need(len(active)==1 and active[0].get('href')==netkeirin_url,
         'NET_SELECTED_CLASS_SELECTION_MISMATCH')
    numbers=selected.select('.Race_Num')
    need(len(numbers)==1 and normalize('NFKC',numbers[0].get_text('',strip=True))==
         str(int(race_id[-2:]))+'R','NET_SELECTED_CLASS_RACE_MISMATCH')
    _url_role(netkeirin_url,'net',race_id)
    _url_role(kdreams_url,'k',race_id)
    for soup,url in ((net,netkeirin_url),(kd,kdreams_url)):
        links=[n for n in soup.find_all('link') if 'canonical' in
               [str(v).lower() for v in n.get('rel',[])]]
        need(len(links)==1 and links[0].get('href')==url,
             'SELECTED_CLASS_CANONICAL_REQUIRED')
    if kd_class is not None:
        need(competition==kd_class,'SELECTED_RACE_CLASS_SOURCE_CONFLICT')
        return None
    need(match[2]==kd_title,'SELECTED_RACE_CLASS_LABEL_MISMATCH')
    net_names={}
    for row in net.find_all('tr'):
        cells=row.find_all(['td','th'],recursive=False)
        if len(cells)!=23:
            continue
        number=normalize('NFKC',cells[1].get_text('',strip=True))
        if not re.fullmatch('[1-9]',number):
            continue
        car=int(number);full_names=cells[4].select('dt.PlayerName')
        if full_names:
            need(len(full_names)==1,'SELECTED_CLASS_NET_ROSTER_AMBIGUOUS')
            # Full desktop identity is direct text. Child SVG/title text is
            # favorite-button metadata, and the mobile link is abbreviated.
            text=''.join(full_names[0].find_all(string=True,recursive=False))
        elif cells[4].select('div.PlayerName.DispB'):
            continue  # A complete full-name row for this car is still required.
        else:
            need(not cells[4].find(True),'SELECTED_CLASS_NET_ROSTER_AMBIGUOUS')
            text=cells[4].get_text('',strip=True)
        name=GAP.sub('',normalize('NFKC',text))
        need(1<=len(name)<=160 and (car not in net_names or net_names[car]==name),
             'SELECTED_CLASS_NET_ROSTER_AMBIGUOUS')
        net_names[car]=name
    tables=kd.select('table.racecard_table')
    need(bool(tables),'SELECTED_CLASS_KD_ROSTER_REQUIRED')
    kd_names={}
    for row in tables[0].select('tr'):
        number=row.select_one('td.num');rider=row.select_one('td.rider')
        if number is None or not re.fullmatch('[1-9]',normalize('NFKC',number.get_text('',strip=True))):
            continue
        car=int(normalize('NFKC',number.get_text('',strip=True)))
        parts=list(rider.stripped_strings) if rider is not None else []
        need(parts and car not in kd_names,'SELECTED_CLASS_KD_ROSTER_AMBIGUOUS')
        kd_names[car]=GAP.sub('',normalize('NFKC',parts[0]))
    need(set(net_names)==set(starter_cars) and net_names==kd_names,
         'SELECTED_CLASS_SOURCE_ROSTER_MISMATCH')
    return dict(field='competition',provider='netkeirin',race_id=race_id,
        day_jst=race_id[:4]+'-'+race_id[4:6]+'-'+race_id[6:8],competition=competition,
        url=netkeirin_url,bytes_sha256=sha256(netkeirin_raw).hexdigest(),
        captured_at=netkeirin_captured_at,selector='.RaceList_NameBox_inner .Race_Name',
        selected_header=header,selected_header_sha256=sha256(header.encode()).hexdigest())


def merge_pre_race_pages(*,race_id,netkeirin_raw,netkeirin_url,
                         netkeirin_captured_at,kdreams_raw,kdreams_url,
                         kdreams_captured_at,created_at,allow_selected_netkeirin_class=False):
    """Two captured public sources, strict same-race identity and provenance."""
    riders=parse_netkeirin(raw=netkeirin_raw,source_url=netkeirin_url,
                          race_id=race_id,captured_at=netkeirin_captured_at)
    need(type(allow_selected_netkeirin_class) is bool,'SELECTED_CLASS_OPT_IN_REQUIRED')
    class_source=(_selected_net_class(race_id=race_id,netkeirin_raw=netkeirin_raw,
        netkeirin_url=netkeirin_url,netkeirin_captured_at=netkeirin_captured_at,
        kdreams_raw=kdreams_raw,kdreams_url=kdreams_url,starter_cars=[r['car'] for r in riders])
        if allow_selected_netkeirin_class else None)
    if class_source is None:
        bracket=parse_kdreams(raw=kdreams_raw,source_url=kdreams_url,
                              race_id=race_id,captured_at=kdreams_captured_at,
                              starter_cars=[r["car"] for r in riders])
    else:
        _time(kdreams_captured_at)
        bracket=_scoped_kdreams(_page(kdreams_raw)[3],race_id=race_id,
            starter_cars=[r['car'] for r in riders],competition_hint=class_source['competition'])
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
    if class_source is not None:
        packet['source_pages'].append(source('PROGRAM',netkeirin_url,netkeirin_raw,netkeirin_captured_at))
    auto.validate_snapshot(packet,computed_at=created_at)
    result={
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
    if class_source is not None:
        result['class_field_source']=class_source
    return result
