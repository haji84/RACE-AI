"""Publish bounded rider dossier facts from already retained Kdreams racecards."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from unicodedata import normalize

from race_ai import keirin_dossier_secondary as secondary
from race_ai.keirin_dossier_race_context import MAX_RACES
from race_ai import keirin_public_forecasts as public
from scripts.keirin_capture_public_two_sources import private_dir
from scripts.keirin_daily_rider_update import BASE_SHA256
from scripts.keirin_note_collect_inputs import _read
from scripts.keirin_public_rider_projection import DIRECTORY_SCHEMA, _checked_starters
from scripts.keirin_publish_result_unread import _source


DIRECTORY_URL = ('https://keirin-20261119-race-note.chankuma.chatgpt.site/'
                 'data/keirin_national_rider_directory.json')
DIRECTORY_LIMIT = 3 * 1024 * 1024


def _person(value):
    return ''.join(normalize('NFKC', value).split())


def _national_identities():
    response = subprocess.run(
        ['curl', '-q', '--proto', '=https', '--max-time', '15', '--max-filesize',
         str(DIRECTORY_LIMIT), '--silent', '--show-error', '--fail', DIRECTORY_URL],
        check=True, capture_output=True)
    raw = response.stdout
    public.need(0 < len(raw) <= DIRECTORY_LIMIT and sha256(raw).hexdigest() == BASE_SHA256,
                'SECONDARY_DOSSIER_DIRECTORY_BINDING')
    directory = public._json(raw)
    public.need(directory['schema'] == DIRECTORY_SCHEMA, 'SECONDARY_DOSSIER_DIRECTORY_SCHEMA')
    names = {}
    duplicates = set()
    for row in directory['riders']:
        name = _person(row['name'])
        if name in names:
            duplicates.add(name)
        names[name] = row['registration']
    return {name: reg for name, reg in names.items() if name not in duplicates}


def _stored(store, head, directory, day, check):
    raw = store.read_previous(head, f'{directory}/{day}.json')
    if raw is None:
        return None
    packet = check(public._json(raw))
    public.need(packet['day'] == day, 'SECONDARY_DOSSIER_DAY_BINDING')
    return packet


def _status(state, day, *, coverage=None, commit=None, holds=None):
    return dict(state='PUBLIC_RIDER_CONTEXT_SECONDARY_'+state, day=day,
                commit=commit, coverage=coverage or {}, holds=dict(holds or {}), provider_requests=0)


def _safe_reason(error):
    reason = str(error)
    return reason if re.fullmatch('[A-Z0-9_]{1,100}', reason) else 'RACECARD_UNVERIFIED'


def publish_cards(repo, day, cards, *, published_at, published_only, store=None):
    """Bind hashed saved sources to current roster identities and add a public day."""
    store = store or public.PublicForecastGit(repo)
    parent = store.head()
    public.need(parent is not None, 'SECONDARY_DOSSIER_PUBLIC_BRANCH')
    for attempt in range(2):
        try:
            return _publish_cards(store, parent, day, cards, published_at=published_at, published_only=published_only)
        except (ValueError, OSError):
            current = store.head()
            if attempt or current is None or current == parent:
                raise
            parent = current


def _publish_cards(store, parent, day, cards, *, published_at, published_only):
    store.fetch(parent)
    starters = _stored(store, parent, 'starters', day, _checked_starters)
    registry = _stored(store, parent, 'forecasts', day, public.checked)
    prior = _stored(store, parent, 'rider-context-secondary', day, secondary.checked_day)
    if published_only:
        public.need(starters is not None and registry is not None, 'SECONDARY_DOSSIER_PUBLIC_ROSTER')
    fields = {row['race_id']: row for row in (starters or {}).get('races', [])}
    cutoffs = {row['race_id']: row['cutoff_at'] for row in (registry or {}).get('races', [])}
    retained = {}
    for row in (prior or {}).get('races', []):
        race_id = row['race_id']
        expected = fields.get(race_id)
        keys = lambda riders: {(rider['number'], rider['registration']) for rider in riders}
        if expected and keys(row['riders']) != keys(expected['riders']):
            continue
        cutoff = cutoffs.get(race_id)
        retained[race_id] = dict(row, cutoff_at=public.when(cutoff).isoformat()) if cutoff else row
    if not published_only:
        for race_id, row in retained.items():
            fields.setdefault(race_id, dict(race_id=race_id, riders=[
                dict(number=rider['number'], registration=rider['registration']) for rider in row['riders']]))
    identities, holds = None, Counter()
    additions = {}
    for race_id, raw, receipt, expected_cutoff in cards:
        try:
            public.need(registry is None or race_id in cutoffs, 'SECONDARY_DOSSIER_UNREGISTERED_RACE')
            card = secondary.source_card(raw, receipt, race_id, now=published_at)
            if expected_cutoff is not None:
                public.need(public.when(expected_cutoff) == public.when(card['source_cutoff_at']),
                            'SECONDARY_DOSSIER_SOURCE_CUTOFF')
            official = fields.get(race_id)
            if not official or 'name' not in official['riders'][0]:
                public.need(not published_only, 'SECONDARY_DOSSIER_PUBLIC_ROSTER')
                if identities is None:
                    identities = _national_identities()
                official = dict(race_id=race_id, riders=[
                    dict(number=rider['number'], name=rider['name'],
                         registration=identities[_person(rider['name'])]) for rider in card['riders']])
            cutoff = cutoffs.get(race_id) or card['source_cutoff_at']
            row = secondary._project_card(card, official, official_cutoff_at=cutoff, now=published_at)
            previous = additions.get(race_id) or retained.get(race_id)
            if previous is None or public.when(row['source_at']) > public.when(previous['source_at']):
                fields[race_id] = official
                additions[race_id] = row
        except (ValueError, KeyError, IndexError, TypeError, OSError, subprocess.SubprocessError) as error:
            holds[_safe_reason(error)] += 1
    if not additions and not retained:
        return _status('NO_QUALIFYING_ROWS', day, holds=holds)
    if published_only:
        public.need(retained.keys() <= fields.keys(), 'SECONDARY_DOSSIER_ROSTER_SHRANK')
    posted = max(published_at, public.when(starters['published_at'])) if starters else published_at
    basis = dict(schema='RACE_AI_KEIRIN_PUBLIC_STARTERS_V1', day=day, published_at=posted.isoformat(),
                 races=list(fields.values()))
    packet = secondary.build_day(basis, list((retained | additions).values()), published_at=posted)
    if prior and packet['races'] == prior['races'] and packet['coverage'] == prior['coverage']:
        return _status('UNCHANGED', day, coverage=packet['coverage'], commit=parent, holds=holds)
    public.need(prior is None or public.when(prior['published_at']) <= posted, 'SECONDARY_DOSSIER_CLOCK')
    path = f'rider-context-secondary/{day}.json'
    commit, raw = public._commit_projection(store, parent, path, packet)
    public._push_projection(store, parent, path, commit, raw)
    return _status('UPDATED', day, coverage=packet['coverage'], commit=commit, holds=holds)


def publish_saved_reference(repo, root, note, entry, *, published_at):
    """Reuse the verified in-run source bundle after its encrypted Git readback."""
    public.project_reference(note, entry, published_at=published_at)
    day, = entry['days']
    saved = public.when(entry['created_at'])
    root = private_dir(root)
    references = public._captured_references(note, day, entry['captured_race_ids'])
    manifest = public._json(note['files'][f'data/{day}/manifest.json']['text'])
    observed = manifest['source_receipts']
    observed_by_url = {receipt['url']: receipt for receipt in observed}
    public.need(len(observed_by_url) == len(observed), 'SECONDARY_DOSSIER_RECEIPT_DUPLICATE')
    cards = []
    for reference in references:
        snapshot = reference['input']
        source = snapshot['cutoff_source']
        receipt = observed_by_url[source['url']]
        cutoff = snapshot['published_cutoff_at']
        public.need(all(source[key] == receipt[key] for key in ('url','bytes_sha256','captured_at')) and
                    public.when(receipt['captured_at']) < public.when(cutoff), 'SECONDARY_DOSSIER_NOTE_SOURCE')
        raw, _ = _source(root, receipt, generated_at=saved)
        cards.append((snapshot['race_id'], raw, receipt, cutoff))
    return publish_cards(repo, day, cards, published_at=published_at, published_only=False)


def replay_saved_captures(repo, day, folders, *, published_at):
    cards = []
    seen = set()
    for folder in folders:
        root = private_dir(folder)
        captured = public._json(_read(root/'cards-observed.json', public.MAX_BYTES))
        public.need(type(captured) is list and len(captured) <= MAX_RACES, 'SECONDARY_DOSSIER_CAPTURE')
        for item in captured:
            rid = item['race_id']
            public.need(rid not in seen and rid[:8] == day.replace('-', ''), 'SECONDARY_DOSSIER_DUPLICATE')
            seen.add(rid)
            receipt = item['kdreams_receipt']
            raw, _ = _source(root, receipt, generated_at=published_at)
            cards.append((rid, raw, receipt, None))
    return publish_cards(repo, day, cards, published_at=published_at, published_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--day', required=True)
    parser.add_argument('--capture-dir', action='append', type=Path, required=True)
    args = parser.parse_args()
    try:
        public.official._day(args.day)
        report = replay_saved_captures(args.repo, args.day, args.capture_dir,
                                       published_at=datetime.now(timezone.utc))
    except (ValueError, OSError, TypeError, KeyError, subprocess.SubprocessError):
        print(json.dumps(dict(state='HOLD_PUBLIC_RIDER_CONTEXT_SECONDARY', provider_requests=0)))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
