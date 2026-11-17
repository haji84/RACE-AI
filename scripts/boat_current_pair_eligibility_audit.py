"""Count authenticated current BOAT native records; never score or qualify G8.

Called inside the existing trusted main audit, with its frozen API reader and
clock. Private originals stay in the existing AES readers and local memory.
Raw official qualification and a prospective sample policy are not audited here.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re


def _need(value):
    if not value:
        raise ValueError('CURRENT_PAIR_AUDIT_REJECTED')


def _scope(get, run_id, now, source):
    from scripts import boat_owner_active_snapshot_audit as active
    from race_ai import boat_all_model_recovery as recovery
    from race_ai.cycle_recovery import artifact_pages
    from race_ai.actions_contract import digest
    source = active._expected_source(source)
    reads = active._Reads(get)
    run = recovery._run(reads(f'actions/runs/{run_id}'), run_id, now)
    listing = artifact_pages(reads, run_id)
    allow_completed = source in active.PARTIAL_RECEIPT_OWNER_SHAS
    control = active._final_control(reads, run, listing, now) if allow_completed and run['status'] == 'completed' else None
    job, rounds = active._jobs(reads, run, now, expected_owner_sha=source,
        completed_round_limit=control['completed_round'] if control else None)
    scope = dict(schema=active.SCHEMA, run=run, job=job, rounds=rounds, inventory=listing,
        inventory_sha256=digest(listing), captured_at=now.isoformat(), expected_owner_sha=source,
        allow_completed_receipts=allow_completed, final_control=control)
    if allow_completed:
        scope['all_model_archive_scope'] = active._model_archive_scope(listing, run_id, rounds, now)
    active.validate_active_scope(scope, run, listing, now, reads, expected_owner_sha=source,
                                 allow_completed_receipts=allow_completed)
    return active, reads, scope


def _audit(get, run_id, now, source):
    from race_ai.actions_contract import canonical, digest
    from race_ai.boat_pdca_state import state_key
    from race_ai import boat_all_model_recovery as recovery
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact, MAX_ARCHIVE_BYTES
    from race_ai.all_existing_model_pairs import record_identity
    from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
    from race_ai.frozen_day_cycle import official_id
    _need(type(run_id) is int and 0 < run_id < 10**20 and type(now) is datetime and now.utcoffset() is not None)
    state_key('production')
    active, reads, scope = _scope(get, run_id, now, source)
    run, job, rounds, listing = (scope[key] for key in ('run', 'job', 'rounds', 'inventory'))
    day = active._time(run['created_at']).astimezone(timezone(timedelta(hours=9))).date().isoformat()
    items = {item['id']: item for item in listing}
    provenance = {}

    def read(item, limit):
        ident = item['id']; _need(type(ident) is int and ident > 0)
        metadata_raw = reads(f'actions/artifacts/{ident}')
        metadata, _ = recovery._metadata(metadata_raw, item, run, now, reads)
        _need(type(metadata.get('id')) is int and type(metadata.get('size_in_bytes')) is int
              and 0 < metadata['size_in_bytes'] <= limit)
        raw = reads(f'actions/artifacts/{ident}/zip')
        _need(type(raw) is bytes and 0 < len(raw) <= limit and metadata['size_in_bytes'] == len(raw)
              and metadata['digest'] == 'sha256:'+sha256(raw).hexdigest()
              and active._time(run['created_at']) <= active._time(metadata['created_at']) <= now)
        provenance[ident] = (sha256(metadata_raw).hexdigest(), sha256(raw).hexdigest())
        return raw, metadata

    def in_round(metadata, number):
        step = next(step for step in job['steps'] if step.get('name') == f'Deadline-ordered five-model round {number:02}')
        _need(active._time(step['started_at']) <= active._time(metadata['created_at']) <= active._time(step['completed_at']))

    selected = {}; excluded = 0
    prefix = f'all-existing-model-pairs-{run_id}-'
    for item in listing:
        name = item.get('name', '')
        if not name.startswith(prefix):
            continue
        match = re.fullmatch(re.escape(prefix)+r'([1-9][0-9]*)', name)
        _need(match is not None)
        number = int(match[1]); _need(number not in selected)
        if number in rounds:
            selected[number] = item
        else:
            excluded += 1

    result = dict(current_pair_audit_schema='RACE_AI_CURRENT_NATIVE_PAIR_ELIGIBILITY_COUNTS_V1',
        current_pair_audit_status='HOLD_G8_UNQUALIFIED', current_pair_authenticated=False,
        current_pair_owner_run_id=run_id, current_pair_owner_source_commit=source,
        current_pair_inventory_sha256=scope['inventory_sha256'], current_pair_scope_sha256=digest(scope),
        current_pair_completed_round_count=len(rounds), current_pair_archive_count=len(selected),
        current_pair_missing_archive_round_count=len(set(rounds)-set(selected)), current_pair_excluded_archive_count=excluded,
        current_pair_forecast_record_count=None, current_pair_input_only_record_count=None,
        current_pair_first_forecast_record_count=None, current_pair_repeat_forecast_record_count=None,
        current_pair_distinct_race_count=None, current_pair_input_only_distinct_race_count=None,
        current_pair_training_archive_count=None, current_pair_result_archive_count=None,
        current_pair_result_unique_revision_count=None, current_pair_result_duplicate_revision_count=None,
        current_pair_producer_journal_settled_join_count=None, current_pair_producer_journal_pending_join_count=None,
        current_pair_producer_journal_special_join_count=None, current_pair_producer_journal_missing_join_count=None,
        current_pair_producer_journal_joined_race_count=None,
        current_pair_official_raw_verified=None, current_pair_official_cutoff_verified=None, current_pair_minimum_cohort=None,
        current_pair_official_source_status='UNKNOWN_HOLD', current_pair_evaluation_minimum_status='UNREGISTERED_HOLD',
        current_pair_result_scope='NOT_READ',
        current_pair_qualifying_g8_count=0, current_pair_qualifying_g8_denominator=None,
        current_pair_accuracy_improvement_proven=False, current_pair_promotion_allowed=False,
        current_pair_full_day_coverage=False, current_pair_new_forecasts=0, current_pair_source_requests=0)
    if not selected:
        return dict(result, current_pair_audit_status='HOLD_NO_PAIR_ARCHIVES')

    first = {}; input_races = set(); training_ids = set(); training_hashes = set()
    forecasts = 0; input_only = 0
    for number, item in sorted(selected.items(), key=lambda entry:(active._time(entry[1]['created_at']), entry[1]['id'])):
        raw, metadata = read(item, MAX_ARCHIVE_BYTES); in_round(metadata, number)
        admission, records = _verified_private_pairs_artifact(raw, metadata, now=now,
            expected_run_id=run_id, expected_head_sha=source)
        _need(admission['scope'] == 'OPERATOR_SUPPLIED_RESEARCH')
        embedded = records[0]['training_receipt']; ident = embedded['id']
        _need(ident in items and ident != metadata['id'])
        learning_raw, learning_metadata = read(items[ident], MAX_ARCHIVE_BYTES)
        _need(re.fullmatch(r'(?:boat-venue-learning|all-existing-model-learning)-'+str(run_id)+r'-[1-9][0-9]*', learning_metadata['name']) is not None)
        def learning_receipt(route):
            _need(route == 'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/'+str(ident))
            return learning_metadata
        context = context_from_encrypted_artifact(learning_raw, ident, now=now, _fetch=learning_receipt)
        _need(context['training']['scope'] == 'OPERATOR_SUPPLIED_RESEARCH')
        training_ids.add(ident); training_hashes.add(digest(context['training']))
        for payload in records:
            _need(canonical(payload['training']) == canonical(context['training'])
                  and canonical(payload['training_receipt']) == canonical(context['receipt']))
            sport, race = record_identity(payload)
            _need(sport == 'boat')
            race = official_id(race)
            _need(race.startswith(day.replace('-', '')+'-'))
            if 'pair' not in payload:
                input_only += 1; input_races.add((sport, race)); continue
            forecasts += 1; pair = payload['pair']
            identity = (sport, race, pair['stage'], pair['cell_key'])
            descriptor = dict(race=(sport, race), record_sha256=digest(payload), artifact_id=metadata['id'],
                cutoff_at=pair['cutoff_at'], info=dict(race_id=race,
                    race_cutoff_at=pair.get('race_cutoff_at', pair['cutoff_at']), roster=pair['baseline_normalized']['roster']))
            if identity in first:
                original = first[identity]
                _need(active._time(original['cutoff_at']) == active._time(descriptor['cutoff_at'])
                      and canonical(original['info']) == canonical(descriptor['info']))
            else:
                first[identity] = descriptor
        del records, context, raw, learning_raw

    result.update(current_pair_authenticated=True, current_pair_forecast_record_count=forecasts,
        current_pair_input_only_record_count=input_only, current_pair_first_forecast_record_count=len(first),
        current_pair_repeat_forecast_record_count=forecasts-len(first),
        current_pair_distinct_race_count=len({item['race'] for item in first.values()}),
        current_pair_input_only_distinct_race_count=len(input_races), current_pair_training_archive_count=len(training_ids),
        current_pair_result_archive_count=0,
        current_pair_training_bodies_sha256=digest(sorted(training_hashes)),
        current_pair_first_versions_sha256=digest(sorted((key, value['record_sha256'], value['artifact_id']) for key, value in first.items())))
    if first:
        from race_ai.all_existing_model_result_intake import observations_from_result_artifact, MAX_ARCHIVE_BYTES as RESULT_LIMIT, _json
        from race_ai.boat_private_original_archive import open_original_zip
        from race_ai.first_receipt_continuity import latest_result_observations
        from race_ai.all_existing_model_intake import _legacy_boat, _ordinary_result
        from race_ai.repeated_cycle import artifact_name
        revisions = {}; latest = {}; observation_count = 0
        for number in rounds:
            name = artifact_name('race-existing-cycle', run_id, number)
            matches = [item for item in listing if item.get('name') == name]; _need(len(matches) == 1)
            raw, metadata = read(matches[0], RESULT_LIMIT); in_round(metadata, number)
            admitted = observations_from_result_artifact(raw, metadata, now=now,
                expected_run_id=run_id, expected_head_sha=source)
            with open_original_zip(raw, metadata, expected_kind='RESULT', max_plain_zip_bytes=32*1024*1024) as archive:
                journal = _json(archive.read('official-result-observations.json'))
                report = _json(archive.read('status.json'))
            step = next(step for step in job['steps'] if step.get('name') == f'Deadline-ordered five-model round {number:02}')
            _need(type(report.get('round_no')) is int and report['round_no'] == number and report.get('day_jst') == day
                  and active._time(step['started_at']) <= active._time(report['updated_at']) <= active._time(metadata['created_at'])
                  and admitted['receipt']['original_journal_sha256'] == digest(journal))
            for observation in journal:
                key = (observation['race_id'], active._time(observation['captured_at']).isoformat())
                fingerprint = digest(observation)
                _need(key not in revisions or revisions[key] == fingerprint)
                revisions[key] = fingerprint; observation_count += 1
            combined, _ = latest_result_observations(list(latest.values())+admitted['observations'])
            latest = {row['race_id']:row for row in combined}
        joins = dict(settled=0, pending=0, special=0, missing=0); joined_races = set()
        for descriptor in first.values():
            sport, race = descriptor['race']; observation = latest.get(race)
            if observation is None:
                joins['missing'] += 1; continue
            value = _legacy_boat(observation)
            _, reason = _ordinary_result(value, descriptor['info'], now)
            joins[reason or 'settled'] += 1; joined_races.add((sport, race))
        result.update(current_pair_result_archive_count=len(rounds),
            current_pair_result_scope='PRODUCER_JOURNAL_ONLY_UNQUALIFIED',
            current_pair_result_unique_revision_count=len(revisions),
            current_pair_result_duplicate_revision_count=observation_count-len(revisions),
            current_pair_result_revisions_sha256=digest(sorted(revisions.items())),
            current_pair_producer_journal_joined_race_count=len(joined_races))
        result.update({'current_pair_producer_journal_'+name+'_join_count':count for name, count in joins.items()})
    result['current_pair_artifacts_sha256'] = digest(sorted(provenance.items()))
    return result


def audit_current_pairs(*, get, run_id, now, expected_owner_sha):
    """Raise on selected bad/missing evidence; return only flat unqualified counts."""
    try:
        return _audit(get, run_id, now, expected_owner_sha)
    except Exception:
        # The trusted workflow preserves its prior independent core proof and
        # emits static UNKNOWN/HOLD fields. Never echo private exception values.
        raise ValueError('CURRENT_PAIR_AUDIT_REJECTED') from None
