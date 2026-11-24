"""Estimate cross-line finishes and large trifecta payouts from pre-race evidence."""

from math import log

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from scripts.keirin_targeted_choice_study import rescale_group


MANSHAKEN_THRESHOLD_YEN = 10_000


def payout_risk(amounts):
    """Classify the official payout per 100 yen once the race has settled."""
    if not amounts:
        return None
    if any(type(amount) is not int or amount < 100 for amount in amounts):
        raise ValueError('A payout label requires valid amounts in yen.')
    types = {amount >= MANSHAKEN_THRESHOLD_YEN for amount in amounts}
    return next(iter(types)) if len(types) == 1 else None


def line_risk(lines, paid):
    """Classify paid first and second places on the announced lines."""
    if not lines or not paid or len(lines)==1 or all(len(line)==1 for line in lines):
        return None
    group_for = {car:index for index,line in enumerate(lines) for car in line}
    if any(a not in group_for or b not in group_for for a,b,_ in paid):
        return None
    types = {group_for[a]!=group_for[b] for a,b,_ in paid}
    return next(iter(types)) if len(types) == 1 else None


def concentrated(values, size):
    return float(np.sort(values)[-size:].sum())


def race_vector(snapshot, cars, order, probability):
    """Describe the current field and the reference distribution before the result."""
    if {'outcomes','result','payouts'} & snapshot.keys():
        raise ValueError('An observed result cannot enter the risk predictor.')
    riders = {row['car']:row for row in snapshot['riders']}
    lines = snapshot['line_groups']
    group_for = {car:index for index,line in enumerate(lines) for car in line}
    if set(cars)!=set(riders) or set(cars)!=set(group_for):
        raise ValueError('Forecast, published lines and entrants must match.')
    field = len(cars)
    group = np.array([group_for[car] for car in cars])
    lengths = sorted((len(line) for line in lines),reverse=True)
    head,follower,_ = order.T
    pair = np.zeros((field,field))
    np.add.at(pair,(head,follower),probability)
    first = pair.sum(axis=1)
    cross = group[head]!=group[follower]
    cross_mass=float(probability[cross].sum())
    distinct = len(lines)>1 and any(len(line)>1 for line in lines)
    points = {car:row.get('competition_points') for car,row in riders.items()}
    ranked = sorted(((score,car) for car,score in points.items() if score is not None), reverse=True)
    numbers = [value for value,_ in ranked]
    gaps = [numbers[0]-numbers[i] if len(numbers)>i else 0. for i in (1,2,3)]
    same_top = len(ranked)>=2 and group_for[ranked[0][1]]==group_for[ranked[1][1]]
    line_mass_first = np.bincount(group, weights=first)
    ranker_entropy = -(probability*np.log(np.maximum(probability,1e-12))).sum()/log(len(probability))
    examples = [row.get('win_rate') for row in riders.values() if row.get('win_rate') is not None]
    known_b = [row.get('b_count') for row in riders.values() if row.get('b_count') is not None]
    marks = [row.get('mark_rank') for row in riders.values()]
    values = np.array([
        field,len(lines),lengths[0],lengths[1] if len(lengths)>1 else 0,lengths.count(1),
        len(numbers)/field,np.std(numbers) if numbers else 0.,*gaps,same_top,
        sum(str(r.get('class','')).startswith('S') for r in riders.values())/field,
        sum(str(r.get('class','')).startswith('L') for r in riders.values())/field,
        max(examples,default=0.),max(known_b,default=0.),len(known_b)/field,
        any(value is not None for value in marks),cross_mass,line_mass_first.max(),
        first.max(),concentrated(first,2),pair.max(),concentrated(pair.ravel(),4),
        probability.max(),concentrated(probability,4),concentrated(probability,8),ranker_entropy,
        np.sum(np.where(np.eye(field,dtype=bool),0,pair)*pair.T),
    ], dtype=float)
    return values,cross,cross_mass if distinct else None


def fit_probability(values, labels):
    matrix=np.asarray(values,dtype=float)
    target=np.asarray(labels,dtype=float)
    if matrix.ndim!=2 or matrix.shape[0]!=len(target) or set(target)!={0.,1.} or not np.all(np.isfinite(matrix)):
        raise ValueError('Fitting requires finite, aligned inputs and both observed outcomes.')
    mean=matrix.mean(axis=0)
    deviation=matrix.std(axis=0)
    scale=np.where(deviation>1e-6,deviation,1.)
    inputs=np.column_stack((np.ones(len(matrix)),np.clip((matrix-mean)/scale,-5,5)))
    ridge=np.r_[0.,np.full(matrix.shape[1],.035)]

    def objective(weights):
        score=inputs @ weights
        loss=(np.logaddexp(0,score)-target*score).mean()+.5*np.sum(ridge*weights**2)
        gradient=inputs.T @ (expit(score)-target)/len(target)+ridge*weights
        return loss,gradient

    fit=minimize(objective,np.zeros(inputs.shape[1]),method='L-BFGS-B',jac=True)
    if not fit.success:
        raise RuntimeError(f'Risk fit did not converge: {fit.message}')
    return {'center':mean.tolist(),'scale':scale.tolist(),'weights':fit.x.tolist()}


def predict_probability(model, values):
    inputs=np.clip((np.asarray(values)-model['center'])/model['scale'],-5,5)
    return expit(model['weights'][0]+inputs @ model['weights'][1:])


def line_mass(probability, cross, target):
    return rescale_group(probability[None,:],cross[None,:],np.array([target]))[0]


def guarded_order(original, revised, *, size=8, protect=4):
    if not 0 <= protect <= size <= len(original) or len(original)!=len(revised):
        raise ValueError('The retained ranks must fit the common field and budget.')
    ahead=list(original[:protect])
    retained=set(ahead)
    remaining=[item for item in revised if item not in retained]
    return np.asarray(ahead+remaining[:size-protect])
