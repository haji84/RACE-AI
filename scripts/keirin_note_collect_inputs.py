"""Collect owner-private Site-shaped inputs and unchanged research A/B only.

Ordinary linked Kdreams pages and netkeirin entry pages; no result requests,
authored analysis, formal PR71 admission, model changes, encryption-key access,
wagers or hosting. Runtime persistence and global stop admission belong to the
existing owner orchestrator. Every plaintext output stays in a private folder.
"""
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from unicodedata import normalize
from urllib.parse import urlsplit
import argparse
import json
import math
import os
import re

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_public_two_source_normalizer as normalize_pages
from race_ai.keirin_note_view import _private_root, MAX_FILE
from scripts import keirin_capture_public_two_sources as capture
from scripts import keirin_discover_public_race_links as links

UTC=timezone.utc
JST=normalize_pages.JST
SCHEMA='RACE_AI_KEIRIN_NOTE_INPUT_COLLECTION_V1'
DENIED='PROVIDER_DENIED_OR_RATE_LIMITED_STOP'
STOPS={DENIED,'PUBLIC_PROVIDER_HTTP_ERROR_STOP','PUBLIC_PROVIDER_UNAVAILABLE_STOP'}


def need(ok,code):
    if not ok:
        raise ValueError('NOTE_'+code)


def _now(clock):
    value=clock()
    need(isinstance(value,datetime) and value.utcoffset() is not None,'AWARE_CLOCK_REQUIRED')
    return value.astimezone(UTC)


def _safe_reason(error):
    reason=str(error)
    return reason if re.fullmatch('[A-Z][A-Z_0-9]{0,99}',reason) else 'SOURCE_OR_LAYOUT_UNAVAILABLE'


def _read(path,limit=capture.MAX_BYTES):
    need(path.is_file() and not path.is_symlink() and path.stat().st_size<=limit,
         'PRIVATE_SOURCE_FILE_UNSAFE')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        raw=stream.read(limit+1)
    need(0<len(raw)<=limit,'PRIVATE_SOURCE_FILE_BOUND')
    return raw


def _write_snapshot(path,value):
    raw=model.canonical(value)+b'\n'
    need(len(raw)<=MAX_FILE and not path.exists() and not path.is_symlink(),
         'IMMUTABLE_SNAPSHOT_OUTPUT_REQUIRED')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    need(_read(path,MAX_FILE)==raw,'SNAPSHOT_READBACK_FAILED')


