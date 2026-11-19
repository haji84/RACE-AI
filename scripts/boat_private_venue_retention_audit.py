"""Read exact failed research ciphertext at one observed transfer commit.

This main-only reader neither retries publication nor claims when an earlier
push completed. Call from the existing trusted matrix using direct _live_gh;
the archival gh adapter can initialize an owner-key vault before this gate.
"""
from datetime import datetime
from hashlib import sha1, sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

SOURCE = '1dbb47b68d487fc6def0bd4b10b1423f0a2145f6'
RUN = 44426169530
JOB = 135231474660
CASES = {18: 14488233127, 23: 14491506398, 24: 14492170715}
REPOSITORY = 'haji84/RACE-AI'
REPOSITORY_ID = 1416489937
WORKFLOW = '.github/workflows/boat-owner-national-p1-matrix.yml'
WORKFLOW_NAME = 'BOAT nationally authenticated P1 matrix (no racing GET)'
BRANCH = 'production/boat-p0-p1-20261111'
PREFIX = 'state/boat-venue-history/v1/learning/'
MAX_ZIP = 128*1024*1024
MAX_EXPANDED = 256*1024*1024
MAX_CANDIDATES = 10000
MAX_GROUP = 64*1024*1024
_FAILURE_CODES = frozenset('''ARTIFACT_INVENTORY_REJECTED ARTIFACT_METADATA_REJECTED
CHECKOUT_REJECTED CLOCK_REJECTED JSON_REJECTED MAIN_CONTEXT_REJECTED PRIVATE_TEMP_REJECTED
READ_ENDPOINT_REJECTED REMOTE_REJECTED RESPONSE_BOUND_REJECTED ROUND_CONTEXT_REJECTED
SOURCE_ADMISSION_REJECTED SOURCE_CONTEXT_REJECTED SUMMARY_COVERAGE_REJECTED ZIP_REJECTED
OBSERVATION_SNAPSHOT_REJECTED OWNER_STATE_KEY_REQUIRED STATE_AUTHENTICATION_OR_COMPRESSION_FAILED
RESEARCH_CACHE_FRESH_METADATA_REQUIRED RESEARCH_CACHE_FRESH_IDENTITY_MISMATCH
RESEARCH_CACHE_ARCHIVE_BOUND_INVALID RESEARCH_CACHE_PRIVATE_ARCHIVE_REQUIRED
RESEARCH_CACHE_ZIP_READ_FAILED RESEARCH_CACHE_ARCHIVE_BYTES_INVALID
ALL_MODEL_PAIR_RECEIPT_ARCHIVE_REJECTED ALL_MODEL_PAIR_RECEIPT_ARTIFACT_BYTES_INVALID
ALL_MODEL_PAIR_RECEIPT_ARTIFACT_CLOCK_INVALID ALL_MODEL_PAIR_RECEIPT_ARTIFACT_IDENTITY_INVALID
ALL_MODEL_PAIR_RECEIPT_ARTIFACT_NAME_INVALID ALL_MODEL_PAIR_RECEIPT_ARTIFACT_RUN_INVALID
ALL_MODEL_PAIR_RECEIPT_PRE_CUTOFF_CLOCK_INVALID ALL_MODEL_PAIR_RECEIPT_CAPTURED_INPUT_PRE_CUTOFF_CLOCK_INVALID
ALL_MODEL_PAIR_RECEIPT_PUBLIC_SUMMARY_BINDING_INVALID ALL_MODEL_PAIR_RECEIPT_PAYLOAD_REPLAY_INVALID
ALL_MODEL_PAIR_RECEIPT_MIXED_CANDIDATE_CONTEXTS_INVALID
VENUE_LEARNING_AUTHENTICATION_FAILED VENUE_LEARNING_PAYLOAD_HASH_INVALID
VENUE_LEARNING_SUMMARY_INVALID VENUE_LEARNING_SUMMARY_MISMATCH
ALL_MODEL_PRIVATE_PDCA_PAYLOAD_SCHEMA_INVALID ALL_MODEL_PRIVATE_PDCA_SCORE_REPLAY_MISMATCH'''.split())


class _Rejected(ValueError):
    pass


def _need(ok, reason):
    if not ok:
        raise _Rejected(reason)


