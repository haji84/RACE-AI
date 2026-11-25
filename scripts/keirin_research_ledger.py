"""Accumulate count-only keirin research results from locally restored owner files.

The manifest lists one public roster and result snapshot per date, along with
each study's normalized predictions, receipt, original forecast file and a
protocol digest. A trusted local clone supplies the Git commitment. Git commit
time is checked against each cutoff, but it is not an independent GitHub
delivery timestamp. For restored normalized formats, the owner's normalizer is
responsible for the original-to-normalized linkage. For native forecasts pass
git_proof, published and publication paths to verify the conversion here.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from scripts import keirin_forward_score
from scripts.keirin_generate_result_unread_analysis import instant, need
from scripts.keirin_line_version_study import write_private

SCHEMA = 'KEIRIN_RESEARCH_LEDGER_INPUT_V1'
LEGACY_BINDINGS = ('original_git_commit', 'original_git_commit_time', 'original_git_path',
                   'original_git_blob_sha256', 'original_forecast_sha256')
CURRENT_BINDINGS = ('git_commit', 'commit_time', 'git_path',
                    'git_blob_sha256', 'original_prediction_sha256')


def _packed(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()


def _digest(raw):
    return sha256(raw).hexdigest()


def _sha(value, width=64):
    return isinstance(value, str) and re.fullmatch(rf'[0-9a-f]{{{width}}}', value) is not None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for part in value.values():
            yield from _strings(part)
    elif isinstance(value, list):
        for part in value:
            yield from _strings(part)


def _git_read(repo, revision, path):
    commit_at = subprocess.check_output(
        ['git', 'show', '-s', '--format=%cI', revision], cwd=repo, stderr=subprocess.DEVNULL,
    ).decode().strip()
    blob = subprocess.check_output(
        ['git', 'show', f'{revision}:{path}'], cwd=repo, stderr=subprocess.DEVNULL,
    )
    return commit_at, blob


def _lookup(revision, path, protocol, read_commitment):
    need(_sha(protocol) and _sha(revision, 40), 'INVALID_RESEARCH_COMMITMENT_HASH')
    file = PurePosixPath(path)
    need(file.parts[:2] == ('docs', 'evidence') and '..' not in file.parts
         and re.fullmatch(r'[a-zA-Z0-9_/-]+\.json', path) is not None, 'INVALID_COMMITMENT_PATH')
    return read_commitment(revision, path)


def _chronology(plan, receipt, reported_time, commit_time):
    freeze = instant(receipt['frozen_at'])
    committed = instant(commit_time)
    need(freeze <= committed and instant(reported_time) == committed, 'GIT_COMMITMENT_TIME_MISMATCH')
    need(all(committed < instant(r['cutoff_at']) for r in plan['races']), 'GIT_COMMITMENT_AT_OR_AFTER_CUTOFF')


def verify_binding(plan, receipt, original_raw, roster_raw, protocol, read_commitment):
    """Cross-check normalized owner material against the digest in its Git commitment."""
    p = receipt['provenance']
    names = CURRENT_BINDINGS if 'git_commit' in p else LEGACY_BINDINGS
    revision, when, path, blob_hash, original_hash = (p[name] for name in names)
    public_hashes = {p[key] for key in ('pub_sha256', 'public_forecast_sha256', 'published_sha256') if key in p}
    need(len(public_hashes) == 1, 'CONFLICTING_OR_MISSING_PUBLIC_FORECAST_SHA')
    public_hash = public_hashes.pop()
    need(all(_sha(s) for s in (blob_hash, original_hash, public_hash)), 'INVALID_RESEARCH_COMMITMENT_HASH')
    need(p['roster_sha256'] == _digest(roster_raw)
         and json.loads(roster_raw)['forecast_asset_sha256'] == public_hash, 'OWNER_ROSTER_DIGEST_MISMATCH')
    need(_digest(original_raw) == original_hash, 'ORIGINAL_PREDICTION_DIGEST_MISMATCH')

    witnessed, blob = _lookup(revision, path, protocol, read_commitment)
    _chronology(plan, receipt, when, witnessed)
    need(instant(p['original_frozen_at']) == instant(receipt['frozen_at']), 'GIT_COMMITMENT_TIME_MISMATCH')
    need(_digest(blob) == blob_hash, 'GIT_COMMITMENT_BLOB_DIGEST_MISMATCH')
    bound = set(_strings(json.loads(blob)))
    need(original_hash in bound and protocol in bound, 'GIT_COMMITMENT_FORECAST_OR_PROTOCOL_MISSING')
    return revision


def verify_native(plan, receipt, original_raw, roster_raw, protocol, read_commitment, *, proof, published_raw, publication):
    """Validate an unchanged native forecast or its old/new row projection."""
    revision = proof['commit']
    commit_time, blob = _lookup(revision, proof['path'], protocol, read_commitment)
    _chronology(plan, receipt, proof['commit_time'], commit_time)
    committed = json.loads(blob)
    need(instant(committed['frozen_at']) == instant(receipt['frozen_at']), 'GIT_COMMITMENT_TIME_MISMATCH')
    need(_digest(original_raw) == committed.get('prediction_sha256', committed.get('forecast_sha256'))
         and protocol in set(_strings(committed)), 'NATIVE_COMMITMENT_FORECAST_OR_PROTOCOL_MISMATCH')
    anonymous = publication['anonymous_readback']
    roster = json.loads(roster_raw)
    wire_hash = committed.get('published_asset_sha256', committed.get('published_sha256'))
    if wire_hash is None:
        wire_hash = committed.get('coverage', {}).get('published_sha256')
    need(publication['date'] == roster['date'] and publication['result_roster_sha256'] == _digest(roster_raw)
         and anonymous['normalized_sha256'] == roster['forecast_asset_sha256'] == _digest(published_raw)
         and anonymous['wire_sha256'] == wire_hash,
         'NATIVE_PUBLIC_ASSET_DIGEST_MISMATCH')

    original = json.loads(original_raw)
    if original.get('schema') != plan['schema']:
        original = dict(schema=plan['schema'], races=[
            dict(race_id=rid, published=row['old'], trial=row['new'], points=row['points'], cutoff_at=row['cutoff'])
            for rid, row in original.items()
        ])
    original_rows, projected_rows = (keirin_forward_score.unique_races(doc) for doc in (original, plan))
    need(_packed(original_rows) == _packed(projected_rows) and original.keys() == plan.keys(),
         'NATIVE_NORMALIZATION_MISMATCH')
    published = keirin_forward_score.unique_races(json.loads(published_raw))
    for row in plan['races']:
        baseline = published[row['race_id']]
        need(baseline['default_trifecta_points'] == row['points']
             and baseline['predictions']['3t'][:len(row['published'])] == row['published']
             and instant(publication['deployment_time_utc']) < instant(row['cutoff_at']),
             'NATIVE_SITE_COMPARATOR_MISMATCH')
    return revision


def _counts(report, plan, outcomes):
    rows = plan['races']
    scoped = {row['race_id'] for row in rows}
    changed = {
        r['race_id'] for r in rows
        if set(map(tuple, r['published'][:r['points']])) != set(map(tuple, r['trial'][:r['points']]))
    }
    matched = {key for key in scoped if outcomes.get(key, {}).get('state') == 'matched'}
    # Races outside the registered cohort never enter a hit-rate denominator.
    holds = Counter(outcomes[key].get('reason') for key in scoped
                    if outcomes.get(key, {}).get('state') == 'held')
    return Counter(
        registered=report['registered'], matched=report['matched'], held=report['result_states'].get('held', 0),
        pending=report['result_states'].get('pending', 0), missing=report['result_states'].get('missing', 0),
        ticket_points_per_arm=report['tickets_per_arm'], published_hits=report['published_hits'],
        trial_hits=report['trial_hits'], gained=len(report['gained']), lost=len(report['lost']),
        changed_registered=len(changed), changed_matched=len(changed & matched),
        special_result_holds=holds['special_result'], source_disagreement_holds=holds['source_disagreement'],
    )


def _summary(counts):
    n = counts['matched']
    target = (95 * n + 99) // 100 if n else None

    def rate(hits):
        return round(100 * hits / n, 4) if n else None

    return dict(counts, published_hit_pct=rate(counts['published_hits']), trial_hit_pct=rate(counts['trial_hits']),
                paired_delta_pp=rate(counts['gained'] - counts['lost']), target_95_hits_on_matched=target,
                gap_to_95_hits_on_matched=max(0, target - counts['trial_hits']) if n else None)


def collect(manifest, directory, read_commitment):
    need(manifest['schema'] == SCHEMA and isinstance(manifest['days'], list), 'INVALID_RESEARCH_LEDGER_MANIFEST')
    methods, day_rows = defaultdict(dict), {}
    for item in manifest['days']:
        roster_raw, results_raw = ((directory / item[name]).read_bytes() for name in ('roster', 'results'))
        roster, results = map(json.loads, (roster_raw, results_raw))
        date = roster['date']
        need(date not in day_rows, 'DUPLICATE_RESEARCH_DATE')
        need(results['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1' and results['date'] == date, 'PUBLIC_DATE_MISMATCH')
        keirin_forward_score.validate_roster(roster, keirin_forward_score.consensus)
        roster_ids, outcomes = (keirin_forward_score.unique_races(doc) for doc in (roster, results))
        need(outcomes.keys() <= roster_ids.keys(), 'UNLISTED_RACE')
        result_counts = Counter(row['state'] for row in outcomes.values())
        need(result_counts.keys() <= {'matched', 'held', 'pending'}, 'UNKNOWN_RESULT_STATE')
        result_counts['missing'] = len(roster_ids) - len(outcomes)
        checked_at = instant(results['checked_at'])
        for key, outcome in outcomes.items():
            if outcome['state'] == 'matched':
                roster_row = roster_ids[key]
                keirin_forward_score.confirmed_order(
                    outcome, roster_row['published_cutoff_at'],
                    {rider['number'] for rider in roster_row['observed_riders']}, checked_at,
                )
        registered = set()
        used = defaultdict(set)
        for study in item['studies']:
            method, protocol = study['name'], study['protocol_sha256']
            need(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,59}', method) is not None, 'INVALID_STUDY_NAME')
            predictions_raw, receipt_raw, original_raw = (
                (directory / study[name]).read_bytes() for name in ('predictions', 'receipt', 'original')
            )
            plan, receipt = map(json.loads, (predictions_raw, receipt_raw))
            verdict = keirin_forward_score.score(predictions_raw, receipt_raw, roster_raw, results_raw)
            need(bool(plan['races']), 'EMPTY_RESEARCH_STUDY')
            args = plan, receipt, original_raw, roster_raw, protocol, read_commitment
            if 'git_proof' in study:
                revision = verify_native(
                    *args, proof=json.loads((directory / study['git_proof']).read_bytes()),
                    published_raw=(directory / study['published']).read_bytes(),
                    publication=json.loads((directory / study['publication']).read_bytes()),
                )
            else:
                revision = verify_binding(*args)
            keys = {r['race_id'] for r in plan['races']}
            need(not keys & used[method], 'DUPLICATE_STUDY_RACE')
            used[method].update(keys)
            registered.update(keys)
            names = tuple(verdict['comparators'][side] for side in ('published', 'trial'))
            record = methods[method, protocol, names].setdefault(
                date, dict(date=date, commitments=set(), roster_size=len(roster_ids),
                           by_points=defaultdict(Counter), counts=Counter()),
            )
            record['commitments'].add(revision)
            record['counts'].update(_counts(verdict, plan, outcomes))
            for points in sorted({r['points'] for r in plan['races']}):
                limited = dict(plan, races=[r for r in plan['races'] if r['points'] == points])
                raw = _packed(limited)
                projected_receipt = _packed(dict(receipt, prediction_sha256=_digest(raw)))
                projection = keirin_forward_score.score(raw, projected_receipt, roster_raw, results_raw)
                record['by_points'][points].update(_counts(projection, limited, outcomes))
        day_rows[date] = dict(public_roster_races=len(roster_ids), result_states=dict(result_counts),
                              registered_distinct=len(registered), unregistered=len(roster_ids) - len(registered),
                              registered_distinct_matched=sum(
                                  outcomes.get(key, {}).get('state') == 'matched' for key in registered
                              ),
                              checked_at=results['checked_at'], roster_sha256=_digest(roster_raw),
                              public_results_sha256=_digest(results_raw))

    summaries = []
    roster_races = sum(row['public_roster_races'] for row in day_rows.values())
    roster_matched = sum(row['result_states'].get('matched', 0) for row in day_rows.values())
    for (method, protocol, names), daily in sorted(methods.items()):
        records = [row for _, row in sorted(daily.items())]
        by_points, combined = defaultdict(Counter), Counter()
        for record in records:
            combined.update(record['counts'])
            for points, counts in record['by_points'].items():
                by_points[points].update(counts)
        roster_size = sum(d['roster_size'] for d in records)
        summaries.append(dict(
            method=method, protocol_sha256=protocol, comparators=dict(zip(('published', 'trial'), names)),
            roster_races_on_registered_dates=roster_size,
            unregistered_on_those_dates=roster_size - combined['registered'], days=len(records),
            unregistered_in_manifest=roster_races - combined['registered'],
            not_scored_among_matched_roster_races=roster_matched - combined['matched'],
            covers_every_matched_roster_race=bool(roster_matched) and combined['matched'] == roster_matched,
            total=_summary(combined), by_points={points: _summary(c) for points, c in sorted(by_points.items())},
            daily=[dict(record, commitments=sorted(record['commitments']), counts=_summary(record['counts']))
                   for record in records],
        ))
    return dict(
        schema='KEIRIN_RESEARCH_LEDGER_COUNTS_V1', date_count=len(day_rows), dates=dict(sorted(day_rows.items())),
        total_public_roster_races=roster_races, total_matched_roster_races=roster_matched,
        total_distinct_registered_races=sum(row['registered_distinct'] for row in day_rows.values()),
        total_distinct_registered_matched=sum(row['registered_distinct_matched'] for row in day_rows.values()),
        witness='owner-restored normalized forecast and pre-cutoff Git commit clock',
        methods=summaries,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--repo', default=Path(__file__).resolve().parents[1], type=Path)
    parser.add_argument('--output-new', type=Path, help='Create a count-only report without replacing an existing file.')
    args = parser.parse_args(argv)
    try:
        ledger = collect(json.loads(args.manifest.read_bytes()), args.manifest.parent,
                         lambda revision, path: _git_read(args.repo, revision, path))
        if args.output_new:
            write_private(args.output_new, ledger)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, subprocess.CalledProcessError) as error:
        code = str(error) if re.fullmatch(r'[A-Z0-9_]+', str(error)) else type(error).__name__
        parser.exit(1, f'Cannot score research ledger: {code}\n')
    if not args.output_new:
        print(json.dumps(ledger, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
