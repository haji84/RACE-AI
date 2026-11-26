"""Publish daily numeric finish counts from the existing verified result archive."""
import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_public_forecasts as public


DAY_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1'
SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_V1'
LATEST = 'rider-history/latest.json'
BASE_SHA256 = '5384e6ea5b7460bc569debcb5871177da9f0ee0a908ca6d95269f4a8d474b310'
BASE_DAY = '2026-11-22'
JST = ZoneInfo('Asia/Tokyo')
MAX_DAYS = 400
MAX_REPLAYS = 4
HEX = re.compile(r'[0-9a-f]{64}')
GIT_OID = re.compile(r'[0-9a-f]{40}')
REGISTRATION = re.compile(r'[0-9]{6}')


def need(ok, code):
    if not ok:
        raise ValueError('PUBLIC_RIDER_HISTORY_' + code)


def _day(value):
    need(type(value) is str and value > BASE_DAY and date.fromisoformat(value).isoformat() == value,
         'DAY')
    return value


def _path(day):
    return 'rider-history/' + _day(day) + '.json'


def _encode(doc):
    body = public.canonical(doc) + b'\n'
    need(len(body) <= public.MAX_BYTES, 'SIZE')
    return body


def _ordered(keys):
    keys = list(keys)
    return keys == sorted(set(keys))


def checked_day(row):
    need(type(row) is dict and set(row) == {
        'schema', 'day', 'source_sha256', 'archive_races', 'verified_races', 'riders',
    } and row['schema'] == DAY_SCHEMA, 'DAY_SCHEMA')
    _day(row['day'])
    archive_races, verified = row['archive_races'], row['verified_races']
    need(type(row['source_sha256']) is str and HEX.fullmatch(row['source_sha256']) and
         type(archive_races) is int and type(verified) is int and
         0 < verified <= archive_races <= public.official.MAX_RACES, 'DAY_SOURCE')
    riders = row['riders']
    need(type(riders) is list and 1 <= len(riders) <= 9 * verified, 'DAY_RIDERS')
    for rider in riders:
        need(type(rider) is dict and set(rider) == {'registration', 'finish_counts'}, 'RIDER_FIELDS')
        reg, counts = rider['registration'], rider['finish_counts']
        need(type(reg) is str and REGISTRATION.fullmatch(reg) and reg != '000000' and
             type(counts) is list and len(counts) == 9 and
             all(type(count) is int and 0 <= count <= verified for count in counts) and
             0 < sum(counts) <= verified, 'RIDER_COUNTS')
    total = sum(sum(rider['finish_counts']) for rider in riders)
    need(_ordered(rider['registration'] for rider in riders) and verified <= total <= 9 * verified,
         'DAY_TOTAL')
    return row


def read_latest(store):
    parent = store.head()
    need(type(parent) is str and GIT_OID.fullmatch(parent), 'PUBLIC_BRANCH_REQUIRED')
    store.fetch(parent)
    raw = store.read_previous(parent, LATEST)
    if raw is None:
        return parent, None
    latest = public._json(raw)
    need(type(latest) is dict and set(latest) == {
        'schema', 'base_sha256', 'base_history_end_day', 'published_at', 'days', 'riders',
    } and latest['schema'] == SCHEMA and latest['base_sha256'] == BASE_SHA256 and
         latest['base_history_end_day'] == BASE_DAY, 'BASELINE')
    posted = public.when(latest['published_at']).astimezone(JST).date().isoformat()
    days = latest['days']
    need(type(days) is list and 1 <= len(days) <= MAX_DAYS and type(latest['riders']) is list, 'MANIFEST')
    for row in days:
        need(type(row) is dict and set(row) == {
            'day', 'archive_races', 'verified_races', 'observed_count', 'sha256', 'archive_index',
        } and _day(row['day']) <= posted and HEX.fullmatch(row['sha256']) and
             GIT_OID.fullmatch(row['archive_index']), 'MANIFEST_DAY')
    need(_ordered(row['day'] for row in days), 'DAY_ORDER')
    return parent, latest


