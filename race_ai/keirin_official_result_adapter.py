"""Offline normal-UI KEIRIN results, separate from frozen forecast features.

The official result help /pc/static/help/PU0326.html says full placings appear
after confirmation and describes refunds and unusual results. A result is not
a teacher until its exact public selector, registered roster and payout unit
are verified. Hashes establish integrity, not provider authentication or rights.
"""
import base64
import binascii
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
from unicodedata import normalize
from urllib.parse import parse_qs, urlsplit

from .keirin_official_sparse_adapter import JST, _clock, _identity, _integer
from .manual_official_capture import _json, official_rights_ref, validate_source_pair


SCHEMA='RACE_AI_KEIRIN_OFFICIAL_RESULT_SOURCE_V1'
CONTEXT='RACE_AI_KEIRIN_OFFICIAL_RESULT_ARCHIVE_CONTEXT_V1'
RIGHTS=official_rights_ref('keirin')
HOSTS=frozenset(('keirin.jp','www.keirin.jp'))
MAX_BYTES=2*1024*1024


def _need(ok,reason):
    if not ok:
        raise ValueError('KEIRIN_RESULT_'+reason)


def _url(url):
    validate_source_pair(url,RIGHTS)
    parsed=urlsplit(url)
    _need(parsed.hostname in HOSTS,'OFFICIAL_KEIRIN_SOURCE_REQUIRED')
    return parsed


