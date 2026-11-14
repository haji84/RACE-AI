"""Fresh future-card orchestration contracts; no provider or credential lookup.

The Actions caller authenticates actual GitHub transports. Original source clocks
remain independent of later encryption/readback clocks. Historical UNKNOWN is
retained, never converted into a zero-request epoch or a new recovery grant.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import re
from urllib.parse import urlsplit

from .actions_contract import digest
from . import official_future_source_packet as builder
from . import all_existing_model_official_recovery as recovery
from . import all_existing_model_official_probe16 as prior
from . import all_existing_model_official_continuation as continuation
from . import manual_official_capture as policy
from .all_existing_model_future_baseline import validate_pin
from .four_sport_learning import LEARNED_ID

SCHEMA='RACE_AI_OFFICIAL_FUTURE_SOURCE_CAPTURE_INPUT_V1'
JOURNAL='RACE_AI_OFFICIAL_FUTURE_SOURCE_JOURNAL_V1'
STATUS='RACE_AI_OFFICIAL_FUTURE_SOURCE_CAPTURE_COUNTS_V1'
ROUND=900025
SPORTS={'autorace','keirin'}
clock=builder._clock


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_FUTURE_SOURCE_'+reason)


def validate_manifest(value,*,now):
    now=clock(now);day=now.astimezone(policy.JST).date().isoformat()
    fields={'schema','execution_day','cases','terms_manifest','maximum_requests','baseline_artifacts',
            'carrier_artifact','prior_journal_artifacts'}
    need(type(value) is dict and set(value)==fields and value['schema']==SCHEMA and
        value['execution_day']==day and type(value['maximum_requests']) is int and
        value['maximum_requests']==32,'MANIFEST_SCHEMA_DAY_OR_BOUND')
    cases=value['cases'];need(type(cases) is list and len(cases)==2 and
        {c.get('sport') for c in cases if type(c) is dict}==SPORTS,'EXACT_TWO_SPORT_CASES')
    for case in cases:
        fields={'sport','race_id','ui_entry_url','expected_date','venue','race_no','cutoff_at'}
        need(fields<=set(case)<=fields|{'ui_venue_name','place_code'},'CASE_SCHEMA')
        sport=case['sport'];venue=case['venue'];url=urlsplit(case['ui_entry_url'])
        policy.validate_source_pair(case['ui_entry_url'],policy.official_rights_ref(sport))
        need(not url.query and not url.fragment and not url.port and case['expected_date']==day and
            type(case['race_no']) is int and 1<=case['race_no']<=12 and
            case['race_id']==f"{sport}:{day}:{venue}:{case['race_no']}" and
            clock(case['cutoff_at']).astimezone(policy.JST).date().isoformat()==day,'CASE_IDENTITY')
        if sport=='autorace':
            need(venue in ('isesaki','kawaguchi','hamamatsu','iizuka','sanyou') and
                url.path=='/race_info/Live/'+venue,'PUBLISHED_NORMAL_UI')
            code=case.get('place_code',{'isesaki':3,'kawaguchi':2}.get(venue))
            need(type(code) is int and 1<=code<=20 and
                (venue not in ('isesaki','kawaguchi') or code=={'isesaki':3,'kawaguchi':2}[venue]),'SAVED_PLACE_CODE')
        else:
            need(type(venue) is str and re.fullmatch('keirin-jyo-[0-9]{2}',venue) and
                url.path=='/pc/top' and 'place_code' not in case,'PUBLISHED_NORMAL_UI')
        if 'ui_venue_name' in case:
            name=case['ui_venue_name'];need(type(name) is str and 1<=len(name)<=80 and
                name.strip()==name and not re.search('[<>\r\n]',name),'UI_VENUE_NAME')
    pins=value['baseline_artifacts'];need(type(pins) is dict and set(pins)==SPORTS,'BASELINE_SPORT_PINS')
    for pin in pins.values():validate_pin(pin)
    carrier=validate_pin(value['carrier_artifact'])
    need(all(p['id']!=carrier['id'] for p in pins.values()),'DISTINCT_CARRIER')
    from scripts.all_existing_model_official_result_collect import _pins
    _pins(value['prior_journal_artifacts'])
    need(not {carrier['id'],*(p['id'] for p in pins.values())}&
        {p['id'] for p in value['prior_journal_artifacts']},'DISTINCT_HISTORY_PINS')
    terms=value['terms_manifest'];urls=[u for term in terms['terms'] for u in term['source_urls']]
    policy._terms(terms,urls,day,now)
    need({term['sport'] for term in terms['terms']}==SPORTS,'EXACT_TERMS_SPORTS')
    return deepcopy(value)


def authenticate_future_history(manifest,*,journal_archives,old_run,prior_runs,now,key,current_run=None):
    """Admit all exact pinned result journals without consuming expired grants."""
    now=clock(now);pins=manifest['prior_journal_artifacts']
    from scripts.all_existing_model_official_result_collect import _pins
    _pins(pins)
    fixed=[p for p in pins if p['id']==recovery.OLD_ARTIFACT]
    need(len(fixed)==1 and fixed[0]['run_id']==recovery.OLD_RUN and fixed[0]['head_sha']==recovery.OLD_HEAD,
        'FIXED_UNKNOWN_PIN')
    archives=continuation._archive_map(journal_archives,pins)
    old=archives[recovery.OLD_ARTIFACT]
    # Later fresh-card epochs join the same append-only explicit pin closure.
    # Their own complete wire is authenticated; no source day or UNKNOWN resets.
    result_pins=[p for p in pins if archives[p['id']]['metadata'].get('name')==
        'official-result-collection-journal-'+str(p['run_id'])]
    result_ids={p['run_id'] for p in result_pins}
    data=dict(request=dict(manifest=dict(manifest,prior_journal_artifacts=result_pins)),old_run=old_run,
        prior_runs=[r for r in prior_runs if r['id'] in result_ids],
        prior_journal_archives=[archives[p['id']] for p in result_pins],old_journal_raw=old['raw'],old_journal_metadata=old['metadata'])
    bodies,receipts,_=prior._prior_evidence(data,key,now)
    runs=recovery._prior_runs(dict(manifest=manifest),old_run,prior_runs);future_sources={}
    for pin in pins:
        if pin in result_pins:continue
        item=archives[pin['id']];meta=item['metadata']
        need(meta.get('id')==pin['id'] and meta.get('digest')==pin['digest'],'FUTURE_PRIOR_PIN')
        journal,source=_future_epoch(item,pin,now=now,key=key)
        future_sources[pin['id']]=source
        bodies[pin['id']]=journal;receipts[pin['id']]=dict(pin=deepcopy(pin),artifact_metadata=deepcopy(meta),
            cipher_sha256=sha256(source['collection.enc']).hexdigest(),payload_sha256=digest(journal))
    for pin in pins:
        body=bodies[pin['id']];run=next(r for r in runs if r['id']==pin['run_id'])
        saved=clock(receipts[pin['id']]['artifact_metadata']['created_at'])
        need(clock(run['run_started_at'])<=clock(body['epoch_started_at'])<=saved+timedelta(seconds=1) and
            saved<=clock(run['updated_at'])+timedelta(seconds=1),'PRIOR_TERMINAL_SAVE_BINDING')
    body=bodies[recovery.OLD_ARTIFACT];browser=body.get('browser_attempt')
    need(type(browser) is dict and browser.get('state')=='RESERVED' and
        'actual_request_count' not in browser and body['maximum_requests']==32 and
        len(body['attempts'])==8 and browser.get('reserved_request_limit')==24 and
        all(a.get('state')=='SUCCESS' and a.get('http_status')==200 for a in body['attempts']) and
        not any(k in body for k in ('browser_index','browser_request_checkpoint')),'FIXED_UNKNOWN_SHAPE')
    for body in bodies.values():
        need(all(p in pins for p in body['manifest']['prior_journal_artifacts']),'TRANSITIVE_PRIOR_PIN_CLOSURE')
    # V2 keeps each original P/O and native source archive. Rejoin that derived
    # context to the actual recursively authenticated source journals as well.
    from . import all_existing_model_future_result_capture as result_core
    from scripts import all_existing_model_future_result_capture as result_wrapper
    for pin in pins:
        body=bodies[pin['id']]
        if body.get('schema')!=result_core.JOURNAL_V2:continue
        admitted,proof=result_wrapper.replay_retained_forecasts(body,future_sources[pin['id']],
            dict(run_id=pin['run_id'],head_sha=pin['head_sha']),now=now,key=key)
        joined=result_core.bind_source_history(admitted,proof,dict(bodies=bodies,receipts=receipts))
        need(all(body['native_source_proof'].get(k)==v for k,v in joined.items()),'FUTURE_RESULT_RECURSIVE_SOURCE_BINDING')
    need(current_run is None or current_run not in {r['id'] for r in runs},'FRESH_CURRENT_RUN')
    latest=max(*(clock(r['updated_at'])+timedelta(seconds=1) for r in runs),
        *(clock(r['artifact_metadata']['created_at'])+timedelta(seconds=1) for r in receipts.values()))
    need(now>=latest+timedelta(hours=1),'LATEST_TERMINAL_INTERVAL')
    return dict(prior_journal_artifact_count=len(pins),prior_journal_receipts_sha256=digest(list(receipts.values())),
        prior_journal_guard_scope='EXPLICIT_TRANSITIVELY_CLOSED_PINS_ONLY',minimum_epoch_interval_seconds=3600,
        latest_possible_old_activity_at=latest.isoformat(),old_source_requests_actual=None,
        old_source_requests_upper_bound=32,old_browser_outcome='UNKNOWN',bodies=bodies,receipts=receipts,runs=runs)


def _future_epoch(item,pin,*,now,key):
    """Explicit fresh-source journal readers; legacy collector grants stay closed."""
    from scripts import all_existing_model_future_source_capture as wrapper
    env=dict(run_id=pin['run_id'],head_sha=pin['head_sha']);name=item['metadata'].get('name')
    if name=='official-future-result-capture-'+str(pin['run_id']):
        from scripts import all_existing_model_future_result_capture as result_wrapper
        journal,source,_=result_wrapper.source_archive(item['raw'],item['metadata'],env,now=now,key=key)
        recovery.no_known_denial(journal)
        need(journal['raw_retention_complete'] is True and type(journal['source_requests_actual']) is int,
            'FUTURE_PRIOR_OUTCOME_UNKNOWN')
        return journal,source
    if name=='official-jra-future-source-capture-'+str(pin['run_id']):
        from scripts import jra_future_source_capture as horse
        from . import jra_future_source_capture as horse_core
        from . import manual_official_capture as capture
        journal,source,files=horse.source_archive(item['raw'],item['metadata'],env,now=now,key=key)
        recovery.no_known_denial(journal)
        cache=journal['capture_cache']
        need(journal['raw_retention_complete'] is True and type(journal['source_requests_actual']) is int and
            cache is not None and horse._known(cache),'FUTURE_PRIOR_OUTCOME_UNKNOWN')
        capture._validate_cache(cache)
        plan=wrapper._open(source['plan.enc'],env,key)
        # The original three-source join verifies each raw HTTP hash/clock and
        # the literal discovery link; source_archive alone is not that replay.
        bodies={url:files[entry['raw_file']] for url,entry in cache['captures'].items()}
        horse_core.originals(journal['manifest'],plan,cache,bodies)
        return journal,source
    need(name=='official-future-source-capture-'+str(pin['run_id']),'FUTURE_PRIOR_ARTIFACT_PURPOSE')
    journal,source,files=wrapper.source_archive(item['raw'],item['metadata'],env,now=now,key=key)
    recovery.no_known_denial(journal)
    need(journal['raw_retention_complete'] is True and type(journal['source_requests_actual']) is int and
        wrapper._known(journal['capture_index'],started=clock(journal['epoch_started_at']),
            finished=clock(journal['completed_at'])),'FUTURE_PRIOR_OUTCOME_UNKNOWN')
    plan=wrapper._open(source['plan.enc'],env,key);index=journal['capture_index'];builder._no_dynamic_replay(index)
    originals=builder._original_rows(index,files,clock(plan['available_after']),clock(index['completed_at']))
    builder._static_replays(plan,index,originals,files)
    return journal,source


def prepare_capture(manifest,contexts,*,now,static_cache=None):
    now=clock(now);validate_manifest(manifest,now=now);need(set(contexts)==SPORTS,'BASELINE_CONTEXTS')
    available=[]
    for sport,context in contexts.items():
        model=context['training']['models'].get(sport+'/'+LEARNED_ID)
        need(type(model) is dict and type(model.get('native_training')) is dict,'EXISTING_NATIVE_RANKER_REQUIRED')
        created=clock(model['native_training']['created_at'])
        ready=clock(context['receipt']['created_at'])+timedelta(seconds=1)
        need(created<now and ready<=now,'BASELINE_CAPTURE_AVAILABILITY')
        available.extend((ready,created+timedelta(microseconds=1)))
    for case in manifest['cases']:
        need(now+timedelta(seconds=600)<clock(case['cutoff_at']),'CURRENT_FUTURE_MARGIN')
    plan=dict(schema=builder.PLAN,intent=builder.INTENT,available_after=max(available).isoformat(),
        cases=deepcopy(manifest['cases']),request_budget=32)
    if static_cache:plan['static_cache']=deepcopy(static_cache)
    return plan


def fixed_selection(built):
    """Use the builder's original requests, never call fresh select_cases."""
    need(built.get('state')=='READY_INPUTS_ONLY','BUILDER_HOLD')
    rows=[]
    from .all_existing_model_learning import _sources
    from . import all_existing_model_registry as registry
    for case,binding in zip(built['packet']['cases'],built['case_bindings'],strict=True):
        sport=case['sport'];requests=[deepcopy(r) for r in built['requests'] if r['cell_key'].startswith(sport+'/')]
        need(len(requests)==len(builder.CELLS[sport]),'EXACT_FIXED_REQUESTS')
        first=requests[0];identity=registry.identity(first['cell_key'].split('/',1)[1],sport,first['native_payload'])
        rows.append(dict(sport=sport,race_id=binding['race_id'],cutoff=clock(identity['race_cutoff_at']),requests=requests,
            source_refs=sorted(set().union(*(_sources(r['native_payload']) for r in requests))),source_case=deepcopy(case)))
    return rows
