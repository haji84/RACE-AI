"""Research paired and third-rider context within the existing KEIRIN ranker."""

from math import isfinite, log1p

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from scripts import keirin_fit_ranking_weights as fitter
from scripts import keirin_line_history_study as lines
from scripts import keirin_small_ticket_study as ranking


BASE = 'published_line'
METHODS = ('baseline', 'third_line', 'pair_and_third')
PHASE_COUNTS = ('S', 'h_count', 'b_count')


def frame(snapshot):
    """Use the published pre-race grouping and fields for each starter."""
    if {'result', 'outcomes', 'payouts'} & set(snapshot):
        raise ValueError('Current race outcomes cannot enter a forecast.')
    base = lines.frame(snapshot)
    riders = {row['car']: row for row in snapshot['riders']}
    counts = np.array([
        [value if type(value := riders[car].get(field)) in (int, float)
         and isfinite(value) and 0 <= value <= 99 else np.nan for field in PHASE_COUNTS]
        for car in base[0]
    ])
    known = np.isfinite(counts)
    activity = np.log1p(np.nan_to_num(counts)) / log1p(99)
    denominator = np.maximum(known.sum(axis=0), 1)
    within_field = (activity - activity.sum(axis=0) / denominator) * known
    return base, np.column_stack((within_field, known))


def line_context(group, position, size, prefix):
    """Compare available riders to the proposed earlier finishers."""
    role = np.eye(4)[np.where(size == 1, 3, np.minimum(position, 2))]
    head = prefix[0][:, None]
    shares_head = group == group[head]
    if len(prefix) == 1:
        pair_roles = (role[head][..., :, None] * role[None, :, None, :]).reshape(len(head), len(group), 16)
        return np.concatenate((pair_roles * shares_head[..., None],
                               pair_roles * (~shares_head)[..., None]), axis=-1)

    second = prefix[1][:, None]
    shares_second = group == group[second]
    same_pair = group[head] == group[second]
    relation = np.stack((same_pair & shares_head, same_pair & ~shares_head,
                         ~same_pair & shares_head, ~same_pair & shares_second,
                         ~same_pair & ~shares_head & ~shares_second), axis=-1)
    context = (relation[..., :, None] * role[None, :, None, :]).reshape(len(head), len(group), 20)
    next_after_head = shares_head & (position == position[head] + 1)
    next_after_second = shares_second & (position == position[second] + 1)
    earlier_in_line = (shares_head & (position < position[head])) | (
        shares_second & (position < position[second]))
    return np.concatenate((context, np.stack((next_after_head, next_after_second, earlier_in_line), axis=-1)),
                          axis=-1)


def additional_design(info, prefix):
    base, counts = info
    group, position, size = base[-3:]
    context = line_context(group, position, size, prefix)
    joins_front = group == group[prefix[0][:, None]]
    activity = np.broadcast_to(counts, (len(context), *counts.shape))
    return np.concatenate((context, activity, activity[..., :3] * joins_front[..., None]), axis=-1)


def fit_offset(logits, features, available, target):
    rows = np.arange(len(target))

    def objective(weights):
        adjusted = logits + features @ weights
        masked = np.where(available, adjusted, -np.inf)
        denominator = logsumexp(masked, axis=1)
        error = np.exp(masked - denominator[:, None])
        error[rows, target] -= 1
        loss = float((denominator - adjusted[rows, target]).mean()) + .001 * (weights @ weights)
        gradient = np.einsum('rn,rnf->f', error, features) / len(rows) + .002 * weights
        return loss, gradient

    fitted = minimize(objective, np.zeros(features.shape[-1]), jac=True, method='L-BFGS-B',
                      bounds=[(-12,12)] * features.shape[-1], options={'ftol': 1e-12})
    if not fitted.success:
        raise ValueError('Conditional fit failed to converge.')
    return fitted.x.tolist()


def fit(examples, frozen_coefficients=None):
    races = []
    for example in examples:
        paid = example['outcomes']
        if len(paid['3t']) != 1 or len(paid['2t']) != 1:
            continue
        trio = tuple(paid['3t'][0])
        if len(trio) != 3 or len(set(trio)) != 3 or trio[:2] != tuple(paid['2t'][0]):
            raise ValueError('Training exacta and trifecta results disagree.')
        info = frame(example['input'])
        cars = info[0][0]
        races.append((info,[cars.index(car) for car in trio]))
    if not races:
        raise ValueError('No earlier, unambiguous races to fit.')

    available = np.array([np.arange(9) < len(info[0][0]) for info,_ in races])
    results = np.array([order for _,order in races])
    base_weights, offsets = [], []
    for stage in range(3):
        names = lines.names_for(BASE, stage)
        matrix = np.zeros((len(races),9,len(names)))
        extras = None
        for index, (info, order) in enumerate(races):
            prefix = tuple(np.array([car]) for car in order[:stage])
            starter_count = len(info[0][0])
            matrix[index,:starter_count] = lines.design(info[0],BASE,prefix)[0]
            if stage:
                extra = additional_design(info,prefix)[0]
                if extras is None:
                    extras = np.zeros((len(races),9,extra.shape[-1]))
                extras[index,:starter_count] = extra
        observed = results[:,stage]
        weights = ([frozen_coefficients[stage][key] for key in names] if frozen_coefficients is not None
                   else fitter.fit_choice(matrix,available,observed))
        base_weights.append(dict(zip(names,weights,strict=True)))
        offsets.append(fit_offset(matrix @ np.array(weights),extras,available,observed) if stage else [])
        available[np.arange(len(races)),observed] = False
    return {'fit_races':len(races),'baseline':base_weights,'offsets':offsets}


def predict(snapshot, configuration, method):
    if method not in METHODS:
        raise ValueError('Unknown research comparison mode.')
    info = frame(snapshot)
    cars = info[0][0]
    base_weights = [
        np.array([mapping[key] for key in lines.names_for(BASE,stage)])
        for stage,mapping in enumerate(configuration['baseline'])
    ]
    adjusted_stages = {'baseline': (), 'third_line': (2,), 'pair_and_third': (1,2)}[method]
    offsets = {stage: np.array(configuration['offsets'][stage]) for stage in adjusted_stages}

    def conditional(prefix):
        stage = len(prefix)
        logits = lines.design(info[0],BASE,prefix) @ base_weights[stage]
        if stage in offsets:
            logits += additional_design(info,prefix) @ offsets[stage]
        return ranking.available_probabilities(logits,prefix)

    return ranking.conditional_rankings(cars,conditional)


def allocate_points(masses):
    """Choose 1, 4 or 8 using only forecast masses, with a total of 4 per race."""
    size = len(masses)
    choices = [4] * size
    gain = [eight-four for _,four,eight in masses]
    cost = [four-one for one,four,_ in masses]
    prioritize_eight = sorted(range(size),key=lambda i:(-gain[i],i))
    prioritize_one = sorted(range(size),key=lambda i:(cost[i],i))
    best = 0.0
    # Three increases of four points use the same total as four decreases of three.
    for groups in range(1, size//7 + 1):
        widen = set(prioritize_eight[:3*groups])
        narrow = [i for i in prioritize_one if i not in widen][:4*groups]
        increase = sum(gain[i] for i in widen) - sum(cost[i] for i in narrow)
        if increase > best:
            best = increase
            choices = [8 if i in widen else 4 for i in range(size)]
            for i in narrow:
                choices[i] = 1
    return choices