def _failure_code(error):
    # Never format exceptions or follow their potentially private cause chain.
    if type(error) in (_Rejected, ValueError) and len(error.args) == 1 and type(error.args[0]) is str:
        if error.args[0] in _FAILURE_CODES:
            return error.args[0]
    return 'UNCLASSIFIED'


def _time(value):
    _need(type(value) is str and len(value) <= 64, 'CLOCK_REJECTED')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(parsed.utcoffset() is not None, 'CLOCK_REJECTED')
    return parsed


def _json(raw, limit=2*1024*1024):
    _need(type(raw) is bytes and 0 < len(raw) <= limit, 'RESPONSE_BOUND_REJECTED')
    def unique(rows):
        out = {}
        for key, value in rows:
            _need(key not in out, 'JSON_REJECTED')
            out[key] = value
        return out
    def nonfinite(value):
        raise _Rejected('JSON_REJECTED')
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    _need(type(value) is dict, 'JSON_REJECTED')
    return value


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def _hash(value):
    return sha256(_wire(value)).hexdigest()


def _repository(value):
    return (type(value) is dict and type(value.get('id')) is int and
            value['id'] == REPOSITORY_ID and value.get('full_name') == REPOSITORY)


class _Reads:
    """Freeze service metadata; ZIPs have a separate explicit aggregate bound."""
    def __init__(self, get, main_run):
        self.get, self.main_run, self.cache = get, main_run, {}
        self.artifacts = set(CASES.values())
    def __call__(self, path):
        artifact = re.fullmatch(r'actions/artifacts/([1-9][0-9]*)(/zip)?', path)
        allowed = path in (f'actions/runs/{self.main_run}', f'actions/runs/{RUN}', f'actions/jobs/{JOB}')
        allowed = allowed or bool(re.fullmatch(f'actions/runs/{RUN}/artifacts\\?per_page=100(?:&page=(?:[1-9]|10))?', path))
        allowed = allowed or artifact is not None and int(artifact[1]) in self.artifacts
        _need(allowed, 'READ_ENDPOINT_REJECTED')
        if path in self.cache:
            return self.cache[path]
        raw = self.get(path)
        archive = artifact is not None and artifact[2] is not None
        _need(type(raw) is bytes and 0 < len(raw) <= (MAX_ZIP if archive else 2*1024*1024),
              'RESPONSE_BOUND_REJECTED')
        if not archive:
            self.cache[path] = raw
        return raw