def _aggregate(days, published_at):
    riders, proof = {}, []
    for day, (oid, raw, item) in sorted(days.items()):
        total = 0
        for result in item['riders']:
            reg, counts = result['registration'], result['finish_counts']
            row = riders.setdefault(reg, dict(registration=reg, finish_counts=[0] * 9,
                                              first_observed_day=day, latest_observed_day=day))
            row['finish_counts'] = [a + b for a, b in zip(row['finish_counts'], counts)]
            row['latest_observed_day'] = day
            total += sum(counts)
        proof.append(dict(day=day, archive_index=oid, sha256=sha256(raw).hexdigest(),
                          archive_races=item['archive_races'], verified_races=item['verified_races'],
                          observed_count=total))
    need(1 <= len(proof) <= MAX_DAYS, 'DAY_LIMIT')
    return dict(schema=SCHEMA, base_sha256=BASE_SHA256, base_history_end_day=BASE_DAY,
                published_at=published_at, days=proof, riders=[riders[reg] for reg in sorted(riders)])


def _read_days(store, parent, prior):
    rows = prior['days'] if prior else ()
    paths = {_path(row['day']) for row in rows}
    if prior:
        paths.add(LATEST)
    found = set(store.run(['ls-tree', '-r', '--name-only', parent, '--', 'rider-history/'])
                .decode().splitlines())
    need(found == paths, 'PREVIOUS_PATHS')
    days = {}
    for row in rows:
        day = row['day']
        raw = store.read_previous(parent, _path(day))
        need(raw is not None and sha256(raw).hexdigest() == row['sha256'], 'PREVIOUS_DAY_SHA')
        item = checked_day(public._json(raw))
        need(item['day'] == day, 'PREVIOUS_DAY')
        days[day] = (row['archive_index'], raw, item)
    if prior:
        need(_aggregate(days, prior['published_at']) == prior, 'PREVIOUS_AGGREGATE')
    return days


def publish_days(store, expected, updates, *, published_at):
    """Replace corrected days as units and commit them together with the cumulative view."""
    when = public.when(published_at.isoformat())
    today = when.astimezone(JST).date().isoformat()
    candidates = {}
    for oid, item in updates.items():
        day = checked_day(item)['day']
        need(day <= today and day not in candidates and GIT_OID.fullmatch(oid), 'UPDATE_DAY')
        candidates[day] = (oid, _encode(item), item)

    for attempt in range(2):
        parent, prior = read_latest(store)
        need(prior == expected, 'CONCURRENT_HISTORY_UPDATE')
        days = _read_days(store, parent, prior)
        files = {}
        for day, candidate in candidates.items():
            old = days.get(day)
            if old:
                if old[1] == candidate[1]:
                    continue
                need(old[0] != candidate[0] and candidate[2]['verified_races'] >= old[2]['verified_races'] and
                     candidate[2]['archive_races'] >= old[2]['archive_races'], 'DAY_COVERAGE_REGRESSED')
            days[day] = candidate
            files[_path(day)] = candidate[1]
        if not files:
            return None
        need(prior is None or public.when(prior['published_at']) < when, 'PUBLICATION_CLOCK')
        latest = _aggregate(days, when.isoformat())
        files[LATEST] = _encode(latest)
        commit = store.commit(files, parent)
        diff = store.run(['diff-tree', '--no-commit-id', '--name-only', '-r', parent, commit])
        need(set(diff.decode().splitlines()) == set(files), 'COMMIT_PATHS')
        try:
            store.push(commit, parent)
        except (ValueError, TimeoutExpired):
            tip, live = read_latest(store)
            if tip != parent:
                store.run(['merge-base', '--is-ancestor', parent, tip])
            if live == latest and all(store.read_previous(tip, path) == raw for path, raw in files.items()):
                return dict(commit=tip, updated_days=len(files) - 1, latest=latest)
            if attempt or parent == tip or live != expected:
                raise
        else:
            need(all(store.read_previous(commit, path) == raw for path, raw in files.items()), 'READBACK')
            return dict(commit=commit, updated_days=len(files) - 1, latest=latest)


def _archive_indexes(reader, head, days, root):
    paths = {f'{root}/{day}/index.json': day for day in days}
    if not paths:
        return {}
    _, listing = archive._cmd(reader, '--no-replace-objects', 'ls-tree', '-z', '--full-tree',
                              head, '--', *paths)
    result = {}
    for record in filter(None, listing.split('\0')):
        match = re.fullmatch(r'100644 blob ([0-9a-f]{40})\t(.+)', record)
        need(match is not None and match[2] in paths and paths[match[2]] not in result, 'ARCHIVE_INDEX')
        result[paths[match[2]]] = match[1]
    need(set(result) == set(days), 'MISSING_ARCHIVE_INDEX')
    return result


