"""Published schedule metadata from an already owner-admitted S16 journal.

No acquisition, key lookup, native input, forecast, cache or dispatch grant.
The caller authenticates the exact journal and normal S16 result first.
"""
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlsplit

from .actions_contract import digest
from . import all_existing_model_official_continuation as continuation
from . import all_existing_model_prior_static_cache as originals
from . import keirin_official_sparse_adapter as keirin
from .manual_official_capture import _url
from .official_future_source_packet import _no_dynamic_replay

SCHEMA='RACE_AI_KEIRIN_FUTURE_SELECTOR_METADATA_V1'
SCHEMA_V2='RACE_AI_KEIRIN_FUTURE_SELECTOR_METADATA_V2'
REASONS=frozenset(('NO_INITIAL_LIST','AMBIGUOUS_INITIAL_LIST','NOT_CURRENT_EVENT_DAY',
                  'MEETING_CANCELLED','NO_PUBLISHED_AFTERNOON_RACE'))
BASE={'schema','state','selector_only','fresh_future_input','fresh_post_f30_capture_required',
      'source_journal','journal_cipher_sha256','journal_payload_sha256','checked_at'}
SOURCE={'sequence','url','method','status','resource_type','content_type','byte_count','source_sha256',
        'http_metadata_sha256','request_body_sha256','request_started_at','headers_received_at',
        'response_received_at','body_captured_at','top_sequence','top_body_sha256',
        'original_index_sha256','returned_index_sha256','ui_event_sha256'}
HASH=re.compile(r'[a-f0-9]{64}\Z')
CLOCK=re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z')


def need(ok,reason):
    if not ok:raise ValueError('OFFICIAL_PREPARE_SELECTOR_'+reason)


def _path(url):
    need(_url(url)[0]=='keirin','SOURCE_HOST')
    parts=urlsplit(url);need(not parts.query and not parts.fragment and parts.port is None,'LITERAL_UI_URL')
    return parts


class _Inputs(HTMLParser):
    def __init__(self,raw):
        super().__init__();self.values={};self.feed(raw.decode('utf-8','strict'));self.close()
    def handle_starttag(self,tag,attrs):
        if tag!='input':return
        fields=dict(attrs);name=fields.get('id')
        if name not in ('hhSelK','hhSelJ'):return
        need(len(fields)==len(attrs) and name not in self.values,'HIDDEN_IDENTITY')
        self.values[name]=fields.get('value')


def _base(evidence,now):
    return dict(schema=SCHEMA,state='selector_absent',selector_only=True,fresh_future_input=False,
        fresh_post_f30_capture_required=True,source_journal=dict(evidence['pin']),
        journal_cipher_sha256=evidence['cipher_sha256'],journal_payload_sha256=evidence['payload_sha256'],
        checked_at=now.isoformat())


