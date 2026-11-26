"""Aggregate already authenticated, paired race observations without publishing picks."""
from collections import defaultdict
from dataclasses import dataclass
from math import fsum, log, log1p, sqrt
from statistics import NormalDist

STAKE_YEN = 100
LOG_FLOOR = 1e-15
ARMS = ('published', 'trial')
PRIMARY = ('trifecta_top4', 'exacta_top2')
MILESTONES = (100, 500, 1000)


@dataclass(frozen=True)
class MarketObservation:
    """One race in cutoff order, with equal points and optional observed payouts."""

    cutoff: str
    race_id: str
    points: int
    hits: tuple[bool, bool]
    probabilities: tuple[float | None, float | None] = (None, None)
    virtual_payouts_yen: tuple[int, int] | None = None


def _wilson(wins, count, z):
    if not count:
        return None
    rate = wins / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    span = z * sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    return [max(0., center - span), min(1., center + span)]


def _difference_ci(gained, lost, count):
    # A pair contributes +1, 0 or -1. Use the simultaneous 97.5% Wilson
    # intervals of its two discordant outcomes (Bonferroni, nominal 95%).
    z = NormalDist().inv_cdf(0.9875)
    gain = _wilson(gained, count, z)
    loss = _wilson(lost, count, z)
    return [gain[0] - loss[1], gain[1] - loss[0]] if count else None


def binary_score(probability, hit):
    clipped = min(1. - LOG_FLOOR, max(LOG_FLOOR, probability))
    return (probability - hit) ** 2, -(log(clipped) if hit else log1p(-clipped))


def average_scores(errors):
    return dict(count=len(errors),
                brier=fsum(error[0] for error in errors) / len(errors) if errors else None,
                log_loss=fsum(error[1] for error in errors) / len(errors) if errors else None)


def distribution(record, market):
    return {tuple(row['order']): row['probability'] for row in record[market]}


def top3_sets(trifectas):
    probabilities = defaultdict(list)
    for order, probability in trifectas.items():
        probabilities[tuple(sorted(order))].append(probability)
    return {group: fsum(parts) for group, parts in probabilities.items()}


def distribution_score(values, target):
    return (fsum((probability - (order == target)) ** 2 for order, probability in values.items()),
            -log(max(LOG_FLOOR, values[target])))


def observe_market(race_id, cutoff, points, distributions, winner, payout):
    if any(len(values) < points for values in distributions):
        return None
    chosen = [sorted(values, key=lambda order: (-values[order], order))[:points]
              for values in distributions]
    hits = tuple(winner in orders for orders in chosen)
    probabilities = tuple(min(1., fsum(values[order] for order in orders))
                          for values, orders in zip(distributions, chosen, strict=True))
    return MarketObservation(cutoff.isoformat(), race_id, points, hits, probabilities,
                             tuple(payout * hit for hit in hits) if payout is not None else None)


def _calibration(rows, side, market):
    thresholds = {'trifecta_top4': (.70, .50, .30), 'exacta_top2': (.80, .60, .40)}
    thresholds = thresholds.get(market)
    blocks = defaultdict(list)
    confidence_bands = defaultdict(list)
    values = [(row.probabilities[side], row.hits[side]) for row in rows
              if None not in row.probabilities]
    for p, hit in values:
        blocks[min(int(p * 10), 9)].append((p, hit))
        if thresholds:
            band = ('very_high', 'high', 'medium', 'low')[sum(p < bound for bound in thresholds)]
            confidence_bands[band].append((p, hit))

    def bucket(observations):
        count = len(observations)
        hits = sum(hit for _, hit in observations)
        return dict(count=count, hits=hits, mean_probability=fsum(p for p, _ in observations) / count,
                    observed_rate=hits / count, coverage=count / len(rows),
                    rate_ci95=_wilson(hits, count, NormalDist().inv_cdf(.975)))

    return dict(**average_scores([binary_score(p, hit) for p, hit in values]),
                state='UNVALIDATED' if values else 'NO_PAIRED_PROBABILITIES',
                unavailable_pairs=len(rows) - len(values),
                bins=[dict(lower=idx / 10, upper=(idx + 1) / 10, **bucket(blocks[idx]))
                      for idx in sorted(blocks)],
                confidence_band_thresholds=thresholds,
                confidence_bands={band: bucket(samples) for band, samples in confidence_bands.items()},
                trusted_confidence_labels=[])


def _return(rows, side):
    stake = payout = balance = peak = drawdown = 0
    # Net changes at the same cutoff are simultaneous. Do not invent an order.
    changes = defaultdict(int)
    for row in rows:
        amount = row.virtual_payouts_yen[side]
        invest = STAKE_YEN * row.points
        stake += invest
        payout += amount
        changes[row.cutoff] += amount - invest
    for cutoff in sorted(changes):
        balance += changes[cutoff]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    return dict(stake_yen=stake, payout_yen=payout, net_yen=balance, max_drawdown_yen=drawdown if stake else None,
                return_rate=payout / stake if stake else None)


def summarize_market(rows, market, *, detail=True):
    """Same-race prediction, probability and virtual-return coverage."""
    count = len(rows)
    gained = sum(row.hits == (False, True) for row in rows)
    lost = sum(row.hits == (True, False) for row in rows)
    summary = dict(paired_races=count, gained=gained, lost=lost,
                   paired_difference=(gained - lost) / count if count else None,
                   paired_difference_ci95=_difference_ci(gained, lost, count))
    for side, arm in enumerate(ARMS):
        hits = sum(row.hits[side] for row in rows)
        summary[arm] = dict(hits=hits, rate=hits / count if count else None,
                            rate_ci95=_wilson(hits, count, NormalDist().inv_cdf(0.975)))
        if detail:
            summary[arm]['calibration'] = _calibration(rows, side, market)
    if not detail:
        return summary
    paid = [row for row in rows if row.virtual_payouts_yen is not None]
    summary['virtual_returns'] = dict(
        unit_yen=STAKE_YEN, paired_races=len(paid), unavailable_payout_or_refund_pairs=count - len(paid),
        drawdown_order='CUTOFF_TIME_SIMULTANEOUS_NETTED',
        **{arm: _return(paid, side) for side, arm in enumerate(ARMS)})
    return summary
