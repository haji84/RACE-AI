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
_HEX40 = re.compile(r'[a-f0-9]{40}\Z')
_CAPSULE = re.compile(r'recovery/official-results/[a-f0-9]{64}/[a-f0-9]{40}/[1-9][0-9]{0,19}/2\.enc\Z')
_GET = re.compile(
    r'(?:pulls/71|actions/runs/[1-9][0-9]{0,19}'
    r'(?:/attempts/1(?:/jobs\?per_page=100)?|/artifacts\?per_page=100(?:&page=(?:[1-9]|1[0-6]))?)?'
    r'|actions/artifacts/[1-9][0-9]{0,19}(?:/zip)?'
    r'|git/ref/heads/state/boat-pdca-transfer|git/(?:commits|trees|blobs)/[a-f0-9]{40})\Z')


def _need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_' + reason)


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
        _need(result.returncode == 0, 'GITHUB_REQUEST')
        return result.stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('OFFICIAL_ISSUE_TRANSPORT_GITHUB_REQUEST') from None


class GithubIssueTransport:
    def __init__(self, request=None):
        self._request = _gh if request is None else request
        _need(callable(self._request), 'REQUEST')

    def _call(self, method, path, body=None, *, limit=MAX_JSON):
        _route(method, path)
        try:
            raw = self._request(method, path, body)
            _need(type(raw) is bytes and 0 < len(raw) <= limit, 'RESPONSE_BOUND')
            return raw
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
        _path(path)
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

    def publish_capsule(self, path, raw, expected_parent):
        _path(path)
        _hex40(expected_parent)
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_WIRE, 'CAPSULE_BOUND')
        _need(self.head() == expected_parent, 'CONCURRENT_REF')
        _need(self.read_file(expected_parent, path, MAX_WIRE) is None, 'CAPSULE_ALREADY_EXISTS')
        root = self._root(expected_parent)
        blob = _document(self._call('POST', 'git/blobs', dict(content=base64.b64encode(raw).decode(), encoding='base64')))
        expected_blob = sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        _need(blob.get('sha') == expected_blob, 'CREATED_BLOB_ID')
        tree = _document(self._call('POST', 'git/trees', dict(base_tree=root, tree=[
            dict(path=path, mode='100644', type='blob', sha=expected_blob)])))
        tree_id = _hex40(tree.get('sha'))
        commit = _document(self._call('POST', 'git/commits', dict(
            message='Retain one consumed fixed official-result recovery capsule',
            tree=tree_id, parents=[expected_parent])))
        commit_id = _hex40(commit.get('sha'))
        _need(type(commit.get('tree')) is dict and commit['tree'].get('sha') == tree_id, 'CREATED_COMMIT_TREE')
        _need(self.head() == expected_parent, 'CONCURRENT_REF')
        _document(self._call('PATCH', 'git/refs/heads/' + TRANSFER_REF, dict(sha=commit_id, force=False)))
        _need(self.head() == commit_id, 'PUBLISHED_REF')
        return commit_id
