"""Compare direct first-two finish probabilities inside the existing ranker."""

import numpy as np
from scipy.special import softmax

from scripts import keirin_boosted_choice_study as individual


ARMS = {
    'saved': (0, 0., 0),
    'joint_32': (32, 1., 0),
    'joint_72': (72, 1., 0),
    'joint_112': (112, 1., 0),
    'joint_112_half': (112, .5, 0),
    'joint_72_plus_third': (72, 1., 56),
    'joint_112_plus_third': (112, 1., 56),
}


def reference_pairs(head_scores, second_scores):
    n = head_scores.shape[1]
    possible = np.arange(n)
    first, second = np.where(possible[:, None] != possible)
    h = individual.masked_probabilities(head_scores, ())[0]
    s = individual.masked_probabilities(second_scores, (possible,))
    return first, second, h[first] * s[first, second]


def design(context, ranker):
    original, static = context
    cars = original[0][0]
    possible = np.arange(len(cars))
    head_scores = ranker.logits(original, ())
    second_scores = ranker.logits(original, (possible,))
    first, second, reference = reference_pairs(head_scores, second_scores)
    base = np.log(reference)
    consecutive = individual.design(context, (possible,), second_scores)[first, second]
    features = np.column_stack((consecutive, static[first], head_scores[0, first], base)).astype(np.float32)
    return first, second, base, features, reference


def fit(races, saved):
    import lightgbm as lgb

    features, offsets, labels = [], [], []
    for context, placed in races:
        first, second, base, pair, _ = design(context, saved)
        features.append(pair)
        offsets.append(base)
        labels.append((first == placed[0]) & (second == placed[1]))
    widths = np.array([len(v) for v in offsets])
    matrix = np.concatenate(features)
    offset = np.concatenate(offsets)
    train = lgb.Dataset(matrix, label=np.concatenate(labels), init_score=offset)
    started = False

    def objective(raw, dataset):
        nonlocal started
        if not started:
            np.testing.assert_allclose(raw, dataset.get_init_score(), atol=1e-12)
            started = True
        return individual.group_derivatives(raw, dataset.get_label(), widths)

    return lgb.train({
        'objective': objective, 'metric': 'None', 'learning_rate': .04,
        'max_depth': 4, 'num_leaves': 12, 'min_data_in_leaf': 240,
        'lambda_l2': 10., 'feature_fraction': .80, 'max_bin': 63,
        'num_threads': 4, 'verbosity': -1, 'seed': 22491, 'deterministic': True, 'force_col_wise': True,
    }, train, num_boost_round=112)


def rank_batch(keys, contexts, saved, joint, third):
    prepared = [design(context, saved) for context in contexts]
    matrix = np.concatenate([row[3] for row in prepared])
    boundaries = np.r_[0, np.cumsum([len(row[2]) for row in prepared])]
    residual = {iteration:joint.predict(matrix, raw_score=True, num_iteration=iteration, num_threads=4)
                for iteration in (32, 72, 112)}
    follow = individual.batch_stage(contexts, saved, third, 2)
    forecasts = []
    for idx, (key,context) in enumerate(zip(keys, contexts, strict=True)):
        first, second, base, _, reference = prepared[idx]
        start, end = boundaries[idx:idx+2]
        cars = context[0][0][0]
        n = len(cars)
        ranks = {}
        for variant, (trees, strength, thirds) in ARMS.items():
            pair = softmax(base + strength*residual[trees][start:end]) if trees else reference
            product = (pair[:,None] * follow[idx][thirds]).ravel()
            assert np.isclose(product.sum(),1.)
            steps = np.argsort(-product,kind='stable')[:8]
            ranks[variant] = [(cars[first[i//n]],cars[second[i//n]],cars[i%n]) for i in steps]
        forecasts.append((key,ranks))
    return forecasts
