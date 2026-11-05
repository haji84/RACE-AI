"""Bounded official nationwide cutoff-order A/B collection (no Vercel).

The authentic current-day nationwide index is verified using fixed PR64
source parser, one official racecard per active venue supplies all 12 cutoffs.
The existing strict PR64 beforeinfo parser validates each race independently.
Source HTML is never persisted. Research scores are untrained/uncalibrated;
external GitHub artifact created_at must still be checked before the cutoff.
This batch adds no scheduling. Request counts have no fixed numeric cap;
the existing source HTTP/identity guards and workload boundaries remain.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT/"pr64-reference"
if not (REF/"race_ai"/"official_day_schedule.py").is_file():
    raise SystemExit("PINNED_OFFICIAL_DAY_SOURCE_REQUIRED")
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(REF))
import race_ai
if str(REF/'race_ai') not in race_ai.__path__:
    race_ai.__path__.append(str(REF/'race_ai'))
from race_ai.core import SourceError
from race_ai.official_day_schedule import (
    endpoint as day_endpoint, parse_day_schedule)
from race_ai.official_racelist_adapter import (
    endpoint as racelist_endpoint, parse_official_racelist, MAX_BYTES, JST)
from race_ai.official_race_updates import (
    endpoint as preview_endpoint, parse_update)
from race_ai.tokuyama_day_worker import NoRedirects
from scripts.boat_actual_one_shot_probe import schedule as schedule_times
from scripts.boat_ab_future_pilot import motor_top2
import race_ai
race_ai.__path__.insert(0,str(ROOT/"race_ai"))
from race_ai.boat_deadline_queue import select_due_races
from race_ai.boat_freeze_index import load_original_race_ids
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.observed_p1_connection import build_bundle as build_observed_p1
OBSERVED_HISTORY_CONTEXT=None
ENTRY_OBSERVATION_HISTORY=None
supplemental_contexts={}
from race_ai.boat_manshu_watch import freeze_priced_tail
from race_ai.official_race_updates import endpoint as update_endpoint
from race_ai.source_retry_policy import SourceWait, plan_http_wait, wait_active

MODULE=importlib.util.spec_from_file_location("national_boat_pair",ROOT/"race_ai"/"boat_ab_shadow.py")
model=importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(model)

OUTPUT=ROOT/"boat_nationwide_output"
FROZEN_INDEX=ROOT/"docs/evidence/2026-11-03/boat-canonical-freeze-index.json"
REQUEST_CAP=None
VENUE_CAP=24
MAX_FORECASTS=None
MAX_ATTEMPTS=None
WAIT_SECONDS=0.15
MIN_TO_CUTOFF=timedelta(seconds=210)
requests_used=0
MAX_HTML=MAX_BYTES
SOURCE_GUARD=None
_HANDOFF_REASONS=frozenset(('DAY_HANDOFF','WORKER_HANDOFF'))


def _clock(day=None):
    now=datetime.now(timezone.utc)
    pinned=os.environ.get('RACE_AI_EVENT_DAY')
    expected=day.isoformat() if day is not None else pinned
    if pinned is not None:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',pinned):
            raise ValueError('EVENT_DAY_INVALID')
        try:parsed=datetime.fromisoformat(pinned+'T00:00:00+09:00').date()
        except ValueError:raise ValueError('EVENT_DAY_INVALID') from None
        if parsed.isoformat()!=pinned or (expected is not None and expected!=pinned):
            raise ValueError('DAY_HANDOFF')
        expected=pinned
    if expected is not None and now.astimezone(JST).date().isoformat()!=expected:
        raise ValueError('DAY_HANDOFF')
    return now


def _wait_record(wait):
    if isinstance(wait,dict):return dict(wait)
    return dict(state=wait.state,reason=wait.reason,retry_at=wait.retry_at)


class _PublicationWait(SourceWait):
    """A known race's unpublished exhibition; never an origin-wide pause."""
    def __init__(self,plan):
        self.plan=dict(plan)
        super().__init__(plan['reason'],plan['retry_at'],state=plan['state'])


def _publication_wait(race,now,plan=None):
    result=dict(plan or plan_http_wait(200,{},now,not_yet_published=True))
    result.update(race_id=race['race_id'],cutoff_at=race['cutoff_at'])
    # The last normal publication check should reach T-10 once, without
    # repeatedly scheduling an already-past target. Server waits are left
    # untouched (global429 waits never reach this per-race helper).
    target=datetime.fromisoformat(race['cutoff_at'])-timedelta(minutes=10)
    retry=result.get('retry_at')
    if retry and now<target and not result.get('server_retry_after'):
        result['retry_at']=min(datetime.fromisoformat(retry),target).isoformat()
    return result


