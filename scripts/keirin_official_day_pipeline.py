"""Execute the existing A/B pipeline against actual official KEIRIN snapshots.

Only encrypted originals and aggregate-safe receipts may leave private runtime
storage. The full official cohort is independent of secondary page availability.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import base64
import json
import os
import re

from race_ai import keirin_dynamic_nationwide_registry as dynamic
from race_ai import keirin_nationwide_auto_generator as model
from scripts import keirin_capture_public_two_sources as capture

JST = timezone(timedelta(hours=9))
SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_DAY_PIPELINE_V1'


class OfficialPipelineError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise OfficialPipelineError(reason)


def reconcile_manifest(schedule, manifest):
    """Preserve every official race; source links determine capture readiness only."""
    need(type(schedule) is dict and type(schedule.get('races')) is list and
         type(manifest) is dict and type(manifest.get('races')) is list and
         schedule.get('day_jst') == manifest.get('day_jst'),
         'OFFICIAL_SECONDARY_DAY_MISMATCH')
    rows = schedule['races']
    official_ids = [r['race_id'] for r in rows]
    linked_ids = [r['race_id'] for r in manifest['races']]
    need(len(official_ids) == len(set(official_ids)) and
         len(linked_ids) == len(set(linked_ids)),
         'OFFICIAL_OR_SECONDARY_RACE_DUPLICATE')
    need(set(linked_ids) <= set(official_ids),
         'SECONDARY_RACE_OUTSIDE_OFFICIAL_COHORT')
    cutoffs = {r['race_id']: r['official_cutoff_at'] for r in rows}
    reconciled = dict(manifest, races=[
        dict(r, cutoff_hint=cutoffs[r['race_id']])
        for r in manifest['races']])
    capture.manifest_check(reconciled, registered_ids=official_ids)
    return reconciled, {
        'official_registered_races': len(rows),
        'source_linked_races': len(linked_ids),
        'missing_source_links': len(rows) - len(linked_ids),
    }


def build_registry(schedule):
    """Reparse saved official bytes, then register the complete official cohort."""
    from race_ai.keirin_official_cohort import build_registry as one_revision
    return one_revision(schedule)


def private_snapshot_json(value):
    """JSON encoding for an encrypted evidence payload, never a public report."""
    if isinstance(value, bytes):
        return {'encoding': 'base64', 'bytes': base64.b64encode(value).decode('ascii')}
    if isinstance(value, dict):
        return {k: private_snapshot_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [private_snapshot_json(v) for v in value]
    return value


def settle_collected(*, schedule, originals_by_race, official_records_by_race,
                     origin_packets_by_race, owner_private_pem, schedule_versions=None):
    """Join authenticated originals with independently acquired official bytes.

    All network I/O belongs to the caller's trusted acquisition boundary. This
    function reparses its source receipts and validates the GitHub server proof;
    a locally present ciphertext or an arbitrary normalized result is insufficient.
    Owner rows contain private predictions and MUST remain private or encrypted.
    """
    from race_ai import keirin_github_origin_evidence as origin
    from race_ai import keirin_nationwide_auto_settlement as settlement
    from race_ai import keirin_official_public_source as official
    from race_ai import keirin_official_cohort as cohort

    joined = cohort.build_registered_cohort([schedule] if schedule_versions is None else schedule_versions)
    need(joined['latest_schedule'] == schedule, 'OFFICIAL_CURRENT_SCHEDULE_LINEAGE_INVALID')
    registry, races = joined['registry'], joined['races_by_id']
    removed = set(joined['removed_race_ids'])
    need(all(type(value) is dict and set(value) <= set(races) for value in (
        originals_by_race, official_records_by_race, origin_packets_by_race)),
        'OFFICIAL_SETTLEMENT_INPUT_OUTSIDE_DAY')
    need(type(owner_private_pem) is bytes and bool(owner_private_pem),
         'OWNER_PRIVATE_KEY_REQUIRED')
    final_results, source_states = {}, {}
    for rid in races:
        if rid in removed:
            source_states[rid] = 'HOLD_RACE_REMOVED_FROM_LATEST_OFFICIAL_SCHEDULE'
            continue
        record = official_records_by_race.get(rid)
        state = 'HOLD_OFFICIAL_RESULT_NOT_COLLECTED'
        if record is not None:
            if (type(record) is not dict or record.get('race_id') != rid or
                    not official.reparse_race_result(record)):
                state = 'HOLD_OFFICIAL_SOURCE_RECEIPT_INVALID'
            else:
                state = record['state']
                result = record.get('result')
                if (state == 'OFFICIAL_FINAL' and type(result) is dict and
                        result.get('official_cutoff_at') ==
                        races[rid]['official_cutoff_at']):
                    final_results[rid] = result
                elif state == 'OFFICIAL_FINAL':
                    state = 'HOLD_OFFICIAL_CUTOFF_CHANGED'
        source_states[rid] = state

    proofs, origin_states = {}, {}
    sealed, expected = {}, {}
    for rid, original in originals_by_race.items():
        need(type(original) is dict and all(k in original for k in (
            'raw_cipher', 'cipher_sha256', 'producer_run_id', 'producer_commit')),
            'ORIGINAL_ARCHIVE_RECEIPT_REQUIRED')
        sealed[rid] = original['raw_cipher']
        expected[rid] = original['cipher_sha256']
        packet = origin_packets_by_race.get(rid)
        origin_states[rid] = 'HOLD_GITHUB_ORIGIN_EVIDENCE_NOT_AVAILABLE'
        if packet is None:
            continue
        try:
            need(type(packet) is dict and set(packet) == {'producer', 'readback'},
                 'GITHUB_EVIDENCE_PAIR_REQUIRED')
            if (rid == origin.UTSUNOMIYA_RACE and
                    original['producer_run_id'] == origin.UTSUNOMIYA_RUN and
                    original['producer_commit'] == origin.UTSUNOMIYA_COMMIT and
                    original['cipher_sha256'] == origin.UTSUNOMIYA_SHA):
                proof = origin.verify_known_utsunomiya_origin(
                    raw_cipher=original['raw_cipher'],
                    official_cutoff_at=races[rid]['official_cutoff_at'],
                    producer=packet['producer'], readback=packet['readback'])
            else:
                proof = origin.verify_origin_evidence(
                    race_id=rid, raw_cipher=original['raw_cipher'],
                    expected_cipher_sha256=original['cipher_sha256'],
                    official_cutoff_at=races[rid]['official_cutoff_at'],
                    expected_producer_run_id=original['producer_run_id'],
                    expected_producer_commit=original['producer_commit'],
                    producer=packet['producer'], readback=packet['readback'])
            proofs[rid] = proof
            origin_states[rid] = proof['state']
        except (origin.OriginEvidenceError, OfficialPipelineError,
                ValueError, TypeError, KeyError):
            origin_states[rid] = 'HOLD_GITHUB_ORIGIN_EVIDENCE_INVALID'

    def verify_original(rid, digest, raw):
        return (rid in proofs and expected.get(rid) == digest and
                type(raw) is bytes and
                sha256(raw).hexdigest() == digest and sealed.get(rid) == raw)

    def verify_cutoff(rid, manifest, result):
        return (rid in final_results and result is final_results[rid] and
                result['official_cutoff_at'] == races[rid]['official_cutoff_at'] and
                manifest['race_id'] == rid)

    def verify_result(rid, result):
        return rid in final_results and result is final_results[rid]

    report = settlement.settle_day(
        registry=registry, sealed_by_race=sealed, expected_sha_by_race=expected,
        final_results_by_race=final_results, owner_private_pem=owner_private_pem,
        independently_verify_immutable_origin=verify_original,
        independently_verify_official_cutoff=verify_cutoff,
        independently_verify_final_result=verify_result)
    report.update({
        'pipeline_schema': SCHEMA,
        'official_result_states': source_states,
        'original_proof_states': origin_states,
        'originals_present': len(originals_by_race),
        'originals_server_verified_before_cutoff': len(proofs),
        'official_final_results_verified': len(final_results),
        'registered_cohort_scope': registry['registered_cohort_scope'],
        'active_official_races': len(joined['active_race_ids']),
        'removed_official_races_held': len(removed),
        'missing_originals': len(races) - len(originals_by_race),
        'originals_not_loaded_for_audit': len(races) - len(originals_by_race),
        'evidence_scope_note': 'この画面で復号・検証できた原本を集計しています。予測なしは、この集計に原本が読み込まれていない状態です。',
    })
    status_by_race = {r['race_id']: r['state'] for r in report['statuses']}
    owner_rows = []
    for entry in registry['races']:
        rid = entry['race_id']
        arms = {'A': None, 'B': None}
        if rid in sealed:
            try:
                _, forecast, _ = settlement.decrypt_original_pair(
                    raw_cipher=sealed[rid], expected_cipher_sha256=expected[rid],
                    owner_private_pem=owner_private_pem)
                arms = {role: forecast[role] for role in ('A', 'B')}
            except (ValueError, TypeError, KeyError):
                pass
        owner_rows.append({
            'race_id': rid, 'venue': entry['venue'], 'race_no': entry['race_no'],
            'official_cutoff_at': races[rid]['official_cutoff_at'],
            'state': status_by_race[rid], **arms,
            'result': final_results.get(rid),
        })
    return report, owner_rows, proofs


def restore_private_snapshot_json(value):
    if type(value) is dict:
        if set(value) == {'encoding', 'bytes'} and value['encoding'] == 'base64':
            try:
                need(type(value['bytes']) is str, 'PRIVATE_BINARY_ENCODING_INVALID')
                return base64.b64decode(value['bytes'], validate=True)
            except (ValueError, TypeError):
                raise OfficialPipelineError('PRIVATE_BINARY_ENCODING_INVALID') from None
        return {key: restore_private_snapshot_json(item) for key, item in value.items()}
    if type(value) is list:
        return [restore_private_snapshot_json(item) for item in value]
    return value


def evidence_fingerprint(value):
    """Identical provider bytes observed again do not create a false revision."""
    def stable(item):
        if type(item) is dict:
            return {key: stable(val) for key, val in item.items()
                    if key not in {'observed_at', 'source_observed_at', 'source_available_at'}}
        if type(item) is list:
            return [stable(val) for val in item]
        return item
    return model.digest(stable(private_snapshot_json(value)))


def result_content_fingerprint(record):
    # The first observation has no parent; rereading the very same official
    # result supplies that accepted result as parent. It is still one result
    # revision. Source bytes/state/result fields remain part of this identity.
    provenance = {key: value for key, value in record['provenance'].items()
                  if key not in {'previous_result', 'revision_relationship'}}
    return evidence_fingerprint(dict(record, provenance=provenance))


def official_fetcher(repo, clock, *, fetch=None):
    """One bounded poll; explicit source opt-in is distinct from source accuracy.

    The observed official robots policy excludes the JSON endpoint. Deployment
    must establish an approved automated source route before setting this flag;
    the flag itself is not evidence of provider permission.
    """
    from race_ai import keirin_official_public_source as official
    from race_ai import keirin_github_provider_stop as stop
    if fetch is None:
        need(os.getenv('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED') == 'true',
             'OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED')
        fetch = official._http_get
    cache, stopped = {}, None

    def get(url):
        nonlocal stopped
        if stopped is not None:
            raise stopped
        if url in cache:
            return cache[url]
        try:
            raw = fetch(url)
        except official.OfficialProviderStop as exc:
            stopped = exc
            stop.record_denial(repo=repo, code='PROVIDER_DENIED_OR_RATE_LIMITED_STOP',
                               observed_at=clock().astimezone(timezone.utc).isoformat())
            raise
        except official.OfficialSourceError as exc:
            # A broken transport is not a request to probe other race URLs.
            stopped = exc
            code = ('PUBLIC_PROVIDER_HTTP_ERROR_STOP' if str(exc).startswith('OFFICIAL_HTTP_')
                    else 'PUBLIC_PROVIDER_UNAVAILABLE_STOP')
            stop.record_denial(repo=repo, code=code,
                               observed_at=clock().astimezone(timezone.utc).isoformat())
            raise
        cache[url] = raw
        return raw
    return get


def select_result_races(schedule, records, originals, now, *, max_races=8, poll_cursor=None):
    need(type(max_races) is int and 1 <= max_races <= 8 and
         isinstance(now, datetime) and now.utcoffset() is not None,
         'OFFICIAL_RESULT_BUDGET_OR_CLOCK_INVALID')
    ready = [row['race_id'] for row in schedule['races']
             if row['official_cutoff_at'] is not None and
             model.when(row['official_cutoff_at']) < now]
    # Every bucket rotates; an unsettled/withdrawn early race cannot starve
    # later races. Completed races retain a reserved correction-check slot.
    pending_original = sorted(rid for rid in ready if rid in originals and
                              records.get(rid, {}).get('state') != 'OFFICIAL_FINAL')
    pending_other = sorted(rid for rid in ready if rid not in originals and
                           records.get(rid, {}).get('state') != 'OFFICIAL_FINAL')
    completed = sorted(rid for rid in ready
                       if records.get(rid, {}).get('state') == 'OFFICIAL_FINAL')
    need(poll_cursor is None or
         (type(poll_cursor) is int and 0 <= poll_cursor <= 10**9),
         'OFFICIAL_RESULT_POLL_CURSOR_INVALID')
    slot = int(now.timestamp()) // 600 if poll_cursor is None else poll_cursor

    def rotate(items, width, phase=slot):
        if not items:
            return []
        offset = (phase * width) % len(items)
        return items[offset:] + items[:offset]

    if max_races == 1 and completed and (pending_original or pending_other):
        bucket = completed if slot % 2 == 0 else pending_original + pending_other
        return rotate(bucket, 1, slot // 2)[:1]
    reserve = 1 if completed and (pending_original or pending_other) and max_races > 1 else 0
    selected = rotate(pending_original + pending_other,
                      max_races - reserve)[:max_races - reserve]
    remaining = max_races - len(selected)
    return selected + rotate(completed, remaining)[:remaining]


def read_originals(repo, day):
    from race_ai import keirin_nationwide_cipher_history as archive
    repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(repo)
    prefix = f'{archive.ROOT}/{day}/'
    _, paths = archive._cmd(repo, 'ls-tree', '-r', '--name-only', head, '--', prefix)
    originals, named = {}, set(paths.splitlines())
    for path in sorted(named):
        need(path.startswith(prefix), 'ORIGINAL_ARCHIVE_DAY_PATH_INVALID')
        if path.endswith('.receipt.json'):
            continue
        need(path.endswith('.sealed.json'), 'ORIGINAL_ARCHIVE_UNKNOWN_FILE')
        rid = path[len(prefix):-len('.sealed.json')]
        need(re.fullmatch(r'20[0-9]{10}', rid) is not None and
             rid[:8] == day.replace('-', ''), 'ORIGINAL_ARCHIVE_RACE_DAY_INVALID')
        sealed_path, receipt_path = archive._refs(rid)
        need(receipt_path in named, 'ORIGINAL_ARCHIVE_RECEIPT_MISSING')
        metadata = archive.read_blob_bytes(repo, head, receipt_path, max_bytes=16384)
        need(metadata is not None, 'ORIGINAL_ARCHIVE_RECEIPT_MISSING')
        receipt = json.loads(metadata)
        checked = archive._read_at(repo, head, rid, receipt['cipher_sha256'])
        raw = archive.read_blob_bytes(repo, head, sealed_path)
        originals[rid] = {key: checked[key] for key in (
            'cipher_sha256', 'producer_run_id', 'producer_commit')}
        originals[rid]['raw_cipher'] = raw
    need(len(named) == 2 * len(originals), 'ORIGINAL_ARCHIVE_ORPHAN_RECEIPT')
    return originals


def load_day_evidence(repo, day, owner_private_pem):
    """Replay every encrypted delta; a corrupt prior state is never reset."""
    from race_ai import keirin_official_public_source as official
    from race_ai import keirin_official_run_history as history
    state = {'schedule': None, 'schedule_versions': [],
             'official_records': {}, 'accepted_results': {},
             'origin_run_bundles': {},
             'safe_report': None, 'revision_receipts': [], 'cohort_state': None}
    for saved in history.read_revisions(repo=repo, day=day):
        payload = restore_private_snapshot_json(history.decrypt_evidence(
            saved['raw_cipher'], owner_private_pem))
        need(payload.get('schema') == 'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1' and
             payload.get('day_jst') == day and payload.get('kind') in (
                 'OFFICIAL_SCHEDULE', 'OFFICIAL_SETTLEMENT'),
             'OFFICIAL_HISTORY_PAYLOAD_CONTRACT_INVALID')
        schedule = payload.get('schedule')
        if schedule is not None:
            need(schedule.get('day_jst') == day and official.reparse_day_schedule(schedule),
                 'OFFICIAL_HISTORY_SCHEDULE_INVALID')
            if (not state['schedule_versions'] or evidence_fingerprint(schedule) !=
                    evidence_fingerprint(state['schedule_versions'][-1])):
                state['schedule_versions'].append(schedule)
        records = payload.get('official_records', {})
        bundles = payload.get('origin_run_bundles', {})
        need(type(records) is dict and type(bundles) is dict,
             'OFFICIAL_HISTORY_DELTA_INVALID')
        for rid, record in records.items():
            need(rid[:8] == day.replace('-', '') and record.get('race_id') == rid and
                 official.reparse_race_result(record), 'OFFICIAL_HISTORY_RESULT_INVALID')
            need(record['provenance'].get('previous_result') ==
                 state['accepted_results'].get(rid),
                 'OFFICIAL_HISTORY_RESULT_LINEAGE_MISMATCH')
            state['official_records'][rid] = record
            if record['state'] == 'OFFICIAL_FINAL':
                state['accepted_results'][rid] = record['result']
        for run, packet in bundles.items():
            need(re.fullmatch(r'[1-9][0-9]{0,17}', run) is not None and
                 type(packet) is dict and set(packet) == {'producer', 'readback'},
                 'OFFICIAL_HISTORY_GITHUB_BUNDLE_INVALID')
            if run in state['origin_run_bundles']:
                need(evidence_fingerprint(state['origin_run_bundles'][run]) ==
                     evidence_fingerprint(packet), 'OFFICIAL_HISTORY_ORIGIN_CHANGED')
            state['origin_run_bundles'][run] = packet
        if payload['kind'] == 'OFFICIAL_SETTLEMENT':
            state['safe_report'] = payload['safe_report']
        state['revision_receipts'].append(saved['receipt'])
    if state['schedule_versions']:
        from race_ai import keirin_official_cohort as cohort
        joined = cohort.build_registered_cohort(state['schedule_versions'])
        state['schedule'] = joined['latest_schedule']
        state['cohort'] = joined
        need(set(state['official_records']) <= set(joined['races_by_id']),
             'OFFICIAL_HISTORY_RESULT_OUTSIDE_REGISTERED_COHORT')
        if joined['removed_race_ids']:
            state['cohort_state'] = 'HOLD_OFFICIAL_COHORT_SHRINK_REVIEW'
    return state


def persist_delta(*, repo, day, payload, owner_public_pem, clock):
    from race_ai import keirin_official_run_history as history
    safe = payload['safe_report']
    raw = history.seal_evidence(private_snapshot_json(payload), owner_public_pem,
                               day, clock().astimezone(timezone.utc).isoformat())
    return history.append_revision(repo=repo, day=day, raw_cipher=raw, safe_report=safe)


def run_capture(*, day, repo, private_root, owner_public_path, max_races=8, clock=None):
    from race_ai import keirin_official_public_source as official
    from race_ai import keirin_official_run_history as history
    from scripts import keirin_github_only_ab_day as live
    from scripts import keirin_register_public_day as registration
    clock = clock or (lambda: datetime.now(timezone.utc))
    need(clock().astimezone(JST).date().isoformat() == day,
         'NO_RETROSPECTIVE_OR_FUTURE_DAY_FORECAST')
    from race_ai import keirin_nationwide_auto_storage as storage
    key_path = Path(owner_public_path)
    need(key_path.is_file() and not key_path.is_symlink(),
         'EXISTING_OWNER_PUBLIC_KEY_REQUIRED')
    storage.checked_public_key(key_path.read_bytes())
    need(type(max_races) is int and 1 <= max_races <= 8,
         'OFFICIAL_CAPTURE_BUDGET_INVALID')
    root = live.private_root(private_root)
    # Existing Git state and denial markers are checked before any provider GET.
    live.archived_day(repo, day)
    get_official = official_fetcher(repo, clock)
    schedule = official.fetch_day_schedule(day, fetcher=get_official, clock=clock)
    registry = build_registry(schedule)
    schedule_report = {'schema': SCHEMA, 'kind': 'OFFICIAL_SCHEDULE', 'day_jst': day,
        'registered_races': len(schedule['races']),
        'official_schedule_content_sha256': evidence_fingerprint(schedule)}
    # The stable report hash permits deduplication without giving the capture
    # runner the owner's private RSA key.
    report_sha = sha256(history._canonical(schedule_report)).hexdigest()
    prior = history.read_revisions(repo=repo, day=day)
    if not any(row['receipt']['report_sha256'] == report_sha for row in prior):
        persist_delta(repo=repo, day=day, payload={
            'schema': 'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1',
            'kind': 'OFFICIAL_SCHEDULE', 'day_jst': day, 'schedule': schedule,
            'safe_report': schedule_report},
            owner_public_pem=Path(owner_public_path).read_bytes(), clock=clock)
    if not schedule['races']:
        return {'schema': live.SCHEMA, 'day_jst': day,
            'national_universe_verified': True, 'observed_races': 0,
            'official_registered_races': 0, 'source_linked_races': 0,
            'missing_source_links': 0, 'new_A_B_sealed': 0,
            'new_A_B_git_archived': 0, 'new_encrypted_originals': [],
            'state': 'OFFICIAL_EMPTY_DAY_VERIFIED',
            'no_plaintext_forecast_uploaded': True}
    secondary_get = live.guarded_provider_fetch(repo, clock)
    _, manifest, status = registration.register_day(
        day_jst=day, private_raw_dir=root / 'raw', fetch=secondary_get, clock=clock)
    manifest, coverage = reconcile_manifest(schedule, manifest)
    report = live.run_day(day=day, workspace=repo, private_dir_path=root,
        owner_public_pem=owner_public_path, max_races=max_races, clock=clock,
        registration_data=(registry, manifest, status), fetch=secondary_get)
    report.update(coverage)
    report['national_universe_verified'] = registry['nationwide_coverage_independently_verified']
    report['official_schedule_content_sha256'] = evidence_fingerprint(schedule)
    return report


def check_owner_private_key(owner_private_pem):
    """Validate the existing RSA key before any provider or GitHub request."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from race_ai import keirin_nationwide_auto_storage as storage
    need(type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 20000,
         'EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED')
    try:
        key = serialization.load_pem_private_key(owner_private_pem, password=None)
    except (ValueError, TypeError):
        raise OfficialPipelineError('EXISTING_OWNER_PRIVATE_SECRET_INVALID') from None
    need(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 3072,
         'EXISTING_OWNER_RSA_PRIVATE_SECRET_REQUIRED')
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    storage.checked_public_key(public)
    return public