class _Session:
    """One shared stop circuit and immutable byte receipts for this run."""
    def __init__(self,root,day,fetch,clock):
        self.raw=root/'raw'
        self.receipt_dir=root/'receipts'
        self.day,self.fetch,self.clock=day,fetch,clock
        self.receipts={}
        self.pages={}
        self.cutoffs={}
        self.requests=0
        self.last_observed=None
        self.stopped=None
        self.marker=self.raw/'provider-denial-stop.json'
        if self.marker.exists() or self.marker.is_symlink():
            previous=json.loads(_read(self.marker))
            need(type(previous) is dict and set(previous)=={
                'schema','state','day_jst','recorded_at'} and
                previous['schema']=='RACE_AI_KEIRIN_PROVIDER_DENIAL_STOP_V1' and
                previous['state']=='HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP',
                'PROVIDER_STOP_UNTRUSTED')
            # A restored denial never becomes permission to try again tomorrow.
            model.when(previous['recorded_at'])
            self.stopped=DENIED

    def observed_clock(self):
        return self.last_observed or _now(self.clock)

    def __call__(self,url):
        if self.stopped:
            raise capture.SourceCaptureError(self.stopped)
        parsed=urlsplit(url)
        need(parsed.scheme=='https' and parsed.hostname in {
            'keirin.kdreams.jp','keirin.netkeiba.com'} and
            parsed.username is None and parsed.password is None and
            parsed.port in (None,443),'APPROVED_PUBLIC_SOURCE_REQUIRED')
        if url in self.cutoffs and (self.cutoffs[url]-_now(self.clock)).total_seconds()<65:
            raise capture.SourceCaptureError('NOTE_PUBLISHED_CUTOFF_TOO_CLOSE')
        self.requests+=1
        try:
            raw=self.fetch(url)
        except (ValueError,OSError) as error:
            self.last_observed=_now(self.clock)
            self.stopped=(str(error) if isinstance(error,capture.SourceCaptureError) and
                          str(error) in STOPS else 'PUBLIC_PROVIDER_UNAVAILABLE_STOP')
            # Provider/library error text is never a public status identifier.
            raise capture.SourceCaptureError(self.stopped) from None
        need(type(raw) is bytes and 0<len(raw)<=capture.MAX_BYTES,'SOURCE_BYTES_BOUND')
        self.last_observed=_now(self.clock)
        digest=sha256(raw).hexdigest()
        receipt=dict(url=url,bytes_sha256=digest,bytes=len(raw),status=200,
                     captured_at=self.last_observed.isoformat())
        capture._write_once(self.raw/(digest+'.html'),raw)
        receipt_bytes=model.canonical(receipt)+b'\n'
        capture._write_once(self.receipt_dir/(sha256(receipt_bytes).hexdigest()+'.json'),receipt_bytes)
        self.pages[url]=raw
        self.receipts[url]=receipt
        return raw

    def finish(self):
        if self.stopped==DENIED and not self.marker.exists():
            capture._write_once(self.marker,model.canonical(dict(
                schema='RACE_AI_KEIRIN_PROVIDER_DENIAL_STOP_V1',
                state='HOLD_PROVIDER_DENIED_OR_RATE_LIMITED_STOP',day_jst=self.day,
                recorded_at=self.observed_clock().isoformat()))+b'\n')


def _discover(session,day):
    """Inspect every published meeting HREF; this is a partial source roster."""
    parsed=date.fromisoformat(day)
    calendar=links.CALENDAR.format(year=parsed.year,month=parsed.month,day=parsed.day)
    cards=links.linked_racecards(session(calendar),base_url=calendar,day=day)
    need(cards,'NO_PUBLISHED_MEETING_LINKS')
    rows=[];meetings={};attempted=0
    for venue,url in sorted(cards.items()):
        if session.stopped:
            break
        attempted+=1
        try:
            raw=session(url)
        except capture.SourceCaptureError:
            break
        details=links.linked_details(raw,base_url=url,day=day,venue=venue)
        hints=links.linked_cutoff_hints(raw,base_url=url,day=day,venue=venue)
        if details:
            meetings[venue]=url
        for race_id,kdreams_url in sorted(details.items()):
            net='https://keirin.netkeiba.com/race/entry/?race_id='+race_id
            capture._allow_url(net,'net',race_id)
            capture._allow_url(kdreams_url,'kd',race_id)
            rows.append(dict(race_id=race_id,netkeirin_url=net,
                             kdreams_url=kdreams_url,cutoff_hint=hints.get(race_id)))
    manifest=dict(schema=capture.SCHEMA,day_jst=day,races=rows,
                  source_use_scope='OWNER_PERSONAL_RESEARCH_ONLY')
    capture.manifest_check(manifest,registered_ids=[r['race_id'] for r in rows])
    return manifest,meetings,len(cards),attempted


def _text(node):
    return ' '.join(node.get_text(' ',strip=True).split()) if node is not None else ''


def _number(value):
    try:
        raw=normalize('NFKC',value).replace('%','').strip()
        number=float(raw) if '.' in raw else int(raw)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError,OverflowError):
        return None


def _lines(node):
    wrap=node.select_one('div.line_position_inner') or node.select_one('div.line_position')
    groups,group,roles=[],[],{}
    if wrap:
        for span in wrap.find_all('span',recursive=False):
            if 'space' in span.get('class',[]):
                if group:
                    groups.append(group)
                    group=[]
            else:
                children=span.find_all('span',recursive=False)
                if children and re.fullmatch('[1-9]',_text(children[0])):
                    car=int(_text(children[0]));group.append(car)
                    if len(children)>1:
                        roles[str(car)]=_text(children[1])
        if group:
            groups.append(group)
    return groups,roles