def _candidate_waits(snapshot,rows):
    known={row['race_id']:row for row in rows}
    values=(snapshot or {}).get('candidate_source_waits',[])
    if not isinstance(values,list) or len(values)>24*12:
        raise ValueError('CANDIDATE_SOURCE_WAIT_INVALID')
    answer={}
    for value in values:
        if not isinstance(value,dict) or value.get('race_id') not in known:
            continue
        rid=value['race_id']
        if (rid in answer or value.get('state')!='WAITING_PUBLICATION'
                or value.get('reason')!='SOURCE_NOT_YET_PUBLISHED'
                or value.get('cutoff_at')!=known[rid]['cutoff_at']
                or value.get('retry_at') is None):
            raise ValueError('CANDIDATE_SOURCE_WAIT_INVALID')
        wait_active(value,_clock())
        answer[rid]=dict(value)
    return answer


def _next_check(rows,waits,now,*,frozen=frozenset(),paused=None):
    if paused is not None:return paused.get('retry_at')
    moments=[]
    for value in waits:
        retry=value.get('retry_at')
        if retry is not None:
            stamp=datetime.fromisoformat(retry)
            if stamp>now:moments.append(stamp)
    for row in rows:
        if row['race_id'] in frozen:continue
        cutoff=datetime.fromisoformat(row['cutoff_at'])
        for minutes in (15,10):
            target=cutoff-timedelta(minutes=minutes)
            if target>now:moments.append(target)
    return min(moments).isoformat() if moments else None


def observed_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def stop(reason, *, source=None, schedule=None, queue=None, tries=None,
         forecasts=None, extended=None, priced=None, observed=None,
         source_wait=None,candidate_waits=None,next_check_at=None,targets=None):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    result={
        "schema":"RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",
        "state":"OBSERVED_ATTEMPT_NO_FORECAST" if not forecasts else "FORECASTS_GENERATED_NEED_ARTIFACT_CLOCK_VERIFICATION",
        "reason":reason, "observed_at":observed_timestamp(),
        "source_request_count":requests_used,
        "source_request_cap":REQUEST_CAP,
        "event_day":os.environ.get('RACE_AI_EVENT_DAY'),
        "source_wait":source_wait,
        "candidate_source_waits":candidate_waits or [],
        "next_retry_at":source_wait.get('retry_at') if source_wait else next_check_at,
        "next_check_at":next_check_at,
        "deadline_targets":targets or {},
        "official_day_source":source,
        "verified_active_venues":schedule["active_venues"] if schedule else [],
        "verified_venue_count":len(schedule["active_venues"]) if schedule else 0,
        "official_race_registry":queue or [],
        "candidate_attempts":tries or [],
        "paired_forecasts":forecasts or [],
        "paired_forecast_count":len(forecasts or []),
        "additional_official_feature_shadows":extended or [],
        "observed_pairwise_p1_bundles":observed or [],
        "supplemental_boat_observations":list(supplemental_contexts.values()),
        "entry_observation_history":ENTRY_OBSERVATION_HISTORY,
        "official_priced_longshot_watches":priced or [],
        "research_only":True,
        "scores_calibrated":False,
        "history_tactical_features_admitted":False,
        "longshot_odds_verified":False,
        "external_artifact_preclose_verified":False,
        "live_continuous_collection_enabled":False,
        "vercel_used":False,
    }
    (OUTPUT/"national.json").write_text(
        json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False),
        encoding="utf-8")
    print(json.dumps({key:result.get(key) for key in (
        "state","reason","verified_venue_count","source_request_count",
        "paired_forecast_count")},ensure_ascii=False))
    return result


