"""Freeze same-input A/B pairs before the cutoff and score read-back results."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from secrets import token_hex
import subprocess
import sys

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from race_ai import keirin_rider_context as context
from scripts import keirin_generate_result_unread_analysis as ingest


FROZEN_SCHEMA = 'KEIRIN_RIDER_CONTEXT_PROSPECTIVE_V1'
RECEIPT_SCHEMA = 'KEIRIN_RIDER_CONTEXT_PUBLIC_COMMITMENT_V1'
WINDOWS = {'2t':4, '3t':4}
REPOSITORY = 'haji84/RACE-AI'
WORKFLOW = '.github/workflows/keirin-persistent-core-ci.yml'


def market_lists(output):
    return {arm:{market:dict(candidates=output[arm].get('candidate_tickets', {}).get(market, []),
                            selected=output[arm].get('markets', {}).get(market, {}).get('tickets', []))
                 for market in WINDOWS} for arm in ('A','B')}


def check_source_receipts(row, started):
    captures = {(ingest.source_url(row['source_url']),row['source_sha256'],ingest.instant(row['fetched_at']))}
    for source in row.get('supplemental_sources',[]):
        digest = source['source_sha256']
        ingest.need(source['http_status']==200 and re.fullmatch(r'[0-9a-f]{64}',str(digest)),
                    'SUPPLEMENT_RECEIPT_INVALID')
        captures.add((ingest.source_url(source['source_url']),digest,ingest.instant(source.get('captured_at'))))
    ingest.need(all(clock <= started for _,_,clock in captures),'SOURCE_CAPTURE_AFTER_GENERATION')
    captured_urls = {url for url,_,_ in captures}
    for hypothesis in row.get('line_hypotheses') or []:
        ingest.need(hypothesis['source_url'] in captured_urls,'LINE_SOURCE_RECEIPT_UNBOUND')
    for rider in row['riders']:
        for source in (rider.get('field_sources') or {}).values():
            if isinstance(source,str):
                bound = source in captured_urls
            else:
                bound = (source.get('url'),source.get('bytes_sha256'),ingest.instant(source.get('captured_at'))) in captures
            ingest.need(bound,'FIELD_SOURCE_RECEIPT_UNBOUND')


def freeze(path):
    raw = path.read_bytes()
    doc = json.loads(raw)
    day = date.fromisoformat(doc['date']).isoformat()
    ingest.need(day == doc['date'], 'INPUT_DATE_INVALID')
    ingest.DAY = day
    model = ingest.load_model()
    started = datetime.now(timezone.utc)
    pairs = []
    seen = set()
    for row in doc['races']:
        race_id = row['race_id']
        ingest.need(race_id not in seen, 'DUPLICATE_INPUT_RACE')
        seen.add(race_id)
        cutoff = ingest.published_cutoff(day,row.get('deadline_time'))
        if cutoff is None or cutoff <= started:
            continue
        check_source_receipts(row,started)
        current = ingest.analyze(row, model, started.isoformat())
        cutoff = ingest.instant(current['published_cutoff_at'])
        if ingest.instant(current['source_as_of']) >= cutoff:
            continue
        compared = context.compare(dict(race_id=race_id, riders=current['normalized_riders'],
                                        line_groups=current['analysis_lines'], line_warnings=current['line_warnings']))
        ingest.need(all(compared['baseline'][arm] == current[arm] for arm in ('A','B')), 'BASELINE_REPLAY_MISMATCH')
        pairs.append(dict(race_id=race_id, cutoff_at=cutoff.isoformat(), input_sha256=current['input_sha256'],
                          baseline=market_lists(compared['baseline']), candidate=market_lists(compared['candidate']),
                          rider_position_evidence=compared['candidate']['position_evidence'],
                          new_scenario_count=compared['candidate']['new_scenario_count']))
    sealed = datetime.now(timezone.utc)
    pairs = [pair for pair in pairs if sealed < ingest.instant(pair['cutoff_at'])]
    ingest.need(pairs, 'NO_PRE_CUTOFF_PAIRS')
    return dict(schema=FROZEN_SCHEMA, date=day, started_at=started.isoformat(), sealed_at=sealed.isoformat(),
                nonce=token_hex(32), input_sha256=sha256(raw).hexdigest(),
                baseline_source_sha256=ingest.MODEL_SHA256, candidate_method=context.METHOD,
                candidate_source_sha256=sha256(Path(context.__file__).read_bytes()).hexdigest(),
                windows=dict(WINDOWS), pairs=pairs)


def commitment(frame):
    return dict(schema=RECEIPT_SCHEMA, date=frame['date'], sealed_at=frame['sealed_at'],
                candidate_method=frame['candidate_method'],
                candidate_source_sha256=frame['candidate_source_sha256'],
                baseline_source_sha256=frame['baseline_source_sha256'], pair_count=len(frame['pairs']),
                earliest_cutoff_at=min(pair['cutoff_at'] for pair in frame['pairs']),
                latest_cutoff_at=max(pair['cutoff_at'] for pair in frame['pairs']),
                windows=frame['windows'], data_sha256=ingest.digest(frame))


def github_json(route, *, raw=False):
    command = ['gh','api',f'repos/{REPOSITORY}/{route}']
    if raw:
        command += ['-H','Accept: application/vnd.github.raw+json']
    return json.loads(subprocess.check_output(command,timeout=25))


def github_witness(frame, commit, run_id, *, receipt_path=None):
    ingest.need(re.fullmatch(r'[0-9a-f]{40}',commit) and type(run_id) is int and run_id > 0, 'GITHUB_WITNESS_INVALID')
    run = github_json(f'actions/runs/{run_id}')
    repository = run['repository']
    ingest.need(repository['full_name']==REPOSITORY and repository['id']==1416489937 and
                run['event']=='pull_request' and run['path']==WORKFLOW and run['head_sha']==commit,
                'GITHUB_WITNESS_RUN_MISMATCH')
    receipt_path = receipt_path or ('docs/evidence/keirin-rider-context-20261123/'
                                    f'prospective-commitment-{frame["date"].replace("-","")}.json')
    ingest.need(re.fullmatch(r'docs/evidence/keirin-rider-context-[0-9]{8}/prospective-commitment-[0-9]{8}(?:-v[0-9]+)?\.json',
                            receipt_path), 'GITHUB_COMMITMENT_PATH_INVALID')
    proof = github_json(f'contents/{receipt_path}?ref={commit}',raw=True)
    ingest.need(proof==commitment(frame), 'GITHUB_COMMITMENT_MISMATCH')
    return run['created_at']


def score(frame, outcomes, *, witnessed_at):
    ingest.need(frame['schema']==FROZEN_SCHEMA and frame['windows']==WINDOWS, 'FROZEN_FRAME_SCHEMA_INVALID')
    ingest.need(outcomes['schema']=='KEIRIN_PUBLISHED_RESULTS_V1' and outcomes['date']==frame['date'],
                'PUBLIC_RESULT_DATE_OR_SCHEMA_MISMATCH')
    witnessed = ingest.instant(witnessed_at)
    ingest.need(ingest.instant(frame['sealed_at']) <= witnessed, 'FRAME_WITNESS_PRECEDES_SEAL')
    eligible = {row['race_id']:row for row in frame['pairs'] if witnessed < ingest.instant(row['cutoff_at'])}
    metrics = {arm:{market:{version:dict(candidate_hits=0, fixed_window_hits=0, selected_hits=0,
                                         fixed_window_points=0, selected_points=0)
                            for version in ('baseline','candidate')} for market in WINDOWS} for arm in ('A','B')}
    matched = set()
    for row in outcomes['races']:
        pair = eligible.get(row['race_id'])
        if row['state'] != 'matched' or pair is None:
            continue
        cmp = row['comparison']
        ingest.need(cmp['race_id']==row['race_id'] and row['race_id'] not in matched and
                    cmp['authority']=='cross_source_reference' and cmp['comparison_scope']=='POST_CUTOFF_REFERENCE',
                    'PUBLIC_RESULT_BINDING_INVALID')
        if not ingest.instant(pair['cutoff_at']) <= ingest.instant(cmp['observed_at']) <= ingest.instant(outcomes['checked_at']):
            continue
        winners = cmp['winning_3t']
        ingest.need(type(winners) is list and len(winners)==3 and
                    all(type(car) is int and 1 <= car <= 9 for car in winners) and len(set(winners))==3 and
                    cmp['winning_2t']==winners[:2], 'PUBLIC_RESULT_ORDER_INVALID')
        matched.add(row['race_id'])
        for arm in ('A','B'):
            for market, window in WINDOWS.items():
                winning = cmp['winning_'+market]
                budget = min(window, *(len(pair[version][arm][market]['candidates']) for version in ('baseline','candidate')))
                for version in ('baseline','candidate'):
                    picks = pair[version][arm][market]
                    counts = metrics[arm][market][version]
                    fixed = picks['candidates'][:budget]
                    counts['candidate_hits'] += winning in picks['candidates']
                    counts['fixed_window_hits'] += winning in fixed
                    counts['selected_hits'] += winning in picks['selected']
                    counts['fixed_window_points'] += len(fixed)
                    counts['selected_points'] += len(picks['selected'])
    return dict(date=frame['date'], eligible_pairs=len(eligible), compared_pairs=len(matched),
                checked_at=outcomes['checked_at'], windows=dict(WINDOWS), metrics=metrics)


def save(path, value, *, private=False):
    if private:
        ingest.need(path.parent.stat().st_mode & 0o777 == 0o700, 'PRIVATE_OUTPUT_DIRECTORY_REQUIRED')
    fd = os.open(path, os.O_WRONLY | os.O_EXCL | os.O_CREAT, 0o600 if private else 0o644)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('freeze')
    preparation.add_argument('--input', type=Path, required=True)
    preparation.add_argument('--private-output', type=Path, required=True)
    preparation.add_argument('--commitment', type=Path, required=True)
    evaluate = commands.add_parser('score')
    evaluate.add_argument('--private-input', type=Path, required=True)
    evaluate.add_argument('--commitment-head', required=True)
    evaluate.add_argument('--commitment-path', required=True)
    evaluate.add_argument('--ci-run-id', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'freeze':
        frame = freeze(args.input)
        receipt = commitment(frame)
        save(args.private_output, frame, private=True)
        save(args.commitment, receipt)
        print(json.dumps(receipt))
    else:
        frame = json.loads(args.private_input.read_bytes())
        witnessed = github_witness(frame,args.commitment_head,args.ci_run_id,receipt_path=args.commitment_path)
        state = github_json('git/ref/heads/state/keirin-public-results')['object']['sha']
        outcomes = github_json(f'contents/results/{frame["date"]}.json?ref={state}',raw=True)
        print(json.dumps(dict(score(frame,outcomes,witnessed_at=witnessed), result_state_head=state,
                              commitment_head=args.commitment_head, witnessed_at=witnessed)))


if __name__ == '__main__':
    main()
