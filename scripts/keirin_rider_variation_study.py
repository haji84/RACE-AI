"""Compare finish variation using only earlier racing days."""

from collections import defaultdict, deque

import numpy as np
from scipy.special import expit, logsumexp

from scripts.keirin_pair_structure_study import pair_mass


WIDTH = 7
SHRINK = 12
PENALTY = .02


class PriorFinishVariation:
    """Rider observations with calendar windows and an explicit day boundary."""

    def __init__(self):
        self.day = None
        self.day_results_seen = False
        self.windows = [(days, defaultdict(lambda: np.zeros(5)), deque()) for days in (365, 90)]

    def start_day(self, day):
        if self.day is not None and day <= self.day:
            raise ValueError('Historical days must increase.')
        self.day = day
        self.day_results_seen = False
        for size, totals, history in self.windows:
            cutoff = day - size
            while history and history[0][0] < cutoff:
                _, registration, observation = history.popleft()
                totals[registration] -= observation
                if not totals[registration][0]:
                    del totals[registration]

    def record(self, registration, points, finish):
        if self.day is None:
            raise ValueError('Start a day before recording results.')
        self.day_results_seen = True
        points = np.asarray(points, dtype=float)
        size = len(points)
        if (len(registration) != size or not 3 <= size <= 9 or
                sorted(finish) != list(range(1, size+1))):
            raise ValueError('Expected a complete, untied race and registration list.')
        if np.any(~np.isfinite(points)) or np.any((points < 1) | (points > 150)):
            return False
        expected = (expit((points[:, None]-points[None, :])/8.).sum(axis=1)-.5) / (size-1)
        residual = (size-np.asarray(finish)) / (size-1) - expected
        values = np.column_stack((np.ones(size),residual,residual**2,
                                  np.maximum(residual-.20,0.),np.maximum(-residual-.20,0.)))
        for rider, observation in zip(registration, values, strict=True):
            if rider is None:
                continue
            for _, totals, history in self.windows:
                totals[rider] += observation
                history.append((self.day,rider,observation))
        return True

    def features(self, registration):
        if self.day is None or self.day_results_seen:
            raise ValueError('Query the day before observing any of its results.')
        longer, shorter = (window[1] for window in self.windows)
        rows = np.zeros((len(registration), WIDTH))
        for index, rider in enumerate(registration):
            base = longer.get(rider)
            if base is None:
                continue
            rows[index, :5] = base/(base[0]+SHRINK)
            recent = shorter.get(rider)
            if recent is not None:
                rows[index, 5:] = recent[3:]/(recent[0]+SHRINK) - rows[index, 3:5]
        return rows


def second_features(variation, groups):
    """Use declared line relation only when both riders have confirmed positions."""
    candidates = np.broadcast_to(variation[:, None], (*groups.shape, *variation.shape[1:]))
    known = groups >= 0
    opposing = (known[:, :, None] & known[:, None, :] &
                (groups[:, :, None] != groups[:, None, :]))
    return np.concatenate((candidates,candidates*opposing[..., None]),axis=-1)


def loss_and_gradient(weights,batches):
    total=0.
    gradient=np.zeros_like(weights)
    samples=0
    for base, features, second in batches:
        r=np.arange(len(base))
        logits=base+features@weights
        normalizer=logsumexp(logits,axis=1)
        totals=np.exp(logits-normalizer[:,None])
        total+=(normalizer-logits[r,second]).sum()
        gradient+=np.einsum('rc,rcf->f',totals,features)-features[r,second].sum(axis=0)
        samples+=len(base)
    if not samples:
        raise ValueError('Expected earlier race observations for fitting.')
    return (total/samples+PENALTY*(weights@weights),
            gradient/samples+2*PENALTY*weights)


def adjust_triples(orders,probabilities,pairs,features,weights):
    """Adjust the runner-up conditional on each possible winner."""
    utility=features@weights
    mass=pairs*np.exp(utility-utility.max(axis=2,keepdims=True))
    adjusted=mass*np.divide(pairs.sum(axis=2,keepdims=True),mass.sum(axis=2,keepdims=True),
                            out=np.zeros_like(mass[:,:,:1]),where=mass.sum(axis=2,keepdims=True)>0)
    a,b=orders[:,:2].T
    scale=np.divide(adjusted[:,a,b],pairs[:,a,b],out=np.zeros_like(probabilities),where=pairs[:,a,b]>0)
    return probabilities*scale, adjusted
