"""Reconcile an authenticated first P0 using only already-retained official bytes.

The native reader, saved-view projection, settlement parser and frozen-forecast
scorer remain the existing implementations. Only the encrypted saved feed is
published; source state and exact forecast originals are never rewritten.
"""
import argparse
import base64
from collections import Counter
from datetime import date, datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_vault as V
from race_ai import boat_model_runtime as runtime
from race_ai import saved_view_feed as F
from race_ai.actions_contract import digest
from race_ai.boat_history_store import instant, wire
from race_ai.boat_name_aliases import _term_names
from race_ai.boat_pdca_recipient import _json
from race_ai.boat_saved_view_intake import append_views, project_native_state
from race_ai.first_receipt_continuity import latest_result_observations
from race_ai.frozen_day_cycle import evaluate
from race_ai.official_race_updates import endpoint
from race_ai.racer_intraday_handoff import load_intraday
from race_ai.racer_intraday_source import result_url
from race_ai.saved_pages import _read
from scripts import boat_first_p0_readback as readback
from scripts import boat_private_original_vault as vaultCLI
from scripts.boat_original_maintenance import protect_new_forecast_originals


class _Rejected(ValueError):
    """Keep private reader, parser and Git errors out of public job output."""


def _need(condition, reason):
    if not condition:
        raise _Rejected('FIRST_P0_RECONCILE_' + reason)


def _bootstrap(repo):
    config = _json(_read(repo/'audit/state/boat-saved-view-input.json', 8192), 8192)
    _need(type(config) is dict and set(config) == {
        'schema', 'bootstrap', 'bootstrap_sha256', 'catchup_artifact_id', 'catchup_sha256'}
        and config['schema'] == 'RACE_AI_SAVED_VIEW_INPUT_V1', 'FEED_CONFIG_INVALID')
    raw = base64.b64decode(config['bootstrap'], validate=True)
    _need(sha256(raw).hexdigest() == config['bootstrap_sha256'], 'FEED_BOOTSTRAP_HASH')
    return F.open_bootstrap(raw)


def _current_day(git, bootstrap, day):
    """Load an existing target day, or the latest view when adding a new day."""
    current = F.current_view(git, bootstrap)
    context = getattr(git, '_saved_history_context', None)
    if context and context['selected_day'] != day:
        try:
            return F.current_view(git, bootstrap, day=day)
        except ValueError as error:
            if str(error) != 'HISTORY_DAY_UNAVAILABLE':
                raise
            # current_view clears its context before attempting the requested
            # date. Restore the latest context for the existing V5 publisher.
            return F.current_view(git, bootstrap)
    return current


def _retained_captures(loaded, race_ids, now):
    """Read both existing indexes; never collect or modify their pointers."""
    state = loaded['state']
    before = digest([state.control, state.new_captures])
    captures = {}
    races = set()
    for name in ('results', 'settlement_captures'):
        pointers = state.control.get(name, {})
        _need(type(pointers) is dict, 'RESULT_INDEX_INVALID')
        for rid in sorted(race_ids & pointers.keys()):
            pointer = pointers[rid]
            _need(type(pointer) is dict and pointer.get('kind') == 'RESULT', 'RESULT_POINTER_INVALID')
            raw, receipt = state.capture(pointer)
            day = date.fromisoformat(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}')
            urls = {result_url(day.isoformat(), rid[9:11], int(rid[-2:])),
                    endpoint(day, rid[9:11], int(rid[-2:]), 'raceresult')}
            _need(receipt['source_url'] in urls and instant(receipt['captured_at']) <= now,
                  'RESULT_RECEIPT_INVALID')
            identity = digest({key: receipt[key] for key in (
                'source_url', 'source_sha256', 'captured_at')})
            _need(identity not in captures or captures[identity] == (raw, receipt),
                  'RESULT_CAPTURE_CONFLICT')
            captures[identity] = (raw, receipt)
            races.add(rid)
    _need(digest([state.control, state.new_captures]) == before, 'SOURCE_STATE_CHANGED')
    return [captures[key] for key in sorted(captures)], races, digest(sorted(captures))


def _no_live_artifact(_endpoint):
    raise _Rejected('FIRST_P0_RECONCILE_RETAINED_ORIGINAL_REQUIRED')


