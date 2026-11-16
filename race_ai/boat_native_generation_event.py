"""Separate actual native-call clocks; never edit a sealed prediction body."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import re
from .actions_contract import digest,stamp

SCHEMA='RACE_AI_BOAT_NATIVE_GENERATION_EVENT_V1'
FIELDS={'schema','race_id','stage','model_id','prediction_sha256','native_input_sha256',
        'source_snapshot_sha256','program_source_sha256','beforeinfo_source_sha256','as_of',
        'computation_started_at','computation_completed_at','event_sha256'}

def need(ok,reason):
    if not ok:raise ValueError('NATIVE_GENERATION_EVENT_'+reason)

def native_hash(model):
    field=next((k for k in ('prediction_sha256','bundle_sha256','model_sha256') if k in model),None)
    need(field is not None and model[field]==digest({k:v for k,v in model.items() if k!=field}),
         'NATIVE_HASH_INVALID')
    return model[field]

def input_hash(model):
    value=model.get('source_snapshot_sha256',model.get('snapshot_sha256'))
    need(type(value) is str and re.fullmatch('[a-f0-9]{64}',value),'INPUT_HASH_MISSING')
    return value

def event_index(document):
    events=document.get('native_generation_events',[])
    need(type(events) is list and len(events)<=288*14,'LIST_INVALID')
    result={}
    for event in events:
        need(type(event) is dict and set(event)==FIELDS and event['schema']==SCHEMA and event['stage']=='P1',
             'SCHEMA_INVALID')
        need(type(event['race_id']) is str and re.fullmatch(r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])',event['race_id'])
             and type(event['model_id']) is str and re.fullmatch('[A-Za-z0-9_.-]{1,128}',event['model_id']), 'IDENTITY_INVALID')
        for field in ('prediction_sha256','native_input_sha256','source_snapshot_sha256',
                      'program_source_sha256','beforeinfo_source_sha256','event_sha256'):
            need(type(event[field]) is str and re.fullmatch('[a-f0-9]{64}',event[field]),'HASH_INVALID')
        need(event['event_sha256']==digest({k:v for k,v in event.items() if k!='event_sha256'}),'SEAL_INVALID')
        need(stamp(event['as_of'])<=stamp(event['computation_started_at'])<=stamp(event['computation_completed_at']),
             'CLOCK_ORDER_INVALID')
        key=(event['race_id'],'P1',event['model_id'],event['prediction_sha256'])
        need(key not in result,'DUPLICATE_NATIVE_OUTPUT')
        result[key]=event
    return result

def record_generation_event(model,*,race_id,source_snapshot_sha256,program_source_sha256,
                            beforeinfo_source_sha256,computation_started_at,computation_completed_at):
    """Called immediately after inference with clocks captured around that call."""
    event=dict(schema=SCHEMA,race_id=race_id,stage='P1',model_id=model['model_id'],
        prediction_sha256=native_hash(model),native_input_sha256=input_hash(model),
        source_snapshot_sha256=source_snapshot_sha256,program_source_sha256=program_source_sha256,
        beforeinfo_source_sha256=beforeinfo_source_sha256,as_of=model['as_of'],
        computation_started_at=computation_started_at,computation_completed_at=computation_completed_at)
    event['event_sha256']=digest(event)
    event_index(dict(native_generation_events=[event]))
    return event

def read_generation_event(document,model,*,race_id,source_snapshot_sha256,program_source_sha256,
                          beforeinfo_source_sha256,source_captured_at,cutoff_at,saved_at=None):
    event=event_index(document).get((race_id,'P1',model['model_id'],native_hash(model)))
    if event is None:return None
    if model.get('source_snapshot_sha256') is not None:
        need(model['source_snapshot_sha256']==source_snapshot_sha256,'BASE_SOURCE_SNAPSHOT_INVALID')
        need(model.get('extra_source_sha256')==sha256((program_source_sha256+beforeinfo_source_sha256).encode()).hexdigest(),
             'EXTRA_SOURCE_INVALID')
    need(event['native_input_sha256']==input_hash(model) and
         event['source_snapshot_sha256']==source_snapshot_sha256 and
         event['program_source_sha256']==program_source_sha256 and
         event['beforeinfo_source_sha256']==beforeinfo_source_sha256 and event['as_of']==model['as_of'],
         'NATIVE_OR_SOURCE_BINDING_INVALID')
    completed=stamp(event['computation_completed_at'])
    need(stamp(source_captured_at)<=stamp(event['as_of']) and completed<stamp(cutoff_at),'SOURCE_OR_CUTOFF_INVALID')
    if saved_at is not None:
        saved=stamp(saved_at)
        need(completed<=saved or saved.microsecond==0 and saved<=completed<saved+timedelta(seconds=1),
             'AFTER_PHYSICAL_SAVE')
    return deepcopy(event)
