"""Publish one validated DT-R1 day to the existing public forecast branch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from race_ai import keirin_public_forecasts as public
from research.chatgpt_dt_r1 import public_shortlists as shortlists
from research.chatgpt_dt_r1.policy import clock


def publish(repo, proposal, *, store=None, now=lambda: datetime.now(timezone.utc)):
    day = shortlists.checked(proposal)['day']
    path = f'dt-r1/{day}.json'
    store = store or public.PublicForecastGit(repo)
    parent = store.head()
    public.need(parent is not None, 'DT_R1_PUBLIC_BRANCH')
    store.fetch(parent)
    previous = store.read_previous(parent, path)
    if previous is not None:
        prior = shortlists.checked(public._json(previous))
        public.need(prior == dict(proposal, published_at=prior['published_at']), 'DT_R1_DAY_ALREADY_PUBLISHED')
        return public._candidates_receipt('DT_R1_PUBLIC_CURRENT', prior, parent)
    store.run(['merge-base', '--is-ancestor', proposal['input_commit'], parent])
    raw = store.read_previous(parent, f'forecasts/{day}.json')
    public.need(raw is not None, 'DT_R1_OFFICIAL_REGISTRY')
    registry = public.checked(public._json(raw))
    cutoffs = {r['race_id']: r['cutoff_at'] for r in registry['races']}
    public.need(cutoffs.keys() == {r['race_id'] for r in proposal['races']}, 'DT_R1_REGISTRY_PARTITION')
    for row in proposal['races']:
        official = cutoffs[row['race_id']]
        public.need(official is None or clock(row['cutoff_at']) <= clock(official), 'DT_R1_REGISTRY_CUTOFF_CHANGED')
    body = shortlists.checked(dict(proposal, published_at=now().isoformat()))
    commit, packed = public._commit_projection(store, parent, path, body)
    public._push_projection(store, parent, path, commit, packed)
    return public._candidates_receipt('DT_R1_PUBLIC_PUBLISHED', body, commit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--body', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        public.need(0 < args.body.stat().st_size <= public.MAX_BYTES, 'DT_R1_PUBLIC_INPUT_BYTES')
        body = shortlists.checked(public._json(args.body.read_bytes()))
        report = (publish(args.repo, body) if args.publish else
                  public._candidates_receipt('DT_R1_PUBLIC_PREVIEW', body, None))
    except (KeyError, OSError, TypeError, ValueError) as error:
        reason = str(error)
        if not reason.isascii() or not reason.replace('_', '').isalnum():
            reason = 'DT_R1_PUBLIC_INPUT_OR_GIT_HOLD'
        print(json.dumps(dict(state='DT_R1_PUBLIC_HOLD', reason=reason), sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
