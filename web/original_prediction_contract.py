"""Untrained within-race display/lap/turn/straight PL, pinned to three receipts."""
import copy
import math

if __package__:
    from . import exhibition_contract as display,original_exhibition_contract as original,research_contract as research,race_contract as facts
else:
    import exhibition_contract as display
    import original_exhibition_contract as original
    import research_contract as research
    import race_contract as facts

PARAMETERS=dict(display_coefficient_per_second=1.0,lap_coefficient_per_second=.05,
    turn_coefficient_per_second=.20,straight_coefficient_per_second=.20,
    log_strength_min=-20.0,log_strength_max=20.0,rating_floor=.01)
COEFFICIENTS=dict(display_time_s=1.0,lap_s=.05,turn_s=.20,straight_s=.20)


def _assemble(baseline,preview,receipt,race,now):
    # Display contract fully validates the first two immutable inputs, frozen B
    # model selection and all source clocks. Its computed payload is detached.
    post=display._assemble(baseline,preview,race,now)
    if receipt is None:raise display.ExhibitionUnavailable('ORIGINAL_NOT_OBTAINED')
    original.validate_original_receipt(receipt,race,now)
    observation=receipt['observation']
    if observation['status']!='AVAILABLE':raise display.ExhibitionUnavailable('ORIGINAL_TIMINGS_INCOMPLETE')
    if receipt['cloud_eligible_pre_race'] is not True:raise display.ExhibitionUnavailable('ORIGINAL_NOT_PRE_RACE')
    by_lane={row['lane']:row for row in observation['boats']}
    values={lane:dict(display_time_s=row['display_time_s'],**row['original_times']) for lane,row in by_lane.items()}
    means={key:math.fsum(row[key] for row in values.values())/6 for key in COEFFICIENTS}
    for boat in post['boats']:
        lane=boat['lane'];source=by_lane[lane]
        if source['display_time_s']!=boat['display_time_seconds']:
            raise display.ExhibitionUnavailable('ORIGINAL_DISPLAY_CONFLICT')
        contributions={key:dict(delta_seconds=means[key]-values[lane][key],coefficient_per_second=coefficient,
            log_strength_contribution=coefficient*(means[key]-values[lane][key])) for key,coefficient in COEFFICIENTS.items()}
        total=math.fsum(value['log_strength_contribution'] for value in contributions.values())
        boat.update(original_times=copy.deepcopy(source['original_times']),contributions=contributions,total_log_strength_delta=total,
            adjusted_strength=math.exp(max(-20.0,min(20.0,math.log(boat['base_strength'])+total))))
    distribution=research.plackett_luce({row['lane']:row['adjusted_strength'] for row in post['boats']})
    base=next(model for model in baseline['snapshot']['models'] if model['model_id']==post['baseline_link']['model_id'])
    model=dict(model_id='official-display-original-pl',model_version='1',parameters=dict(PARAMETERS),**distribution)
    deltas=dict(triples=[dict(combination=list(old['combination']),**display._delta(old['probability'],new['probability']))
        for old,new in zip(base['triples'],model['triples'])],marginals=[dict(lane=old['lane'],
            **{position:display._delta(old[position+'_probability'],new[position+'_probability']) for position in display.POSITIONS})
        for old,new in zip(base['marginals'],model['marginals'])])
    post.update(variant='original-v1',model=model,deltas=deltas,original_link=dict(request_id=receipt['request_id'],
        snapshot_id=observation['snapshot_id'],receipt_sha256=display.digest(receipt),runner_saved_at=facts.stamp(receipt['runner_saved_at']),
        cloud_saved_at=facts.stamp(receipt['cloud_saved_at']),sources=copy.deepcopy(observation['sources'])))
    post['feature_status']['original_exhibition']=dict(status='AVAILABLE',used=True,reason=None)
    post['feature_status']['preview_st']['reason']='NOT_USED_BY_ORIGINAL_TIMING_MODEL'
    post['snapshot_id']=display.digest({key:value for key,value in post.items() if key!='snapshot_id'})
    facts._require(len(facts.canonical(post))<=256_000,'original prediction exceeds bounded contract')
    return post


def build_original_prediction_bundle(baseline,race_bundle,receipt,race,now):
    try:
        clock,_,closed=display._clock(now,race)
        sources=facts.validate_cloud_bundle(race_bundle,race,clock)
        post=_assemble(baseline,sources.get('beforeinfo'),receipt,race,clock)
        if clock>=closed:raise display.ExhibitionUnavailable('CUTOFF_PASSED')
        return post
    except (TypeError,KeyError,AttributeError,UnicodeError,OverflowError) as exc:
        raise ValueError('original prediction evidence malformed') from exc


def validate_original_prediction_bundle(bundle,baseline,preview,receipt,race,now):
    try:
        clock,_,closed=display._clock(now,race)
        generated=facts._time(bundle['generated_at'])
        facts._require(facts._time(bundle['as_of'])==generated<closed and generated<=clock,'original prediction generation invalid')
        expected=_assemble(baseline,preview,receipt,race,generated)
        facts._require(facts.canonical(bundle)==facts.canonical(expected),'original prediction differs from pinned replay')
        return expected
    except (TypeError,KeyError,AttributeError,UnicodeError,OverflowError) as exc:
        raise ValueError('original prediction bundle malformed') from exc
