"""Source-free national P1 coverage and experimental-video admission audit.

This is an isolated research gate, not a forecast writer, web client, or
independent evidence authenticator. It classifies caller-authenticated records
and returns only count-level statuses; it never upgrades a synthetic video
shadow to a production bet or changes a forecast original.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import re

from .actions_contract import digest
from .boat_video_model_context import validate_video_context

SCHEMA = 'RACE_AI_BOAT_NATIONAL_VIDEO_RESEARCH_GATE_V1'
JST = timezone(timedelta(hours=9))
_RACE = re.compile(r'([0-9]{8})-(0[1-9]|1[0-9]|2[0-4])-(0[1-9]|1[0-2])\Z')
_MODEL = re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_ERROR = 'BOAT_NATIONAL_VIDEO_RESEARCH_REJECTED'


def need(ok):
    if not ok:
        raise ValueError(_ERROR)


def instant(value):
    need(type(value) is str and len(value) <= 48)
    try:
        t = datetime.fromisoformat(value.replace('Z','+00:00'))
        need(t.utcoffset() is not None)
        return t
    except (ValueError,TypeError,OverflowError):
        raise ValueError(_ERROR) from None


def _scope(day, schedule):
    try:
        target = date.fromisoformat(day)
        need(type(day) is str and target.isoformat()==day)
        need(type(schedule) is list and 0 < len(schedule) <= 288)
        cutoffs={}
        for item in schedule:
            need(type(item) is dict and
                 type(item.get('race_id')) is str and
                 _RACE.fullmatch(item['race_id']) is not None and
                 item['race_id'][:8]==day.replace('-','') and
                 item['race_id'] not in cutoffs)
            cutoff=instant(item.get('cutoff_at'))
            need(cutoff.astimezone(JST).date()==target)
            cutoffs[item['race_id']]=cutoff
        return cutoffs
    except (TypeError,ValueError,OverflowError):
        raise ValueError(_ERROR) from None


def _originals(rows, stage, cutoffs, now):
    need(type(rows) is list and len(rows)<=15000)
    recorded={}
    for item in rows:
        need(type(item) is dict and item.get('stage')==stage)
        rid=item.get('race_id');mid=item.get('model_id')
        need(type(rid) is str and rid in cutoffs and
             type(mid) is str and _MODEL.fullmatch(mid) is not None)
        need(item.get('cutoff_at') is not None and
             instant(item['cutoff_at'])==cutoffs[rid])
        # Retain late/missing provenance as an explicit non-counting original,
        # rather than treating a missing clock as a pre-cutoff observation.
        try:
            generated=instant(item['as_of']);saved=instant(item['server_saved_at'])
            qualified=generated<=saved<cutoffs[rid] and saved<=now
        except (KeyError,TypeError,ValueError,OverflowError):
            qualified=False
        key=rid,mid
        # Different bytes/receipt clocks for one frozen slot are a conflict,
        # not a new version to silently choose by latest save time.
        if key in recorded:
            need(recorded[key][0]==item)
        else:
            recorded[key]=(item,qualified)
    return recorded


def _video_count(connections,cutoffs,now):
    need(type(connections) is list and len(connections)<=2048)
    races=set();slots=set()
    for connection in connections:
        need(type(connection) is dict and
             connection.get('schema_version')=='RACE_AI_BOAT_VIDEO_CONNECTION_V1' and
             connection.get('production_eligible') is False and
             connection.get('forecast_originals_modified') is False and
             connection.get('status')=='CONNECTED_EXPERIMENTAL' and
             type(connection.get('connection_sha256')) is str and
             _SHA.fullmatch(connection['connection_sha256']) is not None and
             connection['connection_sha256']==digest({k:v for k,v in connection.items()
                                                      if k!='connection_sha256'}))
        rid=connection.get('race_id')
        need(type(rid) is str and rid in cutoffs and
             instant(connection['cutoff_at'])==cutoffs[rid] and
             instant(connection['started_at'])<=instant(connection['completed_at'])<cutoffs[rid] and
             instant(connection['completed_at'])<=now)
        context=connection.get('video_context')
        need(type(context) is dict and
             context.get('eligible_for_research') is True and
             context.get('production_eligible') is False and
             context.get('prediction_eligible') is False and
             instant(context['as_of'])<=instant(connection['started_at']))
        checked=validate_video_context(context,race_id=rid,
                                       cutoff_at=connection['cutoff_at'],
                                       as_of=context['as_of'],roster=connection['roster'])
        need(checked==context)
        rows=connection.get('shadows')
        need(type(rows) is list and len(rows)>=1)
        for item in rows:
            need(type(item) is dict and
                 item.get('race_id')==rid and
                 item.get('cutoff_at')==connection['cutoff_at'] and
                 item.get('stage')=='P1' and
                 item.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL' and
                 item.get('production_eligible') is False and
                 item.get('auto_promoted') is False and
                 item.get('independent_human_heldout_verified') is False and
                 item.get('video_context_sha256')==context['context_sha256'] and
                 type(item.get('model_id')) is str and
                 _MODEL.fullmatch(item['model_id']) is not None and
                 type(item.get('prediction_sha256')) is str and
                 _SHA.fullmatch(item['prediction_sha256']) is not None and
                 item['prediction_sha256']==digest({k:v for k,v in item.items()
                                                    if k!='prediction_sha256'}) and
                 instant(item['as_of'])<cutoffs[rid])
            proof=item.get('video_receipt_proof')
            need(type(proof) is dict and proof.get('context_sha256')==context['context_sha256'] and
                 type(proof.get('id')) is int and proof['id']>0 and
                 type(proof.get('digest')) is str and
                 re.fullmatch(r'sha256:[0-9a-f]{64}',proof['digest']) is not None and
                 instant(proof['created_at'])<=instant(item['as_of']))
            slot=rid,item['model_id']
            need(slot not in slots)
            slots.add(slot)
        races.add(rid)
    return len(races),len(slots)


def audit(*,day,now,schedule,p0_rows,p1_rows,attempts,video_connections,
          expected_p1_models,official_schedule_authenticated=False,
          originals_authenticated=False):
    """Assess an authenticated *caller-supplied* schedule, no source or secrets.

    Even matching hashes in synthetic or declared records do not prove a real
    public source, physical video, recording rights, or independent storage.
    Production acceptance requires separate independent and licensed evidence.
    """
    need(isinstance(now,datetime) and now.utcoffset() is not None and
         type(official_schedule_authenticated) is bool and
         type(originals_authenticated) is bool)
    cutoffs=_scope(day,schedule)
    need(type(expected_p1_models) in (tuple,list) and
         0<len(expected_p1_models)<=128 and
         all(type(m) is str and _MODEL.fullmatch(m) for m in expected_p1_models) and
         len(set(expected_p1_models))==len(expected_p1_models))
    expected=set(expected_p1_models)
    p0=_originals(p0_rows,'P0',cutoffs,now)
    p1=_originals(p1_rows,'P1',cutoffs,now)
    need(all(mid in expected for rid,mid in p1))
    need(type(attempts) is list and len(attempts)<=15000)
    last={}
    for a in attempts:
        need(type(a) is dict and type(a.get('race_id')) is str and
             a['race_id'] in cutoffs and type(a.get('state')) is str and
             re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}',a['state']))
        last[a['race_id']]=a['state']
    videos,video_rows=_video_count(video_connections,cutoffs,now)
    p0_any={rid for rid,mid in p0 if p0[(rid,mid)][1]}
    p1_any={rid for rid,mid in p1}
    complete=set();missing=Counter();per_venue={}
    for rid in cutoffs:
        venue=rid[9:11]
        row=per_venue.setdefault(venue,dict(scheduled=0,p0=0,p1_any=0,p1_complete=0))
        row['scheduled']+=1
        if rid in p0_any:row['p0']+=1
        if rid in p1_any:row['p1_any']+=1
        saved={mid for key,(_,ok) in p1.items() if key[0]==rid and ok for mid in (key[1],)}
        if saved==expected:
            complete.add(rid);row['p1_complete']+=1
        elif rid in p1_any:
            rejected=any(not ok for (race,mid),(_,ok) in p1.items() if race==rid)
            missing['UNVERIFIED_OR_LATE_P1_ORIGINAL' if rejected else 'INCOMPLETE_MODEL_MATRIX']+=1
        else:
            state=last.get(rid,'NO_RETAINED_P1_ATTEMPT')
            # Accepted codes are the actual producer's safe state labels.
            missing[state]+=1
    # Count-level source audit is not independent source authentication.
    state=('HOLD_SOURCE_AUTHENTICATION_UNVERIFIED'
           if not (official_schedule_authenticated and originals_authenticated) else
           'HOLD_NATIONWIDE_P1_INCOMPLETE' if len(complete)<len(cutoffs) else
           'READY_FOR_INDEPENDENT_NATIONWIDE_ACCEPTANCE')
    return dict(schema=SCHEMA,state=state,day_jst=day,
        official_schedule_races=len(cutoffs),official_schedule_authenticated_claimed=official_schedule_authenticated,
        original_readback_authenticated_claimed=originals_authenticated,
        p0_races=len(p0_any),p0_original_slots=len(p0),p1_any_races=len(p1_any),
        p1_original_slots=len(p1),p1_complete_races=len(complete),
        p1_missing_races=len(cutoffs)-len(complete),p1_missing_reasons=dict(sorted(missing.items())),
        per_venue=dict(sorted(per_venue.items())),video_experimental_races=videos,
        video_experimental_rows=video_rows,video_production_proven=False,
        nationwide_p1_complete_proven=False,production_forecasts_changed=False,
        model_coefficients_changed=False,official_source_requests=0,
        experimental_video_not_promoted=True)
