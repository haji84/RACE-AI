"""Keyless proof of explicitly declared, unused failed source issuers.

Only the caller's fixed GitHub reader is used. This verifier creates no grant,
key lookup, source request, rerun, state mutation or replacement original.
"""
from copy import deepcopy
from hashlib import sha256
import io
import re
import stat
import zipfile
import zlib

from .actions_contract import digest
from .boat_all_model_store import MAX_WIRE
from . import all_existing_model_official_issue as I
from .permissioned_source_delivery import read_json_bytes

SCHEMA = 'RACE_AI_OFFICIAL_FAILED_ISSUE_DISPOSITIONS_V1'
JOB_NAME = 'Source-free exact-run recovery issuer'
PROOF_MEMBER = 'official-result-recovery-issue-proof.json'
MAX_PROOF_ARCHIVE = 1024 * 1024
MAX_PROOF_JSON = 128 * 1024


def need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_ISSUE_FAILED_' + reason)


def _json(raw, limit):
    need(type(raw) is bytes and 0 < len(raw) <= limit, 'JSON_BOUND')
    value = read_json_bytes(raw)
    need(type(value) is dict, 'JSON_OBJECT')
    return value


def _list(document, field, *, nonempty=True):
    rows = document.get(field) if type(document) is dict else None
    count = document.get('total_count') if type(document) is dict else None
    need(type(rows) is list and type(count) is int and count == len(rows)
         and (1 if nonempty else 0) <= count <= 100, 'COMPLETE_' + field.upper())
    ids = [row.get('id') if type(row) is dict else None for row in rows]
    need(all(I._id(ident) for ident in ids) and len(set(ids)) == len(ids), 'UNIQUE_' + field.upper())
    return rows


def _run(value, head, *, run_id=None):
    receipt = I.run_scope(value)
    need(receipt['head_sha'] == head and (run_id is None or receipt['id'] == run_id), 'RUN_BINDING')
    return receipt


def _issuers(reader, head):
    path = 'actions/workflows/' + str(I.WORKFLOW) + '/runs?head_sha=' + head + '&event=pull_request&per_page=100'
    rows = _list(reader.json(path), 'workflow_runs')
    for run in rows:
        scope = _run(run, head)
        need(scope['run_attempt'] == 1, 'ISSUER_ATTEMPT_ONE')
    return sorted(rows, key=lambda row: row['id'])


def _job(reader, run):
    ident = run['id'];head = run['head_sha']
    jobs = _list(reader.json('actions/runs/' + str(ident) + '/attempts/1/jobs?per_page=100'), 'jobs')
    need(all(type(j.get('run_id')) is int and j['run_id'] == ident and type(j.get('run_attempt')) is int
             and j['run_attempt'] == 1 and j.get('head_sha') == head for j in jobs), 'ISSUER_JOB_BINDING')
    selected = [j for j in jobs if j.get('name') == JOB_NAME]
    need(len(selected) == 1 and selected[0].get('status') == 'completed'
         and selected[0].get('conclusion') == 'success', 'TERMINAL_ISSUER_JOB_REQUIRED')
    return selected[0]


def _metadata(value, run, name, now):
    need(type(value) is dict and I._id(value.get('id')) and value.get('name') == name
         and value.get('expired') is False and type(value.get('size_in_bytes')) is int
         and 0 < value['size_in_bytes'] <= MAX_PROOF_ARCHIVE and type(value.get('digest')) is str
         and re.fullmatch(r'sha256:[a-f0-9]{64}', value['digest']), 'PROOF_METADATA')
    workflow = value.get('workflow_run')
    need(type(workflow) is dict and type(workflow.get('id')) is int and workflow['id'] == run['id']
         and workflow.get('head_sha') == run['head_sha'] and all(type(workflow.get(k)) is int
             and workflow[k] == I.REPOSITORY_ID for k in ('repository_id', 'head_repository_id')),
         'PROOF_METADATA_RUN')
    need(I.R.clock(value.get('created_at')) <= now < I.R.clock(value.get('expires_at')), 'PROOF_CLOCK')
    return {k: deepcopy(value[k]) for k in ('id', 'name', 'expired', 'size_in_bytes', 'digest',
                                           'created_at', 'expires_at', 'workflow_run')}


