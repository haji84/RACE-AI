"""Research parameter adapters for the existing catalog; no new predictors."""
from copy import deepcopy
from datetime import datetime, timezone, time as day_time
import math
import re

from .actions_contract import digest
from .existing_model_coverage import catalog
from .existing_model_dispatch import GROUPS, InputMissing, _scope, _bind, _authorize, _race_key
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED, WEIGHTS, FEATURE_RANGES, predict_pair
from .observed_weight_learning import vectors, ts
from .four_sport_learning import LEARNED_ID, vector_schema, forecast as ranker_forecast, _all_triples
from . import existing_boat_parameter_adapters as boat
from . import existing_common_parameter_adapters as common
from . import existing_special_parameter_adapters as special

VERSION='RACE_AI_EXISTING_NATIVE_PARAMETER_REGISTRY_V1'
ROSTER_SCHEMA='RACE_AI_REGISTERED_NATIVE_ROSTER_V1'

def need(ok,reason):
    if not ok:raise ValueError('ALL_MODEL_'+reason)

def cell_key(sport,model_id):return sport+'/'+model_id

def group(model_id):
    return next(name for name,ids in GROUPS if model_id in ids)

def specs(model_id,sport):
    need(any(m['model_id']==model_id and sport in m['applicable_sports'] for m in catalog()),'MODEL_SPORT_NOT_APPLICABLE')
    if model_id in OBSERVED:return {k:(v,0.,4.) for k,v in zip(FEATURE_RANGES,WEIGHTS[model_id])}
    if model_id==LEARNED_ID:return {name:(0.,-8.,8.) for name in vector_schema(sport)}
    adapter=boat if group(model_id) in ('boat_ab','boat_clite','boat_tactical','boat_full') else common if group(model_id)=='shared' else special
    return adapter.specs(model_id,sport)

def cells():
    return [dict(cell_key=cell_key(sport,item['model_id']),model_id=item['model_id'],sport=sport,
                 group=group(item['model_id']),required_input=item['required_input']+
                 ('; independently bound registered entrant roster' if group(item['model_id']) in ('seller','autorace_personal') else ''),trainable=True,
                 parameters={k:list(v) for k,v in specs(item['model_id'],sport).items()})
            for item in catalog() for sport in item['applicable_sports']]

def registry_sha256():return digest(dict(version=VERSION,cells=cells()))

def validate_parameters(model_id,sport,parameters):
    spec=specs(model_id,sport)
    need(type(parameters) is dict and set(parameters)==set(spec),'PARAMETER_FIELDS')
    need(all(type(v) in (int,float) and math.isfinite(v) and spec[k][1]<=v<=spec[k][2]
             for k,v in parameters.items()),'PARAMETER_BOUNDS')
    return dict(parameters)