def display_race(snapshot,raw,*,meeting_url,meeting_raw,raw_path):
    """Published Kdreams display values; netkeirin supplies H separately."""
    rid=snapshot['race_id'];receipt=snapshot['cutoff_source']
    need(sha256(raw).hexdigest()==receipt['bytes_sha256'],'DISPLAY_SOURCE_SHA_MISMATCH')
    _,body,_,soup=normalize_pages._page(raw)
    need(soup is not None,'DISPLAY_DOM_REQUIRED')
    normalize_pages._check_canonical(soup,receipt['url'])
    tables=soup.select('table.racecard_table')
    need(len(tables)>=3,'KDREAMS_DISPLAY_TABLES_MISSING')
    riders=[]
    keys=('class','style','gear','score','S','B','nige','makuri','sashi','mark',
          'wins','seconds','thirds','unplaced','win_rate','top2_rate','top3_rate')
    net={r['car']:r for r in snapshot['riders']}
    net_receipt=next(p for p in snapshot['source_pages'] if p['kind']=='RACECARD')
    for tr in tables[0].select('tr'):
        number=_number(_text(tr.select_one('td.num')))
        if type(number) is not int:
            continue
        cells=tr.find_all('td',recursive=False);rider=tr.select_one('td.rider')
        need(rider in cells and number in net,'KDREAMS_DISPLAY_ROSTER_CONFLICT')
        parts=list(rider.stripped_strings)
        metadata=''.join(parts[1:]).split('/')
        values=[_text(c) for c in cells[cells.index(rider)+1:]]
        need(parts and len(metadata)>=3 and len(values)>=17,'KDREAMS_DISPLAY_ROW_INCOMPLETE')
        row=dict(number=number,name=parts[0].replace(' ',''),prefecture=metadata[0].replace('\u3000',''),
                 age=_number(metadata[1]),term=_number(metadata[2]),H=net[number]['h_count'],
                 source_tip=_text(tr.select_one('td.tip')),
                 field_sources={'statistics':receipt,'comment':receipt,'H':net_receipt})
        row.update({key:value if index<2 else _number(value)
                    for index,(key,value) in enumerate(zip(keys,values))})
        riders.append(row)
    need(len(riders)==len(net) and {r['number'] for r in riders}==set(net),
         'KDREAMS_DISPLAY_ROSTER_CONFLICT')
    by_car={r['number']:r for r in riders}
    for tr in tables[1].select('tr'):
        car=_number(_text(tr.select_one('td.num')))
        if car in by_car:
            by_car[car]['comment']=_text(tr.select_one('td.comment'))
            by_car[car]['previous_race_result']=_text(tr.select_one('td.last_result'))
    for index,key,offset in ((2,'recent_meets',2),(4,'same_track_length_year',5),
                             (5,'venue_last_5years',5)):
        if len(tables)<=index:
            continue
        for tr in tables[index].select('tr'):
            car=_number(_text(tr.select_one('td.num')))
            cells=tr.find_all('td',recursive=False);rider=tr.select_one('td.rider')
            if car in by_car and rider in cells:
                values=[_text(c) for c in cells[cells.index(rider)+offset:]]
                by_car[car][key]=values if index==2 else [_number(v) for v in values]
    differences={}
    for row in riders:
        other=net[row['number']]
        compared=(('score',other['competition_points']),('B',other['b_count']),
                  ('win_rate',round(other['recent_form_score']*100,8)))
        changed={key:{'kdreams':row[key],'netkeirin':value}
                 for key,value in compared if row[key]!=value}
        if changed:
            differences[str(row['number'])]=changed
    lines,roles=_lines(soup)
    title=_text(soup.select_one('div.racecard_header h2.title > span.status'))
    headline=_text(soup.select_one('h1.raceinfo_headline'))
    venue=re.match(r'^(.{1,20}?)競輪',headline)
    qualification=_text(soup.select_one('div.racecard_header dl.condition > dd'))
    start=None
    for dt in soup.select('div.racecard_header dl.time > dt'):
        if _text(dt) in ('発走','発走予定'):
            dd=dt.find_next_sibling()
            value=_text(dd) if dd is not None and dd.name=='dd' else ''
            if re.fullmatch(r'(?:[01]?[0-9]|2[0-3]):[0-5][0-9]',value):
                start=value
    _,_,_,meeting=normalize_pages._page(meeting_raw)
    listed=None
    if meeting:
        for li in meeting.select('ul.racecard_list > li'):
            a=li.select_one('p.race > a[href]')
            if a is not None and a['href']==receipt['url']:
                listed=li;break
    listed_lines,listed_roles=_lines(listed) if listed else ([],{})
    odds={}
    for table in soup.select('table.bt5'):
        first=_number(_text(table.select_one('span.number')))
        rows=table.select(':scope > tr, :scope > tbody > tr')
        if first is None or len(rows)<4:
            continue
        seconds=[_number(_text(t)) for t in rows[1].select('th[class]')]
        for tr in rows[3:]:
            third=_number(_text(tr.select_one('th[class]')))
            for second,td in zip(seconds,tr.find_all('td',recursive=False)):
                value=_number(_text(td))
                if None not in (second,third,value) and len({first,second,third})==3:
                    odds[f'{first}-{second}-{third}']=value
    day=rid[:4]+'-'+rid[4:6]+'-'+rid[6:8]
    stamps=re.findall(re.escape(day.replace('-','/'))+r'\s+\d{2}:\d{2}現在',body)
    return dict(race_id=rid,date=day,venue=venue.group(1) if venue else None,
        venue_code=rid[8:10],venue_slug=urlsplit(receipt['url']).path.split('/')[1],
        race_no=int(rid[-2:]),race_title=title,start_time=start,
        deadline_time=snapshot['published_cutoff_at'][11:16],
        deadline_source='楽天Kドリームス掲載締切',source_url=receipt['url'],
        list_source_url=meeting_url,detail_id=urlsplit(receipt['url']).path.rstrip('/').split('/')[-1],
        riders=riders,rider_count=len(riders),lines=lines,roles=roles,
        listed_lines=listed_lines,listed_roles=listed_roles,
        line_type='individual_positions' if snapshot['competition']=='GIRLS' else 'predicted_lines',
        qualification=qualification,qualification_kind=('prize_schedule' if '円' in qualification else
            'advancement_conditions' if qualification else 'UNKNOWN'),
        source_editorial=_text(soup.select_one('p.racereview')),
        fetched_at=receipt['captured_at'],source_sha256=receipt['bytes_sha256'],raw_path=str(raw_path),
        H_source=net_receipt,source_differences=differences,
        source_data_period='掲載媒体の直近4ヶ月統計',odds_3t=odds,
        odds_timestamp=stamps[0] if len(set(stamps))==1 else None,
        odds_scope='掲載媒体内の取得時点オッズ。全市場・締切直前の値は未検証。',
        bank=None,weather=None,missing_fields=['bank','race_time_weather'],no_today_results_used=True)