def get(url,*,day=None,not_yet_published=False,media='html'):
    global requests_used
    now=_clock(day)
    limit=MAX_HTML
    accepted=('text/html',)
    if media=='archive':
        from race_ai.official_archive_probe import official_url, MAX_ARCHIVE_BYTES
        prior=(day or now.astimezone(JST).date())-timedelta(days=1)
        if url not in (official_url(prior,'B'),official_url(prior,'K')):
            raise SourceError('ENTRY_ARCHIVE_SOURCE_IDENTITY_INVALID')
        limit=MAX_ARCHIVE_BYTES
        accepted=('application/octet-stream','application/x-lzh','application/x-lzh-compressed',
                  'application/x-lha','application/lzh')
    elif media!='html':raise ValueError('OFFICIAL_MEDIA_INVALID')
    if SOURCE_GUARD is not None:SOURCE_GUARD.charge("forecast")
    requests_used+=1
    req=request.Request(url,headers={"Accept":"text/html" if media=="html" else "application/octet-stream",
        "User-Agent":"RACE-AI-owner-reviewed-nationwide-pilot/1.0",
        "Cache-Control":"no-store"})
    try:
        with request.build_opener(NoRedirects()).open(req,timeout=12) as response:
            body=response.read(limit+1)
            if (response.status!=200 or response.geturl()!=url or len(body)==0
                    or len(body)>limit or
                    not ((response.headers.get("content-type") or "").split(";",1)[0].strip().lower() in accepted)):
                raise SourceError("OFFICIAL_RESPONSE_IDENTITY_OR_SIZE_INVALID")
            if media=='archive':
                from race_ai.official_archive_probe import inspect_lzh
                inspect_lzh(body)
    except error.HTTPError as exc:
        # An already-issued response can arrive after JST midnight. Preserve
        # its real server wait before the next transaction changes event day.
        now=datetime.now(timezone.utc)
        if exc.code==404 and not_yet_published:
            plan=plan_http_wait(exc.code,exc.headers,now,not_yet_published=True)
            plan['server_retry_after']=bool(exc.headers and
                (exc.headers.get('Retry-After') or exc.headers.get('retry-after')))
            raise _PublicationWait(plan) from None
        plan=(SOURCE_GUARD.http_failure(exc.code,headers=exc.headers)
              if SOURCE_GUARD is not None else plan_http_wait(exc.code,exc.headers,now))
        raise SourceWait(plan['reason'],plan['retry_at'],state=plan['state']) from None
    except (error.URLError,TimeoutError,OSError):
        now=datetime.now(timezone.utc)
        plan=(SOURCE_GUARD.http_failure(None,headers=None)
              if SOURCE_GUARD is not None else plan_http_wait(None,{},now))
        raise SourceWait(plan['reason'],plan['retry_at'],state=plan['state']) from None
    time.sleep(WAIT_SECONDS)
    captured=_clock(day)
    if SOURCE_GUARD is not None:SOURCE_GUARD.http_success()
    return body,captured,hashlib.sha256(body).hexdigest()


def official_schedule(day):
    url=day_endpoint(day)
    data,captured,sha=get(url,day=day)
    checked=parse_day_schedule(data,day=day,source_url=url,observed_at=captured.isoformat())
    if checked["status"]!="OFFICIAL_DAY_SCHEDULE_VERIFIED" or len(checked["active_venues"])>VENUE_CAP:
        raise SourceError("NATIONAL_INDEX_INCOMPLETE")
    return checked,captured,sha,url


def capture_before_context(raw, *, url, captured_at, race, boats):
    """Supplemental facts are not readiness, trained features or new picks."""
    from race_ai.boat_observation_context import parse_beforeinfo, eligibility_for_cutoff
    roster=[dict(lane=r['lane'],registration_number=r['racer_registration_id']) for r in boats]
    try:
        parsed=parse_beforeinfo(raw,source_url=url,captured_at=captured_at.isoformat(),
                                expected_race_id=race['race_id'],roster=roster)
        parsed.update(eligibility_for_cutoff(parsed,cutoff_at=race['cutoff_at']))
    except (ValueError,TypeError,KeyError,UnicodeError):
        return None
    return dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=race['race_id'],
        cutoff_at=race['cutoff_at'],roster=roster,beforeinfo=parsed,pitreport=None,
        entry_history=None,forecast_inputs_used=False)


def collect_pitreport(context,day,*,paused=None):
    """Use the same source guard, after ready inference, with a time margin."""
    if context is None or paused is not None:return paused
    cutoff=datetime.fromisoformat(context['cutoff_at'])
    from race_ai.boat_observation_context import parse_pitreport, eligibility_for_cutoff
    rid=context['race_id']
    url=f'https://www.boatrace.jp/owpc/pc/race/pitreport?rno={int(rid[-2:])}&jcd={rid[9:11]}&hd={rid[:8]}'
    try:
        if _clock(day)+2*MIN_TO_CUTOFF>=cutoff:
            context['pitreport_collection_status']='DEFERRED_TO_PRESERVE_FORECAST_TIME'
            return None
        raw,at,_=get(url,day=day)
        parsed=parse_pitreport(raw,source_url=url,captured_at=at.isoformat(),
                              expected_race_id=rid,roster=context['roster'])
        parsed.update(eligibility_for_cutoff(parsed,cutoff_at=context['cutoff_at']))
        context['pitreport']=parsed
        context['pitreport_collection_status']=parsed['status']
    except SourceWait as ex:
        context['pitreport_collection_status']='SOURCE_WAIT'
        return _wait_record(ex)
    except (SourceError,ValueError,TypeError,KeyError,UnicodeError) as ex:
        if str(ex)=='DAY_HANDOFF':raise
        if str(ex)=='WORKER_HANDOFF':
            context['pitreport_collection_status']='WORKER_HANDOFF'
            return dict(state='WORKER_HANDOFF',reason='WORKER_HANDOFF',retry_at=None)
        context['pitreport_collection_status']='SOURCE_OR_LAYOUT_REJECTED'
    return None