def _registered_roster(sport,payload,*,race_id,as_of,native,slots):
    """Bind external entrant IDs to a native input that has only slot numbers.

    This validates retained source/hash/clock claims, not their external
    authenticity. Research admission and the frozen-payload reader own that
    independent verification; no IDs are inferred from lanes or car numbers.
    """
    envelope=payload.get('registered_roster')
    if envelope is None:raise InputMissing('ALL_MODEL_REGISTERED_ROSTER_INPUT_MISSING')
    fields={'schema','sport','race_id','as_of','roster','native_input_sha256',
            'source_ref','source_rights_ref','source_sha256','captured_at'}
    need(type(envelope) is dict and set(envelope)==fields and
         envelope['schema']==ROSTER_SCHEMA and envelope['sport']==sport,'REGISTERED_ROSTER_SCHEMA')
    need(type(envelope['race_id']) is str and
         _race_key(envelope['race_id'],sport)==_race_key(race_id,sport),'REGISTERED_ROSTER_RACE')
    need(type(envelope['as_of']) is str and type(envelope['captured_at']) is str and
         ts(envelope['as_of'])==ts(as_of) and ts(envelope['captured_at'])<=ts(as_of),'REGISTERED_ROSTER_CLOCK')
    need(envelope['native_input_sha256']==digest(native),'REGISTERED_ROSTER_NATIVE_INPUT')
    roster=envelope['roster']
    need(type(slots) is list and all(type(n) is int and n>0 for n in slots) and len(slots)==len(set(slots)),
         'REGISTERED_ROSTER_NATIVE_SLOTS')
    if sport=='autorace':need(3<=len(slots)<=8 and all(n<=8 for n in slots),'REGISTERED_ROSTER_NATIVE_SLOTS')
    expected={str(n) for n in slots}
    need(type(roster) is dict and set(roster)==expected and
         all(type(v) is str and 1<=len(v)<=128 and all(ord(c)>32 for c in v) for v in roster.values()),
         'REGISTERED_ROSTER_ENTRANTS')
    need(len(set(roster.values()))==len(roster),'REGISTERED_ROSTER_DUPLICATE_ID')
    if sport=='boat':
        need(all(re.fullmatch(r'[0-9]{4}',v) and int(v)>0 for v in roster.values()),'REGISTERED_ROSTER_BOAT_ID')
    else:
        need(sport=='autorace' and not set(roster.values()) & expected and
             all(not v.isdecimal() or int(v)>0 for v in roster.values()),'REGISTERED_ROSTER_DRIVER_ID')
        need(envelope['source_ref']==native['race']['source_url'],'REGISTERED_ROSTER_NATIVE_SOURCE')
    need(type(envelope['source_ref']) is str and bool(envelope['source_ref']) and
         type(envelope['source_rights_ref']) is str and bool(envelope['source_rights_ref']) and
         type(envelope['source_sha256']) is str and re.fullmatch(r'[a-f0-9]{64}',envelope['source_sha256']),
         'REGISTERED_ROSTER_SOURCE')
    evidence=payload.get('source_evidence')
    need(type(evidence) is list and any(type(e) is dict and all(e.get(k)==envelope[k]
         for k in ('source_ref','source_rights_ref','source_sha256','captured_at')) for e in evidence),
         'REGISTERED_ROSTER_SOURCE_BINDING')
    return dict(roster)

def identity(model_id,sport,payload,*,race_id=None):
    kind=group(model_id);scope=_scope(kind,payload)
    if kind in ('boat_ab','boat_clite','boat_tactical','boat_pdca'):
        source=payload.get('source',payload.get('base_source',payload.get('facts',{})))
        participants=source.get('boats',source.get('racers',[]))
        roster={str(p['lane']):p.get('racer_id',p.get('registration_no')) for p in participants}
        return dict(race_id=source['race_id'],stage='P1',as_of=source['captured_at'],
                    cutoff_at=source['cutoff_at'],race_cutoff_at=source['cutoff_at'],roster=roster,scope=scope)
    if kind=='seller':
        from datetime import date
        from .boat_observed_pairwise_models import JST
        rid=race_id or payload.get('race_id');need(type(rid) is str,'SELLER_TARGET_RACE_REQUIRED')
        actual=payload.get('cutoff_at');need(type(actual) is str,'SELLER_ACTUAL_CUTOFF_REQUIRED')
        at=payload.get('as_of');need(type(at) is str,'SELLER_CAPTURE_REQUIRED')
        freeze=datetime.combine(date.fromisoformat(payload['day']),day_time(7),JST)
        need(ts(at)<freeze<=ts(actual),'SELLER_CLOCK')
        native={k:payload[k] for k in ('cards','waku','day')}
        need(any(_race_key(k,'boat')==_race_key(rid,'boat') for k in payload['cards']),'SELLER_ROSTER_RACE_MISSING')
        roster=_registered_roster(sport,payload,race_id=rid,as_of=at,native=native,slots=list(range(1,7)))
        return dict(race_id=rid,stage='P0',as_of=at,cutoff_at=freeze.isoformat(),race_cutoff_at=actual,
                    roster=roster,scope=scope)
    snapshot=payload['snapshot'];race=snapshot.get('race',snapshot)
    if kind=='autorace_personal':
        stage=race['phase'];at=race['as_of_at']
        roster=_registered_roster(sport,payload,race_id=race['race_id'],as_of=at,native=snapshot,
                                  slots=[p['car_no'] for p in snapshot['drivers']])
    elif kind in ('shared','shared_learned'):
        roster={str(p['number']):p['identity'] for p in snapshot['participants']};stage=payload.get('stage','P1');at=race['as_of']
    elif kind=='boat_full':
        roster={str(p['lane']):p['participant_id'] for p in snapshot['entrants']};stage='P1';at=race['as_of']
    else:
        roster={str(p['lane']):p['registration_no'] for p in snapshot['participants']};stage=snapshot['stage'];at=race['as_of']
    return dict(race_id=race['race_id'],stage=stage,as_of=at,cutoff_at=race['sales_cutoff_at'],
                race_cutoff_at=race['sales_cutoff_at'],roster=roster,scope=scope)

