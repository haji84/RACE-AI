"""Authenticated continuation of the existing official public-SP source.

The historical stop is retained, never released globally. Every source job
replays the actual completed four-arm archive, then atomically appends and
reads back a bounded, non-resumable run claim. Only the exact reviewed old
marker is excepted. Any other stop, changed proof, lost acknowledgement or
untrusted runtime prevents source permission. No provider transport lives here.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import RLock
import time
import uuid

from . import keirin_nationwide_cipher_history as archive
from . import keirin_provider_reconciliation as legacy
from . import keirin_official_run_history as history


GATE_RUN_ID = '44784648369'
GATE_SOURCE_COMMIT = '3b9758b8b561605bea1d01ca6a369e713876c42a'
GATE_CIPHER_SHA256 = 'd6a1d3fcf346ce9947f9e1d41c21b8c32eef4b94fb25de7d0a64a79c698515fe'
GATE_DIGEST = '1822e1379e701decce86c1af5cec08458fb482c422c2e453ba77dbde0b0d91e5'
GATE_BLOB = '1ce3c42d267669e3e03868ae8a50b3bc420624b8'
PRE_CUTOFF_DIGEST = 'a5466bb99505add6f5f32a274459df0edb235826e406a552dbdaff5585e6b461'
PRE_CUTOFF_CIPHER_SHA256 = 'b7cadcd9bb740b72311a5ded1ef708f5878925b84e5c087ce50db2f8efa0a7e3'
PRE_CUTOFF_BLOB = '866e5d384b723a85c4b79633fbc93319365ae48c'
PRE_CUTOFF_RUN_ID = '44679067367'
GATE_DAY = '2026-11-20'
ROOT = 'state/keirin/ab/official-source-continuation/v1'
DECISION_PATH = ROOT+'/decision.json'
POLICY = 'EXISTING_OFFICIAL_PUBLIC_SP_20261121_V1'
DECISION_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_SOURCE_CONTINUATION_DECISION_V1'
CLAIM_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_SOURCE_CONTINUATION_CLAIM_V1'
FINISH_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_SOURCE_CONTINUATION_FINISH_V1'
SOURCE_WORKFLOWS = {
    'official-sp-capture': legacy.WORKFLOW_REF,
    'official-sp-settle': legacy.WORKFLOW_REF,
    'observe-results': 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main',
}
SOURCE_JOBS = frozenset(SOURCE_WORKFLOWS)
FINISH_STATES = frozenset(('COMPLETED', 'PARTIAL', 'FAILED', 'PROVIDER_STOPPED'))
MAX_REQUESTS = 300
DEFAULT_LEASE_SECONDS = 900
MAX_LEASE_SECONDS = 1800
MAX_DAY_CLAIMS = 512
JST = legacy.JST
_ISSUER = object()

# These paths come from the existing calendar/card/history adapters, not from
# endpoint discovery. Query values and form fields are validated separately;
# the caller must still derive them from the observed published controls.
ROUTES = {
    'OFFICIAL_CALENDAR': ('keirin.jp', '/sp/raceschedule', 'GET'),
    'CALENDAR_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0201.js', 'GET'),
    'FORM_SCRIPT': ('keirin.jp', '/sp/static/js/commonSubmit.js', 'GET'),
    'OFFICIAL_RACE_LIST': ('keirin.jp', '/sp/racelist', 'POST'),
    'RACE_LIST_VIEW_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0301_v.js', 'GET'),
    'RACE_LIST_CONTROLLER_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0301_c.js', 'GET'),
    'OFFICIAL_CARD': ('keirin.jp', '/sp/race', 'POST'),
    'OFFICIAL_FINAL_RESULT': ('keirin.jp', '/sp/race', 'POST'),
    'OFFICIAL_HISTORY_RESULT': ('keirin.jp', '/sp/race', 'POST'),
    'LINE_VIEW_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0314_v.js', 'GET'),
    'PREDICTION_FRAME_SCRIPT': ('keirin.jp', '/sp/static/js/FSJ0315.js', 'GET'),
    'PREDICTION_CONTROLLER_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0321_c.js', 'GET'),
    'PUBLIC_JSON_SCRIPT': ('keirin.jp', '/sp/static/js/commonJSON.js', 'GET'),
    'PREDICTION_VIEW_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0321_v.js', 'GET'),
    'OFFICIAL_PREDICTION_TAB': ('keirin.jp', '/sp/json', 'GET'),
    'OFFICIAL_PROFILE': ('keirin.jp', '/sp/racerracentrecord', 'GET'),
    'OFFICIAL_PAYOUT_UNIT': ('www.hofukeirin.jp', '/ticket/', 'GET'),
}
_DISP = {'OFFICIAL_RACE_LIST':'SJ0301', 'OFFICIAL_CARD':'SJ0315',
         'OFFICIAL_FINAL_RESULT':'SJ0326', 'OFFICIAL_HISTORY_RESULT':'SJ0326'}


class ContinuationError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ContinuationError('HOLD_OFFICIAL_CONTINUATION_'+code)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def _pairs(items):
    value = {}
    for key, item in items:
        need(key not in value, 'DUPLICATE_RECEIPT_FIELD')
        value[key] = item
    return value


def _json(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 8192, 'RECEIPT_SIZE_INVALID')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    need(type(value) is dict and _canonical(value) == raw, 'RECEIPT_CANONICAL_BYTES_REQUIRED')
    return value


def _aware(now):
    need(isinstance(now, datetime) and now.utcoffset() is not None, 'CLOCK_INVALID')
    return now.astimezone(timezone.utc)


def _when(value):
    need(type(value) is str, 'CLOCK_INVALID')
    return _aware(datetime.fromisoformat(value))


def _code_lineage(repo, source_commit):
    """Verify ancestry from a depth-one Actions checkout without other refs.

    Fetch only the already authenticated immutable GITHUB_SHA, never all
    branches or a moving default ref. Four bounded expansions obtain at most
    4096 additional generations; unavailable history is a closed admission.
    """
    for deepen in (0, 64, 192, 768, 3072):
        if deepen:
            need(archive._cmd(repo, 'rev-parse', '--is-shallow-repository')[1] == 'true',
                 'PRE_GATE_CODE_REJECTED')
            archive._cmd(repo, 'fetch', '--no-tags', '--deepen='+str(deepen), 'origin', source_commit)
        if archive._cmd(repo, '--no-replace-objects', 'merge-base', '--is-ancestor',
                        GATE_SOURCE_COMMIT, source_commit, okay=True)[0] == 0:
            return
    need(False, 'CODE_ANCESTRY_NOT_VERIFIED_WITHIN_BOUND')


def _runtime(repo, now, source_commit, event_day, *, current_day=True):
    now = _aware(now)
    need(type(event_day) is str and date.fromisoformat(event_day).isoformat() == event_day,
         'DAY_INVALID')
    need(not current_day or now.astimezone(JST).date().isoformat() == event_day, 'CURRENT_DAY_REQUIRED')
    need(type(source_commit) is str and archive.COMMIT.fullmatch(source_commit), 'CODE_IDENTITY_INVALID')
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and
         os.environ.get('GITHUB_REPOSITORY') == archive.REPO and
         os.environ.get('GITHUB_REPOSITORY_ID') == archive.REPO_ID and
         os.environ.get('GITHUB_REF') == 'refs/heads/main' and
         os.environ.get('GITHUB_EVENT_NAME') in ('schedule', 'workflow_dispatch') and
         os.environ.get('GITHUB_JOB') in SOURCE_JOBS and
         os.environ.get('GITHUB_WORKFLOW_REF') == SOURCE_WORKFLOWS.get(os.environ.get('GITHUB_JOB')) and
         os.environ.get('GITHUB_RUN_ATTEMPT') == '1' and
         archive.RUN.fullmatch(os.environ.get('GITHUB_RUN_ID', '')) and
         os.environ.get('GITHUB_SHA') == source_commit and
         os.environ.get('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true', 'TRUSTED_SOURCE_JOB_REQUIRED')
    repo = archive._remote(repo, synthetic_local=False)
    need(archive._cmd(repo, 'rev-parse', 'HEAD')[1] == source_commit, 'CHECKOUT_SHA_CHANGED')
    _code_lineage(repo, source_commit)
    need(archive._cmd(repo, 'rev-parse', 'HEAD')[1] == source_commit, 'CHECKOUT_SHA_CHANGED')
    return Path(repo).resolve()


def _entry(repo, head, path):
    return legacy._entry(repo, head, path)


def _unchanged(repo, head, pins):
    for path, blob in pins.items():
        need(_entry(repo, head, path) == ('100644 blob', blob), 'AUTHENTICATED_EVIDENCE_CHANGED')


def _reconciliation_proof(repo, head, now):
    raw_claim = archive.read_blob_bytes(repo, head, legacy.CLAIM_PATH, max_bytes=8192)
    raw_finish = archive.read_blob_bytes(repo, head, legacy.FINISH_PATH, max_bytes=8192)
    claim, finish = _json(raw_claim), _json(raw_finish)
    need(set(claim) == {'schema','race_id','day_jst','attempt_id','run_id','source_commit',
         'prior_state_commit','legacy_stop_blob','started_at','expires_at','permitted_purposes',
         'max_source_requests','legacy_incident_resolved','general_source_release'} and
         claim['schema'] == legacy.CLAIM_SCHEMA and claim['day_jst'] == legacy.DAY and
         claim['race_id'] == legacy.RACE and claim['run_id'] == GATE_RUN_ID and
         claim['source_commit'] == GATE_SOURCE_COMMIT and
         type(claim['attempt_id']) is str and re.fullmatch(r'[a-f0-9]{32}', claim['attempt_id']) and
         claim['legacy_stop_blob'] == legacy.MARKER_BLOB and
         claim['permitted_purposes'] == list(legacy.PURPOSES) and
         type(claim['max_source_requests']) is int and claim['max_source_requests'] == 8 and
         claim['legacy_incident_resolved'] is False and claim['general_source_release'] is False,
         'RECONCILIATION_CLAIM_UNVERIFIED')
    need(set(finish) == {'schema','race_id','attempt_id','run_id','source_commit','claim_commit',
         'legacy_stop_blob','state','finished_at','requests_consumed','purposes_consumed',
         'legacy_incident_resolved','general_source_release'} and
         finish['schema'] == legacy.FINISH_SCHEMA and finish['race_id'] == legacy.RACE and
         finish['attempt_id'] == claim['attempt_id'] and finish['run_id'] == GATE_RUN_ID and
         finish['source_commit'] == GATE_SOURCE_COMMIT and
         finish['legacy_stop_blob'] == legacy.MARKER_BLOB and finish['state'] == 'FOUR_ARMS_ARCHIVED' and
         type(finish['requests_consumed']) is int and finish['requests_consumed'] == 8 and
         finish['purposes_consumed'] == list(legacy.PURPOSES) and
         finish['legacy_incident_resolved'] is False and finish['general_source_release'] is False,
         'FOUR_ARMS_FINISH_REQUIRED')
    start, expiry, completed = _when(claim['started_at']), _when(claim['expires_at']), _when(finish['finished_at'])
    need(start.astimezone(JST).date().isoformat() == legacy.DAY and
         start < expiry <= start+timedelta(seconds=legacy.LEASE_SECONDS) and
         start <= completed <= min(expiry, now) and
         type(finish['claim_commit']) is str and archive.COMMIT.fullmatch(finish['claim_commit']) and
         type(claim['prior_state_commit']) is str and archive.COMMIT.fullmatch(claim['prior_state_commit']),
         'RECONCILIATION_LINEAGE_INVALID')
    need(archive._cmd(repo, '--no-replace-objects', 'merge-base', '--is-ancestor',
                     claim['prior_state_commit'], finish['claim_commit'], okay=True)[0] == 0,
         'RECONCILIATION_LINEAGE_INVALID')
    legacy._readback(repo, head, finish['claim_commit'], legacy.CLAIM_PATH, raw_claim)
    return {path: _entry(repo, head, path)[1] for path in (legacy.CLAIM_PATH, legacy.FINISH_PATH)}


def _replay_gate(repo, head, owner_private_pem):
    """Bounded exact reads and real owner-key decryption, without provider I/O."""
    from scripts import keirin_official_form_canary as canary
    from scripts import keirin_official_day_pipeline as pipeline
    need(type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 20000,
         'OWNER_PRIVATE_KEY_REQUIRED')
    paths = []
    for digest, cipher_sha, blob, run_id in (
        (GATE_DIGEST, GATE_CIPHER_SHA256, GATE_BLOB, GATE_RUN_ID),
        (PRE_CUTOFF_DIGEST, PRE_CUTOFF_CIPHER_SHA256, PRE_CUTOFF_BLOB, PRE_CUTOFF_RUN_ID)):
        pair = history._refs(GATE_DAY, digest)
        need(_entry(repo, head, pair[0]) == ('100644 blob', blob), 'PINNED_GATE_CIPHER_CHANGED')
        stored = history._read_at(repo, head, GATE_DAY, digest)
        need(stored is not None and sha256(stored['raw_cipher']).hexdigest() == cipher_sha and
             stored['receipt'].get('producer_run_id') == run_id, 'PINNED_GATE_RECEIPT_CHANGED')
        plain = pipeline.restore_private_snapshot_json(history.decrypt_evidence(stored['raw_cipher'], owner_private_pem))
        if digest == GATE_DIGEST:
            saved, saved_receipt = plain, stored['receipt']
        else:
            payload, bundle_receipt = plain, stored['receipt']
        paths.extend(pair)
    need(saved.get('schema') == canary.SETTLEMENT_SCHEMA and
         saved.get('settler_run_id') == GATE_RUN_ID and saved.get('settler_commit') == GATE_SOURCE_COMMIT and
         saved.get('pre_cutoff_evidence_plaintext_sha256') == PRE_CUTOFF_DIGEST and
         payload.get('producer_run_id') == PRE_CUTOFF_RUN_ID,
         'ACTUAL_ARCHIVED_FOUR_ARMS_REQUIRED')
    base_receipt = archive._read_at(repo, head, legacy.RACE, payload['baseline_cipher_sha256'])
    need(base_receipt is not None and base_receipt['producer_run_id'] == payload['producer_run_id'] and
         base_receipt['producer_commit'] == payload['producer_commit'] and
         base_receipt.get('cohort_sha256') == payload['cohort_sha256'] == canary.core.digest(canary.COHORT),
         'FROZEN_ORIGINAL_LINEAGE_INVALID')
    archive._read_conditioned_at(repo, head, legacy.RACE, payload['conditioned_cipher_sha256'],
        payload['baseline_cipher_sha256'], payload['baseline']['prediction_sha256'], payload['cohort_sha256'])
    base_paths, form_paths = archive._refs(legacy.RACE), archive._form_refs(legacy.RACE)
    raw_base = archive.read_blob_bytes(repo, head, base_paths[0])
    raw_form = archive.read_blob_bytes(repo, head, form_paths[0])
    scored = canary.replay_saved_result(payload=payload, bundle_receipt=bundle_receipt,
        saved_pair=(saved, saved_receipt), raw_baseline=raw_base, raw_conditioned=raw_form,
        owner_private_pem=owner_private_pem)
    report = saved.get('safe_report', {})
    need(report.get('state') == 'REAL_FUTURE_CANARY_FOUR_ARMS_COMPARISON_COMPLETE' and
         all(report.get(key) is True for key in ('server_origin_verified','nationwide_expansion_gate_passed',
             'actual_official_result_verified','exact_frozen_originals_authenticated','same_conditions_all_four_arms')) and
         type(report.get('paired_comparable_races')) is int and report['paired_comparable_races'] == 1 and
         scored['comparison']['paired_comparable_races'] == 1 and
         scored['official_result']['monetary_comparison_eligible'] is True and
         scored['official_result']['payout_unit_evidence']['verified_payout_basis_yen'] == 100,
         'FULL_COMPARISON_REPLAY_REQUIRED')
    paths.extend(base_paths+form_paths)
    pins = {}
    for path in paths:
        entry = _entry(repo, head, path)
        need(entry is not None and entry[0] == '100644 blob', 'GATE_ENTRY_INVALID')
        pins[path] = entry[1]
    return pins


def _decision_facts():
    return dict(schema=DECISION_SCHEMA, policy=POLICY, race_id=legacy.RACE,
        gate_run_id=GATE_RUN_ID, gate_source_commit=GATE_SOURCE_COMMIT,
        gate_cipher_sha256=GATE_CIPHER_SHA256, legacy_stop_blob=legacy.MARKER_BLOB,
        permitted_purposes=sorted(ROUTES), max_requests_per_run=MAX_REQUESTS,
        max_lease_seconds=MAX_LEASE_SECONDS, legacy_incident_resolved=False,
        general_source_release=False)


def _checked_decision(raw, now):
    value = _json(raw); facts = _decision_facts()
    need(set(value) == set(facts)|{'created_at','created_by_run','source_commit'} and
         all(value.get(k) == v and type(value.get(k)) is type(v) for k, v in facts.items()) and
         _when(value['created_at']) <= now and
         type(value['created_by_run']) is str and archive.RUN.fullmatch(value['created_by_run']) and
         type(value['source_commit']) is str and archive.COMMIT.fullmatch(value['source_commit']),
         'DECISION_CHANGED_OR_UNVERIFIED')
    return value


def _paths(day, run_id, job):
    stem = ROOT+'/leases/'+day+'/'+run_id+'.'+job
    return stem+'.claim.json', stem+'.finish.json'


def _checked_claim(raw, day, name):
    value = _json(raw)
    need(set(value) == {'schema','policy','event_day','run_id','job','attempt_id','source_commit',
         'started_at','expires_at','max_source_requests','gate_cipher_sha256','general_source_release'} and
         value['schema'] == CLAIM_SCHEMA and value['policy'] == POLICY and value['event_day'] == day and
         type(value['run_id']) is str and archive.RUN.fullmatch(value['run_id']) and
         value['job'] in SOURCE_JOBS and name == value['run_id']+'.'+value['job']+'.claim.json' and
         type(value['attempt_id']) is str and re.fullmatch(r'[a-f0-9]{32}', value['attempt_id']) and
         type(value['source_commit']) is str and archive.COMMIT.fullmatch(value['source_commit']) and
         type(value['max_source_requests']) is int and 1 <= value['max_source_requests'] <= MAX_REQUESTS and
         value['gate_cipher_sha256'] == GATE_CIPHER_SHA256 and value['general_source_release'] is False,
         'RUN_CLAIM_INVALID')
    started, expires = _when(value['started_at']), _when(value['expires_at'])
    midnight = datetime.combine(date.fromisoformat(day)+timedelta(days=1), datetime.min.time(), JST)
    need(started.astimezone(JST).date().isoformat() == day and
         started < expires <= min(started+timedelta(seconds=MAX_LEASE_SECONDS), midnight),
         'RUN_CLAIM_CLOCK_INVALID')
    return value


def _checked_finish(raw, claim):
    value = _json(raw)
    need(set(value) == {'schema','policy','event_day','run_id','job','attempt_id','source_commit',
         'claim_commit','state','finished_at','requests_consumed','purpose_counts','general_source_release'} and
         value['schema'] == FINISH_SCHEMA and value['policy'] == POLICY and
         all(value[k] == claim[k] for k in ('event_day','run_id','job','attempt_id','source_commit')) and
         type(value['claim_commit']) is str and archive.COMMIT.fullmatch(value['claim_commit']) and
         value['state'] in FINISH_STATES and _when(value['finished_at']) >= _when(claim['started_at']) and
         type(value['requests_consumed']) is int and 0 <= value['requests_consumed'] <= claim['max_source_requests'] and
         type(value['purpose_counts']) is dict and set(value['purpose_counts']) <= set(ROUTES) and
         all(type(count) is int and 0 < count <= claim['max_source_requests'] for count in value['purpose_counts'].values()) and
         sum(value['purpose_counts'].values()) == value['requests_consumed'] and
         value['general_source_release'] is False, 'RUN_FINISH_INVALID')
    return value


def _check_run_namespace(repo, head, day, now, claim_path):
    path = ROOT+'/leases/'+day
    entry = _entry(repo, head, path)
    if entry is None:
        return
    need(entry[0] == '040000 tree', 'RUN_DIRECTORY_INVALID')
    _, size = archive._cmd(repo, '--no-replace-objects', 'cat-file', '-s', head+':'+path)
    need(size.isascii() and size.isdecimal() and len(size) <= 6 and int(size) <= 131072,
         'RUN_DIRECTORY_TOO_LARGE')
    _, listed = archive._cmd(repo, '--no-replace-objects', 'ls-tree', '-z', head+':'+path)
    entries = {}
    for row in listed.rstrip('\0').split('\0'):
        match = re.fullmatch(r'100644 blob [a-f0-9]{40}\t([1-9][0-9]{0,16}\.(?:official-sp-(?:capture|settle)|observe-results)\.(?:claim|finish)\.json)', row)
        need(match is not None, 'UNREVIEWED_RUN_ENTRY')
        need(match[1] not in entries and len(entries) < 2*MAX_DAY_CLAIMS, 'RUN_DIRECTORY_TOO_LARGE')
        entries[match[1]] = None
    need(Path(claim_path).name not in entries, 'RUN_ALREADY_CONSUMED')
    claims = [name for name in entries if name.endswith('.claim.json')]
    need(len(claims) < MAX_DAY_CLAIMS, 'DAILY_CLAIM_BUDGET_REACHED')
    for name in entries:
        if name.endswith('.finish.json'):
            need(name.replace('.finish.json','.claim.json') in entries, 'ORPHAN_RUN_FINISH')
    for name in claims:
        claim = _checked_claim(archive.read_blob_bytes(repo, head, path+'/'+name, max_bytes=8192), day, name)
        finish_name = name.replace('.claim.json','.finish.json')
        if finish_name in entries:
            finished = _checked_finish(archive.read_blob_bytes(repo, head, path+'/'+finish_name, max_bytes=8192), claim)
            need(finished['state'] != 'PROVIDER_STOPPED', 'PREVIOUS_RUN_PROVIDER_STOPPED')
        elif claim['job'] == os.environ['GITHUB_JOB']:
            need(now >= _when(claim['expires_at']), 'ANOTHER_SOURCE_LEASE_ACTIVE')


def _append_files(repo, parent, files, message):
    """One ordinary fast-forward CAS; ambiguous failure is never retried."""
    for path in files:
        need(_entry(repo, parent, path) is None, 'RECEIPT_ALREADY_EXISTS')
        parts = path.split('/')
        for length in range(1, len(parts)):
            entry = _entry(repo, parent, '/'.join(parts[:length]))
            need(entry is None or entry[0] == '040000 tree', 'STATE_ANCESTOR_INVALID')
    with TemporaryDirectory(prefix='keirin-official-continuation-') as folder:
        tree = Path(folder)/'branch'
        archive._cmd(repo, 'worktree', 'add', '--detach', str(tree), parent)
        try:
            for path, raw in files.items():
                target = tree/path; target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream: stream.write(raw)
            archive._cmd(tree, 'add', '--', *files)
            archive._cmd(tree, '-c', 'user.name=RACE-AI', '-c',
                         'user.email=race-ai@users.noreply.github.com', 'commit', '-m', message)
            commit = archive._cmd(tree, 'rev-parse', 'HEAD')[1]
            need(archive.COMMIT.fullmatch(commit), 'COMMIT_IDENTITY_INVALID')
            status, _ = archive._cmd(tree, 'push', 'origin', 'HEAD:refs/heads/'+archive.BRANCH, okay=True)
            need(status == 0, 'PUSH_NOT_ACKNOWLEDGED')
        finally:
            archive._cmd(repo, 'worktree', 'remove', '--force', str(tree), okay=True)
    return commit


def _readback(repo, head, commit, files):
    need(archive._cmd(repo, '--no-replace-objects', 'merge-base', '--is-ancestor',
                     commit, head, okay=True)[0] == 0, 'REMOTE_READBACK_FAILED')
    for path, raw in files.items():
        need((_entry(repo, head, path) or ('',))[0] == '100644 blob' and
             archive.read_blob_bytes(repo, head, path, max_bytes=8192) == raw, 'REMOTE_READBACK_FAILED')


def begin(*, repo, now, source_commit, owner_private_pem, event_day,
          max_requests=MAX_REQUESTS, lease_seconds=DEFAULT_LEASE_SECONDS):
    """Authenticate the actual gate, then claim a bounded source run durably."""
    try:
        tick = time.monotonic()
        need(math.isfinite(tick), 'MONOTONIC_CLOCK_INVALID')
        now = _aware(now)
        need(type(max_requests) is int and 1 <= max_requests <= MAX_REQUESTS and
             type(lease_seconds) is int and 1 <= lease_seconds <= MAX_LEASE_SECONDS,
             'BUDGET_INVALID')
        repo = _runtime(repo, now, source_commit, event_day)
        midnight = datetime.combine(date.fromisoformat(event_day)+timedelta(days=1), datetime.min.time(), JST)
        expires = min(now+timedelta(seconds=lease_seconds), midnight).astimezone(timezone.utc)
        deadline = tick+(expires-now).total_seconds()
        run_id, job = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_JOB']
        claim_path, finish_path = _paths(event_day, run_id, job)
        head = archive._refresh(repo)
        legacy._fixed_marker(repo, head, sole=True)
        pins = _reconciliation_proof(repo, head, now)
        _check_run_namespace(repo, head, event_day, now, claim_path)
        pins.update(_replay_gate(repo, head, owner_private_pem))
        _unchanged(repo, head, pins)
        raw_decision = archive.read_blob_bytes(repo, head, DECISION_PATH, max_bytes=8192)
        files = {}
        if raw_decision is None:
            decision = dict(_decision_facts(), created_at=now.isoformat(), created_by_run=run_id, source_commit=source_commit)
            raw_decision = _canonical(decision); files[DECISION_PATH] = raw_decision
        else:
            _checked_decision(raw_decision, now)
        claim = dict(schema=CLAIM_SCHEMA, policy=POLICY, event_day=event_day, run_id=run_id,
            job=job, attempt_id=uuid.uuid4().hex, source_commit=source_commit,
            started_at=now.isoformat(), expires_at=expires.isoformat(), max_source_requests=max_requests,
            gate_cipher_sha256=GATE_CIPHER_SHA256, general_source_release=False)
        claim_raw = _canonical(claim); files[claim_path] = claim_raw
        commit = _append_files(repo, head, files, 'safety(keirin): claim authenticated official SP continuation')
        observed = archive._refresh(repo)
        _readback(repo, observed, commit, {DECISION_PATH:raw_decision, claim_path:claim_raw})
        legacy._fixed_marker(repo, observed, sole=True); _unchanged(repo, observed, pins)
        need(_entry(repo, observed, finish_path) is None, 'RUN_ALREADY_FINISHED')
        after = time.monotonic()
        need(math.isfinite(after) and tick <= after < deadline, 'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        return ContinuationLease(_issuer=_ISSUER, repo=repo, claim=claim, claim_raw=claim_raw,
            claim_commit=commit, decision_raw=raw_decision, pins=pins, tick=after, deadline=deadline)
    except ContinuationError:
        raise
    except Exception:
        raise ContinuationError('HOLD_OFFICIAL_CONTINUATION_ADMISSION_NOT_VERIFIED') from None


def _route(purpose, method, url, fields):
    need(type(purpose) is str and purpose in ROUTES and type(url) is str, 'REQUEST_ROUTE_INVALID')
    host, path, expected_method = ROUTES[purpose]
    need(method == expected_method, 'REQUEST_METHOD_INVALID')
    base = 'https://'+host+path
    if purpose == 'OFFICIAL_PROFILE':
        need(re.fullmatch(re.escape(base)+r'\?snum=[0-9]{6}', url), 'REQUEST_ROUTE_INVALID')
    elif purpose == 'OFFICIAL_PREDICTION_TAB':
        need(re.fullmatch(re.escape(base)+r'\?encp=[A-Za-z0-9_-]{64}&skbn=1&type=JSJ041', url), 'REQUEST_ROUTE_INVALID')
    else:
        need(url == base, 'REQUEST_ROUTE_INVALID')
    if method == 'GET':
        need(fields is None, 'UNEXPECTED_REQUEST_FIELDS')
    else:
        if type(fields) is list or type(fields) is tuple:
            need(len(fields) == 2 and all(type(row) in (list, tuple) and len(row) == 2 for row in fields), 'REQUEST_FIELDS_INVALID')
            need(len({row[0] for row in fields}) == 2, 'REQUEST_FIELDS_INVALID')
            fields = dict(fields)
        need(type(fields) is dict and set(fields) == {'encp','disp'} and
             fields['disp'] == _DISP[purpose] and type(fields['encp']) is str and
             re.fullmatch(r'[A-Za-z0-9_-]{43}', fields['encp']), 'REQUEST_FIELDS_INVALID')


class ContinuationLease:
    """Non-restorable source permit; the caller owns response/denial handling."""
    def __init__(self, *, _issuer, repo, claim, claim_raw, claim_commit, decision_raw, pins, tick, deadline):
        need(_issuer is _ISSUER, 'ISSUER_INVALID')
        self._repo = repo; self._claim = claim; self._raw = claim_raw
        self.claim_commit = claim_commit
        self.claim_path, self.finish_path = _paths(claim['event_day'], claim['run_id'], claim['job'])
        self._decision = decision_raw; self._pins = dict(pins)
        self._last = _when(claim['started_at']); self._expires = _when(claim['expires_at'])
        self._tick = tick; self._deadline = deadline; self._counts = {}
        self._closed = False; self._finished = False; self._lock = RLock()

    @property
    def request_count(self):
        return sum(self._counts.values())

    def remaining_capture_capacity(self, *, now):
        """Read the current capacity without issuing permission or consuming a request."""
        with self._lock:
            need(not self._closed, 'LEASE_CLOSED')
            now = _aware(now)
            tick = time.monotonic()
            need(math.isfinite(tick) and self._tick <= tick and self._last <= now, 'LEASE_CLOCK_CHANGED')
            remaining = min(self._deadline - tick, (self._expires - now).total_seconds())
            return self._claim['max_source_requests'] - self.request_count, max(0, remaining)

    def _active(self, now, repo):
        need(not self._closed, 'LEASE_CLOSED')
        tick = time.monotonic(); now = _aware(now)
        need(math.isfinite(tick) and self._tick <= tick < self._deadline and
             self._last <= now < self._expires, 'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        need(Path(repo).resolve() == self._repo, 'REPO_CHANGED')
        _runtime(self._repo, now, self._claim['source_commit'], self._claim['event_day'])
        need(os.environ['GITHUB_RUN_ID'] == self._claim['run_id'] and
             os.environ['GITHUB_JOB'] == self._claim['job'], 'RUN_IDENTITY_CHANGED')
        head = archive._refresh(self._repo)
        legacy._fixed_marker(self._repo, head, sole=True); _unchanged(self._repo, head, self._pins)
        _readback(self._repo, head, self.claim_commit, {DECISION_PATH:self._decision, self.claim_path:self._raw})
        need(_entry(self._repo, head, self.finish_path) is None, 'RUN_ALREADY_FINISHED')
        after = time.monotonic()
        need(math.isfinite(after) and tick <= after < self._deadline, 'LEASE_EXPIRED_OR_CLOCK_CHANGED')
        self._last = now; self._tick = after

    def assert_active(self, *, repo, now):
        with self._lock:
            try:
                self._active(now, repo)
            except Exception as exc:
                self._closed = True
                if isinstance(exc, ContinuationError): raise
                raise ContinuationError('HOLD_OFFICIAL_CONTINUATION_LEASE_NOT_VERIFIED') from None

    def before_request(self, *, purpose, method, url, now, fields=None):
        with self._lock:
            try:
                _route(purpose, method, url, fields)
                need(self.request_count < self._claim['max_source_requests'], 'REQUEST_BUDGET_REACHED')
                self.assert_active(repo=self._repo, now=now)
                self._counts[purpose] = self._counts.get(purpose, 0)+1
            except Exception as exc:
                self._closed = True
                if isinstance(exc, ContinuationError): raise
                raise ContinuationError('HOLD_OFFICIAL_CONTINUATION_REQUEST_NOT_VERIFIED') from None

    def finish(self, *, state, now):
        with self._lock:
            self._closed = True
            need(not self._finished, 'FINISH_ALREADY_ATTEMPTED'); self._finished = True
            try:
                need(state in FINISH_STATES, 'FINISH_STATE_INVALID')
                now = _aware(now); need(now >= self._last, 'FINISH_CLOCK_CHANGED')
                _runtime(self._repo, now, self._claim['source_commit'], self._claim['event_day'], current_day=False)
                need(os.environ['GITHUB_RUN_ID'] == self._claim['run_id'] and
                     os.environ['GITHUB_JOB'] == self._claim['job'], 'RUN_IDENTITY_CHANGED')
                head = archive._refresh(self._repo)
                legacy._fixed_marker(self._repo, head, sole=False)
                _readback(self._repo, head, self.claim_commit, {DECISION_PATH:self._decision, self.claim_path:self._raw})
                need(_entry(self._repo, head, self.finish_path) is None, 'FINISH_ALREADY_EXISTS')
                result = dict(schema=FINISH_SCHEMA, policy=POLICY, event_day=self._claim['event_day'],
                    run_id=self._claim['run_id'], job=self._claim['job'], attempt_id=self._claim['attempt_id'],
                    source_commit=self._claim['source_commit'], claim_commit=self.claim_commit,
                    state=state, finished_at=now.isoformat(), requests_consumed=self.request_count,
                    purpose_counts=dict(self._counts), general_source_release=False)
                raw = _canonical(result)
                commit = _append_files(self._repo, head, {self.finish_path:raw},
                    'safety(keirin): close bounded official SP continuation')
                observed = archive._refresh(self._repo)
                _readback(self._repo, observed, commit, {self.finish_path:raw})
                legacy._fixed_marker(self._repo, observed, sole=False)
                return result
            except ContinuationError:
                raise
            except Exception:
                raise ContinuationError('HOLD_OFFICIAL_CONTINUATION_FINISH_NOT_VERIFIED') from None