def _day_coverage(manifest,*,already,captured,reasons,stopped,clock):
    """Account for observed IDs without treating acquisition as settlement.

    This summary stays inside the encrypted manifest. Prior saved research
    inputs remain available when a refresh fails or its cutoff has passed.
    The source roster is observed, not independently verified nationwide.
    """
    fresh=set(captured);available=set(already)|fresh;rows=[]
    for race in manifest['races']:
        race_id=race['race_id']
        reason=reasons.get(race_id,'NOT_ATTEMPTED_THIS_CYCLE')
        if reason=='NOT_ATTEMPTED_THIS_CYCLE' and stopped:
            reason='HOLD_'+_safe_reason(stopped)
        status=('available' if race_id in available else
                'held' if reason.startswith('HOLD_') else 'missing')
        rows.append(dict(race_id=race_id,published_cutoff_at=race['cutoff_hint'],
            input_status=status,reason=reason,captured_this_cycle=race_id in fresh))
    counts=Counter(row['input_status'] for row in rows)
    return dict(schema='RACE_AI_KEIRIN_NOTE_DAY_COVERAGE_V1',
        day_jst=manifest['day_jst'],observed_at=_now(clock).isoformat(),
        national_universe_verified=False,formal_model_admission=False,
        counts=dict(observed=len(rows),input_available=counts['available'],
                    missing=counts['missing'],held=counts['held']),races=rows)


