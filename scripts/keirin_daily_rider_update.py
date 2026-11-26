"""Publish daily numeric finish counts from the existing verified result archive."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
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


def _window_start(instant):
    today = instant.astimezone(JST).date()
    return (today - timedelta(days=MAX_DAYS - 1)).isoformat()


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
    published = public.when(latest['published_at'])
    posted = published.astimezone(JST).date().isoformat()
    first = _window_start(published)
    days = latest['days']
    need(type(days) is list and 1 <= len(days) <= MAX_DAYS and type(latest['riders']) is list, 'MANIFEST')
    for row in days:
        need(type(row) is dict and set(row) == {
            'day', 'archive_races', 'verified_races', 'observed_count', 'sha256', 'archive_index',
        } and first <= _day(row['day']) <= posted and HEX.fullmatch(row['sha256']) and
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
    unlisted = found - paths
    need(paths <= found and (prior is not None or not unlisted), 'PREVIOUS_PATHS')
    if unlisted:
        first = _window_start(public.when(prior['published_at']))
        for path in unlisted:
            day = path.removeprefix('rider-history/').removesuffix('.json')
            need(_path(day) == path and day < first, 'PREVIOUS_PATHS')
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
    first = _window_start(when)
    candidates = {}
    for oid, item in updates.items():
        day = checked_day(item)['day']
        need(day <= today and day not in candidates and GIT_OID.fullmatch(oid), 'UPDATE_DAY')
        if first <= day:
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
        # Earlier days stay on the public branch as separate dated archives.
        latest = _aggregate({day: item for day, item in days.items() if first <= day}, when.isoformat())
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
                              head, '--', *sorted(paths))
    result = {}
    for record in filter(None, listing.split('\0')):
        match = re.fullmatch(r'100644 blob ([0-9a-f]{40})\t(.+)', record)
        need(match is not None and match[2] in paths and paths[match[2]] not in result, 'ARCHIVE_INDEX')
        result[paths[match[2]]] = match[1]
    return result


def refresh(repo, reader, owner_private_pem, *, clock=lambda: datetime.now(timezone.utc), store=None):
    from race_ai import keirin_dossier_conditions as conditions
    from race_ai import keirin_official_nationwide_records as records
    from race_ai import keirin_official_rider_history as history
    from scripts.keirin_official_day_pipeline import check_owner_private_key
    from scripts import keirin_publish_dossier_conditions as dossier

    owner_public = check_owner_private_key(owner_private_pem)
    pin = Path(repo) / 'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
    need(owner_public.strip() == pin.read_bytes().strip(), 'OWNER_KEY_PAIR')
    store = store or public.PublicForecastGit(repo)
    parent, prior = read_latest(store)
    known = {row['day']: row for row in prior['days']} if prior else {}
    as_of = clock()
    today = as_of.astimezone(JST).date()
    first = _window_start(as_of)
    head = records.fetch_partial_head(reader, with_ancestry=True)
    # Exact paths keep discovery bounded as prior seasons accumulate in Git.
    elapsed_days = (today - date.fromisoformat(BASE_DAY)).days
    dated = set(known) | {(today - timedelta(days=age)).isoformat()
                          for age in range(min(MAX_DAYS, elapsed_days))}
    indexes = _archive_indexes(reader, head, dated, records.ROOT)
    need(known.keys() <= indexes.keys(), 'ARCHIVED_DAYS_MISSING')
    condition_paths = set(store.run(['ls-tree', '-r', '--name-only', parent, '--',
                                     'rider-condition-results/']).decode().splitlines())
    dirty = sorted(day for day, oid in indexes.items() if first <= day and (
        known.get(day, {}).get('archive_index') != oid or dossier.result_path(day) not in condition_paths))
    ready = []
    holds = Counter()
    contexts = {}
    for day in dirty:
        try:
            selected_store = records.RecordStore(reader, day, index_commit=head)
            if not selected_store.index['results'] and day not in known:
                continue
            regular_dirty = day not in known
            if not regular_dirty and known[day]['archive_index'] != indexes[day]:
                previous = store.read_previous(parent, _path(day))
                need(previous and sha256(previous).hexdigest() == known[day]['sha256'], 'PREVIOUS_DAY_SHA')
                old = checked_day(public._json(previous))
                regular_dirty = old['source_sha256'] != history.archive_signature(selected_store)
            context = None
            if selected_store.index.get('registry') is not None:
                try:
                    candidate = dossier.registry_conditions(selected_store, owner_private_pem)
                    contexts[day] = candidate
                    previous = store.read_previous(parent, dossier.result_path(day))
                    if previous is None or conditions.checked_result_slice(public._json(previous))[
                            'source_sha256'] != history.conditioned_signature(
                                day, history.archive_signature(selected_store), candidate[2]):
                        context = candidate
                except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
                    holds['condition_registry'] += 1
            if regular_dirty or context is not None:
                ready.append((day, selected_store, regular_dirty, context))
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            holds['archive_index'] += 1
    selected = ready
    if len(ready) > MAX_REPLAYS:
        # Earlier corrections rotate by JST day so held records cannot monopolize
        # every run. Leave two slots for the most recent changed dates.
        earlier, recent = ready[:-2], ready[-2:]
        cursor = today.toordinal() % len(earlier)
        selected = recent + (earlier[cursor:] + earlier[:cursor])[:MAX_REPLAYS - 2]
    pending, conditions_pending = {}, {}
    for day, selected_store, regular_dirty, context in selected:
        try:
            if context is not None:
                _, rows, signature = context
                ordinary, condition_result = history.project_rider_day_with_conditions(
                    selected_store, owner_private_pem, now=as_of, race_conditions=rows,
                    conditions_sha256=signature)
                conditions_pending[day] = condition_result
            else:
                ordinary = history.project_rider_day(selected_store, owner_private_pem, now=as_of)
            if regular_dirty:
                pending[indexes[day]] = checked_day(ordinary)
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            holds['saved_result_replay'] += 1
            # A sidecar failure never blocks the existing verified counts.
            if context is not None and regular_dirty:
                try:
                    pending[indexes[day]] = checked_day(history.project_rider_day(
                        selected_store, owner_private_pem, now=as_of))
                except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
                    pass
    if pending:
        published = publish_days(store, prior, pending, published_at=clock())
    else:
        _read_days(store, parent, prior)
        published = None
    latest = published['latest'] if published else prior
    rows = latest['days'] if latest else []
    state = 'PUBLIC_RIDER_HISTORY_UPDATED' if published else (
        'HOLD_PUBLIC_RIDER_HISTORY_SOURCE' if holds else 'PUBLIC_RIDER_HISTORY_CURRENT')
    condition_report = dict(state='HOLD_DOSSIER_CONDITIONS_REGISTRY')
    event_day = today.isoformat()
    if event_day in indexes:
        try:
            current = contexts.get(event_day)
            if current is None:
                source = records.RecordStore(reader, event_day, index_commit=head)
                if source.index.get('registry') is not None:
                    current = dossier.registry_conditions(source, owner_private_pem)
            if current is not None:
                registry, races, _ = current
                outcome = dossier.publish_day(store, event_day, registry=registry,
                    race_conditions=races, all_past_days={day for day in indexes if first <= day},
                    updated_results=conditions_pending, published_at=clock())
                condition_report = dict(state='DOSSIER_CONDITIONS_PUBLISHED' if outcome else
                    'DOSSIER_CONDITIONS_CURRENT', race_day=event_day, registered_races=len(registry['registered_race_ids']),
                    observed_grade=sum(row['meeting_grade'] is not None for row in races.values()),
                    observed_round=sum(row['round_stage'] is not None for row in races.values()))
                if outcome:
                    packet = outcome['packet']
                    window = packet['history']
                    condition_report.update(commit=outcome['commit'], riders=len(packet['riders']),
                        history_start_day=window['start_day'], history_end_day=window['end_day'],
                        numeric_finishes=window['numeric_finishes'],
                        condition_matched_finishes=window['condition_matched_finishes'],
                        history_scope=window['scope'])
        except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
            condition_report = dict(state='HOLD_DOSSIER_CONDITIONS_PUBLICATION')
    return dict(state=state,
                archive_commit=head, public_commit=published['commit'] if published else parent,
                days_updated=published['updated_days'] if published else 0,
                days_held=sum(holds.values()), hold_reasons=dict(holds),
                days_deferred=len(ready)-len(selected), result_days=len(rows),
                verified_races=sum(row['verified_races'] for row in rows),
                numeric_finishes=sum(row['observed_count'] for row in rows),
                latest_result_day=rows[-1]['day'] if rows else None, rider_conditions=condition_report,
                provider_requests=0)


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
