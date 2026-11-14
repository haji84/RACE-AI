"""Explicit prospective venue inputs, separate from historical training scope.

Only the two literal reviewed, completed Nov6/Nov7 reader witnesses are admitted.
No provider, Git writer, model fit, local-key lookup or source-clock adjustment
exists here. Keys are supplied explicitly by the existing Actions caller.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import hmac
from pathlib import Path
import re

from .actions_contract import canonical, digest, stamp

SCHEMA = 'RACE_AI_PROSPECTIVE_BOAT_VENUE_GRID_INPUT_V1'
CAP_SCHEMA = 'RACE_AI_PROSPECTIVE_BOAT_VENUE_GRID_CAPABILITY_V1'
POLICY = 'EXPLICIT_REPLACE_SUPPORTED_COURSE_FIELDS_RETAIN_PRIOR_V1'
DOMAIN = b'RACE_AI_PROSPECTIVE_BOAT_VENUE_GRID_CAPABILITY_V1\0'
DATASET_SHA = 'c68d32474e1797a0409917fa96ad7393b4a0057bc5081ba31578ac131ec1f254'
# The reviewed witness restored c68d at this immutable commit.
DATASET_COMMIT = '505800f55176867e8a5a06491fcc18eadca8e070'
READBACK_HEAD = 'b569f3c0248c51092a24db1995d5418c2f1e18e4'
READBACK_RUN = 42370578793
READBACK_JOB = 128397771646
METADATA_SHA = 'a7c6ed0a973309804938eeefdb207b69d3b402c24247a7488fe8b09f676f15bf'
LOG_SHA = '34b242bba6a1724e1107452da2f2e283ea71abd35a2ef60328334ba3c3dd7208'
READBACK_LOG_MEMBER = '2_Independently restore encrypted all-racer SQLite.txt'
REQUIRED_STEPS = {
    2: 'Run actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683',
    7: 'Authenticate, decrypt, verify SQLite and lookup every racer',
    10: 'Restore pinned full-period monthly generations and verify every original hash',
    11: 'Restore encrypted venue grid and verify all racer and course cells',
}


def _need(ok, reason):
    if not ok:
        raise ValueError('PROSPECTIVE_BOAT_GRID_'+reason)


def _witnesses():
    # Keep the original constants and capability/MAC bytes compatible. No
    # manifest, environment value or latest pointer can add a registry entry.
    return (
        dict(dataset_sha256=DATASET_SHA, source_commit=DATASET_COMMIT, source_days=7963,
             readback=dict(run_id=READBACK_RUN, run_attempt=1, job_id=READBACK_JOB,
                 head_sha=READBACK_HEAD, metadata_sha256=METADATA_SHA, log_sha256=LOG_SHA)),
        dict(dataset_sha256='7ea4281b5674e605918536ecf905d726d78c721aa0f6c6ed60d4c51d250d5678',
             source_commit='bd932a4d91317c5d8349989a96ddb184938c539d', source_days=7964,
             readback=dict(run_id=42395208517, run_attempt=1, job_id=128471073052,
                 head_sha='b3239877b05c2725af459cec13c1d1501a820a09',
                 metadata_sha256='9fd49f6c2b9b920a06d8c392dbf14a5b3cb94616c513de678a8c6bd7e35a3b32',
                 log_sha256='4f2c015998399c4031502cc072635458609269551f019eeda80d6d1673a0ad1f')),
    )


def _witness(pointer):
    found = [row for row in _witnesses() if pointer['dataset_sha256'] == row['dataset_sha256'] and
             pointer['source_commit'] == row['source_commit']]
    _need(len(found) == 1, 'UNREVIEWED_DATASET')
    return found[0]


def readback_routes():
    """Exact GitHub read routes for the two reviewed witnesses only."""
    routes = set()
    for row in _witnesses():
        witness = row['readback']
        routes.update((f'actions/runs/{witness["run_id"]}/attempts/1',
                       f'actions/runs/{witness["run_id"]}/attempts/1/jobs?per_page=100',
                       f'actions/runs/{witness["run_id"]}/attempts/1/logs',
                       f'actions/jobs/{witness["job_id"]}/logs'))
    return frozenset(routes)


def readback_log_archive(job_log_path):
    """Map a registered job to its documented attempt archive and exact member."""
    matches=[row['readback'] for row in _witnesses() if
        job_log_path==f'actions/jobs/{row["readback"]["job_id"]}/logs']
    _need(len(matches)==1,'UNREVIEWED_LOG_ROUTE')
    selected=matches[0]
    return dict(route=f'actions/runs/{selected["run_id"]}/attempts/1/logs',
        member=READBACK_LOG_MEMBER,log_sha256=selected['log_sha256'])


def validate_manifest(value):
    from .boat_venue_learning import _pin
    _need(type(value) is dict and set(value) == {'schema', 'dataset_pointer', 'readback',
          'observed_only', 'course_feature_policy'} and value['schema'] == SCHEMA and
          value['observed_only'] is True and value['course_feature_policy'] == POLICY, 'MANIFEST')
    pointer = value['dataset_pointer']
    _need(type(pointer) is dict and set(pointer) == {'schema', 'status', 'repository_id',
          'source_commit', 'dataset_path', 'dataset_sha256'}, 'DATASET_POINTER')
    _pin(pointer)
    expected = _witness(pointer)['readback']
    _need(type(value['readback']) is dict and value['readback'] == expected, 'UNREVIEWED_READBACK')
    return deepcopy(value)


def _take(value, names):
    _need(type(value) is dict and all(name in value for name in names), 'ACTUAL_METADATA')
    return {name: deepcopy(value[name]) for name in names}


def verify_readback(manifest, run, jobs, log, *, now):
    """Authenticate actual API responses; mutable embedded PR heads are omitted."""
    validate_manifest(manifest)
    witness = _witness(manifest['dataset_pointer'])['readback']
    _need(type(now) is datetime and now.utcoffset() is not None, 'PHYSICAL_CLOCK')
    _need(type(jobs) is dict and type(jobs.get('jobs')) is list and
          type(jobs.get('total_count')) is int and jobs['total_count'] == len(jobs['jobs']) <= 100,
          'ACTUAL_JOBS')
    found = [job for job in jobs['jobs'] if type(job) is dict and job.get('id') == witness['job_id']]
    _need(len(found) == 1, 'READBACK_JOB')
    job = found[0]
    run_part = _take(run, ('id', 'workflow_id', 'path', 'event', 'head_sha', 'head_branch', 'run_attempt'))
    for name in ('actor', 'triggering_actor'):
        run_part[name] = _take(run.get(name), ('id', 'login'))
    for name in ('repository', 'head_repository'):
        run_part[name] = _take(run.get(name), ('id', 'full_name'))
    prs = run.get('pull_requests')
    _need(type(prs) is list and all(type(p) is dict and type(p.get('number')) is int for p in prs),
          'READBACK_PR')
    run_part['pull_request_numbers'] = sorted(p['number'] for p in prs)
    job_part = _take(job, ('id', 'run_id', 'run_attempt', 'head_sha', 'name', 'status',
                          'conclusion', 'started_at', 'completed_at'))
    steps = job.get('steps')
    _need(type(steps) is list and len(steps) <= 100 and all(type(s) is dict for s in steps), 'READBACK_STEPS')
    required = []
    for number, name in REQUIRED_STEPS.items():
        matched = [s for s in steps if s.get('number') == number]
        _need(len(matched) == 1 and matched[0].get('name') == name and
              matched[0].get('status') == 'completed' and matched[0].get('conclusion') == 'success',
              'READBACK_STEP_NOT_VERIFIED')
        required.append(_take(matched[0], ('number', 'name', 'status', 'conclusion', 'started_at', 'completed_at')))
    projection = dict(schema='RACE_AI_REVIEWED_BOAT_GRID_READBACK_METADATA_V1',
                      run=run_part, job=job_part, required_steps=required)
    # This literal reviewed projection binds repo/owner/HEAD/attempt/job and all
    # required statuses/times. A success-only or operator-supplied receipt fails.
    _need(digest(projection) == witness['metadata_sha256'], 'READBACK_METADATA_MISMATCH')
    _need(type(log) is bytes and 0 < len(log) <= 2*1024*1024 and sha256(log).hexdigest() == witness['log_sha256'],
          'READBACK_LOG_MISMATCH')
    _need(stamp(job_part['completed_at']) <= now, 'READBACK_FROM_FUTURE')
    return dict(metadata_sha256=witness['metadata_sha256'], log_sha256=witness['log_sha256'],
                completed_at=job_part['completed_at'], projection=projection)


def prepare_capability(manifest, folder, repo, *, gh, clock, run_id, head_sha, round_no, key):
    """Read only GitHub/state bytes before source collection; reject HOLDs."""
    from .boat_venue_dataset import readback_dataset, _manifest, _sha
    from .permissioned_source_delivery import read_json_bytes
    _key(key); validate_manifest(manifest)
    row = _witness(manifest['dataset_pointer']); witness = row['readback']
    started = clock()
    def read(path, limit):
        raw = gh(path)
        _need(type(raw) is bytes and 0 < len(raw) <= limit, 'GITHUB_READ_BOUND')
        return raw
    run = read_json_bytes(read(f'actions/runs/{witness["run_id"]}/attempts/1', 2*1024*1024))
    jobs = read_json_bytes(read(f'actions/runs/{witness["run_id"]}/attempts/1/jobs?per_page=100', 8*1024*1024))
    log = read(f'actions/jobs/{witness["job_id"]}/logs', 2*1024*1024)
    proof = verify_readback(manifest, run, jobs, log, now=started)
    report = readback_dataset(manifest['dataset_pointer'], folder, repo)
    _need(type(report) is dict and report.get('status') == 'ENCRYPTED_ALL_VENUE_GRID_READBACK_VERIFIED' and
          report.get('plaintext_published') is False and
          (report.get('verified_cells'), report.get('known_racers'), report.get('venues'), report.get('source_days')) ==
          (63432, 2643, 24, row['source_days']), 'DATASET_RESTORE_NOT_READY')
    raw, state = _manifest(folder)
    _need(_sha(raw) == manifest['dataset_pointer']['dataset_sha256'], 'RESTORED_DATASET_CHANGED')
    verified = clock()
    _need(type(started) is datetime and type(verified) is datetime and
          started.utcoffset() is not None and verified.utcoffset() is not None and verified >= started,
          'PRELOAD_PHYSICAL_CLOCK')
    return seal_capability(manifest, proof, folder, available_at=state['available_at'],
        verified_at=verified.isoformat(), run_id=run_id, head_sha=head_sha, round_no=round_no, key=key)


def _private_folder(folder):
    path = Path(folder).absolute()
    _need(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_dir() and
          not path.stat().st_mode & 0o077 and not any((p/'.git').exists() for p in path.parents),
          'PRIVATE_DATASET_FOLDER')
    return path


def _key(key):
    _need(type(key) is bytes and len(key) == 32, 'EXPLICIT_ACTIONS_KEY')
    return key


def _mac(data, key):
    return hmac.new(_key(key), DOMAIN+canonical(data).encode(), sha256).hexdigest()


def seal_capability(manifest, proof, folder, *, available_at, verified_at, run_id, head_sha, round_no, key):
    validate_manifest(manifest)
    witness = _witness(manifest['dataset_pointer'])['readback']
    _need(type(proof) is dict and set(proof) == {'metadata_sha256', 'log_sha256', 'completed_at', 'projection'} and
          proof['metadata_sha256'] == digest(proof['projection']) == witness['metadata_sha256'] and
          proof['log_sha256'] == witness['log_sha256'] and
          proof['completed_at'] == proof['projection']['job']['completed_at'], 'READBACK_PROOF')
    _need(type(run_id) is str and re.fullmatch('[1-9][0-9]{0,19}', run_id) and
          type(head_sha) is str and re.fullmatch('[a-f0-9]{40}', head_sha) and
          type(round_no) is int and 1 <= round_no <= 999999, 'CURRENT_RUN_BINDING')
    _need(stamp(available_at) <= stamp(verified_at) and
          stamp(proof['completed_at']) < stamp(verified_at), 'PRELOAD_CLOCK')
    data = dict(schema=CAP_SCHEMA, manifest=deepcopy(manifest), proof=deepcopy(proof),
                dataset_folder=str(_private_folder(folder)), available_at=available_at,
                verified_at=verified_at, run_id=run_id, head_sha=head_sha, round_no=round_no)
    return dict(data=data, mac=_mac(data, key))


class _VerifiedGrid:
    def __init__(self, record):
        self._record = deepcopy(record)
        self._binding = digest(record)

    @property
    def record(self):
        return deepcopy(self._record)


def open_capability(record, *, run_id, head_sha, round_no, key):
    _need(type(record) is dict and set(record) == {'data', 'mac'} and type(record['data']) is dict and
          type(record['mac']) is str and hmac.compare_digest(record['mac'], _mac(record['data'], key)),
          'CAPABILITY_AUTHENTICATION')
    data = record['data']
    _need(set(data) == {'schema', 'manifest', 'proof', 'dataset_folder', 'available_at', 'verified_at',
          'run_id', 'head_sha', 'round_no'} and data['schema'] == CAP_SCHEMA and
          (data['run_id'], data['head_sha'], data['round_no']) == (run_id, head_sha, round_no),
          'CAPABILITY_RUN_BINDING')
    _need(record == seal_capability(data['manifest'], data['proof'], data['dataset_folder'],
          available_at=data['available_at'], verified_at=data['verified_at'], run_id=run_id,
          head_sha=head_sha, round_no=round_no, key=key), 'CAPABILITY_BINDING')
    return _VerifiedGrid(record)


def require_before_source(capability, source_as_of):
    _need(type(capability) is _VerifiedGrid and digest(capability._record) == capability._binding,
          'AUTHENTICATED_CAPABILITY_REQUIRED')
    data = capability._record['data']; asof = stamp(source_as_of)
    _need(stamp(data['available_at']) < asof and stamp(data['verified_at']) < asof and
          stamp(data['proof']['completed_at'])+timedelta(seconds=1) < asof,
          'SOURCE_PRECEDES_ADMITTED_GRID')
    return deepcopy(data)


def enrich_native_inputs(built, capability, *, source_as_of):
    """Copy fresh native inputs; explicit replacement retains exact prior terms.

    Only existing supported course terms are projected. All other history,
    current-source observations, rosters, model parameters and clocks remain.
    Evidence is carried inside each new capsule, including unchanged families.
    """
    from .boat_venue_dataset import _manifest, _sha
    from .boat_venue_feature_adapter import enrich_venue_snapshot, RIGHTS
    from .boat_venue_learning import _pin
    from .boat_all_model_inputs import shared_snapshot_from_observed
    data = require_before_source(capability, source_as_of)
    _need(type(built) is dict and built.get('as_of') == source_as_of and built.get('stage') == 'P1' and
          type(built.get('native_inputs')) is dict and 'prospective_grid_evidence' not in built,
          'FRESH_NATIVE_INPUTS_REQUIRED')
    old = built['native_inputs']
    _need('boat_observed' in old and all('prospective_grid_evidence' not in p for p in old.values()),
          'UNENRICHED_CURRENT_OBSERVED_INPUT_REQUIRED')
    folder = _private_folder(data['dataset_folder']); raw, state = _manifest(folder)
    pointer = data['manifest']['dataset_pointer']
    _need(_sha(raw) == pointer['dataset_sha256'] and state['available_at'] == data['available_at'],
          'RESTORED_DATASET_CHANGED')
    snapshot = old['boat_observed']['snapshot']
    _need(snapshot['as_of'] == source_as_of, 'ORIGINAL_SOURCE_CLOCK_CHANGED')
    source_url = _pin(pointer)
    enriched = enrich_venue_snapshot(snapshot, folder, pointer, verified_at=data['verified_at'],
        observed_only=True, allow_source=lambda ref, rights, purpose:
            (ref, rights, purpose) == (source_url, RIGHTS, 'analysis'))
    mapped = shared_snapshot_from_observed(enriched['snapshot'])
    out = deepcopy(built); native = out['native_inputs']; prior = {}
    native['boat_observed']['snapshot'] = enriched['snapshot']
    for group in ('shared', 'shared_learned'):
        if group not in native: continue
        rows = {p['number']: p for p in mapped['participants']}
        prior[group] = {}
        for row in native[group]['snapshot']['participants']:
            before = {}; replacement = rows[row['number']]
            for name in ('course_compatibility', 'lane_course_fit', 'local_course_history'):
                before[name] = dict(feature=deepcopy(row['features'].get(name)), missing=row['missing'].get(name))
                row['features'].pop(name, None); row['missing'].pop(name, None)
                if name in replacement['features']: row['features'][name] = deepcopy(replacement['features'][name])
                else: row['missing'][name] = replacement['missing'].get(name, 'NOT_AVAILABLE')
            prior[group][str(row['number'])] = before
    if 'boat_full' in native:
        prior['boat_full'] = {}; rows = {p['lane']: p for p in enriched['snapshot']['participants']}
        source = enriched['snapshot']['sources'][-1]
        evidence = dict(source_ref=source['source_url'], source_rights_ref=source['source_rights_ref'],
            source_sha256=source['source_sha256'], captured_at=source['captured_at'], published_at=None)
        native['boat_full']['source_evidence'].append(evidence)
        for row in native['boat_full']['snapshot']['entrants']:
            name = 'course_suitability_rating'
            prior['boat_full'][str(row['lane'])] = dict(feature=row['features'].get(name), missing=row['missing'].get(name),
                source_ref=row['source_ref'], captured_at=row['captured_at'])
            row['features'].pop(name, None); row['missing'].pop(name, None)
            finish = rows[row['lane']]['features'].get('course_mean_finish')
            if finish is not None:
                row['features'][name] = 100*(6-finish['value'])/5
                # A composite source binds unchanged current measurements and
                # the new course term. Other feature values are not replaced.
                members = [e for e in native['boat_full']['source_evidence'] if e['source_ref'] == row['source_ref']]+[evidence]
                composite = dict(source_ref='urn:race-ai:prospective-course:'+digest(members),
                    source_rights_ref=evidence['source_rights_ref'], source_sha256=digest(members),
                    published_at=None, captured_at=max((m['captured_at'] for m in members),key=stamp), source_members=members)
                native['boat_full']['source_evidence'].append(composite)
                row['source_ref'] = composite['source_ref']; row['captured_at'] = composite['captured_at']
            else: row['missing'][name] = 'NOT_AVAILABLE'
    prior['boat_observed'] = [{k:deepcopy(p[k]) for k in ('lane', 'features', 'missing')} for p in snapshot['participants']]
    audit = dict(schema='RACE_AI_PROSPECTIVE_BOAT_GRID_NATIVE_EVIDENCE_V1',
        dataset_pointer=deepcopy(pointer), manifest=deepcopy(data['manifest']), readback_proof=deepcopy(data['proof']),
        dataset_available_at=data['available_at'], dataset_verified_at=data['verified_at'],
        capture_run_id=data['run_id'], capture_head_sha=data['head_sha'], capture_round_no=data['round_no'],
        capability_sha256=capability._binding,
        original_source_as_of=source_as_of, new_native_as_of=source_as_of,
        original_native_inputs_sha256=digest(old), explicit_replaced_course_terms=prior,
        venue_evidence=deepcopy(enriched['venue_evidence']), actual_entry_course_inferred=False,
        recent_history_replaced=False, model_coefficients_changed=False, formal_backtest_eligible=False)
    out['prospective_grid_evidence'] = audit
    for value in native.values(): value['prospective_grid_evidence'] = deepcopy(audit)
    # The engine obtains the source authorizer's exact scope from this list.
    source = enriched['snapshot']['sources'][-1]
    out['source_evidence'].append(dict(source_ref=source['source_url'], source_rights_ref=source['source_rights_ref'],
        source_sha256=source['source_sha256'], captured_at=source['captured_at'], published_at=None))
    if 'boat_full' in native:
        out['source_evidence'].extend(deepcopy(native['boat_full']['source_evidence']))
    return out


def prospective_requests(requests, *, now):
    """Keep complete fourteen-cell originals; never re-enrich saved capsules."""
    from . import all_existing_model_registry as registry
    from .all_existing_model_learning import _sources
    from .existing_model_dispatch import _race_key
    _need(type(now) is datetime and now.utcoffset() is not None and
          type(requests) is list and 0 < len(requests) <= 14*288, 'CARRIER_INPUTS')
    expected = {c['cell_key'] for c in registry.active_cells() if c['sport'] == 'boat'}
    _need(len(expected) == 14, 'EXACT_FOURTEEN_REGISTRY')
    refs = set().union(*(_sources(row.get('native_payload', {})) for row in requests if type(row) is dict))
    allow = lambda ref, rights, purpose: purpose == 'analysis' and (ref, rights) in refs
    cases = {}
    for row in requests:
        _need(type(row) is dict and set(row) == {'cell_key', 'native_payload'} and
              row['cell_key'] in expected and type(row['native_payload']) is dict, 'CARRIER_ENVELOPE')
        native = row['native_payload']; audit = native.get('prospective_grid_evidence')
        _need(type(audit) is dict and audit.get('schema') == 'RACE_AI_PROSPECTIVE_BOAT_GRID_NATIVE_EVIDENCE_V1',
              'CARRIER_GRID_EVIDENCE')
        manifest = validate_manifest(audit.get('manifest'))
        witness = _witness(manifest['dataset_pointer'])['readback']
        proof = audit.get('readback_proof')
        _need(type(proof) is dict and set(proof) == {'metadata_sha256', 'log_sha256', 'completed_at', 'projection'} and
              proof['metadata_sha256'] == digest(proof['projection']) == witness['metadata_sha256'] and
              proof['log_sha256'] == witness['log_sha256'] and
              proof['completed_at'] == proof['projection']['job']['completed_at'] and
              audit.get('dataset_pointer') == manifest['dataset_pointer'],
              'CARRIER_GRID_PROOF')
        info = registry.validate_payload(row['cell_key'][5:], 'boat', native, at=now, allow_source=allow)
        asof = stamp(info['as_of']); master = stamp(audit['original_source_as_of'])
        _need(info['stage'] == 'P1' and audit['new_native_as_of'] == audit['original_source_as_of'] and
              stamp(audit['dataset_available_at']) < asof and stamp(audit['dataset_verified_at']) < asof == master <= now and
              stamp(proof['completed_at'])+timedelta(seconds=1) < asof and
              now+timedelta(seconds=600) < stamp(info['race_cutoff_at']), 'CARRIER_ORIGINAL_CLOCK')
        race = _race_key(info['race_id'], 'boat'); case = cases.setdefault(race, {})
        _need(row['cell_key'] not in case, 'CARRIER_DUPLICATE_CELL')
        case[row['cell_key']] = (info, audit)
    for case in cases.values():
        _need(set(case) == expected, 'CARRIER_INCOMPLETE_FOURTEEN')
        first, evidence = next(iter(case.values()))
        _need(all(all(info[k] == first[k] for k in ('roster', 'race_cutoff_at', 'scope')) and audit == evidence
                  for info, audit in case.values()), 'CARRIER_RACE_OR_GRID_CONFLICT')
    return deepcopy(requests)
