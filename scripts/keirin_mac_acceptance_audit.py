"""Read Mac cadence and the protected GitHub delivery receipts in one audit."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

from race_ai.keirin_note_feed import BRANCH, MAX_WIRE, checked_index
from scripts.keirin_mac_cycle import audit_window


REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
JST = timezone(timedelta(hours=9))
WORKFLOWS = ('keirin-nationwide-ab-auto.yml', 'keirin-result-live.yml',
             'keirin-pr71-owner-autonomous.yml')
EVENTS = ('schedule', 'workflow_dispatch')


def utc(value):
    at = datetime.fromisoformat(value)
    if at.utcoffset() is None:
        raise ValueError('an explicit GitHub timestamp is required')
    return at.astimezone(timezone.utc)


def delivery_days(index, start, end):
    days = {}
    day = start.astimezone(JST).date()
    while day <= end.astimezone(JST).date():
        days[str(day)] = dict(registered=None, original={}, results=set())
        day += timedelta(days=1)
    for entry in index['entries']:
        if utc(entry['created_at']) > end:
            continue
        if entry['kind'] == 'nationwide' and (state := days.get(entry['days'][0])) is not None:
            state['registered'] = set(entry['registered_race_ids'])
            for race_id, revision in entry['original_revisions'].items():
                baseline = revision['baseline']
                if state['original'].setdefault(race_id, baseline) != baseline:
                    raise ValueError('frozen original identity changed')
        if entry['kind'] == 'result':
            for race_id in entry['result_revisions']:
                race_day = f'{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}'
                if race_day in days:
                    days[race_day]['results'].add(race_id)
    observed = []
    for day, state in days.items():
        registered = state['registered']
        originals = state['original'].keys()
        results = state['results']
        observed.append(dict(day_jst=day, registered=len(registered) if registered is not None else None,
            original_count=len(originals), original_missing=len(registered-originals) if registered is not None else None,
            result_revision_count=len(results), originals_with_result_revision=len(results & originals)))
    return observed


def workflow_observation(name, runs, start, end):
    events = {event: dict(starts=0, concluded_success=0, other_conclusions=0,
                          completion_unconfirmed_in_window=0, runs=[]) for event in EVENTS}
    runs = sorted(runs, key=lambda row: utc(row['run_started_at']))
    seen = set()
    starts = []
    for row in runs:
        run_id = row['id']
        attempt = row['run_attempt']
        if (type(run_id) is not int or run_id <= 0 or run_id in seen
                or type(attempt) is not int or attempt < 1
                or row['event'] not in events or row['head_branch'] != 'main'
                or row['path'] != '.github/workflows/' + name
                or not re.fullmatch('[0-9a-f]{40}', row['head_sha'])
                or row['repository']['id'] != REPO_ID or row['head_repository']['id'] != REPO_ID):
            raise ValueError('unexpected GitHub workflow provenance')
        seen.add(run_id)
        at = utc(row['run_started_at'])
        if not start <= at <= end:
            continue
        starts.append(at)
        event = events[row['event']]
        event['starts'] += 1
        event['runs'].append(dict(id=run_id, attempt=attempt, started_at=at.isoformat()))
        if row['status'] != 'completed' or utc(row['updated_at']) > end:
            event['completion_unconfirmed_in_window'] += 1
        elif row['conclusion'] == 'success':
            event['concluded_success'] += 1
        else:
            event['other_conclusions'] += 1
    for event in events.values():
        event.update(start_intervals([utc(row['started_at']) for row in event['runs']]))
    events['all_start_intervals'] = start_intervals(starts)
    return events


def start_intervals(starts):
    return dict(first_start=starts[0].isoformat() if starts else None,
                last_start=starts[-1].isoformat() if starts else None,
                max_start_gap_seconds=max(((b-a).total_seconds() for a, b in zip(starts, starts[1:])),
                                          default=None))


def github_api(gh, path, *, paginated=False):
    command = [str(gh), 'api', '--hostname', 'github.com']
    if paginated:
        command.extend(('--paginate', '--slurp'))
    result = subprocess.run([*command, f'repos/{REPO}/{path}'], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, GH_PROMPT_DISABLED='1'), timeout=45, check=True)
    return json.loads(result.stdout)


def workflow_runs(gh, name, start, end):
    # A schedule queued before the observation can start inside the window.
    bounds = ((start-timedelta(days=1)).astimezone(timezone.utc), end.astimezone(timezone.utc))
    created = '..'.join(at.isoformat(timespec='seconds').replace('+00:00', 'Z') for at in bounds)
    runs = []
    for event in EVENTS:
        query = urlencode(dict(branch='main', event=event, per_page=100, created=created))
        pages = github_api(gh, f'actions/workflows/{name}/runs?{query}', paginated=True)
        rows = [row for page in pages for row in page['workflow_runs']]
        if not pages or len(rows) != pages[0]['total_count'] or len(rows) > 1000:
            raise ValueError('incomplete Actions run listing')
        runs.extend(rows)
    return runs


def production_observation(gh, start, end):
    ref = github_api(gh, 'git/ref/heads/' + BRANCH)
    commit = ref['object']['sha']
    if (ref['ref'] != 'refs/heads/' + BRANCH or ref['object']['type'] != 'commit'
            or not re.fullmatch('[0-9a-f]{40}', commit)):
        raise ValueError('unexpected encrypted delivery ref')
    url = f'https://raw.githubusercontent.com/{REPO}/{commit}/index.json'
    with urlopen(url, timeout=15) as response:
        body = response.read(MAX_WIRE + 1)
        if response.status != 200 or response.geturl() != url or len(body) > MAX_WIRE:
            raise ValueError('unexpected encrypted index response')
    read_at = datetime.now(timezone.utc)
    root = Path(__file__).resolve().parents[1]
    recipient = json.loads((root/'config/keirin-note-recipient.json').read_bytes())
    index = checked_index(json.loads(body), recipient)
    workflows = {name: workflow_observation(name, workflow_runs(gh, name, start, end), start, end)
                 for name in WORKFLOWS}
    return dict(state='GITHUB_PRODUCTION_READBACK', delivery_commit=commit, index_read_at=read_at.isoformat(),
                delivery_index_sha256=sha256(body).hexdigest(),
                delivery_days=delivery_days(index, start, end), workflows=workflows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--audit-since', type=datetime.fromisoformat, required=True)
    parser.add_argument('--gh', type=Path, default=Path('/opt/homebrew/bin/gh'))
    args = parser.parse_args(argv)
    os.umask(0o077)
    now = datetime.now(timezone.utc)
    local = audit_window(args.state_dir, args.audit_since, clock=lambda: now)
    try:
        github = production_observation(args.gh, args.audit_since, now)
    except (OSError, ValueError, KeyError, TypeError, HTTPException, subprocess.SubprocessError):
        github = dict(state='HOLD_GITHUB_PRODUCTION_READBACK')
    print(json.dumps(dict(schema='RACE_AI_KEIRIN_MAC_ACCEPTANCE_OBSERVATION_V1',
                    local=local, github=github), sort_keys=True, allow_nan=False))
    return 0 if github['state'] == 'GITHUB_PRODUCTION_READBACK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