def collect_entry_history(context,day,*,paused=None):
    """Collect descriptive prior-day history after higher-priority race work."""
    global ENTRY_OBSERVATION_HISTORY
    if context is None or paused is not None:return paused
    from race_ai.boat_entry_source_collection import collect_previous_day_history, optional_cache_from_document
    from race_ai.boat_entry_observations import conditional_profile_before
    try:
        if _clock(day)+2*MIN_TO_CUTOFF>=datetime.fromisoformat(context['cutoff_at']):
            context['entry_history']=dict(profiles=[],collection_status='DEFERRED_TO_PRESERVE_FORECAST_TIME')
            return None
        candidate_cache=ENTRY_OBSERVATION_HISTORY
        _,rejection=optional_cache_from_document({'entry_observation_history':candidate_cache},day=day,as_of=_clock(day))
        if rejection is not None:ENTRY_OBSERVATION_HISTORY=None
        ENTRY_OBSERVATION_HISTORY=collect_previous_day_history(day,now=lambda:_clock(day),
            fetch=lambda url:get(url,day=day,media='archive',not_yet_published=True),
            cache=candidate_cache)
        cache=ENTRY_OBSERVATION_HISTORY
        profiles=[]
        if cache['status']=='READY':
            as_of=_clock(day).isoformat()
            profiles=[conditional_profile_before(cache['history'],as_of=as_of,
                racer_id=row['registration_number']) for row in sorted(context['roster'],key=lambda r:r['lane'])]
        context['entry_history']=dict(profiles=profiles,collection_status=cache['status'],
            history_day=cache['history_day'],missing_sources=cache['missing_sources'],source_wait=cache['source_wait'],
            rejected_cache_count=cache['rejected_cache_count'],cache_rejection_reason=cache['cache_rejection_reason'])
    except SourceWait as ex:
        context['entry_history']=dict(profiles=[],collection_status='SOURCE_WAIT',source_wait=_wait_record(ex))
        return _wait_record(ex)
    except (SourceError,ValueError,TypeError,KeyError,UnicodeError) as ex:
        if str(ex) in _HANDOFF_REASONS:
            context['entry_history']=dict(profiles=[],collection_status=str(ex))
            return dict(state=str(ex),reason=str(ex),retry_at=None)
        context['entry_history']=dict(profiles=[],collection_status='SOURCE_OR_LAYOUT_REJECTED')
    return None


