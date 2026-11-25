"""Estimate finish orders by summing over possible H and B leaders."""

import numpy as np
from scipy.special import softmax

from scripts import keirin_line_event_study as history_study
from scripts import keirin_line_history_study as lines
from scripts import keirin_ordered_ticket_study as ordered


def transfer_design(groups, homes):
    same = groups[homes, None] == groups
    same_rider = homes[:, None] == np.arange(len(groups))
    independent = np.sum(groups[:, None] == groups, axis=1) == 1
    return np.stack((same_rider, same, same & ~same_rider, ~same & independent), axis=-1)


def back_given_home(logits, groups, weights):
    corrected = logits + transfer_design(groups, np.arange(len(groups))) @ weights
    return softmax(corrected, axis=-1)


def marginal_back(home_probabilities, conditional_back):
    return home_probabilities @ conditional_back


def finish_design(groups, roles, back, prefix):
    count = len(groups)
    width = len(prefix[0]) if prefix else 1
    own = (groups[back, None] == groups)[:, None, :]
    shape = (len(back), width, count)
    same_rider = (back[:, None] == np.arange(count))[:, None, :]
    blocks = [same_rider, own, own & (roles == 0), own & (roles == 1),
              own & (roles >= 2), ~own & (roles <= 1), ~own & (roles == 3)]
    prefix_flags = []
    for earlier in prefix:
        on_back_line = (groups[back, None] == groups[earlier])[:, :, None]
        prefix_flags.append(on_back_line)
        blocks.extend((own & on_back_line, own & ~on_back_line, same_rider & ~on_back_line))
    if len(prefix_flags) == 2:
        cross = prefix_flags[0] ^ prefix_flags[1]
        blocks.extend((own & cross, own & prefix_flags[0] & prefix_flags[1]))
    return np.stack([np.broadcast_to(value, shape) for value in blocks], axis=-1)


def phase_features(info, history):
    _, base, column, _, _, _ = info[0]
    return np.column_stack((
        base['relative_points'], base['relative_points_known'],
        base['points_percentile'], *[column[key] for key in lines.LINE_FIELDS],
        info[1], history.individual[:, (0, 1, 2, 9, 10)],
        column['line_leader'] * history.individual[:, 1],
    ))


def roles_and_groups(info):
    groups, positions, sizes = info[0][-3:]
    roles = np.where(sizes == 1, 3, np.minimum(positions, 2))
    return roles, groups


def regularized_offset(baseline, matrix, available, target, scale=1):
    weights = ordered.fit_offset(baseline, matrix / scale, available, target)
    return (np.array(weights) / scale).tolist()


def padded_features(examples, get_matrix):
    counts = np.array([len(example[0][0][0]) for example in examples])
    designs = [get_matrix(example) for example in examples]
    padded = np.zeros((len(designs), 9, designs[0].shape[-1]))
    for index, (count, matrix) in enumerate(zip(counts, designs, strict=True)):
        padded[index, :count] = matrix
    return padded, np.arange(9) < counts[:, None]


def unconditional(info, model):
    count = len(info[0][0])
    riders = np.arange(count)
    head, second = np.where(riders[:, None] != riders)
    first = softmax(model.logits(info, ()), axis=-1)[0]
    logits = model.logits(info, (riders,))
    logits[riders, riders] = -np.inf
    pairs = first[:, None] * softmax(logits, axis=-1)
    thirds = model.logits(info, (head, second))
    thirds[np.arange(len(head)), head] = -np.inf
    thirds[np.arange(len(head)), second] = -np.inf
    return (pairs[head, second, None] * softmax(thirds, axis=-1)).ravel()


class PhaseRanker:
    def __init__(self, baseline):
        self.model = history_study.SavedRanker(baseline)

    def fit_back(self, examples):
        data = []
        for snapshot, prior, finish, back in examples:
            info = ordered.frame(snapshot)
            cars = info[0][0]
            if sorted(finish) != cars or back not in cars:
                raise ValueError('Observed history must match the complete lineup.')
            data.append((info, prior, [cars.index(car) for car in finish[:3]], cars.index(back)))
        matrix, availability = padded_features(data, lambda row:phase_features(row[0], row[1]))
        back_choice = regularized_offset(np.zeros(matrix.shape[:2]), matrix, availability,
                                         np.array([row[3] for row in data]), scale=.5)
        target = np.array([row[2] for row in data])
        rank_weights = []
        for stage in range(3):
            def prefix(row):
                return tuple(np.array([p]) for p in row[2][:stage])

            def context(row):
                roles, groups = roles_and_groups(row[0])
                return finish_design(groups, roles, np.array([row[3]]), prefix(row))[0, 0]

            matrix, _ = padded_features(data, context)
            baseline = np.zeros(matrix.shape[:2])
            for index, row in enumerate(data):
                logits = self.model.logits(row[0], prefix(row))[0]
                baseline[index, :len(logits)] = logits
            rank_weights.append(regularized_offset(baseline, matrix, availability, target[:, stage]))
            availability[np.arange(len(data)), target[:, stage]] = False
        return {'fit_races': len(data), 'back': back_choice, 'finish_by_back': rank_weights}

    def fit_home(self, examples, config):
        data = []
        for snapshot, prior, home, back in examples:
            info = ordered.frame(snapshot)
            cars = info[0][0]
            data.append((info, prior, cars.index(home), cars.index(back)))
        if not data:
            return {'fit_races': 0}
        matrix, available = padded_features(data, lambda row:phase_features(row[0], row[1]))
        baseline = matrix @ np.asarray(config['back'])
        home = regularized_offset(baseline, matrix, available, np.array([row[2] for row in data]), scale=4)
        transfer, _ = padded_features(data, lambda row:transfer_design(row[0][0][-3], np.array([row[2]]))[0])
        shift = regularized_offset(baseline, transfer, available, np.array([row[3] for row in data]), scale=4)
        return {'fit_races': len(data), 'home_delta': home, 'transfer': shift}

    def distributions(self, snapshot, history, config, *, home_config):
        info = ordered.frame(snapshot)
        cars = info[0][0]
        roles, groups = roles_and_groups(info)
        count = len(cars)
        riders = np.arange(count)
        head, second = np.where(riders[:, None] != riders)

        def choice(prefix):
            ordinary = self.model.logits(info, prefix)
            adjusted = ordinary + finish_design(groups, roles, riders, prefix) @ config['finish_by_back'][len(prefix)]
            for positions in prefix:
                adjusted[:, np.arange(len(positions)), positions] = -np.inf
            return softmax(adjusted, axis=-1)

        over_back = choice(())[:, 0, head] * choice((riders,))[:, head, second]
        given_back = (over_back[..., None] * choice((head, second))).reshape(count, -1)
        columns = phase_features(info, history)
        logits = columns @ config['back']
        back = softmax(logits)
        results = {'saved': unconditional(info, self.model), 'back': back @ given_back}
        if home_config.get('fit_races'):
            home = softmax(logits + columns @ home_config['home_delta'])
            transferred = marginal_back(home, back_given_home(logits, groups, home_config['transfer']))
            results['home_back'] = transferred @ given_back
        else:
            transferred = back
        for masses in results.values():
            if not np.isclose(masses.sum(), 1, rtol=0, atol=1e-10):
                raise ValueError('Legal finish probabilities must add up to one.')
        return cars, head, second, results, back, transferred