def _saved_program_names(files, view, day, now, registry):
    """Display-only fallback from exact retained official B bytes; zero provider GET.

    Only a verified same-day B archive and an exact race/lane/registration
    binding may fill a currently blank name. The forecast original is not
    changed. Unknown or conflicting evidence must never become a name.
    """
    missing = set()
    for row in view['records']:
        if row.get('sport') != 'boat' or row['event_date_jst'] != day:
            continue
        for person in row['participants']:
            pid = person['registration_no']
            if not person.get('name') and pid not in registry:
                missing.add((row['race_id'], person['number'], pid))
    if not missing:
        return {}
    metadata_file = files.get('metadata.json')
    if not metadata_file:
        return {}
    metadata = _json(_read(Path(metadata_file), runtime.FILE_LIMITS['metadata.json']),
                     runtime.FILE_LIMITS['metadata.json'])
    _need(type(metadata) is dict, 'PROGRAM_METADATA_INVALID')
    manifest = metadata.get('name_alias_sources')
    sources = []
    if manifest is not None:
        _need(type(manifest) is dict and
              set(manifest) == {'schema', 'b_sources'} and
              manifest['schema'] == 'RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1' and
              type(manifest['b_sources']) is list and
              len(manifest['b_sources']) <= 16 and
              all(type(entry) is dict for entry in manifest['b_sources']),
              'PROGRAM_MANIFEST_INVALID')
        sources = [entry for entry in manifest['b_sources'] if entry.get('day') == day]
    if not sources:
        # Some genuine model runtimes retain the B archive as the historical
        # seller input instead of the newer alias-source manifest. Recover
        # only from its original P0 document and independently checked receipt.
        seller = metadata.get('seller_official_source')
        if seller is not None:
            _need(type(seller) is dict, 'PROGRAM_SELLER_METADATA_INVALID')
            if seller.get('day') == day and files.get('p0-source.json'):
                from race_ai.boat_seller_inputs import official_b_cards_source
                import base64
                packet = _json(_read(Path(files['p0-source.json']),
                                     runtime.FILE_LIMITS['p0-source.json']),
                               runtime.FILE_LIMITS['p0-source.json'])
                _need(type(packet) is dict and set(packet) == {'document', 'receipt'},
                      'PROGRAM_P0_PACKET_INVALID')
                document, receipt = packet['document'], packet['receipt']
                encoded = seller.get('raw_b_base64')
                if encoded is None or encoded == '':
                    return {}
                _need(type(encoded) is str, 'PROGRAM_SELLER_BYTES_INVALID')
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError):
                    raise _Rejected('FIRST_P0_RECONCILE_PROGRAM_SELLER_BYTES_INVALID') from None
                # This existing validator verifies the official B URL,
                # archive/text SHA, actual physical P0 receipt and full
                # original roster. No network operation occurs.
                official_b_cards_source(raw, document, receipt, day=day,
                                        as_of=now.isoformat())
                sources = [dict(day=day, raw_b_base64=encoded,
                    source_url=document['source_url'],
                    source_sha256=document['source_sha256'],
                    captured_at=document['captured_at'])]
    if not sources:
        return {}
    from race_ai.boat_name_aliases import _b_programs
    races = {}
    # _b_programs reopens and hashes the stored original B bytes, verifies its
    # official URL, observation clock and day, then parses the actual program.
    verified = _b_programs(dict(schema='RACE_AI_BOAT_NAME_ALIAS_SOURCES_V1', b_sources=sources), now)
    for source, program in verified:
        for venue in program['venues']:
            for race in venue['races']:
                rid = race['race_id']
                for boat in race['boats']:
                    number, pid = boat['lane'], boat['racer_registration_id']
                    if (rid, number, pid) not in missing:
                        continue
                    name = boat.get('name')
                    _need(type(name) is str and bool(name.strip()),
                          'PROGRAM_NAME_INVALID')
                    item = dict(name=name, number=number, registration_no=pid,
                                source_url=source['source_url'],
                                source_sha256=source['source_sha256'],
                                captured_at=source.get('captured_at'))
                    per_race = races.setdefault(rid, {})
                    _need(pid not in per_race or per_race[pid] == item,
                          'PROGRAM_NAME_CONFLICT')
                    per_race[pid] = item
    return races



