"""Read existing admitted official SP receipts and publish a roster-bound dossier."""
import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from race_ai import keirin_dossier_race_context as context
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_public_forecasts as public
from scripts.keirin_public_rider_projection import _checked_starters


JST = ZoneInfo('Asia/Tokyo')


def publish_day(repo, day, rows, *, published_at, store=None):
    """Append only newly verified race contexts to the existing public branch."""
    store = store or public.PublicForecastGit(repo)
    parent = store.head()
    public.need(parent is not None, 'DOSSIER_PUBLIC_BRANCH')
    store.fetch(parent)
    raw_registry = store.read_previous(parent, f'forecasts/{day}.json')
    raw_starters = store.read_previous(parent, f'starters/{day}.json')
    public.need(raw_registry is not None and raw_starters is not None, 'DOSSIER_PUBLIC_ROSTER')
    registry = public.checked(public._json(raw_registry))
    starters = _checked_starters(public._json(raw_starters))
    eligible = {row['race_id'] for row in starters['races']}
    registered = {row['race_id']: row['cutoff_at'] for row in registry['races']}
    public.need(registry['day'] == starters['day'] == day and eligible <= registered.keys(), 'DOSSIER_ROSTER_DAY')
    path = f'rider-context/{day}.json'
    raw = store.read_previous(parent, path)
    prior = context.checked_day(public._json(raw)) if raw else None
    public.need(prior is None or prior['day'] == day, 'DOSSIER_PREVIOUS_DAY')
    retained = {row['race_id']: row for row in prior['races']} if prior else {}
    new = {row['race_id']: row for row in rows if row['race_id'] in eligible}
    public.need(len({row['race_id'] for row in rows}) == len(rows), 'DOSSIER_DUPLICATE_RACE')
    public.need(all(registered[rid] is not None and public.when(row['cutoff_at']) == public.when(registered[rid])
                    for rid, row in new.items()), 'DOSSIER_REGISTRY_CUTOFF')
    same_sources = set(retained) & set(new)
    public.need(all(retained[rid]['card_sha256'] == new[rid]['card_sha256'] and
                    retained[rid]['comments_sha256'] == new[rid]['comments_sha256']
                    for rid in same_sources), 'DOSSIER_SOURCE_CHANGED')
    # A later independent read can recover prior finishes, so prefer the more
    # complete verified supplemental history from the same immutable source.
    for race_id in same_sources:
        previous, candidate = retained[race_id], new[race_id]
        if candidate == previous:
            continue
        verified = {rider['registration']: rider for rider in candidate['riders']}
        enriched = []
        for rider in previous['riders']:
            current = verified[rider['registration']]
            public.need({k: v for k, v in rider.items() if k != 'recent_results'} ==
                        {k: v for k, v in current.items() if k != 'recent_results'}, 'DOSSIER_RIDER_CHANGED')
            history = {entry['day']: entry for entry in current['recent_results']}
            history.update((entry['day'], entry) for entry in rider['recent_results'])
            dates = sorted(history, reverse=True)[:context.MAX_RECENT]
            enriched.append(dict(rider, recent_results=[history[day] for day in dates]))
        new[race_id] = dict(previous, riders=enriched)
    body = context.build_day(starters, list((retained | new).values()), published_at=published_at)
    if prior and body['coverage'] == prior['coverage'] and body['races'] == prior['races']:
        state, commit = 'PUBLIC_RIDER_CONTEXT_CURRENT', parent
    else:
        public.need(prior is None or public.when(prior['published_at']) <= published_at, 'DOSSIER_PUBLICATION_CLOCK')
        commit, raw = public._commit_projection(store, parent, path, body)
        public._push_projection(store, parent, path, commit, raw)
        state = 'PUBLIC_RIDER_CONTEXT_UPDATED'
    return dict(state=state, day=day, commit=commit, registered_calendar_races=len(registered),
                coverage=body['coverage'], provider_requests=0)


def replay_day(repo, day, owner_private_pem, *, clock=lambda: datetime.now(timezone.utc)):
    from race_ai import keirin_official_nationwide_records as records
    from scripts.keirin_official_day_pipeline import check_owner_private_key

    now = clock()
    public.need(date.fromisoformat(day).isoformat() == day <= now.astimezone(JST).date().isoformat(),
                'DOSSIER_REPLAY_DAY')
    expected = repo / 'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
    public.need(check_owner_private_key(owner_private_pem).strip() == expected.read_bytes().strip(),
                'DOSSIER_REPLAY_OWNER')
    with TemporaryDirectory(prefix='keirin-rider-context-') as folder:
        reader = Path(folder)
        archive._cmd(reader, 'init', '--quiet', '--template=')
        archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
        archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
        archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
        head = records.fetch_partial_head(reader, with_ancestry=True)
        admitted = records.load_admitted_day(reader, owner_private_pem, day, index_commit=head,
                                             include_dossier_context=True)
    report = publish_day(repo, day, admitted['dossier_rows'], published_at=clock())
    return dict(report, authenticated_originals=len(admitted['records']),
                source_projection_holds=admitted['dossier_holds'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--day', required=True)
    args = parser.parse_args()
    env = os.environ
    private = env.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        repo = args.repo.resolve()
        public.need(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == archive.REPO and
                    env.get('GITHUB_REPOSITORY_ID') == archive.REPO_ID and env.get('GITHUB_REF') == 'refs/heads/main' and
                    env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and env.get('GITHUB_JOB') == 'observe-results' and
                    env.get('GITHUB_WORKFLOW_REF') == 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main' and
                    env.get('RESULT_MODE') == 'dossier-context' and
                    archive._cmd(repo, 'rev-parse', 'HEAD')[1] == env.get('GITHUB_SHA'), 'DOSSIER_REPLAY_RUNTIME')
        report = replay_day(repo, args.day, private)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, TimeoutExpired):
        print(json.dumps(dict(state='HOLD_PUBLIC_RIDER_CONTEXT', provider_requests=0)))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
