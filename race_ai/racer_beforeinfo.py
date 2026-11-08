"""Collect factual pre-race observations into existing encrypted source packets."""
from copy import deepcopy
from datetime import timedelta
import re
from .racer_daily import clock,need,sha,JST
from .source_retry_policy import SourceWait
from .boat_observation_context import parse_beforeinfo,MAX_BYTES
from .boat_context_store import _context

RACE=re.compile(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')

def _source_time(value):
    try:return clock(value)
    except (AttributeError,TypeError,ValueError,OverflowError):
        raise ValueError('BEFOREINFO_SOURCE_CLOCK_REQUIRED') from None

def beforeinfo_url(rid):
    match=RACE.fullmatch(rid);need(match is not None,'BEFOREINFO_RACE_IDENTITY')
    day,venue,number=match.groups()
    return f'https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd={day}&jcd={venue}&rno={int(number)}'

def _program_source(program,at):
    from .boat_active_exhibition import _program
    roster=_program(program,at)
    need(type(program.get('active_entrant_count')) is int and
         all(type(n) is int for n in program['active_lanes']),'BEFOREINFO_PROGRAM_ROSTER_MISMATCH')
    source=program.get('source',{})
    need(type(source) is dict and source.get('source_url')==program['source_url'] and source.get('sha256')==program['source_sha256'] and
         _source_time(source.get('captured_at'))==_source_time(program['captured_at']),'BEFOREINFO_PROGRAM_SOURCE_BINDING')
    return roster

def _latest_program(rid,candidates,*,at):
    programs=[program for program in candidates if program is not None]
    for program in programs:
        _program_source(program,at)
        need(program['race_id']==rid,'BEFOREINFO_PROGRAM_ROSTER_MISMATCH')
    if not programs:return None
    latest=max(programs,key=lambda program:_source_time(program['captured_at']))
    need(all(program==latest for program in programs if _source_time(program['captured_at'])==
             _source_time(latest['captured_at'])),'BEFOREINFO_PROGRAM_REVISION_CONFLICT')
    return latest

def _roster(row, program=None, *, at=None):
    from .boat_saved_model_view import _registration
    people=row.get('participants',[])
    need(row.get('sport')=='boat' and type(people) is list and
         (3<=len(people)<=6 if program is not None else len(people)==6),'BEFOREINFO_ROSTER_REQUIRED')
    values=[dict(lane=p['number'],registration_number=_registration(p)) for p in people]
    need(all(type(p['lane']) is int and 1<=p['lane']<=6 for p in values) and
         len({p['lane'] for p in values})==len(values) and
         len({p['registration_number'] for p in values})==len(values) and
         all(isinstance(p['registration_number'],str) and re.fullmatch('[0-9]{4}',p['registration_number']) for p in values),'BEFOREINFO_ROSTER_REQUIRED')
    if program is None:
        need({p['lane'] for p in values}==set(range(1,7)),'BEFOREINFO_ROSTER_REQUIRED')
    else:
        active, full, withdrawn = _program_source(program, at or program['captured_at'])
        expected={p['lane']:p['registration_number'] for p in active}
        saved={p['lane']:p['registration_number'] for p in values}
        need(program['race_id']==row['race_id'] and row.get('event_date_jst')==program['date_jst'] and
             (row.get('race_no') is None or type(row['race_no']) is int and row['race_no']==int(program['race_id'][-2:])) and
             set(expected)<=set(saved) and all(lane in full and full[lane]['racer_registration_id']==pid
                 and (lane in expected or lane in withdrawn) for lane,pid in saved.items()) and
             all((p['number'] not in expected or p.get('active') is not False and p.get('withdrawn') is not True) and
                 all(p[k]==p['number'] for k in ('lane',) if k in p) for p in people),
             'BEFOREINFO_PROGRAM_ROSTER_MISMATCH')
        if 'withdrawn_lanes' in row:
            absent=row['withdrawn_lanes']
            need(type(absent) is list and all(type(n) is int for n in absent) and
                 len(set(absent))==len(absent) and set(absent)<=set(withdrawn),'BEFOREINFO_PROGRAM_ROSTER_MISMATCH')
        seen=set()
        for person in row.get('withdrawn_participants',[]):
            lane=person['number']
            keys=('registration_no','registration_number','registration_id','racer_registration_id','racer_id')
            pid=_registration(person) if any(person.get(k) is not None for k in keys) else None
            need(type(lane) is int and lane in withdrawn and lane not in seen and
                 pid==full[lane]['racer_registration_id'],'BEFOREINFO_PROGRAM_ROSTER_MISMATCH')
            seen.add(lane)
        values=[p for p in values if p['lane'] in expected]
    return values

def _parsed(row,raw,receipt,program=None):
    need(receipt.get('http_status')==200 and sha(raw)==receipt.get('source_sha256') and
         receipt.get('source_url')==beforeinfo_url(row['race_id']),'BEFOREINFO_CAPTURE_BINDING')
    roster=_roster(row,program,at=receipt['captured_at'])
    if program is None:
        page=parse_beforeinfo(raw,source_url=receipt['source_url'],captured_at=receipt['captured_at'],expected_race_id=row['race_id'],roster=roster)
    else:
        from .boat_active_exhibition import parse_active_beforeinfo
        page=parse_active_beforeinfo(raw,program=program,source_url=receipt['source_url'],captured_at=receipt['captured_at'])['context']
    need(page.get('status')=='PARSED' and page.get('roster_binding_status')=='VERIFIED','BEFOREINFO_SOURCE_LAYOUT')
    context=dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=row['race_id'],cutoff_at=page['source_cutoff_at'],
        roster=roster,beforeinfo=page,pitreport=None,entry_history=None,forecast_inputs_used=False)
    if program is not None:context['program']=deepcopy(program)
    checked,_=_context(context)
    return checked