def make_pair(day,race):
    race_id=race["race_id"];venue=race_id[9:11];n=int(race_id[-2:])
    now=_clock(day)
    cutoff=datetime.fromisoformat(race["cutoff_at"])
    if cutoff-now<=MIN_TO_CUTOFF:
        return {"race_id":race_id,"state":"TOO_LATE_BEFORE_SOURCE"},None,None,None,None
    url=racelist_endpoint(day,venue,n)
    raw,at,program_sha=get(url,day=day)
    try:
        program=parse_official_racelist(raw,day=day,venue=venue,race_no=n,
                         source_url=url,captured_at=at.isoformat())
    except SourceError:
        # Official SG navigation may exceed the pinned forecast adapter's
        # supported statistics layout. Strict metadata can still bind weather,
        # equipment and attributed comments without constructing model inputs.
        from race_ai.boat_observation_context import parse_program_roster
        metadata=parse_program_roster(raw,source_url=url,captured_at=at.isoformat(),expected_race_id=race_id)
        if metadata['race_id']!=race_id or metadata['source_cutoff_at']!=race['cutoff_at']:
            raise SourceError('PROGRAM_CONTEXT_IDENTITY_OR_CUTOFF_MISMATCH')
        if _clock(day)+MIN_TO_CUTOFF>=cutoff:
            return dict(race_id=race_id,state='TOO_LATE_BEFORE_SOURCE'),None,None,None,None
        official_preview_url=preview_endpoint(day,venue,n,'beforeinfo')
        preview,preview_at,preview_sha=get(official_preview_url,day=day,not_yet_published=True)
        roster=[dict(lane=row['lane'],racer_registration_id=row['registration_number'])
                for row in metadata['participants']]
        context=capture_before_context(preview,url=official_preview_url,captured_at=preview_at,race=race,boats=roster)
        if context is not None:supplemental_contexts[race_id]=context
        paused=collect_pitreport(context,day)
        paused=collect_entry_history(context,day,paused=paused)
        return dict(race_id=race_id,state='PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY',
                    program_sha256=program_sha,exhibition_sha256=preview_sha,source_wait=paused),None,None,None,None
    if (program["race_id"]!=race_id or program["closed_at"]!=race["cutoff_at"]
            or any(r["entry_status"]!="listed" for r in program["boats"])):
        return {"race_id":race_id,"state":"OFFICIAL_PROGRAM_OR_WITHDRAWAL_CONFLICT"},None,None,None,None
    motor=motor_top2(raw,program["boats"])
    official_preview_url=preview_endpoint(day,venue,n,"beforeinfo")
    _clock(day)
    preview,preview_at,preview_sha=get(official_preview_url,day=day,not_yet_published=True)
    context=capture_before_context(preview,url=official_preview_url,captured_at=preview_at,
                                   race=race,boats=program['boats'])
    if context is not None:supplemental_contexts[race_id]=context
    result=parse_update(preview,kind="beforeinfo",day=day,venue=venue,race_no=n,
                        source_url=official_preview_url,captured_at=preview_at.isoformat(),
                        entries=program["boats"])
    if result["status"]!="AVAILABLE" or result.get("data") is None:
        comment_wait=collect_pitreport(context,day)
        comment_wait=collect_entry_history(context,day,paused=comment_wait)
        return {"race_id":race_id,"state":"EXHIBITION_NOT_FULLY_PUBLISHED",
                "source_sha256":preview_sha,
                "source_wait":comment_wait or _publication_wait(race,_clock(day))},None,None,None,None
    six=sorted(result["data"]["boats"],key=lambda r:r["lane"])
    if len(six)!=6 or any(r["display_time"] is None for r in six):
        comment_wait=collect_pitreport(context,day)
        comment_wait=collect_entry_history(context,day,paused=comment_wait)
        return {"race_id":race_id,"state":"EXHIBITION_TIME_INCOMPLETE",
                "source_wait":comment_wait or _publication_wait(race,_clock(day))},None,None,None,None
    entrants={r["lane"]:r for r in program["boats"]}
    boats=[]
    for measured in six:
        known=entrants[measured["lane"]]
        if known["racer_registration_id"]!=measured["racer_registration_id"]:
            raise SourceError("SIX_BOAT_REGISTRATION_MISMATCH")
        boats.append({
            "lane":measured["lane"],
            "racer_id":known["racer_registration_id"],
            "national_win_rate":known["national_win_rate"],
            "exhibition_time_seconds":measured["display_time"],
            "motor_two_place_rate_percent":motor[measured["lane"]],
        })
    generated=observed_timestamp()
    data={
        "race_id":race_id, "cutoff_at":race["cutoff_at"],
        "captured_at":max(at,preview_at).isoformat(timespec="microseconds"),
        "program_source_sha256":program_sha,
        "beforeinfo_source_sha256":preview_sha,
        "boats":boats,
    }
    _clock(day)
    computed=model.build_pair(data,generated)
    if _clock(day)+MIN_TO_CUTOFF>=cutoff:
        return {"race_id":race_id,"state":"TOO_LATE_AFTER_MODEL"},None,None,None,None
    # C-lite uses the *same official observations*, including local rate and
    # the already published historical average ST. It remains separate from
    # frozen A/B and is never misrepresented as a tactical history model.
    extra={
        "race_id":race_id,
        "observed_at":preview_at.isoformat(timespec="microseconds"),
        "source_sha256":hashlib.sha256((program_sha+preview_sha).encode()).hexdigest(),
        "participants":[{
            "lane":r["lane"],"racer_id":r["racer_registration_id"],
            "local_win_rate":r["local_win_rate"],
            "average_st":r["average_st"],
            "exhibition_st":next(x for x in six if x["lane"]==r["lane"])["preview_st"],
            "exhibition_st_status":next(x for x in six if x["lane"]==r["lane"])["preview_st_status"],
        } for r in program["boats"]],
    }
    extended=None
    try:
        if _clock(day)+MIN_TO_CUTOFF>=cutoff:
            return {"race_id":race_id,"state":"TOO_LATE_BEFORE_MODEL"},None,None,None,None
        extended=build_live_feature_shadow(data,extra,observed_timestamp())
    except ValueError as ex:
        if str(ex) in _HANDOFF_REASONS:raise
        extended={"race_id":race_id,"state":"C_LITE_SOURCE_NOT_ADMITTED"}
    # Reuse the existing pairwise models on these same fresh observations.
    # A failure isolated to this adapter does not discard the ready A/B pair.
    observed=None
    try:
        if _clock(day)+MIN_TO_CUTOFF>=cutoff:
            return {"race_id":race_id,"state":"TOO_LATE_BEFORE_MODEL"},None,None,None,None
        history_options={} if OBSERVED_HISTORY_CONTEXT is None else {"history_context":OBSERVED_HISTORY_CONTEXT}
        observed=build_observed_p1(data,extra,generated,
            program_url=url,preview_url=official_preview_url,
            program_captured_at=at.isoformat(),preview_captured_at=preview_at.isoformat(),
            owner_reviewed=os.environ.get("RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED")=="true",**history_options)
    except ValueError as ex:
        if str(ex) in _HANDOFF_REASONS:raise
        observed={"race_id":race_id,"state":"OBSERVED_P1_INPUT_REJECTED","reason":str(ex)[:160]}
    # A man-shu is >=10,000 yen for a 100-yen ticket. Do NOT infer it
    # from a low model score. Require 120 published official odds before the
    # relevant cutoff and label the priced research variant separately.
    priced={"race_id":race_id,"state":"OFFICIAL_PRE_CLOSE_PRICES_NOT_VERIFIED"}
    paused=None
    if _clock(day)+MIN_TO_CUTOFF<cutoff:
        try:
            price_url=update_endpoint(day,venue,n,"odds3t")
            odds_raw,odds_at,odds_sha=get(price_url,day=day)
            odds=parse_update(odds_raw,kind="odds3t",day=day,venue=venue,race_no=n,
                              source_url=price_url,captured_at=odds_at.isoformat(),
                              entries=program["boats"])
            old_pair={"schema":"RACE_AI_BOAT_LIVE_AB_RESEARCH_V1",
                      "status":"REAL_TWO_MODEL_PAIR_GENERATED_UNVERIFIED_ARTIFACT",
                      "race_id":race_id,"cutoff_at":race["cutoff_at"],
                      "result_used":False,"paired_forecast":computed}
            priced=freeze_priced_tail(old_pair,odds,observed_timestamp())
        except SourceWait as ex:
            paused=_wait_record(ex)
            priced={"race_id":race_id,"state":"SOURCE_WAIT","source_wait":paused}
        except (SourceError,ValueError,KeyError,TypeError) as ex:
            if str(ex)=='DAY_HANDOFF':raise
            if str(ex)=='WORKER_HANDOFF':
                paused=dict(state='WORKER_HANDOFF',reason='WORKER_HANDOFF',retry_at=None)
                priced=dict(race_id=race_id,state='WORKER_HANDOFF')
            else:
                priced={"race_id":race_id,"state":"OFFICIAL_PRE_CLOSE_PRICES_NOT_VERIFIED",
                        "failure_class":type(ex).__name__}
    if _clock(day)+MIN_TO_CUTOFF>=cutoff:
        return {"race_id":race_id,"state":"TOO_LATE_AFTER_MODEL"},None,None,None,None
    paused=collect_pitreport(context,day,paused=paused)
    paused=collect_entry_history(context,day,paused=paused)
    return {"race_id":race_id,"state":"AB_GENERATED_NOT_YET_EXTERNAL_FROZEN",
            "program_sha256":program_sha,"exhibition_sha256":preview_sha,
            "generated_at":generated,"source_wait":paused},computed,extended,priced,observed


