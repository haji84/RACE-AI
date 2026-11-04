"""Coverage of the sixteen previously inventoried families, not invented picks.

An applicable model remains visible when its genuine inputs are absent. Merely
registering a model never makes it operational or adds a forecast to a score.
"""
from collections import Counter
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
        no_new_predictor=True,missing_models_are_not_losses=True)