def _checked_live_context(row,live,*,now=None):
    """Bind the separate live overlay to this exact current registered roster."""
    need(type(live) is dict and live.get('schema')=='RACE_AI_LIVE_BOAT_OBSERVATION_V1' and
         live.get('forecast_inputs_used') is False and
         live.get('state') in ('READY','AWAITING_EXHIBITION','SOURCE_WAIT','SOURCE_ERROR'),
         'BEFOREINFO_LIVE_BINDING')
    checked=_source_time(live['checked_at'])
    need(now is None or checked<=clock(now),'BEFOREINFO_FUTURE_CAPTURE')
    context=live.get('context')
    if context is None:
        need(live['state']!='READY','BEFOREINFO_LIVE_BINDING')
        return None
    context,_=_context(context)
    need(context['race_id']==row['race_id'],'BEFOREINFO_LIVE_BINDING')
    program=context.get('program')
    roster=_roster(row,program,at=checked)
    need({p['lane']:p['registration_number'] for p in roster}==
         {p['lane']:p['registration_number'] for p in context['roster']},'BEFOREINFO_LIVE_BINDING')
    page=context['beforeinfo']
    need(type(page) is dict and _source_time(page['source']['captured_at'])<=checked,'BEFOREINFO_FUTURE_CAPTURE')
    return context

def project_program_observation(row,program,beforeinfo,*,checked_at):
    """Carry already-verified native input facts in a mutable display overlay.

    The caller validates the saved native payload and physical receipt first.
    This function does not fetch, retain, execute, or modify any forecast.
    """
    from .boat_active_exhibition import SCHEMA
    need(type(beforeinfo) is dict and beforeinfo.get('schema')==SCHEMA and
         beforeinfo.get('race_id')==row['race_id'] and beforeinfo.get('body_identity_verified') is True,
         'BEFOREINFO_NATIVE_INPUT_BINDING')
    page=beforeinfo['context'];source=page['source']
    need(source['sha256']==beforeinfo['source_sha256'] and source['source_url']==beforeinfo['source_url'] and
         clock(source['captured_at'])==clock(beforeinfo['captured_at']),'BEFOREINFO_NATIVE_INPUT_BINDING')
    roster=_roster(row,program,at=source['captured_at'])
    context=dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=row['race_id'],
        cutoff_at=program['closed_at'],roster=roster,program=deepcopy(program),beforeinfo=deepcopy(page),
        pitreport=None,entry_history=None,forecast_inputs_used=False)
    live=dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',checked_at=checked_at,
        state='READY' if all(p.get('display_time') is not None for p in page['participants']) else 'AWAITING_EXHIBITION',
        reason=None,context=context,forecast_inputs_used=False)
    live['context']=_checked_live_context(row,live)
    return live