def _proof(reader, run, now):
    name = 'official-result-recovery-issue-proof-' + str(run['id']) + '-1'
    rows = _list(reader.json('actions/runs/' + str(run['id']) + '/artifacts?per_page=100'),
                 'artifacts', nonempty=False)
    selected = [row for row in rows if row.get('name') == name]
    need(len(selected) == 1, 'EXACT_PROOF_ARTIFACT_REQUIRED')
    metadata = _metadata(selected[0], run, name, now)
    archive = reader.archive(dict(id=metadata['id'], digest=metadata['digest'],
        run_id=run['id'], head_sha=run['head_sha']))
    need(type(archive) is dict and type(archive.get('raw')) is bytes
         and _metadata(archive.get('metadata'), run, name, now) == metadata, 'ACTUAL_PROOF_METADATA')
    raw = archive['raw']
    need(len(raw) == metadata['size_in_bytes'] and 'sha256:' + sha256(raw).hexdigest() == metadata['digest']
         and raw.startswith(b'PK\x03\x04') and len(raw) >= 22 and raw[-22:-18] == b'PK\x05\x06'
         and raw[-2:] == b'\0\0', 'PROOF_ARCHIVE_BYTES')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
            entries = zipped.infolist()
            need(len(entries) == 1 and not zipped.comment, 'PROOF_EXACT_MEMBER')
            entry = entries[0]
            need(entry.filename == entry.orig_filename == PROOF_MEMBER and
                 stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG) and not entry.flag_bits & 0x41
                 and entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                 and 0 < entry.file_size <= MAX_PROOF_JSON, 'PROOF_EXACT_MEMBER')
            with zipped.open(entry) as stream:
                body = stream.read(MAX_PROOF_JSON + 1)
            need(len(body) == entry.file_size, 'PROOF_MEMBER_SIZE')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error):
        raise ValueError('OFFICIAL_ISSUE_FAILED_PROOF_ZIP') from None
    return _json(body, MAX_PROOF_JSON), dict(artifact_id=metadata['id'], artifact_digest=metadata['digest'],
                                           proof_sha256=sha256(body).hexdigest())


def _privacy(proof):
    need(proof.get('source_requests') == 0 and type(proof.get('source_requests')) is int
         and all(proof.get(k) is False for k in ('plaintext_published', 'production_promoted', 'actual_purchases')),
         'ZERO_SOURCE_AND_PRIVATE_REQUIRED')


def _hold(proof):
    _privacy(proof)
    need(proof.get('schema') in (I.PROOF, I.PROOF_V2) and proof.get('ready') is False
         and proof.get('state') == 'HOLD_FIXED_RECOVERY_ISSUANCE'
         and proof.get('independent_git_readback_verified') is False and type(proof.get('reason')) is str
         and re.fullmatch(r'[A-Z][A-Z0-9_]{1,199}', proof['reason'])
         and 'publication_attempt' not in proof and 'UNCONFIRMED' not in proof['reason'],
         'EXPLICIT_UNUSED_HOLD_REQUIRED')


def _anchor(snapshot, descriptor):
    head = descriptor['intent_head_sha']
    raw = snapshot.read(head, I.ISSUE_PATH, 16384)
    need(type(raw) is bytes and sha256(raw).hexdigest() == descriptor['issue_blob_sha256'], 'ISSUE_BYTES')
    old = I.validate_issue_request(_json(raw, 16384));facts = snapshot.commit_facts(head)
    parent = old['intent_parent_sha'] if old['schema'] == I.SCHEMA_V2 else old['target']['head_sha']
    need(facts.get('head_sha') == head and facts.get('parents') == [parent]
         and facts.get('changed_files') == [I.ISSUE_PATH] and type(facts.get('subject')) is str
         and facts['subject'].startswith(I.PREFIX) and snapshot.is_ancestor(parent, head)
         and (old['schema'] == I.SCHEMA or snapshot.is_ancestor(old['target']['head_sha'], parent)),
         'ISSUE_LINEAGE')
    recovery = snapshot.read(old['target']['head_sha'], I.REQUEST_PATH, 32768)
    request = _json(recovery, 32768)
    need(sha256(recovery).hexdigest() == old['recovery_request_blob_sha256']
         and digest(request) == old['recovery_request_sha256'], 'RECOVERY_BYTES')
    return old, request


