"""Pure fresh JRA card/result binding to an already verified future native.

The caller authenticates the original forecast/native artifacts, source journal,
shared request budget and acquisition authority. This module never acquires a
source, opens a key or manufactures a result URL, cutoff, roster or label.
"""
from datetime import timedelta
import re
from urllib.parse import parse_qs,urlsplit

from . import all_existing_model_registry as registry
from .all_existing_model_learning import _sources
from .four_sport_learning import LEARNED_ID
from .jra_official_sparse_adapter import _clock,_document,VENUES
from .manual_official_capture import official_rights_ref,validate_source_pair
from scripts import all_existing_model_official_result_collect as C

PREFIX='ALL_MODEL_FUTURE_RESULT_HORSE_'


def _need(ok,reason):
    if not ok:raise ValueError(PREFIX+reason)


def _url_identity(url,kind):
    validate_source_pair(url,official_rights_ref('horse'))
    parts=urlsplit(url);query=parse_qs(parts.query,keep_blank_values=True)
    _need(parts.path==('/JRADB/accessD.html' if kind=='dde' else '/JRADB/accessS.html') and
        set(query)=={'CNAME'} and len(query['CNAME'])==1,'LITERAL_SOURCE_IDENTITY')
    mode='01' if kind=='dde' else '(?:01|10)'
    match=re.fullmatch(r'pw01'+kind+mode+r'(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/[A-Fa-f0-9]{2}',query['CNAME'][0])
    _need(match is not None,'LITERAL_SOURCE_IDENTITY')
    return match.groups()


def _case(case,native,now):
    now=_clock(now)
    _need(type(case) is dict and set(case)=={'sport','race_id','route'} and case['sport']=='horse' and
        type(native) is dict and type(native.get('snapshot')) is dict,'FROZEN_HORSE_CASE')
    route=case['route']
    _need(type(route) is dict and {'kind','card_url'}<=set(route)<={'kind','card_url','result_url','link_capture'} and
        route['kind']=='JRA_CARD_PUBLISHED_GET' and route.get('result_url') is None and route.get('link_capture') is None,
        'FRESH_LITERAL_ROUTE_REQUIRED')
    race=native['snapshot']['race'];info=registry.identity(LEARNED_ID,'horse',native)
    _need(race['sport']=='horse' and case['race_id']==race['race_id']==info['race_id'] and
        (route['card_url'],official_rights_ref('horse')) in _sources(native),'FROZEN_CARD_SOURCE_BINDING')
    identity=_url_identity(route['card_url'],'dde');venue,year,_,_,number,day=identity
    expected_day=f'{day[:4]}-{day[4:6]}-{day[6:]}'
    _need(case['race_id']==f'horse:{expected_day}:jra-{venue}:{int(number)}' and
        race['event_date_jst']==expected_day and year==day[:4] and VENUES.get(race['venue'])==venue,
        'FROZEN_RACE_IDENTITY')
    participants=native['snapshot']['participants'];roster=info['roster']
    _need(type(participants) is list and 3<=len(participants)<=18 and len(roster)==len(participants) and
        all(type(p['number']) is int and 1<=p['number']<=18 and type(p['identity']) is str and p['identity'] for p in participants) and
        len(set(roster.values()))==len(roster),'FROZEN_REGISTERED_ROSTER')
    cutoff=_clock(race['sales_cutoff_at']);due=cutoff+timedelta(seconds=120)
    _need(_clock(race['as_of'])<cutoff and now>=due,'ORIGINAL_CUTOFF_NOT_DUE')
    return route,identity,due,now


def _capture(capture,url,due,now):
    _need(type(capture) is dict and type(capture.get('metadata')) is dict,'ACTUAL_SOURCE_CAPTURE')
    metadata=capture['metadata']
    _need(metadata.get('source_url')==url and metadata.get('final_url')==url and
        metadata.get('method')==metadata.get('http_method')=='GET','ACTUAL_LITERAL_GET')
    started=_clock(metadata['fetched_at']);completed=_clock(metadata['response_received_at'])
    _need(due<=started<=completed<=now,'ACTUAL_SOURCE_DUE_CLOCK')
    _document(C._blob(capture['raw_base64']),metadata,now)
    return started,completed


def _discover(case,native,card_capture,*,now):
    route,identity,due,now=_case(case,native,now)
    _capture(card_capture,route['card_url'],due,now)
    target=C.published_result(card_capture,native,now)
    if target is not None:_need(_url_identity(target,'sde')==identity,'PUBLISHED_RESULT_FULL_IDENTITY')
    return target


def _bind(case,native,card_capture,result_capture,*,now):
    target=_discover(case,native,card_capture,now=now);_need(target is not None,'PUBLISHED_RESULT_LINK_REQUIRED')
    route,_,due,now=_case(case,native,now)
    _,discovered=_capture(card_capture,route['card_url'],due,now)
    started,_=_capture(result_capture,target,due,now)
    _need(discovered<=started,'RESULT_PRECEDES_PUBLISHED_DISCOVERY')
    return C._parse(result_capture,native,'horse',now=now,allow_order_only=False)


def _guard(operation,*args,**kwargs):
    try:return operation(*args,**kwargs)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        if isinstance(exc,ValueError) and str(exc).startswith(PREFIX):raise
        raise ValueError(PREFIX+'INPUT_REJECTED') from None


def discover_result(case,native,card_capture,*,now):
    """Return the fresh card's exact published same-race href, or None."""
    return _guard(_discover,case,native,card_capture,now=now)


def bind_result(case,native,card_capture,result_capture,*,now):
    """Return the unchanged existing settled/pending/special horse observation."""
    return _guard(_bind,case,native,card_capture,result_capture,now=now)
