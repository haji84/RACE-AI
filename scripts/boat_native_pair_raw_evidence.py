"""Independent raw evidence for the two existing S BOAT observed P1 cells.

Only existing GitHub/archive readers and the original vault/parser contracts
are used. Private evidence is returned to trusted main memory, never printed.
Raw agreement grants neither publication/actual-close proof nor qualification.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import os
import re


SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
CELLS = frozenset(('boat/boat-observed-pairwise-factor-v1',
                   'boat/boat-observed-pairwise-start-v1'))
SCHEMA = 'RACE_AI_NATIVE_PAIR_RAW_EVIDENCE_COUNTS_V1'
_PHASES = frozenset(('INPUT_OR_CONTEXT_REJECTED', 'SOURCE_SCOPE_REJECTED',
    'PAIR_OR_TRAINING_REJECTED', 'RESULT_SNAPSHOT_REJECTED',
    'CAPTURE_INVENTORY_REJECTED', 'CAPTURE_AUTHENTICATION_REJECTED',
    'RAW_SOURCE_BINDING_REJECTED', 'RAW_REPLAY_REJECTED'))
_JST = timezone(timedelta(hours=9))


def _need(value):
    if not value:
        raise ValueError('NATIVE_PAIR_RAW_EVIDENCE_REJECTED')


def _hex(value, size):
    return type(value) is str and re.fullmatch('[a-f0-9]{' + str(size) + '}', value) is not None


def _id(value):
    return type(value) is int and 0 < value < 10**20


def _public(reason=None, proof=None):
    matched = proof is not None
    return dict(schema=SCHEMA, raw_status='RAW_SOURCE_REPLAY_MATCH' if matched else 'HOLD',
        reason=reason if type(reason) is str and reason in _PHASES else None,
        comparison_count=int(matched), raw_program_match=matched, raw_result_match=matched,
        registered_identities_match=matched, capture_clocks_match=matched,
        upstream_published_at=None, actual_voting_closed_at=None,
        formal_status='HOLD_UNPROVEN_PUBLICATION_AND_ACTUAL_CLOSE', formal_qualified=False,
        promotion_allowed=False, source_requests=0,
        proof_sha256=proof)


def _actions_context(get, now):
    """Reject non-main execution before resolving the owner's production key."""
    from race_ai.boat_private_original_vault import _json, _time
    _need(os.environ.get('GITHUB_ACTIONS') == 'true'
          and os.environ.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI'
          and os.environ.get('GITHUB_REF') == 'refs/heads/main'
          and os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_run')
          and os.environ.get('GITHUB_RUN_ATTEMPT') == '1')
    ident = os.environ.get('GITHUB_RUN_ID', '')
    head = os.environ.get('GITHUB_SHA')
    _need(re.fullmatch('[1-9][0-9]{0,19}', ident) is not None and _hex(head, 40))
    run = _json(get('actions/runs/' + ident), 1024 * 1024)
    _need(type(run) is dict and type(run.get('id')) is int and run['id'] == int(ident)
          and run.get('head_sha') == head and run.get('head_branch') == 'main'
          and run.get('event') == os.environ['GITHUB_EVENT_NAME']
          and run.get('path') == '.github/workflows/boat-owner-national-p1-matrix.yml'
          and type(run.get('run_attempt')) is int and run['run_attempt'] == 1
          and run.get('status') == 'in_progress' and run.get('conclusion') is None
          and _time(run.get('created_at')) <= now)
    for name in ('repository', 'head_repository'):
        value = run.get(name)
        _need(type(value) is dict and type(value.get('id')) is int and value['id'] == 1416489937
              and value.get('full_name') == 'haji84/RACE-AI')


def _read_original(reads, item, run, now, limit):
    from race_ai import boat_all_model_recovery as recovery
    from scripts import boat_owner_active_snapshot_audit as active
    ident = item['id']
    metadata_raw = reads(f'actions/artifacts/{ident}')
    metadata, _ = recovery._metadata(metadata_raw, item, run, now, reads)
    _need(type(metadata.get('size_in_bytes')) is int and 0 < metadata['size_in_bytes'] <= limit)
    raw = reads(f'actions/artifacts/{ident}/zip')
    _need(type(raw) is bytes and 0 < len(raw) <= limit
          and len(raw) == metadata['size_in_bytes']
          and metadata['digest'] == 'sha256:' + sha256(raw).hexdigest()
          and active._time(run['created_at']) <= active._time(metadata['created_at']) <= now)
    return raw, metadata