def _selected_class_records(report,*,manifest,session,cards,clock):
    """Recheck saved pairs locally; no new fetch, retry or shared-module patch."""
    by_id={row['race_id']:row for row in manifest['races']};records=[]
    for record in report['records']:
        if record['state'] not in {'PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES',
                'HOLD_KDREAMS_RACE_CLASS_NOT_IN_SOURCE'}:
            records.append(record);continue
        rid=record['race_id'];item=by_id[rid]
        try:
            net=session.receipts[item['netkeirin_url']];kd=session.receipts[item['kdreams_url']]
            net_raw=session.pages[item['netkeirin_url']];kd_raw=session.pages[item['kdreams_url']]
            need(sha256(net_raw).hexdigest()==net['bytes_sha256'] and
                 sha256(kd_raw).hexdigest()==kd['bytes_sha256'],'SELECTED_CLASS_SOURCE_SHA_CHANGED')
            normalized=normalize_pages.merge_pre_race_pages(race_id=rid,
                netkeirin_raw=net_raw,netkeirin_url=net['url'],netkeirin_captured_at=net['captured_at'],
                kdreams_raw=kd_raw,kdreams_url=kd['url'],kdreams_captured_at=kd['captured_at'],
                created_at=_now(clock).isoformat(),allow_selected_netkeirin_class=True)
            raw=model.canonical(normalized['source_packet'])+b'\n'
            capture._write_once(cards/(rid+'.json'),raw)
            row=dict(race_id=rid,state='PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES',
                     packet_sha256=sha256(raw).hexdigest())
            if 'class_field_source' in normalized:
                row['class_field_source']=normalized['class_field_source']
            records.append(row)
        except (ValueError,KeyError,TypeError,OSError) as error:
            records.append(dict(race_id=rid,state='HOLD_'+_safe_reason(error)))
    counts=Counter(row['state'] for row in records)
    return dict(report,records=records,states=dict(sorted(counts.items())),
                normalized_private_cards=counts['PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES'])


