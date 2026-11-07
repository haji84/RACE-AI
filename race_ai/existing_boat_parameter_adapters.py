"""Optional coefficients for six existing native BOAT research families.

Native inputs, equations, clamps and mixture policies remain owned by their
original modules. Source/time admission belongs to the existing dispatcher;
this adapter neither fetches evidence nor turns caller coefficients into a fit.
"""
import math

from .boat_ab_shadow import MODEL_IDS as AB, build_pair
from .boat_live_feature_shadow import MODEL_ID as CLITE, build_live_feature_shadow
from .boat_tactical_scenarios import MODEL_ID as TACTICAL, predict_tactical_shadow
from .boat_multi_feature_models import MODEL_IDS as FULL, run_models


def _defaults(model_id):
    base = dict(log_national_rate=1., exhibition_delta=1.)
    course = dict(base, **{'course_log_bonus_'+str(i): value for i, value in
                          enumerate((.20, .10, .04, -.04, -.12, -.18), 1)}, motor_deviation=.003)
    if model_id == AB[0]:
        return base
    if model_id == AB[1]:
        return course
    if model_id == CLITE:
        return dict(course, local_rate_delta=.08, average_st_delta=2., exhibition_st_delta=.65)
    if model_id == TACTICAL:
        return dict(base, course_logratio=.45, recent_form_delta=.38, displacement=.4,
                    inside_defense=.40, inside_loss_method=.12, winning_method=.30)
    if model_id == FULL[0]:
        return dict(ability=1.25, recent=1., motor=.75, course=.65, start=.35,
                    exhibition=.35, st=.2, lane_prior=.3)
    if model_id == FULL[1]:
        components = {
            'calm': dict(ability=.55, recent=.45, motor=.55, course=.5, lane_prior=.8,
                         start=.55, st=.55, exhibition=.25),
            'attack': dict(ability=.75, recent=.8, motor=.5, course=.35, start=.9,
                           exhibition=.7, st=.5, lane_prior=-.2),
            'rough': dict(ability=.9, recent=.45, course=.95, motor=.45, start=.3,
                          exhibition=.25, lane_prior=.55, breeze=-.15, swell=-.10, rain=-.08),
        }
        return {component+'_'+name: value for component, values in components.items()
                for name, value in values.items()}
    raise ValueError('unknown native BOAT family')


def specs(model_id, sport='boat'):
    """Existing utility coefficients with finite bounds retaining their sign."""
    if sport != 'boat':
        raise ValueError('native BOAT family cannot train another sport')
    return {name: (value, 0. if value > 0 else 3*value-1.,
                   0. if value < 0 else 3*value+1.)
            for name, value in _defaults(model_id).items()}


def validate_parameters(model_id, parameters):
    specification = specs(model_id)
    if type(parameters) is not dict or set(parameters) != set(specification):
        raise ValueError('exact native research coefficient names required')
    if any(type(value) not in (int, float) or not math.isfinite(value) or
           not specification[name][1] <= value <= specification[name][2]
           for name, value in parameters.items()):
        raise ValueError('finite bounded native research coefficients required')
    return dict(parameters)


def validate_group_parameters(parameters, model_ids):
    if type(parameters) is not dict or not parameters or not set(parameters) <= set(model_ids):
        raise ValueError('existing native model coefficient mapping required')
    return {mid: validate_parameters(mid, values) for mid, values in parameters.items()}


def predict(model_id, payload, parameters=None, *, at, allow_source=None):
    """Return one original native output, with optional research coefficients."""
    _defaults(model_id)
    checked = None if parameters is None else validate_parameters(model_id, parameters)
    if type(payload) is not dict:
        raise ValueError('native input mapping required')
    required = (('source',) if model_id in AB else
                ('base_source', 'extra') if model_id == CLITE else
                ('source', 'histories', 'venue') if model_id == TACTICAL else ('snapshot',))
    if any(not payload.get(name) for name in required):
        raise ValueError('genuine native input missing')
    if model_id in AB:
        group = None if checked is None else {model_id: checked}
        return build_pair(payload['source'], at, parameters=group)['models'][AB.index(model_id)]
    if model_id == CLITE:
        return build_live_feature_shadow(payload['base_source'], payload['extra'], at, parameters=checked)
    if model_id == TACTICAL:
        return predict_tactical_shadow(payload['source'], payload['histories'], payload['venue'], at,
                                       parameters=checked)
    group = None if checked is None else {model_id: checked}
    return run_models(payload['snapshot'], parameters=group)[model_id]


def probability(model_id, payload, parameters, winning, *, at, allow_source=None):
    """Exact native winning-order likelihood; tactical skips other 119 tickets."""
    if (type(winning) not in (list, tuple) or len(winning) != 3 or
            any(type(n) is not int or n not in range(1, 7) for n in winning) or len(set(winning)) != 3):
        raise ValueError('three distinct native BOAT winning lanes required')
    if model_id == TACTICAL:
        from .boat_tactical_scenarios import tactical_winner_probability
        checked = None if parameters is None else validate_parameters(model_id, parameters)
        if type(payload) is not dict or any(not payload.get(k) for k in ('source', 'histories', 'venue')):
            raise ValueError('genuine native input missing')
        return tactical_winner_probability(payload['source'], payload['histories'], payload['venue'],
                                           at, winning, parameters=checked)
    output = predict(model_id, payload, parameters, at=at, allow_source=allow_source)
    for row in output.get('candidates', output.get('full_120', ())):
        ticket = row.get('combination') or [int(n) for n in row['ticket'].split('-')]
        if ticket == list(winning):
            return row['score']
    raise ValueError('native candidate distribution missing winning order')
