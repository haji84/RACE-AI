"""Score an early private baseline and its challengers on one common race cohort.

The manifest identifies each native forecast, its receipt, and the corresponding
local Git commit and docs/evidence path. Omit both roster and results to verify
registration before the public result assets exist. The public roster identifies
starters by their car numbers.

Alternatively use a local owner note result readback and its Git index commit.
Reparse saved official result records to verify the result-side roster and cutoff.
"""
import argparse
from base64 import b64decode
from collections import Counter
from datetime import date
import json
import os
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


def _official_note_context(raw, day):
    from race_ai import keirin_official_public_source as official
    from scripts.keirin_official_day_pipeline import restore_private_snapshot_json

    result = {}
    for key, row in keirin_forward_score.unique_races(json.loads(raw)).items():
        need(key.startswith(day.replace('-', '')), 'NOTE_COHORT_OFFICIAL_DAY_MISMATCH')
        row = restore_private_snapshot_json(row)
        if not official.reparse_race_result(row) or row['state'] != 'OFFICIAL_FINAL':
            continue
        final = row['result']
        if len(final['winning_triples']) != 1:
            continue
        race, _ = official._evidence_race(row['provenance']['schedule_evidence'], key)
        result[key] = dict(cutoff_at=final['official_cutoff_at'],
                           starters={rider['car'] for rider in race['starters']},
                           registrations={str(rider['car']): rider['registration_id'] for rider in race['starters']},
                           winning_triple=final['winning_triples'][0])
    return result


def _archived_sp_context(repo, day, candidates, revision, owner_private_pem):
    """Recheck the latest saved official result for each matched note race."""
    details = dict(index_commit=revision, requested=len(candidates), indexed=0, verified=0, replay_held=0)
    if not candidates:
        return {}, dict(details, state='no_matched_results')
    if not owner_private_pem:
        return {}, dict(details, state='owner_key_unavailable')
    from race_ai import keirin_official_nationwide_records as records
    from scripts.keirin_official_day_pipeline import check_owner_private_key

    try:
        check_owner_private_key(owner_private_pem)
    except (ValueError, TypeError):
        return {}, dict(details, state='owner_key_unverified')
    try:
        store = records.RecordStore(repo, day, index_commit=revision)
    except (OSError, ValueError):
        return {}, dict(details, state='pinned_archive_unavailable')
    actual = {}
    for key in sorted(candidates & store.index['results'].keys()):
        details['indexed'] += 1
        try:
            latest = store.index['results'][key][-1]
            actual[key] = records.replay_saved_result_context(store, store.index['originals'][key], latest,
                                                             owner_private_pem)
        except (ValueError, TypeError, KeyError, OSError, OverflowError):
            details['replay_held'] += 1
    return actual, dict(details, state='pinned_archive_checked', verified=len(actual))


def _read_frozen_identities(directory, entry, read_commitment, day):
    raw = (directory / entry['original']).read_bytes()
    digest = ledger._digest(raw)
    recorded_at, receipt_raw = ledger._lookup(entry['git_commit'], entry['git_path'], digest, read_commitment)
    doc, receipt = json.loads(raw), json.loads(receipt_raw)
    need(doc['schema'] == 'KEIRIN_FROZEN_RIDER_IDENTITIES_V1' and
         receipt['schema'] == 'KEIRIN_FROZEN_RIDER_IDENTITIES_RECEIPT_V1' and
         day == doc['date'] == receipt['date'] and receipt['identity_manifest_sha256'] == digest,
         'FROZEN_RIDER_IDENTITY_RECEIPT_MISMATCH')
    witness = instant(recorded_at)
    rows = keirin_forward_score.unique_races(doc)
    need(len(rows) == receipt['registered_races'] and
         sum(len(row['starter_registrations']) for row in rows.values()) == receipt['starter_appearances'] and
         instant(receipt['assembled_at']) <= witness, 'FROZEN_RIDER_IDENTITY_COHORT_MISMATCH')
    for key, row in rows.items():
        mapping = row['starter_registrations']
        need(re.fullmatch(day.replace('-', '') + r'\d{4}', key) and
             type(mapping) is dict and 4 <= len(mapping) <= 9 and
             all(re.fullmatch(r'[1-9]', car) and type(registration) is str and
                 re.fullmatch(r'\d{6}', registration) for car, registration in mapping.items()) and
             len(set(mapping.values())) == len(mapping) and witness < instant(row['cutoff_at']),
             'FROZEN_RIDER_IDENTITY_ROW_MISMATCH')
    return rows, witness, digest