def _service_context(reads, identity, now):
    _need(type(identity) is dict and set(identity) == {'commit', 'run_id', 'attempt', 'repository'} and
          identity['repository'] == REPOSITORY and type(identity['run_id']) is int and 0 < identity['run_id'] < 10**20 and
          type(identity['attempt']) is int and identity['attempt'] == 1 and
          type(identity['commit']) is str and re.fullmatch('[a-f0-9]{40}', identity['commit']), 'MAIN_CONTEXT_REJECTED')
    expected = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY=REPOSITORY,
        GITHUB_RUN_ID=str(identity['run_id']), GITHUB_RUN_ATTEMPT='1', GITHUB_SHA=identity['commit'],
        GITHUB_JOB='authenticated_original_matrix', GITHUB_WORKFLOW_REF=REPOSITORY+'/'+WORKFLOW+'@refs/heads/main')
    _need(all(os.environ.get(key) == value for key, value in expected.items()), 'MAIN_CONTEXT_REJECTED')
    main = _json(reads(f'actions/runs/{identity["run_id"]}'))
    _need(type(main.get('id')) is int and main['id'] == identity['run_id'] and main.get('head_sha') == identity['commit'] and
          main.get('head_branch') == 'main' and main.get('path') == WORKFLOW and main.get('name') == WORKFLOW_NAME and
          type(main.get('workflow_id')) is int and main['workflow_id'] == 418875114 and
          main.get('event') in ('push', 'workflow_run') and
          os.environ.get('GITHUB_EVENT_NAME') == main['event'] and type(main.get('run_attempt')) is int and
          main['run_attempt'] == 1 and main.get('status') == 'in_progress' and main.get('conclusion') is None and
          all(_repository(main.get(key)) for key in ('repository', 'head_repository')) and
          _time(main['created_at']) <= _time(main['updated_at']) <= now, 'MAIN_CONTEXT_REJECTED')
    source = _json(reads(f'actions/runs/{RUN}'))
    _need(type(source.get('id')) is int and source['id'] == RUN and source.get('head_sha') == SOURCE and source.get('head_branch') == BRANCH and
          source.get('path') == '.github/workflows/boat-nationwide-ab-one-shot.yml' and
          source.get('name') == 'BOAT nationwide cutoff-ordered A/B research (no Vercel)' and
          type(source.get('workflow_id')) is int and source['workflow_id'] == 405276784 and source.get('event') == 'workflow_dispatch' and
          type(source.get('run_attempt')) is int and source['run_attempt'] == 1 and
          source.get('status') == 'completed' and source.get('conclusion') == 'success' and
          all(_repository(source.get(key)) for key in ('repository', 'head_repository')), 'SOURCE_CONTEXT_REJECTED')
    job = _json(reads(f'actions/jobs/{JOB}'))
    _need(type(job.get('id')) is int and job['id'] == JOB and type(job.get('run_id')) is int and
          job['run_id'] == RUN and job.get('head_sha') == SOURCE and
          type(job.get('run_attempt')) is int and job['run_attempt'] == 1 and
          job.get('name') == 'Existing frozen P0, exhibition P1, separate official results and PDCA' and
          job.get('status') == 'completed' and job.get('conclusion') == 'success' and
          _time(source['created_at']) <= _time(job['started_at']) <= _time(job['completed_at']) <=
          _time(source['updated_at']) <= now, 'SOURCE_CONTEXT_REJECTED')
    _need(type(job.get('steps')) is list and len(job['steps']) <= 256, 'ROUND_CONTEXT_REJECTED')
    rounds = {}
    for step in job['steps']:
        _need(type(step) is dict, 'ROUND_CONTEXT_REJECTED')
        match = re.fullmatch(r'Deadline-ordered five-model round ([0-9]{2})', str(step.get('name')))
        if not match:
            continue
        number = int(match[1])
        _need(1 <= number <= 24 and number not in rounds and step.get('status') == 'completed' and
              step.get('conclusion') == 'success', 'ROUND_CONTEXT_REJECTED')
        rounds[number] = (_time(step['started_at']), _time(step['completed_at']))
    _need(set(rounds) == set(range(1, 25)), 'ROUND_CONTEXT_REJECTED')
    clock = _time(job['started_at'])
    for number in range(1, 25):
        start, end = rounds[number]
        _need(clock <= start <= end <= _time(job['completed_at']), 'ROUND_CONTEXT_REJECTED')
        clock = end
    return rounds


def _metadata(meta, rounds, now, *, round_no, pdca):
    ident = meta.get('id')
    prefix = 'boat-venue-research-pdca' if pdca else 'all-existing-model-pairs'
    _need(type(ident) is int and ident > 0 and meta.get('name') == f'{prefix}-{RUN}-{round_no}' and
          (not pdca or CASES.get(round_no) == ident) and meta.get('expired') is False and
          type(meta.get('size_in_bytes')) is int and 0 < meta['size_in_bytes'] <= (MAX_ZIP if pdca else MAX_GROUP) and
          type(meta.get('digest')) is str and re.fullmatch('sha256:[a-f0-9]{64}', meta['digest']), 'ARTIFACT_METADATA_REJECTED')
    owner = meta.get('workflow_run')
    _need(type(owner) is dict and type(owner.get('id')) is int and owner['id'] == RUN and owner.get('head_sha') == SOURCE and
          owner.get('head_branch') == BRANCH and all(type(owner.get(key)) is int and owner[key] == REPOSITORY_ID
          for key in ('repository_id', 'head_repository_id')), 'ARTIFACT_METADATA_REJECTED')
    start, end = rounds[round_no]
    _need(start <= _time(meta['created_at']) <= end and _time(meta['created_at']) <= now <
          _time(meta['expires_at']), 'ARTIFACT_METADATA_REJECTED')


