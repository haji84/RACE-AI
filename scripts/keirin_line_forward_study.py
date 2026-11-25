"""Freeze the saved KEIRIN line ranker alongside current A/B and score both."""

import argparse
from base64 import b64decode
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from secrets import token_hex

from race_ai import keirin_secondary_result_consensus as consensus
from scripts import keirin_generate_result_unread_analysis as ingest
from scripts import keirin_rider_context_study as ledger


FRAME_SCHEMA = 'KEIRIN_LINE_RANKER_PROSPECTIVE_V1'
COMMITMENT_SCHEMA = 'KEIRIN_LINE_RANKER_PUBLIC_COMMITMENT_V1'
METHODS = ('current_A', 'current_B', 'published_line')
CAPS = {'2t': (1, 2, 4), '3t': (1, 4, 8)}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = 'docs/evidence/keirin-all-rider-profiles-20261124/prefecture-normalized/weights.json'
LOCKED_FILES = (
    WEIGHTS, 'race_ai/keirin_nationwide_auto_generator.py',
    'scripts/keirin_generate_result_unread_analysis.py',
    'scripts/keirin_rider_profile_study.py', 'scripts/keirin_line_history_study.py',
    'scripts/keirin_small_ticket_study.py', 'scripts/keirin_line_forward_study.py',
)


def freeze(path):
    from race_ai import keirin_nationwide_auto_generator as core
    from scripts import keirin_rider_profile_study as model

    raw = path.read_bytes()
    document = json.loads(raw)
    day = date.fromisoformat(document['date']).isoformat()
    now = datetime.now(timezone.utc)
    ingest.need(document['date'] == day == now.astimezone(ingest.JST).date().isoformat(),
                'PROSPECTIVE_CAPTURE_DAY_MISMATCH')
    ingest.need(re.fullmatch(r'[0-9a-f]{64}', document['source_inventory_sha256']),
                'SOURCE_INVENTORY_DIGEST_REQUIRED')
    intake = document['races']
    unique = {row['race_id'] for row in intake}
    ingest.need(len(unique) == len(intake) <= document['target_count'], 'PROSPECTIVE_RACE_COUNT_MISMATCH')
    ingest.DAY = day
    coefficients = json.loads((REPOSITORY_ROOT / WEIGHTS).read_bytes())
    ingest.need(coefficients['selected'] == 'published_line' and model.CAPS == CAPS,
                'SAVED_COMPARISON_SETTING_MISMATCH')
    locked = {file: sha256((REPOSITORY_ROOT / file).read_bytes()).hexdigest() for file in LOCKED_FILES}
    ingest.need(locked[LOCKED_FILES[1]] == ingest.MODEL_SHA256, 'BASELINE_GENERATOR_MISMATCH')
    races, omissions = [], Counter()
    for row in intake:
        cutoff = ingest.published_cutoff(day, row['deadline_time'])
        if cutoff is None or cutoff <= now:
            omissions['no_future_published_cutoff'] += 1
            continue
        ledger.check_source_receipts(row, now)
        current = ingest.analyze(row, core, now.isoformat())
        if current['analysis_lines'] is None:
            omissions['published_line_missing'] += 1
            continue
        riders = current['normalized_riders']
        card = {'race_id': row['race_id'], 'riders': riders, 'line_groups': current['analysis_lines']}
        learned = model.predict(card, coefficients['coefficients'], modes=('published_line',))
        ranks = {f'current_{arm}': {
            market: current[arm]['candidate_tickets'][market][:caps[-1]]
            for market, caps in CAPS.items()
        } for arm in ('A', 'B')}
        ranks['published_line'] = learned['published_line']
        races.append(dict(race_id=row['race_id'], venue=row['venue'], race_no=row['race_no'],
                          cutoff_at=cutoff.isoformat(), starters=[rider['car'] for rider in riders],
                          source_as_of=current['source_as_of'], input_sha256=current['input_sha256'], ranks=ranks))
    sealed = datetime.now(timezone.utc)
    eligible = [row for row in races if sealed < ingest.instant(row['cutoff_at'])]
    omissions['expired_during_generation'] += len(races) - len(eligible)
    ingest.need(bool(eligible), 'NO_PRE_CUTOFF_RACES')
    return dict(schema=FRAME_SCHEMA, date=day, sealed_at=sealed.isoformat(), nonce=token_hex(32),
                input_sha256=sha256(raw).hexdigest(), target_count=document['target_count'],
                source_inventory_sha256=document['source_inventory_sha256'], locked_files=locked,
                omissions=dict(omissions), races=eligible)


def commitment(frame):
    deadlines = sorted(row['cutoff_at'] for row in frame['races'])
    return dict(schema=COMMITMENT_SCHEMA, date=frame['date'], sealed_at=frame['sealed_at'],
                methods=list(METHODS), caps={market: list(caps) for market, caps in CAPS.items()},
                primary_metric='3t:8:published_line_vs_current_B',
                source_inventory_sha256=frame['source_inventory_sha256'], locked_files=frame['locked_files'],
                target_count=frame['target_count'], frozen_count=len(deadlines),
                first_cutoff_at=deadlines[0], last_cutoff_at=deadlines[-1], data_sha256=ingest.digest(frame))


