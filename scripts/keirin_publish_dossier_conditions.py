"""Project and publish condition aggregates without accessing any provider."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from subprocess import TimeoutExpired

from race_ai import keirin_dossier_conditions as conditions
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as history
from race_ai import keirin_public_forecasts as public

ARCHIVE_PATH = 'rider-condition-archive/2026-11-25.json'


def result_path(day):
    return 'rider-condition-results/' + conditions._day(day) + '.json'


def condition_path(day):
    return 'rider-conditions/' + conditions._day(day) + '.json'


def registry_conditions(store, key):
    """Re-read captured calendar and race program for the complete dated registry."""
    meta = store.index['registry']
    if meta is None:
        raise ValueError('DOSSIER_CONDITIONS_REGISTRY_REQUIRED')
    source = store.read(meta, key)
    registry = records.replay_registry(source)
    data = conditions.official_race_conditions(**source['inventory'],
        day=store.day, now=source['observed_at'])
    public.need(set(data) <= set(registry['registered_race_ids']), 'CONDITION_REGISTRY_BINDING')
    return registry, data, sha256(history._canonical(data)).hexdigest()


def checked_archive_bytes(raw):
    archive = conditions.checked_archive_slice(public._json(raw))
    receipt = Path(__file__).resolve().parent.parent / (
        'docs/evidence/keirin-live-accuracy-closure-20261125/rider-dossier-recovery.json')
    pins = json.loads(receipt.read_bytes())
    from scripts.keirin_dossier_condition_archive import PINNED_ARCHIVES

    public.need(archive['registry_sha256'] == pins['files']['official-current-registry.json']['sha256'] and
                archive['archive_sha256s'] == sorted(item[0] for item in PINNED_ARCHIVES.values()) and
                archive['start_day'] == pins['history_start_day'] and archive['end_day'] == pins['history_end_day'] and
                archive['numeric_finishes'] == pins['numeric_finish_records'], 'CONDITION_ARCHIVE_PIN')
    return archive


def _encode(row, limit):
    raw = public.canonical(row) + b'\n'
    public.need(len(raw) <= limit, 'CONDITION_BODY_SIZE')
    return raw


def _commit(store, parent, files):
    commit = store.commit(files, parent)
    paths = store.run(['diff-tree','--no-commit-id','--name-only','-r',parent,commit])
    public.need(set(paths.decode().splitlines()) == set(files), 'CONDITION_COMMIT_PATHS')
    store.push(commit, parent)
    public.need(all(store.read_previous(commit,path) == raw for path,raw in files.items()),
                'CONDITION_READBACK')
    return commit


def publish_archive(store, raw, expected_sha256):
    """Accept the exact protected runner aggregate and retain it immutably."""
    public.need(type(raw) is bytes and 0 < len(raw) <= conditions.MAX_BYTES and
                sha256(raw).hexdigest() == expected_sha256, 'CONDITION_ARCHIVE_READBACK_SHA')
    doc = checked_archive_bytes(raw)
    public.need(_encode(doc, conditions.MAX_BYTES) == raw, 'CONDITION_ARCHIVE_CANONICAL')
    for attempt in range(2):
        parent = store.head()
        store.fetch(parent)
        old = store.read_previous(parent, ARCHIVE_PATH)
        if old is not None:
            public.need(old == raw, 'CONDITION_ARCHIVE_CHANGED')
            return parent
        try:
            return _commit(store, parent, {ARCHIVE_PATH:raw})
        except (ValueError, TimeoutExpired):
            if attempt or store.head() == parent:
                raise
    raise ValueError('DOSSIER_CONDITIONS_CONCURRENT_ARCHIVE')


def publish_day(store, day, *, registry, race_conditions, all_past_days, updated_results, published_at):
    """Update whole corrected result slices and the current day's dated condition snapshot atomically."""
    path = condition_path(day)
    day_path = {d:result_path(d) for d in all_past_days if d < day}
    for attempt in range(2):
        parent = store.head()
        store.fetch(parent)
        files, sources = {}, []
        for d, result in sorted(updated_results.items()):
            public.need(conditions.checked_result_slice(result)['day'] == d, 'CONDITION_RESULT_DAY')
            raw = _encode(result, public.MAX_BYTES)
            if store.read_previous(parent, result_path(d)) != raw:
                files[result_path(d)] = raw
        # Today's results never enter today's race dossier history, even if already official.
        for d, item_path in sorted(day_path.items()):
            raw = files.get(item_path) or store.read_previous(parent, item_path)
            if raw is not None:
                part = conditions.checked_result_slice(public._json(raw))
                public.need(part['day'] == d, 'CONDITION_RESULT_DAY')
                sources.append(part)
        base = store.read_previous(parent, ARCHIVE_PATH)
        packet = conditions.build_day(day=day, published_at=published_at,
            registered_races=len(registry['registered_race_ids']), calendar_sha256=registry['calendar_source_sha256'],
            races=race_conditions, past_results=sources, history_archive=checked_archive_bytes(base) if base else None)
        old = store.read_previous(parent,path)
        if old:
            prior = conditions.checked_day(public._json(old))
            old_rows = {row['race_id']:row for row in prior['races']}
            new_rows = {row['race_id']:row for row in packet['races']}
            public.need(prior['day'] == day and packet['registered_races'] >= prior['registered_races'] and
                        set(old_rows) <= set(new_rows) and
                        len(prior['history']['source_sha256s']) <= len(packet['history']['source_sha256s']) and
                        public.when(prior['published_at']) <= public.when(packet['published_at']),
                        'CONDITION_PROJECTION_REGRESSED')
            for rid, row in old_rows.items():
                new = new_rows[rid]
                public.need(public.when(row['source_at']) <= public.when(new['source_at']) and
                            (row['meeting_grade'] is None or new['meeting_grade'] is not None) and
                            (row['round_stage'] is None or new['round_stage'] is not None),
                            'CONDITION_SOURCE_REGRESSED')
        if not old or prior != dict(packet, published_at=prior['published_at']):
            files[path] = _encode(packet, conditions.MAX_BYTES)
        if not files:
            return None
        try:
            commit = _commit(store, parent, files)
        except (ValueError, TimeoutExpired):
            if attempt or store.head() == parent:
                raise
        else:
            return dict(commit=commit, packet=packet)
    raise ValueError('DOSSIER_CONDITIONS_CONCURRENT_DAY')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        with args.archive.open('rb') as stream:
            raw = stream.read(conditions.MAX_BYTES + 1)
        commit = publish_archive(public.PublicForecastGit(args.repo), raw, args.expected_sha256)
    except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
        print(json.dumps(dict(state='HOLD_DOSSIER_CONDITION_ARCHIVE_PUBLICATION')))
        return 2
    print(json.dumps(dict(state='DOSSIER_CONDITION_ARCHIVE_PUBLISHED', commit=commit, path=ARCHIVE_PATH)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