def _first(reader, target, now):
    ident = str(target['run_id'])
    first = _run(reader.json('actions/runs/' + ident + '/attempts/1'),
                 target['head_sha'], run_id=target['run_id'])
    need(first['run_attempt'] == 1 and first['status'] == 'completed' and first['conclusion'] == 'success'
         and I.R.clock(first['run_started_at']) <= I.R.clock(first['updated_at']) <= now,
         'UNUSED_FIRST_ATTEMPT_REQUIRED')
    return first


def _hold_receipts(reader, head, now):
    proofs = []
    for run in _issuers(reader, head):
        job = _job(reader, run);proof, receipt = _proof(reader, run, now);_hold(proof)
        proofs.append(dict(issuer_run_id=run['id'], issuer_job_id=job['id'], **receipt, reason=proof['reason']))
    return proofs


def _verified_row(descriptor, old, first, proofs):
    return dict(**descriptor, target=deepcopy(old['target']), recovery_request_sha256=old['recovery_request_sha256'],
        recovery_request_blob_sha256=old['recovery_request_blob_sha256'], target_first_attempt=first, issuer_proofs=proofs)


def _unused(snapshot, descriptor, reader, now):
    old, request = _anchor(snapshot, descriptor);target = old['target'];ident = str(target['run_id'])
    current = _run(reader.json('actions/runs/' + ident), target['head_sha'], run_id=target['run_id'])
    first = _first(reader, target, now)
    need(current == first, 'UNUSED_FIRST_ATTEMPT_REQUIRED')
    path = I.R.capsule_path(request, target['head_sha'], target['run_id'])
    fresh = reader.head();need(I._hex(fresh), 'FRESH_STATE_HEAD')
    need(reader.read_file(fresh, path, MAX_WIRE) is None, 'CANONICAL_CAPSULE_MUST_BE_ABSENT')
    return _verified_row(descriptor, old, first, _hold_receipts(reader, descriptor['intent_head_sha'], now))


def _ready(proof, run, issue, binding, outer, failed):
    _privacy(proof)
    need(proof.get('schema') == I.PROOF_V2 and proof.get('ready') is True
         and proof.get('state') == 'CONSUMED_CAPSULE_PUBLISHED_AND_READ_BACK'
         and proof.get('independent_git_readback_verified') is True
         and 'publication_attempt' not in proof, 'CURRENT_READY_PROOF_REQUIRED')
    expected = dict(repository_id=I.REPOSITORY_ID, workflow_id=I.WORKFLOW, pull_request=71,
        issuer_run_id=run['id'], issuer_run_attempt=1, issuer_actor_id=I.OWNER_ID)
    need(all(type(proof.get(k)) is int and proof[k] == value for k, value in expected.items())
         and proof.get('issuer_head_sha') == binding['intent_head_sha']
         and proof.get('tested_execution_head_sha') == issue['tested_execution_head_sha']
         and proof.get('issue_request_sha256') == digest(issue)
         and proof.get('recovery_request_sha256') == issue['recovery_request_sha256']
         and type(proof.get('target')) is dict and set(proof['target']) == {'head_sha', 'run_id', 'run_attempt'}
         and type(proof['target'].get('run_id')) is int and type(proof['target'].get('run_attempt')) is int
         and proof['target'] == issue['target'] and type(proof.get('target_first_viewer_job_id')) is int
         and proof['target_first_viewer_job_id'] == issue['target_first_viewer_job_id'], 'CURRENT_READY_SCOPE')
    rows = proof.get('failed_issue_dispositions')
    need(type(rows) is list and len(rows) == len(failed) and type(proof.get('verified_failed_issue_count')) is int
         and proof['verified_failed_issue_count'] == len(rows)
         and proof.get('failed_issue_dispositions_sha256') == digest(rows)
         and all(type(row) is dict and row.get('intent_head_sha') == descriptor['intent_head_sha']
             and row.get('issue_blob_sha256') == descriptor['issue_blob_sha256']
             for row, descriptor in zip(rows, failed)), 'CURRENT_READY_FAILED_LIST')
    need(proof.get('outer_capsule_sha256') == sha256(outer).hexdigest()
         and I._hex(proof.get('inner_capsule_sha256'), 64)
         and proof.get('source_frozen_binding_sha256') == digest(binding), 'CURRENT_READY_CAPSULE_BINDING')
    return deepcopy(rows)


