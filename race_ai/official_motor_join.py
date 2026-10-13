"""Join motor usage by completed meet with official racer profile extracts.

This is an OFFLINE, provenance-labeled, retrospective descriptive audit.
It does not fetch websites, assign phantom race IDs, or claim online availability
at the historical decision time. All supplied text must come from a permitted source.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import json
import re
import unicodedata


class OfficialSourceError(ValueError):
    pass


def _normal(s: str) -> str:
    return unicodedata.normalize('NFKC',str(s))


def _name(s: str) -> str:
    return re.sub(r'\s+', '', _normal(s))


class _TrParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]
        self.row=None
        self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':
            self.row=[]
        if tag in ('th','td') and self.row is not None:
            self.cell=[]
        if tag=='br' and self.cell is not None:
            self.cell.append(' ')
    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('th','td') and self.cell is not None and self.row is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row)
            self.row=None


def _rows(text: str) -> list[list[str]]:
    if '<tr' in text.lower():
        parser=_TrParser()
        parser.feed(text)
        if parser.rows:
            return parser.rows
    lines=[]
    for line in text.splitlines():
        line=re.sub(r'^\s*L\d+:\s*','',line).strip()
        if line.startswith('【') and ' | ' in line:
            line=re.sub(r'^【[^】]+】\s*','',line)
        if '|' in line:
            lines.append([x.strip() for x in line.split('|')])
    return lines


_DATES=re.compile(r'(?P<start>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s*[～〜~\-–]+\s*(?P<end>20\d{2}[/-]\d{1,2}[/-]\d{1,2})')
_DIGIT=re.compile(r'([1-6])')
_FINAL=re.compile(r'\[([1-6])\]')
_ALLOWED=re.compile(r'^[1-6FL欠失転落妨不沈返待保その他\[\]\s]+$')


def parse_motor_history(text: str, *, venue: str, motor_no: int, source_url: str,
                        captured_at: str) -> list[dict]:
    """Parse rows under a known official site's motor-history detail heading.

    Only four-column history rows are accepted. A published site HTML format
    change is a SAFE_STOP rather than a guessed structure.
    """
    if not re.fullmatch(r'\d{2}',str(venue)) or type(motor_no) is not int or not 1<=motor_no<=999:
        raise OfficialSourceError('invalid venue/motor')
    if not source_url.startswith('https://'):
        raise OfficialSourceError('HTTPS source URL required')
    if not captured_at:
        raise OfficialSourceError('snapshot capture time required')
    norm=_normal(text)
    # Prevent choosing an unrelated motor's table from an aggregate search page.
    motor_mark=re.search(r'(\d{1,3})番モーターの節間成績',norm)
    if motor_mark is None or int(motor_mark.group(1))!=motor_no:
        raise OfficialSourceError('motor-specific detail heading not found/mismatched')
    output=[]
    for cells in _rows(text):
        if len(cells)!=4:
            continue
        dated=_DATES.search(_normal(cells[0]))
        if not dated:
            continue
        start=date.fromisoformat(dated.group('start').replace('/','-'))
        end=date.fromisoformat(dated.group('end').replace('/','-'))
        if end<start:
            raise OfficialSourceError('meet ends before it starts')
        title=_normal(cells[1]).strip()
        racer=_name(cells[2])
        results=_normal(cells[3]).replace(' ','').replace('　','')
        if not (title and racer and results) or not _ALLOWED.fullmatch(results):
            raise OfficialSourceError('unrecognized racer/results line; manual verification required')
        all_finishes=[int(x) for x in _DIGIT.findall(results)]
        if not all_finishes:
            raise OfficialSourceError('no numerical race finishes')
        final_positions=[int(x) for x in _FINAL.findall(results)]
        output.append(dict(venue=str(venue),motor_no=motor_no,
            start=start.isoformat(),end=end.isoformat(),meet_label=title,
            racer_name=racer,finish_sequence=results,
            ordinary_races=len(all_finishes)-len(final_positions),
            finish_count=len(all_finishes),top2_count=sum(x<=2 for x in all_finishes),
            top2_rate=round(sum(x<=2 for x in all_finishes)/len(all_finishes),6),
            final_positions=final_positions,
            source_url=source_url,captured_at=captured_at))
    if not output:
        raise OfficialSourceError('no completed official motor-use rows found')
    keys={(r['start'],r['end']) for r in output}
    if len(keys)!=len(output):
        raise OfficialSourceError('duplicate same-date motor use; requires manual review')
    return sorted(output,key=lambda r:r['start'],reverse=True)


def parse_official_racer_profile(text: str, *, expected_name: str,
                                 source_url: str, captured_at: str) -> dict:
    if '<html' in text.lower() or '<body' in text.lower():
        # Decode the visible profile text only. Do not parse IDs out of attributes.
        class PlainText(HTMLParser):
            def __init__(self):
                super().__init__()
                self.chunks=[]
            def handle_data(self,data):
                self.chunks.append(data)
        visible=PlainText()
        visible.feed(text)
        norm=_normal(' '.join(visible.chunks))
    else:
        norm=_normal(text)
    if not source_url.startswith('https://'):
        raise OfficialSourceError('HTTPS racer source URL required')
    if _name(expected_name) not in _name(norm):
        raise OfficialSourceError('official profile name mismatch')
    number=re.search(r'登録番号\s*(\d{4})',norm)
    cohort=re.search(r'登録期\s*(\d{1,3})期',norm)
    if not number or not cohort:
        raise OfficialSourceError('official racer ID or registration cohort missing')
    # Profiles from /data/racersearch/profile?toban=XXXX must not silently bind
    # a different registered racer than the URL identifies.
    from urllib.parse import parse_qs,urlsplit
    params=parse_qs(urlsplit(source_url).query)
    if 'toban' in params and number.group(1) not in params['toban']:
        raise OfficialSourceError('profile URL registration number mismatch')
    return dict(racer_name=_name(expected_name),racer_id=number.group(1),
                registration_cohort=int(cohort.group(1)),source_url=source_url,
                captured_at=captured_at)


def rookie_proxy(profile: dict, meet_date: str, *, cohort_debut_months: dict[int,str]) -> dict:
    """No invented debut date or absolute 'rookie' label.

    Cohort-wide first debut *month* is from official graduating-school notices;
    individual actual debut dates and starts require separate real data.
    """
    cohort=profile.get('registration_cohort')
    debut_month=cohort_debut_months.get(cohort)
    if debut_month is None:
        return dict(status='UNKNOWN',reason='no confirmed official cohort debut month')
    year,month=map(int,debut_month.split('-'))
    d=date.fromisoformat(meet_date)
    month_gap=(d.year-year)*12+d.month-month
    if month_gap<0:
        return dict(status='INVALID',reason='usage predates cohort expected debut')
    return dict(status='RECENT_DEBUT_COHORT' if month_gap<12 else 'OLDER_COHORT',
                months_since_cohort_debut_month=month_gap,cohort=cohort,
                reason='cohort proxy, not player-specific race debut date or skill rank')


def audit_previous_meet(history: list[dict], profiles: list[dict], *,
                        target_meet_start: str, cohort_debut_months: dict[int,str],
                        decision_at: str|None=None) -> dict:
    target=next((r for r in history if r['start']==target_meet_start),None)
    if not target:
        raise OfficialSourceError('target meeting not present in supplied motor history')
    older=sorted((r for r in history if r['end']<target['start']),
                 key=lambda r:r['end'],reverse=True)
    if not older:
        return dict(target=target,previous=None,confidence='UNKNOWN_PREVIOUS')
    prev=older[0]
    matched=[p for p in profiles if p['racer_name']==prev['racer_name']]
    if len(matched)!=1:
        return dict(target=target,previous=prev,profile=None,
                    rookie_proxy={'status':'UNKNOWN','reason':'missing/ambiguous exact racer name match'},
                    prediction_asof_supported=False,
                    confidence='UNVERIFIED_PROFILE')
    profile=matched[0]
    proxy=rookie_proxy(profile,prev['start'],cohort_debut_months=cohort_debut_months)
    # Retrospective site snapshot is not evidence the same source was published pre-race.
    return dict(target=target,previous=prev,profile=profile,
                rookie_proxy=proxy,prediction_asof_supported=False,
                warning='Historical web snapshot is NOT proven to have been available at target-race decision time; use for retrospective audit only.',
                result='HISTORICAL_JOINED_PROFILE_VERIFIED')


def load_join(motor_file: str|Path,profile_files: list[str|Path], *,
              venue: str,motor_no: int,motor_source: str,
              profile_sources: list[str], captured_at: str,
              target_meet_start: str,cohort_debut_months: dict[int,str],
              expected_profile_names: list[str]|None=None) -> dict:
    if len(profile_files)!=len(profile_sources):
        raise OfficialSourceError('each profile file requires its own official source URL')
    if expected_profile_names is not None and len(expected_profile_names)!=len(profile_files):
        raise OfficialSourceError('one expected racer name per profile is required')
    motor_bytes=Path(motor_file).read_bytes()
    motor_text=motor_bytes.decode('utf-8-sig')
    history=parse_motor_history(motor_text,venue=venue,motor_no=motor_no,
                               source_url=motor_source,captured_at=captured_at)
    profiles=[]
    for i,(file,url) in enumerate(zip(profile_files,profile_sources)):
        text=Path(file).read_text(encoding='utf-8-sig')
        if expected_profile_names is not None:
            first=_name(expected_profile_names[i])
        elif '<html' in text.lower() or '<body' in text.lower():
            raise OfficialSourceError('raw HTML profile requires explicit expected_profile_names')
        else:
            first=_name(re.split(r'[（(]',_normal(text.splitlines()[0]))[0])
        # Header must be an operator-provided profile identity, NOT free text guessing.
        if not first or not re.fullmatch(r'[\u3040-\u30ff\u3400-\u9fff\w]+',first):
            raise OfficialSourceError('first profile line must be racer name')
        profiles.append(parse_official_racer_profile(text,expected_name=first,
                    source_url=url,captured_at=captured_at))
    outcome=audit_previous_meet(history,profiles,
            target_meet_start=target_meet_start,cohort_debut_months=cohort_debut_months)
    outcome['motor_snapshot_sha256']=hashlib.sha256(motor_bytes).hexdigest()
    outcome['input_profile_sha256']=[hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in profile_files]
    outcome['motor_rows_parsed']=len(history)
    return outcome