def _in_round(metadata, number, scope, parse_time):
    step = next(row for row in scope['job']['steps']
                if row.get('name') == f'Deadline-ordered five-model round {number:02}')
    _need(parse_time(step['started_at']) <= parse_time(metadata['created_at']) <= parse_time(step['completed_at']))
    return step


def _pair(reads, scope, ident, record_sha, now, key):
    from race_ai.actions_contract import canonical, digest
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact, MAX_ARCHIVE_BYTES
    from race_ai.boat_venue_learning_context import context_from_encrypted_artifact
    from scripts import boat_owner_active_snapshot_audit as active
    run = scope['run']; items = {item['id']: item for item in scope['inventory']}
    _need(ident in items)
    item = items[ident]
    match = re.fullmatch('all-existing-model-pairs-' + str(run['id']) + '-([1-9][0-9]*)', item.get('name', ''))
    _need(match is not None and int(match[1]) in scope['rounds'])
    raw, metadata = _read_original(reads, item, run, now, MAX_ARCHIVE_BYTES)
    _in_round(metadata, int(match[1]), scope, active._time)
    admission, records = _verified_private_pairs_artifact(raw, metadata, now=now,
        expected_run_id=run['id'], expected_head_sha=SOURCE, key=key)
    _need(admission['scope'] == 'OPERATOR_SUPPLIED_RESEARCH' and bool(records))
    selected = [row for row in records if digest(row) == record_sha]
    _need(len(selected) == 1)
    learning_id = records[0]['training_receipt']['id']
    _need(learning_id in items and learning_id != ident)
    learning_raw, learning_meta = _read_original(reads, items[learning_id], run, now, MAX_ARCHIVE_BYTES)
    _need(re.fullmatch(r'(?:boat-venue-learning|all-existing-model-learning)-' + str(run['id'])
                      + r'-[1-9][0-9]*', learning_meta['name']) is not None)

    def receipt(route):
        _need(route == 'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/' + str(learning_id))
        return learning_meta

    context = context_from_encrypted_artifact(learning_raw, learning_id, now=now, _fetch=receipt)
    for row in records:
        _need(canonical(row['training']) == canonical(context['training'])
              and canonical(row['training_receipt']) == canonical(context['receipt']))
    payload = selected[0]; pair = payload.get('pair')
    _need(type(pair) is dict and pair.get('cell_key') in CELLS and pair.get('stage') == 'P1'
          and pair.get('sport') == 'boat' and payload['cell_key'] == pair['cell_key'])
    return payload, metadata


