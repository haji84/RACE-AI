"""Actions-only exact-original retention, private restore and bounded backfill.

The existing Actions owner key stays in its environment. Commands print only
counts, immutable Git locators and fixed diagnostic classes; private payloads
and exact response bytes are written only to fresh private runner paths.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_vault as V
from race_ai.boat_pdca_github_handoff import GitStateRepository, TRANSFER_REF


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


def _gh(endpoint):
    V._need(re.fullmatch(r'actions/(?:artifacts/[1-9][0-9]*(?:/zip)?|runs/[1-9][0-9]*)', endpoint),
            'GITHUB_ENDPOINT_INVALID')
    limit = V.MAX_ORIGINAL if endpoint.endswith('/zip') else 256*1024
    process = None
    try:
        process = subprocess.Popen(['gh','api','repos/haji84/RACE-AI/'+endpoint],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        deadline = time.monotonic()+90; result = bytearray()
        with selectors.DefaultSelector() as selected:
            selected.register(process.stdout, selectors.EVENT_READ)
            complete = False
            while not complete:
                remaining = deadline-time.monotonic()
                V._need(remaining > 0, 'GITHUB_READ_TIMEOUT')
                for item, _ in selected.select(min(remaining,1)):
                    block = os.read(item.fd,65536)
                    if not block:
                        complete = True; break
                    result.extend(block); V._need(len(result) <= limit, 'GITHUB_READ_BOUND_INVALID')
        V._need(process.wait(timeout=max(.01,deadline-time.monotonic())) == 0, 'GITHUB_READ_DENIED_OR_UNAVAILABLE')
        V._need(result, 'GITHUB_RESPONSE_EMPTY')
        return bytes(result)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('VAULT_GITHUB_READ_UNAVAILABLE') from None
    finally:
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait()
            if process.stdout: process.stdout.close()


def _parent(git, requested):
    parent = git.head() if requested == 'current' else requested
    V._need(parent is not None, 'EXISTING_TRANSFER_REF_REQUIRED'); V._hex(parent, V._HEAD)
    return parent


def _live_run(raw, metadata):
    value = V._json(raw, 256*1024); run = metadata['workflow_run']
    V._need(type(value) is dict and value.get('id') == run['id'] and value.get('head_sha') == run['head_sha']
            and value.get('workflow_id') == 405276784
            and value.get('head_branch') == 'feat/four-sport-forecast-audit-view-20261022'
            and all(type(value.get(name)) is dict and value[name].get('id') == 1416489937
                    and value[name].get('full_name') == 'haji84/RACE-AI'
                    for name in ('repository','head_repository')), 'LIVE_WORKFLOW_IDENTITY_INVALID')


def _capture(ids, repo, parent, git, readback, get, now):
    V._need(0 < len(ids) <= V.MAX_BATCH and len(set(ids)) == len(ids), 'BATCH_ARTIFACT_IDS_INVALID')
    records = []; saved = []; runs = {}; total = 0; companions = {}
    for ident in ids:
        V._id(ident)
        # Choose the authenticated vault before any live GET for this ID.
        locator = V.lookup_original(ident, repo, source_commit=parent, transport=git)
        if locator is not None:
            restored = V.restore_original(locator, repo, transport=git)
            if locator['kind'] == 'CONTINUITY':
                companions[restored['metadata']['workflow_run']['id']] = (restored['raw_zip'],restored['metadata_raw'])
            saved.append(locator); continue
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
        report = V.retain_originals(records, repo, expected_parent=parent, transport=git,
                                   readback_transport=readback, now=now)
        report['locators'] += saved; report['retained_originals'] += len(saved)
        return report
    return dict(status='EXACT_ORIGINAL_VAULT_UNCHANGED', source_commit=parent,
                retained_originals=len(saved), locators=saved,
                independent_git_readback_verified=True, plaintext_published=False)


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
        if name == 'retain-files': command.add_argument('--manifest', required=True)
        if name == 'retain-captures': command.add_argument('--capture-dir', required=True)
        if name in ('restore','restore-captures'):
            command.add_argument('--locator', required=True); command.add_argument('--output-dir', required=True)
    return parser


def main(argv=None, *, transport=None, readback_transport=None, github_get=None, now=None):
    args = _parser().parse_args(argv)
    try:
        repo = _environment(args.repo_root)
        output = _private_path(args.output, repo, exists=False) if args.output else None
        git = V._transport(repo, transport)
        clock = now or datetime.now(timezone.utc)
        V._need(type(clock) is datetime and clock.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
        if args.command == 'capture':
            report = _capture(args.artifact, repo, _parent(git,args.expected_parent), git,
                              readback_transport, github_get or _gh, clock)
        elif args.command == 'retain-files':
            report = V.retain_originals(_file_records(args.manifest,repo), repo,
                expected_parent=_parent(git,args.expected_parent), transport=git,
                readback_transport=readback_transport, now=clock)
        elif args.command == 'retain-captures':
            captures = _capture_files(args.capture_dir,repo)
            if not captures:
                report = dict(status='NO_SOURCE_CAPTURES_TO_RETAIN', retained_captures=0)
            else:
                run = os.environ.get('GITHUB_RUN_ID'); V._need(run and run.isdecimal(), 'ACTIONS_RUN_REQUIRED')
                locator = V.retain_capture_bundle(captures, repo, run_id=int(run), head_sha=os.environ.get('GITHUB_SHA'),
                    expected_parent=_parent(git,args.expected_parent), transport=git,
                    readback_transport=readback_transport, now=clock)
                report = dict(status='SOURCE_CAPTURES_RETAINED', source_commit=locator['source_commit'],
                              retained_captures=len(captures), locator=locator, plaintext_published=False)
        elif args.command == 'lookup':
            V._need(len(args.artifact) == 1, 'ONE_LOOKUP_ID_REQUIRED')
            locator = V.lookup_original(args.artifact[0],repo,transport=git)
            report = dict(status='ARCHIVED_ORIGINAL_FOUND' if locator else 'ARCHIVED_ORIGINAL_NOT_FOUND', locator=locator)
        else:
            locator = V._json(_read_private(args.locator,repo,16384),16384)
            if type(locator) is dict and 'locator' in locator:
                locator = locator['locator']
            elif type(locator) is dict and 'locators' in locator:
                V._need(type(locator['locators']) is list and len(locator['locators']) == 1,
                        'ONE_LOCATOR_REQUIRED')
                locator = locator['locators'][0]
            folder = _private_path(args.output_dir,repo,exists=False)
            if args.command == 'restore':
                restored = V.restore_original(locator,repo,transport=git)
                bodies = {'original.zip':restored['raw_zip'],'metadata.json':restored['metadata_raw']}
                report = dict(status='EXACT_ORIGINAL_RESTORED', artifact_id=locator['artifact_id'],
                              provenance=restored['provenance'], plaintext_published=False)
            else:
                restored = V.restore_capture_bundle(locator,repo,transport=git)
                bodies = {f'capture-{index:04d}.'+suffix:body for index,pair in enumerate(restored['captures'])
                          for suffix,body in zip(('raw','json'),pair)}
                report = dict(status='EXACT_SOURCE_CAPTURES_RESTORED', captures=len(restored['captures']),
                              provenance=restored['provenance'], plaintext_published=False)
            folder.mkdir(mode=0o700)
            for name,body in bodies.items(): _write(folder/name,body)
        if output: _write(output,V._wire(report)+b'\n')
        print(V._wire(report).decode('utf-8'))
        return 0
    except Exception as exc:
        reason = str(exc) if type(exc) is ValueError and re.fullmatch(r'VAULT_[A-Z0-9_]{1,100}',str(exc)) else 'VAULT_OPERATION_FAILED'
        print(V._wire(dict(status='EXACT_ORIGINAL_VAULT_REJECTED',reason=reason)).decode('utf-8'))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
