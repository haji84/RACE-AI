"""Learn which KEIRIN riders finish together at fixed individual probabilities."""

import numpy as np


FEATURES = (
    'same_line', 'leader_then_follower', 'follower_then_leader',
    'opposing_leaders', 'opposing_followers',
    'same_line_win_probability_gap', 'opposing_line_combined_win_probability',
    'opposing_rider_win_probability_gap',
)
PENALTY = .02


def pair_mass(orders, probabilities, size):
    first, second = orders[:, :2].T
    result = np.zeros((len(probabilities), size, size))
    np.add.at(result, (np.arange(len(probabilities))[:, None], first, second), probabilities)
    return result


def pair_features(pairs, groups, positions):
    winning = pairs.sum(axis=2)
    same = groups[:, :, None] == groups[:, None, :]
    leaders = positions == 0
    followers = positions == 1
    gap = np.abs(winning[:, :, None] - winning[:, None, :])
    line_winning = np.einsum('bij,bj->bi', same, winning)
    cross = ~same
    return np.stack((
        same,
        same & leaders[:, :, None] & followers[:, None, :],
        same & followers[:, :, None] & leaders[:, None, :],
        cross & leaders[:, :, None] & leaders[:, None, :],
        cross & followers[:, :, None] & followers[:, None, :],
        same * gap,
        cross * (line_winning[:, :, None] + line_winning[:, None, :]),
        cross * gap,
    ), axis=-1)


def _balance(reference, log_multiplier):
    rows = reference.sum(axis=2)
    columns = reference.sum(axis=1)
    if (np.any(rows <= 0) or np.any(columns <= 0)
            or not np.all(np.isfinite(log_multiplier))):
        raise ValueError('Pair calibration requires positive rider marginals and finite offsets.')
    result = reference * np.exp(log_multiplier)
    for _ in range(500):
        result *= (rows / result.sum(axis=2))[:, :, None]
        result *= (columns / result.sum(axis=1))[:, None, :]
        if np.max(np.abs(result.sum(axis=2) - rows)) < 2e-12:
            return result
    raise ArithmeticError('Pair calibration did not recover both original marginals.')


def adjust_triples(orders, probabilities, reference, features, weights):
    """Adjust the dependence of first and second while keeping the third conditional."""
    adjusted = _balance(reference, features @ weights)
    first, second = orders[:, :2].T
    support = reference[:, first, second]
    multiplier = np.divide(adjusted[:, first, second], support,
                           out=np.ones_like(probabilities), where=support > 0)
    return probabilities * multiplier, adjusted


def _adjusted_feature_gradient(pairs, features, finish):
    weighted = pairs[..., None] * features
    row_features = weighted.sum(axis=2)
    col_features = weighted.sum(axis=1)[:, :-1]
    rows = pairs.sum(axis=2)
    columns = pairs.sum(axis=1)[:, :-1]
    # Set the last column's offset derivative to zero. The other derivatives
    # are fixed by the constraints that every marginal derivative is zero.
    reduced = pairs[:, :, :-1]
    scaled = reduced / columns[:, None, :]
    schur = rows[:, :, None] * np.eye(rows.shape[1]) - scaled @ reduced.transpose(0, 2, 1)
    row_offset = np.linalg.solve(schur, -row_features + scaled @ col_features)
    col_offset = (-col_features - reduced.transpose(0, 2, 1) @ row_offset) / columns[..., None]
    col_offset = np.pad(col_offset, ((0, 0), (0, 1), (0, 0)))
    i = np.arange(len(finish))
    first, second = finish.T
    return features[i, first, second] + row_offset[i, first] + col_offset[i, second]


def loss_and_gradient(weights, batches):
    loss = 0.
    gradient = np.zeros_like(weights)
    samples = 0
    for reference, features, finish in batches:
        calibrated = _balance(reference, features @ weights)
        actual = calibrated[np.arange(len(finish)), finish[:, 0], finish[:, 1]]
        if np.any(actual <= 0):
            raise ValueError('The observed first-two must have support in the original forecast.')
        loss -= np.log(actual).sum()
        gradient -= _adjusted_feature_gradient(calibrated, features, finish).sum(axis=0)
        samples += len(finish)
    if not samples:
        raise ValueError('At least one earlier complete ordered finish is required.')
    return (loss / samples + PENALTY * (weights @ weights),
            gradient / samples + 2 * PENALTY * weights)
