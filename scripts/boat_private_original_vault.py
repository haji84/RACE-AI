"""Actions-only exact-original retention, private restore and bounded backfill.

The existing Actions owner key stays in its environment. Commands print only
counts, immutable Git locators and fixed diagnostic classes; private payloads
and exact response bytes are written only to fresh private runner paths.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_vault as V
from race_ai import boat_source_capture_files as C
from race_ai.boat_owner_source_identity import authenticated_live_owner_run


def _environment(repo):
    V._keys(None)  # Before any Git/source request or private-file creation.
    V._need(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI', 'ACTIONS_OWNER_CONTEXT_REQUIRED')
    V._need(type(os.environ.get('GH_TOKEN')) is str and
            re.fullmatch(r'[A-Za-z0-9_.-]{20,512}', os.environ['GH_TOKEN']), 'GITHUB_TOKEN_REQUIRED')
    from scripts.boat_saved_view_feed import git_auth
    git_auth()
    root = Path(repo).resolve()
    V._need(root.is_dir(), 'REPOSITORY_REQUIRED')
    return root


def _private_path(value, repo, *, exists=True, directory=False):
    path = Path(value).absolute()
    V._need('..' not in path.parts and not any(parent.is_symlink() for parent in (path, *path.parents))
            and not path.is_relative_to(Path(repo).resolve())
            and not any((parent/'.git').exists() for parent in (path, *path.parents)), 'PRIVATE_OUTSIDE_GIT_REQUIRED')
    if exists:
        info = path.lstat()
        V._need((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                and not info.st_mode & 0o077 and (directory or info.st_nlink == 1), 'PRIVATE_INPUT_REQUIRED')
    else:
        V._need(not os.path.lexists(path) and path.parent.is_dir(), 'FRESH_PRIVATE_OUTPUT_REQUIRED')
    return path


def _read_private(value, repo, limit):
    path = _private_path(value, repo)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        V._need(stat.S_ISREG(before.st_mode) and not before.st_mode & 0o077
                and before.st_nlink == 1 and 0 < before.st_size <= limit, 'PRIVATE_INPUT_BOUND_INVALID')
        raw = stream.read(limit+1); after = os.fstat(stream.fileno())
    V._need(len(raw) == before.st_size and len(raw) <= limit
            and (before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
                (after.st_size,after.st_mtime_ns,after.st_ctime_ns), 'PRIVATE_INPUT_CHANGED')
    return raw


def _write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _github_endpoint_kind(endpoint):
    V._need(type(endpoint) is str and re.fullmatch(
        r'actions/(?:artifacts/[1-9][0-9]*(?:/zip)?|runs/[1-9][0-9]*)', endpoint),
        'GITHUB_ENDPOINT_INVALID')
    return ('ARTIFACT_ZIP' if endpoint.endswith('/zip') else
            'RUN_METADATA' if endpoint.startswith('actions/runs/') else 'ARTIFACT_METADATA')


def _github_read_diagnostic(kind, attempt, reason, status, *, delay=None):
    # Never print stderr, response bodies, IDs, URLs, tokens or private data.
    safe = reason if re.fullmatch(r'VAULT_[A-Z0-9_]{1,100}', reason) else 'VAULT_OPERATION_FAILED'
    record = dict(status=status, endpoint_kind=kind, attempt=attempt,
                  max_attempts=3, reason=safe)
    if delay is not None:
        record['retry_in_seconds'] = delay
    print(json.dumps(record, sort_keys=True), file=sys.stderr)


def _fresh_upload_context(ids, repo, get, now):
    """Bind an opt-in visibility retry to this runner's exact upload receipts.

    Receipts come from upload-artifact outputs, never a dispatch input. This
    only permits re-reading metadata; capture still checks the ZIP and AES.
    """
    V._need(os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('GITHUB_REPOSITORY') == 'haji84/RACE-AI'
            and os.environ.get('GITHUB_REF') == 'refs/heads/production/boat-p0-p1-20261111'
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'FRESH_UPLOAD_CONTEXT_INVALID')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    head = os.environ.get('GITHUB_SHA', '')
    V._need(re.fullmatch('[1-9][0-9]{0,19}', run_id) is not None
            and re.fullmatch('[a-f0-9]{40}', head) is not None, 'FRESH_UPLOAD_CONTEXT_INVALID')
    local = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                   stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    V._need(local == head, 'FRESH_UPLOAD_CHECKOUT_INVALID')
    raw = os.environ.get('RACE_AI_FRESH_UPLOAD_RECEIPTS', '')
    V._need(0 < len(raw.encode()) <= 16384, 'FRESH_UPLOAD_RECEIPTS_INVALID')
    try:
        receipts = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError('VAULT_FRESH_UPLOAD_RECEIPTS_INVALID') from None
    V._need(type(receipts) is list and 0 < len(receipts) <= V.MAX_BATCH,
            'FRESH_UPLOAD_RECEIPTS_INVALID')
    entries = {}
    for row in receipts:
        V._need(type(row) is dict and set(row) == {'artifact_id', 'name', 'digest'},
                'FRESH_UPLOAD_RECEIPTS_INVALID')
        # An optional upload skipped by Actions has no ID and no digest.
        if row['artifact_id'] == '' and row['digest'] == '':
            continue
        ident, name, digest = row['artifact_id'], row['name'], row['digest']
        V._need(type(ident) is str and re.fullmatch('[1-9][0-9]{0,19}', ident) is not None
                and type(name) is str and type(digest) is str, 'FRESH_UPLOAD_RECEIPTS_INVALID')
        ident = int(ident)
        digest = digest.removeprefix('sha256:')
        V._need(re.fullmatch('[a-f0-9]{64}', digest) is not None and ident not in entries,
                'FRESH_UPLOAD_RECEIPTS_INVALID')
        try:
            kind = V._kind(dict(name=name, workflow_run=dict(id=int(run_id))))
        except (ValueError, KeyError, TypeError):
            raise ValueError('VAULT_FRESH_UPLOAD_RECEIPTS_INVALID') from None
        V._need(kind in ('P0', 'P1', 'RESULT', 'ALL_MODEL'), 'FRESH_UPLOAD_KIND_INVALID')
        entries[ident] = dict(id=ident, name=name, digest='sha256:'+digest)
    V._need(entries and len(set(ids)) == len(ids) and set(entries) == set(ids),
            'FRESH_UPLOAD_RECEIPTS_INVALID')
    run = V._json(get('actions/runs/'+run_id), 256*1024)
    V._need(authenticated_live_owner_run(run) and run.get('id') == int(run_id)
            and run.get('head_sha') == head and run.get('head_branch') == 'production/boat-p0-p1-20261111'
            and run.get('status') == 'in_progress' and run.get('run_attempt') == 1,
            'FRESH_UPLOAD_RUN_INVALID')
    started = V._time(run.get('created_at'))
    V._need(started <= now, 'FRESH_UPLOAD_CLOCK_INVALID')
    deadline = time.monotonic()+60
    return {f'actions/artifacts/{ident}': dict(receipt=row, run_id=int(run_id), head_sha=head,
            run_started_at=started, now=now, deadline=deadline) for ident, row in entries.items()}


def _verify_fresh_upload_metadata(raw, context):
    value = V._json(raw, V.MAX_METADATA)
    expected = context['receipt']
    V._need(type(value) is dict and all(value.get(k) == v for k, v in expected.items())
            and value.get('expired') is False and type(value.get('size_in_bytes')) is int
            and 0 < value['size_in_bytes'] <= V.MAX_ORIGINAL, 'FRESH_UPLOAD_METADATA_INVALID')
    run = value.get('workflow_run')
    V._need(type(run) is dict and run.get('id') == context['run_id']
            and run.get('head_sha') == context['head_sha'] and all(
                type(run.get(k)) is int and run[k] == 1416489937
                for k in ('repository_id', 'head_repository_id')), 'FRESH_UPLOAD_METADATA_INVALID')
    V._need(context['run_started_at'] <= V._time(value.get('created_at')) <= context['now']
            < V._time(value.get('expires_at')), 'FRESH_UPLOAD_CLOCK_INVALID')


def _gh(endpoint, *, fresh_uploads=None, once_get=None):
    """Retry the same exact GitHub read, never the forecast or provider source.

    Explicit HTTP 5xx, local read timeout and recognized transient transport
    failures retry. A trusted current upload also permits its exact metadata
    404 for 60 seconds. Authentication, rate limits, ambiguous failures
    and integrity/size errors stay closed. After recovery the existing capture
    verifies the original digest/identity/time before the next round can run.
    """
    kind = _github_endpoint_kind(endpoint)
    fresh = fresh_uploads.get(endpoint) if fresh_uploads else None
    for attempt in range(1, 4):
        try:
            raw = (once_get or _gh_once)(endpoint)
        except ValueError as exc:
            reason = str(exc)
            retryable = (re.fullmatch(r'VAULT_GITHUB_HTTP_5[0-9]{2}', reason) is not None
                         or reason in ('VAULT_GITHUB_READ_TIMEOUT', 'VAULT_GITHUB_TRANSPORT_TRANSIENT')
                         or (reason == 'VAULT_GITHUB_HTTP_404' and kind == 'ARTIFACT_METADATA'
                             and fresh is not None and time.monotonic() <= fresh['deadline']))
            if not retryable or attempt == 3:
                _github_read_diagnostic(kind, attempt, reason, 'GITHUB_READ_FAILED')
                raise
            delay = 2 * attempt
            _github_read_diagnostic(kind, attempt, reason, 'GITHUB_READ_RETRY', delay=delay)
            time.sleep(delay)
        else:
            if fresh is not None:
                _verify_fresh_upload_metadata(raw, fresh)
            if attempt > 1:
                _github_read_diagnostic(kind, attempt, 'VAULT_GITHUB_READ_OK', 'GITHUB_READ_RECOVERED')
            return raw
    raise AssertionError('UNREACHABLE_GITHUB_ARTIFACT_RETRY')


def _github_failure_reason(diagnostic):
    """Classify bounded CLI stderr without disclosing it or guessing HTTP status."""
    text = diagnostic.decode('utf-8', errors='replace')
    statuses = set(re.findall(r'(?i)\bHTTP(?:/\d(?:\.\d)?)?[\s:]+([1-5][0-9]{2})\b', text))
    if len(statuses) == 1:
        return 'VAULT_GITHUB_HTTP_' + next(iter(statuses))
    if not statuses and re.search(
            r'(?i)connection reset by peer|connection timed out|TLS handshake timeout|'
            r'i/o timeout|temporary failure in name resolution|unexpected EOF', text):
        return 'VAULT_GITHUB_TRANSPORT_TRANSIENT'
    return 'VAULT_GITHUB_READ_DENIED_OR_UNAVAILABLE'


def _gh_once(endpoint):
    _github_endpoint_kind(endpoint)
    limit = V.MAX_ORIGINAL if endpoint.endswith('/zip') else 256*1024
    process = None
    try:
        process = subprocess.Popen(['gh','api','repos/haji84/RACE-AI/'+endpoint],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic()+90
        result, diagnostic = bytearray(), bytearray()
        # Drain both bounded pipes concurrently: a full stderr pipe must not
        # deadlock stdout or force retention of private response text in logs.
        with selectors.DefaultSelector() as selected:
            selected.register(process.stdout, selectors.EVENT_READ, 'body')
            selected.register(process.stderr, selectors.EVENT_READ, 'diagnostic')
            while selected.get_map():
                remaining = deadline-time.monotonic()
                V._need(remaining > 0, 'GITHUB_READ_TIMEOUT')
                for item, _ in selected.select(min(remaining,1)):
                    block = os.read(item.fd,65536)
                    if not block:
                        selected.unregister(item.fileobj)
                        continue
                    if item.data == 'body':
                        result.extend(block)
                        V._need(len(result) <= limit, 'GITHUB_READ_BOUND_INVALID')
                    else:
                        diagnostic.extend(block)
                        V._need(len(diagnostic) <= 16384, 'GITHUB_DIAGNOSTIC_BOUND_INVALID')
        code = process.wait(timeout=max(.01,deadline-time.monotonic()))
        if code != 0:
            raise ValueError(_github_failure_reason(diagnostic))
        V._need(result, 'GITHUB_RESPONSE_EMPTY')
        return bytes(result)
    except subprocess.TimeoutExpired:
        raise ValueError('VAULT_GITHUB_READ_TIMEOUT') from None
    except (OSError, subprocess.SubprocessError):
        raise ValueError('VAULT_GITHUB_READ_UNAVAILABLE') from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


def _parent(git, requested):
    parent = git.head() if requested == 'current' else requested
    V._need(parent is not None, 'EXISTING_VAULT_REF_REQUIRED'); V._hex(parent, V._HEAD)
    return parent


def _live_run(raw, metadata):
    value = V._json(raw, 256*1024); run = metadata['workflow_run']
    V._need(type(value) is dict and value.get('id') == run['id'] and value.get('head_sha') == run['head_sha']
            and authenticated_live_owner_run(value), 'LIVE_WORKFLOW_IDENTITY_INVALID')


def _capture(ids, repo, parent, git, readback, get, now, *, allow_refresh=False):
    V._need(0 < len(ids) <= V.MAX_BATCH and len(set(ids)) == len(ids), 'BATCH_ARTIFACT_IDS_INVALID')
    V._need(type(allow_refresh) is bool, 'PARENT_REFRESH_FLAG_INVALID')
    records = []; saved = []; runs = {}; total = 0; companions = {}
    for ident in ids:
        V._id(ident)
        # Choose the authenticated vault before any live GET for this ID.
        locator = V.lookup_original(ident, repo, source_commit=parent, transport=git)
        if locator is not None:
            restored = V.restore_original(locator, repo, transport=git)
            if locator['kind'] == 'CONTINUITY':
                companions[restored['metadata']['workflow_run']['id']] = (restored['raw_zip'],restored['metadata_raw'])
            saved.append((locator,V._sha(restored['raw_zip']),V._sha(restored['metadata_raw']))); continue
        metadata_raw = get(f'actions/artifacts/{ident}')
        metadata = V._json(metadata_raw, V.MAX_METADATA)
        V._need(type(metadata) is dict and metadata.get('id') == ident and metadata.get('expired') is False,
                'LIVE_ARTIFACT_IDENTITY_INVALID')
        run = metadata.get('workflow_run')
        V._need(type(run) is dict and all(type(run.get(name)) is int and run[name] == 1416489937
                for name in ('repository_id','head_repository_id')), 'LIVE_ARTIFACT_REPOSITORY_INVALID')
        V._id(run.get('id')); V._hex(run.get('head_sha'), V._HEAD)
        V._need(V._time(metadata.get('created_at')) <= now < V._time(metadata.get('expires_at')),
                'LIVE_ARTIFACT_CLOCK_INVALID')
        V._need(type(metadata.get('size_in_bytes')) is int and 0 < metadata['size_in_bytes'] <= V.MAX_ORIGINAL,
                'LIVE_ARTIFACT_BOUND_INVALID')
        if run['id'] not in runs:
            runs[run['id']] = get(f'actions/runs/{run["id"]}')
        _live_run(runs[run['id']], metadata)
        raw = get(f'actions/artifacts/{ident}/zip')
        V._need(type(raw) is bytes and len(raw) == metadata['size_in_bytes']
                and metadata.get('digest') == 'sha256:'+V._sha(raw), 'LIVE_ARTIFACT_DIGEST_INVALID')
        total += len(raw)+len(metadata_raw)
        V._need(total <= V.MAX_BATCH_PLAIN, 'BATCH_TOTAL_BOUND_INVALID')
        records.append(dict(raw_zip=raw, metadata_raw=metadata_raw))
    for record in records:
        metadata = V._json(record['metadata_raw'], V.MAX_METADATA)
        if V._kind(metadata) == 'CONTINUITY':
            companions[metadata['workflow_run']['id']] = (record['raw_zip'],record['metadata_raw'])
    for record in records:
        metadata = V._json(record['metadata_raw'], V.MAX_METADATA)
        if V._kind(metadata) == 'SOURCE_CONTROL':
            record['companion'] = companions.get(metadata['workflow_run']['id'])
    if records:
        # Source acquisition and authentication above happen once. A known CAS
        # race may rebase those same exact bytes onto a verified descendant;
        # denials, integrity errors and unknown Git failures never retry.
        for attempt in range(3 if allow_refresh else 1):
            if allow_refresh:parent=V.refresh_parent(git,parent)
            try:
                report = V.retain_originals(records, repo, expected_parent=parent, transport=git,
                                           readback_transport=readback, now=now)
                break
            except ValueError as exc:
                if type(exc) is not ValueError or str(exc) != 'STATE_REF_CONCURRENT_UPDATE' or not allow_refresh or attempt == 2:
                    raise
    else:
        if allow_refresh:parent=V.refresh_parent(git,parent)
        report = dict(status='EXACT_ORIGINAL_VAULT_UNCHANGED', source_commit=parent,
                      retained_originals=0, locators=[], independent_git_readback_verified=True,
                      plaintext_published=False)
    if saved:
        # Producer-cache reads choose originals before live GETs. They do not
        # prove remote retention, so verify cached originals in a different
        # object database at the exact commit returned by this operation.
        commit=report['source_commit'];locators=[]
        with V._independent_reader(git,readback) as reader:
            reader.fetch(commit)
            for locator,zip_sha,metadata_sha in saved:
                pinned=dict(locator,source_commit=commit)
                restored=V.restore_original(pinned,reader.repo,transport=reader)
                V._need(V._sha(restored['raw_zip'])==zip_sha
                        and V._sha(restored['metadata_raw'])==metadata_sha,'REMOTE_ORIGINAL_READBACK_MISMATCH')
                locators.append(pinned)
        report['locators'] += locators;report['retained_originals'] += len(locators)
    return report


def _file_records(manifest, repo):
    values = V._json(_read_private(manifest, repo, V.MAX_INDEX))
    V._need(type(values) is list and 0 < len(values) <= V.MAX_BATCH, 'FILE_MANIFEST_INVALID')
    records = []; total = 0
    for item in values:
        V._need(type(item) is dict and {'raw_zip','metadata_raw'} <= set(item)
                and set(item) <= {'raw_zip','metadata_raw','expected_kind','companion'}, 'FILE_MANIFEST_INVALID')
        record = dict(raw_zip=_read_private(item['raw_zip'], repo, V.MAX_ORIGINAL),
                      metadata_raw=_read_private(item['metadata_raw'], repo, V.MAX_METADATA))
        if 'expected_kind' in item: record['expected_kind'] = item['expected_kind']
        if 'companion' in item:
            companion = item['companion']
            V._need(type(companion) is dict and set(companion) == {'raw_zip','metadata_raw'}, 'FILE_COMPANION_INVALID')
            record['companion'] = (_read_private(companion['raw_zip'], repo, V.MAX_ORIGINAL),
                                    _read_private(companion['metadata_raw'], repo, V.MAX_METADATA))
        total += len(record['raw_zip'])+len(record['metadata_raw'])+sum(len(raw) for raw in record.get('companion',()))
        V._need(total <= V.MAX_BATCH_PLAIN, 'BATCH_TOTAL_BOUND_INVALID')
        records.append(record)
    return records


def _capture_files(folder, repo):
    """Compatibility API for one bounded list; retention uses the inventory."""
    root = _private_path(folder, repo, directory=True)
    receipts = sorted(root.glob('*.json'))
    V._need(len(receipts) <= 240, 'CAPTURE_COUNT_INVALID')
    captures = []
    for path in receipts:
        metadata_raw = _read_private(path, repo, 16384); metadata = V._json(metadata_raw, 16384)
        V._need(V._sha(V._wire(metadata)) == path.stem, 'CAPTURE_FILENAME_INVALID')
        ident = V._hex(metadata.get('source_sha256'))
        candidates = [root/(ident+suffix) for suffix in ('.html','.raw') if (root/(ident+suffix)).exists()]
        V._need(len(candidates) == 1, 'CAPTURE_BODY_REQUIRED')
        captures.append((_read_private(candidates[0], repo, 4*1024*1024), metadata_raw))
    return captures


CAPTURE_SET = 'RACE_AI_SOURCE_CAPTURE_SET_V1'


def _capture_set_report(locators, counts, hashes, total, *, complete):
    return dict(schema=CAPTURE_SET,
        status='SOURCE_CAPTURES_RETAINED' if complete else 'SOURCE_CAPTURES_RETENTION_HOLD',
        complete=complete, source_commit=locators[-1]['source_commit'] if locators else None,
        retained_captures=sum(counts), requested_captures=total, locators=locators,
        bundle_capture_counts=counts, bundle_inventory_sha256=hashes,
        capture_set_sha256=C.capture_set_hash(hashes), plaintext_published=False)


def _safe_reason(exc):
    return str(exc) if type(exc) is ValueError and re.fullmatch(r'VAULT_[A-Z0-9_]{1,100}',str(exc)) else 'VAULT_OPERATION_FAILED'


def _retain_capture_files(folder, repo, requested_parent, git, readback, clock):
    # No Git publication until every receipt, body, source URL, actual clock,
    # global identity and private file has passed the disk-backed preflight.
    with C.CaptureInventory(folder, repo=repo, now=clock) as inventory:
        if not inventory.count:return dict(status='NO_SOURCE_CAPTURES_TO_RETAIN', retained_captures=0), 0
        run = os.environ.get('GITHUB_RUN_ID'); V._need(run and run.isdecimal(), 'ACTIONS_RUN_REQUIRED')
        V._id(int(run)); V._hex(os.environ.get('GITHUB_SHA'), V._HEAD)
        parent = _parent(git, requested_parent); locators = []; counts = []; hashes = []
        try:
            for group in inventory.groups():
                captures = inventory.materialize(group)
                count = len(captures); digest = C.bundle_inventory(captures)
                locator = V.retain_capture_bundle(captures, repo, run_id=int(run), head_sha=os.environ['GITHUB_SHA'],
                    expected_parent=parent, transport=git, readback_transport=readback, now=clock)
                del captures  # Never keep two raw-body groups alive.
                locators.append(locator); counts.append(count); hashes.append(digest)
                parent = locator['source_commit']
        except Exception as exc:
            # A commit may exist even when its independent readback failed.
            # Only the verified prefix is acknowledged; retry never resets it.
            report = _capture_set_report(locators, counts, hashes, inventory.count, complete=False)
            report['reason'] = _safe_reason(exc)
            return report, 2
        if len(locators) == 1:
            # Exact pre-batching report shape and file order for one bundle.
            return dict(status='SOURCE_CAPTURES_RETAINED', source_commit=parent,
                retained_captures=inventory.count, locator=locators[0], plaintext_published=False), 0
        return _capture_set_report(locators, counts, hashes, inventory.count, complete=True), 0


def _capture_set(value):
    """Validate a plural acknowledgment, not a new cryptographic authority.

    Every member is separately authenticated by the existing vault. The JSON
    count/hash acknowledgment is not a substitute for a trusted report hash.
    """
    fields = {'schema','status','complete','source_commit','retained_captures','requested_captures',
              'locators','bundle_capture_counts','bundle_inventory_sha256','capture_set_sha256','plaintext_published'}
    V._need(type(value) is dict and set(value) == fields and value['schema'] == CAPTURE_SET
            and value['status'] == 'SOURCE_CAPTURES_RETAINED' and value['complete'] is True
            and value['plaintext_published'] is False, 'CAPTURE_SET_INCOMPLETE')
    locators = value['locators']; counts = value['bundle_capture_counts']; hashes = value['bundle_inventory_sha256']
    V._need(type(locators) is list and len(locators) > 1
            and type(counts) is list and type(hashes) is list and len(locators) == len(counts) == len(hashes)
            and all(type(n) is int and 0 < n <= C.MAX_CAPTURES for n in counts)
            and type(value['retained_captures']) is int and type(value['requested_captures']) is int
            and value['retained_captures'] == value['requested_captures'] == sum(counts), 'CAPTURE_SET_COUNT_INVALID')
    V._hex(value['source_commit'], V._HEAD)
    V._need(all(type(locator) is dict and locator.get('kind') == 'SOURCE_CAPTURES' for locator in locators)
            and value['source_commit'] == locators[-1].get('source_commit'), 'CAPTURE_SET_LOCATOR_INVALID')
    identities = [(locator.get('batch_path'), locator.get('entry_sha256')) for locator in locators]
    V._need(len(set(identities)) == len(identities)
            and C.capture_set_hash(hashes) == value['capture_set_sha256'], 'CAPTURE_SET_HASH_INVALID')
    return locators, counts, hashes


def _expose_private_directory(stage, folder, repo):
    # Ubuntu Actions supports renameat2. Refuse on other platforms rather than
    # use rename(), whose empty-directory replacement would hide a collision.
    _private_path(folder, repo, exists=False)
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    V._need(rename is not None, 'ATOMIC_PRIVATE_RESTORE_UNAVAILABLE')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    V._need(rename(-100, os.fsencode(stage), -100, os.fsencode(folder), 1) == 0,
            'FRESH_PRIVATE_OUTPUT_REQUIRED')


def _restore_captures(value, folder, repo, git, clock):
    plural = type(value) is dict and value.get('schema') == CAPTURE_SET
    if plural:
        locators, counts, hashes = _capture_set(value)
    else:
        if type(value) is dict and 'locator' in value:value = value['locator']
        elif type(value) is dict and 'locators' in value:
            V._need(type(value['locators']) is list and len(value['locators']) == 1, 'ONE_LOCATOR_REQUIRED')
            value = value['locators'][0]
        locators = [value]; counts = hashes = None
    # Sibling staging keeps one atomic no-replace rename on the same filesystem.
    # Failure of any final bundle, count, hash or output check removes staging.
    with tempfile.TemporaryDirectory(prefix='.boat-capture-restore-', dir=folder.parent) as name, \
         C.CaptureReceiptIndex(repo=repo, now=clock) as identities:
        stage = _private_path(name, repo, directory=True); provenance = []
        for number, locator in enumerate(locators):
            restored = V.restore_capture_bundle(locator, repo, transport=git)
            pairs = restored['captures']
            if plural:
                V._need(len(pairs) == counts[number] and C.bundle_inventory(pairs) == hashes[number],
                        'CAPTURE_SET_READBACK_MISMATCH')
            identities.add(pairs)
            target = stage/f'bundle-{number:06d}' if plural else stage
            if plural:target.mkdir(mode=0o700)
            for index, pair in enumerate(pairs):
                for suffix, body in zip(('raw','json'), pair):_write(target/f'capture-{index:04d}.{suffix}', body)
            provenance.append(restored['provenance'])
            del pairs, restored
        if plural:V._need(identities.count == value['retained_captures'], 'CAPTURE_SET_COUNT_INVALID')
        report = dict(status='EXACT_SOURCE_CAPTURES_RESTORED', captures=identities.count,
            provenance=provenance if plural else provenance[0], plaintext_published=False)
        if plural:report.update(complete=True, capture_bundles=len(locators), capture_set_sha256=value['capture_set_sha256'])
        _expose_private_directory(stage, folder, repo)
    return report


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('capture','retain-files','retain-captures','lookup','restore','restore-captures'):
        command = commands.add_parser(name)
        command.add_argument('--repo-root', default=str(ROOT))
        command.add_argument('--output')
        if name in ('capture','retain-files','retain-captures'):
            command.add_argument('--expected-parent', required=True)
        if name in ('capture','lookup'):
            command.add_argument('--artifact', type=int, action='append', required=True)
        if name == 'capture':
            command.add_argument('--fresh-upload', action='store_true')
        if name == 'retain-files': command.add_argument('--manifest', required=True)
        if name == 'retain-captures': command.add_argument('--capture-dir', required=True)
        if name in ('restore','restore-captures'):
            command.add_argument('--locator', required=True); command.add_argument('--output-dir', required=True)
    return parser


def main(argv=None, *, transport=None, readback_transport=None, github_get=None, now=None):
    args = _parser().parse_args(argv)
    try:
        code = 0
        repo = _environment(args.repo_root)
        output = _private_path(args.output, repo, exists=False) if args.output else None
        git = V._transport(repo, transport)
        clock = now or datetime.now(timezone.utc)
        V._need(type(clock) is datetime and clock.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        if args.command == 'capture':
            get = github_get or _gh
            if args.fresh_upload:
                context = _fresh_upload_context(args.artifact, repo, get, clock)
                get = lambda endpoint: _gh(endpoint, fresh_uploads=context, once_get=github_get)
            report = _capture(args.artifact, repo, _parent(git,args.expected_parent), git,
                              readback_transport, get, clock,
                              allow_refresh=args.expected_parent == 'current')
        elif args.command == 'retain-files':
            report = V.retain_originals(_file_records(args.manifest,repo), repo,
                expected_parent=_parent(git,args.expected_parent), transport=git,
                readback_transport=readback_transport, now=clock)
        elif args.command == 'retain-captures':
            report, code = _retain_capture_files(args.capture_dir,repo,args.expected_parent,git,readback_transport,clock)
        elif args.command == 'lookup':
            V._need(len(args.artifact) == 1, 'ONE_LOOKUP_ID_REQUIRED')
            locator = V.lookup_original(args.artifact[0],repo,transport=git)
            report = dict(status='ARCHIVED_ORIGINAL_FOUND' if locator else 'ARCHIVED_ORIGINAL_NOT_FOUND', locator=locator)
        else:
            locator = V._json(_read_private(args.locator,repo,V.MAX_INDEX),V.MAX_INDEX)
            folder = _private_path(args.output_dir,repo,exists=False)
            if args.command == 'restore-captures':
                report = _restore_captures(locator,folder,repo,git,clock)
            else:
                # Original-artifact restore still requires a single locator.
                if type(locator) is dict and 'locator' in locator:locator = locator['locator']
                elif type(locator) is dict and 'locators' in locator:
                    V._need(type(locator['locators']) is list and len(locator['locators']) == 1, 'ONE_LOCATOR_REQUIRED')
                    locator = locator['locators'][0]
                restored = V.restore_original(locator,repo,transport=git)
                bodies = {'original.zip':restored['raw_zip'],'metadata.json':restored['metadata_raw']}
                report = dict(status='EXACT_ORIGINAL_RESTORED', artifact_id=locator['artifact_id'],
                              provenance=restored['provenance'], plaintext_published=False)
                folder.mkdir(mode=0o700)
                for name,body in bodies.items(): _write(path=folder/name, raw=body)
        if output: _write(output,V._wire(report)+b'\n')
        print(V._wire(report).decode('utf-8'))
        return code
    except Exception as exc:
        reason = _safe_reason(exc)
        print(V._wire(dict(status='EXACT_ORIGINAL_VAULT_REJECTED',reason=reason)).decode('utf-8'))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