def validate_payload(model_id,sport,payload,*,at,allow_source=None,race_id=None):
    specs(model_id,sport);at=ts(at) if type(at) is str else at
    need(type(at) is datetime and at.utcoffset() is not None,'AWARE_CLOCK')
    info=identity(model_id,sport,payload,race_id=race_id)
    if 'original_native_payload' in payload or 'original_input_sha256' in payload:
        original=payload.get('original_native_payload')
        need(type(original) is dict and 'original_native_payload' not in original and
             'original_input_sha256' not in original and digest(original)==payload.get('original_input_sha256'),
             'ORIGINAL_INPUT_BINDING')
        prior=validate_payload(model_id,sport,original,at=at,allow_source=allow_source,race_id=race_id)
        need(all(prior[k]==info[k] for k in ('stage','cutoff_at','race_cutoff_at','roster','scope')) and
             _race_key(prior['race_id'],sport)==_race_key(info['race_id'],sport) and
             ts(prior['as_of'])<=ts(info['as_of']),'ORIGINAL_INPUT_IDENTITY')
        need(model_id in OBSERVED,'ORIGINAL_METADATA_ONLY_FOR_VENUE_ENRICHMENT')
        old=original['snapshot'];new=payload['snapshot']
        need(all(old[k]==new[k] for k in old if k not in ('as_of','sources','participants')),'ORIGINAL_SNAPSHOT_BINDING')
        previous={p['lane']:p for p in old['participants']}
        for p in new['participants']:
            before=deepcopy(previous[p['lane']]);after=deepcopy(p)
            for obj in (before,after):
                for field in ('course_mean_finish','course_mean_st'):
                    obj['features'].pop(field,None);obj['missing'].pop(field,None)
            need(before==after,'ORIGINAL_NONVENUE_FEATURE_CHANGED')
    row=dict(race_id=race_id or info['race_id'],sport=sport,stage=info['stage'],cutoff_at=info['race_cutoff_at'])
    _bind(group(model_id),payload,row,at)
    _authorize(group(model_id),payload,allow_source)
    if group(model_id) in ('seller','autorace_personal') and info['scope']!='SYNTHETIC_ONLY':
        roster=payload['registered_roster']
        need(callable(allow_source) and allow_source(roster['source_ref'],roster['source_rights_ref'],'analysis') is True,
             'REGISTERED_ROSTER_SOURCE_NOT_ADMITTED')
    need(ts(info['as_of'])<=at<ts(info['cutoff_at']),'NATIVE_INPUT_CLOCK')
    return info