def _inventory(reads, rounds, now):
    rows, total = [], None
    for page in range(1, 11):
        suffix = '' if page == 1 else '&page='+str(page)
        value = _json(reads(f'actions/runs/{RUN}/artifacts?per_page=100'+suffix))
        count, part = value.get('total_count'), value.get('artifacts')
        _need(type(count) is int and 0 < count <= 1000 and (total is None or total == count) and
              type(part) is list and len(part) <= 100, 'ARTIFACT_INVENTORY_REJECTED')
        total = count
        rows.extend(part)
        if len(rows) >= total:
            break
        _need(len(part) == 100, 'ARTIFACT_INVENTORY_REJECTED')
    _need(len(rows) == total and all(type(row) is dict and type(row.get('id')) is int for row in rows) and
          len({row['id'] for row in rows}) == len(rows), 'ARTIFACT_INVENTORY_REJECTED')
    selected, originals = {}, {}
    for row in rows:
        name = row.get('name')
        _need(type(name) is str and len(name) <= 256, 'ARTIFACT_INVENTORY_REJECTED')
        pdca = re.fullmatch(f'boat-venue-research-pdca-{RUN}-([1-9][0-9]*)', name)
        pair = re.fullmatch(f'all-existing-model-pairs-{RUN}-([1-9][0-9]*)', name)
        _need(not name.startswith(f'boat-venue-research-pdca-{RUN}-') or
              pdca is not None and 1 <= int(pdca[1]) <= 24, 'ARTIFACT_INVENTORY_REJECTED')
        _need(not name.startswith(f'all-existing-model-pairs-{RUN}-') or pair is not None,
              'ARTIFACT_INVENTORY_REJECTED')
        if pair:
            number = int(pair[1])
            _need(number not in CASES and 1 <= number <= 24 and number not in originals,
                  'ARTIFACT_INVENTORY_REJECTED')
            originals[number] = row
        if pdca and int(pdca[1]) in CASES:
            number = int(pdca[1])
            _need(number not in selected, 'ARTIFACT_INVENTORY_REJECTED')
            selected[number] = row
        _need(not any(name == f'boat-venue-research-p1-{RUN}-{n}' for n in CASES), 'ARTIFACT_INVENTORY_REJECTED')
    _need(set(selected) == set(CASES), 'ARTIFACT_INVENTORY_REJECTED')
    reads.artifacts.update(row['id'] for row in originals.values())
    for number, row in selected.items():
        fresh = _json(reads(f'actions/artifacts/{row["id"]}'))
        _need(all(fresh.get(k) == row.get(k) for k in ('id', 'name', 'size_in_bytes', 'digest', 'created_at',
              'expires_at', 'expired', 'workflow_run')), 'ARTIFACT_METADATA_REJECTED')
        _metadata(fresh, rounds, now, round_no=number, pdca=True)
    return selected, {row['id']: (number, row) for number, row in originals.items()}


def _repos(repo, identity):
    root = Path(repo).resolve()
    main = Path(__file__).resolve().parents[1]
    for path, expected in ((main, identity['commit']), (root, SOURCE)):
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=path, timeout=10).decode().strip()
        changed = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=path, timeout=10)
        _need(actual == expected and not changed.strip(), 'CHECKOUT_REJECTED')
    temporary = Path(os.environ['RUNNER_TEMP']).absolute()
    _need('..' not in temporary.parts and not any(p.is_symlink() for p in (temporary, *temporary.parents)) and
          temporary.is_dir() and not temporary.is_relative_to(main) and not temporary.is_relative_to(root),
          'PRIVATE_TEMP_REJECTED')
    return root, temporary


def _original(ident, originals, reads, rounds, now, cache, verified):
    if ident in verified:
        return verified[ident]
    from race_ai.boat_venue_research_cache import read_research_archive
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
    from race_ai.all_existing_model_pairs import partition_key
    _need(ident in originals, 'SOURCE_ADMISSION_REJECTED')
    number, listed = originals[ident]
    meta = _json(reads(f'actions/artifacts/{ident}'))
    _need(all(meta.get(k) == listed.get(k) for k in ('id', 'name', 'size_in_bytes', 'digest', 'created_at',
          'expires_at', 'expired', 'workflow_run')), 'SOURCE_ADMISSION_REJECTED')
    _metadata(meta, rounds, now, round_no=number, pdca=False)
    raw, actual = read_research_archive(dict(artifact_id=ident, run_id=RUN, head_sha=SOURCE, digest=meta['digest']),
        gh=reads, cache_root=cache, maximum_bytes=MAX_GROUP)
    admission, records = _verified_private_pairs_artifact(raw, actual, now=now, expected_run_id=RUN, expected_head_sha=SOURCE)
    forecasts = {partition_key(record['pair']): _hash(record) for record in records if 'pair' in record}
    verified[ident] = (admission, forecasts)
    return verified[ident]


