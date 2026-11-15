"""Schedule-to-screen bridge for 3–6 active BOAT entries (research only).

The BOATCAST venue replay page URL is a *candidate*, not a race-specific
video identity. A distinct verifier must observe the correct selected day,
venue and race in the live DOM before record_screen permits a capture.
No GET, recording, model inference, or video publication occurs in plan().
"""
from datetime import datetime, timedelta
from hashlib import sha256
import re

from .boat_national_video_research_gate import JST, instant, _RACE
from .boat_screen_record_research import record_screen

_SCHEMA='RACE_AI_BOAT_VIDEO_SCREEN_QUEUE_V1'
_MODEL_GUARD='HOLD_NOT_REAL_VIDEO_FORECAST'
_SHA=re.compile(r'[a-f0-9]{64}\Z')
_REG=re.compile(r'[0-9]{4}\Z')


def _require(ok):
    if not ok:
        raise ValueError('BOAT_VIDEO_SCREEN_QUEUE_REJECTED')


def _active(roster):
    _require(type(roster) is list and 3<=len(roster)<=6)
    lanes=set()
    active=[]
    for item in roster:
        _require(type(item) is dict and set(item)==
                 {'lane','registration_number','entry_status'})
        lane=item['lane'];rid=item['registration_number']
        _require(type(lane) is int and 1<=lane<=6 and lane not in lanes and
                 type(rid) is str and _REG.fullmatch(rid) is not None and
                 item['entry_status'] in ('listed','withdrawn'))
        lanes.add(lane)
        if item['entry_status']=='listed':
            active.append((lane,rid))
    active.sort()
    # Missing and withdrawn lanes must never be silently renumbered.
    return active


def plan(schedule, *, day, now):
    _require(type(day) is str and
             isinstance(now,datetime) and now.utcoffset() is not None and
             type(schedule) is list and 0<len(schedule)<=288)
    _require(re.fullmatch('20[0-9]{2}-[01][0-9]-[0-3][0-9]',day) is not None)
    _require(datetime.strptime(day,'%Y-%m-%d').date().isoformat()==day)
    _require(now.astimezone(JST).date().isoformat()==day)
    ready=[];holds={};seen=set()
    for row in schedule:
        _require(type(row) is dict and set(row)==
                 {'race_id','cutoff_at','roster','program_sha256','program_captured_at',
                  'race_status'})
        rid=row['race_id']
        _require(type(rid) is str and _RACE.fullmatch(rid) is not None and
                 rid[:8]==day.replace('-','') and rid not in seen)
        seen.add(rid)
        cutoff=instant(row['cutoff_at'])
        captured=instant(row['program_captured_at'])
        _require(cutoff.astimezone(JST).date().isoformat()==day and
                 type(row['program_sha256']) is str and
                 _SHA.fullmatch(row['program_sha256']) is not None and
                 captured<=now and captured<cutoff and
                 row['race_status'] in ('LISTED','CANCELLED'))
        active=_active(row['roster'])
        if row['race_status']!='LISTED' or len(active)<3:
            holds['RACE_INELIGIBLE_OR_LESS_THAN_THREE_ACTIVE']=holds.get(
                'RACE_INELIGIBLE_OR_LESS_THAN_THREE_ACTIVE',0)+1
            continue
        margin=(cutoff-now).total_seconds()
        if margin>900:
            holds['BEFORE_T_MINUS_15']=holds.get('BEFORE_T_MINUS_15',0)+1
            continue
        if margin<600:
            holds['AFTER_T_MINUS_10']=holds.get('AFTER_T_MINUS_10',0)+1
            continue
        venue=rid[9:11]
        # BOATCAST venue-level page, not a verified per-race video URL.
        # The live DOM selector must still bind the exact race+date.
        url=f'https://race.boatcast.jp/replay?jo={venue}&md=T'
        source=dict(schema='RACE_AI_BOAT_SCREEN_SOURCE_V1',
                    race_id=rid,cutoff_at=row['cutoff_at'],
                    page_url=url,mode='REPLAY',play_selector=None)
        ready.append(dict(race_id=rid,active_lanes=[lane for lane,_ in active],
                          roster=[dict(lane=lane,registration_number=reg)
                                  for lane,reg in active],
                          program_sha256=row['program_sha256'],
                          source=source,
                          requires_actual_dom_race_identity=True,
                          video_prediction_eligible=False,
                          producer_original_changed=False))
    ready.sort(key=lambda r:(instant(r['source']['cutoff_at']),r['race_id']))
    return dict(schema=_SCHEMA,state='RESEARCH_SOURCE_CANDIDATES_NEED_DOM_PROOF',
                day_jst=day,schedule_races=len(schedule),
                candidate_races=len(ready),
                held_races=len(schedule)-len(ready),
                hold_reasons=dict(sorted(holds.items())),
                candidates=ready,official_video_playback_proven=False,
                independent_boat_identity_proven=False,
                nationwide_p1_proven=False,source_requests=0,
                forecast_originals_modified=False)


async def capture_first(browser, queue, *, now, aes_key, verify_page_identity,
                        timeout_seconds=30):
    """Execute exactly one candidate with the existing sealed recorder.

    This is the bridge missing from the source-free scheduler; it cannot
    skip actual DOM identity verification, invent video or promote a P1.
    """
    _require(type(queue) is dict and queue.get('schema')==_SCHEMA and
             type(queue.get('candidates')) is list and
             isinstance(now,datetime) and now.utcoffset() is not None)
    if not callable(verify_page_identity):
        return dict(status='HOLD_REAL_DOM_IDENTITY_CALLBACK_REQUIRED',
                    source_requests=0,video_prediction_eligible=False)
    if not queue['candidates']:
        return dict(status='HOLD_NO_VIDEO_CAPTURE_WINDOW',
                    source_requests=0,video_prediction_eligible=False)
    candidate=queue['candidates'][0]
    _require(candidate['requires_actual_dom_race_identity'] is True and
             candidate['video_prediction_eligible'] is False and
             candidate['producer_original_changed'] is False and
             len(candidate['active_lanes'])>=3 and
             len(set(candidate['active_lanes']))==len(candidate['active_lanes']))
    result=await record_screen(browser,candidate['source'],now=now,
                               aes_key=aes_key,
                               verify_page_identity=verify_page_identity,
                               timeout_seconds=timeout_seconds)
    # The encrypted envelope remains local/private. The caller needs a
    # separate verified private vault for persistence and independent SHA.
    return dict(result,active_lanes=list(candidate['active_lanes']),
                video_prediction_eligible=False,
                production_video_forecast_proven=False,
                originals_unchanged=True)