def _note_result_scope(rows, witnesses, day, raw, index_raw, index_time, official_raw=None, *, read_official_sp=None):
    from race_ai import keirin_note_cohort_results, keirin_note_feed, keirin_note_view

    archive = json.loads(raw)
    index = json.loads(index_raw)
    checks = keirin_note_feed.checked_result_checks(index.get('result_checks', {}))
    daily_checks = {key: row for key, row in checks.items() if key.startswith(day.replace('-', ''))}
    packets = [entry for entry in index['entries'] if entry['kind'] == 'results' and day in entry['days']]
    need(index['schema'] == keirin_note_feed.INDEX and index['repository'] == keirin_note_feed.REPO
         and daily_checks == archive['result_checks'] and len(packets) == len(archive['packets'])
         and instant(index_time) <= instant(archive['checked_at']), 'NOTE_COHORT_INDEX_READBACK_MISMATCH')
    decoded = archive.pop('source_packets')
    need(type(decoded) is list and len(decoded) == len(packets), 'NOTE_COHORT_SOURCE_PROOFS_REQUIRED')
    file_path = f'data/{day}/research_results.json'
    for entry, encoded, delta in zip(packets, decoded, archive['packets'], strict=True):
        need(type(encoded) is str and 0 < len(encoded) <= keirin_note_feed.MAX_WIRE,
             'NOTE_COHORT_SOURCE_PROOF_SIZE')
        plain = b64decode(encoded, validate=True)
        need(len(plain) <= keirin_note_view.MAX_VIEW and ledger._digest(plain) == entry['source_content_sha256'],
             'NOTE_COHORT_SOURCE_PROOF_MISMATCH')
        file = json.loads(plain)['files'][file_path]
        contents = file['text'].encode()
        need(len(contents) == file['bytes'] and ledger._digest(contents) == file['sha256']
             and json.loads(contents) == delta, 'NOTE_COHORT_DECODED_PACKET_MISMATCH')
    official = _official_note_context(official_raw, day) if official_raw is not None else {}
    sp_details = None
    conflicts = set()
    if read_official_sp is not None:
        need(all('starter_registrations' in row for row in rows.values()), 'OFFICIAL_SP_FROZEN_IDENTITIES_REQUIRED')
        candidates = {key for key, check in daily_checks.items() if key in rows and check['status'] == 'MATCHED' and
                      instant(check['checked_at']) >= instant(rows[key]['official_cutoff_at'])}
        sp, sp_details = read_official_sp(day, candidates)
        need(sp.keys() <= candidates, 'OFFICIAL_SP_RESULT_OUTSIDE_MATCHED_COHORT')
        for key, verified in sp.items():
            earlier = official.get(key)
            if earlier is not None and (dict(earlier, cutoff_at=instant(earlier['cutoff_at'])) !=
                                        dict(verified, cutoff_at=instant(verified['cutoff_at']))):
                conflicts.add(key)
                del official[key]
            else:
                official[key] = verified
    cohort = {}
    exclusions = Counter()
    for key, row in sorted(rows.items()):
        proof = official.get(key)
        if proof and proof['starters'] != set(row['starter_cars']):
            exclusions['official_starter_numbers_changed'] += 1
        elif proof and 'starter_registrations' in row and proof['registrations'] != row['starter_registrations']:
            exclusions['official_rider_registrations_changed'] += 1
        elif proof and witnesses[key] >= instant(proof['cutoff_at']):
            exclusions['witness_at_or_after_official_cutoff'] += 1
        else:
            cohort[key] = dict(starter_cars=row['starter_cars'], cutoff_at=row['official_cutoff_at'],
                               result_cutoff_at=proof['cutoff_at'] if proof else None)
    outcomes, winners, checked_at = keirin_note_cohort_results.admit(archive, day=day, registered=cohort)
    for key in conflicts & outcomes.keys():
        if outcomes[key].get('reason') == 'independent_roster_or_cutoff_unverified':
            outcomes[key]['reason'] = 'official_source_context_disagreement'
    for key, order in list(winners.items()):
        if order != official[key]['winning_triple']:
            outcomes[key] = dict(state='held', reason='official_note_order_disagreement')
            del winners[key]
    states = Counter(outcomes.get(key, {}).get('state', 'missing') for key in cohort)
    holds = Counter(row['reason'] for row in outcomes.values() if row['state'] == 'held')
    proof = dict(checked_at=checked_at, note_readback_sha256=ledger._digest(raw), note_index_sha256=ledger._digest(index_raw),
                 official_result_records_sha256=ledger._digest(official_raw) if official_raw is not None else None,
                 note_matched_races=sum(row['status'] == 'MATCHED' for key, row in daily_checks.items() if key in rows),
                 official_roster_verified_races=len(official.keys() & cohort.keys()),
                 eligible_common_races=len(cohort), eligible_result_states=dict(states), eligible_hold_reasons=dict(holds),
                 eligible_matched_pct=round(100 * len(winners) / len(cohort), 4) if cohort else None)
    if sp_details is not None:
        proof['official_sp_replay'] = sp_details
    return cohort.keys(), winners, exclusions, proof