def run_settlement(*, day, repo, private_root, owner_public_path,
                   owner_private_pem, max_races=8, clock=None,
                   collect_official=True, github_client=None, shared_official_fetch=None):
    from race_ai import keirin_github_evidence_client as github
    from race_ai import keirin_official_public_source as official
    from race_ai import keirin_github_provider_stop as stop
    from race_ai import keirin_official_owner_report as owner
    from race_ai import keirin_official_cohort as cohort
    from race_ai import keirin_official_poll_progress as progress
    from scripts import keirin_github_only_ab_day as live
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    check_owner_private_key(owner_private_pem)
    need(type(max_races) is int and 1 <= max_races <= 8,
         'OFFICIAL_RESULT_BUDGET_OR_CLOCK_INVALID')
    need(day <= now.astimezone(JST).date().isoformat(), 'RESULT_FUTURE_DAY_INVALID')
    root = live.private_root(private_root)
    saved = load_day_evidence(repo, day, owner_private_pem)
    progress_before = progress.read_day(repo=repo, day=day) or {}
    originals = read_originals(repo, day)
    schedule = saved['schedule']
    versions = list(saved['schedule_versions'])
    records = dict(saved['official_records'])
    cursor = progress_before.get('result_poll_cursor', 0)
    origin_cursor = progress_before.get('origin_poll_cursor', 0)
    need(all(type(value) is int and 0 <= value <= 10**9
             for value in (cursor, origin_cursor)), 'OFFICIAL_POLL_CURSOR_INVALID')
    selected = []
    provider_state = saved['cohort_state']
    stopped = stop.read_for_observed_day(repo=repo, day=now.astimezone(JST).date().isoformat())
    if collect_official and stopped is None:
        get = shared_official_fetch or official_fetcher(repo, clock)
        try:
            current = official.fetch_day_schedule(day, fetcher=get, clock=clock)
            if not versions or evidence_fingerprint(current) != evidence_fingerprint(versions[-1]):
                versions.append(current)
            schedule = versions[-1]
            joined = cohort.build_registered_cohort(versions)
            provider_state = ('HOLD_OFFICIAL_COHORT_SHRINK_REVIEW'
                              if joined['removed_race_ids'] else None)
            selected = select_result_races(schedule, records, originals, now,
                                           max_races=max_races, poll_cursor=cursor)
            for rid in selected:
                previous = saved['accepted_results'].get(rid)
                records[rid] = official.fetch_race_result(
                    rid, schedule=schedule, fetcher=get, clock=clock, previous_result=previous)
        except official.OfficialSourceError:
            provider_state = 'HOLD_OFFICIAL_PROVIDER_STOPPED_THIS_POLL'
    elif stopped is not None:
        provider_state = 'HOLD_PROVIDER_PREVIOUS_DENIAL_NO_RETRY'
    need(schedule is not None, 'OFFICIAL_SCHEDULE_NOT_AVAILABLE')
    joined = cohort.build_registered_cohort(versions)
    need(set(originals) <= set(joined['races_by_id']),
         'RESTORED_ORIGINAL_OUTSIDE_OFFICIAL_COHORT')
    # Preserve the first trusted API/ZIP acquisition in encrypted Git before
    # artifact expiry. Later runs revalidate it against the exact original.
    bundles = dict(saved['origin_run_bundles'])
    client = github_client or github.GitHubEvidenceClient()
    missing_runs = sorted({r['producer_run_id'] for r in originals.values()} - set(bundles))
    if missing_runs:
        offset = (origin_cursor * 8) % len(missing_runs)
        missing_runs = (missing_runs[offset:] + missing_runs[:offset])[:8]
    selected_runs = missing_runs if client.stopped_reason is None else []
    for run in selected_runs:
        try:
            bundles[run] = client.read_run_bundle(run)
        except github.GitHubEvidenceError:
            if client.stopped_reason is not None:
                break
    packets = {rid: bundles[original['producer_run_id']] for rid, original in originals.items()
               if original['producer_run_id'] in bundles}
    report, rows, proofs = settle_collected(schedule=schedule, originals_by_race=originals,
        official_records_by_race=records, origin_packets_by_race=packets,
        owner_private_pem=owner_private_pem, schedule_versions=versions)
    if provider_state is not None:
        report['provider_state'] = provider_state
    if client.stopped_reason is not None:
        report['github_evidence_state'] = client.stopped_reason
    changed_records = {rid: record for rid, record in records.items()
        if rid not in saved['official_records'] or result_content_fingerprint(record) !=
           result_content_fingerprint(saved['official_records'][rid])}
    new_bundles = {run: bundle for run, bundle in bundles.items()
                   if run not in saved['origin_run_bundles']}
    changed_schedule = (saved['schedule'] is None or evidence_fingerprint(schedule) !=
                        evidence_fingerprint(saved['schedule']))
    if (changed_records or new_bundles or changed_schedule or
            report != saved['safe_report']):
        payload = {'schema': 'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DELTA_V1',
            'kind': 'OFFICIAL_SETTLEMENT', 'day_jst': day, 'safe_report': report,
            'official_records': changed_records, 'origin_run_bundles': new_bundles,
            'origin_receipts': proofs}
        if changed_schedule:
            payload['schedule'] = schedule
        persist_delta(repo=repo, day=day, payload=payload,
            owner_public_pem=Path(owner_public_path).read_bytes(), clock=clock)
    if selected or selected_runs:
        at = clock().astimezone(timezone.utc).isoformat()
        operation = model.digest({'day_jst': day, 'observed_at': at,
            'result_cursor_before': cursor, 'origin_cursor_before': origin_cursor,
            'selected_race_ids': selected, 'selected_origin_run_ids': selected_runs,
            'run_id': os.getenv('GITHUB_RUN_ID'), 'attempt': os.getenv('GITHUB_RUN_ATTEMPT')})
        progress.advance_day(repo=repo, day=day, result_delta=int(bool(selected)),
            origin_delta=int(bool(selected_runs)), operation_id=operation, observed_at=at)
    html = owner.render_private_report(report, rows)
    capture._write_once(root / 'owner-report.html', html.encode('utf-8'))
    from race_ai import keirin_official_run_history as history
    owner_snapshot = history.seal_evidence({
        'schema': 'RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DAY_V1', 'day_jst': day,
        'safe_report': report, 'owner_rows': rows},
        Path(owner_public_path).read_bytes(), day, clock().astimezone(timezone.utc).isoformat())
    capture._write_once(root / 'owner-view.sealed.json', owner_snapshot)
    return report


