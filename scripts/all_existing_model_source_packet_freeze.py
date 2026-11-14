"""One-time offline replay of encrypted official UI source packets in Actions."""
import argparse
import base64
import binascii
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

from race_ai.actions_contract import digest
from race_ai import all_existing_model_registry as registry
from race_ai import autorace_official_sparse_adapter as autorace
from race_ai import manual_official_capture as capture
from race_ai.all_existing_model_learning import _sources
from race_ai.all_existing_model_pairs import (INPUTS_SCHEMA, _race_key, _seal_cutoff,
    make_private_pairs, record_identity, record_partition_key, verify_private_record)
from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
from race_ai.boat_all_model_store import MAX_WIRE, open_forecasts
from race_ai.boat_pdca_state import state_key
from race_ai.boat_venue_learning import read_candidate
from race_ai.four_sport_learning import LEARNED_ID
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_future_p0 as future
from scripts.all_existing_model_official_freeze import _repository_file
from scripts.boat_all_racers import _read, _write
from scripts.boat_history_collect import save

ROOT=Path(__file__).resolve().parents[1]
ROUND=900003
SCHEMA='RACE_AI_OFFICIAL_SOURCE_PACKET_FREEZE_INPUT_V1'
SCHEMA_V2='RACE_AI_OFFICIAL_SOURCE_PACKET_FREEZE_INPUT_V2'
PACKET='RACE_AI_OFFICIAL_SOURCE_PACKET_V1'
STATUS='RACE_AI_OFFICIAL_SOURCE_PACKET_FREEZE_COUNTS_V1'
MAX_PLAIN=24*1024*1024
CELLS={'autorace':set(autorace.CELLS),'keirin':{'keirin/'+mid for mid in (*ALL_MODELS,LEARNED_ID)}}
JST=timezone(timedelta(hours=9))


def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_SOURCE_PACKET_FREEZE_'+reason)


def utc_now():return datetime.now(timezone.utc)


def load_manifest(path,*,now):
    value=read_json_bytes(_read(Path(path),16384))
    fields={'schema','execution_day','packet_path','packet_sha256','maximum_races_per_sport'}
    need(type(value) is dict and (value.get('schema')==SCHEMA and set(value)==fields or
         value.get('schema')==SCHEMA_V2 and set(value)==fields|{'baseline_artifacts','carrier_artifact'}),'MANIFEST_SCHEMA')
    need(value['execution_day']==now.astimezone(JST).date().isoformat(),'EXECUTION_DAY')
    sha=value['packet_sha256']
    need(type(sha) is str and re.fullmatch('[a-f0-9]{64}',sha) and
         value['packet_path']=='audit/state/official-source-packet-'+sha+'.enc','PACKET_PATH_SHA')
    bounds=value['maximum_races_per_sport']
    need(type(bounds) is dict and 1<=len(bounds)<=2 and set(bounds)<=set(CELLS) and
         all(type(n) is int and 1<=n<=8 for n in bounds.values()),'SPORT_RACE_BOUNDS')
    if value['schema']==SCHEMA_V2:
        from race_ai.all_existing_model_future_baseline import validate_pin
        pins=value['baseline_artifacts']
        need(type(pins) is dict and set(pins)==set(bounds),'EXACT_BASELINE_SPORT_PINS')
        for pin in pins.values():validate_pin(pin)
        carrier=validate_pin(value['carrier_artifact'])
        need(all(pin['id']!=carrier['id'] for pin in pins.values()),'BASELINE_DISTINCT_FROM_CARRIER')
    return value


def _terms(value,execution_day,now):
    need(type(value) is dict and type(value.get('terms')) is list,'TERMS_REQUIRED')
    urls=[]
    for item in value['terms']:
        need(type(item) is dict and type(item.get('source_urls')) is list,'TERMS_REQUIRED')
        urls.extend(item['source_urls'])
    capture._terms(value,urls,execution_day,now)
    return set(urls)


def load_packet(manifest,*,key,now):
    raw=_repository_file(ROOT/manifest['packet_path'],MAX_WIRE)
    need(sha256(raw).hexdigest()==manifest['packet_sha256'],'PACKET_CIPHER_SHA')
    value=open_forecasts(raw,key=key)
    need(type(value) is dict and set(value)=={'schema','execution_day','cases','terms_manifest'} and
         value['schema']==PACKET and value['execution_day']==manifest['execution_day'],'PACKET_SCHEMA')
    need(len(future.wire(value))<=MAX_PLAIN and type(value['cases']) is list and
         1<=len(value['cases'])<=32,'PACKET_BOUND')
    _terms(value['terms_manifest'],value['execution_day'],now)
    need(all(type(case) is dict and case.get('sport') in manifest['maximum_races_per_sport']
         for case in value['cases']),'PACKET_SPORT_SCOPE')
    return value