def _blob(value):
    _need(type(value) is str and 0<len(value)<=((MAX_BYTES+2)//3)*4,'BOUNDED_BASE64_REQUIRED')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise ValueError('KEIRIN_RESULT_BASE64_INVALID') from None
    _need(0<len(raw)<=MAX_BYTES and base64.b64encode(raw).decode('ascii')==value,'BASE64_INVALID')
    return raw


def _http(raw,metadata,now,*,json_source=False):
    _need(type(raw) is bytes and 0<len(raw)<=MAX_BYTES and type(metadata) is dict,'BOUNDED_SOURCE_REQUIRED')
    url=metadata.get('source_url');parsed=_url(url)
    _need(metadata.get('final_url')==url and metadata.get('method')=='GET' and metadata.get('status')==200 and
          type(metadata.get('byte_count')) is int and metadata['byte_count']==len(raw) and
          metadata.get('source_sha256')==sha256(raw).hexdigest() and type(metadata.get('headers')) is dict,
          'SOURCE_BYTES_OR_HTTP_BINDING')
    _need('source_rights_ref' not in metadata or metadata['source_rights_ref']==RIGHTS,'SOURCE_PURPOSE_MISMATCH')
    start,complete=_clock(metadata.get('fetched_at')),_clock(metadata.get('response_received_at'))
    _need(start<=complete<=now,'SOURCE_CAPTURE_CLOCK')
    headers={str(k).lower():v for k,v in metadata['headers'].items()}
    mime=headers.get('content-type','')
    _need(type(mime) is str and mime.lower().startswith('application/json' if json_source else 'text/html'),
          'SOURCE_CONTENT_TYPE')
    return parsed,complete


def _selector(parsed,kind):
    query=parse_qs(parsed.query,keep_blank_values=True,strict_parsing=True)
    _need(parsed.path=='/pc/json' and set(query)=={'encp','type'} and query['type']==[kind] and
          len(query['encp'])==1 and 1<=len(query['encp'][0])<=2048,'NORMAL_UI_SOURCE_SELECTOR')
    return query['encp'][0]


def _capture(value,now,*,json_source=False):
    _need(type(value) is dict and set(value)=={'raw_base64','metadata'},'COMPANION_CAPTURE_REQUIRED')
    raw=_blob(value['raw_base64']);parsed,complete=_http(raw,value['metadata'],now,json_source=json_source)
    return raw,value['metadata'],parsed,complete


def _browser(value,sources,now):
    _need(type(value) is dict and set(value)=={'metadata','rendered_dom_base64'},'NORMAL_UI_PROOF_REQUIRED')
    metadata=value['metadata'];dom=_blob(value['rendered_dom_base64'])
    _need(type(metadata) is dict and metadata.get('schema')=='RACE_AI_PRIVATE_OFFICIAL_BROWSER_PROBE_V1' and
          metadata.get('normal_ui_only') is True and metadata.get('undocumented_api_manually_called') is False and
          metadata.get('http_access_denied') is False and metadata.get('entire_host_stopped') is False and
          metadata.get('stop_reason')=='FINISHED' and type(metadata.get('network_host_allowlist')) is list and
          set(metadata['network_host_allowlist'])==HOSTS,'NORMAL_UI_PROOF_REQUIRED')
    source=_url(metadata.get('source_url'))
    _need(source.path in ('/pc/top','/pc/racelist','/pc/racelive') and not source.query,'NORMAL_UI_PAGE_REQUIRED')
    started,complete=_clock(metadata.get('started_at')),_clock(metadata.get('captured_at'))
    _need(started<=complete<=now,'NORMAL_UI_CAPTURE_CLOCK')
    proof=metadata.get('rendered_dom')
    _need(type(proof) is dict and proof.get('byte_count')==len(dom) and
          proof.get('source_sha256')==sha256(dom).hexdigest(),'RENDERED_DOM_BINDING')
    ledger=metadata.get('ledger')
    _need(type(ledger) is list and 1<=len(ledger)<=2048 and all(type(e) is dict for e in ledger),
          'BOUNDED_NETWORK_LEDGER_REQUIRED')
    _need(not any(type(e.get('status')) is int and 400<=e['status']<500 for e in ledger),'HOST_DENIAL_REJECTED')
    selected=False
    for entry in ledger:
        if type(entry.get('status')) is int:
            _url(entry.get('url'))
        if entry.get('event')=='NORMAL_SEMANTIC_UI_CLICK':
            when=_clock(entry.get('at'));before,after=_url(entry.get('before')),_url(entry.get('after'))
            _need(started<=when<=complete,'UI_CLICK_CLOCK')
            if re.sub(r'\s+','',entry.get('label',''))=='競走結果':
                selected|=before.path==after.path=='/pc/racelive' and not before.query and not after.query
    _need(selected,'VISIBLE_NORMAL_RESULT_SELECTION_REQUIRED')
    for raw,http in sources:
        found=[e for e in ledger if e.get('status')==200 and e.get('url')==http['source_url'] and
               e.get('source_sha256')==sha256(raw).hexdigest() and e.get('method')=='GET' and
               e.get('resource_type') in ('xhr','fetch') and e.get('byte_count')==len(raw) and
               e.get('request_started_at')==http['fetched_at'] and e.get('body_captured_at')==http['response_received_at']]
        _need(found,'EXACT_NORMAL_UI_RESPONSE_BINDING')
        _need(started<=_clock(http['fetched_at'])<=_clock(http['response_received_at'])<=complete,'UI_SOURCE_CLOCK')


class _Text(HTMLParser):
    _VOID=frozenset(('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'))
    _HIDDEN=frozenset(('head','title','script','style','noscript','template','iframe','object','embed','defs'))
    _BLOCK=frozenset(('html','body','p','div','section','article','aside','li','ul','ol','table','td','th','tr',
                      'br','hr','blockquote','figure','figcaption','h1','h2','h3','h4','h5','h6'))

    def __init__(self,raw):
        super().__init__(convert_charrefs=True);self.parts=[];self.stack=[];self.nodes=0
        self.feed(raw.decode('utf-8','strict'));self.close()

    def handle_starttag(self,tag,attrs):
        self.nodes+=1
        _need(self.nodes<=50000 and len(self.stack)<=128,'UNIT_DOCUMENT_BOUND')
        attrs=dict(attrs);style=re.sub(r'\s+','',attrs.get('style','').lower())
        classes=set(attrs.get('class','').lower().split())
        hidden=(bool(self.stack and self.stack[-1][1]) or tag in self._HIDDEN or 'hidden' in attrs or
                attrs.get('aria-hidden','').lower()=='true' or 'display:none' in style or
                'visibility:hidden' in style or bool(classes&{'hidden','d-none','visually-hidden','sr-only'}))
        if tag in self._BLOCK:self.parts.append('\n')
        if tag not in self._VOID:self.stack.append((tag,hidden))

    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,-1,-1):
            if self.stack[index][0]==tag:
                self.stack=self.stack[:index];break
        if tag in self._BLOCK:self.parts.append('\n')

    def handle_data(self,text):
        if not self.stack or not self.stack[-1][1]:self.parts.append(text)


def _unit(value,now):
    if value is None:return False
    raw,metadata,parsed,complete=_capture(value,now)
    segments=[re.sub(r'\s+','',normalize('NFKC',segment))
              for segment in re.split(r'[。\r\n!！]+',''.join(_Text(raw).parts))]
    # A minimum purchase of100yen does not establish the displayed payout unit.
    payout=r'(?:払戻金額|払い戻し金額|払戻し金額|払戻金|払い戻し金|払戻し金|払戻額|払い戻し額|配当金)'
    denominator=r'(?<![\d,.+\-])100円(?:券|の投票|投票)?(?:1枚)?(?:に対する|あたり|当たり|当り|につき)'
    subject=r'は[、,]?(?:すべて|全て|いずれも)?'
    forward=r'(?:※)?'+payout+subject+denominator+r'(?:の)?金額(?:です|となります|になります)'
    reverse=r'(?:※)?'+denominator+r'の'+payout+r'(?:を表示します|を表示しています|です|となります)'
    return any(re.fullmatch(forward,text) is not None or re.fullmatch(reverse,text) is not None for text in segments)


def _registered(rows,slot_key,id_key):
    _need(type(rows) is list and 7<=len(rows)<=9,'FULL_REGISTERED_ROSTER_REQUIRED')
    roster={}
    for row in rows:
        _need(type(row) is dict,'REGISTERED_RIDER_REQUIRED')
        number=_integer(row.get(slot_key),1,9);identity=_identity(row.get(id_key))
        _need(str(number) not in roster and identity not in roster.values(),'DUPLICATE_REGISTERED_RIDER')
        roster[str(number)]=identity
    return roster


def _state(facts,status,reason,*,refunds=()):
    facts.update(status=status,reason=reason,ordered_top3=[],payout_per_100_yen=None,
                 refund_numbers=sorted(set(refunds)))
    return facts


def parse_official_result_source(raw,metadata,*,now):
    """Return private source facts; creates no frozen-input or save attestation."""
    now=_clock(now);main,captured=_http(raw,metadata,now,json_source=True);selector=_selector(main,'JSJ012')
    context=metadata.get('keirin_result_archive_context')
    _need(type(context) is dict and set(context)=={'schema','identity_capture','browser_capture','payout_unit_capture'} and
          context['schema']==CONTEXT,'RESULT_ARCHIVE_CONTEXT_REQUIRED')
    identity_raw,identity_meta,identity_url,identity_time=_capture(context['identity_capture'],now,json_source=True)
    _need(_selector(identity_url,'JSJ001')==selector and identity_time<=captured,'IDENTITY_SELECTOR_OR_CLOCK_MISMATCH')
    identity=_json(identity_raw);body=_json(raw)
    _need(type(identity) is dict and type(identity.get('resultCd')) is int and identity['resultCd']==0 and
          type(identity.get('C0201data')) is dict and type(body) is dict and
          type(body.get('resultCd')) is int and body['resultCd']==0,'SUCCESSFUL_OFFICIAL_SOURCE_REQUIRED')
    selected=identity['C0201data'];_need(selected.get('encSelParaR')==selector,'SELF_IDENTIFYING_SELECTOR_MISMATCH')
    _browser(context['browser_capture'],((identity_raw,identity_meta),(raw,metadata)),now)
    day=selected.get('selKaisai');venue=selected.get('selKjyoCd');number=_integer(selected.get('selRaceNo'),1,12)
    _need(type(day) is str and re.fullmatch(r'[0-9]{8}',day) and type(venue) is str and
          re.fullmatch(r'[0-9]{2}',venue) and int(venue)>0,'EXPLICIT_RACE_IDENTITY_REQUIRED')
    day=date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:])
    detail=selected.get('C0201racedtl')
    _need(type(detail) is dict,'OFFICIAL_RACE_DETAIL_REQUIRED')
    cutoff_text=detail.get('aftBetTime');source_cutoff=None
    if type(cutoff_text) is str and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',cutoff_text):
        source_cutoff=datetime.combine(day,datetime.strptime(cutoff_text,'%H:%M').time(),JST)
    race=dict(race_id=f'keirin:{day.isoformat()}:keirin-jyo-{venue}:{number}',venue='keirin-jyo-'+venue,
              event_date_jst=day.isoformat(),race_no=number)
    facts=dict(schema=SCHEMA,race=race,roster={},finish_rows=[],observed_top3=[],observed_payout_yen=None,
        captured_at=metadata['response_received_at'],published_at=None,source_ref=metadata['source_url'],
        source_sha256=metadata['source_sha256'],future_frozen_input_paired=False,payout_unit_verified=False,
        source_sales_cutoff_at=source_cutoff.isoformat() if source_cutoff is not None else None)
    _need(all(selected.get(key) is None or type(selected[key]) is bool
              for key in ('flgRaceCancel','flgSectionCancel')),'EXACT_CANCELLATION_STATUS_REQUIRED')
    if selected.get('flgRaceCancel') is True or selected.get('flgSectionCancel') is True:
        return _state(facts,'special','EXPLICIT_RACE_CANCELLATION')
    _need(all(type(body.get(k)) is bool for k in ('tyakujyunDispFlg','haraiGakuDispFlg','bikouDispFlg')),
          'OFFICIAL_DISPLAY_STATUS_REQUIRED')
    if body['tyakujyunDispFlg'] is False:
        return _state(facts,'pending','RESULT_PLACINGS_NOT_FINAL')
    rows=body.get('tyakujyunItemSubData')
    if rows==[]:return _state(facts,'pending','RESULT_ROWS_NOT_AVAILABLE')
    roster=_registered(rows,'syaban','sensyuRegistNo')
    header=_registered(selected['C0201racedtl']['C0201sensyu'],'carNum','numPlayer')
    _need(roster==header,'RESULT_HEADER_REGISTERED_ROSTER_MISMATCH');facts['roster']=roster
    pending,nonfinish,annotation,refunds=False,False,False,[]
    for row in rows:
        slot=_integer(row['syaban'],1,9);place=row.get('tyaku')
        _need(type(place) in (str,int) and type(place) is not bool,'OFFICIAL_PLACING_REQUIRED')
        place=re.sub(r'\s+','',normalize('NFKC',str(place)));rank=None
        if place.isdecimal():rank=_integer(place,1,len(rows))
        elif place in ('','-','--','未確定','未発表'):pending=True
        else:
            nonfinish=True
            if any(word in place for word in ('欠','取消','除外')):refunds.append(slot)
        states=row.get('kojinStateItemSubData')
        _need(type(states) is list and all(type(item) is dict for item in states),'OFFICIAL_RIDER_STATE_REQUIRED')
        annotation|=any(any(str(value).strip() for value in item.values()) for item in states)
        facts['finish_rows'].append(dict(number=slot,identity=row['sensyuRegistNo'],finish=rank))
    if nonfinish:return _state(facts,'special','NONFINISH_OR_SPECIAL_PLACING',refunds=refunds)
    if pending:return _state(facts,'pending','RESULT_PLACINGS_NOT_FINAL')
    ranks=[r['finish'] for r in facts['finish_rows']]
    if sorted(ranks)!=list(range(1,len(rows)+1)):
        return _state(facts,'special','TIED_OR_NONUNIQUE_PLACINGS')
    if annotation or body['bikouDispFlg']:
        return _state(facts,'special','RESULT_REMARKS_OR_RIDER_STATE')
    pay=body.get('haraiGakuSubData')
    _need(type(pay) is dict and type(pay.get('APartReturnDispFlg')) is bool,'OFFICIAL_REFUND_STATUS_REQUIRED')
    if pay['APartReturnDispFlg']:return _state(facts,'special','EXPLICIT_PARTIAL_REFUND',refunds=refunds)
    if body['haraiGakuDispFlg'] is False:return _state(facts,'pending','PAYOUT_NOT_AVAILABLE')
    trifecta=pay.get('RT3HaraiGakuDispItemSubData')
    _need(type(trifecta) is list,'TRIFECTA_RECORDS_REQUIRED')
    if not trifecta:return _state(facts,'pending','TRIFECTA_NOT_AVAILABLE')
    if len(trifecta)!=1:return _state(facts,'special','MULTIPLE_TRIFECTA_RECORDS')
    payment=trifecta[0];_need(type(payment) is dict,'TRIFECTA_RECORD_REQUIRED')
    combo=re.fullmatch(r'\s*([1-9])\s*[-→]\s*([1-9])\s*[-→]\s*([1-9])\s*',str(payment.get('kumiBan','')))
    amount=re.fullmatch(r'[0-9]+(?:,[0-9]{3})*',str(payment.get('haraiGaku','')))
    if payment.get('kumiDispFlg') is not True or combo is None or amount is None:
        return _state(facts,'special','SPECIAL_TRIFECTA_PAYMENT')
    winning=list(map(int,combo.groups()));payout=int(amount[0].replace(',',''))
    _need(len(set(winning))==3 and all(str(n) in roster for n in winning) and 0<payout<=10**9,
          'INVALID_TRIFECTA_PAYMENT')
    ordered=[row['number'] for row in sorted(facts['finish_rows'],key=lambda row:row['finish'])[:3]]
    _need(winning==ordered,'FINISH_TRIFECTA_CONFLICT')
    facts.update(observed_top3=ordered,observed_payout_yen=payout)
    if source_cutoff is None:return _state(facts,'pending','OFFICIAL_CUTOFF_NOT_AVAILABLE')
    _need(source_cutoff<captured,'SOURCE_RESULT_CAPTURE_BEFORE_OFFICIAL_CUTOFF')
    verified=_unit(context['payout_unit_capture'],now);facts['payout_unit_verified']=verified
    if not verified:return _state(facts,'pending','PAYOUT_UNIT_NOT_VERIFIED')
    facts.update(status='settled',reason='ORDINARY_SETTLED_RESULT',ordered_top3=ordered,
                 payout_per_100_yen=payout,refund_numbers=[])
    return facts