def validate_metadata(value):
    from scripts.all_existing_model_official_result_collect import _pins
    if type(value) is dict and value.get('schema')==SCHEMA_V2:
        alternatives=value.get('published_alternatives')
        need(value.get('state')=='published_selector' and type(alternatives) is list and
            0<=len(alternatives)<=11,'ALTERNATIVE_BOUND')
        primary=dict(value);primary['schema']=SCHEMA;primary.pop('published_alternatives')
        validate_metadata(primary);case=primary['case']
        seen={case['race_no']};previous=(keirin._clock(case['cutoff_at']),case['race_no'])
        for item in alternatives:
            need(type(item) is dict and {'case'}<=set(item)<={'case','published_start_at'},'ALTERNATIVE_FIELDS')
            row=dict(primary,case=item['case']);row.pop('published_start_at',None)
            if 'published_start_at' in item:row['published_start_at']=item['published_start_at']
            validate_metadata(row);other=row['case']
            need(all(other.get(k)==case.get(k) for k in ('sport','expected_date','venue','ui_entry_url','ui_venue_name')) and
                other['race_no'] not in seen,'ALTERNATIVE_CONTEXT')
            order=(keirin._clock(other['cutoff_at']),other['race_no'])
            need(previous<order,'ALTERNATIVE_ORDER');seen.add(other['race_no']);previous=order
        return value
    need(type(value) is dict and value.get('schema')==SCHEMA and value.get('selector_only') is True and
        value.get('fresh_future_input') is False and value.get('fresh_post_f30_capture_required') is True,'OUTPUT_FLAGS')
    need(value.get('state') in ('selector_absent','published_selector'),'OUTPUT_STATE')
    absent=value['state']=='selector_absent'
    need(set(value)==BASE|({'reason'} if absent else {'case','source'}) or
        not absent and set(value)==BASE|{'case','source','published_start_at'},'OUTPUT_FIELDS')
    _pins([value['source_journal']])
    need(all(type(value[k]) is str and HASH.fullmatch(value[k]) for k in
        ('journal_cipher_sha256','journal_payload_sha256')),'OUTPUT_HASH')
    now=keirin._clock(value['checked_at'])
    if absent:
        need(value['reason'] in REASONS,'OUTPUT_REASON');return value
    case=value['case'];source=value['source']
    fields={'sport','race_id','expected_date','venue','race_no','cutoff_at','ui_entry_url'}
    need(type(case) is dict and fields<=set(case)<=fields|{'ui_venue_name'} and case['sport']=='keirin' and
        type(case['venue']) is str and re.fullmatch(r'keirin-jyo-[0-9]{2}',case['venue']) and
        type(case['race_no']) is int and 1<=case['race_no']<=12 and
        case['race_id']==f"keirin:{case['expected_date']}:{case['venue']}:{case['race_no']}",'OUTPUT_CASE')
    day=date.fromisoformat(case['expected_date']);cutoff=keirin._clock(case['cutoff_at'])
    need(cutoff.astimezone(keirin.JST).date()==day and cutoff.utcoffset()==timedelta(hours=9) and
        cutoff.astimezone(keirin.JST).hour>=15 and now+timedelta(seconds=600)<cutoff and
        _path(case['ui_entry_url']).path=='/pc/top','OUTPUT_CASE_CLOCK')
    if 'ui_venue_name' in case:
        name=case['ui_venue_name'];need(type(name) is str and 0<len(name)<=80 and name.strip()==name and
            not re.search(r'[<>\r\n]',name),'OUTPUT_VENUE_NAME')
    need(type(source) is dict and set(source)==SOURCE and source['method']=='POST' and source['status']==200 and
        source['resource_type']=='document' and _path(source['url']).path=='/pc/racelist' and
        _path(source['url']).hostname==_path(case['ui_entry_url']).hostname and
        type(source['sequence']) is int and type(source['top_sequence']) is int and
        1<=source['top_sequence']<source['sequence']<=16 and type(source['byte_count']) is int and
        0<source['byte_count']<=keirin.MAX_BYTES and type(source['content_type']) is str and
        source['content_type'].lower().startswith('text/html'),'OUTPUT_SOURCE')
    need(all(type(source[k]) is str and HASH.fullmatch(source[k]) for k in SOURCE if k.endswith('sha256')),'OUTPUT_SOURCE_HASH')
    clocks=[keirin._clock(source[k]) for k in ('request_started_at','headers_received_at','response_received_at','body_captured_at')]
    need(clocks==sorted(clocks) and clocks[-1]<=now and all(t.astimezone(keirin.JST).date()==day for t in clocks),'OUTPUT_SOURCE_CLOCK')
    if 'published_start_at' in value:
        start=keirin._clock(value['published_start_at']);need(cutoff<start and start.astimezone(keirin.JST).date()==day,'OUTPUT_START')
    return value