def _results(reads, scope, race, now, parse_time):
    from race_ai.actions_contract import digest
    from race_ai.all_existing_model_result_intake import observations_from_result_artifact, MAX_ARCHIVE_BYTES, _json
    from race_ai.boat_private_original_archive import open_original_zip
    from race_ai.first_receipt_continuity import latest_result_observations
    from race_ai.repeated_cycle import artifact_name
    run = scope['run']; revisions = {}; latest = {}; origins = {}; provenance = []
    day = parse_time(run['created_at']).astimezone(_JST).date().isoformat()
    for number in scope['rounds']:
        name = artifact_name('race-existing-cycle', run['id'], number)
        selected = [item for item in scope['inventory'] if item.get('name') == name]
        _need(len(selected) == 1)
        raw, metadata = _read_original(reads, selected[0], run, now, MAX_ARCHIVE_BYTES)
        step = _in_round(metadata, number, scope, parse_time)
        admitted = observations_from_result_artifact(raw, metadata, now=now,
            expected_run_id=run['id'], expected_head_sha=SOURCE)
        with open_original_zip(raw, metadata, expected_kind='RESULT', max_plain_zip_bytes=32 * 1024 * 1024) as archive:
            journal = _json(archive.read('official-result-observations.json'))
            report = _json(archive.read('status.json'))
        _need(type(report.get('round_no')) is int and report['round_no'] == number
              and report.get('day_jst') == day
              and parse_time(step['started_at']) <= parse_time(report['updated_at']) <= parse_time(metadata['created_at'])
              and admitted['receipt']['original_journal_sha256'] == digest(journal))
        provenance.append(dict(artifact_id=metadata['id'], metadata_sha256=digest(metadata),
                               zip_sha256=sha256(raw).hexdigest(), journal_sha256=digest(journal)))
        for row in journal:
            identity = (row['race_id'], parse_time(row['captured_at']).isoformat())
            fingerprint = digest(row)
            _need(identity not in revisions or revisions[identity] == fingerprint)
            revisions[identity] = fingerprint
            origins.setdefault(identity, []).append(metadata['id'])
        combined, _ = latest_result_observations(list(latest.values()) + admitted['observations'])
        latest = {row['race_id']: row for row in combined}
    _need(race in latest)
    observation = latest[race]
    identity = (race, parse_time(observation['captured_at']).isoformat())
    return observation, dict(observed_at=now.isoformat(), run_scope_sha256=digest(scope),
        owner_run_id=run['id'], owner_source_commit=SOURCE, completed_rounds=list(scope['rounds']),
        owner_inventory_sha256=scope['inventory_sha256'],
        result_artifacts=provenance, revisions_sha256=digest(sorted(revisions.items())),
        selected_original_artifact_ids=sorted(set(origins[identity])))


def _capture_headers(repo, snapshot, run, now, wanted, vault, key, transport):
    """Authenticate the complete bounded run inventory before hash selection."""
    git = vault.VaultGitRepository(repo, ref=vault.VAULT_REF) if transport is None else transport
    _need(git.ref == vault.VAULT_REF)
    created = vault._time(run['created_at']).astimezone(_JST)
    months = sorted({created.strftime('%Y-%m'), (created + timedelta(days=1)).strftime('%Y-%m')})
    mac = vault._keys(key)[1]
    candidates = []; headers = []; seen = set()
    for month in months:
        # The unchanged complete-month reader reconciles the signed root's
        # entry total with all bounded run indexes. This reads descriptors,
        # never unrelated ciphertext, before narrowing to this actual run.
        vault.list_originals(month, repo, source_commit=snapshot, key=key, transport=git)
        locators = vault.list_originals(month, repo, source_commit=snapshot, run_id=run['id'], key=key, transport=git)
        _need(type(locators) is list and len(locators) <= vault.MAX_RUN_ENTRIES)
        for locator in locators:
            if locator['kind'] != 'SOURCE_CAPTURES':
                continue
            vault._validate_locator(locator)
            _need(locator['ref'] == vault.VAULT_REF and locator['source_commit'] == snapshot
                  and locator['artifact_id'] is None)
            identity = (locator['batch_path'], locator['entry_sha256'])
            _need(identity not in seen); seen.add(identity)
            reference = {name: locator[name] for name in ('batch_path', 'batch_sha256', 'entry_sha256', 'artifact_id', 'kind')}
            entry = vault._batch_entry(git, snapshot, reference, mac)
            header = entry['header']; summary = header['summary']; files = header['files']
            archived = vault._time(header['archived_at'])
            _need(summary['kind'] == 'SOURCE_CAPTURES' and type(summary['run_id']) is int
                  and summary['run_id'] == run['id'] and summary['head_sha'] == SOURCE
                  and summary['month'] == month == archived.astimezone(_JST).strftime('%Y-%m')
                  and vault._time(run['created_at']) <= archived <= now)
            count = summary['capture_count']
            _need(type(count) is int and 0 < count <= 240)
            expected = {f'capture-{i:04d}.{suffix}' for i in range(count) for suffix in ('raw', 'json')}
            _need(set(files) == expected and len(files) == 2 * count)
            for i in range(count):
                _need(0 < files[f'capture-{i:04d}.raw']['size'] <= 4 * 1024 * 1024
                      and 0 < files[f'capture-{i:04d}.json']['size'] <= 16384)
            headers.append(locator['entry_sha256'])
            if any(files[f'capture-{i:04d}.raw']['sha256'] in wanted for i in range(count)):
                candidates.append(locator)
    _need(bool(headers) and bool(candidates))
    return git, candidates, headers