def _retained_result_names(captures, view, now):
    """Bind names ONLY to the exact race/lane/registration of saved official results.

    The existing parsed result includes six names and SHA-bound raw source
    receipts. An unsupported source does not supply names, and conflicting
    authentic observations stop the display update. No new provider GET.
    """
    from race_ai.racer_intraday_source import parse_result
    targets = {(row['race_id'], person['number'], person['registration_no'])
               for row in view['records'] if row.get('sport') == 'boat'
               for person in row['participants'] if not person.get('name')}
    if not targets:
        return {}, 0
    found = {}
    observed_registrations = {}
    conflicting_registrations = set()
    unsupported = 0
    for raw, receipt in captures:
        try:
            parsed = parse_result(raw, receipt, now=now)
        except ValueError:
            unsupported += 1
            continue
        if parsed.get('status') != 'CONFIRMED':
            continue
        rid = parsed['race_id']
        for observed in parsed['rows']:
            pid, lane = observed['racer_id'], observed['lane']
            prior = observed_registrations.get(pid)
            if prior is not None and prior['name'] != observed['name']:
                conflicting_registrations.add(pid)
            observed_registrations.setdefault(pid, dict(observed, source_race_id=rid))
            if (rid, lane, pid) not in targets:
                continue
            meta = dict(kind='SAME_RACE_RESULT', name=observed['name'],
                        number=lane, registration_no=pid, race_id=rid,
                        source_url=observed['source_url'],
                        source_sha256=observed['source_sha256'],
                        captured_at=observed['captured_at'])
            known = found.setdefault(rid, {})
            _need(pid not in known or known[pid]['name'] == meta['name'],
                  'RETAINED_RESULT_NAME_CONFLICT')
            # Never manufacture or silently revise an identity on another
            # observation. The first authenticated matching source is enough.
            known.setdefault(pid, meta)
    # A rider's registration is stable within one event day. Other races
    # from that same day may supply independently authenticated display text,
    # but cannot serve as a same-race proof. Keep their origin race explicit.
    for rid, lane, pid in sorted(targets):
        if pid in found.get(rid, {}) or pid in conflicting_registrations:
            continue
        observed = observed_registrations.get(pid)
        if not observed or observed['source_race_id'] == rid or observed['source_race_id'][:8] != rid[:8]:
            continue
        meta = dict(kind='SAME_DAY_OFFICIAL_RESULT', name=observed['name'],
                    number=lane, registration_no=pid, race_id=rid,
                    source_race_id=observed['source_race_id'],
                    source_url=observed['source_url'],
                    source_sha256=observed['source_sha256'],
                    captured_at=observed['captured_at'])
        found.setdefault(rid, {})[pid] = meta
    return found, unsupported


def _retained_names(repo, now, *, view=None, day=None, transport=None):
    """Read a verified TERM registry and optional exact saved B names."""
    pointer = _json(_read(repo/runtime.INPUT_PATH, 64*1024), 64*1024)
    with TemporaryDirectory(prefix='boat-first-p0-names-', dir=os.environ['RUNNER_TEMP']) as folder:
        restored = runtime.restore_runtime(pointer, repo, folder, transport=transport)
        documents, source = _term_names(restored['files']['racers.sqlite'], now)
        fields = ('verified', 'source_url', 'source_sha256', 'captured_at')
        registry = {pid: dict(name=document['name'], **{key: source[key] for key in fields})
                    for pid, document in documents.items()}
        races = (_saved_program_names(restored['files'], view, day, now, registry)
                 if view is not None and day is not None else {})
    return dict(registry=registry, races=races), dict(
        display_name_runtime_commit=restored['source_commit'],
        display_name_registry_source_sha256=source['source_sha256'] if source else None,
        display_name_program_races=len(races),
        display_name_program_candidates=sum(map(len, races.values())))


def _named_target(view, day, names):
    """Apply the existing display merger only to the selected day."""
    target = dict(view, records=[row for row in view['records'] if row['event_date_jst'] == day])
    enriched = append_views(target, names=names)
    by_race = {row['race_id']: row for row in enriched['records']}
    output = dict(view, records=[by_race.get(row['race_id'], row) for row in view['records']])
    _need(F.forecast_inventory(output) == F.forecast_inventory(view), 'DISPLAY_FORECAST_CHANGED')
    return output


def _name_counts(view, day, names):
    people = [person for row in view['records'] if row['event_date_jst'] == day
              for person in row['participants']]
    present = sum(bool(person.get('name')) for person in people)
    bound = 0
    for person in people:
        registration = person['registration_no']
        expected = names['registry'].get(registration)
        source = person.get('name_source') or {}
        if (expected and person.get('name') == expected['name']
                and source.get('kind') == 'VERIFIED_RACER_REGISTRY'
                and source.get('registration_no') == registration
                and all(source.get(key) == expected[key] for key in
                        ('verified', 'source_url', 'source_sha256', 'captured_at'))):
            bound += 1
    return dict(display_name_participants=len(people), display_name_present=present,
        display_name_registry_bound=bound, display_name_missing=len(people)-present)