def _candidates(raw, round_no, meta, root, reads, originals, rounds, now, cache, verified):
    from race_ai.boat_venue_learning_handoff import FILES, _verified
    from race_ai.boat_venue_learning import read_candidate
    from race_ai.all_existing_model_pdca import verify_private_pdca, _summary
    from race_ai.all_existing_model_pairs import partition_key
    from race_ai.existing_model_dispatch import _race_key
    from race_ai.boat_research_batch import file_snapshot
    from scripts.boat_all_racers import _write
    _need(raw.startswith(b'PK\x03\x04') and len(raw) >= 22 and raw[-22:-18] == b'PK\x05\x06' and
          raw[-2:] == b'\0\0', 'ZIP_REJECTED')
    candidates, groups, summaries, expanded = [], {}, {}, 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        _need(1 <= len(entries) <= 4*MAX_CANDIDATES and len({p.filename for p in entries}) == len(entries), 'ZIP_REJECTED')
        for entry in entries:
            match = re.fullmatch(r'([1-9][0-9]{0,19})/(?:summary\.json|([a-f0-9]{64})/(learning\.json|learning\.enc|summary\.json))', entry.filename)
            _need(match is not None and not entry.flag_bits & 0x41 and
                  stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG) and
                  entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'ZIP_REJECTED')
            ident, partition, name = int(match[1]), match[2], match[3]
            limit = FILES[name] if name else FILES['summary.json']
            expanded += entry.file_size
            _need(0 < entry.file_size <= limit and expanded <= MAX_EXPANDED, 'ZIP_REJECTED')
            if partition is None:
                summaries[ident] = entry
            else:
                groups.setdefault(ident, {}).setdefault(partition, {})[name] = entry
        _need(set(groups) <= set(summaries) and summaries, 'SUMMARY_COVERAGE_REJECTED')
        for ident, summary_entry in summaries.items():
            admission, forecasts = _original(ident, originals, reads, rounds, now, cache, verified)
            partitions = groups.get(ident, {})
            _need(set(partitions) == set(forecasts), 'SUMMARY_COVERAGE_REJECTED')
            rows, observations = [], {}
            # The producer aggregated in original P1 record order. ZIP member
            # order is transport layout and must not reorder float summation.
            for partition in forecasts:
                members = partitions[partition]
                _need(set(members) == set(FILES), 'SUMMARY_COVERAGE_REJECTED')
                files = {name: archive.read(entry) for name, entry in members.items()}
                _need(all(len(files[name]) == members[name].file_size for name in FILES), 'ZIP_REJECTED')
                training, _ = _verified(files)
                folder = root/str(round_no)/str(ident)/partition
                folder.mkdir(mode=0o700, parents=True)
                for name, body in files.items():
                    _write(folder/name, body)
                payload = read_candidate(folder)
                _need(verify_private_pdca(payload) is True and payload['source_artifact'] == admission and
                      partition_key(payload['private_forecast']['pair']) == partition and
                      _hash(payload['private_forecast']) == forecasts[partition] and
                      rounds[round_no][0] <= _time(payload['evaluated_at']) <= _time(meta['created_at']) and
                      _time(admission['saved_at']) <= _time(payload['evaluated_at']), 'SOURCE_ADMISSION_REJECTED')
                rows.append(payload['score'])
                pair = payload['private_forecast']['pair']
                race = (pair['sport'], _race_key(pair['race_id'], pair['sport']))
                snapshot = None if payload['observation'] is None else _wire(payload['observation'])
                # The producer rejects unrelated/duplicate result identities,
                # then shares one complete observation (or None) across cells.
                _need(race not in observations or observations[race] == snapshot,
                      'OBSERVATION_SNAPSHOT_REJECTED')
                observations[race] = snapshot
                identity = sha256(files['learning.json']).hexdigest()
                prefix = PREFIX+identity+'/'
                candidates.append(dict(manifest_sha256=identity, training_sha256=training, round_no=round_no,
                    files={prefix+name: file_snapshot(folder/name, FILES[name], body) for name, body in files.items()}))
            expected = dict(_summary(admission, rows, sum(value is not None for value in observations.values())),
                            encrypted_readback_verified=True)
            _need(_json(archive.read(summary_entry), FILES['summary.json']) == expected, 'SUMMARY_COVERAGE_REJECTED')
    _need(len(candidates) <= MAX_CANDIDATES, 'ZIP_REJECTED')
    return candidates


