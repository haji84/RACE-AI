"""Read-only, Git-only verification of one closed BOAT run's retained originals."""
import argparse
from contextlib import contextmanager
from datetime import date
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_vault as V, boat_original_recovery as R
from race_ai import boat_source_control_mirror as M
from scripts.boat_private_original_vault import _environment, _private_path, _write

MAX_ARCHIVES = 128
MAX_BYTES = 512 * 1024 * 1024
REASONS = frozenset((
    'OWNER_CONTEXT_REQUIRED', 'INPUT_INVALID', 'AUTHENTICATED_READ_FAILED',
    'CLOSED_RUN_CATALOGUE_REQUIRED', 'CLOSED_RUN_SCOPE_MISMATCH',
    'INVENTORY_BOUND_EXCEEDED', 'INVENTORY_COVERAGE_MISMATCH',
    'ORIGINAL_SCOPE_MISMATCH', 'LATEST_MIRROR_REQUIRED',
    'LATEST_MIRROR_SCOPE_MISMATCH', 'READ_BUDGET_EXCEEDED',
    'LIVE_REQUEST_FORBIDDEN', 'FRESH_REPOSITORY_FAILED',
    'REQUIRED_CAPTURE_INVALID', 'REQUIRED_CAPTURE_NOT_IN_INVENTORY',
    'REQUIRED_CAPTURE_COUNT_MISMATCH', 'REQUIRED_CAPTURE_TYPE_MISMATCH',
))


def _need(ok, reason):
    if not ok:
        raise ValueError(reason)


def _deny_live(_endpoint):
    raise ValueError('LIVE_REQUEST_FORBIDDEN')


class _ReadOnlyGit:
    """Pin one remote head and bound all blob reads, including repeated restores."""
    def __init__(self, git, maximum):
        _need(type(maximum) is int and 0 < maximum <= MAX_BYTES, 'INPUT_INVALID')
        self._git = git
        self.repo, self.ref = git.repo, git.ref
        self.maximum, self.used = maximum, 0
        self.commit_id = git.head()
        V._hex(self.commit_id, V._HEAD)

    def head(self):
        return self.commit_id

    def fetch(self, commit):
        return self._git.fetch(commit)

    def exists(self, commit, path):
        return self._git.exists(commit, path)

    def read(self, commit, path, limit):
        remaining = self.maximum - self.used
        _need(remaining > 0, 'READ_BUDGET_EXCEEDED')
        # The existing Git reader checks blob size before retrieving its bytes.
        raw = self._git.read(commit, path, min(limit, remaining))
        _need(type(raw) is bytes and len(raw) <= remaining, 'READ_BUDGET_EXCEEDED')
        self.used += len(raw)
        return raw


def _entry(locator, git, key):
    _, mac = V._keys(key)
    git.fetch(locator['source_commit'])
    reference = {name: locator[name] for name in
                 ('batch_path', 'batch_sha256', 'entry_sha256', 'artifact_id', 'kind')}
    return V._batch_entry(git, locator['source_commit'], reference, mac)


def _requirement(value):
    _need(type(value) is dict and set(value) == {'schema', 'locator', 'expected_capture_count'}
          and value['schema'] == 'RACE_AI_BOAT_REQUIRED_CAPTURE_V1'
          and type(value['expected_capture_count']) is int
          and 1 <= value['expected_capture_count'] <= 240, 'REQUIRED_CAPTURE_INVALID')
    V._validate_locator(value['locator'])
    _need(value['locator']['kind'] == 'SOURCE_CAPTURES', 'REQUIRED_CAPTURE_INVALID')
    return value


def _capture_type(metadata):
    url = metadata['source_url']
    match = re.fullmatch(r'https://www\.boatrace\.jp/owpc/pc/race/raceresult\?'
                        r'rno=(?:[1-9]|1[0-2])&jcd=(?:0[1-9]|1[0-9]|2[0-4])&hd=(\d{8})', url)
    if match:
        try:
            date.fromisoformat(match[1])
        except ValueError:
            return 'OTHER_RETAINED'
        return 'OFFICIAL_RACE_RESULT'
    if url.startswith(R.API) and V._capture_url(url):
        return 'GITHUB_METADATA'
    return 'OTHER_RETAINED'


def _locator_identity(locator):
    return {name: value for name, value in locator.items() if name != 'source_commit'}