def parse_result(raw,metadata,*,frozen_native_payload,now,source_rights_ref):
    """Semantic join only; caller independently authenticates both archives."""
    now=_clock(now);_need(source_rights_ref==RIGHTS,'SOURCE_PURPOSE_MISMATCH')
    _need(type(frozen_native_payload) is dict and type(frozen_native_payload.get('snapshot')) is dict,
          'FROZEN_NATIVE_INPUT_REQUIRED')
    snapshot=frozen_native_payload['snapshot'];race=snapshot.get('race')
    _need(type(race) is dict and race.get('sport')=='keirin','FROZEN_KEIRIN_RACE_REQUIRED')
    facts=parse_official_result_source(raw,metadata,now=now)
    _need(all(race.get(k)==facts['race'][k] for k in ('race_id','venue','event_date_jst')),'FROZEN_RESULT_RACE_MISMATCH')
    cutoff=_clock(race.get('sales_cutoff_at'));capture=_clock(facts['captured_at'])
    _need(_clock(race.get('as_of'))<cutoff<capture<=now,'FROZEN_RESULT_CAPTURE_CLOCK')
    if facts['source_sales_cutoff_at'] is not None:
        _need(_clock(facts['source_sales_cutoff_at'])==cutoff,'FROZEN_OFFICIAL_CUTOFF_MISMATCH')
    roster=_registered(snapshot.get('participants'),'number','identity')
    _need(len(roster) in (7,9),'FROZEN_ACTIVE_FIELD_SIZE_REQUIRED')
    verified=bool(facts['roster'])
    if verified:_need(facts['roster']==roster,'FROZEN_RESULT_REGISTERED_ROSTER_MISMATCH')
    _need(facts['status']!='settled' or verified,'SETTLED_REGISTERED_ROSTER_REQUIRED')
    return dict(race_id=race['race_id'],sport='keirin',status=facts['status'],reason=facts['reason'],
        ordered_top3=facts['ordered_top3'],roster=facts['roster'],identity_verified=verified,
        captured_at=facts['captured_at'],published_at=None,source_ref=facts['source_ref'],source_rights_ref=source_rights_ref,
        source_sha256=facts['source_sha256'],payout_per_100_yen=facts['payout_per_100_yen'],
        refund_numbers=facts['refund_numbers'],closed_at=race['sales_cutoff_at'])