def _bytes(value,limit):
    need(type(value) is str and 0<len(value)<=((limit+2)//3)*4,'SOURCE_BASE64_BOUND')
    try:raw=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise ValueError('ALL_MODEL_SOURCE_PACKET_FREEZE_SOURCE_BASE64') from None
    need(0<len(raw)<=limit and base64.b64encode(raw).decode('ascii')==value,'SOURCE_BASE64')
    return raw


def case_inputs(case,*,now):
    need(type(case) is dict and case.get('sport') in CELLS,'CASE_SPORT')
    sport=case['sport'];rights=capture.official_rights_ref(sport)
    if sport=='autorace':
        need(set(case)=={'sport','program_raw_b64','race_info_raw_b64','rendered_dom_b64',
             'capture_metadata','request_bodies_b64'},'AUTO_CASE_SCHEMA')
        bodies=case['request_bodies_b64']
        need(type(bodies) is dict and 1<=len(bodies)<=32 and all(type(sha) is str and
             re.fullmatch('[a-f0-9]{64}',sha) for sha in bodies),'REQUEST_BODY_SCHEMA')
        bodies={sha:_bytes(value,16384) for sha,value in bodies.items()}
        need(all(sha256(raw).hexdigest()==sha for sha,raw in bodies.items()),'REQUEST_BODY_SHA')
        converted=autorace.build_requests(_bytes(case['program_raw_b64'],capture.MAX_BYTES),
            _bytes(case['race_info_raw_b64'],capture.MAX_BYTES),_bytes(case['rendered_dom_b64'],capture.MAX_BYTES),
            deepcopy(case['capture_metadata']),now=now,source_rights_ref=rights,request_bodies=bodies)
    else:
        from race_ai import keirin_official_sparse_adapter as keirin
        need(set(case)=={'sport','racelist_raw_b64','racelist_metadata','racelive_raw_b64',
             'racelive_metadata','rendered_dom_b64','browser_metadata'},'KEIRIN_CASE_SCHEMA')
        converted=keirin.build_native_inputs(_bytes(case['racelist_raw_b64'],capture.MAX_BYTES),
            deepcopy(case['racelist_metadata']),_bytes(case['racelive_raw_b64'],capture.MAX_BYTES),
            deepcopy(case['racelive_metadata']),now=now,
            rendered_dom_bytes=_bytes(case['rendered_dom_b64'],capture.MAX_BYTES),
            browser_metadata=deepcopy(case['browser_metadata']),source_rights_ref=rights)
    if converted.get('state')!='READY':return converted
    requests=converted.get('requests')
    need(type(requests) is list and len(requests)==len(CELLS[sport]) and all(type(row) is dict and
         set(row)=={'cell_key','native_payload'} for row in requests) and
         {row['cell_key'] for row in requests}==CELLS[sport],'EXACT_NATIVE_CELLS')
    refs=converted.get('source_refs')
    need(type(refs) in (list,tuple) and 1<=len(refs)<=32,'SOURCE_REFS')
    admitted=set()
    for pair in refs:
        need(type(pair) in (list,tuple) and len(pair)==2 and pair[1]==rights,'SOURCE_REFS')
        admitted.add(capture.validate_source_pair(*pair))
    analysis=lambda source,right,purpose:purpose=='analysis' and (source,right) in admitted
    identities=[]
    for request in requests:
        need(type(request['native_payload']) is dict and
             _sources(request['native_payload'])<=admitted,'ADAPTER_SOURCE_CLOSURE')
        identities.append(registry.validate_payload(request['cell_key'].split('/',1)[1],sport,
            request['native_payload'],at=now,allow_source=analysis))
    first=identities[0]
    need(all(_race_key(row['race_id'],sport)==_race_key(first['race_id'],sport) and
         all(row[key]==first[key] for key in ('cutoff_at','race_cutoff_at','roster','scope'))
         for row in identities),'NATIVE_RACE_ROSTER_CLOCK_BINDING')
    converted=deepcopy(converted)
    converted.update(sport=sport,race_id=first['race_id'],cutoff_at=first['race_cutoff_at'])
    return converted


def select_cases(packet,manifest,*,now):
    terms=_terms(packet['terms_manifest'],manifest['execution_day'],now)
    selected=[];seen=set();held=0;rejected=0
    for case in packet['cases']:
        try:converted=case_inputs(case,now=now)
        except (ValueError,TypeError,KeyError,AttributeError):rejected+=1;continue
        if converted.get('state')!='READY':held+=1;continue
        sport=case['sport'];race=converted['race_id'];identity=(sport,_race_key(race,sport))
        need(identity not in seen,'DUPLICATE_RACE');seen.add(identity)
        need({pair[0] for pair in converted['source_refs']}<=terms,'SOURCE_TERMS_CLOSURE')
        cutoff=future.stamp(converted['cutoff_at'])
        if cutoff<now+timedelta(seconds=120):held+=1;continue
        selected.append(dict(sport=sport,race_id=race,cutoff=cutoff,requests=converted['requests'],
                             source_refs=converted['source_refs']))
        if manifest['schema']==SCHEMA_V2:selected[-1]['source_case']=deepcopy(case)
    selected.sort(key=lambda row:(row['cutoff'],row['sport'],row['race_id']))
    counts={sport:0 for sport in manifest['maximum_races_per_sport']};bounded=[]
    for row in selected:
        sport=row['sport']
        if counts[sport]<manifest['maximum_races_per_sport'][sport]:bounded.append(row);counts[sport]+=1
    return bounded,dict(held_cases=held,rejected_cases=rejected,ready_races_by_sport=counts)


def _carrier_context(ident,manifest,*,now):
    from race_ai import all_existing_model_future_baseline as baseline
    pin=manifest['carrier_artifact'];need(ident==pin['id'],'EXPLICIT_CARRIER_PIN_REQUIRED')
    context=baseline.load_baseline(pin,now=now,fetch_metadata=future.metadata,
        fetch_zip=lambda value:future.gh('actions/artifacts/'+str(value)+'/zip'))
    models=context['training']['models']
    need(len(models) in (12,14) and all(model['sport']=='boat' for model in models.values()),'BOAT_ONLY_INPUT_CARRIER_REQUIRED')
    return context


def _baseline_contexts(manifest,*,now,carrier_id):
    from race_ai import all_existing_model_future_baseline as baseline
    pins=manifest['baseline_artifacts'];contexts={};cache={}
    for sport,pin in pins.items():
        need(pin['id']!=carrier_id,'BASELINE_DISTINCT_FROM_CARRIER')
        fingerprint=digest(pin)
        if fingerprint not in cache:
            cache[fingerprint]=baseline.load_baseline(pin,now=now,fetch_metadata=future.metadata,
                fetch_zip=lambda ident:future.gh('actions/artifacts/'+str(ident)+'/zip'))
        contexts[sport]=cache[fingerprint]
    return contexts


def _baseline_source_metadata(case,payload,manifest,context,*,now):
    """Normalize actual HTTP event fields; DOM remains a typed browser capture."""
    sport=case['sport'];model=context['training']['models'].get(sport+'/'+LEARNED_ID)
    need(type(model) is dict and type(model.get('native_training')) is dict,'BASELINE_SPORT_FIT_REQUIRED')
    available=future.stamp(context['receipt']['created_at'])+timedelta(seconds=1)
    created=future.stamp(model['native_training']['created_at']);evidence=payload['source_evidence'];http=[]
    if sport=='autorace':
        sources=[(_bytes(case['program_raw_b64'],capture.MAX_BYTES),case['capture_metadata']),
            (_bytes(case['race_info_raw_b64'],capture.MAX_BYTES),case['capture_metadata'])]
        browser=case['capture_metadata']
    else:
        sources=[(_bytes(case['racelist_raw_b64'],capture.MAX_BYTES),case['racelist_metadata']),
            (_bytes(case['racelive_raw_b64'],capture.MAX_BYTES),case['racelive_metadata'])]
        browser=case['browser_metadata'] if case['browser_metadata'] is not None else case['racelive_metadata']
    for raw,metadata in sources:
        sha=sha256(raw).hexdigest()
        matches=[entry for entry in metadata['ledger'] if entry.get('status')==200 and entry.get('source_sha256')==sha and
            any(e.get('source_ref')==entry.get('url') and e.get('source_sha256')==sha and
                e.get('captured_at')==entry.get('body_captured_at') for e in evidence)]
        need(bool(matches),'BASELINE_SOURCE_CLOSURE')
        entry=max(matches,key=lambda e:future.stamp(e['body_captured_at']))
        fetched=future.stamp(entry['request_started_at']);completed=future.stamp(entry['body_captured_at'])
        need(available<=fetched and created<fetched<=completed<=now and entry.get('byte_count')==len(raw),
            'BASELINE_COMPANION_SOURCE_CLOCK')
        http.append(dict(source_url=entry['url'],status=entry['status'],source_sha256=sha,byte_count=len(raw),
            fetched_at=entry['request_started_at'],response_received_at=entry['body_captured_at'],
            original_ledger_entry=deepcopy(entry),clock_basis='ORIGINAL_REQUEST_START_AND_BODY_CAPTURE'))
    dom_raw=_bytes(case['rendered_dom_b64'],capture.MAX_BYTES);dom=browser['rendered_dom'];dom_sha=sha256(dom_raw).hexdigest()
    need(dom.get('source_sha256')==dom_sha and dom.get('byte_count')==len(dom_raw) and
        available<=future.stamp(browser['started_at']) and created<future.stamp(browser['started_at'])<=
        future.stamp(browser['captured_at'])<=now,'BASELINE_DOM_SOURCE_CLOCK')
    if sport=='autorace':
        need(any(e.get('source_ref')==browser['source_url'] and e.get('source_sha256')==dom_sha and
            e.get('captured_at')==browser['captured_at'] for e in evidence),'BASELINE_DOM_SOURCE_CLOSURE')
    else:need(payload['adapter_lineage']['rendered_dom_sha256']==dom_sha,'BASELINE_DOM_SOURCE_CLOSURE')
    closure=dict(schema='RACE_AI_SOURCE_PACKET_BASELINE_SOURCE_CLOSURE_V1',packet_sha256=manifest['packet_sha256'],
        case_sha256=digest(case),http_metadata=http,rendered_dom=dict(kind='RENDERED_DOM',source_url=browser['source_url'],
            final_url=browser.get('final_url'),started_at=browser['started_at'],captured_at=browser['captured_at'],
            byte_count=len(dom_raw),source_sha256=dom_sha,original_browser_metadata=deepcopy(browser)))
    return dict(http[0],source_packet_closure=closure)


def _attach_baselines(selected,manifest,contexts,*,now):
    from race_ai import all_existing_model_future_baseline as baseline
    attached=0
    for row in selected:
        sport=row['sport'];requests=row['requests'];request=next(r for r in requests if r['cell_key']==sport+'/'+LEARNED_ID)
        metadata=_baseline_source_metadata(row['source_case'],request['native_payload'],manifest,contexts[sport],now=now)
        original=deepcopy(request['native_payload'])
        request['native_payload']=baseline.attach(original,contexts[sport],sport=sport,source_metadata=metadata,now=now)
        restored={k:v for k,v in request['native_payload'].items() if k not in ('learned_model','baseline_attachment')}
        need(restored==original,'BASELINE_ORIGINAL_NATIVE_SOURCE_BINDING');attached+=1
    return attached


def _verify_baselines(records,manifest,contexts,packet,*,now):
    from race_ai import all_existing_model_future_baseline as baseline
    count=0
    for record in records:
        sport,race=record_identity(record);matches=[]
        learned=[c for c in record['captured_native_inputs'] if c['cell_key']==sport+'/'+LEARNED_ID]
        need(len(learned)==1,'EXACT_BASELINE_ATTACHMENT_COUNT')
        original_at=future.stamp(learned[0]['native_payload']['snapshot']['race']['as_of'])
        for case in packet['cases']:
            if case['sport']!=sport:continue
            converted=case_inputs(case,now=original_at)
            if converted.get('state')=='READY' and _race_key(converted['race_id'],sport)==race:matches.append((case,converted))
        need(len(matches)==1,'BASELINE_ORIGINAL_CASE_REQUIRED')
        expected={r['cell_key']:r['native_payload'] for r in matches[0][1]['requests']}
        for capsule in record['captured_native_inputs']:
            payload=capsule['native_payload'];original=deepcopy(payload)
            if capsule['cell_key']==sport+'/'+LEARNED_ID:
                original.pop('baseline_attachment',None);original.pop('learned_model',None)
            need(capsule['cell_key'] in expected and original==expected[capsule['cell_key']],'BASELINE_ORIGINAL_NATIVE_SOURCE_BINDING')
            if capsule['cell_key']!=sport+'/'+LEARNED_ID:
                need('baseline_attachment' not in payload and 'learned_model' not in payload,'BASELINE_ONLY_LEARNED_RANKER');continue
            baseline.verify_attachment(payload,contexts[sport],sport=sport,now=now,generated_at=record['generated_at'])
            metadata=_baseline_source_metadata(matches[0][0],payload,manifest,contexts[sport],now=now)
            need(payload['baseline_attachment']['source_metadata']==metadata,'BASELINE_ORIGINAL_SOURCE_BINDING');count+=1
    need(count==len(records),'EXACT_BASELINE_ATTACHMENT_COUNT')
    return count


def local_records(root):
    from race_ai.all_existing_model_runtime import _private_directory,_private_file
    _private_directory(root);children=list(root.iterdir())
    need(1<=len(children)<=16 and all(re.fullmatch('[a-f0-9]{64}',p.name) for p in children),'OPAQUE_PARTITIONS')
    records=[];seen=set();counts={sport:0 for sport in CELLS}
    for folder in sorted(children):
        _private_directory(folder)
        need({p.name for p in folder.iterdir()}=={'learning.enc','learning.json','summary.json'},'PARTITION_LAYOUT')
        for path in folder.iterdir():_private_file(path)
        payload=read_candidate(folder)
        need(payload.get('schema')==INPUTS_SCHEMA and verify_private_record(payload) is True and
             record_partition_key(payload)==folder.name,'INPUT_ONLY_READBACK')
        sport,race=record_identity(payload)
        need(sport in CELLS and (sport,race) not in seen,'INPUT_SPORT_RACE');seen.add((sport,race))
        counts[sport]+=1;need(counts[sport]<=8,'SPORT_RACE_BOUND')
        capsules=payload['captured_native_inputs']
        need(len(capsules)==len(CELLS[sport]) and {c['cell_key'] for c in capsules}==CELLS[sport],
             'EXACT_NATIVE_CELL_CAPSULES')
        public=read_json_bytes(_read(folder/'summary.json',1024*1024))
        need(public==dict(payload['summary'],encrypted_readback_verified=True,plaintext_published=False),
             'PUBLIC_SUMMARY_BINDING')
        records.append(payload)
    return records


def _counts(records):
    return {sport:sum(record_identity(record)[0]==sport for record in records) for sport in CELLS}


def seal_selected(ident,root,manifest,context,packet,selected,counts,*,contexts=None,
                  minimum_margin_seconds=120):
    """Encrypt already converted requests; the caller preserves their as-of.

    This helper does not select cases or acquire/re-time any source. Fresh
    browser callers authenticate context/packet originals before entering here.
    """
    need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    attachments=(_attach_baselines(selected,manifest,contexts,now=utc_now()) if contexts is not None else 0)
    requests=[request for row in selected for request in row['requests']]
    refs={tuple(pair) for row in selected for pair in row['source_refs']}
    if contexts is not None:
        for request in requests:refs.update(_sources(request['native_payload']))
    pair_context=({k:context[k] for k in ('training','receipt')} if contexts is not None else context)
    summary=make_private_pairs(pair_context,requests,root,now=utc_now(),allow_source=lambda source,right,purpose:
        purpose=='analysis' and (source,right) in refs)
    expected=sum(len(CELLS[row['sport']]) for row in selected)
    need(summary['partition_count']==summary['frozen_input_only_partition_count']==len(selected) and
         summary['forecast_partition_count']==0 and summary['captured_native_input_count']==expected,
         'EXACT_FROZEN_INPUT_COUNTS')
    need(read_json_bytes(_read(root/'summary.json',1024*1024))==summary,'ROOT_SUMMARY_BINDING')
    (root/'summary.json').unlink();records=local_records(root)
    need(min(_seal_cutoff(p) for p in records)>=utc_now()+timedelta(seconds=minimum_margin_seconds),'FINAL_MARGIN_ELAPSED')
    extra={}
    if contexts is not None:
        _verify_baselines(records,manifest,contexts,packet,now=utc_now())
        extra.update(source_packet_freeze_schema=SCHEMA_V2,manifest_sha256=digest(manifest),
            baseline_artifacts_sha256=digest(manifest['baseline_artifacts']),baseline_attachment_count=attachments,
            carrier_artifact_pin_sha256=digest(manifest['carrier_artifact']),independent_carrier_artifact_receipt_verified=True)
    return dict(counts,**extra,state='OFFICIAL_SOURCE_PACKET_INPUTS_ENCRYPTED_LOCAL_ONLY',ready=True,
        ready_races=len(records),partition_count=len(records),frozen_input_only_partition_count=len(records),
        forecast_partition_count=0,captured_native_input_count=expected,candidate_artifact_id=ident,
        training_sha256=context['training']['training_sha256'],source_packet_sha256=manifest['packet_sha256'],
        terms_manifest_sha256=digest(packet['terms_manifest']),record_sha256=sorted(digest(p) for p in records),
        encrypted_readback_verified=True,independent_pre_cutoff_receipt_verified=False)


def generate(ident,root,env,manifest):
    need(not root.exists(),'OUTPUT_EXISTS_DO_NOT_RESET')
    key=state_key('production');context=(_carrier_context(ident,manifest,now=utc_now()) if manifest['schema']==SCHEMA_V2
        else future.candidate(ident,env))
    need(context['training']['scope']=='OPERATOR_SUPPLIED_RESEARCH','REAL_RESEARCH_CANDIDATE_REQUIRED')
    need(not set().union(*CELLS.values())&set(context['training']['models']),'INPUT_ONLY_CANDIDATE_REQUIRED')
    ready=future.stamp(context['receipt']['created_at'])+timedelta(seconds=1)
    remaining=(ready-utc_now()).total_seconds()
    if 0<remaining<=2:time.sleep(remaining+.02)
    need(utc_now()>=ready,'CANDIDATE_RECEIPT_PRECISION')
    contexts=(_baseline_contexts(manifest,now=utc_now(),carrier_id=ident) if manifest['schema']==SCHEMA_V2 else None)
    packet=load_packet(manifest,key=key,now=utc_now())
    selected,counts=select_cases(packet,manifest,now=utc_now())
    if not selected:return dict(counts,state='HOLD_NO_READY_FUTURE_NATIVE_INPUTS',ready=False,ready_races=0)
    return seal_selected(ident,root,manifest,context,packet,selected,counts,contexts=contexts)


def readback(ident,root,env,*,manifest=None,_packet_loader=None):
    local=local_records(root);proof=root.with_name(root.name+'.generation.json')
    previous=read_json_bytes(_read(proof if proof.exists() else root.with_name(root.name+'.status.json'),128*1024))
    v2=any('baseline_attachment' in c['native_payload'] or 'learned_model' in c['native_payload']
        for p in local for c in p['captured_native_inputs'])
    extra={}
    if v2:
        need(type(manifest) is dict and manifest.get('schema')==SCHEMA_V2 and
            previous.get('manifest_sha256')==digest(manifest) and
            previous.get('baseline_artifacts_sha256')==digest(manifest['baseline_artifacts']),'BASELINE_MANIFEST_REQUIRED')
        carrier=_carrier_context(local[0]['training_receipt']['id'],manifest,now=utc_now())
        need(previous.get('carrier_artifact_pin_sha256')==digest(manifest['carrier_artifact']) and all(
            p['training']==carrier['training'] and p['training_receipt']==carrier['receipt'] for p in local),
            'CARRIER_ORIGINAL_READBACK')
        contexts=_baseline_contexts(manifest,now=utc_now(),carrier_id=local[0]['training_receipt']['id'])
        packet=(_packet_loader or load_packet)(manifest,key=state_key('production'),now=utc_now())
        count=_verify_baselines(local,manifest,contexts,packet,now=utc_now())
        need(previous.get('baseline_attachment_count')==count,'BASELINE_ATTACHMENT_COUNTS')
        extra.update(source_packet_freeze_schema=SCHEMA_V2,manifest_sha256=digest(manifest),
            baseline_artifacts_sha256=digest(manifest['baseline_artifacts']),baseline_attachment_count=count,
            independent_baseline_artifact_receipts_verified=True,carrier_artifact_pin_sha256=digest(manifest['carrier_artifact']),
            independent_carrier_artifact_receipt_verified=True)
    else:need(manifest is None or manifest.get('schema')==SCHEMA,'BASELINE_ATTACHMENTS_REQUIRED')
    hashes=sorted(digest(p) for p in local)
    need(type(previous) is dict and previous.get('schema')==STATUS and previous.get('ready') is True and
         all(type(previous.get(key)) is str and re.fullmatch('[a-f0-9]{64}',previous[key])
             for key in ('source_packet_sha256','terms_manifest_sha256')) and
         all(type(previous.get(key)) is int and 0<=previous[key]<=32 for key in ('held_cases','rejected_cases')) and
         previous.get('workflow_run_id')==env['run_id'] and
         previous.get('expected_head_sha')==env['head_sha'] and previous.get('record_sha256')==hashes and
         previous.get('candidate_artifact_id')==local[0]['training_receipt']['id'] and
         previous.get('training_sha256')==local[0]['training']['training_sha256'],'LOCAL_GENERATION_STATUS')
    actual=future.metadata(ident);raw=future.gh('actions/artifacts/'+str(ident)+'/zip')
    need(actual.get('name')==f'all-existing-model-pairs-{env["run_id"]}-{ROUND}','ACTUAL_ARTIFACT_NAME')
    admitted,records=_verified_private_pairs_artifact(raw,actual,now=utc_now(),
        expected_run_id=env['run_id'],expected_head_sha=env['head_sha'])
    expected=sum(len(p['captured_native_inputs']) for p in local)
    need(admitted['partition_count']==admitted['frozen_input_only_partition_count']==len(local) and
         admitted['forecast_partition_count']==0 and admitted['captured_native_input_count']==expected and
         sorted(digest(p) for p in records)==hashes,'ACTUAL_NATIVE_INPUT_READBACK')
    lineage={key:previous[key] for key in ('source_packet_sha256','terms_manifest_sha256','held_cases',
        'rejected_cases') if key in previous}
    return dict(lineage,**extra,state='OFFICIAL_SOURCE_PACKET_INPUTS_ACTUAL_PRE_CUTOFF_VERIFIED',ready=True,
        ready_races=len(local),ready_races_by_sport=_counts(local),partition_count=len(local),
        frozen_input_only_partition_count=len(local),forecast_partition_count=0,captured_native_input_count=expected,
        record_sha256=hashes,candidate_artifact_id=previous['candidate_artifact_id'],
        training_sha256=previous['training_sha256'],artifact_id=ident,artifact_digest=actual['digest'],
        saved_at=actual['created_at'],encrypted_readback_verified=True,independent_pre_cutoff_receipt_verified=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--candidate-artifact',type=int);mode.add_argument('--readback-artifact',type=int)
    parser.add_argument('--input');parser.add_argument('--out-dir',required=True);args=parser.parse_args(argv)
    result=dict(schema=STATUS,state='HOLD_OFFICIAL_SOURCE_PACKET_FREEZE',ready=False,source_requests=0,
        independent_pre_cutoff_receipt_verified=False,plaintext_published=False,public_redistribution=False,
        provider_model_training_permission_confirmed=False,production_promoted=False,actual_purchases=False,
        forecast_partition_count=0);status=None
    try:
        env=future.environment();root=future.output_path(args.out_dir,env);status=root.with_name(root.name+'.status.json')
        result.update(workflow_run_id=env['run_id'],expected_head_sha=env['head_sha'],
            artifact_name=f'all-existing-model-pairs-{env["run_id"]}-{ROUND}')
        if args.candidate_artifact:
            need(args.input is not None,'INPUT_MANIFEST_REQUIRED')
            manifest=load_manifest(args.input,now=utc_now());result.update(generate(args.candidate_artifact,root,env,manifest))
        else:
            manifest=load_manifest(args.input,now=utc_now()) if args.input is not None else None
            result.update(readback(args.readback_artifact,root,env,manifest=manifest))
        if args.candidate_artifact and result.get('source_packet_freeze_schema')==SCHEMA_V2 and result['ready']:
            _write(root.with_name(root.name+'.generation.json'),future.wire(result))
    except Exception as exc:
        reason=str(exc)
        result.update(state='HOLD_OFFICIAL_SOURCE_PACKET_FREEZE',ready=False,reason=reason if re.fullmatch(
            'ALL_MODEL_SOURCE_PACKET_FREEZE_[A-Z_]{1,100}',reason) else 'OFFICIAL_SOURCE_PACKET_OPERATION_REJECTED')
    if status is not None:save(status,future.wire(result),replace=status.exists())
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('ready='+str(result['ready']).lower()+'\n')
            if result.get('artifact_name'):output.write('artifact_name='+result['artifact_name']+'\n')
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
