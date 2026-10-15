"""Pure name-bound v2 numeric research; original B remains the frozen prior."""
import copy
import hashlib
import math

if __package__:
    from . import race_contract as facts, research_contract as research, exhibition_contract as display
    from .original_prediction_contract import PARAMETERS, COEFFICIENTS
    from .name_bound_inputs import validate_name_bound_inputs
else:
    import race_contract as facts
    import research_contract as research
    import exhibition_contract as display
    from original_prediction_contract import PARAMETERS, COEFFICIENTS
    from name_bound_inputs import validate_name_bound_inputs

MAX_BYTES=256_000
RECEIPT={'schema_version','request_id','baseline_request_id','name_binding_request_id','snapshot','cloud_saved_at','cloud_eligible_pre_race'}
MARKER={'schema_version','race_id','request_id','snapshot_id','input_snapshot_id','baseline_request_id','name_binding_request_id','receipt_sha256','receipt_confirmed_at'}

def require(condition):
    if not condition:raise ValueError('NAME_BOUND_PREDICTION_INVALID')

def digest(value):return hashlib.sha256(facts.canonical(value)).hexdigest()

def _assemble(inputs,race,baseline,binding,*,runner_saved_at,input_cloud_saved_at,parents_resolved_at,now):
    clock,day,closed=display._clock(now,race)
    inputs=validate_name_bound_inputs(inputs,race,baseline,binding,now=clock)
    times=[facts._time(v) for v in (inputs['generated_at'],runner_saved_at,parents_resolved_at,input_cloud_saved_at,clock)]
    require(times==sorted(times) and all(t<closed and t.astimezone(facts.JST).date()==day for t in times))
    models={m['model_id']:m for m in baseline['snapshot']['models']}
    base=models[research.RATING_MODEL] if research.RATING_MODEL in models else models[research.UNIFORM_MODEL]
    strengths={r['lane']:r['strength'] for r in base['strengths']}
    original=sorted(inputs['original_observation']['boats'],key=lambda b:b['lane'])
    values={r['lane']:dict(display_time_s=r['display_time_s'],**r['original_times']) for r in original}
    means={k:math.fsum(values[lane][k] for lane in range(1,7))/6 for k in COEFFICIENTS}
    programs={b['lane']:b for b in race['boats']}
    boats=[]
    for row in original:
        lane=row['lane'];strength=strengths[lane]
        contributions={k:dict(delta_seconds=means[k]-values[lane][k],coefficient_per_second=c,
            log_strength_contribution=c*(means[k]-values[lane][k])) for k,c in COEFFICIENTS.items()}
        total=math.fsum(contributions[k]['log_strength_contribution'] for k in COEFFICIENTS)
        adjusted=lambda delta:math.exp(max(-20.0,min(20.0,math.log(strength)+delta)))
        boats.append(dict(lane=lane,racer_registration_id=row['racer_registration_id'],program_name=programs[lane]['name'],
            verified_full_name=row['name'],display_time_s=row['display_time_s'],original_times=copy.deepcopy(row['original_times']),
            base_strength=strength,display_delta_seconds=contributions['display_time_s']['delta_seconds'],contributions=contributions,
            total_original_log_delta=total,display_adjusted_strength=adjusted(contributions['display_time_s']['log_strength_contribution']),
            original_adjusted_strength=adjusted(total)))
    forecasts=[];deltas=[]
    for kind,parameters in [('display',display.PARAMETERS),('original',PARAMETERS)]:
        model=dict(model_id='name-bound-'+kind,model_version='2',parameters=dict(parameters),
            **research.plackett_luce({b['lane']:b[kind+'_adjusted_strength'] for b in boats}))
        forecasts.append(model)
        deltas.append(dict(model_id=model['model_id'],triples=[dict(combination=list(old['combination']),
            **display._delta(old['probability'],new['probability'])) for old,new in zip(base['triples'],model['triples'])],
            marginals=[dict(lane=old['lane'],**{p:display._delta(old[p+'_probability'],new[p+'_probability']) for p in display.POSITIONS})
            for old,new in zip(base['marginals'],model['marginals'])]))
    count=sum(b['preview_st_status']!='PENDING' for b in inputs['beforeinfo_record']['data']['boats'])
    features=dict(display_time=dict(status='AVAILABLE',used=True,reason=None),original_exhibition=dict(status='AVAILABLE',used=True,reason=None),
        preview_st=dict(status='OBSERVED_UNUSED' if count==6 else 'PARTIAL_UNUSED' if count else 'MISSING',used=False,reason='NOT_USED_BY_ORIGINAL_TIMING_MODEL'),
        weather=dict(status='SOURCE_TIME_UNVERIFIED_UNUSED',used=False,reason='SOURCE_TIME_HAS_NO_DATE'),
        exhibition_video=dict(status='MISSING',used=False,reason='NO_VALIDATED_BOAT_FEATURES'))
    result=dict(schema_version=1,kind='NAME_BOUND_EXHIBITION_PREDICTION',variant='name-bound-v2',phase='post_exhibition_numeric_inputs',
        race_id=race['race_id'],date_jst=day.isoformat(),closed_at=facts.stamp(closed),as_of=facts.stamp(clock),generated_at=facts.stamp(clock),
        program_identity_sha256=inputs['program_identity_sha256'],validation_program_identity_sha256=inputs['validation_program_identity_sha256'],
        baseline_link={**inputs['baseline_link'],'model_id':base['model_id']},name_binding_link=copy.deepcopy(inputs['name_binding_link']),
        input_link=dict(snapshot_id=inputs['snapshot_id'],sha256=digest(inputs),runner_saved_at=facts.stamp(runner_saved_at),input_cloud_saved_at=facts.stamp(input_cloud_saved_at)),
        parents_resolved_at=facts.stamp(parents_resolved_at),boats=boats,models=forecasts,deltas=deltas,feature_status=features,
        research_only=True,validation_status='UNVALIDATED',purchase_decision='skip',purchase_recommendations=[],physical_exhibition_timing_verified=False)
    result['snapshot_id']=digest(result);require(len(facts.canonical(result))<=MAX_BYTES)
    return result