def public_failure(exc):
    reason = str(exc)
    if re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}', reason) is None:
        reason = 'OFFICIAL_PIPELINE_SOURCE_KEY_OR_HISTORY_UNAVAILABLE'
    return 'HOLD_' + reason


def run_settlement_days(*, repo, private_root, owner_public_path, owner_private_pem,
                        max_races=8, clock=None, collect_official=True):
    """One process/client for today's, yesterday's and one older cohort.

    A GitHub refusal remains latched across days. A failure to persist a
    provider refusal terminates the batch rather than starting another client.
    """
    from race_ai import keirin_github_evidence_client as github
    from scripts import keirin_github_only_ab_day as live
    from scripts import keirin_official_backlog_days as backlog
    clock = clock or (lambda: datetime.now(timezone.utc))
    check_owner_private_key(owner_private_pem)
    root = live.private_root(private_root)
    days = backlog.select_days(clock(), backlog.discover_days(repo))
    client = github.GitHubEvidenceClient()
    get = official_fetcher(repo, clock) if collect_official else None
    summaries, held = [], 0
    for day in days:
        day_root = root / day
        day_root.mkdir(mode=0o700)
        fatal = False
        try:
            report = run_settlement(day=day, repo=repo, private_root=day_root,
                owner_public_path=owner_public_path, owner_private_pem=owner_private_pem,
                max_races=max_races, clock=clock, collect_official=collect_official,
                github_client=client, shared_official_fetch=get)
            if report.get('provider_state') or report.get('github_evidence_state'):
                held += 1
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            report = {'schema': SCHEMA, 'day_jst': day, 'state': public_failure(exc)}
            held += 1
            fatal = isinstance(exc, RuntimeError)
        capture._write_once(day_root / 'safe.json',
            (json.dumps(report, ensure_ascii=False, sort_keys=True)+'\n').encode('utf-8'))
        summaries.append({key: report[key] for key in (
            'day_jst', 'state', 'registered_races', 'paired_A_B_scored',
            'originals_server_verified_before_cutoff', 'provider_state',
            'github_evidence_state') if key in report})
        if fatal:
            break
    return {'schema': SCHEMA, 'day_jst': clock().astimezone(JST).date().isoformat(),
        'state': 'HOLD_SELECTED_DAY_UNAVAILABLE' if held else 'SELECTED_DAYS_PROCESSED',
        'days_selected': days, 'days_completed': len(summaries) - held,
        'days_held': held, 'days_not_attempted': len(days) - len(summaries),
        'day_reports': summaries, 'github_evidence_state': client.stopped_reason}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('capture', 'settle', 'settle-days'))
    parser.add_argument('--day', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--max-races', type=int, default=8)
    parser.add_argument('--saved-only', action='store_true')
    args = parser.parse_args(argv)
    out = Path(args.report)
    try:
        need((args.command == 'settle-days' and args.day == 'auto') or
             re.fullmatch(r'20[0-9]{2}-[0-9]{2}-[0-9]{2}', args.day) is not None,
             'OFFICIAL_DAY_INVALID')
        need(out.is_absolute() and out.parent.is_dir() and
             not out.exists() and not out.is_symlink(), 'NEW_REPORT_PATH_REQUIRED')
        if args.command == 'capture':
            need(not args.saved_only, 'CAPTURE_REQUIRES_CURRENT_SOURCE')
            report = run_capture(day=args.day, repo=Path(args.repo),
                private_root=Path(args.private_root), owner_public_path=args.owner_public_pem,
                max_races=args.max_races)
        else:
            key = os.environ.get('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode('utf-8')
            need(bool(key), 'EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED')
            common = dict(repo=Path(args.repo), private_root=Path(args.private_root),
                owner_public_path=args.owner_public_pem, owner_private_pem=key,
                max_races=args.max_races, collect_official=not args.saved_only)
            report = (run_settlement_days(**common) if args.command == 'settle-days'
                      else run_settlement(day=args.day, **common))
        raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()
        capture._write_once(out, raw)
        # No provider documents, predictions, PEMs or raw exception values.
        print(json.dumps({key: report[key] for key in (
            'schema', 'day_jst', 'registered_races', 'observed_races',
            'new_A_B_sealed', 'new_A_B_git_archived', 'paired_A_B_scored',
            'originals_server_verified_before_cutoff', 'provider_state',
            'state', 'days_completed', 'days_held', 'days_not_attempted',
            'github_evidence_state') if key in report}))
        return 2 if report.get('days_held', 0) else 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        failure = {'schema': SCHEMA, 'day_jst': args.day, 'state': public_failure(exc)}
        if out.is_absolute() and out.parent.is_dir() and not out.exists() and not out.is_symlink():
            try:
                capture._write_once(out, (json.dumps(failure)+'\n').encode('utf-8'))
            except (ValueError, OSError):
                pass
        print(json.dumps(failure))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
