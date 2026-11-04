"""Coverage of the sixteen previously inventoried families, not invented picks.

An applicable model remains visible when its genuine inputs are absent. Merely
registering a model never makes it operational or adds a forecast to a score.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import re
from .boat_ab_shadow import MODEL_IDS as AB
from .boat_live_feature_shadow import MODEL_ID as CLITE
from .boat_tactical_scenarios import MODEL_ID as TACTICAL
from .boat_multi_feature_models import MODEL_IDS as BOAT_FULL
from .boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from .four_sport_model_suite import ALL_MODELS
from .four_sport_learning import LEARNED_ID
from .autorace_personal_baseline import MODEL_ID as AUTO

ALL=('boat','keirin','autorace','horse')

def catalog():
    groups=[(AB,('boat',),'same-race official exhibition and program'),
        ((CLITE,),('boat',),'local win rate and start observations'),
        ((TACTICAL,),('boat',),'verified pre-as-of racer entry/course/method history'),
        (BOAT_FULL,('boat',),'complete timestamped form/course/start ratings and conditions'),
        (OBSERVED,('boat',),'verified program or exhibition observations with explicit missing fields'),
        (ALL_MODELS,ALL,'complete per-participant features and environment snapshot'),
        ((LEARNED_ID,),ALL,'genuine fitted artifact plus complete current snapshot'),
        ((AUTO,),('autorace',),'actual prior finish positions; same-race trial for phase B'),
        (('boat-pdca-lane-shadow-v1',),('boat',),'24 earlier verified same-venue results and new pre-cutoff input'),
        (('seller-shadow-v1-20261104',),('boat',),'national and historical same-lane rates; frozen before 07:00 JST')]
    return [dict(model_id=mid,applicable_sports=list(sports),required_input=required)
            for ids,sports,required in groups for mid in ids]

def coverage(rows,scheduled):
    counts=Counter(x['model_id'] for x in rows)
    models=[]
    for spec in catalog():
        subset=[x for x in rows if x['model_id']==spec['model_id']]
        models.append(dict(**spec,saved_forecasts=len(subset),
            distinct_races=len({x['race_id'] for x in subset}),
            by_phase=dict(Counter(x['stage'] for x in subset)),
            target_races=sum(scheduled.get(s,0) for s in spec['applicable_sports']),
            state='SOME_FROZEN_FORECASTS' if subset else 'NO_FROZEN_FORECAST_INPUT_OR_WINDOW_INCOMPLETE'))
    known={x['model_id'] for x in models}
    return dict(schema='RACE_AI_EXISTING_MODEL_COVERAGE_V1',model_family_count=len(models),
        scope='previously inventoried 16 families; not every alias or pinned dependency',
        models=models,total_saved_forecasts=len(rows),scheduled_races_by_sport=scheduled,
        additional_model_ids=sorted(set(counts)-known),all_models_operational=False,
        no_new_predictor=True,missing_models_are_not_losses=True,
        counts_only=True,schedule_completeness_proven=False)


_STAGES=('P0','P1')
_NATIVE_STAGES=_STAGES+('A_PRE_TRIAL','B_POST_TRIAL')
_SHA=re.compile(r'^[0-9a-f]{64}$')
_DISPATCH_STATES=frozenset(('NOT_APPLICABLE','INPUT_MISSING','TRAINED_ARTIFACT_MISSING',
    'DEADLINE_PASSED','RULE_FILTERED','UNCONNECTED_NATIVE_RUNTIME','SOURCE_NOT_AUTHORIZED',
    'INPUT_REJECTED','GENERATED_UNATTESTED','ORIGINAL_REUSED'))


def _need(ok,reason):
    if not ok:raise ValueError(reason)


def _time(value):
    if isinstance(value,str):
        try:value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:raise ValueError('invalid coverage timestamp') from None
    _need(isinstance(value,datetime) and value.utcoffset() is not None,
          'aware coverage timestamp required')
    return value


def _label(value):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=250


def _versions(value,known):
    _need(isinstance(value,dict) and set(value)<=set(known),'existing model version roster required')
    result={}
    for mid,items in value.items():
        items=(items,) if items is None or isinstance(items,str) else items
        _need(isinstance(items,(list,tuple)) and 1<=len(items)<=16 and
              all(v is None or _label(v) for v in items) and len(set(items))==len(items),
              'unique nonempty model versions required')
        result[mid]=tuple(items)
    return result


def _receipt_metadata(row,cutoff,now):
    """Check metadata consistency, never authenticate a caller's receipt claim."""
    required=('as_of','server_saved_at','artifact_id','original_json_sha256')
    model_sha=row.get('model_sha256',row.get('prediction_sha256'))
    if (any(row.get(k) is None for k in required) or
        type(row.get('artifact_id')) is not int or row['artifact_id']<=0 or
        not isinstance(model_sha,str) or not _SHA.fullmatch(model_sha) or
        not isinstance(row['original_json_sha256'],str) or
        not _SHA.fullmatch(row['original_json_sha256'])):
        return 'SAVED_RECEIPT_UNVERIFIED',False,['RECEIPT_METADATA_MISSING']
    try:asof,saved=_time(row['as_of']),_time(row['server_saved_at'])
    except ValueError:return 'SAVED_RECEIPT_UNVERIFIED',False,['RECEIPT_TIMESTAMP_INVALID']
    if asof>=cutoff or saved>=cutoff:
        return 'SAVED_AFTER_CUTOFF',False,['NO_PRE_CUTOFF_RECEIPT']
    # GitHub metadata truncates fractional seconds; preserve the existing
    # reader's strict one-second exception, rather than inventing receipt time.
    if not (asof<=saved or saved.microsecond==0 and saved<=asof<saved+timedelta(seconds=1)):
        return 'SAVED_RECEIPT_UNVERIFIED',False,['RECEIPT_BEFORE_INPUT']
    if now is not None and max(asof,saved)>now:
        return 'SAVED_RECEIPT_UNVERIFIED',False,['RECEIPT_OR_INPUT_IN_FUTURE']
    return 'RECEIPT_METADATA_CONSISTENT',True,['INDEPENDENT_RECEIPT_AUTHENTICATION_NOT_PERFORMED']


