"""Publish only verified Mac cycle counters to the existing public Git state."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from subprocess import SubprocessError, run

from race_ai import keirin_public_forecasts as public
from race_ai.keirin_nationwide_auto_generator import when
from race_ai.keirin_nationwide_forecast_view import JST

SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_OPERATIONS_V1'
MAX_RECEIPT = 1024 * 1024
STAMP = '%Y%m%dT%H%M%S%f'


def _nonnegative(n):
    return type(n) in (int, float) and 0 <= n < 1000000000


def _receipts(state, audit):
    begin = when(audit['first_tick']).astimezone(timezone.utc).strftime(STAMP)
    end = when(audit['last_tick']).astimezone(timezone.utc).strftime(STAMP)
    rows = []
    for path in sorted((state/'ticks').glob('*.json')):
        if not begin <= path.name.partition('-')[0] <= end:
            continue
        public.need(not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_RECEIPT,
                    'MAC_OPERATIONS_RECEIPT_FILE')
        raw = path.read_bytes()
        row = json.loads(raw)
        stamp = when(row['checked_at']).astimezone(timezone.utc).strftime(STAMP)
        public.need(row['schema'] == 'KEIRIN_MAC_CYCLE_V1' and len(raw) <= MAX_RECEIPT and
                    path.name == f'{stamp}-{sha256(raw).hexdigest()}.json', 'MAC_OPERATIONS_RECEIPT_HASH')
        rows.append(row)
    public.need(len(rows) == audit['completed_ticks'] and
                when(rows[-1]['checked_at']) == when(audit['last_tick']), 'MAC_OPERATIONS_RECEIPTS')
    return rows


def summarize(state, audit):
    public.need(audit['schema'] == 'KEIRIN_MAC_CYCLE_TIMING_V1' and audit['scope'] == 'LOCAL_KEIRIN_RESEARCH' and
                type(audit['completed_ticks']) is int and audit['completed_ticks'] > 0 and
                _nonnegative(audit['seconds_observed']) and _nonnegative(audit['seconds_since_last_completion']) and
                type(audit['full_24h_local_cadence']) is bool, 'MAC_OPERATIONS_TIMING')
    rows = _receipts(state, audit)
    video = rows[-1]['video']
    mode = video.get('model_state')
    latest = when(audit['last_tick'])
    checked_at = when(audit['checked_at'])
    recorded = [row['video'].get('recorded', 0) for row in rows]
    count = video.get('observation_count')
    trial = video.get('trial_sha256')
    previous_trial = rows[-2]['video'].get('trial_sha256') if len(rows) > 1 else None
    checkpoint_same = trial == previous_trial if all(type(value) is str and re.fullmatch('[a-f0-9]{64}',value)
                                                    for value in (trial,previous_trial)) else None
    fits = sum(row['video'].get('model_state') == 'TRIAL_PROFILE_FITTED' for row in rows)
    public.need(latest <= checked_at and all(type(n) is int and n >= 0 for n in recorded) and
                sum(recorded) == audit['new_recordings'] and fits == audit['new_candidate_fits'] and
                (count is None or type(count) is int and count >= 0), 'MAC_OPERATIONS_COUNTERS')
    reason = {'TRIAL_PROFILE_FITTED':'直近の定期処理で試行モデルを再フィットしました。',
              'TRIAL_PROFILE_REUSED':'直近の定期処理は、保存済みの試行モデルを再利用しました。'}.get(
                  mode, '直近の定期処理の学習成果は未確認です。')
    published = dict(state='running' if audit['seconds_since_last_completion'] <= 960 else 'idle',
                     observedAt=latest.isoformat(), completedTicks=len(rows), newRecordings=sum(recorded),
                     observedMinutes=int(audit['seconds_observed'] // 60), reviewedObservations=count,
                     refits=fits, reuses=sum(row['video'].get('model_state') == 'TRIAL_PROFILE_REUSED' for row in rows),
                     checkpointSame=checkpoint_same,
                     trainingUsedInProduction=False if all(row.get('production_weights_promoted') is False for row in rows) else None,
                     full24h=audit['full_24h_local_cadence'], reason=reason)
    return dict(schema=SCHEMA, day=checked_at.astimezone(JST).date().isoformat(),
                published_at=checked_at.isoformat(), mac=published)


def publish(repo, body):
    store = public.PublicForecastGit(repo)
    parent = store.head()
    public.need(parent is not None, 'MAC_OPERATIONS_BRANCH_REQUIRED')
    store.fetch(parent)
    path = f'operations/{body["day"]}.json'
    raw = store.read_previous(parent, path)
    if raw is not None:
        prior = public._json(raw)
        public.need(prior['schema'] == SCHEMA and prior['day'] == body['day'] and
                    when(prior['published_at']) <= when(body['published_at']) and
                    when(prior['mac']['observedAt']) <= when(body['mac']['observedAt']), 'MAC_OPERATIONS_STALE')
        if prior['mac'] == body['mac']:
            return parent, False
    commit, raw = public._commit_projection(store, parent, path, body)
    public._push_projection(store, parent, path, commit, raw)
    return commit, True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--mac-root', type=Path, required=True)
    parser.add_argument('--since', required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        state = args.mac_root/'state'
        since = max(when(args.since), datetime.now(timezone.utc)-timedelta(hours=25))
        timing = run([str(args.mac_root/'venv/bin/python'), '-B', '-m', 'scripts.keirin_mac_cycle',
                      '--state-dir', str(state), '--audit-since', since.isoformat()],
                     cwd=args.mac_root/'runtime', capture_output=True, check=True, timeout=90)
        body = summarize(state, json.loads(timing.stdout))
        commit, updated = publish(args.repo, body)
        print(json.dumps(dict(day=body['day'], observed_at=body['mac']['observedAt'], commit=commit, updated=updated)))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, SubprocessError):
        print(json.dumps({'state': 'HOLD_MAC_OPERATIONS_PUBLICATION'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