def witness(frame, head, run_id):
    ingest.need(re.fullmatch('[0-9a-f]{40}', head) and type(run_id) is int and run_id > 0,
                'PROSPECTIVE_WITNESS_REFERENCE_INVALID')
    path = f'docs/evidence/keirin-line-forward-{frame["date"].replace("-", "")}/forecast-commitment.json'
    remote = ledger.github_json(f'contents/{path}?ref={head}', raw=True)
    ingest.need(remote == commitment(frame), 'GITHUB_COMMITMENT_MISMATCH')
    job = ledger.github_json(f'actions/runs/{run_id}')
    ingest.need(job['repository']['full_name'] == ledger.REPOSITORY and job['repository']['id'] == 1416489937
                and job['head_sha'] == head and job['event'] == 'pull_request' and job['path'] == ledger.WORKFLOW
                and job['conclusion'] == 'success', 'GITHUB_WITNESS_RUN_MISMATCH')
    for file, expected in remote['locked_files'].items():
        # The public blob API provides the bytes used by the same witnessed revision.
        blob = ledger.github_json(f'contents/{file}?ref={head}')
        ingest.need(blob['encoding'] == 'base64' and sha256(b64decode(blob['content'])).hexdigest() == expected,
                    'WITNESSED_MODEL_BYTES_MISMATCH')
    time = ingest.instant(job['created_at'])
    ingest.need(ingest.instant(frame['sealed_at']) <= time, 'WITNESS_PRECEDES_FORECAST_SEAL')
    return job['created_at']


def checked_result(row, bound, checked_at):
    return consensus.checked_published_result(row, bound, checked_at)


def score(frame, outcomes, *, witnessed_at):
    ingest.need(frame['schema'] == FRAME_SCHEMA and outcomes['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1'
                and frame['date'] == outcomes['date'], 'PROSPECTIVE_RESULT_DATE_OR_SCHEMA_MISMATCH')
    observed = ingest.instant(witnessed_at)
    ingest.need(ingest.instant(frame['sealed_at']) <= observed, 'WITNESS_PRECEDES_FORECAST_SEAL')
    checked_at = ingest.instant(outcomes['checked_at'])
    eligible = {row['race_id']: row for row in frame['races'] if observed < ingest.instant(row['cutoff_at'])}
    results = {row['race_id']: row for row in outcomes['races']}
    ingest.need(len(results) == len(outcomes['races']), 'DUPLICATE_RESULT_RACE')
    states = Counter()
    metrics = {market: {str(cap): dict(points_per_method=0, short_of_cap=0,
                                       hits=dict.fromkeys(METHODS, 0), new_hits_vs_B=0, lost_hits_vs_B=0)
                        for cap in caps} for market, caps in CAPS.items()}
    for key, race in eligible.items():
        label = results.get(key)
        if label is None or label['state'] != 'matched':
            states[label['state'] if label else 'missing'] += 1
            continue
        state, winners = checked_result(label, race, checked_at)
        states[state] += 1
        if winners is None:
            continue
        for market, caps in CAPS.items():
            ranked = {method: race['ranks'][method][market] for method in METHODS}
            for cap in caps:
                budget = min(cap, *(len(orders) for orders in ranked.values()))
                got = {method: winners[market] in orders[:budget] for method, orders in ranked.items()}
                report = metrics[market][str(cap)]
                report['points_per_method'] += budget
                report['short_of_cap'] += budget < cap
                for method in METHODS:
                    report['hits'][method] += got[method]
                report['new_hits_vs_B'] += got['published_line'] and not got['current_B']
                report['lost_hits_vs_B'] += got['current_B'] and not got['published_line']
    return dict(date=frame['date'], target_count=frame['target_count'], eligible=len(eligible),
                matched=states['matched'], witness_at_or_after_cutoff=len(frame['races']) - len(eligible),
                result_states=dict(states), checked_at=outcomes['checked_at'], metrics=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    seal = commands.add_parser('freeze')
    seal.add_argument('--input', type=Path, required=True)
    seal.add_argument('--private-output', type=Path, required=True)
    seal.add_argument('--commitment', type=Path, required=True)
    for name in ('verify', 'score'):
        verify = commands.add_parser(name)
        verify.add_argument('--private-input', type=Path, required=True)
        verify.add_argument('--head', required=True)
        verify.add_argument('--run', type=int, required=True)
        if name == 'score':
            verify.add_argument('--result-packet', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        frame = freeze(args.input)
        proof = commitment(frame)
        ledger.save(args.private_output, frame, private=True)
        ledger.save(args.commitment, proof)
        print(json.dumps(proof))
        return
    frame = json.loads(args.private_input.read_bytes())
    at = witness(frame, args.head, args.run)
    before_cutoff = sum(ingest.instant(at) < ingest.instant(row['cutoff_at']) for row in frame['races'])
    if args.command == 'verify':
        print(json.dumps(dict(witnessed_at=at, before_cutoff=before_cutoff, target_count=frame['target_count'])))
        return
    if args.result_packet:
        raw_packet = args.result_packet.read_bytes()
        packet = json.loads(raw_packet)
        label_reference = sha256(raw_packet).hexdigest()
    else:
        label_reference = ledger.github_json('git/ref/heads/state/keirin-public-results')['object']['sha']
        packet = ledger.github_json(f'contents/results/{frame["date"]}.json?ref={label_reference}', raw=True)
    result = score(frame, packet, witnessed_at=at)
    print(json.dumps(dict(result, witness_head=args.head, witness_run=args.run, witnessed_at=at,
                          result_reference=label_reference)))


if __name__ == '__main__':
    main()