def _note_comparison(manifest, directory, read_commitment, baseline, challengers, registered, exclusions, report,
                     read_official_sp):
    revision = manifest['note_index_commit']
    need(ledger._sha(revision, 40), 'NOTE_COHORT_INDEX_COMMIT')
    index_time, index_raw = read_commitment(revision, 'index.json')
    raw = (directory / manifest['note_results']).read_bytes()
    official_raw = ((directory / manifest['official_result_records']).read_bytes()
                    if 'official_result_records' in manifest else None)
    witness = max(arm['witness'] for arm in [baseline, *challengers])
    rows = {key:baseline['rows'][key] for key in registered}
    if 'frozen_identities' in manifest:
        entry = manifest['frozen_identities']
        identities, identity_witness, digest = _read_frozen_identities(directory, entry, read_commitment, baseline['day'])
        need(rows.keys() <= identities.keys(), 'FROZEN_RIDER_IDENTITY_COHORT_MISMATCH')
        for key, row in rows.items():
            bound = identities[key]
            mapping = bound['starter_registrations']
            need(instant(bound['cutoff_at']) == instant(row['cutoff_at']) and
                 set(map(int, mapping)) == set(row['starter_cars']), 'FROZEN_RIDER_ORIGINAL_MISMATCH')
            rows[key] = dict(row, starter_registrations=mapping)
        witness = max(witness, identity_witness)
        report = dict(report, starter_evidence='official_registration_ids_and_car_numbers',
                      frozen_identity_sha256=digest, frozen_identity_witness=entry['git_commit'])
    sp_reader = None
    if 'official_sp_archive_commit' in manifest:
        sp_revision = manifest['official_sp_archive_commit']
        need(ledger._sha(sp_revision, 40) and callable(read_official_sp), 'COHORT_OFFICIAL_SP_ARCHIVE_READER_REQUIRED')
        sp_reader = lambda day, candidates: read_official_sp(day, candidates, sp_revision)
    cohort, winners, excluded, proof = _note_result_scope(
        rows, dict.fromkeys(registered, witness), baseline['day'], raw, index_raw, index_time, official_raw,
        read_official_sp=sp_reader,
    )
    return dict(report, status='OWNER_NOTE_TRIFECTA_CHECKED', note_index_commit=revision, **proof,
                result_scope='owner-only archived 3T consensus requires a reparsed official result for scoring',
                exclusions=dict(exclusions + excluded), uncertainty='Wilson intervals describe individual race hits on this date',
                comparisons={arm['method']: {cap: _compare(cohort, winners, baseline, arm, cap) for cap in CAPS}
                             for arm in challengers})


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
                target_95_hits_on_matched=target,
                gap_to_95_hits_on_matched=max(0, target - counts['challenger_hits']) if n else None)


def collect(manifest, directory, read_commitment, *, read_official_sp=None):
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
    if 'note_results' in manifest:
        need('roster' not in manifest and 'results' not in manifest, 'COHORT_RESULT_SOURCE_MIXED')
        return _note_comparison(manifest, directory, read_commitment, baseline, challengers, registered, exclusions,
                                report, read_official_sp)
    need(not {'note_index_commit', 'official_result_records', 'frozen_identities', 'official_sp_archive_commit'}.intersection(manifest),
         'COHORT_REQUIRES_NOTE_READBACK')
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
    public_count = len(entries)
    states = Counter(outcomes[key]['state'] if key in outcomes else 'missing' for key in eligible)
    hold_reasons = Counter(outcomes[key].get('reason', 'unspecified') for key in eligible
                           if key in outcomes and outcomes[key]['state'] == 'held')
    return dict(report, status='PUBLIC_RESULTS_CHECKED', public_roster_races=public_count,
                public_roster_not_registered=len(entries.keys() - race_ids), public_roster_confirmed=len(winners),
                public_confirmed_not_in_comparison=len(winners) - len(settled),
                public_roster_scored_pct=round(100 * len(settled) / public_count, 4),
                public_roster_completeness='coverage measured against published roster; nationwide count unverified here',
                eligible_common_races=len(eligible), eligible_result_states=dict(states), eligible_hold_reasons=dict(hold_reasons),
                eligible_matched_pct=round(100 * len(settled) / len(eligible), 4) if eligible else None,
                uncertainty='Wilson intervals describe individual race hits on this date',
                exclusions=dict(exclusions), checked_at=checked_at, public_roster_sha256=ledger._digest(roster_raw),
                public_results_sha256=ledger._digest(results_raw),
                comparisons={arm['method']: {cap: _compare(eligible, settled, baseline, arm, cap) for cap in CAPS}
                             for arm in challengers})


def main(argv=None):
    try:
        owner_private_pem = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    except UnicodeError:
        owner_private_pem = b''
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-new', type=Path)
    args = parser.parse_args(argv)
    try:
        def read_official_sp(day, candidates, revision):
            return _archived_sp_context(args.repo, day, candidates, revision, owner_private_pem)
        report = collect(json.loads(args.manifest.read_bytes()), args.manifest.parent,
                         lambda revision, path: ledger._git_read(args.repo, revision, path),
                         read_official_sp=read_official_sp)
        if args.output_new:
            write_private(args.output_new, report)
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.CalledProcessError) as error:
        code = str(error) if re.fullmatch(r'[A-Z0-9_]+', str(error)) else type(error).__name__
        parser.exit(1, f'Cannot score forecast cohort: {code}\n')


if __name__ == '__main__':
    main()
