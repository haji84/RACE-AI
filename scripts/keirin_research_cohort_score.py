"""Score an early private baseline and its challengers on one common race cohort.

The manifest identifies each native forecast, its receipt, and the corresponding
local Git commit and docs/evidence path. Omit both roster and results to verify
registration before the public result assets exist. The public roster identifies
starters by their car numbers.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from race_ai.keirin_small_ticket_budget import wilson_lower
from scripts import keirin_forward_score, keirin_research_ledger as ledger
from scripts.keirin_generate_result_unread_analysis import check_tickets, instant, need
from scripts.keirin_line_version_study import write_private

SCHEMA = 'KEIRIN_RESEARCH_COHORT_INPUT_V1'
BASELINE = 'KEIRIN_RESEARCH_INITIAL_FORECAST_V1'
CHALLENGER = 'KEIRIN_RESEARCH_DAILY_HEAD_TO_HEAD_V1'
CAPS = [1, 4, 8]
JST = ZoneInfo('Asia/Tokyo')


def _read_arm(entry, directory, read_commitment, *, baseline=None):
    original_raw, receipt_raw = ((directory / entry[name]).read_bytes() for name in ('original', 'receipt'))
    original, receipt = map(json.loads, (original_raw, receipt_raw))
    initial = baseline is None
    stage = original['schema']
    prior_static_link = not initial and stage == BASELINE
    need(stage == BASELINE or (not initial and stage == CHALLENGER), 'INVALID_NATIVE_COHORT_FORECAST')
    day = original['date']
    need(date.fromisoformat(day).isoformat() == day and receipt['date'] == day, 'COHORT_DATE_MISMATCH')
    protocol = receipt['driver_sha256' if prior_static_link else 'implementation_sha256']
    commit_time, blob = ledger._lookup(entry['git_commit'], entry['git_path'], protocol, read_commitment)
    digest = ledger._digest(original_raw)
    need(receipt_raw == blob and receipt['forecast_sha256'] == digest, 'COHORT_GIT_RECEIPT_MISMATCH')
    freeze = instant(original['frozen_at'])
    witness = instant(commit_time)
    readback = instant(receipt['readback_at' if initial else 'readback'])
    need(instant(receipt['frozen_at']) == freeze <= readback <= witness, 'COHORT_WITNESS_CHRONOLOGY')
    rows = keirin_forward_score.unique_races(original)
    need(rows and len(rows) == receipt['races' if stage == CHALLENGER else 'predictions_frozen'],
         'COHORT_RECEIPT_ROW_COUNT_MISMATCH')
    if initial:
        need(receipt['fixed_point_caps'] == CAPS and receipt['registered_known_races'] == len(rows),
             'COHORT_BASELINE_CAPS_OR_SCOPE_MISMATCH')
        comparisons = ('early_existing_static', 'early_existing_static')
    else:
        caps = receipt['eligible_fixed_points'] if prior_static_link else original['caps']
        link = receipt['base_static_sha256' if prior_static_link else 'original_baseline_sha256']
        need(caps == CAPS and freeze >= baseline['freeze'] and day == baseline['day']
             and link == baseline['digest'], 'COHORT_BASELINE_LINK_MISMATCH')
        names = (dict(published=baseline['method'], trial='existing_phase_h_unavailable')
                 if prior_static_link else original['comparators'])
        need(set(names) == {'published', 'trial'} and all(
            isinstance(n, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', n) for n in names.values()),
            'INVALID_COHORT_COMPARATOR_NAMES')
        comparisons = names['published'], names['trial']
        need(comparisons[0] == baseline['method'] and comparisons[1] != comparisons[0]
             and rows.keys() == baseline['rows'].keys(), 'COHORT_RACE_OR_COMPARATOR_MISMATCH')

    for key, row in rows.items():
        need(re.fullmatch(day.replace('-', '') + r'\d{4}', key) and 1 <= int(key[-2:]) <= 12,
             'INVALID_COHORT_RACE_ID')
        close = instant(row['cutoff_at'])
        need(witness < close and close.astimezone(JST).date().isoformat() == day,
             'COHORT_WITNESS_AT_OR_AFTER_CUTOFF')
        cars = row['starter_cars']
        need(isinstance(cars, list) and 4 <= len(cars) <= 9 and
             all(type(c) is int and 1 <= c <= 9 for c in cars) and len(set(cars)) == len(cars),
             'INVALID_COHORT_STARTERS')
        if stage == BASELINE:
            need(row['eligible_points'] == CAPS and instant(row['source_as_of']) <= freeze
                 and close <= instant(row['official_cutoff_at']), 'COHORT_NATIVE_SOURCE_OR_CAP_MISMATCH')
        if not initial:
            earlier = baseline['rows'][key]
            baseline_tickets = row['prior_static' if prior_static_link else 'published']
            need(set(cars) == set(earlier['starter_cars']) and baseline_tickets == earlier['ranked_3t'],
                 'COHORT_CHALLENGER_BASELINE_ROW_MISMATCH')
        tickets = row['ranked_3t' if stage == BASELINE else 'trial']
        check_tickets(tickets, set(cars), 3)
        need(len(tickets) == max(CAPS) and all(type(c) is int for t in tickets for c in t),
             'INVALID_COHORT_RANKED_TICKETS')

    return dict(method=comparisons[1], day=day, freeze=freeze, witness=witness, digest=digest, rows=rows,
                git_commit=entry['git_commit'], receipt_sha256=ledger._digest(receipt_raw),
                protocol_sha256=protocol, ticket_key='ranked_3t' if stage == BASELINE else 'trial')


def _public_results(roster_raw, results_raw, arm):
    roster, results = map(json.loads, (roster_raw, results_raw))
    keirin_forward_score.validate_roster(roster, keirin_forward_score.consensus)
    need(roster['date'] == arm['day'] == results['date']
         and results['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1', 'PUBLIC_COHORT_DATE_OR_SCHEMA')
    entries, outcomes = (keirin_forward_score.unique_races(x) for x in (roster, results))
    need(outcomes.keys() <= entries.keys() and all(o['state'] in {'matched', 'pending', 'held'}
         for o in outcomes.values()), 'INVALID_PUBLIC_COHORT_RESULTS')
    checked_at = instant(results['checked_at'])
    winners = {}
    for key, row in outcomes.items():
        if row['state'] == 'matched':
            entry = entries[key]
            cars = {rider['number'] for rider in entry['observed_riders']}
            winners[key] = keirin_forward_score.confirmed_order(
                row, entry['published_cutoff_at'], cars, checked_at,
            )
    return entries, outcomes, winners, results['checked_at']


def _compare(registered, settled, baseline, arm, cap):
    earlier = baseline['rows']
    later = arm['rows']
    counts = Counter(dict.fromkeys(('changed_registered', 'changed_scored', 'baseline_hits',
                                    'challenger_hits', 'gained', 'lost'), 0))
    misses = {'baseline': Counter(), 'challenger': Counter()}
    for key in registered:
        old = earlier[key]['ranked_3t'][:cap]
        new = later[key][arm['ticket_key']][:cap]
        changed = {tuple(ticket) for ticket in old} != {tuple(ticket) for ticket in new}
        counts['changed_registered'] += changed
        if key not in settled:
            continue
        counts['changed_scored'] += changed
        winning = settled[key]
        old_hit, new_hit = (winning in picks for picks in (old, new))
        counts['baseline_hits'] += old_hit
        counts['challenger_hits'] += new_hit
        counts['gained'] += new_hit and not old_hit
        counts['lost'] += old_hit and not new_hit
        for name, picks, hit in (('baseline', old, old_hit), ('challenger', new, new_hit)):
            if hit:
                continue
            if any(t[:2] == winning[:2] for t in picks):
                misses[name]['third_missing_for_correct_first_two'] += 1
            elif any(t[0] == winning[0] for t in picks):
                misses[name]['second_missing_for_correct_winner'] += 1
            else:
                misses[name]['winner_missing_in_first_position'] += 1
    n = len(settled)
    target = (95 * n + 99) // 100 if n else None

    def interval(hits):
        if not n:
            return None
        return [round(100 * max(0.0, wilson_lower(hits, n)), 4),
                round(100 * min(1.0, 1 - wilson_lower(n - hits, n)), 4)]

    return dict(counts, scored=n, tickets_per_arm=n * cap,
                baseline_hit_pct=round(100 * counts['baseline_hits'] / n, 4) if n else None,
                challenger_hit_pct=round(100 * counts['challenger_hits'] / n, 4) if n else None,
                baseline_correct_first_two=counts['baseline_hits'] + misses['baseline']['third_missing_for_correct_first_two'],
                challenger_correct_first_two=counts['challenger_hits'] + misses['challenger']['third_missing_for_correct_first_two'],
                baseline_wilson_95_pct=interval(counts['baseline_hits']),
                challenger_wilson_95_pct=interval(counts['challenger_hits']),
                paired_delta_pp=round(100 * (counts['gained'] - counts['lost']) / n, 4) if n else None,
                misses_by_first_failed_position={name: dict(value) for name, value in misses.items()},
                target_95_hits=target, gap_to_95_hits=max(0, target - counts['challenger_hits']) if n else None)


def collect(manifest, directory, read_commitment):
    need(manifest['schema'] == SCHEMA and isinstance(manifest['challengers'], list)
         and bool(manifest['challengers']), 'INVALID_COHORT_MANIFEST')
    baseline = _read_arm(manifest['baseline'], directory, read_commitment)
    challengers = [_read_arm(v, directory, read_commitment, baseline=baseline) for v in manifest['challengers']]
    need(len({arm['method'] for arm in challengers}) == len(challengers), 'DUPLICATE_COHORT_METHOD')
    race_ids = baseline['rows'].keys()
    all_arms = [baseline] + challengers
    latest_witness = max(arm['witness'] for arm in all_arms)
    metadata = [dict(method=arm['method'], git_commit=arm['git_commit'], commit_time=arm['witness'].isoformat(),
                     frozen_at=arm['freeze'].isoformat(),
                     forecast_sha256=arm['digest'], receipt_sha256=arm['receipt_sha256'],
                     protocol_sha256=arm['protocol_sha256']) for arm in all_arms]

    # Check the earliest cutoff in all registered inputs. Every arm must be mature
    # before that cutoff for a chance to appear in the common denominator.
    exclusions = Counter()
    registered = set()
    for key in race_ids:
        cutoff = min(instant(arm['rows'][key]['cutoff_at']) for arm in all_arms)
        if latest_witness >= cutoff:
            exclusions['witness_at_or_after_earliest_registered_cutoff'] += 1
        else:
            registered.add(key)
    report = dict(schema='KEIRIN_RESEARCH_COHORT_COUNTS_V1', date=baseline['day'], original_registered=len(race_ids),
                  witness='local Git commit clock and native forecast digest', commitments=metadata,
                  starter_evidence='car_numbers_only', registered_without_publication=len(registered))
    need(('roster' in manifest) == ('results' in manifest), 'COHORT_REQUIRES_BOTH_PUBLIC_FILES')
    if 'roster' not in manifest:
        return dict(report, status='AWAITING_PUBLIC_ROSTER_AND_RESULTS', exclusions=dict(exclusions))
    roster_raw, results_raw = ((directory / manifest[name]).read_bytes() for name in ('roster', 'results'))
    entries, outcomes, winners, checked_at = _public_results(roster_raw, results_raw, baseline)
    eligible = set()
    for key in sorted(registered):
        row = entries.get(key)
        if row is None:
            exclusions['registered_not_on_public_roster'] += 1
        elif {rider['number'] for rider in row['observed_riders']} != set(baseline['rows'][key]['starter_cars']):
            exclusions['starter_numbers_changed'] += 1
        elif latest_witness >= instant(row['published_cutoff_at']):
            exclusions['witness_at_or_after_public_cutoff'] += 1
        else:
            eligible.add(key)
    settled = {key: winners[key] for key in eligible if key in winners}
    states = Counter(outcomes[key]['state'] if key in outcomes else 'missing' for key in eligible)
    hold_reasons = Counter(outcomes[key].get('reason', 'unspecified') for key in eligible
                           if key in outcomes and outcomes[key]['state'] == 'held')
    return dict(report, status='PUBLIC_RESULTS_CHECKED', public_roster_races=len(entries),
                public_roster_not_registered=len(entries.keys() - race_ids), public_roster_confirmed=len(winners),
                public_confirmed_not_in_comparison=len(winners) - len(settled),
                eligible_common_races=len(eligible), eligible_result_states=dict(states), eligible_hold_reasons=dict(hold_reasons),
                eligible_matched_pct=round(100 * len(settled) / len(eligible), 4) if eligible else None,
                uncertainty='Wilson intervals describe individual race hits on this date',
                exclusions=dict(exclusions), checked_at=checked_at, public_roster_sha256=ledger._digest(roster_raw),
                public_results_sha256=ledger._digest(results_raw),
                comparisons={arm['method']: {cap: _compare(eligible, settled, baseline, arm, cap) for cap in CAPS}
                             for arm in challengers})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-new', type=Path)
    args = parser.parse_args(argv)
    try:
        report = collect(json.loads(args.manifest.read_bytes()), args.manifest.parent,
                         lambda revision, path: ledger._git_read(args.repo, revision, path))
        if args.output_new:
            write_private(args.output_new, report)
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.CalledProcessError) as error:
        code = str(error) if re.fullmatch(r'[A-Z0-9_]+', str(error)) else type(error).__name__
        parser.exit(1, f'Cannot score forecast cohort: {code}\n')


if __name__ == '__main__':
    main()