def collect_day(*,day_jst,private_root,fetch=None,clock=None,already_captured_ids=(),
                priority_captured_ids=(),model_source_commit=None):
    """Return safe_report plus private Site-root handles for owner encryption.

    A fresh private root is required for each immutable dated snapshot. Prior
    coverage IDs are supplied by the existing durable owner index, not guessed.
    """
    need(type(day_jst) is str and date.fromisoformat(day_jst).isoformat()==day_jst,'DAY_INVALID')
    clock=clock or (lambda:datetime.now(UTC));fetch=fetch or capture.fetch_once
    need(callable(clock) and callable(fetch),'FETCH_AND_CLOCK_REQUIRED')
    need(_now(clock).astimezone(JST).date().isoformat()==day_jst,'CURRENT_JST_DAY_REQUIRED')
    need(model_source_commit is None or (type(model_source_commit) is str and
         re.fullmatch('[0-9a-f]{40}',model_source_commit)),'MODEL_SOURCE_COMMIT_INVALID')
    previous=[]
    for values in (already_captured_ids,priority_captured_ids):
        need(type(values) in (tuple,list,set,frozenset) and all(type(r) is str and
             model.VENUE.fullmatch(r) for r in values),'PRIOR_COVERAGE_IDS_INVALID')
        previous.append(set(values))
    already,priority_done=previous
    root=_private_root(private_root)
    for label in ('raw','receipts','cards','data','data/'+day_jst):
        folder=root/label;folder.mkdir(mode=0o700,exist_ok=True)
        capture.private_dir(folder)
    dated=root/'data'/day_jst
    paths=[dated/name for name in ('races.json','reference_AB.json','manifest.json')]
    need(not any(p.exists() or p.is_symlink() for p in paths),'DATED_SNAPSHOT_ALREADY_EXISTS')
    session=_Session(root,day_jst,fetch,clock)
    counts=Counter();states=Counter();reasons={};races=[];references=[];captured=[];priority_captured=[]
    manifest=dict(schema=capture.SCHEMA,day_jst=day_jst,races=[],
                  source_use_scope='OWNER_PERSONAL_RESEARCH_ONLY')
    try:
        manifest,meetings,linked_meetings,meeting_attempts=_discover(session,day_jst)
        counts['observed_races']=len(manifest['races'])
        counts['observed_venues']=len(meetings)
        counts['published_meeting_links']=linked_meetings
        counts['meeting_pages_attempted']=meeting_attempts
        priority=[];future=[]
        for row in manifest['races']:
            if row['cutoff_hint'] is None:
                reasons[row['race_id']]='HOLD_PUBLISHED_CUTOFF_UNAVAILABLE'
                counts['missing_cutoff_hint_races']+=1;continue
            remaining=(model.when(row['cutoff_hint'])-_now(clock)).total_seconds()
            if remaining<=0:
                reasons[row['race_id']]='PAST_PUBLISHED_CUTOFF'
                counts['past_cutoff_races']+=1;continue
            if remaining<65:
                reasons[row['race_id']]='HOLD_PUBLISHED_CUTOFF_TOO_CLOSE'
                counts['too_close_races']+=1;continue
            window=600<=remaining<=900
            if row['race_id'] in already and (not window or row['race_id'] in priority_done):
                reasons[row['race_id']]='PREVIOUSLY_CAPTURED'
                counts['already_captured_races_skipped']+=1;continue
            (priority if window else future).append(row)
            session.cutoffs[row['netkeirin_url']]=model.when(row['cutoff_hint'])
            session.cutoffs[row['kdreams_url']]=model.when(row['cutoff_hint'])
        counts['selected_races']=len(priority)+len(future)
        counts['selected_priority_races']=len(priority)
        for phase in (priority,future):
            if not phase or session.stopped:
                continue
            selected=dict(manifest,races=phase)
            report=capture.capture_cycle(day_manifest=selected,
                registered_ids=[r['race_id'] for r in manifest['races']],
                private_cards_dir=root/'cards',private_raw_dir=root/'raw',
                fetch=session,clock=session.observed_clock,max_races=None)
            report=_selected_class_records(report,manifest=selected,session=session,
                                           cards=root/'cards',clock=clock)
            states.update(report['states'])
            for row in report['records']:
                reasons[row['race_id']]=row['state']
                if row['state']!='PRIVATE_CARD_NORMALIZED_FROM_TWO_PUBLIC_SOURCES':
                    continue
                race_id=row['race_id']
                try:
                    raw_card=_read(root/'cards'/(race_id+'.json'))
                    need(sha256(raw_card).hexdigest()==row['packet_sha256'],'PRIVATE_CARD_SHA_CHANGED')
                    snap=json.loads(raw_card)
                    receipt=snap['cutoff_source'];source=root/'raw'/(receipt['bytes_sha256']+'.html')
                    raw=_read(source)
                    for page in snap['source_pages']:
                        need(sha256(_read(root/'raw'/(page['bytes_sha256']+'.html'))).hexdigest()==
                             page['bytes_sha256'],'PRIVATE_RAW_SHA_CHANGED')
                    meeting_url=meetings[race_id[8:10]]
                    display=display_race(snap,raw,meeting_url=meeting_url,
                        meeting_raw=session.pages[meeting_url],raw_path=source)
                    if 'class_field_source' in row:
                        display['field_sources']={'competition':row['class_field_source']}
                    generated_at=_now(clock).isoformat()
                    prediction=model.generate_A_B(snap,generated_at=generated_at,max_tickets=12)
                    races.append(display)
                    references.append(dict(input=snap,output=prediction,
                        status='OWNER_RESEARCH_REFERENCE_NOT_FORMAL_SEALED_ORIGINAL',
                        independent_runner_readback=False,model_source_commit=model_source_commit,
                        model_source_sha256=sha256(Path(model.__file__).read_bytes()).hexdigest()))
                    if 'class_field_source' in row:
                        references[-1]['class_field_source']=row['class_field_source']
                    captured.append(race_id)
                    reasons[race_id]='RESEARCH_INPUT_CAPTURED'
                    source_remaining=(model.when(snap['published_cutoff_at'])-
                                      model.when(snap['as_of'])).total_seconds()
                    generation_remaining=(model.when(snap['published_cutoff_at'])-
                                          model.when(generated_at)).total_seconds()
                    if 600<=source_remaining<=900 and 600<=generation_remaining<=900:
                        priority_captured.append(race_id)
                except (ValueError,KeyError,TypeError,OSError) as error:
                    reasons[race_id]='HOLD_'+_safe_reason(error)
                    states[reasons[race_id]]+=1
    except (ValueError,KeyError,TypeError,OSError) as error:
        states['HOLD_'+_safe_reason(error)]+=1
    finally:
        session.finish()
    safe=dict(schema=SCHEMA,day_jst=day_jst,
        **{key:counts[key] for key in ('observed_races','observed_venues','published_meeting_links',
            'meeting_pages_attempted','past_cutoff_races',
            'too_close_races','missing_cutoff_hint_races','already_captured_races_skipped',
            'selected_races','selected_priority_races')},
        captured_race_ids=captured,priority_window_race_ids=priority_captured,
        captured_races=len(captured),research_references_generated=len(references),
        missing_source_races=counts['selected_races']-len(captured),
        public_page_requests=session.requests,
        provider_denied=session.stopped==DENIED,states=dict(sorted(states.items())),
        national_universe_verified=False,formal_model_admission=False,
        actual_four_model_forecast_saved=False,production_weight_switch=False,
        no_results_used_as_pre_race_inputs=True,authored_forecasts_created=0,wagers_placed=False)
    _write_snapshot(paths[0],dict(date=day_jst,timezone='Asia/Tokyo',races=races,
        retrieved_race_count=len(races),observed_race_count=counts['observed_races'],
        observed_venue_count=counts['observed_venues'],national_universe_verified=False))
    _write_snapshot(paths[1],references)
    _write_snapshot(paths[2],dict(schema=SCHEMA,day_jst=day_jst,
        source_manifest=manifest,source_receipts=list(session.receipts.values()),safe_report=safe,
        daily_coverage=_day_coverage(manifest,already=already,captured=captured,
            reasons=reasons,stopped=session.stopped,clock=clock)))
    return dict(safe_report=safe,site_root=str(root),dated_dir=str(dated),
                races_path=str(paths[0]),reference_path=str(paths[1]),manifest_path=str(paths[2]))


def main(argv=None,*,fetch=None,clock=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day',required=True)
    parser.add_argument('--private-root',required=True)
    args=parser.parse_args(argv)
    try:
        result=collect_day(day_jst=args.day,private_root=args.private_root,fetch=fetch,clock=clock)
        print(json.dumps({key:value for key,value in result['safe_report'].items()
                          if key not in ('captured_race_ids','priority_window_race_ids')},sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError):
        print('{"state":"HOLD_OWNER_PRIVATE_NOTE_INPUT_COLLECTION"}')
        return 2


if __name__=='__main__':
    raise SystemExit(main())
