"""Calibrate the exact public shortlist from saved prior races on protected main."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_paired_measurement as measured
from race_ai import keirin_public_confidence as confidence
from race_ai import keirin_public_forecasts as public
from race_ai import keirin_secondary_result_consensus as consensus
from race_ai.keirin_nationwide_forecast_view import JST
from race_ai.keirin_note_feed import NoteFeedGit
from scripts import keirin_official_nationwide_continuation as continuation
from scripts.keirin_public_site_results import validate_roster


class ResultGit(NoteFeedGit):
    ref = 'state/keirin-public-results'


def _prior_revision(revisions, end):
    return next((row for row in reversed(revisions) if model.when(row['observed_at']) < end), None)


def _official_observations(store, private, end, coverage):
    for race_id, revisions in sorted(store.index['results'].items()):
        result_meta = _prior_revision(revisions, end)
        if result_meta is None:
            coverage['result_not_available_before_target'] += 1
            continue
        coverage['prior_results'] += 1
        try:
            original, scored, _ = records._replay_saved_result(
                store, store.index['originals'][race_id], result_meta, private)
            details = measured._result_measurements(original, scored)
            if details is None:
                coverage['void_or_refund'] += 1
                continue
            cutoff, _, winners, arms, _ = details
            result_at = max(model.when(scored['official_result']['observed_at']),
                            model.when(result_meta['observed_at']))
            sealed = original['baseline_sealed_at']
            if not model.when(sealed) < cutoff < result_at < end:
                coverage['held'] += 1
                continue
            expected = {'A': model.MODEL_A, 'B': model.MODEL_B}
            if any(original['baseline'][arm]['model'] != name for arm, name in expected.items()):
                coverage['other_model'] += 1
                continue
            coverage['scored_races'] += 1
            for arm in expected:
                tickets = arms[arm][:public.LIMIT]
                if tickets:
                    yield confidence.ShortlistObservation('official', arm, race_id, len(tickets),
                        sealed, cutoff.isoformat(), result_at.isoformat(), any(ticket in winners for ticket in tickets))
        except (ValueError, TypeError, KeyError, OSError, TimeoutExpired):
            coverage['held'] += 1


def _replay_day(store, private, end):
    coverage = Counter()
    return store.day, coverage, list(_official_observations(store, private, end, coverage))


def _prefetch(reader, head, stores):
    """Fetch only the pinned ciphertexts and receipts needed for this cohort."""
    paths, folders = set(), []
    for store, end in stores:
        folder = f'{records.ROOT}/{store.day}'
        folders.extend((folder, f'{archive.ROOT}/{store.day}'))
        for rid, versions in store.index['results'].items():
            selected = _prior_revision(versions, end)
            if selected is None:
                continue
            original = store.index['originals'][rid]
            paths.update(archive._refs(rid))
            paths.update(archive._form_refs(rid))
            paths.update(f"{folder}/{meta['evidence_sha256']}.sealed.json" for meta in (original, selected))
    return archive.prefetch_pinned_blobs(reader, head, paths, folders)


def _public_observations(day, forecasts, results, roster):
    if not forecasts or results is None or roster is None:
        return
    validate_roster(roster, consensus)
    public.need(roster['date'] == results['date'] == day and
                results['schema'] == 'KEIRIN_PUBLISHED_RESULTS_V1', 'CONFIDENCE_RESULT_DAY')
    starters = {row['race_id']: row for row in roster['races']}
    result_ids = [row['race_id'] for row in results['races']]
    public.need(len(result_ids) <= 300 and len(set(result_ids)) == len(result_ids), 'CONFIDENCE_RESULT_UNIQUE')
    matches = {row['race_id']: row for row in results['races'] if row['state'] == 'matched'}
    checked_at = model.when(results['checked_at'])
    for lane, packet in forecasts.items():
        if not packet:
            continue
        public.need(packet['day'] == day, 'CONFIDENCE_PREDICTION_DAY')
        for forecast in packet['races']:
            rid = forecast['race_id']
            if rid not in matches or rid not in starters:
                continue
            race = starters[rid]
            cutoff = forecast['cutoff_at']
            if model.when(cutoff) != model.when(race['published_cutoff_at']):
                continue
            created = forecast['saved_at' if lane == 'reference' else 'generated_at']
            if not model.when(created) < model.when(cutoff):
                continue
            if lane == 'racecard' and model.when(packet['published_at']) >= model.when(cutoff):
                continue
            cars = {row['number'] for row in race['observed_riders']}
            if lane == 'racecard' and cars != set(forecast['starter_cars']):
                continue
            state, winners = consensus.checked_published_result(matches[rid],
                dict(race_id=rid, cutoff_at=cutoff, starters=cars), checked_at)
            if state != 'matched':
                continue
            comparison = matches[rid]['comparison']
            compared = comparison['observed_at']
            sources = comparison['sources']
            if len(sources) != 2 or {source['source_id'] for source in sources} != {'kdreams', 'netkeirin'}:
                continue
            for origin in sources:
                consensus.check_race_url(provider='Kdreams' if origin['source_id'] == 'kdreams' else 'netkeirin',
                                         url=origin['url'], race_id=rid)
            if not all(model.when(cutoff) <= model.when(source['checked_at']) <= model.when(compared)
                       for source in sources):
                continue
            for arm in ('A', 'B'):
                tickets = forecast[arm.lower()]
                if tickets and all(set(ticket) <= cars for ticket in tickets):
                    yield confidence.ShortlistObservation(lane, arm, rid, len(tickets),
                        created, cutoff, compared, winners['3t'] in tickets)


def _published_observations(repo, store, parent, result_store, result_head, days):
    if result_head is None:
        return
    result_store.fetch(result_head)
    store.fetch(parent)
    for day in days:
        raw = store.read_previous(parent, f'forecasts/{day}.json')
        if not raw:
            continue
        registry = public.checked(public._json(raw))
        pending = {row['race_id']: row['cutoff_at'] for row in registry['races'] if row['status'] == 'pending'}
        forecasts = {}
        for lane, folder, check in (('reference', 'references', public.checked_reference),
                                    ('racecard', 'research', public.checked_research)):
            raw = store.read_previous(parent, f'{folder}/{day}.json')
            if raw is not None:
                packet = check(public._json(raw))
                rows = [row for row in packet['races'] if row['race_id'] in pending and
                        (pending[row['race_id']] is None or
                         model.when(pending[row['race_id']]) == model.when(row['cutoff_at']))]
                forecasts[lane] = dict(packet, races=rows)
                for row in rows:
                    del pending[row['race_id']]
        if not forecasts:
            continue
        documents = []
        for folder in ('results', 'rosters'):
            raw = archive.read_blob_bytes(repo, result_head, f'{folder}/{day}.json', max_bytes=public.MAX_BYTES)
            documents.append(public._json(raw) if raw else None)
        yield from _public_observations(day, forecasts, *documents)


def _publish(store, path, report):
    for attempt in range(2):
        parent = store.head()
        store.fetch(parent)
        raw = store.read_previous(parent, path)
        prior = public._json(raw) if raw else None
        if prior is not None:
            public.need(prior['schema'] == confidence.SCHEMA and prior['day'] == report['day'], 'CONFIDENCE_SCHEMA')
            if all(prior[key] == report[key] for key in ('training_window', 'validation_window', 'rows')):
                return dict(state='CONFIDENCE_CURRENT', commit=parent)
            public.need(model.when(prior['assessed_at']) < model.when(report['assessed_at']), 'CONFIDENCE_STALE')
        commit, payload = public._commit_projection(store, parent, path, report)
        try:
            public._push_projection(store, parent, path, commit, payload)
        except ValueError as error:
            if attempt or str(error) not in ('KEIRIN_NOTE_FEED_CONCURRENT_UPDATE', 'KEIRIN_NOTE_FEED_REMOTE_READBACK'):
                raise
        else:
            return dict(state='CONFIDENCE_PUBLISHED', commit=commit)


def run(repo, root, private, day, clock, *, skip_current):
    at = clock()
    target = date.fromisoformat(day)
    public.need(target <= at.astimezone(JST).date(), 'CONFIDENCE_FUTURE_DAY')
    days = [(target - timedelta(days=offset)).isoformat() for offset in range(10, 0, -1)]
    end = min(datetime.combine(target, time.min, JST), at)
    fit_end = datetime.combine(target - timedelta(days=3), time.min, JST)
    public_store = public.PublicForecastGit(repo)
    parent = public_store.head()
    public.need(parent is not None, 'CONFIDENCE_FORECAST_BRANCH')
    path = f'measurements/confidence-{day}.json'
    if skip_current:
        public_store.fetch(parent)
        prior = public_store.read_previous(parent, path)
        if prior:
            data = public._json(prior)
            public.need(data['schema'] == confidence.SCHEMA and data['day'] == day, 'CONFIDENCE_SCHEMA')
            return dict(data, publication=dict(state='CONFIDENCE_CURRENT', commit=parent))
    coverage = {}
    observations = []
    with TemporaryDirectory(prefix='shortlist-archive-', dir=root) as folder:
        reader = Path(folder)
        archive._cmd(reader, 'init', '--quiet', '--template=')
        archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
        archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
        archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
        head = records.fetch_partial_head(reader, with_ancestry=True)
        archive_days = set(records.discover_days_at(reader, head))
        stores = [(records.RecordStore(reader, historical, index_commit=head),
                   min(end, fit_end) if historical < fit_end.date().isoformat() else end)
                  for historical in reversed(days) if historical in archive_days]
        transport = _prefetch(reader, head, stores)
        # Prior dates are independent. Share the checked Git object cache and
        # keep the two most recent, larger days from serializing their reads.
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(_replay_day, store, private, available) for store, available in stores]
            for job in jobs:
                historical, day_coverage, rows = job.result()
                coverage[historical] = day_coverage
                observations.extend(rows)
    secondary_state = 'COMPARED'
    result_store = ResultGit(repo)
    result_head = None
    try:
        result_head = result_store.head()
        observations.extend(list(_published_observations(repo, public_store, parent, result_store, result_head, days)))
    except (ValueError, TypeError, KeyError, OSError, TimeoutExpired):
        secondary_state = 'PUBLIC_REFERENCE_RESULTS_HELD'
    report = confidence.build(observations, day=day, assessed_at=at.isoformat(), archive_commit=head)
    # Legacy public reference packets bind dates and tickets, but carry no
    # model revision. Their measured results can be shown without certifying
    # a probability across a potential model change.
    for row in report['rows']:
        if row['lane'] != 'official' and row['state'] == 'GRADED':
            row.update(state='HOLD_CALIBRATION_MODEL_PROVENANCE', probability=None, grade=None)
    report.update(official_replay=coverage, archive_transport=transport, secondary_state=secondary_state,
                  public_forecast_commit=parent, public_result_commit=result_head)
    publication = _publish(public_store, path, report)
    return dict(report, publication=publication)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--day')
    parser.add_argument('--skip-current', action='store_true')
    args = parser.parse_args()
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        repo, root, day, _, _ = continuation._runtime(repo=args.repo, private_root=args.private_root,
            owner_public_pem=args.owner_public_pem, owner_private_pem=private, day=args.day,
            clock=continuation.now_utc, mode='measure')
        outcome = run(repo, root, private, day, continuation.now_utc, skip_current=args.skip_current)
    except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
        print(json.dumps(dict(schema=confidence.SCHEMA, state='HOLD_SHORTLIST_CONFIDENCE_RUNTIME')))
        return 2
    print(json.dumps(outcome, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
