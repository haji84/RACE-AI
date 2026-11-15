"""Collect factual pre-race observations into existing encrypted source packets."""
from datetime import timedelta
import re
from .racer_daily import clock,need,sha,JST
from .source_retry_policy import SourceWait
from .boat_observation_context import parse_beforeinfo,MAX_BYTES
from .boat_context_store import _context

RACE=re.compile(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')

def beforeinfo_url(rid):
    match=RACE.fullmatch(rid);need(match is not None,'BEFOREINFO_RACE_IDENTITY')
    day,venue,number=match.groups()
    return f'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={day}&jcd={venue}&rno={int(number)}'

def _roster(row):
    from .boat_saved_model_view import _registration
    people=row.get('participants',[])
    need(row.get('sport')=='boat' and len(people)==6,'BEFOREINFO_ROSTER_REQUIRED')
    values=[dict(lane=p['number'],registration_number=_registration(p)) for p in people]
    need({p['lane'] for p in values}==set(range(1,7)) and len({p['registration_number'] for p in values})==6 and
         all(isinstance(p['registration_number'],str) and re.fullmatch('[0-9]{4}',p['registration_number']) for p in values),'BEFOREINFO_ROSTER_REQUIRED')
    return values

def _parsed(row,raw,receipt):
    need(receipt.get('http_status')==200 and sha(raw)==receipt.get('source_sha256') and
         receipt.get('source_url')==beforeinfo_url(row['race_id']),'BEFOREINFO_CAPTURE_BINDING')
    roster=_roster(row)
    page=parse_beforeinfo(raw,source_url=receipt['source_url'],captured_at=receipt['captured_at'],expected_race_id=row['race_id'],roster=roster)
    need(page.get('status')=='PARSED' and page.get('roster_binding_status')=='VERIFIED','BEFOREINFO_SOURCE_LAYOUT')
    context=dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=row['race_id'],cutoff_at=page['source_cutoff_at'],
        roster=roster,beforeinfo=page,pitreport=None,entry_history=None,forecast_inputs_used=False)
    checked,_=_context(context)
    return checked

def _cutoff(row):
    values=[row.get('cutoff_at'),*row.get('saved_cutoff_variants',[])]
    return max((clock(v) for v in values if v),default=None)

def collect_beforeinfo(state,rows,*,now,fetch,max_requests=4):
    """Share the caller's client/budget; do not execute or rewrite a forecast."""
    now=clock(now);need(type(max_requests) is int and 1<=max_requests<=4,'BEFOREINFO_REQUEST_BOUND')
    control=state.control;checks=control.setdefault('beforeinfo_checks',{});captures=control.setdefault('beforeinfo_captures',{})
    day=now.astimezone(JST).date().isoformat();queue=[]
    for row in rows:
        try:
            _roster(row);rid=row['race_id'];beforeinfo_url(rid);cutoff=_cutoff(row)
            if row.get('event_date_jst')!=day or cutoff is None or cutoff>now+timedelta(minutes=60):continue
            item=checks.get(rid,{})
            if item.get('next_at') and clock(item['next_at'])>now:continue
            # Refresh upcoming races; after the race, make at most one final
            # factual capture. Missing older current-day facts can backfill.
            if cutoff<=now and item.get('finished'):continue
            priority=0 if cutoff>now else 1
            last=clock(item['checked_at']) if item.get('checked_at') else now-timedelta(days=1)
            queue.append((priority,last,cutoff,rid,row))
        except (ValueError,KeyError,TypeError):continue
    requests=parsed=rejected=0
    for _,_,cutoff,rid,row in sorted(queue,key=lambda item:item[:4]):
        if requests>=max_requests:break
        url=beforeinfo_url(rid)
        active=[control['waits'].get(key) for key in ('boatrace','boatrace-beforeinfo',url)]
        if any(wait and clock(wait['until'])>now for wait in active):continue
        requests+=1
        check=dict(checked_at=now.isoformat(),next_at=(now+timedelta(minutes=5)).isoformat(),state='SOURCE_ERROR',reason='BEFOREINFO_SOURCE_LAYOUT',finished=False)
        try:
            raw,at=fetch(url);at=clock(at)
            need(at<=now+timedelta(minutes=5) and len(raw)<=MAX_BYTES,'BEFOREINFO_CAPTURE_BOUND')
            receipt=dict(source_url=url,source_sha256=sha(raw),captured_at=at.isoformat(),http_status=200)
            try:context=_parsed(row,raw,receipt)
            except (ValueError,KeyError,TypeError):
                state.remember('BEFOREINFO_REJECTED',raw,receipt);raise ValueError('BEFOREINFO_SOURCE_LAYOUT') from None
            captures[rid]=state.remember('BEFOREINFO',raw,receipt)
            people=context['beforeinfo']['participants']
            complete=all(p.get('display_time') is not None and p.get('exhibition_st_status') in ('OK','F','L') for p in people)
            check.update(state='READY' if complete else 'AWAITING_EXHIBITION',reason=None,finished=cutoff<=now and complete)
            parsed+=1
        except SourceWait as error:
            status=getattr(error,'plan',{}).get('http_status')
            key=url if status==404 else 'boatrace-beforeinfo' if status in (401,403) else 'boatrace'
            until=max(clock(error.retry_at),now+timedelta(minutes=5)).isoformat() if error.retry_at else (now+timedelta(minutes=5)).isoformat() if status==404 else '9999-12-31T23:59:59+00:00'
            control['waits'][key]=dict(until=until,reason=error.reason)
            check.update(state='SOURCE_WAIT',reason=error.reason,next_at=until)
        except (ValueError,KeyError,TypeError):
            rejected+=1;check['next_at']=(now+timedelta(minutes=15)).isoformat()
        checks[rid]=check
    # Historical ciphertext packets remain intact; the active queue is bounded
    # to the latest two days just like the existing result bridge.
    oldest=(now.astimezone(JST).date()-timedelta(days=1)).strftime('%Y%m%d')
    for collection in (checks,captures):
        for rid in list(collection):
            if rid[:8]<oldest:del collection[rid]
    return dict(requests=requests,parsed=parsed,rejected=rejected)

def project_beforeinfo(row,state,*,now):
    """Interpret authenticated retained bytes without mutating any original."""
    now=clock(now);rid=row['race_id'];check=state.control.get('beforeinfo_checks',{}).get(rid)
    pointer=state.control.get('beforeinfo_captures',{}).get(rid)
    if check is None and pointer is None:return None
    context=None
    if pointer:
        try:
            raw,receipt=state.capture(pointer);need(clock(receipt['captured_at'])<=now,'BEFOREINFO_FUTURE_CAPTURE')
            context=_parsed(row,raw,receipt)
        except (ValueError,KeyError,TypeError):context=None
    check=check or dict(checked_at=pointer['captured_at'],state='SOURCE_ERROR',reason='BEFOREINFO_STATE_MISSING')
    return dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',checked_at=check['checked_at'],state=check['state'],
        reason=check.get('reason'),context=context,forecast_inputs_used=False)