def selector_metadata(journal,evidence,*,probe_case,now,include_alternatives=False):
    """Return only a selector, preserving every original wire and source clock."""
    need(type(include_alternatives) is bool,'ALTERNATIVE_OPT_IN');now=keirin._clock(now)
    need(evidence.get('payload_sha256')==digest(journal),'ADMITTED_JOURNAL_BINDING')
    continuation.probe.no_known_denial(journal)
    continuation._complete(journal,evidence['artifact_metadata'],now,required=True,expected_limit=16)
    _no_dynamic_replay(journal)
    result=_base(evidence,now)
    def absent(reason):
        result['reason']=reason;return validate_metadata(result)
    # Legacy authored/retained sources without a normal list remain usable for
    # teacher-plan preparation; they supply no future schedule selector.
    if not any(e.get('method')=='POST' and e.get('resource_type')=='document'
               for e in journal['browser_index']['responses']):return absent('NO_INITIAL_LIST')
    index,files,_=originals.verified_browser_wire(journal,evidence['artifact_metadata'],now=now,strict_http=True)
    need(all(_url(e['url'])[0]=='keirin' for e in index['responses']),'SOURCE_SCOPE')
    lists=[e for e in index['responses'] if e['method']=='POST' and e['resource_type']=='document' and
           _path(e['url']).path=='/pc/racelist']
    if not lists:return absent('NO_INITIAL_LIST')
    entry=min(lists,key=lambda e:e['sequence']);parts=_path(entry['url'])
    tops=[e for e in index['responses'] if e['sequence']<entry['sequence'] and e['method']=='GET' and
          e['resource_type']=='document' and _path(e['url']).path=='/pc/top' and _path(e['url']).hostname==parts.hostname]
    if len(tops)!=1:return absent('AMBIGUOUS_INITIAL_LIST')
    top=tops[0];next_list=min((e['sequence'] for e in lists if e['sequence']>entry['sequence']),default=17)
    segment=index['ledger'][index['ledger'].index(entry)+1:]
    events=[e for e in segment if e.get('event')=='NORMAL_SEMANTIC_UI_CLICK' and
        keirin._text(e.get('label',''))=='出走表一覧' and e.get('before')==top['url'] and e.get('after')==entry['url']]
    upper=next((keirin._clock(e['request_started_at']) for e in lists if e['sequence']==next_list),keirin._clock(index['completed_at']))
    if len(events)!=1 or not (keirin._clock(top['body_captured_at'])<=keirin._clock(entry['request_started_at'])<=
        keirin._clock(events[0]['at'])<upper and keirin._clock(entry['body_captured_at'])<upper):
        return absent('AMBIGUOUS_INITIAL_LIST')
    request=files[entry['request_body_file']]
    pairs=parse_qsl(request.decode('utf-8','strict'),keep_blank_values=True,max_num_fields=3)
    need(len(pairs)==2 and len(dict(pairs))==2 and set(dict(pairs))=={'disp','encp'} and
        dict(pairs)['disp']=='PJ0305' and re.fullmatch(r'[A-Za-z0-9_=-]{1,512}',dict(pairs)['encp']) and
        entry['request_content_type'].lower().startswith('application/x-www-form-urlencoded'),'PUBLISHED_LIST_REQUEST')
    raw=files[entry['body_file']];data=keirin._embedded(raw,('PC0201','PJ0305'))
    selected=data['PC0201'].get('C0201data');listing=data['PJ0305']
    need(type(selected) is dict,'LIST_IDENTITY')
    day=selected.get('selKaisai');venue=selected.get('selKjyoCd')
    need(type(day) is str and re.fullmatch('[0-9]{8}',day) and day==listing.get('kaisaihi') and
        type(venue) is str and re.fullmatch('[0-9]{2}',venue) and int(venue)>0 and venue==listing.get('keirinCd'),'LIST_IDENTITY')
    hidden=_Inputs(raw).values
    need(all(hidden[k]==v for k,v in (('hhSelK',day),('hhSelJ',venue)) if k in hidden),'HIDDEN_IDENTITY')
    event_day=date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:])
    if event_day.isoformat()!=journal.get('execution_day') or event_day!=now.astimezone(keirin.JST).date() or any(
        keirin._clock(entry[k]).astimezone(keirin.JST).date()!=event_day for k in ('request_started_at','body_captured_at')):
        return absent('NOT_CURRENT_EVENT_DAY')
    if selected.get('flgSectionCancel') not in (None,False,0):return absent('MEETING_CANCELLED')
    rows=listing.get('rInfo');need(type(rows) is list and len(rows)<=12 and all(type(r) is dict for r in rows),'RACE_LIST')
    seen=set();choices=[]
    for row in rows:
        number=keirin._integer(row.get('raceNo'),1,12);need(number not in seen,'DUPLICATE_RACE');seen.add(number)
        text=row.get('denTime');start=row.get('stTime')
        if text in (None,''):continue
        need(type(text) is str and CLOCK.fullmatch(text) and (start in (None,'') or type(start) is str and CLOCK.fullmatch(start)),'PUBLISHED_CLOCK')
        cutoff=datetime.combine(event_day,datetime.strptime(text,'%H:%M').time(),keirin.JST)
        started=None if start in (None,'') else datetime.combine(event_day,datetime.strptime(start,'%H:%M').time(),keirin.JST)
        need(started is None or cutoff<started,'PUBLISHED_CLOCK')
        if row.get('flgRaceCancel') not in (None,False,0) or (str(selected.get('selRaceNo'))==str(number) and
            selected.get('flgRaceCancel') not in (None,False,0)):continue
        if cutoff.hour>=15 and now+timedelta(seconds=600)<cutoff:choices.append((cutoff,venue,number,started))
    if not choices:return absent('NO_PUBLISHED_AFTERNOON_RACE')
    cutoff,venue,number,started=min(choices,key=lambda v:v[:3])
    case=dict(sport='keirin',race_id=f'keirin:{event_day.isoformat()}:keirin-jyo-{venue}:{number}',
        expected_date=event_day.isoformat(),venue='keirin-jyo-'+venue,race_no=number,cutoff_at=cutoff.isoformat(),ui_entry_url=top['url'])
    if probe_case['race_id'].split(':')[2]=='keirin-jyo-'+venue and probe_case.get('route',{}).get('ui_venue_name'):
        case['ui_venue_name']=probe_case['route']['ui_venue_name']
    source={k:entry[k] for k in ('sequence','method','status','resource_type','content_type','byte_count','source_sha256',
        'request_body_sha256','request_started_at','headers_received_at','response_received_at','body_captured_at')}
    source.update(url=entry['url'],http_metadata_sha256=sha256(files[entry['metadata_file']]).hexdigest(),
        top_sequence=top['sequence'],top_body_sha256=top['source_sha256'],original_index_sha256=sha256(files['capture-index.json']).hexdigest(),
        returned_index_sha256=digest(index),ui_event_sha256=digest(events[0]))
    result.update(state='published_selector',case=case,source=source)
    if started is not None:result['published_start_at']=started.isoformat()
    if include_alternatives:
        alternatives=[]
        for later,_,number,started in sorted(choices,key=lambda v:v[:3])[1:]:
            alternative=dict(case,race_id=f'keirin:{event_day.isoformat()}:keirin-jyo-{venue}:{number}',
                race_no=number,cutoff_at=later.isoformat())
            item=dict(case=alternative)
            if started is not None:item['published_start_at']=started.isoformat()
            alternatives.append(item)
        result.update(schema=SCHEMA_V2,published_alternatives=alternatives)
    return validate_metadata(result)