def coverage_matrix(schedule,forecast_rows,*,stages=None,now=None,model_versions=None):
    """Materialize supplied race/stage IDs against all sixteen existing families.

    Schedule rows require race_id, sport and aware cutoff_at. A row with stage
    requests exactly that stage; otherwise it expands ``stages`` (default P0/P1).
    A supplied stage must belong to ``stages`` when that filter is explicit.
    ``model_versions`` optionally maps existing model IDs to expected versions;
    each version gets its own slot. A schedule row's model_versions overrides
    those defaults. Scalars pin one version; lists request separate slots.
    Undeclared conflicting issued versions are rejected.

    Plain dictionaries cannot attest external authenticity. This pure report
    validates supplied receipt metadata and preserves dispatcher input reasons,
    but never calls a saved/generated row independently verified. It does not
    fetch, execute predictors, copy private forecasts or certify race discovery.
    """
    _need(isinstance(schedule,list) and len(schedule)<=10000,'explicit bounded race ledger required')
    _need(isinstance(forecast_rows,list) and len(forecast_rows)<=500000,'bounded forecast rows required')
    requested=_STAGES if stages is None else stages
    _need(isinstance(requested,(list,tuple)) and requested and
          all(s in _NATIVE_STAGES for s in requested) and len(set(requested))==len(requested),
          'unique requested native stages required')
    clock=None if now is None else _time(now)
    specs=catalog();by_model={m['model_id']:m for m in specs}
    ledger={};races={};row_versions={}
    for row in schedule:
        _need(isinstance(row,dict) and _label(row.get('race_id')) and row.get('sport') in ALL,
              'race identity and supported sport required')
        rid,sport=row['race_id'],row['sport'];cutoff=_time(row.get('cutoff_at'))
        prefix=rid.split(':',1)[0]
        _need(prefix not in ALL or prefix==sport,'race identity/sport mismatch')
        identity=(sport,cutoff)
        _need(rid not in races or races[rid]==identity,'conflicting race metadata')
        races[rid]=identity
        row_stages=(row['stage'],) if 'stage' in row else requested
        _need(all(s in _NATIVE_STAGES and (stages is None or s in requested) for s in row_stages),
              'schedule stage not requested')
        roster=_versions(row.get('model_versions',{}),by_model)
        for phase in row_stages:
            key=(rid,phase)
            _need(key not in ledger,'duplicate race/stage schedule')
            ledger[key]=(sport,cutoff)
            row_versions[key]=roster
    versions=_versions({} if model_versions is None else model_versions,by_model)
    declared={key:{**versions,**row_versions[key]} for key in ledger}
    incoming={};observed_versions={};placeholders=set();slot_groups=Counter()
    for row in forecast_rows:
        _need(isinstance(row,dict),'forecast row must be an object')
        rid,phase,mid=row.get('race_id'),row.get('stage'),row.get('model_id')
        _need(isinstance(rid,str) and isinstance(phase,str) and (rid,phase) in ledger,
              'forecast race/stage absent from schedule')
        _need(isinstance(mid,str) and mid in by_model,'unknown model family')
        sport,cutoff=ledger[(rid,phase)]
        _need(row.get('sport')==sport,'forecast sport mismatch')
        if 'cutoff_at' in row:_need(_time(row['cutoff_at'])==cutoff,'forecast cutoff mismatch')
        version=row.get('model_version')
        _need(version is None or _label(version),'invalid model version')
        status=row.get('status')
        _need(status is None or isinstance(status,str) and status in _DISPATCH_STATES,
              'unsupported dispatcher status')
        # A blocked dispatcher slot has no issued model version. It requests
        # the input for each expected version, rather than inventing a None
        # version or conflicting with real originals on other races.
        placeholder=version is None and status not in (None,'GENERATED_UNATTESTED','ORIGINAL_REUSED')
        roster=declared[(rid,phase)].get(mid)
        if roster is not None and not placeholder:
            _need(version in roster,'forecast version absent from roster')
        if roster is None and not placeholder:observed_versions.setdefault(mid,set()).add(version)
        applies=sport in by_model[mid]['applicable_sports']
        _need(applies or status=='NOT_APPLICABLE','specialist forecast cannot run another sport')
        _need(not applies or status!='NOT_APPLICABLE','applicable model cannot be omitted as not applicable')
        if row.get('reason') is not None:_need(_label(row['reason']),'invalid dispatcher reason')
        key=(rid,phase,mid,version)
        _need(key not in incoming,'duplicate race/stage/model/version forecast')
        incoming[key]=row
        slot_groups[key[:3]]+=1
        if placeholder:placeholders.add(key)
    for rid,phase,mid,version in placeholders:
        _need(slot_groups[(rid,phase,mid)]==1,
              'duplicate placeholder and versioned forecast')
    for mid,values in observed_versions.items():
        _need(len(values)==1,'model version roster required for mixed versions')
    expected={key:{mid:declared[key][mid] if mid in declared[key] else
                   tuple(observed_versions.get(mid,{None})) for mid in by_model} for key in ledger}
    _need(sum(len(v) for roster in expected.values() for v in roster.values())<=500000,
          'coverage matrix too large')
    slots=[]
    for (rid,phase),(sport,cutoff) in ledger.items():
        for spec in specs:
            mid=spec['model_id'];applies=sport in spec['applicable_sports']
            for version in expected[(rid,phase)][mid]:
                supplied=incoming.get((rid,phase,mid,version));consistent=False
                wildcard=(rid,phase,mid,None)
                if supplied is None and wildcard in placeholders:supplied=incoming[wildcard]
                if not applies:state,reasons='NOT_APPLICABLE',['MODEL_SPORT_NOT_APPLICABLE']
                elif supplied is None:
                    if clock is not None and cutoff<=clock:
                        state,reasons='DEADLINE_PASSED',['NO_PRE_CUTOFF_FORECAST']
                    else:state,reasons='INPUT_MISSING',['NO_SAVED_FORECAST','INPUT_READINESS_NOT_PROVEN']
                elif supplied.get('status') not in (None,'ORIGINAL_REUSED'):
                    state=supplied['status'];reasons=[supplied.get('reason') or state]
                else:state,consistent,reasons=_receipt_metadata(supplied,cutoff,clock)
                item=dict(race_id=rid,sport=sport,stage=phase,model_id=mid,model_version=version,
                    cutoff_at=cutoff.isoformat(),applicable=applies,state=state,reasons=reasons,
                    required_input=spec['required_input'],receipt_metadata_consistent=consistent,
                    independent_receipt_verified=False)
                if supplied is not None and supplied.get('status') is not None:
                    item['reported_status']=supplied['status']
                    item['reported_model_version']=supplied.get('model_version')
                slots.append(item)
    applicable=sum(s['applicable'] for s in slots)
    receipts=sum(s['receipt_metadata_consistent'] for s in slots)
    return dict(schema='RACE_AI_EXISTING_MODEL_COVERAGE_MATRIX_V1',model_family_count=len(specs),
        scheduled_races=len(races),race_stage_count=len(ledger),slot_count=len(slots),
        applicable_slots=applicable,not_applicable_slots=len(slots)-applicable,
        receipt_metadata_slots=receipts,missing_receipt_metadata_slots=applicable-receipts,
        independently_verified_frozen_slots=0,missing_frozen_slots=applicable,
        states=dict(Counter(s['state'] for s in slots)),slots=slots,counts_only=False,
        verification_scope='SUPPLIED_METADATA_ONLY',independent_receipts_verified=False,
        schedule_completeness_proven=False,all_models_operational=False,
        no_new_predictor=True,missing_models_are_not_losses=True)