def _captures(repo, candidates, wanted, vault, key, git):
    selected = []; total = 0
    for locator in candidates:
        restored = vault.restore_capture_bundle(locator, repo, key=key, transport=git)
        _need(restored['provenance']['independent_git_readback_verified'] is True)
        for raw, metadata_raw in restored['captures']:
            if sha256(raw).hexdigest() not in wanted:
                continue
            metadata = vault._json(metadata_raw, 16384)
            _need(set(metadata) == {'source_url', 'captured_at', 'source_sha256', 'http_status'})
            total += len(raw) + len(metadata_raw)
            _need(len(selected) < 2 * vault.MAX_RUN_ENTRIES * 240 and total <= vault.MAX_PLAIN)
            selected.append((raw, metadata_raw))
    return tuple(selected)


def _compare(payload, observation, captures, info, *, replay, parsers, registry, now, run):
    """Pure projection; callers must first authenticate all originals and captures."""
    from race_ai.actions_contract import digest
    from race_ai.all_existing_model_intake import _time, _legacy_boat, _ordinary_result
    ref = replay._program_ref_for_pair(payload, info=info, registry=registry, parse_time=_time)
    _need(ref is not None)
    program_ref = replay._ref(ref, info['race_id'], _time)
    _need(replay._exact_url(observation.get('source_url'), 'raceresult', info['race_id']))
    result_ref = dict(sha=observation['source_sha256'], ref=observation['source_url'],
                     captured=_time(observation['captured_at']), form='EXACT')
    items = replay._capture_pairs(captures, parsers, _time)
    before, program_binding = replay._select_capture(items, program_ref, 'racelist', info['race_id'])
    after, result_binding = replay._select_capture(items, result_ref, 'raceresult', info['race_id'])
    _need(before is not None and after is not None)
    _need(_time(run['created_at']) <= before['captured'] <= _time(payload['pair']['input_as_of'])
          and _time(info['race_cutoff_at']) <= after['captured'] <= now)
    race = info['race_id']; day = date.fromisoformat(race[:4] + '-' + race[4:6] + '-' + race[6:8])
    options = dict(day=day, venue=race[9:11], race_no=int(race[-2:]))
    program = parsers['A74_PROGRAM'].parse_program(before['raw'], **options,
        source_url=before['url'], captured_at=before['captured_text'])
    _need(program.get('race_id') == race and program.get('source_sha256') == before['sha']
          and program.get('pre_cutoff_eligible') is True
          and _time(program['closed_at']) == _time(info['race_cutoff_at'])
          and {str(row['lane']): row['racer_registration_id'] for row in program['boats']} == info['roster'])
    result = parsers['PR64_RESULT'].parse_update(after['raw'], **options, kind='raceresult', entries=None,
        source_url=after['url'], captured_at=after['captured_text'])
    _need(digest(result) == digest(observation))
    converted, reason = _ordinary_result(_legacy_boat(result), info, now)
    _need(reason is None and converted['roster'] == info['roster']
          and payload['pair']['learned_normalized']['roster'] == info['roster'])
    return dict(program_receipt_binding_sha256=digest([
                    value.isoformat() if type(value) is datetime else value for value in program_binding]),
                result_receipt_binding_sha256=digest([
                    value.isoformat() if type(value) is datetime else value for value in result_binding]),
                program_projection_sha256=digest(program), result_observation_sha256=digest(result))


