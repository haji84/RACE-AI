"""Source-free prior-epoch wait for exactly the existing JRA and A/K captures.

This supplies no source authority. Original generators repeat their full MAC,
originals, baseline, interval and once admission after the physical wait.
"""
from datetime import datetime,timedelta,timezone
import math
import re
import time

from . import all_existing_model_official_issue as issue
from . import all_existing_model_future_source_capture as ak
from . import all_existing_model_future_source_once as ak_once
from . import jra_future_source_capture as horse
from .boat_all_model_store import MAX_WIRE

MAX_ARCHIVE=96*1024*1024


def profile(manifest):
    schema=manifest.get('schema') if type(manifest) is dict else None
    if schema==horse.SCHEMA:return horse,horse.PATH,horse.MarkerTransport
    if schema==ak.SCHEMA:return ak,ak_once.PATH,ak_once.FutureSourceMarkerTransport
    raise ValueError('ALL_MODEL_FUTURE_SOURCE_WAIT_SCHEMA')


def wait_for_prior_window(manifest,env,*,reader=None,marker_transport=None,clock=None,sleeper=None,monotonic=None):
    """Wait using public facts only; the unchanged generator must still admit.

    All prior runs must already be terminal. No source request, marker write,
    output file, owner-key lookup or capture status is performed here.
    """
    source,path,transport_type=profile(manifest)
    need=source.need
    def cutoff():
        values=[manifest['cutoff_at']] if manifest['schema']==horse.SCHEMA else [case['cutoff_at'] for case in manifest['cases']]
        return min(source.clock(value) for value in values)
    clock=clock or (lambda:datetime.now(timezone.utc));sleeper=sleeper or time.sleep;monotonic=monotonic or time.monotonic
    need(type(env.get('run_id')) is int and env['run_id']>0 and env.get('run_attempt')==1 and
        type(env.get('head_sha')) is str and re.fullmatch('[a-f0-9]{40}',env['head_sha']),'WAIT_CURRENT_RUN')
    start=monotonic();last_tick=start;last_utc=None;origin=None;origin_tick=None;expires=None;snapshots=0
    need(type(start) in (int,float) and math.isfinite(start),'WAIT_CLOCK')
    def moment():
        nonlocal last_tick,last_utc,origin,origin_tick
        tick=monotonic()
        need(type(tick) in (int,float) and math.isfinite(tick) and last_tick<=tick<=start+3605,'WAIT_BUDGET')
        now=clock();need(type(now) is datetime and now.utcoffset() is not None and
            (last_utc is None or last_utc<=now),'WAIT_CLOCK')
        if origin is None:origin=now;origin_tick=tick
        last_tick=tick;last_utc=now
        source.validate_manifest(manifest,now=now)
        need(now+timedelta(seconds=700)<=cutoff(),'WAIT_CAPTURE_MARGIN')
        if expires is not None:need(now<expires,'WAIT_EVIDENCE_EXPIRED')
        return now
    moment()
    transport=marker_transport or transport_type()
    # Existing fixed-host transport is single-attempt and never selects an
    # archived receipt. The final history() still authenticates original ZIPs.
    reader=reader or transport.json
    need(transport.read_file(transport.head(),path,MAX_WIRE) is None,'ONCE_ALREADY_CONSUMED')
    moment()
    def snapshot():
        nonlocal snapshots
        snapshots+=1;need(snapshots<=4,'WAIT_METADATA_REVISION_BOUND')
        latest=[];expiries=[]
        for pin in manifest['prior_journal_artifacts']:
            need(pin['run_id']!=env['run_id'],'WAIT_FRESH_CURRENT_RUN')
            actual=reader('actions/artifacts/'+str(pin['id']));now=moment()
            need(type(actual) is dict and actual.get('id')==pin['id'] and actual.get('digest')==pin['digest'] and
                actual.get('expired') is False and type(actual.get('size_in_bytes')) is int and
                0<actual['size_in_bytes']<=MAX_ARCHIVE and actual.get('name') in (
                    'official-result-collection-journal-'+str(pin['run_id']),
                    'official-future-source-capture-'+str(pin['run_id']),
                    'official-jra-future-source-capture-'+str(pin['run_id']),
                    'official-future-result-capture-'+str(pin['run_id'])),'WAIT_PRIOR_ARTIFACT')
            binding=actual.get('workflow_run',{})
            need(type(binding) is dict and binding.get('id')==pin['run_id'] and binding.get('head_sha')==pin['head_sha'] and
                all(type(binding.get(k)) is int and binding[k]==1416489937 for k in ('repository_id','head_repository_id')),
                'WAIT_PRIOR_ARTIFACT_SCOPE')
            saved=source.clock(actual['created_at']);expiry=source.clock(actual['expires_at'])
            need(saved<=now<expiry,'WAIT_PRIOR_ARTIFACT_CLOCK')
            run=issue.run_scope(reader('actions/runs/'+str(pin['run_id'])));moment()
            # Legacy UNKNOWN/cancelled epochs remain terminal evidence. Their
            # original outcome and MAC are checked by history(), not relabelled.
            need(run['id']==pin['run_id'] and run['head_sha']==pin['head_sha'] and run['status']=='completed',
                'WAIT_PRIOR_NOT_TERMINAL')
            updated=source.clock(run['updated_at'])
            need(source.clock(run['run_started_at'])<=saved+timedelta(seconds=1) and saved<=updated+timedelta(seconds=1),
                'WAIT_PRIOR_SAVE_CLOCK')
            latest.extend((updated,saved));expiries.append(expiry)
        return max(latest)+timedelta(seconds=3601),min(expiries)
    boundary,expires=snapshot();refreshed=False
    while True:
        now=moment()
        # A forward UTC jump cannot shorten a physical interval. Any updated
        # prior boundary uses the same initial UTC/monotonic origin and budget.
        ready_tick=origin_tick+max(0,(boundary-origin).total_seconds())
        need(ready_tick<=start+3605,'WAIT_BUDGET')
        need(boundary+timedelta(seconds=700)<=cutoff() and boundary<expires,
            'WAIT_WINDOW_UNAVAILABLE')
        remaining=max((boundary-now).total_seconds(),ready_tick-last_tick)
        if remaining<=0:
            if refreshed:return None
            boundary,expires=snapshot();refreshed=True
            continue
        budget=start+3605-last_tick;need(budget>0,'WAIT_BUDGET')
        sleeper(min(45,remaining,budget));refreshed=False