def _score_counts(scored):
    """Project the native verdicts to counts/hashes, without forecast bodies."""
    verdicts = scored['per_forecast']
    states = Counter(item['state'] for item in verdicts)
    resolved = {'HIT', 'MISS', 'FULL_REFUND'}
    numeric = ('forecast_count', 'scored', 'hits', 'hit_rate', 'stake_yen',
               'received_yen', 'net_yen', 'roi', 'pending',
               'manshu_opportunities', 'manshu_hits')
    groups = [dict(model_id_sha256=sha256(item['model_id'].encode()).hexdigest(),
                   stage=item['stage'], **{key: item[key] for key in numeric})
              for item in scored['scoreboard']]
    return dict(scored_forecasts=scored['scored_forecasts'],
        scored_races=len({item['race_id'] for item in verdicts if item['state'] in ('HIT', 'MISS')}),
        held_forecasts=sum(count for state, count in states.items() if state not in resolved),
        void_forecasts=states['FULL_REFUND'], rejected_forecasts=states['RESULT_REJECTED'],
        native_verdict_counts=dict(sorted(states.items())), model_score_counts=groups,
        native_evaluation_sha256=digest(scored), scoring_performed=True)


def reconcile(repo, *, vault_commit, receipt_commit, day, p0_artifact,
              companion_artifacts, transport=None, receipt_get=None,
              feed_transport=None, intraday_transport=None, runtime_transport=None,
              now=None, include_verified_result_names=False):
    """Verify, replay retained results and append to the existing encrypted feed.

    Optional transports replace external Git/Contents I/O only. All private
    documents, official bodies and native score details remain in memory.
    """
    stage = 'READBACK'
    try:
        verified, document, rows, metadata = readback.verify(repo,
            vault_commit=vault_commit, receipt_commit=receipt_commit, day=day,
            p0_artifact=p0_artifact, companion_artifacts=companion_artifacts,
            transport=transport, receipt_get=receipt_get)
        repo = Path(repo).resolve()
        now = now or datetime.now(timezone.utc)
        _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        original_digest = digest([document, rows, metadata])
        stage = 'PROJECTION'
        documents = [dict(artifact_id=p0_artifact, member_name='forecasts.json',
                          member_sha256=verified['json_sha256'], document=document)]
        state = dict(schema='RACE_AI_PRIVATE_ARTIFACT_READBACK_V1', day_jst=day,
            rows=rows, receipts=[metadata], observations=[], original_documents=documents,
            complete=False, coverage_scope='EXPLICIT_ARTIFACTS_ONLY', excluded_repeats=[])
        state['state_sha256'] = digest(state)
        native_view = project_native_state(state, documents=documents)

        stage = 'SAVED_FEED'
        bootstrap = _bootstrap(repo)
        git = feed_transport or F.FeedRepository(repo)
        parent, previous, generation, before = _current_day(git, bootstrap, day)
        history = bool(getattr(git, '_saved_history_context', None))
        merged = append_views(before, [native_view])

        stage = 'DISPLAY_NAMES'
        names, name_proof = _retained_names(repo, now, view=merged, day=day, transport=runtime_transport)
        merged = _named_target(merged, day, names)

        stage = 'RETAINED_RESULTS'
        loaded = load_intraday(repo, transport=intraday_transport, now=now)
        source_digest = digest([loaded['state'].control, loaded['state'].new_captures])
        race_ids = {row['race_id'] for row in rows}
        captures, captured_races, capture_hash = _retained_captures(loaded, race_ids, now)
        if include_verified_result_names:
            stage = 'DISPLAY_RETAINED_RESULT_NAMES'
            found, unsupported = _retained_result_names(captures, merged, now)
            if found:
                merged = _named_target(merged, day, dict(registry={}, races=found))
            name_proof['display_name_result_races'] = len(found)
            name_proof['display_name_result_candidates'] = sum(map(len, found.values()))
            name_proof['display_name_result_cross_race_candidates'] = sum(
                item.get('kind') == 'SAME_DAY_OFFICIAL_RESULT'
                for names_for_race in found.values() for item in names_for_race.values())
            name_proof['display_name_result_unsupported_captures'] = unsupported
        native_results = F.update_view(native_view, [], captures=captures, synced_at=now.isoformat())
        captured_latest, _ = latest_result_observations([
            observation for row in native_results['records']
            for observation in row['result_observations']])
        after = F.update_view(merged, [], captures=captures, synced_at=now.isoformat())
        # The encrypted feed can contain a newer retained pending/rejected
        # observation. Keep that journal authoritative over an older final in
        # the main collector; only the exact verified P0 rows are evaluated.
        latest, _ = latest_result_observations([
            observation for row in after['records'] if row['race_id'] in race_ids
            for observation in row['result_observations']])
        _need(all(instant(item['captured_at']) <= now for item in latest),
              'RESULT_JOURNAL_FUTURE')
        capture_clocks = {item['race_id']: instant(item['captured_at']) for item in captured_latest}
        newer_saved = sum(item['race_id'] not in capture_clocks or
                          instant(item['captured_at']) > capture_clocks[item['race_id']]
                          for item in latest)
        stage = 'NATIVE_EVALUATION'
        counts = _score_counts(evaluate(rows, latest))
        _need(digest([document, rows, metadata]) == original_digest, 'ORIGINAL_CHANGED')
        _need(digest([loaded['state'].control, loaded['state'].new_captures]) == source_digest,
              'SOURCE_STATE_CHANGED')
        F.ensure_append_only(before, after)
        name_counts = _name_counts(after, day, names)

        stage = 'ORIGINAL_PROTECTION'
        protection = protect_new_forecast_originals(before, after, repo,
            github_get=_no_live_artifact, transport=transport, now=now)
        _need(protection.get('complete') is True and protection['newly_retained_originals'] == 0,
              'RETAINED_ORIGINAL_REQUIRED')
        # Replayed identical observations can update only the top-level sync
        # clock. Do not publish a redundant encrypted generation for that.
        changed = wire(before['records']) != wire(after['records'])
        published = dict(commit=parent, generation=generation, cipher_sha256=previous)
        if changed:
            stage = 'FEED_PUBLICATION'
            publication = dict(after, source_complete=False, coverage_scope='EXPLICIT_ARTIFACTS_ONLY')
            if history:
                # The existing V5 publisher accepts a subset of changed days
                # and retains all other descriptors. Do not copy this partial
                # day's metadata into the older day used to load the router.
                publication.update(event_date_jst=day,
                    records=[row for row in after['records'] if row['event_date_jst'] == day])
            published = F.publish_view(git, bootstrap, publication, parent=parent,
                                       previous=previous, generation=generation)
        source = loaded['previous']
        return dict(verified, **counts, **name_proof, **name_counts,
            status='FIRST_P0_RECONCILED' if counts['held_forecasts'] == 0 else 'HOLD_OFFICIAL_RESULTS_INCOMPLETE',
            coverage_scope='EXPLICIT_ARTIFACTS_ONLY', source_complete=False,
            retained_result_captures=len(captures), retained_result_races=len(captured_races),
            retained_capture_set_sha256=capture_hash,
            newer_saved_observation_races=newer_saved,
            native_result_observation_sha256=digest(latest),
            results_feed_source_commit=parent, results_feed_source_cipher_sha256=previous,
            results_source_commit=loaded['parent'], results_generation=source['head']['generation'],
            results_cipher_sha256=source['head']['cipher_sha256'],
            feed_changed=changed, feed_commit=published['commit'],
            feed_generation=published['generation'], feed_cipher_sha256=published['cipher_sha256'],
            original_document_set_sha256=original_digest, originals_unchanged=True,
            source_state_saved=False, forecast_rewrites=0, actual_purchases=False,
            auto_promoted=False, formal_model_superiority=False)
    except _Rejected:
        raise
    except Exception:
        raise _Rejected('FIRST_P0_RECONCILE_' + stage + '_REJECTED') from None