def build_name_bound_prediction(inputs,race,baseline,binding,*,runner_saved_at,input_cloud_saved_at,parents_resolved_at,now):
    try:
        return _assemble(inputs,race,baseline,binding,runner_saved_at=runner_saved_at,input_cloud_saved_at=input_cloud_saved_at,parents_resolved_at=parents_resolved_at,now=now)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,RecursionError) as exc:
        raise ValueError('NAME_BOUND_PREDICTION_INVALID') from exc

def validate_name_bound_prediction(snapshot,inputs,race,baseline,binding,*,now):
    try:
        clock,_,_=display._clock(now,race)
        require(isinstance(snapshot,dict) and len(facts.canonical(snapshot))<=MAX_BYTES)
        generated=facts._time(snapshot['generated_at']);require(generated<=clock)
        link=snapshot['input_link']
        expected=_assemble(inputs,race,baseline,binding,runner_saved_at=link['runner_saved_at'],input_cloud_saved_at=link['input_cloud_saved_at'],
            parents_resolved_at=snapshot['parents_resolved_at'],now=generated)
        require(facts.canonical(snapshot)==facts.canonical(expected))
        return expected
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,RecursionError) as exc:
        raise ValueError('NAME_BOUND_PREDICTION_INVALID') from exc

def validate_name_bound_envelope(envelope,race,*,now):
    try:
        clock,day,closed=display._clock(now,race)
        require(isinstance(envelope,dict) and set(envelope)=={'receipt','finalization','inputs','baseline','name_binding'} and len(facts.canonical(envelope))<=MAX_BYTES)
        r=envelope['receipt'];m=envelope['finalization'];i=envelope['inputs'];base=envelope['baseline'];binding=envelope['name_binding']
        require(isinstance(r,dict) and set(r)==RECEIPT and type(r['schema_version']) is int and r['schema_version']==1 and r['cloud_eligible_pre_race'] is True)
        require(isinstance(m,dict) and set(m)==MARKER and type(m['schema_version']) is int and m['schema_version']==1)
        # Same nonce syntax as the immutable publication stores, without importing API code.
        import re
        require(all(isinstance(r[k],str) and re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,3}',r[k]) for k in ('request_id','baseline_request_id','name_binding_request_id')))
        s=validate_name_bound_prediction(r['snapshot'],i,race,base,binding,now=clock)
        require(r['baseline_request_id']==base['request_id'] and r['name_binding_request_id']==binding['receipt']['request_id'])
        require(m==dict(schema_version=1,race_id=race['race_id'],request_id=r['request_id'],snapshot_id=s['snapshot_id'],input_snapshot_id=i['snapshot_id'],
            baseline_request_id=r['baseline_request_id'],name_binding_request_id=r['name_binding_request_id'],receipt_sha256=digest(r),receipt_confirmed_at=m['receipt_confirmed_at']))
        generated,saved,confirmed=map(facts._time,(s['generated_at'],r['cloud_saved_at'],m['receipt_confirmed_at']))
        require(generated<=saved<=confirmed<=clock and confirmed<closed and all(t.astimezone(facts.JST).date()==day for t in (saved,confirmed)))
        require(r['cloud_saved_at']==facts.stamp(saved) and m['receipt_confirmed_at']==facts.stamp(confirmed))
        return copy.deepcopy(envelope)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,RecursionError) as exc:
        raise ValueError('NAME_BOUND_ENVELOPE_INVALID') from exc
