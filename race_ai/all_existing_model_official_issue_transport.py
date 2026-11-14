"""GitHub-only originals and create-only fixed-recovery ciphertext transport.

This transport has no source, workflow dispatch, rerun, key or issuance API.
Publication changes one computed ciphertext path on the existing transfer ref.
Callers independently authenticate remote bytes after publication.
"""
import base64
from hashlib import sha1, sha256
import json
import re
import subprocess

from .boat_all_model_store import MAX_WIRE
from .boat_pdca_github_handoff import REPO, TRANSFER_REF
from .boat_private_original_vault import _json as bounded_json


MAX_ARCHIVE = 64 * 1024 * 1024
MAX_JSON = 52 * 1024 * 1024
MAX_PUBLICATION_ATTEMPTS = 3
MAX_ANCESTRY_COMMITS = 64
MAX_COMPARISON_TREES = 128
MAX_COMPARISON_ENTRIES = 131072
_HEX40 = re.compile(r'[a-f0-9]{40}\Z')
_CAPSULE = re.compile(r'recovery/official-results/[a-f0-9]{64}/[a-f0-9]{40}/[1-9][0-9]{0,19}/2\.enc\Z')
_GET = re.compile(
    r'(?:pulls/71|actions/runs/[1-9][0-9]{0,19}'
    r'(?:/attempts/1(?:/jobs\?per_page=100)?|/attempts/2/jobs\?per_page=100|/artifacts\?per_page=100(?:&page=(?:[1-9]|1[0-6]))?)?'
    r'|actions/workflows/392270247/runs\?head_sha=[a-f0-9]{40}&event=pull_request&per_page=100'
    r'|actions/artifacts/[1-9][0-9]{0,19}(?:/zip)?'
    r'|git/ref/heads/state/boat-pdca-transfer|git/(?:commits|trees|blobs)/[a-f0-9]{40})\Z')
# These are the authenticated mutable heads/indexes of existing transfer-ref
# writers. Original manifests, proof/metadata JSON, ZIPs and ciphertext are not
# mutable. Their own readers still authenticate pointer contents and histories.
_MUTABLE_POINTERS = frozenset((
    'state/boat-pdca/v1/latest.json',
    'state/boat-venue-history/v1/latest.json',
    'state/boat-racer-daily/v1/latest.json',
    'state/boat-racer-intraday/v1/latest.json',
    'state/boat-original-maintenance/v1/progress.json',
))
_MUTABLE_INDEX = re.compile(
    r'(?:state/boat-original-recovery/v1/runs/[1-9][0-9]{0,19}/latest\.json'
    r'|state/boat-private-originals/v1/(?:lookup/(?:0|[1-9][0-9]{0,19})\.json'
    r'|[0-9]{4}-(?:0[1-9]|1[0-2])/(?:month\.json|runs/[1-9][0-9]{0,19}\.json)))\Z')


def _need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_' + reason)


class _GitHubDenied(ValueError):
    def __init__(self):
        super().__init__('OFFICIAL_ISSUE_TRANSPORT_GITHUB_DENIED')


class PublicationUnconfirmed(ValueError):
    """Safe hashes for read-only recovery; this is never issuance proof."""
    def __init__(self, commit, path, raw, parent, observed=None):
        super().__init__('OFFICIAL_ISSUE_TRANSPORT_PUBLICATION_UNCONFIRMED')
        self.publication_attempt = dict(
            state='UNCONFIRMED_DO_NOT_REISSUE', commit_sha=commit,
            capsule_path=path, capsule_sha256=sha256(raw).hexdigest(),
            expected_parent=parent, observed_head=observed,
            ref=TRANSFER_REF, source_requests=0)


def _hex40(value):
    _need(type(value) is str and _HEX40.fullmatch(value), 'OBJECT_ID')
    return value


def _path(value):
    _need(type(value) is str and _CAPSULE.fullmatch(value), 'CAPSULE_PATH')
    return value