def verify(transport, *, run, day, head, key=None, max_bytes=MAX_BYTES, required_capture=None):
    """Authenticate originals in memory. No upstream writes or live fallback exist."""
    key = V.state_key('production', key)
    V._id(run)
    V._hex(head, V._HEAD)
    _need(type(day) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day), 'INPUT_INVALID')
    date.fromisoformat(day)
    required = _requirement(required_capture) if required_capture is not None else None
    git = _ReadOnlyGit(transport, max_bytes)
    locators = V.list_originals(day[:7], git.repo, run_id=run,
                               source_commit=git.head(), key=key, transport=git)
    _need(0 < len(locators) <= MAX_ARCHIVES, 'INVENTORY_BOUND_EXCEEDED')
    if required is not None:
        required_identity = _locator_identity(required['locator'])
        _need(sum(_locator_identity(value) == required_identity for value in locators) == 1,
              'REQUIRED_CAPTURE_NOT_IN_INVENTORY')
    recovery = R.ArtifactRecovery(_deny_live, git.repo, key=key, transport=git)
    _need(recovery.has_closed_run(run), 'CLOSED_RUN_CATALOGUE_REQUIRED')
    closed = recovery.closures[run]
    validated = closed['validated']
    actual_run = validated['run']
    _need(actual_run['id'] == run and actual_run['head_sha'] == head
          and actual_run.get('run_attempt', 1) == 1
          and V._time(actual_run['created_at']).astimezone(V.JST).date().isoformat() == day,
          'CLOSED_RUN_SCOPE_MISMATCH')
    listed = {row['id']: row for row in validated['rows']
              if R._native_kind(row['name'], run) is not None}
    native = [value for value in locators if value['kind'] in V.KINDS]
    native_ids = [value['artifact_id'] for value in native]
    _need(len(native_ids) == len(set(native_ids)) and set(listed) <= set(native_ids)
          and set(listed) == {value['artifact_id'] for value in native
                              if value['kind'] != 'PRIVATE_PAIRS'}, 'INVENTORY_COVERAGE_MISMATCH')
    _need(set(listed) == {value['artifact_id'] for value in closed['state']['originals']},
          'INVENTORY_COVERAGE_MISMATCH')
    counts = {kind: 0 for kind in sorted(V.KINDS)}
    capture_bundles = capture_records = 0
    capture_types = dict(OFFICIAL_RACE_RESULT=0, GITHUB_METADATA=0, OTHER_RETAINED=0)
    required_official_count = None
    unique_receipts = set()
    for locator in locators:
        is_required = required is not None and _locator_identity(locator) == required_identity
        if is_required:
            # Restore the exact terminal receipt's commit, not a replacement locator.
            locator = required['locator']
        summary = _entry(locator, git, key)['header']['summary']
        _need(summary['run_id'] == run and summary['head_sha'] == head, 'ORIGINAL_SCOPE_MISMATCH')
        if is_required:
            _need(summary['capture_count'] == required['expected_capture_count'],
                  'REQUIRED_CAPTURE_COUNT_MISMATCH')
        if locator['kind'] == 'SOURCE_CAPTURES':
            restored = V.restore_capture_bundle(locator, git.repo, key=key, transport=git)
            capture_bundles += 1
            if is_required:
                _need(len(restored['captures']) == required['expected_capture_count'],
                      'REQUIRED_CAPTURE_COUNT_MISMATCH')
                required_receipts = set()
            for raw, receipt in restored['captures']:
                metadata = V._json(receipt, 16384)
                capture_type = _capture_type(metadata)
                capture_types[capture_type] += 1
                if is_required:
                    _need(capture_type == 'OFFICIAL_RACE_RESULT', 'REQUIRED_CAPTURE_TYPE_MISMATCH')
                # Keep only hashes in the deduplication set, never source values in output.
                identity = [metadata['source_url'], metadata['captured_at'], metadata['source_sha256']]
                unique_receipts.add(V._sha(V._wire(identity)))
                if is_required:
                    required_receipts.add(V._sha(V._wire(identity)))
                capture_records += 1
            if is_required:
                _need(len(required_receipts) == required['expected_capture_count'],
                      'REQUIRED_CAPTURE_COUNT_MISMATCH')
                required_official_count = len(required_receipts)
        else:
            restored = V.restore_original(locator, git.repo, key=key, transport=git)
            metadata = restored['metadata']
            _need(metadata['workflow_run']['id'] == run
                  and metadata['workflow_run']['head_sha'] == head, 'ORIGINAL_SCOPE_MISMATCH')
            if locator['artifact_id'] in listed:
                row = listed[locator['artifact_id']]
                _need(all(row.get(field) == metadata.get(field) for field in
                          ('id', 'name', 'digest', 'size_in_bytes', 'created_at')),
                      'INVENTORY_COVERAGE_MISMATCH')
            counts[locator['kind']] += 1
        del restored
    _need(git.exists(git.head(), M.LATEST), 'LATEST_MIRROR_REQUIRED')
    latest = M._validate_latest(M._decode(V._read(git, git.head(), M.LATEST, M.MAX_RECORD), key))
    _need(latest['run_id'] == run and latest['source_head'] == head and latest['day_jst'] == day,
          'LATEST_MIRROR_SCOPE_MISMATCH')
    M._check_latest_record(git, git.head(), latest, key)
    raw = V._read(git, git.head(), latest['record_path'], M.MAX_RECORD)
    state = M.verify_record(raw, run=actual_run, key=key, source_commit=git.head())['state']
    M._readback_sources(state, git, key)
    return dict(schema='RACE_AI_BOAT_RETAINED_RUN_VERIFICATION_V1',
        status='RETAINED_RUN_VERIFIED' if required is not None else 'RETAINED_RUN_PARTIALLY_VERIFIED',
        originals_by_kind=counts, originals_restored=sum(counts.values()),
        listed_native_originals=len(listed), listed_artifacts=len(validated['rows']),
        closed_listing_pages=len(validated['pages']), capture_bundles_restored=capture_bundles,
        captures_restored=capture_records, unique_capture_receipts=len(unique_receipts),
        capture_records_by_type=capture_types, required_official_result_captures=required_official_count,
        raw_capture_completeness_verified=required is not None,
        blob_bytes_read=git.used, max_blob_bytes=git.maximum,
        closed_run_catalogue_verified=True, mirror_cipher_binding_verified=True,
        official_source_requests=0, live_artifact_requests=0, upstream_writes=0,
        plaintext_published=False, automatic_continuation_proven=False)


