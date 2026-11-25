"""Score same-budget, frozen trifecta lists against one public daily result snapshot.

Run with python -m scripts.keirin_forward_score. The receipt supplies the original
forecast freeze time. Verifying external time evidence and a later normalization's
mapping to the original predictions is the caller's responsibility.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from race_ai import keirin_secondary_result_consensus as consensus
from scripts.keirin_generate_result_unread_analysis import check_tickets, instant, need
from scripts.keirin_public_site_results import validate_roster


def unique_races(document):
    rows = document['races']
    need(isinstance(rows, list), 'RACE_LIST_REQUIRED')
    indexed = {row['race_id']: row for row in rows}
    need(len(indexed) == len(rows), 'DUPLICATE_RACE_ID')
    return indexed


def confirmed_order(row, cutoff, starters, checked_at):
    bound = dict(race_id=row['race_id'], cutoff_at=cutoff, starters=starters)
    state, winners = consensus.checked_published_result(row, bound, checked_at)
    need(state == 'matched', 'INVALID_MATCHED_RESULT_' + state.upper())
    comparison = row['comparison']
    need(all(type(car) is int for car in comparison['winning_2t']), 'INVALID_EXACTA_RESULT')
    sources = comparison['sources']
    need(len(sources) == 2 and {s['source_id'] for s in sources} == {'kdreams', 'netkeirin'},
         'DISTINCT_RESULT_SOURCES_REQUIRED')
    observed = instant(comparison['observed_at'])
    for source in sources:
        provider = 'Kdreams' if source['source_id'] == 'kdreams' else 'netkeirin'
        consensus.check_race_url(provider=provider, url=source['url'], race_id=row['race_id'])
        need(instant(cutoff) <= instant(source['checked_at']) <= observed, 'INVALID_SOURCE_TIME')
    payouts = comparison['payouts_100yen']
    need(all(type(payouts[m]) is int and 100 <= payouts[m] <= 10**9 for m in ('2t', '3t')),
         'INVALID_PUBLISHED_PAYOUT')
    return winners['3t']


def score(predictions_raw, receipt_raw, roster_raw, results_raw, *, flow_observations_raw=None):
    """Return aggregates and gain/loss IDs for settled races, without disclosing lists."""
    receipt = json.loads(receipt_raw)
    need(receipt['schema'] == 'KEIRIN_FORWARD_RECEIPT_V1', 'INVALID_RECEIPT_SCHEMA')
    forecast_sha = sha256(predictions_raw).hexdigest()
    need(forecast_sha == receipt['prediction_sha256'], 'PREDICTION_DIGEST_MISMATCH')
    frozen = instant(receipt['frozen_at'])
    if 'normalized_at' in receipt:
        need(instant(receipt['normalized_at']) >= frozen, 'NORMALIZATION_PRECEDES_FREEZE')
    names = receipt.get('comparators', {'published': 'published', 'trial': 'trial'})
    need(set(names) == {'published', 'trial'} and all(isinstance(n, str) and n for n in names.values()),
         'INVALID_COMPARATOR_NAMES')

    predictions, roster, results = map(json.loads, (predictions_raw, roster_raw, results_raw))
    need(predictions['schema'] == 'KEIRIN_FORWARD_PREDICTIONS_V1' and
         results['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1' and results['date'] == roster['date'],
         'INVALID_FORECAST_OR_RESULT_SCHEMA_OR_DATE')
    validate_roster(roster, consensus)
    forecasts, entries, outcomes = map(unique_races, (predictions, roster, results))
    need(forecasts.keys() <= entries.keys() and outcomes.keys() <= entries.keys(), 'UNLISTED_RACE')
    checked_at = instant(results['checked_at'])
    states = Counter()
    published_hits = trial_hits = points = 0
    gained, lost = [], []
    orders_by_race, starters_by_race = {}, {}
    for key, forecast in sorted(forecasts.items()):
        entry = entries[key]
        cutoff = entry['published_cutoff_at']
        need(instant(forecast['cutoff_at']) == instant(cutoff), 'PUBLISHED_CUTOFF_MISMATCH')
        need(frozen < instant(cutoff), 'FORECAST_AT_OR_AFTER_CUTOFF')
        starters = {rider['number'] for rider in entry['observed_riders']}
        starters_by_race[key] = starters
        orders_by_race[key] = None
        budget = forecast['points']
        need(type(budget) is int and 1 <= budget <= 8, 'INVALID_TICKET_BUDGET')
        for side in ('published', 'trial'):
            tickets = forecast[side]
            check_tickets(tickets, starters, 3)
            need(all(type(car) is int for ticket in tickets for car in ticket), 'INVALID_CAR_NUMBER')
            need(len(tickets) >= budget, 'FEWER_TICKETS_THAN_DECLARED')
        outcome = outcomes.get(key)
        state = 'missing'
        if outcome is not None:
            state = outcome['state']
            need(state in ('matched', 'held', 'pending'), 'UNKNOWN_RESULT_STATE')
        states[state] += 1
        if state != 'matched':
            continue
        winner = confirmed_order(outcome, cutoff, starters, checked_at)
        published_hit = winner in forecast['published'][:budget]
        trial_hit = winner in forecast['trial'][:budget]
        orders_by_race[key] = winner
        published_hits += published_hit
        trial_hits += trial_hit
        points += budget
        if trial_hit and not published_hit:
            gained.append(key)
        if published_hit and not trial_hit:
            lost.append(key)
    report = dict(date=roster['date'], comparators=names, receipt_frozen_at=receipt['frozen_at'],
                receipt_normalized_at=receipt.get('normalized_at'),
                receipt_timestamp_semantics=receipt.get('timestamp_semantics'), checked_at=results['checked_at'],
                prediction_sha256=forecast_sha, receipt_sha256=sha256(receipt_raw).hexdigest(),
                roster_sha256=sha256(roster_raw).hexdigest(), results_sha256=sha256(results_raw).hexdigest(),
                registered=len(forecasts), matched=states['matched'], result_states=dict(states),
                tickets_per_arm=points, published_hits=published_hits, trial_hits=trial_hits,
                gained=gained, lost=lost)
    if flow_observations_raw is not None:
        from race_ai.keirin_flow_evaluation import summarize_flow
        report['flow_evaluation'] = summarize_flow(
            predictions, json.loads(flow_observations_raw), forecast_sha256=forecast_sha,
            receipt=receipt, orders_by_race=orders_by_race, starters_by_race=starters_by_race)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('predictions', 'receipt', 'roster', 'results'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--flow-observations', type=Path,
                        help='Separately stored observations bound to the original prediction SHA.')
    args = parser.parse_args()
    try:
        report = score(*(path.read_bytes() for path in (args.predictions, args.receipt, args.roster, args.results)),
                       flow_observations_raw=args.flow_observations.read_bytes() if args.flow_observations else None)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f'Forward score failed: {error}\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