class _ReadOnly:
    """Expose only the existing independent reader's pinned read operations."""
    def __init__(self, reader):
        _need(getattr(reader, 'ref', None) == 'state/boat-pdca-transfer', 'REMOTE_REJECTED')
        self.reader, self.pinned = reader, None
    def pin(self):
        _need(self.pinned is None, 'REMOTE_REJECTED')
        self.pinned = self.reader.head()
        _need(type(self.pinned) is str and re.fullmatch('[a-f0-9]{40}', self.pinned), 'REMOTE_REJECTED')
        self.reader.fetch(self.pinned)
        return self.pinned
    def tree(self, paths):
        _need(self.pinned is not None and 1 <= len(paths) <= 128 and
              all(re.fullmatch(re.escape(PREFIX)+r'[a-f0-9]{64}/(?:learning\.json|learning\.enc|summary\.json)', p) for p in paths),
              'REMOTE_REJECTED')
        return self.reader._run(['--no-lazy-fetch', 'ls-tree', '-z', self.pinned, '--', *paths])
    def prefetch(self, files):
        return self.reader.prefetch_selected(self.pinned, files, maximum_bytes=MAX_GROUP)
    def _publication_rejected(self, *args, **kwargs):
        raise ValueError('READ_ONLY_REPOSITORY')
    commit = commit_snapshot = push = _write_tree = _publication_rejected


def _remote(candidates, git, out):
    from race_ai.boat_research_batch import _body
    from race_ai.boat_venue_learning_handoff import _verified
    matching = []
    out.update(verified_candidate_count=0, missing_candidate_count=0, conflict_candidate_count=0, verified_original_bytes=0)
    for candidate in candidates:
        files = {path: _body(body) for path, body in candidate['files'].items()}
        raw = git.tree(sorted(files))
        _need(type(raw) is bytes and len(raw) <= sum(len(path)+80 for path in files), 'REMOTE_REJECTED')
        found, conflict = {}, False
        for row in raw.split(b'\0')[:-1] if raw else []:
            match = re.fullmatch(rb'([0-7]{6}) (blob|tree|commit) ([a-f0-9]{40})\t([^\0]+)', row)
            _need(match is not None, 'REMOTE_REJECTED')
            path = match[4].decode('ascii')
            _need(path in files and path not in found, 'REMOTE_REJECTED')
            found[path] = True
            expected = sha1(b'blob '+str(len(files[path])).encode()+b'\0'+files[path]).hexdigest().encode()
            conflict |= match[1] != b'100644' or match[2] != b'blob' or match[3] != expected
        _need(not raw or raw.endswith(b'\0'), 'REMOTE_REJECTED')
        if conflict:
            out['conflict_candidate_count'] += 1
        elif set(found) != set(files):
            out['missing_candidate_count'] += 1
        else:
            matching.append(candidate)
    group, size = [], 0
    def verify(group):
        expected = {path: _body(body) for candidate in group for path, body in candidate['files'].items()}
        read = git.prefetch(expected)
        for candidate in group:
            actual = {}
            for path, source in candidate['files'].items():
                body = read(git.pinned, path, MAX_GROUP)
                _need(body == expected[path], 'REMOTE_REJECTED')
                actual[path.rsplit('/', 1)[1]] = body
            training, _ = _verified(actual)
            _need(training == candidate['training_sha256'], 'REMOTE_REJECTED')
            out['verified_candidate_count'] += 1
            out['verified_original_bytes'] += sum(map(len, actual.values()))
    for candidate in matching:
        amount = sum(value[2] for value in candidate['files'].values())
        if group and size+amount > MAX_GROUP:
            verify(group)
            group, size = [], 0
        group.append(candidate)
        size += amount
    if group:
        verify(group)