def _wire(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_JSON') from None


def _document(raw):
    try:
        value = bounded_json(raw, MAX_JSON)
        _need(type(value) is dict, 'JSON_OBJECT')
        return value
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_JSON') from None


def _route(method, path):
    _need(type(path) is str and (
        (method == 'GET' and _GET.fullmatch(path)) or
        (method == 'POST' and path in ('git/blobs', 'git/trees', 'git/commits')) or
        (method == 'PATCH' and path == 'git/refs/heads/' + TRANSFER_REF)), 'ROUTE')


def _gh(method, path, body=None):
    """Send only allowlisted repository-relative requests to github.com."""
    _route(method, path)
    args = ['gh', 'api', '--hostname', 'github.com', 'repos/' + REPO + '/' + path, '--method', method]
    raw = None
    if body is not None:
        args += ['--input', '-']
        raw = _wire(body)
    try:
        result = subprocess.run(args, input=raw, capture_output=True, timeout=50, check=False)
        if result.returncode != 0 and re.search(rb'\bHTTP (?:401|403|429)\b', result.stderr):
            raise _GitHubDenied()
        _need(result.returncode == 0, 'GITHUB_REQUEST')
        return result.stdout
    except _GitHubDenied:
        raise
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_GITHUB_REQUEST') from None


class GithubIssueTransport:
    _validate_path = staticmethod(_path)
    _commit_message = 'Retain one consumed fixed official-result recovery capsule'
    def __init__(self, request=None):
        self._request = _gh if request is None else request
        _need(callable(self._request), 'REQUEST')

    def _call(self, method, path, body=None, *, limit=MAX_JSON):
        _route(method, path)
        try:
            raw = self._request(method, path, body)
            _need(type(raw) is bytes and 0 < len(raw) <= limit, 'RESPONSE_BOUND')
            return raw
        except _GitHubDenied:
            raise
        except Exception:
            raise ValueError('OFFICIAL_ISSUE_TRANSPORT_GITHUB_REQUEST') from None

    def json(self, path):
        return _document(self._call('GET', path))

    def archive(self, pin):
        _need(type(pin) is dict and set(pin) == {'id', 'digest', 'run_id', 'head_sha'} and
              type(pin['id']) is int and 0 < pin['id'] < 10**20 and
              type(pin['run_id']) is int and 0 < pin['run_id'] < 10**20 and
              type(pin['digest']) is str and re.fullmatch(r'sha256:[a-f0-9]{64}', pin['digest']), 'ARCHIVE_PIN')
        _hex40(pin['head_sha'])
        metadata = self.json('actions/artifacts/' + str(pin['id']))
        run = metadata.get('workflow_run')
        size = metadata.get('size_in_bytes')
        _need(metadata.get('id') == pin['id'] and type(metadata.get('id')) is int and
              metadata.get('digest') == pin['digest'] and metadata.get('expired') is False and
              type(size) is int and 0 < size <= MAX_ARCHIVE and type(run) is dict and
              type(run.get('id')) is int and run['id'] == pin['run_id'] and run.get('head_sha') == pin['head_sha'] and
              all(type(run.get(field)) is int and run[field] == 1416489937 for field in
                  ('repository_id', 'head_repository_id')), 'ARCHIVE_METADATA')
        raw = self._call('GET', 'actions/artifacts/' + str(pin['id']) + '/zip', limit=size)
        _need(len(raw) == size and raw.startswith(b'PK\x03\x04') and
              'sha256:' + sha256(raw).hexdigest() == pin['digest'], 'ARCHIVE_BYTES')
        return dict(raw=raw, metadata=metadata)

    def head(self):
        ref = self.json('git/ref/heads/' + TRANSFER_REF)
        _need(ref.get('ref') == 'refs/heads/' + TRANSFER_REF and type(ref.get('object')) is dict and
              ref['object'].get('type') == 'commit', 'EXISTING_TRANSFER_REF')
        return _hex40(ref['object'].get('sha'))

    def _root(self, commit):
        _hex40(commit)
        document = self.json('git/commits/' + commit)
        _need(document.get('sha') == commit and type(document.get('tree')) is dict, 'COMMIT_IDENTITY')
        return _hex40(document['tree'].get('sha'))

    def read_file(self, commit, path, limit):
        _hex40(commit)
        self._validate_path(path)
        _need(type(limit) is int and 0 < limit <= MAX_WIRE, 'FILE_BOUND')
        tree = self._root(commit)
        parts = path.split('/')
        for index, part in enumerate(parts):
            listing = self.json('git/trees/' + tree)
            rows = listing.get('tree')
            _need(listing.get('sha') == tree and listing.get('truncated') is False and
                  type(rows) is list and len(rows) <= 32768, 'TREE_BOUND')
            names = set()
            for row in rows:
                _need(type(row) is dict and type(row.get('path')) is str and
                      0 < len(row['path']) <= 255 and '/' not in row['path'] and
                      row['path'] not in ('.', '..') and '\x00' not in row['path'] and
                      row['path'] not in names, 'TREE_ENTRY')
                names.add(row['path'])
            found = [row for row in rows if row['path'] == part]
            if not found:
                return None
            row = found[0]
            ident = _hex40(row.get('sha'))
            if index < len(parts) - 1:
                _need(row.get('type') == 'tree' and row.get('mode') == '040000', 'PATH_TREE')
                tree = ident
                continue
            size = row.get('size')
            _need(row.get('type') == 'blob' and row.get('mode') == '100644' and
                  type(size) is int and 0 < size <= limit, 'BLOB_BOUND')
            blob = self.json('git/blobs/' + ident)
            _need(blob.get('sha') == ident and blob.get('encoding') == 'base64' and
                  type(blob.get('size')) is int and blob['size'] == size and
                  type(blob.get('content')) is str, 'BLOB_METADATA')
            try:
                encoded = blob['content'].replace('\n', '')
                raw = base64.b64decode(encoded, validate=True)
            except (ValueError, UnicodeError):
                raise ValueError('OFFICIAL_ISSUE_TRANSPORT_BLOB_BYTES') from None
            _need(len(raw) == size and base64.b64encode(raw).decode() == encoded and
                  sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == ident, 'BLOB_BYTES')
            return raw

    def _descends_from(self, commit, ancestor, *, stop_at=None):
        """Bounded immutable Git ancestry; equal trees alone are not ancestry."""
        _hex40(commit); _hex40(ancestor)
        if stop_at is not None:_hex40(stop_at)
        pending = [commit]; seen = set()
        while pending:
            current = pending.pop()
            if current == ancestor:
                return True
            # A freshly created child cannot be an ancestor below its known
            # parent. Do not search an entire old transfer history to prove
            # that a rejected candidate was never published.
            if current == stop_at:
                continue
            if current in seen:
                continue
            _need(len(seen) < MAX_ANCESTRY_COMMITS, 'REF_ANCESTRY_BOUND')
            seen.add(current)
            document = self.json('git/commits/' + current)
            parents = document.get('parents')
            _need(document.get('sha') == current and type(parents) is list and
                  len(parents) <= 8 and all(type(p) is dict for p in parents), 'COMMIT_PARENTS')
            ids = [_hex40(p.get('sha')) for p in parents]
            _need(len(ids) == len(set(ids)), 'COMMIT_PARENTS')
            if ancestor in ids:
                return True
            pending.extend(ids)
        return False

    def _preserve_originals(self, previous, current, cache, budget):
        """Compare only changed subtrees, preserving every unknown original."""
        def listing(tree):
            if tree not in cache:
                budget[0] += 1
                _need(budget[0] <= MAX_COMPARISON_TREES, 'REF_TREE_BOUND')
                value = self.json('git/trees/' + tree); rows = value.get('tree')
                _need(value.get('sha') == tree and value.get('truncated') is False and
                      type(rows) is list and len(rows) <= 32768, 'TREE_BOUND')
                budget[1] += len(rows)
                _need(budget[1] <= MAX_COMPARISON_ENTRIES, 'REF_TREE_ENTRY_BOUND')
                entries = {}
                for row in rows:
                    _need(type(row) is dict and type(row.get('path')) is str and
                          0 < len(row['path']) <= 255 and '/' not in row['path'] and
                          '\x00' not in row['path'] and row['path'] not in ('.', '..') and
                          row['path'] not in entries, 'TREE_ENTRY')
                    _hex40(row.get('sha'))
                    _need((row.get('type'), row.get('mode')) in (
                        ('tree', '040000'), ('blob', '100644'), ('blob', '100755'),
                        ('blob', '120000'), ('commit', '160000')), 'TREE_ENTRY')
                    entries[row['path']] = row
                cache[tree] = entries
            return cache[tree]
        pending = [('', self._root(previous), self._root(current))]
        while pending:
            prefix, old_tree, new_tree = pending.pop()
            if old_tree == new_tree:
                continue
            budget[2] += 1
            _need(budget[2] <= MAX_COMPARISON_TREES, 'REF_TREE_BOUND')
            old, new = listing(old_tree), listing(new_tree)
            for name, before in old.items():
                after = new.get(name); path = prefix + name
                _need(after is not None and after['mode'] == before['mode'] and
                      after['type'] == before['type'], 'ORIGINAL_REMOVED_OR_MODE_CHANGED')
                if before['sha'] == after['sha']:
                    continue
                if before['type'] == 'tree':
                    pending.append((path + '/', before['sha'], after['sha']))
                else:
                    _need(before['type'] == 'blob' and before['mode'] == '100644' and
                          (path in _MUTABLE_POINTERS or _MUTABLE_INDEX.fullmatch(path)),
                          'IMMUTABLE_ORIGINAL_CHANGED')

    def _advance(self, previous, current, cache, budget):
        _need(self._descends_from(current, previous), 'REF_NOT_DESCENDANT')
        if previous != current:
            self._preserve_originals(previous, current, cache, budget)

    def _published(self, commit, current, path, raw, cache, budget, *, parent):
        if not self._descends_from(current, commit, stop_at=parent):
            return False
        self._preserve_originals(commit, current, cache, budget)
        _need(self.read_file(current, path, MAX_WIRE) == raw, 'PUBLISHED_CAPSULE_CHANGED')
        return True

    def publish_capsule(self, path, raw, expected_parent, *, before_publish=None):
        self._validate_path(path)
        _hex40(expected_parent)
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_WIRE, 'CAPSULE_BOUND')
        _need(before_publish is None or callable(before_publish), 'PUBLICATION_CALLBACK')
        parent = self.head(); cache = {}; budget = [0, 0, 0]
        # Existing callers without fresh-admission support retain one-shot
        # stale-parent rejection. The issuer explicitly opts into bounded CAS.
        _need(before_publish is not None or parent == expected_parent, 'CONCURRENT_REF')
        self._advance(expected_parent, parent, cache, budget)
        _need(self.read_file(parent, path, MAX_WIRE) is None, 'CAPSULE_ALREADY_EXISTS')
        blob = _document(self._call('POST', 'git/blobs', dict(content=base64.b64encode(raw).decode(), encoding='base64')))
        expected_blob = sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        _need(blob.get('sha') == expected_blob, 'CREATED_BLOB_ID')
        attempts = MAX_PUBLICATION_ATTEMPTS if before_publish is not None else 1
        for attempt in range(attempts):
            current = self.head()
            _need(before_publish is not None or current == parent, 'CONCURRENT_REF')
            self._advance(parent, current, cache, budget); parent = current
            _need(self.read_file(parent, path, MAX_WIRE) is None, 'CAPSULE_ALREADY_EXISTS')
            tree = _document(self._call('POST', 'git/trees', dict(base_tree=self._root(parent), tree=[
                dict(path=path, mode='100644', type='blob', sha=expected_blob)])))
            tree_id = _hex40(tree.get('sha'))
            commit = _document(self._call('POST', 'git/commits', dict(
                message=self._commit_message, tree=tree_id, parents=[parent])))
            commit_id = _hex40(commit.get('sha'))
            _need(type(commit.get('tree')) is dict and commit['tree'].get('sha') == tree_id,
                  'CREATED_COMMIT_TREE')
            if before_publish is not None:
                before_publish()
            current = self.head()
            if current != parent:
                _need(before_publish is not None, 'CONCURRENT_REF')
                self._advance(parent, current, cache, budget)
                parent = current
                continue
            try:
                _document(self._call('PATCH', 'git/refs/heads/' + TRANSFER_REF,
                                     dict(sha=commit_id, force=False)))
            except _GitHubDenied:
                raise
            except ValueError:
                # A failed request may have reached GitHub. Only retry after a
                # real descendant makes the old force:false update impossible.
                try:
                    current = self.head()
                    if self._published(commit_id, current, path, raw, cache, budget, parent=parent):
                        return commit_id
                except ValueError:
                    raise PublicationUnconfirmed(commit_id, path, raw, parent) from None
                if before_publish is None or current == parent:
                    raise PublicationUnconfirmed(commit_id, path, raw, parent, current)
                self._advance(parent, current, cache, budget)
                _need(self.read_file(current, path, MAX_WIRE) is None, 'CAPSULE_ALREADY_EXISTS')
                parent = current
                continue
            try:
                current = self.head()
                _need(self._published(commit_id, current, path, raw, cache, budget, parent=parent), 'PUBLISHED_REF')
            except ValueError:
                raise PublicationUnconfirmed(commit_id, path, raw, parent) from None
            return commit_id
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_CONCURRENT_REF_BOUND')
