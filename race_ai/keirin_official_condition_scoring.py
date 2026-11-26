"""Score the frozen meeting/round trial after independently authenticated settlement."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import fsum
from random import Random

from . import keirin_dossier_conditions as dossier
from . import keirin_form_fall_blind_pdca as ticket_score
from . import keirin_joint_forecast as joint
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_condition_trial as trial
from . import keirin_paired_measurement as paired

DAY_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CONDITION_TRIAL_DAY_MEASUREMENT_V1'
COHORT_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_CONDITION_TRIAL_COHORT_MEASUREMENT_V1'
MIN_PAIRS = 5600
MIN_DAYS = 60
MAX_DAYS = trial.STUDY_DAYS
BOOTSTRAP_SAMPLES = 4000
BOOTSTRAP_SEED = 20261127
TICKET_BUDGETS = dict(trifecta_top1=('trifectas', 1), trifecta_top4=('trifectas', 4),
                      trifecta_top8=('trifectas', 8), exacta_top2=('exactas', 2), top3_set_top1=('sets', 1))
PROBABILITY_METRICS = ('first_three_order', 'first_two_order', 'rider_full_rank',
                       'rider_top1', 'rider_top2', 'rider_top3')


@dataclass(frozen=True)
class Observation:
    race_id: str
    groups: dict
    markets: dict
    errors: tuple


def _need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_CONDITION_SCORING_' + reason)


def _checked_pair(pair, cutoff, sealed_at, latest_server_evidence_at):
    _need(pair['schema'] == trial.SCHEMA and pair['meeting_grade'] in dossier.GRADES and
          pair['round_stage'] in dossier.ROUND_PATTERNS, 'PAIR_SCOPE')
    baseline, challenger = pair['baseline'], pair['challenger']
    for record, model_id in ((baseline, trial.BASELINE), (challenger, trial.CHALLENGER)):
        joint.validate_forecast(record)
        _need(record['model_id'] == model_id and record['model_version'] == trial.SCHEMA and
              record['scope'] == 'PROSPECTIVE_RESEARCH' and record['race_id'] == pair['race_id'] and
              record['source_packet_sha256'] == pair['historical_packet_sha256'], 'FORECAST_IDENTITY')
    for field in ('cars', 'input_sha256', 'source_packet_sha256', 'generated_at', 'cutoff_at',
                  'source_as_of', 'source_forecast_generated_at'):
        _need(baseline[field] == challenger[field], 'UNEQUAL_PAIR_INPUTS')
    _need(5 <= len(baseline['cars']) <= 9 and
          [(r['car'], r['registration']) for r in baseline['riders']] ==
          [(r['car'], r['registration']) for r in challenger['riders']] and
          all(r['registration'] is not None for r in baseline['riders']), 'UNEQUAL_RIDERS')
    sealed, observed = map(model.when, (sealed_at, latest_server_evidence_at))
    _need(model.when(baseline['cutoff_at']) == cutoff and
          model.when(baseline['generated_at']) <= sealed <= observed <= cutoff - trial.WITNESS_MARGIN,
          'T15_WITNESS')
    _need(type(pair['covered_riders']) is int and 1 <= pair['covered_riders'] <= len(baseline['cars']), 'COVERAGE')
    return baseline, challenger


def _order(official, cars, cutoff):
    _need(official['status'] == 'FINAL_NORMAL' and official['refund_status'] == 'NONE' and
          model.when(official['observed_at']) > cutoff, 'OFFICIAL_SETTLEMENT')
    finishes = official['finishes']
    _need(len(finishes) == len(cars) and {r['car'] for r in finishes} == cars and
          {r['place'] for r in finishes} == set(range(1, len(cars) + 1)) and
          all(type(r['place']) is int and r['status'] in ('FINISHED', 'FALL_FINISHED') for r in finishes),
          'UNSUPPORTED_ALL_FINISH_NO_TIES_PREMISE')
    order = tuple(row['car'] for row in sorted(finishes, key=lambda row: row['place']))
    _need(official['winning_triples'] == [list(order[:3])], 'OFFICIAL_WINNER')
    return order


def observe(pair, official, *, latest_server_evidence_at, sealed_at, competition=None,
            largest_line_size=None, confirmed_exacta_payout=None):
    """Project a privately replayed pair and official result to score observations."""
    rid = pair['race_id']
    _need(official['race_id'] == rid, 'RESULT_RACE_IDENTITY')
    cutoff = model.when(official['official_cutoff_at'])
    records = _checked_pair(pair, cutoff, sealed_at, latest_server_evidence_at)
    cars = set(records[0]['cars'])
    order = _order(official, cars, cutoff)
    trifecta_amount = (ticket_score._result(official, cars, rid)[order[:3]]
                       if official['monetary_comparison_eligible'] is True else None)
    exacta_amount = None
    if confirmed_exacta_payout is not None:
        exacta_order, exacta_amount = confirmed_exacta_payout
        _need(exacta_order == order[:2] and type(exacta_amount) is int and 100 <= exacta_amount <= 10**9,
              'OFFICIAL_EXACTA_PAYOUT')
    law = {market: tuple(paired.distribution(record, market) for record in records)
           for market in ('trifectas', 'exactas')}
    law['sets'] = tuple(paired.top3_sets(outcomes) for outcomes in law['trifectas'])
    bindings = dict(trifectas=(order[:3], trifecta_amount), exactas=(order[:2], exacta_amount),
                    sets=(tuple(sorted(order[:3])), None))
    observations = {label: paired.observe_market(rid, cutoff, points, law[market], *bindings[market])
                    for label, (market, points) in TICKET_BUDGETS.items()}
    errors = []
    actual_places = {car: rank for rank, car in enumerate(order, 1)}
    for side, record in enumerate(records):
        values = dict(first_three_order=[paired.distribution_score(law['trifectas'][side], order[:3])],
                      first_two_order=[paired.distribution_score(law['exactas'][side], order[:2])],
                      rider_full_rank=[], rider_top1=[], rider_top2=[], rider_top3=[])
        for rider in record['riders']:
            probabilities = rider['rank_probabilities']
            actual = actual_places[rider['car']]
            values['rider_full_rank'].append(paired.distribution_score(
                dict(enumerate(probabilities, 1)), actual))
            for rank in (1, 2, 3):
                values[f'rider_top{rank}'].append(paired.binary_score(fsum(probabilities[:rank]), actual <= rank))
        errors.append(values)
    groups = dict(meeting_grade=pair['meeting_grade'], round_stage=pair['round_stage'], field_size=str(len(cars)),
                  venue_code=rid[8:10], feature_coverage='ALL' if pair['covered_riders'] == len(cars) else 'PARTIAL')
    if competition in model.CLASSES:
        groups['competition'] = competition
    if type(largest_line_size) is int and 1 <= largest_line_size <= len(cars):
        groups['largest_line_size'] = str(largest_line_size)
    return Observation(rid, groups, observations, tuple(errors))


def summarize_day(day, rows, *, coverage=None):
    _need(date.fromisoformat(day).isoformat() == day and type(rows) is list and
          len({row.race_id for row in rows}) == len(rows) and
          all(row.race_id.startswith(day.replace('-', '')) for row in rows), 'DAILY_COHORT')
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for axis, category in row.groups.items():
            groups[axis][category].append(row)
    return dict(schema=DAY_SCHEMA, day_jst=day, eligible_paired_races=len(rows),
                result_authority='KEIRIN_JP_OFFICIAL_SP_REPLAY', coverage=dict(coverage or {}),
                premise='ALL_FINISH_NO_TIES', probability_status='UNVALIDATED',
                interval_scope='EXPLORATORY_NOMINAL_WILSON_RACES_UNCLUSTERED',
                markets={name: paired.summarize_market([row.markets[name] for row in rows], name)
                         for name in TICKET_BUDGETS},
                probability_scores={arm: {metric: paired.average_scores(
                    [error for row in rows for error in row.errors[side][metric]]) for metric in PROBABILITY_METRICS}
                    for side, arm in enumerate(paired.ARMS)},
                subgroups={axis: {category: {market: paired.summarize_market(
                    [row.markets[market] for row in category_rows], market, detail=False)
                    for market in paired.PRIMARY} for category, category_rows in sorted(categories.items())}
                    for axis, categories in groups.items()},
                unavailable=['PREREGISTERED_MODEL_ADOPTION_PENDING_COHORT', 'INDEPENDENT_RACE_FLOW', 'PRE_CUTOFF_MARKET_BENCHMARK'])


def _block_interval(blocks):
    if len(blocks) < 2:
        return None
    generator = Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = generator.choices(blocks, k=len(blocks))
        draws.append(sum(value for value, count in sample) / sum(count for value, count in sample))
    draws.sort()
    return [draws[int(.025 * (len(draws) - 1))], draws[int(.975 * (len(draws) - 1))]]


def _summarize_market(market, reports):
    rows = [report['markets'][market] for report in reports if report['markets'][market]['paired_races']]
    blocks = [(row['gained'] - row['lost'], row['paired_races']) for row in rows]
    count = sum(n for _, n in blocks)
    virtual = [row['virtual_returns'] for row in rows if row['virtual_returns']['paired_races']]
    monetary_blocks = [(row['trial']['payout_yen'] - row['published']['payout_yen'], row['trial']['stake_yen'])
                       for row in virtual]
    returns = dict(paired_races=sum(row['paired_races'] for row in virtual), days=len(virtual),
                   day_block_return_rate_difference_ci95=_block_interval(monetary_blocks))
    for arm in paired.ARMS:
        stake = sum(row[arm]['stake_yen'] for row in virtual)
        payout = sum(row[arm]['payout_yen'] for row in virtual)
        returns[arm] = dict(stake_yen=stake, payout_yen=payout, net_yen=payout-stake,
                            return_rate=payout/stake if stake else None)
    return dict(paired_races=count, measured_days=len(blocks),
                published_hits=sum(row['published']['hits'] for row in rows),
                trial_hits=sum(row['trial']['hits'] for row in rows),
                paired_difference=sum(value for value, _ in blocks) / count if count else None,
                day_block_difference_ci95=_block_interval(blocks), virtual_returns=returns)


def summarize_days(reports):
    """Combine one current aggregate per day; adoption still needs subgroup approval."""
    _need(all(report['schema'] == DAY_SCHEMA for report in reports), 'DAILY_SCHEMA')
    days = [date.fromisoformat(report['day_jst']) for report in reports]
    _need(len(days) == len(set(days)) and (not days or (max(days) - min(days)).days < MAX_DAYS), 'DAILY_COHORT')
    reports = sorted(reports, key=lambda report: report['day_jst'])
    count = sum(report['eligible_paired_races'] for report in reports)
    measured_days = sum(report['eligible_paired_races'] > 0 for report in reports)
    primary = {market: _summarize_market(market, reports) for market in paired.PRIMARY}
    _need(all(row['paired_races'] == count for row in primary.values()), 'PRIMARY_COHORT')
    adoption = 'HOLD_MINIMUM_SAMPLE_OR_DAYS'
    if count >= MIN_PAIRS and measured_days >= MIN_DAYS:
        trifecta, exacta = (primary[market] for market in paired.PRIMARY)
        passes = (trifecta['paired_difference'] >= .025 and trifecta['day_block_difference_ci95'][0] > 0 and
                  exacta['day_block_difference_ci95'][0] >= -.01)
        adoption = 'HOLD_SUBGROUP_AND_PROTECTED_REVIEW_REQUIRED' if passes else 'KEEP_CURRENT_MODEL_PRIMARY_GATE'
    return dict(schema=COHORT_SCHEMA, measured_days=measured_days, eligible_paired_races=count,
                first_day=min(days).isoformat() if days else None, last_day=max(days).isoformat() if days else None,
                milestones={str(target): count >= target for target in paired.MILESTONES},
                minimum_paired_races=MIN_PAIRS, minimum_race_days=MIN_DAYS, maximum_calendar_days=MAX_DAYS,
                interval_method='CALENDAR_DAY_PAIRED_BLOCK_BOOTSTRAP_95', primary=primary, adoption_status=adoption)