def audit_private_venue_retention(repo, *, get, now, main_identity):
    """Counts/hash-only proof of current exact retention; every failure is HOLD."""
    out = dict(schema='RACE_AI_PRIVATE_VENUE_RETENTION_READBACK_COUNTS_V1', status='HOLD_PRIVATE_RESEARCH_RETENTION',
        phase='MAIN_CONTEXT', reason='CONTEXT_REJECTED', failure_code=None, artifact_count=None, expected_candidate_count=None,
        verified_candidate_count=None, missing_candidate_count=None, conflict_candidate_count=None,
        verified_original_bytes=None, artifact_inventory_sha256=None, candidate_inventory_sha256=None,
        observed_remote_commit=None, source_requests=0, production_promoted=False, plaintext_published=False,
        historical_push_completion_time_proven=False)
    try:
        _need(type(now) is datetime and now.utcoffset() is not None and callable(get) and type(main_identity) is dict,
              'MAIN_CONTEXT_REJECTED')
        reads = _Reads(get, main_identity.get('run_id'))
        rounds = _service_context(reads, main_identity, now)
        out['phase'] = 'ARTIFACT_METADATA'
        selected, originals = _inventory(reads, rounds, now)
        out['phase'] = 'CHECKOUT'
        root, temporary = _repos(repo, main_identity)
        out['phase'] = 'OWNER_AUTHENTICATION'
        from race_ai.boat_pdca_state import state_key
        state_key('production')
        from race_ai.boat_venue_research_cache import read_research_archive, research_readback_transport
        with tempfile.TemporaryDirectory(prefix='private-research-retention-', dir=temporary) as private:
            private = Path(private)
            cache = private/'source-cache'
            candidates, verified = [], {}
            out['phase'] = 'PRIVATE_ARCHIVE'
            for number, meta in sorted(selected.items()):
                raw, actual = read_research_archive(dict(artifact_id=meta['id'], run_id=RUN, head_sha=SOURCE,
                    digest=meta['digest']), gh=reads, cache_root=cache, maximum_bytes=MAX_ZIP)
                candidates.extend(_candidates(raw, number, actual, private/'candidates', reads, originals,
                                             rounds, now, cache, verified))
            _need(0 < len(candidates) <= MAX_CANDIDATES and len({c['manifest_sha256'] for c in candidates}) == len(candidates),
                  'SUMMARY_COVERAGE_REJECTED')
            out.update(artifact_count=3, expected_candidate_count=len(candidates),
                artifact_inventory_sha256=_hash([dict(round_no=n, artifact_id=m['id'], digest=m['digest'],
                    size_in_bytes=m['size_in_bytes'], created_at=m['created_at']) for n, m in sorted(selected.items())]),
                candidate_inventory_sha256=_hash(sorted([dict(round_no=c['round_no'], manifest_sha256=c['manifest_sha256'],
                    training_sha256=c['training_sha256'], files={p: dict(size=v[2], sha256=v[3]) for p, v in c['files'].items()})
                    for c in candidates], key=lambda c: c['manifest_sha256'])))
            out['phase'] = 'REMOTE_READBACK'
            git = _ReadOnly(research_readback_transport(root, cache_root=private/'independent.git'))
            out['observed_remote_commit'] = git.pin()
            _remote(candidates, git, out)
            if out['missing_candidate_count'] or out['conflict_candidate_count']:
                out['reason'] = 'REMOTE_CANDIDATES_MISSING_OR_CONFLICTING'
            else:
                _need(out['verified_candidate_count'] == len(candidates), 'REMOTE_REJECTED')
                out.update(status='EXACT_PRIVATE_RESEARCH_RETENTION_VERIFIED', reason='EXACT_CIPHERTEXT_AT_OBSERVED_COMMIT')
    except Exception as error:
        out['failure_code'] = _failure_code(error)
        out['reason'] = ('CONTEXT_REJECTED' if out['phase'] in ('MAIN_CONTEXT', 'ARTIFACT_METADATA', 'CHECKOUT')
                         else 'PRIVATE_EVIDENCE_REJECTED' if out['phase'] in ('OWNER_AUTHENTICATION', 'PRIVATE_ARCHIVE')
                         else 'REMOTE_READBACK_REJECTED')
    return out