def _published_rows(snapshot, issue, reader, now):
    from .all_existing_model_official_frozen_capsule import validate_binding
    facts = snapshot.facts;binding = validate_binding(facts.get('source_frozen_binding'))
    source = facts.get('source_issue_head')
    need(I._hex(source) and source == binding['intent_head_sha'] and binding['target'] == issue['target']
         and binding['intent_parent_sha'] == issue['intent_parent_sha']
         and source not in {d['intent_head_sha'] for d in issue['failed_issue_dispositions']}, 'CURRENT_SOURCE_BINDING')
    current, request = _anchor(snapshot, dict(intent_head_sha=source,
        issue_blob_sha256=binding['issue_request_blob_sha256']))
    need(current == issue and binding['recovery_request_blob_sha256'] == issue['recovery_request_blob_sha256'],
         'CURRENT_SOURCE_ISSUE')
    target = issue['target']
    actual = _run(reader.json('actions/runs/' + str(target['run_id'])), target['head_sha'], run_id=target['run_id'])
    need(actual['run_attempt'] == 2 and actual['status'] in ('queued', 'in_progress', 'completed')
         and (actual['status'] != 'completed' or actual['conclusion'] == 'success'), 'CURRENT_ACTUAL_SOURCE_TWO')
    fresh = reader.head();need(I._hex(fresh), 'FRESH_STATE_HEAD')
    outer = reader.read_file(fresh, I.R.capsule_path(request, target['head_sha'], target['run_id']), MAX_WIRE)
    need(type(outer) is bytes and 0 < len(outer) <= MAX_WIRE, 'CURRENT_CANONICAL_CAPSULE_REQUIRED')
    ready = []
    for run in _issuers(reader, source):
        _job(reader, run);proof, _ = _proof(reader, run, now)
        if proof.get('ready') is True:
            ready.append(_ready(proof, run, issue, binding, outer, issue['failed_issue_dispositions']))
        else:
            _hold(proof)
    need(len(ready) == 1, 'ONE_CURRENT_READY_PROOF_REQUIRED')
    return ready[0]


def verify_failed_dispositions(snapshot, issue, reader, *, now, published=False):
    """Preserve explicit failed anchors; missing or uncertain evidence is HOLD."""
    issue = I.validate_issue_request(issue);now = I.R.clock(now)
    need(type(published) is bool, 'PUBLISHED_PHASE')
    declared = issue.get('failed_issue_dispositions', [])
    if not declared:
        return dict(schema=SCHEMA, verified_failed_issue_count=0, failed_issues=[])
    history = snapshot.issue_history(issue['intent_parent_sha'])
    need(type(history) is list and len(history) <= 128 and len(set(history)) == len(history)
         and all(I._hex(h) for h in history) and all(d['intent_head_sha'] in history for d in declared),
         'DECLARED_ACTUAL_HISTORY_REQUIRED')
    anchors = [_anchor(snapshot, descriptor)[0] for descriptor in declared]
    same_target = [old['target'] == issue['target'] for old in anchors]
    saved = _published_rows(snapshot, issue, reader, now) if published and any(same_target) else None
    verified = []
    for descriptor, old, same in zip(declared, anchors, same_target):
        if saved is not None and same:
            # The current producer proved absence while this exact target was
            # still first-only. Its immutable READY proof binds the subsequently
            # published C2 outer capsule. Replay old first/HOLD evidence without
            # falsely requiring the now-consumed target to remain attempt one.
            row = _verified_row(descriptor, old, _first(reader, old['target'], now),
                                _hold_receipts(reader, descriptor['intent_head_sha'], now))
        else:
            row = _unused(snapshot, descriptor, reader, now)
        verified.append(row)
    need(saved is None or saved == verified and digest(saved) == digest(verified),
         'PUBLISHED_FAILED_EVIDENCE_CHANGED')
    return dict(schema=SCHEMA, verified_failed_issue_count=len(verified), failed_issues=verified)