def audit_native_pair_raw_evidence(*, get, repo, run_id, pair_artifact_id, record_sha256,
                                   vault_snapshot_commit, now, key=None, transport=None):
    """Verify one original; raw agreement always leaves formal status on HOLD.

    ``get`` is the existing read-only GitHub/archive adapter, not provider I/O.
    Explicit key/transport injection is for public invented local fixtures.
    Production key resolution is restricted to the existing trusted main run.
    The derived latest-result snapshot never rewrites or backdates the pair.
    """
    phase = 'INPUT_OR_CONTEXT_REJECTED'
    try:
        _need(callable(get) and _id(run_id) and _id(pair_artifact_id)
              and _hex(record_sha256, 64) and _hex(vault_snapshot_commit, 40)
              and type(now) is datetime and now.utcoffset() is not None)
        from scripts import boat_owner_active_snapshot_audit as active
        reads = active._Reads(get)
        if key is None:
            _actions_context(reads, now)
        else:
            _need(type(key) is bytes and len(key) == 32)
        from race_ai.boat_pdca_state import state_key
        state_key('production', key)
        from scripts import boat_current_pair_eligibility_audit as pairs
        from scripts import boat_cutoff_raw_replay_audit as replay
        from race_ai import boat_private_original_vault as vault
        from race_ai import boat_official_program as program
        from race_ai import official_race_updates as result
        from race_ai import all_existing_model_intake as intake
        from race_ai import observed_p1_connection as observed
        from race_ai import all_existing_model_registry as registry
        from race_ai.actions_contract import digest
        for module, expected in ((replay, 'daef1d09ce55dde149defda0a15e6459ac511f73'),
            (vault, '582dd4933f81d3ef0c76dc5f5479c9617f57a902'),
            (program, '1cfed75add647d77f76936f24be33db0776266c4'),
            (result, '06ec8fba76767b6a56cd9d26dd7e568fc4b0f0e2'),
            (intake, '56f7310f8a30c72aa223641f35605948bd6e9208'),
            (observed, 'd37ce58025e358fee6189b632938ed088cf1c5a2')):
            replay._pinned(module, expected)
        with vault._native_key(key):
            phase = 'SOURCE_SCOPE_REJECTED'
            _, reads, scope = pairs._scope(reads, run_id, now, SOURCE)
            phase = 'PAIR_OR_TRAINING_REJECTED'
            payload, metadata = _pair(reads, scope, pair_artifact_id, record_sha256, now, key)
            pair = payload['pair']
            from race_ai.frozen_day_cycle import official_id
            race = official_id(pair['race_id'])
            _need(race.startswith(active._time(scope['run']['created_at']).astimezone(_JST).strftime('%Y%m%d-')))
            info = dict(race_id=race, race_cutoff_at=pair['race_cutoff_at'], roster=pair['baseline_normalized']['roster'])
            phase = 'RESULT_SNAPSHOT_REJECTED'
            observation, snapshot = _results(reads, scope, race, now, active._time)
            converted, reason = intake._ordinary_result(intake._legacy_boat(observation), info, now)
            _need(reason is None)
            phase = 'RAW_SOURCE_BINDING_REJECTED'
            ref = replay._program_ref_for_pair(payload, info=info, registry=registry, parse_time=active._time)
            _need(ref is not None)
            wanted = {ref['source_sha256'], observation['source_sha256']}
            phase = 'CAPTURE_INVENTORY_REJECTED'
            git, candidates, headers = _capture_headers(repo, vault_snapshot_commit, scope['run'], now,
                                                        wanted, vault, key, transport)
            phase = 'CAPTURE_AUTHENTICATION_REJECTED'
            captures = _captures(repo, candidates, wanted, vault, key, git)
            phase = 'RAW_REPLAY_REJECTED'
            proof = _compare(payload, observation, captures, info, replay=replay,
                parsers={'A74_PROGRAM': program, 'PR64_RESULT': result, 'receipt_json': vault._json},
                registry=registry, now=now, run=scope['run'])
            proof.update(schema='RACE_AI_NATIVE_PAIR_RAW_PRIVATE_EVIDENCE_V1',
                source_commit=SOURCE, run_id=run_id, pair_artifact_id=pair_artifact_id,
                pair_artifact_metadata_sha256=digest(metadata), record_sha256=record_sha256,
                input_sha256=pair['input_sha256'], pair_sha256=pair['pair_sha256'],
                vault_snapshot_commit=vault_snapshot_commit, capture_headers_sha256=digest(sorted(headers)),
                result_snapshot=snapshot)
            return dict(public=_public(proof=digest(proof)), private=proof)
    except Exception:
        return dict(public=_public(reason=phase), private=None)
