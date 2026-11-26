"""Project one archived, independently scored joint cohort to safe public rank artifacts."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import fsum
import os
from pathlib import Path
import subprocess

from race_ai.keirin_public_rank_distribution import checked_day, project_recovered_day
from scripts import keirin_forward_score as forward
from scripts.keirin_generate_result_unread_analysis import instant, need


DAY = '2026-11-25'
ROSTER_URL = ('https://keirin-20261119-race-note.chankuma.chatgpt.site/'
              'data/keirin_20261125_ranked_v3_public.json')
ROSTER_SHA256 = '2a62f3a6cf7f2a12d62b5b49b4d9a620db49309b0522814ed904c11c942e3d35'
ROSTER_LIMIT = 1024 * 1024
EVIDENCE = Path('docs/evidence/keirin-live-accuracy-closure-20261125')
SECRET = 'RACE_AI_KEIRIN_PRIVATE_RSA_PEM'
RUNNER_CONTEXT = {
    'GITHUB_ACTIONS': 'true',
    'GITHUB_REPOSITORY': 'haji84/RACE-AI',
    'GITHUB_REPOSITORY_ID': '1416489937',
    'GITHUB_EVENT_NAME': 'workflow_dispatch',
    'GITHUB_REF': 'refs/heads/main',
    'GITHUB_REF_PROTECTED': 'true',
    'GITHUB_WORKFLOW_REF': 'haji84/RACE-AI/.github/workflows/keirin-joint-original-readback.yml@refs/heads/main',
    'GITHUB_JOB': 'independent-owner-readback',
}


def require_runner(context):
    need(all(context.get(key) == value for key, value in RUNNER_CONTEXT.items()),
         'RANK_EXHIBIT_RUNNER_CONTEXT')


def bounded_read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    need(0 < len(data) <= limit, 'RANK_EXHIBIT_INPUT_LIMIT')
    return data


def named_rosters(raw):
    need(0 < len(raw) <= ROSTER_LIMIT and sha256(raw).hexdigest() == ROSTER_SHA256,
         'RANK_EXHIBIT_PUBLIC_ROSTER_DIGEST')
    doc = json.loads(raw)
    need(doc['schema'] == 'KEIRIN_PUBLISHED_LINE_RANK_V3' and doc['date'] == DAY,
         'RANK_EXHIBIT_PUBLIC_ROSTER_SCHEMA')
    return [dict(race_id=row['race_id'], cutoff_at=row['cutoff_at'],
                 riders=[dict(number=rider['number'], name=rider['name']) for rider in row['riders']])
            for row in forward.unique_races(doc).values()]


def fetch_named_roster(path):
    # Ignore the runner's curl config and require an exact 200 from this URL.
    subprocess_result = subprocess.run(
        ['curl', '-q', '--proto', '=https', '--max-time', '20', '--max-filesize', str(ROSTER_LIMIT),
         '--fail', '--silent', '--show-error', '--write-out', '%{http_code}', '--output', str(path),
         ROSTER_URL], check=True, capture_output=True)
    need(subprocess_result.stdout == b'200', 'RANK_EXHIBIT_PUBLIC_ROSTER_STATUS')
    named_rosters(bounded_read(path, ROSTER_LIMIT))


def validate_rank_cohort(packet, report, roster_raw, results_raw, receipt_raw, publication_raw, witness_raw):
    checked_day(packet)
    need(packet['day'] == report['date'] == DAY and
         report['registered'] == report['matched'] == report['trifecta_by_points']['4']['matched'] ==
         len(packet['races']) == 10, 'RANK_EXHIBIT_INCOMPLETE_COHORT')
    need(report['original_plaintext_authentication'] == 'INDEPENDENT_RSA_READBACK_VERIFIED' and
         report['independent_research_plaintext_readback'] is True and
         report['actual_organizer_cutoff_authenticated'] is False and report['accuracy_improvement_proven'] is False,
         'RANK_EXHIBIT_SCORING_STATE')
    for key, raw in (('roster', roster_raw), ('results', results_raw), ('recovery_receipt', receipt_raw),
                     ('publication_receipt', publication_raw), ('independent_witness', witness_raw)):
        need(report[key + '_sha256'] == sha256(raw).hexdigest(), 'RANK_EXHIBIT_SCORE_INPUT_DIGEST')
    receipt = json.loads(receipt_raw)
    need(report['original_note_sha256'] == receipt['original_note_sha256'], 'RANK_EXHIBIT_SCORE_ORIGINAL_DIGEST')

    roster, results = json.loads(roster_raw), json.loads(results_raw)
    need(roster['schema'] == 'KEIRIN_PUBLIC_RESULT_ROSTER_V1' and
         results['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1' and roster['date'] == results['date'] == DAY,
         'RANK_EXHIBIT_RESULT_SCHEMA')
    entries, outcomes = forward.unique_races(roster), forward.unique_races(results)
    checked_at = instant(results['checked_at'])
    errors = {k: [] for k in (1, 2, 3)}
    for race in packet['races']:
        race_id = race['race_id']
        entry = entries[race_id]
        cutoff = entry['published_cutoff_at']
        starters = {rider['number'] for rider in entry['observed_riders']}
        need(instant(cutoff) == instant(race['cutoff_at']) and
             starters == {rider['number'] for rider in race['riders']} and len(starters) == 7,
             'RANK_EXHIBIT_OFFICIAL_ROSTER_BINDING')
        order = forward.confirmed_order(outcomes[race_id], cutoff, starters, checked_at)
        for k, values in errors.items():
            observed = set(order[:k])
            values.extend((fsum(rider['probabilities'][:k]) - (rider['number'] in observed)) ** 2
                          for rider in race['riders'])
    return dict(schema='RACE_AI_KEIRIN_PUBLIC_RANK_VALIDATION_V1', day=DAY, races=len(packet['races']),
                rider_starts=len(errors[1]), metric='BINARY_BRIER_BY_RANK_THRESHOLD',
                validation_scope='ARCHIVED_PROSPECTIVE_RESEARCH_TWO_SOURCE_TOP3',
                calibration_status='UNVALIDATED', forecast_premise='ALL_FINISH_NO_TIES',
                actual_organizer_cutoff_authenticated=False, accuracy_improvement_proven=False,
                results_sha256=report['results_sha256'], roster_sha256=report['roster_sha256'],
                original_note_sha256=report['original_note_sha256'],
                top_k_brier={str(k): fsum(values) / len(values) for k, values in errors.items()})


def project_artifacts(folder, private_pem):
    receipt, publication, witness = [
        bounded_read(EVIDENCE / name, 128 * 1024) for name in
        ('joint-original-rsa-recovery.json', 'prospective-publication.json', 'independent-runner-readback.json')]
    packet = project_recovered_day(
        bounded_read(folder / 'recovery.sealed.json', 24 * 1024 * 1024), private_pem, receipt, publication, witness,
        named_rosters(bounded_read(folder / 'named-roster.json', ROSTER_LIMIT)),
        published_at=datetime.now(timezone.utc).isoformat())
    metrics = validate_rank_cohort(packet, json.loads(bounded_read(folder / 'score-report.json', 128 * 1024)),
                                  bounded_read(folder / 'roster.json', 12 * 1024 * 1024),
                                  bounded_read(folder / 'results.json', 12 * 1024 * 1024),
                                  receipt, publication, witness)
    for name, value in (('rank-distribution.json', packet), ('rank-validation.json', metrics)):
        with (folder / name).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n')


def main():
    secret = os.environ.pop(SECRET, '')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('fetch-named-roster', 'project'))
    args = parser.parse_args()
    try:
        require_runner(os.environ)
        folder = Path(os.environ['RUNNER_TEMP']) / 'keirin-joint-independent'
        if args.mode == 'fetch-named-roster':
            need(not secret, 'RANK_EXHIBIT_FETCH_REQUIRES_KEYLESS_CONTEXT')
            fetch_named_roster(folder / 'named-roster.json')
        else:
            project_artifacts(folder, secret.encode())
    except Exception:
        raise SystemExit('HOLD_JOINT_RANK_EXHIBIT_' + args.mode.upper().replace('-', '_')) from None


if __name__ == '__main__':
    main()