def run(*, schedule_snapshot=None):
    global requests_used, ENTRY_OBSERVATION_HISTORY
    requests_used=0
    supplemental_contexts.clear()
    if os.environ.get("RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED")!="true":
        return stop("OWNER_SOURCE_SCOPE_REQUIRED")
    try:now=_clock()
    except ValueError as ex:return stop(str(ex))
    day=now.astimezone(JST).date()
    if ENTRY_OBSERVATION_HISTORY is not None and (not isinstance(ENTRY_OBSERVATION_HISTORY,dict)
            or ENTRY_OBSERVATION_HISTORY.get('event_day')!=day.isoformat()):
        ENTRY_OBSERVATION_HISTORY=None
    paused=None
    from race_ai.repeated_cycle import usable_schedule
    if usable_schedule(schedule_snapshot,day=day.isoformat(),now=now):
        import copy
        cached=copy.deepcopy(schedule_snapshot)
        source=cached['official_day_source']
        listing={'active_venues':cached['verified_active_venues']}
        index_at=datetime.fromisoformat(source['captured_at'])
        index_sha=source['source_sha256'];url=source['url']
        active=listing['active_venues'];rows=cached['official_race_registry'];venue_errors=[]
    else:
        try:
            listing,index_at,index_sha,url=official_schedule(day)
        except SourceWait as ex:
            paused=_wait_record(ex)
            return stop(ex.reason,source_wait=paused,next_check_at=ex.retry_at)
        except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
            if str(ex) in _HANDOFF_REASONS:return stop(str(ex))
            return stop("VERIFIED_DAY_SOURCE_UNAVAILABLE",
                        source={"failure_class":type(ex).__name__})
        active=listing["active_venues"]
        rows=[];venue_errors=[]
        # One verified 12R closing schedule per active venue. Source is original,
        # not inferred from a cached website snippet or the race's number.
        for venue in active:
            try:
                source_url=racelist_endpoint(day,venue,1)
                body,at,sha=get(source_url,day=day)
                metadata=None
                try:
                    identity=parse_official_racelist(body,day=day,venue=venue,race_no=1,
                         source_url=source_url,captured_at=at.isoformat())
                    if identity["status"]!="OFFICIAL_BODY_IDENTITY_VERIFIED":
                        raise SourceError("RACELIST_IDENTITY_UNVERIFIED")
                except SourceError:
                    from race_ai.boat_observation_context import parse_program_roster
                    metadata=parse_program_roster(body,source_url=source_url,captured_at=at.isoformat(),
                        expected_race_id=f'{day:%Y%m%d}-{venue}-01')
                times=schedule_times(body,day,venue)
                if (metadata is not None and set(times)!=set(range(1,13)) or any(closed.utcoffset()!=timedelta(hours=9)
                        or closed.date()!=day for closed in times.values())
                        or metadata is not None and times[1].isoformat()!=metadata['source_cutoff_at']):
                    raise SourceError('VENUE_SCHEDULE_CONTEXT_IDENTITY_INVALID')
                if metadata is not None:
                    venue_errors.append(dict(venue=venue,state='VENUE_PROGRAM_STATS_UNSUPPORTED_CONTEXT_ONLY'))
                for no,closed in times.items():
                    rows.append({"race_id":f"{day:%Y%m%d}-{venue}-{no:02d}",
                                 "cutoff_at":closed.isoformat(),
                                 "schedule_captured_at":at.isoformat(),
                                 "source_sha256":sha})
            except SourceWait as ex:
                paused=_wait_record(ex)
                venue_errors.append({'venue':venue,'state':ex.state,'reason':ex.reason})
                break
            except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
                if str(ex) in _HANDOFF_REASONS:return stop(str(ex),schedule=listing,tries=venue_errors)
                venue_errors.append({"venue":venue,"state":"VENUE_SCHEDULE_REJECTED",
                                     "failure_class":type(ex).__name__})
    if not rows:
        return stop(paused['reason'] if paused else "NO_VERIFIED_CUTOFF_ROWS",schedule=listing,
                    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat()},
                    tries=venue_errors,source_wait=paused,
                    next_check_at=paused.get('retry_at') if paused else None)
    # The verified day registry contains already-closed morning races. A
    # schedule captured this afternoon is NOT pre-close evidence for a race
    # that finished in the morning. Retain these in the registry/audit count,
    # but never submit them to the pre-close queue or pretend a forecast.
    try:selection_clock=_clock(day)
    except ValueError as ex:return stop(str(ex),schedule=listing,queue=rows,tries=venue_errors)
    prospective_rows=[]
    after_close_rows=[]
    for record in rows:
        cutoff=datetime.fromisoformat(record["cutoff_at"])
        captured=datetime.fromisoformat(record["schedule_captured_at"])
        if cutoff<=selection_clock or captured>=cutoff:
            after_close_rows.append({
                "race_id":record["race_id"],
                "reason":"ALREADY_CLOSED_BEFORE_SCHEDULE_CAPTURE"})
        else:
            prospective_rows.append(record)
    try:
        # Same race may have been frozen by the Miyajima or nationwide
        # previous pilot. Use one canonical reviewed index of original IDs
        # to skip it rather than issuing a second post-exhibition forecast.
        # This is bookkeeping only: each new artifact still needs external
        # saved_at and SHA readback, and a live CAS store is not deployed.
        previously_frozen=load_original_race_ids(
            FROZEN_INDEX,as_of=selection_clock.isoformat())
        queue=select_due_races(prospective_rows,selection_clock.isoformat(),
                              already_frozen=previously_frozen,max_items=None)
        race_waits=_candidate_waits(schedule_snapshot,rows)
    except (OSError, ValueError, UnicodeError) as ex:
        if str(ex) in _HANDOFF_REASONS:return stop(str(ex),schedule=listing,queue=rows,tries=venue_errors)
        return stop("NATIONWIDE_ORDER_VALIDATION_REJECTED",schedule=listing,
                    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat()},
                    tries=venue_errors)
    attempts=list(after_close_rows)
    attempts.extend({"race_id":r["race_id"],"state":"ALREADY_FROZEN_IN_CANONICAL_INDEX"}
                    for r in queue["rejected"] if r["reason"]=="ALREADY_FROZEN")
    forecasts=[];extra_forecasts=[];priced_watches=[];observed_forecasts=[]
    handoff=False;handoff_reason='DAY_HANDOFF'
    for race in queue["eligible"]:
        if paused is not None:break
        rid=race['race_id']
        try:
            at=_clock(day)
            if rid in race_waits and wait_active(race_waits[rid],at):
                attempts.append(dict(race_id=rid,state='WAITING_PUBLICATION',
                                     source_wait=race_waits[rid],phase=race.get('phase')))
                continue
            status,pair,extended,priced,observed=make_pair(day,race)
            status.update(phase=race.get('phase'),cutoff_at=race['cutoff_at'],
                          target_at=(datetime.fromisoformat(race['cutoff_at'])-timedelta(minutes=10)).isoformat())
            if observed is not None and 'suite' not in observed:
                status['observed_pairwise_failure']=observed
            wait=status.get('source_wait')
            if pair is None and status.get('state') in ('EXHIBITION_NOT_FULLY_PUBLISHED','EXHIBITION_TIME_INCOMPLETE'):
                wait=wait or _publication_wait(race,_clock(day))
                status['source_wait']=wait
            if wait is not None:
                if wait.get('state')=='WAITING_PUBLICATION':race_waits[rid]=dict(wait)
                else:paused=dict(wait)
            attempts.append(status)
            if pair is not None:
                race_waits.pop(rid,None)
                forecasts.append(pair)
                if extended is not None:extra_forecasts.append(extended)
                if priced is not None:priced_watches.append(priced)
                if observed is not None and "suite" in observed:observed_forecasts.append(observed)
        except _PublicationWait as ex:
            try:at=_clock(day)
            except ValueError as control:
                if str(control)!='DAY_HANDOFF':raise
                attempts.append(dict(race_id=rid,state='DAY_HANDOFF'))
                handoff=True
                break
            wait=_publication_wait(race,at,ex.plan)
            race_waits[rid]=wait
            attempts.append(dict(race_id=rid,state='WAITING_PUBLICATION',source_wait=wait,phase=race.get('phase')))
        except SourceWait as ex:
            paused=_wait_record(ex)
            attempts.append(dict(race_id=rid,state=ex.state,reason=ex.reason,source_wait=paused))
            break
        except (SourceError,ValueError,UnicodeError,OSError,error.URLError,TimeoutError,TypeError) as ex:
            if str(ex) in _HANDOFF_REASONS:
                handoff_reason=str(ex)
                attempts.append(dict(race_id=rid,state=handoff_reason))
                handoff=True
                break
            attempts.append({"race_id":race["race_id"],"state":"OFFICIAL_RACE_REJECTED",
                             "failure_class":type(ex).__name__})
    # If the externally saved batch is late, the independent GitHub artifact
    # verifier must disqualify that race, never present it as pre-cutoff.
    source={"url":url,"source_sha256":index_sha,"captured_at":index_at.isoformat(),
            "active_venues":active}
    compact=[{key:item[key] for key in ("race_id","cutoff_at","schedule_captured_at","source_sha256")}
            for item in rows]
    try:_clock(day)
    except ValueError as ex:
        if str(ex)!='DAY_HANDOFF':raise
        handoff=True
    remaining_waits=[value for rid,value in sorted(race_waits.items())
                     if datetime.fromisoformat(value['cutoff_at'])>datetime.now(timezone.utc)+MIN_TO_CUTOFF]
    targets=dict(window_open_seconds=900,target_before_cutoff_seconds=600,
        minimum_buffer_seconds=int(MIN_TO_CUTOFF.total_seconds()),due_races=len(queue['eligible']),
        window_races=sum(r.get('phase')=='WINDOW' for r in queue['eligible']),
        late_fallback_races=sum(r.get('phase')=='LATE_INPUT_FALLBACK' for r in queue['eligible']),
        waiting_publication_races=len(remaining_waits),forecast_pairs=len(forecasts),
        external_target_save_verified=False)
    next_check=None if handoff else _next_check(rows,remaining_waits,datetime.now(timezone.utc),
        frozen=previously_frozen|frozenset(p['race_id'] for p in forecasts),paused=paused)
    reason=(handoff_reason if handoff else paused['reason'] if paused else
            'NEEDS_INDEPENDENT_GITHUB_ARTIFACT_TIME_CHECK' if forecasts else
            'NO_COMPLETE_EXHIBITION_IN_ORDERED_CANDIDATES')
    return stop(reason,
                source=source,schedule=listing,
                queue=compact,tries=venue_errors+attempts,forecasts=forecasts,
                extended=extra_forecasts,priced=priced_watches,observed=observed_forecasts,
                source_wait=paused,candidate_waits=remaining_waits,next_check_at=next_check,targets=targets)


if __name__=="__main__":
    run()