def _cutoff(row):
    values=[row.get('cutoff_at'),*row.get('saved_cutoff_variants',[])]
    return max((_source_time(v) for v in values if v),default=None)

def _context_clock(context):
    program=context.get('program')
    return (_source_time(program['captured_at']) if program else _source_time('0001-01-01T00:00:00Z'),
            _source_time(context['beforeinfo']['source']['captured_at']))

def collect_beforeinfo(state,rows,*,now,fetch,max_requests=4,programs=None,completion_clock=None):
    """Share the caller's client/budget; do not execute or rewrite a forecast."""
    now=clock(now);need(type(max_requests) is int and 1<=max_requests<=4,'BEFOREINFO_REQUEST_BOUND')
    control=state.control;checks=control.setdefault('beforeinfo_checks',{});captures=control.setdefault('beforeinfo_captures',{})
    need(programs is None or type(programs) is dict and len(programs)<=576,'BEFOREINFO_PROGRAM_BOUND')
    retained=control.get('beforeinfo_programs',{})
    day=now.astimezone(JST).date().isoformat();queue=[]
    for row in rows:
        rid=program=None
        try:
            rid=row['race_id'];beforeinfo_url(rid)
            if row.get('event_date_jst')!=day:continue
            item=checks.get(rid,{})
            live=row.get('live_boat_observation')
            need(live is None or type(live) is dict,'BEFOREINFO_LIVE_BINDING')
            context=(live or {}).get('context') or {}
            need(type(context) is dict,'BEFOREINFO_LIVE_BINDING')
            candidates=[(programs or {}).get(rid),context.get('program'),retained.get(rid)]
            program=next((value for value in candidates if value is not None),None)
            program=_latest_program(rid,candidates,at=now)
            if program is None and type(row.get('participants')) is list and 3<=len(row['participants'])<6:
                checks[rid]=dict(checked_at=now.isoformat(),next_at=(now+timedelta(minutes=15)).isoformat(),
                    state='SOURCE_ERROR',reason='BEFOREINFO_ACTIVE_PROGRAM_REQUIRED',finished=False)
                continue
            _roster(row,program,at=now)
            cutoff=clock(program['closed_at']) if program is not None else _cutoff(row)
            if cutoff is None or cutoff>now+timedelta(minutes=60):continue
            if program is not None and live is not None and (not item or
                    _source_time(live['checked_at'])>_source_time(item['checked_at'])):
                inherited=_checked_live_context(row,live,now=now)
                if inherited is not None and inherited.get('program')==program:
                    checked=clock(live['checked_at'])
                    item=dict(checked_at=live['checked_at'],next_at=(checked+timedelta(minutes=5)).isoformat(),
                        state=live['state'],reason=live.get('reason'),finished=False)
                    checks[rid]=item
            if item.get('next_at') and clock(item['next_at'])>now:continue
            # Refresh upcoming races; after the race, make at most one final
            # factual capture. Missing older current-day facts can backfill.
            if cutoff<=now and item.get('finished'):continue
            priority=0 if cutoff>now else 1
            last=clock(item['checked_at']) if item.get('checked_at') else now-timedelta(days=1)
            queue.append((priority,last,cutoff,rid,row,program))
        except (ValueError,KeyError,TypeError):
            if program is not None and type(rid) is str:
                checks[rid]=dict(checked_at=now.isoformat(),next_at=(now+timedelta(minutes=15)).isoformat(),
                    state='SOURCE_ERROR',reason='BEFOREINFO_PROGRAM_BINDING_REJECTED',finished=False)
            continue
    requests=parsed=rejected=0
    for _,_,cutoff,rid,row,program in sorted(queue,key=lambda item:item[:4]):
        if requests>=max_requests:break
        url=beforeinfo_url(rid)
        active=[control['waits'].get(key) for key in ('boatrace','boatrace-beforeinfo',url)]
        if any(wait and clock(wait['until'])>now for wait in active):continue
        requests+=1
        check=dict(checked_at=now.isoformat(),next_at=(now+timedelta(minutes=5)).isoformat(),state='SOURCE_ERROR',reason='BEFOREINFO_SOURCE_LAYOUT',finished=False)
        try:
            raw,at=fetch(url);at=clock(at)
            completed=_source_time(completion_clock()) if completion_clock else now
            need(now<=completed<=now+timedelta(minutes=5),'BEFOREINFO_COMPLETION_BOUND')
            check.update(checked_at=completed.isoformat(),next_at=(completed+timedelta(minutes=5)).isoformat())
            need(at<=(completed if program is not None or completion_clock else now+timedelta(minutes=5)) and
                 len(raw)<=MAX_BYTES,'BEFOREINFO_CAPTURE_BOUND')
            receipt=dict(source_url=url,source_sha256=sha(raw),captured_at=at.isoformat(),http_status=200)
            try:context=_parsed(row,raw,receipt,program)
            except (ValueError,KeyError,TypeError):
                state.remember('BEFOREINFO_REJECTED',raw,receipt);raise ValueError('BEFOREINFO_SOURCE_LAYOUT') from None
            captures[rid]=state.remember('BEFOREINFO',raw,receipt)
            if program is not None:
                retained=control.setdefault('beforeinfo_programs',{})
                retained[rid]=deepcopy(program)
            people=context['beforeinfo']['participants']
            complete=all(p.get('display_time') is not None and
                         (program is not None or p.get('exhibition_st_status') in ('OK','F','L')) for p in people)
            check.update(state='READY' if complete else 'AWAITING_EXHIBITION',reason=None,finished=cutoff<=completed and complete)
            parsed+=1
        except SourceWait as error:
            status=getattr(error,'plan',{}).get('http_status')
            key=url if status==404 else 'boatrace-beforeinfo' if status in (401,403) else 'boatrace'
            until=max(clock(error.retry_at),now+timedelta(minutes=5)).isoformat() if error.retry_at else (now+timedelta(minutes=5)).isoformat() if status==404 else '9999-12-31T23:59:59+00:00'
            control['waits'][key]=dict(until=until,reason=error.reason)
            check.update(state='SOURCE_WAIT',reason=error.reason,next_at=until)
        except (ValueError,KeyError,TypeError):
            rejected+=1;check['next_at']=(_source_time(check['checked_at'])+timedelta(minutes=15)).isoformat()
        checks[rid]=check
    # Historical ciphertext packets remain intact; the active queue is bounded
    # to the latest two days just like the existing result bridge.
    oldest=(now.astimezone(JST).date()-timedelta(days=1)).strftime('%Y%m%d')
    for collection in (checks,captures,retained):
        for rid in list(collection):
            if rid[:8]<oldest:del collection[rid]
    return dict(requests=requests,parsed=parsed,rejected=rejected)