def predict(model_id,sport,payload,parameters=None,*,at,allow_source=None,native_training=None):
    if parameters is not None:validate_parameters(model_id,sport,parameters)
    at=at.isoformat() if isinstance(at,datetime) else at
    validate_payload(model_id,sport,payload,at=at,allow_source=allow_source)
    if model_id in OBSERVED:
        baseline=predict_pair(payload['snapshot'],allow_source=allow_source,model_ids=[model_id])['models'][model_id]
        if parameters is None:return baseline
        ranking=_all_triples(vectors(payload['snapshot']),[parameters[name] for name in FEATURE_RANGES])
        result=dict(schema='RACE_AI_EXISTING_OBSERVED_PARAMETER_REPLAY_V1',model_id=model_id,
            race_id=baseline['race_id'],as_of=baseline['as_of'],cutoff_at=baseline['sales_cutoff_at'],
            candidates=ranking,ordered_top8=[r['combination'] for r in ranking[:8]],
            research_parameters=dict(parameters),parameter_source='OPERATOR_SUPPLIED_RESEARCH_PARAMETERS',
            trained=False,calibrated=False,production_promoted=False)
        result['prediction_sha256']=digest(result);return result
    if model_id==LEARNED_ID:
        model=deepcopy(native_training or payload.get('learned_model'))
        need(type(model) is dict,'RANKER_ARTIFACT_REQUIRED')
        return ranker_forecast(payload['snapshot'],model,allow_source=allow_source)
    adapter=boat if group(model_id) in ('boat_ab','boat_clite','boat_tactical','boat_full') else common if group(model_id)=='shared' else special
    return adapter.predict(model_id,payload,parameters,at=at,allow_source=allow_source)

def normalize(model_id,sport,payload,prediction,*,race_id=None):
    info=identity(model_id,sport,payload,race_id=race_id);kind=group(model_id)
    if kind=='seller':
        wanted=_race_key(info['race_id'],'boat')
        selected=next((p for p in prediction['rows'] if _race_key(p['race_id'],'boat')==wanted),None)
        need(selected is not None,'SELLER_RACE_NOT_DISCOVERED')
        tickets=selected.get('tickets',{}).get('five',[])
        top=[[int(x) for x in row['ticket'].split('-')] for row in tickets]
        plans={}
        for name,plan in selected.get('tickets',{}).items():
            plans[name]=dict(top=[[int(x) for x in r['ticket'].split('-')] for r in plan],
                             stakes=[r['yen'] for r in plan],ticket_count=len(plan))
        return dict(ranked=[],top=top,ticket_count=len(top),stakes=[r['yen'] for r in tickets],
                    roster=info['roster'],selection_status=selected['status'],kind='SELECTION',plans=plans)
    rows=prediction.get('candidates',prediction.get('full_120',prediction.get('ranked_relative_weights',prediction.get('all120'))))
    need(type(rows) is list and rows,'NATIVE_DISTRIBUTION_REQUIRED')
    ranking=[]
    for row in rows:
        ticket=row.get('combination',row.get('ticket'))
        if type(ticket) is str:ticket=[int(v) for v in ticket.split('-')]
        value=row.get('score',row.get('relative_weight',row.get('probability')))
        need(type(ticket) is list and len(ticket)==3 and len(set(ticket))==3 and
             all(str(i) in info['roster'] for i in ticket) and type(value) in (int,float) and math.isfinite(value) and value>=0,'NATIVE_CANDIDATE_INVALID')
        ranking.append(dict(combination=deepcopy(ticket),score=value))
    n=len(info['roster']);need(len(ranking)==n*(n-1)*(n-2) and len({tuple(r['combination']) for r in ranking})==len(ranking),'NATIVE_UNIVERSE')
    need(math.isclose(math.fsum(r['score'] for r in ranking),1.,abs_tol=1e-8),'NATIVE_PROBABILITY_MASS')
    top=[r['combination'] for r in ranking[:8]]
    return dict(ranked=ranking,top=top,ticket_count=len(top),stakes=[100]*len(top),
                roster=info['roster'],selection_status='FORECAST',kind='PROBABILITY')

def winning_probability(model_id,sport,payload,parameters,winning,*,at,allow_source=None):
    kind=group(model_id)
    if kind in ('boat_ab','boat_clite','boat_tactical','boat_full'):
        return boat.probability(model_id,payload,parameters,winning,at=at,allow_source=allow_source)
    prediction=predict(model_id,sport,payload,parameters,at=at,allow_source=allow_source)
    normalized=normalize(model_id,sport,payload,prediction)
    if normalized['kind']=='SELECTION':return 1. if winning in normalized['top'] else 0.
    return next(r['score'] for r in normalized['ranked'] if r['combination']==winning)