def main(argv=None, *, transport=None, receipt_get=None, feed_transport=None,
         intraday_transport=None, runtime_transport=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT))
    parser.add_argument('--vault-commit', required=True)
    parser.add_argument('--receipt-commit', required=True)
    parser.add_argument('--day', required=True)
    parser.add_argument('--p0-artifact', type=int, required=True)
    parser.add_argument('--companion-artifact', type=int, action='append', required=True)
    parser.add_argument('--include-verified-result-names', action='store_true',
                        help='Source-free display-only names from already retained exact official results')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        repo = vaultCLI._environment(args.repo_root)
        output = vaultCLI._private_path(args.output, repo, exists=False)
        report = reconcile(repo, vault_commit=args.vault_commit,
            receipt_commit=args.receipt_commit, day=args.day, p0_artifact=args.p0_artifact,
            companion_artifacts=args.companion_artifact, transport=transport,
            receipt_get=receipt_get, feed_transport=feed_transport,
            intraday_transport=intraday_transport, runtime_transport=runtime_transport,
            now=now, include_verified_result_names=args.include_verified_result_names)
        vaultCLI._write(output, V._wire(report) + b'\n')
        print(V._wire(report).decode('utf-8'))
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, _Rejected) else 'FIRST_P0_RECONCILE_OPERATION_REJECTED'
        print(V._wire(dict(status='FIRST_P0_RECONCILIATION_REJECTED', reason=reason,
            new_forecasts_created=0, provider_requests=0, plaintext_published=False)).decode('utf-8'))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