def project_beforeinfo(row,state,*,now):
    """Interpret authenticated retained bytes without mutating any original."""
    now=clock(now);rid=row['race_id'];check=state.control.get('beforeinfo_checks',{}).get(rid)
    pointer=state.control.get('beforeinfo_captures',{}).get(rid)
    inherited=None;contexts=[]
    if row.get('live_boat_observation') is not None:
        try:
            inherited=deepcopy(row['live_boat_observation'])
            inherited['context']=_checked_live_context(row,inherited,now=now)
            if inherited['context'] is not None:contexts.append(inherited['context'])
        except (ValueError,KeyError,TypeError):inherited=None
    if check is None and pointer is None:return inherited
    if pointer:
        try:
            raw,receipt=state.capture(pointer);need(clock(receipt['captured_at'])<=now,'BEFOREINFO_FUTURE_CAPTURE')
            program=state.control.get('beforeinfo_programs',{}).get(rid)
            contexts.append(_parsed(row,raw,receipt,program))
        except (ValueError,KeyError,TypeError):pass
    context=max(contexts,key=_context_clock) if contexts else None
    if inherited is not None and (check is None or _source_time(inherited['checked_at'])>_source_time(check['checked_at'])):
        check=inherited
    check=check or dict(checked_at=pointer['captured_at'],state='SOURCE_ERROR',reason='BEFOREINFO_STATE_MISSING')
    if context is None and check['state']=='READY':
        check=dict(check,state='SOURCE_ERROR',reason='BEFOREINFO_SOURCE_LAYOUT')
    return dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',checked_at=check['checked_at'],state=check['state'],
        reason=check.get('reason'),context=context,forecast_inputs_used=False)