@contextmanager
def _fresh_reader(repo, runner_temp):
    origin = V._transport(repo, None)
    with tempfile.TemporaryDirectory(prefix='boat-retained-run-', dir=runner_temp) as temporary:
        root = Path(temporary)
        for command in (['git', 'init', '--bare', str(root)],
                        ['git', '-C', str(root), 'remote', 'add', 'origin', origin.fetch_url]):
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            _need(result.returncode == 0, 'FRESH_REPOSITORY_FAILED')
        yield V.VaultGitRepository(root, ref=origin.ref)


def _read_requirement(value, repo):
    path = Path(value)
    if not path.is_absolute():
        path = repo/path
    _need('..' not in path.parts and path.is_relative_to(repo/'audit'/'state')
          and path.suffix == '.json'
          and not any(p.is_symlink() for p in (path, *path.parents)), 'REQUIRED_CAPTURE_INVALID')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 16384,
              'REQUIRED_CAPTURE_INVALID')
        return _requirement(V._json(stream.read(16385), 16384))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--day', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--required-capture-locator')
    args = parser.parse_args(argv)
    phase = 'OWNER_CONTEXT_REQUIRED'
    output = None
    try:
        repo = _environment(ROOT)
        phase = 'INPUT_INVALID'
        V._id(args.run)
        V._hex(args.head, V._HEAD)
        _need(re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.day), 'INPUT_INVALID')
        date.fromisoformat(args.day)
        runner_temp = Path(os.environ['RUNNER_TEMP']).absolute()
        _need(runner_temp.is_dir() and not runner_temp.is_relative_to(repo)
              and not any(p.is_symlink() for p in (runner_temp, *runner_temp.parents)), 'INPUT_INVALID')
        candidate = _private_path(args.output, repo, exists=False)
        _need(candidate.is_relative_to(runner_temp), 'INPUT_INVALID')
        output = candidate
        required = _read_requirement(args.required_capture_locator, repo) if args.required_capture_locator else None
        phase = 'AUTHENTICATED_READ_FAILED'
        with _fresh_reader(repo, runner_temp) as git:
            report = verify(git, run=args.run, day=args.day, head=args.head,
                            key=V.state_key('production', None), required_capture=required)
        _write(output, V._wire(report)+b'\n')
        print(V._wire(report).decode())
        return 0
    except Exception as exc:
        reason = str(exc) if type(exc) is ValueError and str(exc) in REASONS else phase
        report = dict(status='RETAINED_RUN_VERIFICATION_HOLD', reason=reason,
                      official_source_requests=0, live_artifact_requests=0, upstream_writes=0,
                      plaintext_published=False)
        if output is not None and not output.exists():
            _write(output, V._wire(report)+b'\n')
        print(V._wire(report).decode())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