def refresh(repo, reader, owner_private_pem, *, clock=lambda: datetime.now(timezone.utc), store=None):
    from race_ai import keirin_official_nationwide_records as records
    from race_ai import keirin_official_rider_history as history
    from scripts.keirin_official_day_pipeline import check_owner_private_key

    owner_public = check_owner_private_key(owner_private_pem)
    pin = Path(repo) / 'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
    need(owner_public.strip() == pin.read_bytes().strip(), 'OWNER_KEY_PAIR')
    store = store or public.PublicForecastGit(repo)
    parent, prior = read_latest(store)
    known = {row['day']: row for row in prior['days']} if prior else {}
    as_of = clock()
    today = as_of.astimezone(JST).date().isoformat()
    head = records.fetch_partial_head(reader)
    dated = [day for day in records.discover_days_at(reader, head) if BASE_DAY < day <= today]
    indexes = _archive_indexes(reader, head, dated, records.ROOT)
    need(known.keys() <= indexes.keys(), 'ARCHIVED_DAYS_MISSING')
    dirty = sorted(day for day, oid in indexes.items() if known.get(day, {}).get('archive_index') != oid)
    ready = []
    holds = 0
    for day in dirty:
        try:
            selected_store = records.RecordStore(reader, day, index_commit=head)
            if day in known:
                previous = store.read_previous(parent, _path(day))
                need(previous and sha256(previous).hexdigest() == known[day]['sha256'], 'PREVIOUS_DAY_SHA')
                old = checked_day(public._json(previous))
                if old['source_sha256'] == history.archive_signature(selected_store):
                    continue
            if not selected_store.index['results'] and day not in known:
                continue
            ready.append((day, selected_store))
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            holds += 1
    selected = ready
    if len(ready) > MAX_REPLAYS:
        # Earlier corrections rotate by JST day so held records cannot monopolize
        # every run. Leave two slots for the most recent changed dates.
        earlier, recent = ready[:-2], ready[-2:]
        cursor = date.fromisoformat(today).toordinal() % len(earlier)
        selected = recent + (earlier[cursor:] + earlier[:cursor])[:MAX_REPLAYS - 2]
    pending = {}
    for day, selected_store in selected:
        try:
            pending[indexes[day]] = checked_day(history.project_rider_day(
                selected_store, owner_private_pem, now=as_of))
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            holds += 1
    if pending:
        published = publish_days(store, prior, pending, published_at=clock())
    else:
        _read_days(store, parent, prior)
        published = None
    latest = published['latest'] if published else prior
    rows = latest['days'] if latest else []
    state = 'PUBLIC_RIDER_HISTORY_UPDATED' if published else (
        'HOLD_PUBLIC_RIDER_HISTORY_SOURCE' if holds else 'PUBLIC_RIDER_HISTORY_CURRENT')
    return dict(state=state,
                archive_commit=head, public_commit=published['commit'] if published else parent,
                days_updated=published['updated_days'] if published else 0, days_held=holds,
                days_deferred=len(ready)-len(selected), result_days=len(rows),
                verified_races=sum(row['verified_races'] for row in rows),
                numeric_finishes=sum(row['observed_count'] for row in rows),
                latest_result_day=rows[-1]['day'] if rows else None, provider_requests=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        env = os.environ
        need(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == archive.REPO and
             env.get('GITHUB_REPOSITORY_ID') == archive.REPO_ID and env.get('GITHUB_REF') == 'refs/heads/main' and
             env.get('GITHUB_EVENT_NAME') in ('schedule', 'workflow_dispatch') and
             env.get('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true' and
             env.get('GITHUB_WORKFLOW_REF') == 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main' and
             env.get('GITHUB_JOB') == 'publish-rider-dossiers', 'TRUSTED_WORKFLOW')
        need(archive._cmd(repo, 'rev-parse', 'HEAD')[1] == env.get('GITHUB_SHA'), 'CHECKOUT')
        with TemporaryDirectory(prefix='keirin-rider-archive-') as folder:
            reader = Path(folder)
            archive._cmd(reader, 'init', '--quiet', '--template=')
            archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
            archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
            archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
            report = refresh(repo, reader, env.get('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode())
    except (ValueError, TypeError, KeyError, OSError, TimeoutExpired) as error:
        reason = str(error)
        report = dict(state='HOLD_PUBLIC_RIDER_HISTORY', provider_requests=0)
        if re.fullmatch(r'PUBLIC_RIDER_HISTORY_[A-Z_]+', reason):
            report['reason'] = reason
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 2 if report['state'].startswith('HOLD_') else 0


if __name__ == '__main__':
    raise SystemExit(main())
