"""Keyless, stdlib-only provenance for an exact tested source execution tree.

Git objects are data. This module neither imports code from the supplied Git
repository nor changes/fetches its refs. New current PR objects are read through
the fixed repository's existing JSON reader. No key or provider interface exists.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY = 'haji84/RACE-AI'
REPOSITORY_ID = 1416489937
OWNER = 'haji84'
OWNER_ID = 173585154
BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
BASE = 'codex/actions-four-sport-e2e'
WORKFLOW_ID = 392270247
WORKFLOW_PATH = '.github/workflows/forecast-audit-ui.yml'
BOOTSTRAP_PATH = 'scripts/official_frozen_execution.py'
REQUEST_PATH = 'audit/state/official-result-recovery-request.json'
ISSUE_PATH = 'audit/state/official-result-recovery-issue-request.json'
PREP_PATH = 'audit/state/official-result-recovery-prepare-request.json'
LOCATOR_PATH = 'docs/evidence/2026-11-07/official-personal-terms-cipher-locators.json'
ISSUE_SCHEMA = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2'
PREP_SCHEMA = 'RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3'
SOURCE_BINDING_SCHEMA = 'RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1'
PR64_HEAD = '761247bee0209e37b1af6b8885e92cad3e9260a5'
FIXED_PATHS = (WORKFLOW_PATH, BOOTSTRAP_PATH, 'requirements-history.txt', REQUEST_PATH,
               'race_ai/manual_official_capture.py', 'race_ai/permissioned_source_delivery.py', LOCATOR_PATH)
MAX_WIRE = 36 * 1024 * 1024
MAX_HISTORY = 128
MAX_GRAPH = 4096
MAX_TREE = 32768
FULL_CHECK_STEPS = ('Python synthetic journal to viewer projection tests',
                   'Verify isolated experimental video decoding and measurements')
_HEAD = re.compile(r'[a-f0-9]{40}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_PLAN = re.compile(r'audit/state/official-result-collection-plan-[a-f0-9]{64}\.enc\Z')
_TERMS = re.compile(r'audit/state/official-terms-[A-Za-z0-9_.-]+\.enc\Z')


def need(ok, reason):
    if not ok:
        raise ValueError('OFFICIAL_FROZEN_' + reason)


def _hex(value):
    return type(value) is str and _HEAD.fullmatch(value) is not None


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _digest(value):
    return sha256(_wire(value)).hexdigest()


def _json(raw, limit):
    need(type(raw) is bytes and 0 < len(raw) <= limit, 'JSON_BOUND')
    def pairs(rows):
        result = {}
        for name, value in rows:
            need(name not in result, 'JSON_DUPLICATE_KEY')
            result[name] = value
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda value: need(False, 'JSON_NONFINITE'))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('OFFICIAL_FROZEN_JSON_INVALID') from None
    need(type(value) is dict, 'JSON_OBJECT')
    return value


def _path_allowed(path):
    return type(path) is str and (path in FIXED_PATHS + (ISSUE_PATH, PREP_PATH)
                                 or _PLAN.fullmatch(path) is not None or _TERMS.fullmatch(path) is not None)


class _GitObjects:
    def __init__(self, root, reader, *, complete=True):
        root = Path(root).absolute()
        need(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), 'GIT_ROOT')
        self.root = root.resolve()
        self.reader = reader
        self._commits = {}
        self._trees = {}
        self._blobs = {}
        self._local = {}
        self._ancestry = {}
        self._histories = {}
        shallow = self.git(['rev-parse', '--is-shallow-repository']).strip()
        need(shallow in (b'false', b'true') and (not complete or shallow == b'false'), 'COMPLETE_GIT_HISTORY')

    def git(self, args, *, absent=False, limit=MAX_WIRE):
        try:
            value = subprocess.run(['git', '--no-replace-objects', *args], cwd=self.root,
                                   capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('OFFICIAL_FROZEN_GIT_READ') from None
        if absent and value.returncode in (1, 128):
            return None
        need(value.returncode == 0 and len(value.stdout) <= limit, 'GIT_READ')
        return value.stdout

    def local(self, head):
        need(_hex(head), 'COMMIT_SHA')
        if head not in self._local:
            self._local[head] = self.git(['cat-file', '-e', head + '^{commit}'], absent=True) is not None
        return self._local[head]

    def commit(self, head):
        need(_hex(head), 'COMMIT_SHA')
        if head not in self._commits:
            if self.local(head):
                raw = self.git(['show', '-s', '--format=%T%n%P%n%B', head], limit=1024 * 1024)
                pieces = raw.decode('utf-8').split('\n', 2)
                need(len(pieces) == 3, 'COMMIT_FIELDS')
                tree, parent_text, message = pieces
                value = dict(sha=head, tree=dict(sha=tree),
                             parents=[dict(sha=p) for p in parent_text.split()], message=message.rstrip('\n'))
            else:
                need(self.reader is not None, 'REMOTE_READER_REQUIRED')
                value = self.reader.json('git/commits/' + head)
            need(type(value) is dict and value.get('sha') == head and type(value.get('tree')) is dict
                 and _hex(value['tree'].get('sha')) and type(value.get('parents')) is list
                 and len(value['parents']) <= 32 and all(type(p) is dict and _hex(p.get('sha')) for p in value['parents'])
                 and len({p['sha'] for p in value['parents']}) == len(value['parents'])
                 and type(value.get('message')) is str and len(value['message'].encode('utf-8')) <= 1024 * 1024,
                 'COMMIT_OBJECT')
            self._commits[head] = dict(head_sha=head, tree_sha=value['tree']['sha'],
                                      parents=[p['sha'] for p in value['parents']],
                                      subject=value['message'].split('\n', 1)[0])
        return deepcopy(self._commits[head])

    def tree(self, ident):
        need(_hex(ident), 'TREE_SHA')
        if ident not in self._trees:
            if self.git(['cat-file', '-e', ident + '^{tree}'], absent=True) is not None:
                raw = self.git(['ls-tree', '-z', ident])
                rows = []
                for row in raw.split(b'\0'):
                    if not row:
                        continue
                    attrs, name = row.split(b'\t', 1)
                    mode, typ, sha = attrs.decode('ascii').split()
                    rows.append(dict(path=name.decode('utf-8'), mode=mode, type=typ, sha=sha))
                value = dict(sha=ident, truncated=False, tree=rows)
            else:
                need(self.reader is not None, 'REMOTE_READER_REQUIRED')
                value = self.reader.json('git/trees/' + ident)
            rows = value.get('tree') if type(value) is dict else None
            need(type(value) is dict and value.get('sha') == ident and value.get('truncated') is False
                 and type(rows) is list and len(rows) <= MAX_TREE, 'TREE_OBJECT')
            names = set()
            encoded_rows = []
            for row in rows:
                name = row.get('path') if type(row) is dict else None
                need(type(name) is str and 0 < len(name.encode('utf-8')) <= 255 and '/' not in name
                     and '\0' not in name and name not in ('.', '..') and name not in names
                     and _hex(row.get('sha')) and (row.get('mode'), row.get('type')) in
                     (('040000', 'tree'), ('100644', 'blob'), ('100755', 'blob'), ('120000', 'blob'), ('160000', 'commit')),
                     'TREE_ENTRY')
                names.add(name)
                mode = row['mode'].lstrip('0')
                encoded_rows.append((name.encode('utf-8') + (b'/' if row['type'] == 'tree' else b''),
                    mode.encode('ascii') + b' ' + name.encode('utf-8') + b'\0' + bytes.fromhex(row['sha'])))
            # Authenticate complete tree bytes, including names/modes; a JSON
            # response cannot splice an unrelated blob under a claimed SHA.
            tree_raw = b''.join(part for _, part in sorted(encoded_rows))
            need(sha1(b'tree ' + str(len(tree_raw)).encode() + b'\0' + tree_raw).hexdigest() == ident,
                 'TREE_IMMUTABLE_BYTES')
            self._trees[ident] = deepcopy(rows)
        return deepcopy(self._trees[ident])

    def entry(self, head, path):
        need(_hex(head) and _path_allowed(path), 'IMMUTABLE_PATH')
        tree = self.commit(head)['tree_sha']
        names = path.split('/')
        for index, name in enumerate(names):
            matches = [r for r in self.tree(tree) if r['path'] == name]
            if not matches:
                return None
            row = matches[0]
            if index == len(names) - 1:
                return row
            need(row['type'] == 'tree' and row['mode'] == '040000', 'PATH_TREE_MODE')
            tree = row['sha']

    def blob(self, ident, limit):
        need(_hex(ident) and type(limit) is int and 0 < limit <= MAX_WIRE, 'BLOB_BOUND')
        if ident not in self._blobs:
            if self.git(['cat-file', '-e', ident + '^{blob}'], absent=True) is not None:
                size = int(self.git(['cat-file', '-s', ident]))
                need(0 < size <= limit, 'BLOB_BOUND')
                raw = self.git(['cat-file', 'blob', ident], limit=limit)
            else:
                need(self.reader is not None, 'REMOTE_READER_REQUIRED')
                value = self.reader.json('git/blobs/' + ident)
                need(type(value) is dict and value.get('sha') == ident and value.get('encoding') == 'base64'
                     and type(value.get('size')) is int and 0 < value['size'] <= limit
                     and type(value.get('content')) is str and len(value['content']) <= MAX_WIRE * 2,
                     'BLOB_OBJECT')
                encoded = value['content'].replace('\n', '')
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, TypeError):
                    raise ValueError('OFFICIAL_FROZEN_BLOB_ENCODING') from None
                need(len(raw) == value['size'] and base64.b64encode(raw).decode() == encoded, 'BLOB_ENCODING')
            need(0 < len(raw) <= limit and sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == ident,
                 'BLOB_IMMUTABLE_BYTES')
            self._blobs[ident] = raw
        raw = self._blobs[ident]
        need(0 < len(raw) <= limit, 'BLOB_BOUND')
        return raw

    def read(self, head, path, limit):
        need(type(limit) is int and 0 < limit <= MAX_WIRE, 'BLOB_BOUND')
        row = self.entry(head, path)
        if row is None:
            return None
        need(row['type'] == 'blob' and row['mode'] == '100644', 'REGULAR_GIT_BLOB')
        return self.blob(row['sha'], limit)

    def ancestor(self, ancestor, descendant):
        need(_hex(ancestor) and _hex(descendant), 'ANCESTRY_SHA')
        pair = (ancestor, descendant)
        if pair in self._ancestry:
            return self._ancestry[pair]
        pending = [descendant]
        seen = set()
        result = False
        while pending:
            head = pending.pop()
            if head in seen:
                continue
            seen.add(head)
            need(len(seen) <= MAX_GRAPH, 'ANCESTRY_BOUND')
            if head == ancestor:
                result = True
                break
            if self.local(head) and self.local(ancestor):
                found = self.git(['merge-base', '--is-ancestor', ancestor, head], absent=True)
                if found is not None:
                    result = True
                    break
                continue
            pending.extend(self.commit(head)['parents'])
        self._ancestry[pair] = result
        return result

    def commit_facts(self, head):
        value = self.commit(head)
        parents = value['parents']
        if self.local(head):
            args = ['diff-tree', '--no-ext-diff', '--no-commit-id', '--name-only', '--no-renames', '-r', '-z']
            if not parents:
                args.extend(('--root', head))
            elif len(parents) > 1:
                args.extend((parents[0], head))
            else:
                args.append(head)
            changed = self.git(args).decode('utf-8').rstrip('\0').split('\0')
            if changed == ['']:
                changed = []
        else:
            before = self.commit(parents[0])['tree_sha'] if parents else None
            changed = []
            def compare(old, new, prefix=''):
                if old == new:
                    return
                left = {r['path']: r for r in self.tree(old)} if old else {}
                right = {r['path']: r for r in self.tree(new)} if new else {}
                for name in sorted(set(left) | set(right)):
                    a, b = left.get(name), right.get(name)
                    if a == b or a and b and (a['mode'], a['type'], a['sha']) == (b['mode'], b['type'], b['sha']):
                        continue
                    if (a is None or a['type'] == 'tree') and (b is None or b['type'] == 'tree'):
                        compare(a['sha'] if a else None, b['sha'] if b else None, prefix + name + '/')
                    else:
                        changed.append(prefix + name)
                    need(len(changed) <= MAX_TREE, 'CHANGED_FILES_BOUND')
            compare(before, value['tree_sha'])
        return dict(head_sha=head, parents=parents, subject=value['subject'], changed_files=changed)

    def history(self, head):
        need(_hex(head), 'HISTORY_HEAD')
        if head in self._histories:
            return list(self._histories[head])
        # Walk only unknown immutable tips. Local boundaries use Git's original
        # complete full-history query together, retaining topology across merges.
        boundaries = set()
        remote_postorder = []
        visited = set()
        active = set()
        def visit(node):
            if node in visited:
                return
            need(node not in active and len(visited) + len(active) < MAX_GRAPH, 'HISTORY_GRAPH_BOUND')
            if self.local(node):
                boundaries.add(node)
                visited.add(node)
                return
            active.add(node)
            for parent in self.commit(node)['parents']:
                visit(parent)
            active.remove(node)
            visited.add(node)
            remote_postorder.append(node)
        visit(head)
        local_changes = self.git(['rev-list', '--topo-order', '--full-history', '--max-count=129',
                                  *sorted(boundaries), '--', ISSUE_PATH]).decode().splitlines() if boundaries else []
        remote_changes = []
        for node in reversed(remote_postorder):
            parents = self.commit(node)['parents']
            entry = self.entry(node, ISSUE_PATH)
            inherited = [self.entry(p, ISSUE_PATH) for p in parents]
            signature = lambda row: None if row is None else (row['mode'], row['type'], row['sha'])
            if (not parents and entry is not None) or any(signature(p) != signature(entry) for p in inherited):
                remote_changes.append(node)
        changes = remote_changes + local_changes
        need(len(changes) <= MAX_HISTORY and len(set(changes)) == len(changes), 'ISSUE_HISTORY_BOUND')
        retained = []
        for node in changes:
            parents = self.commit(node)['parents']
            if len(parents) > 1:
                merged = self.read(node, ISSUE_PATH, 16384)
                inherited = [self.read(p, ISSUE_PATH, 16384) for p in parents]
                if type(merged) is bytes and merged in inherited and all(raw is None or raw == merged for raw in inherited):
                    continue
                if type(merged) is bytes and merged in inherited and all(type(raw) is bytes for raw in inherited):
                    epochs = [self._latest_actual_issue(parent, raw) for parent, raw in zip(parents, inherited)]
                    selected = {epoch for epoch, raw in zip(epochs, inherited) if raw == merged}
                    if None not in epochs and len(selected) == 1:
                        latest = next(iter(selected))
                        if all(self.ancestor(epoch, latest) for epoch in epochs):
                            # A UI branch can still carry the older real issue
                            # while another contains its later descendant. This
                            # only removes the merge pseudo-change: both actual
                            # epochs and every nonmerge/revocation stay above.
                            continue
            retained.append(node)
        self._histories[head] = tuple(retained)
        return list(retained)

    def _latest_actual_issue(self, head, expected_raw):
        changes = self.history(head)
        if not changes:
            return None
        latest = changes[0]
        if not all(self.ancestor(epoch, latest) for epoch in changes[1:]):
            return None
        if self.read(latest, ISSUE_PATH, 16384) != expected_raw:
            return None
        facts = self.commit_facts(latest)
        if len(facts['parents']) != 1 or facts['changed_files'] != [ISSUE_PATH] or not facts['subject'].startswith('official-results-issue:'):
            return None
        value = _json(expected_raw, 16384)
        target = value.get('target')
        if type(target) is not dict or not _hex(target.get('head_sha')):
            return None
        if value.get('schema') == 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1':
            return latest if facts['parents'] == [target['head_sha']] else None
        parent = value.get('intent_parent_sha')
        if value.get('schema') == ISSUE_SCHEMA and _hex(parent) and facts['parents'] == [parent] \
                and value.get('tested_execution_head_sha') == target['head_sha'] and self.ancestor(target['head_sha'], parent):
            return latest
        return None

    def term_paths(self, head):
        tree = self.commit(head)['tree_sha']
        for name in ('audit', 'state'):
            entries = [r for r in self.tree(tree) if r['path'] == name]
            need(len(entries) == 1 and entries[0]['type'] == 'tree' and entries[0]['mode'] == '040000', 'TERMS_DIRECTORY')
            tree = entries[0]['sha']
        return ['audit/state/' + r['path'] for r in self.tree(tree) if _TERMS.fullmatch('audit/state/' + r['path'])]

    def protected_changes_since(self, ancestor, descendant, paths):
        """Retain revocations even when a later commit restores identical bytes."""
        need(_hex(ancestor) and _hex(descendant) and all(_path_allowed(p) for p in paths), 'PROTECTED_HISTORY_PATH')
        if ancestor == descendant:
            return []
        def prefix(head, excluded=()):
            boundaries, postorder, seen, active = set(), [], set(), set()
            def visit(node):
                if node in excluded or node in seen:
                    return
                need(node not in active and len(seen) + len(active) < MAX_GRAPH, 'PROTECTED_HISTORY_GRAPH_BOUND')
                if self.local(node):
                    boundaries.add(node)
                    seen.add(node)
                    return
                active.add(node)
                for parent in self.commit(node)['parents']:
                    visit(parent)
                active.remove(node)
                seen.add(node)
                postorder.append(node)
            visit(head)
            return boundaries, postorder
        old_boundaries, old_remote = prefix(ancestor)
        boundaries, remote = prefix(descendant, set(old_remote))
        changes = []
        signature = lambda row: None if row is None else (row['mode'], row['type'], row['sha'])
        for node in reversed(remote):
            parents = self.commit(node)['parents']
            if any(any(signature(self.entry(node, path)) != signature(self.entry(parent, path)) for parent in parents)
                   or not parents and self.entry(node, path) is not None for path in paths):
                changes.append(node)
        if boundaries:
            changes.extend(self.git(['rev-list', '--topo-order', '--full-history', '--max-count=129',
                *sorted(boundaries), *('^' + h for h in sorted(old_boundaries)), '--', *paths]).decode().splitlines())
        need(len(changes) <= MAX_HISTORY and len(set(changes)) == len(changes), 'PROTECTED_HISTORY_BOUND')
        retained = []
        for node in changes:
            parents = self.commit(node)['parents']
            if len(parents) > 1:
                transparent = True
                for path in paths:
                    merged = self.read(node, path, MAX_WIRE)
                    inherited = [self.read(p, path, MAX_WIRE) for p in parents]
                    if merged is None and all(raw is None for raw in inherited):
                        continue
                    if not (type(merged) is bytes and merged in inherited
                            and all(raw is None or raw == merged for raw in inherited)):
                        transparent = False
                        break
                if transparent:
                    continue
            retained.append(node)
        return retained


class FrozenGitSnapshot:
    """Real intent lineage and a stable tested-code/source authority binding."""
    def __init__(self, git_root, intent_head, execution_head, *, reader, kind='issue'):
        need(kind in ('issue', 'prepare') and type(kind) is str and _hex(intent_head) and _hex(execution_head), 'SNAPSHOT_ARGUMENTS')
        self.root = Path(git_root).resolve()
        self.reader = reader
        self.kind = kind
        self.intent_head = intent_head
        self.execution_head = execution_head
        self._objects = _GitObjects(git_root, reader)
        self._intent = self.commit_facts(intent_head)
        path = ISSUE_PATH if kind == 'issue' else PREP_PATH
        prefix = 'official-results-issue:' if kind == 'issue' else 'official-results-prepare:'
        need(len(self._intent['parents']) == 1 and self._intent['changed_files'] == [path]
             and self._intent['subject'].startswith(prefix), 'INTENT_ONLY_CHILD')
        need(self.is_ancestor(execution_head, self._intent['parents'][0]), 'TESTED_CODE_ANCESTOR')
        self._intent_raw = self.read(intent_head, path, 32768)
        value = _json(self._intent_raw, 32768)
        if kind == 'prepare':
            need(value.get('schema') == PREP_SCHEMA and type(value.get('verified_code_ancestor')) is dict
                 and value['verified_code_ancestor'].get('head_sha') == execution_head
                 and type(value.get('previous_source')) is dict and value['previous_source'].get('head_sha') == execution_head,
                 'PREPARE_EXECUTION')
            history = self.issue_history(self._intent['parents'][0])
            need(bool(history), 'SOURCE_ISSUE_REQUIRED')
            source = history[0]
        else:
            source = intent_head
        self.source_head = source
        self._source_facts = self.commit_facts(source)
        self._source_raw = self.read(source, ISSUE_PATH, 16384)
        self.issue = _json(self._source_raw, 16384)
        issue = self.issue
        target = issue.get('target')
        need(issue.get('schema') == ISSUE_SCHEMA and issue.get('repository_id') == REPOSITORY_ID
             and type(issue.get('repository_id')) is int and issue.get('workflow_id') == WORKFLOW_ID
             and type(issue.get('workflow_id')) is int and type(issue.get('pull_request')) is int and issue['pull_request'] == 71
             and type(target) is dict and target.get('head_sha') == execution_head
             and issue.get('tested_execution_head_sha') == execution_head
             and type(target.get('run_id')) is int and 0 < target['run_id'] < 10**20
             and type(target.get('run_attempt')) is int and target['run_attempt'] == 2
             and self._source_facts['parents'] == [issue.get('intent_parent_sha')]
             and self._source_facts['changed_files'] == [ISSUE_PATH]
             and self._source_facts['subject'].startswith('official-results-issue:')
             and self.is_ancestor(execution_head, issue['intent_parent_sha']), 'SOURCE_ISSUE_LINEAGE')
        original = self.read(execution_head, REQUEST_PATH, 32768)
        need(type(original) is bytes and sha256(original).hexdigest() == issue.get('recovery_request_blob_sha256'),
             'REQUEST_IMMUTABLE_BYTES')
        request = _json(original, 32768)
        need(_digest(request) == issue.get('recovery_request_sha256'), 'REQUEST_CANONICAL_DIGEST')
        manifest = request.get('manifest')
        need(type(manifest) is dict and type(manifest.get('plan_path')) is str and _PLAN.fullmatch(manifest['plan_path'])
             and type(manifest.get('plan_sha256')) is str and _SHA.fullmatch(manifest['plan_sha256']), 'SELECTED_PLAN')
        selected = self.read(execution_head, manifest['plan_path'], MAX_WIRE)
        need(type(selected) is bytes and sha256(selected).hexdigest() == manifest['plan_sha256'], 'SELECTED_PLAN_BYTES')
        self._protected_paths = tuple(sorted(set(FIXED_PATHS + (manifest['plan_path'],) + tuple(self._objects.term_paths(execution_head)))))
        self._closure = {}
        for protected in self._protected_paths:
            raw = self.read(execution_head, protected, MAX_WIRE)
            need(type(raw) is bytes, 'PROTECTED_BLOB_REQUIRED')
            self._closure[protected] = sha256(raw).hexdigest()
        self._closure_digest = _digest(self._closure)
        self._assert_closure(source)
        self._assert_closure(intent_head)
        before = self.issue_history(execution_head)
        authoring = self.issue_history(issue['intent_parent_sha'])
        before_set = set(before)
        intervening = [h for h in authoring if h not in before_set]
        dispositions = issue.get('failed_issue_dispositions')
        need(type(dispositions) is list and len(dispositions) <= 8, 'FAILED_DISPOSITIONS')
        declared = []
        for descriptor in dispositions:
            need(type(descriptor) is dict and set(descriptor) == {'intent_head_sha', 'issue_blob_sha256'}
                 and _hex(descriptor['intent_head_sha']) and type(descriptor['issue_blob_sha256']) is str
                 and _SHA.fullmatch(descriptor['issue_blob_sha256']), 'FAILED_DESCRIPTOR')
            old_head = descriptor['intent_head_sha']
            raw = self.read(old_head, ISSUE_PATH, 16384)
            need(type(raw) is bytes and sha256(raw).hexdigest() == descriptor['issue_blob_sha256'], 'FAILED_DESCRIPTOR_BYTES')
            old_facts = self.commit_facts(old_head)
            need(len(old_facts['parents']) == 1 and old_facts['changed_files'] == [ISSUE_PATH]
                 and old_facts['subject'].startswith('official-results-issue:'), 'FAILED_DESCRIPTOR_LINEAGE')
            declared.append(old_head)
        need(len(set(declared)) == len(declared) and set(intervening) <= set(declared)
             and set(declared) <= set(authoring), 'UNDECLARED_ISSUE_EPOCH')
        need(all(self.is_ancestor(h, source) for h in authoring), 'INCOMPARABLE_ISSUE_HISTORY')
        self._source_binding = dict(schema=SOURCE_BINDING_SCHEMA, tested_execution_head_sha=execution_head,
            intent_head_sha=source, intent_parent_sha=issue['intent_parent_sha'], target=deepcopy(target),
            issue_request_blob_sha256=sha256(self._source_raw).hexdigest(),
            recovery_request_blob_sha256=issue['recovery_request_blob_sha256'],
            protected_files_sha256=self._closure_digest)
        self._frozen_binding = dict(schema='RACE_AI_OFFICIAL_FROZEN_EXECUTION_BINDING_V1',
            kind=kind, intent_head_sha=intent_head, intent_parent_sha=self._intent['parents'][0],
            intent_blob_sha256=sha256(self._intent_raw).hexdigest(), source_frozen_binding=deepcopy(self._source_binding))
        self.facts = dict(self._intent, intent_head_sha=intent_head, execution_head_sha=execution_head, source_is_ancestor=True,
            source_issue_head=source, latest_issue_head_sha=source, latest_issue_raw=self._source_raw,
            recovery_raw=original, current_recovery_raw=self.read(intent_head, REQUEST_PATH, 32768),
            target_subject=self.commit_facts(execution_head)['subject'],
            tested_workflow_blob=self._objects.entry(execution_head, WORKFLOW_PATH)['sha'],
            protected_files_sha256=self._closure_digest, protected_files=deepcopy(self._closure),
            executed_workflow=None, source_frozen_binding=deepcopy(self._source_binding),
            frozen_binding=deepcopy(self._frozen_binding), current_admission=None,
            issue_history=self.issue_history(intent_head), intervening_issue_heads=intervening,
            issuer_parent=dict(self._source_facts, issue_raw=self._source_raw))

    def read(self, head, path, limit):
        return self._objects.read(head, path, limit)

    def commit_facts(self, head):
        return self._objects.commit_facts(head)

    def is_ancestor(self, ancestor, descendant):
        return self._objects.ancestor(ancestor, descendant)

    def issue_history(self, head):
        return self._objects.history(head)

    def previous_issue(self, head):
        history = self.issue_history(head)
        raw = self.read(head, ISSUE_PATH, 16384)
        if not history:
            need(raw is None, 'HISTORY_MARKER_REQUIRED')
            return None
        latest = history[0]
        need(all(self.is_ancestor(h, latest) for h in history[1:]), 'INCOMPARABLE_ISSUE_HISTORY')
        selected = self.read(latest, ISSUE_PATH, 16384)
        need(type(selected) is bytes and selected == raw, 'LATEST_ISSUE_MARKER_REQUIRED')
        value = _json(selected, 16384)
        actual = self.commit_facts(latest)
        target = value.get('target')
        need(type(target) is dict and _hex(target.get('head_sha'))
             and actual['changed_files'] == [ISSUE_PATH] and actual['subject'].startswith('official-results-issue:'),
             'LATEST_ISSUE_COMMIT_REQUIRED')
        if value.get('schema') == 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1':
            need(actual['parents'] == [target['head_sha']], 'LATEST_LEGACY_ISSUE_PARENT')
        else:
            parent = value.get('intent_parent_sha')
            need(value.get('schema') == ISSUE_SCHEMA and _hex(parent) and actual['parents'] == [parent]
                 and value.get('tested_execution_head_sha') == target['head_sha']
                 and self.is_ancestor(target['head_sha'], parent), 'LATEST_FROZEN_ISSUE_PARENT')
        return selected

    def _assert_closure(self, head):
        for path, expected in self._closure.items():
            raw = self.read(head, path, MAX_WIRE)
            need(type(raw) is bytes and sha256(raw).hexdigest() == expected, 'PROTECTED_AUTHORITY_CHANGED')

    def refresh(self, current_pr):
        need(type(current_pr) is dict and current_pr.get('number') == 71 and current_pr.get('state') == 'open'
             and current_pr.get('user', {}).get('id') == OWNER_ID and current_pr['user'].get('login') == OWNER
             and all(type(current_pr.get(side)) is dict and type(current_pr[side].get('repo')) is dict
                     and type(current_pr[side]['repo'].get('id')) is int and current_pr[side]['repo']['id'] == REPOSITORY_ID
                     and current_pr[side]['repo'].get('full_name') == REPOSITORY for side in ('head', 'base'))
             and current_pr['head'].get('ref') == BRANCH and current_pr['base'].get('ref') == BASE,
             'CURRENT_PR_SCOPE')
        current = current_pr['head'].get('sha')
        need(_hex(current) and self.is_ancestor(self.intent_head, current), 'CURRENT_INTENT_ANCESTOR')
        history = self.issue_history(current)
        need(bool(history) and history[0] == self.source_head
             and all(self.is_ancestor(h, self.source_head) for h in history[1:])
             and self.read(current, ISSUE_PATH, 16384) == self._source_raw, 'CURRENT_ACTIVE_ISSUE')
        self._assert_closure(current)
        need(not self._objects.protected_changes_since(self.source_head, current, self._protected_paths),
             'PROTECTED_AUTHORITY_HISTORY_CHANGED')
        if self.kind == 'prepare':
            need(self.read(current, PREP_PATH, 32768) == self._intent_raw, 'CURRENT_ACTIVE_PREPARE')
            need(not self._objects.protected_changes_since(self.intent_head, current, (PREP_PATH,)),
                 'PREPARE_INTENT_HISTORY_CHANGED')
        self.facts.update(current_head_sha=current, intent_is_ancestor_of_current=True,
            current_recovery_raw=self.read(current, REQUEST_PATH, 32768),
            issue_history=history, latest_issue_head_sha=self.source_head,
            current_admission=dict(schema='RACE_AI_OFFICIAL_FROZEN_CURRENT_ADMISSION_V1',
                current_head_sha=current, intent_head_sha=self.intent_head, latest_issue_head_sha=self.source_head,
                current_pr_head_sha=current, intent_is_ancestor=True, current_issue_head_sha=self.source_head,
                issue_history_count=len(history), protected_files_sha256=self._closure_digest))
        return deepcopy(self.facts)


def _clock(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00')) if type(value) is str else value
        need(type(stamp) is datetime and stamp.utcoffset() is not None, 'AWARE_CLOCK')
    except (ValueError, TypeError, AttributeError):
        raise ValueError('OFFICIAL_FROZEN_AWARE_CLOCK') from None
    return stamp


def _run_receipt(value, *, head, run_id):
    need(type(value) is dict and type(value.get('id')) is int and value['id'] == run_id
         and value.get('head_sha') == head and value.get('workflow_id') == WORKFLOW_ID
         and value.get('path') == WORKFLOW_PATH and value.get('head_branch') == BRANCH
         and value.get('event') == 'pull_request' and type(value.get('run_attempt')) is int
         and value['run_attempt'] > 0 and all(type(value.get(side)) is dict
             and type(value[side].get('id')) is int and value[side]['id'] == REPOSITORY_ID
             and value[side].get('full_name') == REPOSITORY for side in ('repository', 'head_repository'))
         and type(value.get('pull_requests')) is list
         and any(type(p) is dict and type(p.get('number')) is int and p['number'] == 71 for p in value['pull_requests'])
         and all(type(value.get(actor)) is dict and type(value[actor].get('id')) is int
                 and value[actor]['id'] == OWNER_ID and value[actor].get('login') == OWNER
                 for actor in ('actor', 'triggering_actor')), 'ACTUAL_RUN_SCOPE')
    _clock(value.get('run_started_at'))
    _clock(value.get('updated_at'))
    return {k: deepcopy(value[k]) for k in ('id', 'head_sha', 'run_attempt', 'status', 'conclusion', 'updated_at', 'run_started_at')}


def verify_full_first(reader, execution_head, run_id, *, viewer_job_id=None, now=None):
    """Replay the exact first-attempt heavy-step witness using only metadata."""
    need(_hex(execution_head) and type(run_id) is int and 0 < run_id < 10**20, 'FIRST_ATTEMPT_TARGET')
    first = reader.json('actions/runs/' + str(run_id) + '/attempts/1')
    receipt = _run_receipt(first, head=execution_head, run_id=run_id)
    now = _clock(now) if now is not None else datetime.now(timezone.utc)
    need(receipt['run_attempt'] == 1 and receipt['status'] == 'completed' and receipt['conclusion'] == 'success'
         and _clock(receipt['run_started_at']) <= _clock(receipt['updated_at']) <= now, 'FULL_FIRST_ATTEMPT_REQUIRED')
    document = reader.json('actions/runs/' + str(run_id) + '/attempts/1/jobs?per_page=100')
    need(type(document) is dict and type(document.get('total_count')) is int and type(document.get('jobs')) is list
         and 1 <= document['total_count'] == len(document['jobs']) <= 100, 'FIRST_JOBS_COMPLETE')
    jobs = document['jobs']
    seen = set()
    for job in jobs:
        need(type(job) is dict and type(job.get('id')) is int and job['id'] > 0 and job['id'] not in seen
             and type(job.get('run_id')) is int and job['run_id'] == run_id
             and type(job.get('run_attempt')) is int and job['run_attempt'] == 1
             and job.get('head_sha') == execution_head, 'FIRST_JOB_BINDING')
        seen.add(job['id'])
    viewers = [j for j in jobs if j.get('name') == 'Viewer audit contract']
    need(len(viewers) == 1 and viewers[0].get('status') == 'completed' and viewers[0].get('conclusion') == 'success',
         'FULL_VIEWER_JOB_REQUIRED')
    viewer = viewers[0]
    need(viewer_job_id is None or type(viewer_job_id) is int and viewer['id'] == viewer_job_id, 'EXACT_VIEWER_JOB')
    steps = viewer.get('steps')
    need(type(steps) is list and 2 <= len(steps) <= 128, 'FULL_FIRST_STEPS_REQUIRED')
    checked = []
    for name in FULL_CHECK_STEPS:
        matches = [s for s in steps if type(s) is dict and s.get('name') == name]
        need(len(matches) == 1 and matches[0].get('status') == 'completed' and matches[0].get('conclusion') == 'success'
             and type(matches[0].get('number')) is int, 'FULL_FIRST_STEPS_REQUIRED')
        step = matches[0]
        need(_clock(step.get('started_at')) <= _clock(step.get('completed_at')) <= _clock(receipt['updated_at']) + timedelta(seconds=1),
             'FIRST_STEP_CLOCK')
        checked.append({k: step[k] for k in ('name', 'number', 'status', 'conclusion', 'started_at', 'completed_at')})
    proof = dict(schema='RACE_AI_SAME_HEAD_PRIOR_FULL_VERIFICATION_V1', first_attempt=receipt,
                 first_jobs_sha256=_digest(document), viewer_job_id=viewer['id'], verified_steps=checked)
    return dict(verified_first_attempt=1, verified_first_run_id=run_id, verified_first_head_sha=execution_head,
                prior_full_jobs_sha256=_digest(document), prior_full_verification_sha256=_digest(proof))


def source_admission(git_root, execution_head, run_id, *, reader, current_pr=None):
    """Discover real active issuer before key lookup; this creates no authority.

    Declared failed dispositions remain pending the issuer module's independent
    terminal-HOLD/capability-absence checks. The caller must perform those checks
    before a key lookup and again before dispatch. No missing epoch is omitted.
    """
    need(_hex(execution_head) and type(run_id) is int and 0 < run_id < 10**20, 'SOURCE_TARGET')
    objects = _GitObjects(git_root, reader)
    need(objects.git(['rev-parse', 'HEAD']).decode().strip() == execution_head, 'SOURCE_CHECKOUT_HEAD')
    pr = current_pr if current_pr is not None else reader.json('pulls/71')
    need(type(pr) is dict and type(pr.get('head')) is dict and _hex(pr['head'].get('sha')), 'CURRENT_PR_SCOPE')
    history = objects.history(pr['head']['sha'])
    need(bool(history), 'ACTIVE_SOURCE_ISSUE_REQUIRED')
    snapshot = FrozenGitSnapshot(git_root, history[0], execution_head, reader=reader, kind='issue')
    snapshot.refresh(pr)
    need(snapshot.issue['target'] == dict(head_sha=execution_head, run_id=run_id, run_attempt=2), 'EXACT_SOURCE_TARGET')
    actual = _run_receipt(reader.json('actions/runs/' + str(run_id)), head=execution_head, run_id=run_id)
    need(actual['run_attempt'] == 2, 'ACTUAL_SOURCE_ATTEMPT_TWO')
    snapshot.facts['prior_full_verification'] = verify_full_first(reader, execution_head, run_id,
        viewer_job_id=snapshot.issue.get('target_first_viewer_job_id'))
    return snapshot


def executed_workflow(snapshot, environment):
    """Bind the actual merge workflow, rather than a working-tree YAML file."""
    commit = environment.get('GITHUB_WORKFLOW_SHA')
    need(_hex(commit) and commit == environment.get('GITHUB_SHA'), 'ACTUAL_WORKFLOW_ENVIRONMENT')
    actual = snapshot._objects.commit(commit)
    need(len(actual['parents']) <= 2 and (commit == snapshot.intent_head or snapshot.intent_head in actual['parents']),
         'ACTUAL_WORKFLOW_COMMIT')
    row = snapshot._objects.entry(commit, WORKFLOW_PATH)
    need(type(row) is dict and row['mode'] == '100644' and row['type'] == 'blob'
         and row['sha'] == snapshot.facts['tested_workflow_blob'], 'ACTUAL_WORKFLOW_BLOB')
    return dict(commit_sha=commit, head_sha=snapshot.intent_head, blob_sha=row['sha'])


def execution_witness(git_root, execution_root, intent_head, execution_head, *, reader):
    """Witness the actual private B2 interpreter tree immediately before key use.

    The caller has already checked its owner Actions environment. This verifies
    tree/runtime provenance only and confers no source/decryption authority.
    """
    need(_hex(intent_head) and _hex(execution_head), 'RUNTIME_HEAD')
    root = Path(execution_root).absolute()
    metadata_root = Path(git_root).absolute()
    temp = Path(os.environ.get('RUNNER_TEMP', '')).absolute()
    need(root.is_dir() and temp.is_dir() and Path(os.environ.get('RUNNER_TEMP', '')).is_absolute()
         and not any(p.is_symlink() for p in (root, *root.parents)) and root.is_relative_to(temp)
         and not root.is_relative_to(metadata_root.resolve()) and Path(__file__).resolve() == root / BOOTSTRAP_PATH,
         'RUNTIME_PRIVATE_ROOT')
    objects = _GitObjects(root, reader)
    need(objects.git(['rev-parse', 'HEAD']).decode().strip() == execution_head
         and objects.git(['diff', '--no-ext-diff', '--quiet', 'HEAD', '--'], absent=True) is not None
         and objects.git(['diff', '--no-ext-diff', '--cached', '--quiet', 'HEAD', '--'], absent=True) is not None,
         'RUNTIME_CLEAN_TESTED_TREE')
    # The isolated loader controls sys.path. Independently reject any project
    # module already loaded from the mutable PR data checkout, or an untracked
    # module injected into the private B2 tree.
    for search in sys.path:
        need(type(search) is str and not Path(search or '.').absolute().is_relative_to(metadata_root.resolve()),
             'CURRENT_PROJECT_IMPORT_PATH')
    reference_roots = {}
    def admitted_origin(path, *, directory=False):
        path = Path(path).absolute()
        need(not any(p.is_symlink() for p in (path, *path.parents))
             and not path.is_relative_to(metadata_root.resolve()), 'CURRENT_PROJECT_MODULE_LOADED')
        if path.is_relative_to(root):
            source = objects
            project = root
        else:
            need(path.is_relative_to(temp), 'UNVERIFIED_PROJECT_MODULE_ORIGIN')
            candidates = [p for p in (path.parent, *path.parents) if (p / '.git').exists()]
            need(bool(candidates), 'UNVERIFIED_PROJECT_MODULE_ORIGIN')
            project = candidates[0]
            if project not in reference_roots:
                # The immutable parser checkout may be a normal shallow exact
                # SHA checkout; it is never used to prove source/issue ancestry.
                reference = _GitObjects(project, reader, complete=False)
                need(reference.git(['rev-parse', 'HEAD']).decode().strip() == PR64_HEAD
                     and reference.git(['diff', '--no-ext-diff', '--quiet', 'HEAD', '--'], absent=True) is not None,
                     'IMMUTABLE_REFERENCE_REQUIRED')
                reference_roots[project] = reference
            source = reference_roots[project]
        relative = path.relative_to(project).as_posix()
        need(directory or path.suffix == '.py', 'RUNTIME_PROJECT_MODULE_TYPE')
        tracked = source.git(['ls-files', '--error-unmatch', '--', relative], absent=True)
        need(tracked is not None and len(tracked) > 0, 'RUNTIME_UNTRACKED_PROJECT_MODULE')
    for name, module in tuple(sys.modules.items()):
        location = getattr(module, '__file__', None)
        if location is not None:
            need(not Path(location).absolute().is_relative_to(metadata_root.resolve()), 'CURRENT_PROJECT_MODULE_LOADED')
        if name != 'race_ai' and not name.startswith('race_ai.') and name != 'scripts' and not name.startswith('scripts.'):
            continue
        if location is not None:
            admitted_origin(location)
        for package_path in getattr(module, '__path__', ()):
            admitted_origin(package_path, directory=True)
    facts = _GitObjects(metadata_root, reader).commit_facts(intent_head)
    kind = 'issue' if facts['changed_files'] == [ISSUE_PATH] else 'prepare'
    snapshot = FrozenGitSnapshot(metadata_root, intent_head, execution_head, reader=reader, kind=kind)
    workflow = executed_workflow(snapshot, dict(os.environ))
    need(Path(__file__).read_bytes() == snapshot.read(execution_head, BOOTSTRAP_PATH, MAX_WIRE), 'RUNTIME_BOOTSTRAP_BYTES')
    return dict(frozen_code_execution=True, current_pr_code_executed=False, executed_workflow=workflow)


def _trusted_bootstrap_environment(environment, intent_head):
    env = environment
    need(type(env) is dict and env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == REPOSITORY
         and env.get('GITHUB_REPOSITORY_ID') == str(REPOSITORY_ID) and env.get('GITHUB_EVENT_NAME') == 'pull_request'
         and env.get('GITHUB_RUN_ATTEMPT') == '1' and env.get('GITHUB_ACTOR') == OWNER
         and env.get('GITHUB_ACTOR_ID') == str(OWNER_ID) and env.get('GITHUB_TRIGGERING_ACTOR') == OWNER
         and env.get('GITHUB_REF') == 'refs/pull/71/merge'
         and env.get('GITHUB_WORKFLOW_REF') == REPOSITORY + '/' + WORKFLOW_PATH + '@refs/pull/71/merge',
         'ACTIONS_OWNER_ONLY')
    run = env.get('GITHUB_RUN_ID')
    need(type(run) is str and re.fullmatch(r'[1-9][0-9]{0,19}', run), 'ISSUER_RUN')
    event_path = Path(env.get('GITHUB_EVENT_PATH', '')).absolute()
    need(event_path.is_file() and not any(p.is_symlink() for p in (event_path, *event_path.parents))
         and 0 < event_path.stat().st_size <= 1024 * 1024, 'EVENT_FILE')
    event = _json(event_path.read_bytes(), 1024 * 1024)
    pr = event.get('pull_request')
    need(type(pr) is dict and type(event.get('number')) is int and event['number'] == 71
         and type(event.get('sender')) is dict and event['sender'].get('id') == OWNER_ID
         and event['sender'].get('login') == OWNER and type(event.get('repository')) is dict
         and event['repository'].get('id') == REPOSITORY_ID and event['repository'].get('full_name') == REPOSITORY
         and type(pr.get('head')) is dict and pr['head'].get('sha') == intent_head
         and pr['head'].get('ref') == BRANCH and type(pr['head'].get('repo')) is dict
         and pr['head']['repo'].get('id') == REPOSITORY_ID and pr['head']['repo'].get('full_name') == REPOSITORY,
         'EVENT_SCOPE')
    return int(run)


def _private_bootstrap_output(out_dir, environment, git_root):
    value = str(out_dir)
    need(type(out_dir) in (str, Path) or isinstance(out_dir, Path), 'PRIVATE_OUTPUT')
    need('\n' not in value and '\r' not in value and '\0' not in value, 'PRIVATE_OUTPUT')
    path = Path(out_dir).absolute()
    temp = Path(environment.get('RUNNER_TEMP', '')).absolute()
    need(temp.is_dir() and Path(environment.get('RUNNER_TEMP', '')).is_absolute()
         and not any(p.is_symlink() for p in (temp, *temp.parents))
         and path != temp and path.is_relative_to(temp) and not path.is_relative_to(Path(git_root).resolve())
         and '..' not in path.parts and not path.exists()
         and not any(p.is_symlink() for p in (path, *path.parents)) and path.parent == temp,
         'PRIVATE_OUTPUT')
    return path


def _immutable_reference(root, reader):
    """Validate only the existing literal PR64 parser, never a source ancestor."""
    reference = _GitObjects(root, reader, complete=False)
    need(reference.git(['rev-parse', '--show-toplevel']).decode().strip() == str(reference.root)
         and reference.git(['rev-parse', 'HEAD']).decode().strip() == PR64_HEAD
         and reference.git(['diff', '--no-ext-diff', '--quiet', 'HEAD', '--'], absent=True) is not None
         and reference.git(['diff', '--no-ext-diff', '--cached', '--quiet', 'HEAD', '--'], absent=True) is not None,
         'IMMUTABLE_REFERENCE_REQUIRED')
    return reference


def prepare_execution(git_root, intent_head, *, reader, kind='issue', out_dir, environment=None):
    """Verify public provenance, then materialize the entire tested B2 tree.

    This function is deliberately stdlib-only and runs before pip and secret
    steps. The workflow loader supplies these exact bytes from B2. A successful
    result is code provenance, never permission to decrypt or dispatch a source.
    """
    environment = dict(os.environ) if environment is None else dict(environment)
    need(_hex(intent_head) and type(kind) is str and kind in ('issue', 'prepare'), 'BOOTSTRAP_ARGUMENTS')
    run_id = _trusted_bootstrap_environment(environment, intent_head)
    output = _private_bootstrap_output(out_dir, environment, git_root)
    objects = _GitObjects(git_root, reader)
    need(objects.git(['rev-parse', 'HEAD']).decode().strip() == intent_head, 'EVENT_CHECKOUT_HEAD')
    intent_path = ISSUE_PATH if kind == 'issue' else PREP_PATH
    intent = _json(objects.read(intent_head, intent_path, 32768), 32768)
    if kind == 'issue':
        need(intent.get('schema') == ISSUE_SCHEMA, 'BOOTSTRAP_ISSUE_SCHEMA')
        execution_head = intent.get('tested_execution_head_sha')
    else:
        need(intent.get('schema') == PREP_SCHEMA and type(intent.get('verified_code_ancestor')) is dict,
             'BOOTSTRAP_PREPARE_SCHEMA')
        execution_head = intent['verified_code_ancestor'].get('head_sha')
    need(_hex(execution_head) and objects.local(execution_head), 'LOCAL_EXECUTION_HEAD')
    snapshot = FrozenGitSnapshot(git_root, intent_head, execution_head, reader=reader, kind=kind)
    facts = snapshot.refresh(reader.json('pulls/71'))
    workflow = executed_workflow(snapshot, environment)
    bootstrap_raw = snapshot.read(execution_head, BOOTSTRAP_PATH, MAX_WIRE)
    need(Path(__file__).read_bytes() == bootstrap_raw, 'EXECUTED_BOOTSTRAP_BYTES')
    issuer = _run_receipt(reader.json('actions/runs/' + str(run_id)), head=intent_head, run_id=run_id)
    need(issuer['run_attempt'] == 1 and issuer['status'] in ('queued', 'in_progress'), 'ISSUER_ATTEMPT_ONE')
    target = snapshot.issue['target']
    need(run_id != target['run_id'], 'ISSUER_IS_SOURCE')
    first_proof = verify_full_first(reader, execution_head, target['run_id'],
                                   viewer_job_id=snapshot.issue.get('target_first_viewer_job_id'))
    target_current = _run_receipt(reader.json('actions/runs/' + str(target['run_id'])),
                                  head=execution_head, run_id=target['run_id'])
    if kind == 'issue':
        need(target_current['run_attempt'] == 1 and target_current['status'] == 'completed'
             and target_current['conclusion'] == 'success', 'TARGET_ACTUAL_FIRST_ONLY')
    else:
        need(target_current['run_attempt'] == 2 and target_current['status'] == 'completed'
             and target_current['conclusion'] == 'success', 'PREVIOUS_SOURCE_COMPLETED_TWO')
    # Re-sample current intent after metadata reads, before materializing any
    # executable tree or handing a path to a subsequent dependency/secret step.
    facts = snapshot.refresh(reader.json('pulls/71'))
    reference = _immutable_reference(objects.root / 'pr64-reference', reader)
    output.mkdir(mode=0o700)
    execution = output / 'execution'
    command = ['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
               'worktree', 'add', '--detach', str(execution), execution_head]
    try:
        completed = subprocess.run(command, cwd=objects.root, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('OFFICIAL_FROZEN_PRIVATE_CHECKOUT') from None
    need(completed.returncode == 0 and execution.is_dir() and not execution.is_symlink(), 'PRIVATE_CHECKOUT')
    checked_head = subprocess.run(['git', '--no-replace-objects', 'rev-parse', 'HEAD'], cwd=execution,
                                 capture_output=True, timeout=30, check=False)
    checked_tree = subprocess.run(['git', '--no-replace-objects', 'rev-parse', 'HEAD^{tree}'], cwd=execution,
                                 capture_output=True, timeout=30, check=False)
    need(checked_head.returncode == checked_tree.returncode == 0
         and checked_head.stdout.decode().strip() == execution_head
         and checked_tree.stdout.decode().strip() == objects.commit(execution_head)['tree_sha'], 'PRIVATE_CHECKOUT_IDENTITY')
    for path, checksum in facts['protected_files'].items():
        item = execution / path
        need(item.is_file() and not any(p.is_symlink() for p in (item, *item.parents))
             and sha256(item.read_bytes()).hexdigest() == checksum, 'PRIVATE_CHECKOUT_PROTECTED_BYTES')
    private_reference = output / 'pr64-reference'
    try:
        retained = subprocess.run(['git', '--no-replace-objects', '-c', 'core.hooksPath=/dev/null',
            '-c', 'core.fsmonitor=false', 'worktree', 'add', '--detach', str(private_reference), PR64_HEAD],
            cwd=reference.root, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('OFFICIAL_FROZEN_PRIVATE_REFERENCE_CHECKOUT') from None
    need(retained.returncode == 0 and private_reference.is_dir() and not private_reference.is_symlink(),
         'PRIVATE_REFERENCE_CHECKOUT')
    os.chmod(private_reference, 0o700)
    _immutable_reference(private_reference, reader)
    proof = dict(schema='RACE_AI_OFFICIAL_FROZEN_EXECUTION_PROVENANCE_V1', ready=True,
        kind=kind, intent_head_sha=intent_head, execution_head_sha=execution_head,
        parents=facts['parents'], source_frozen_binding=facts['source_frozen_binding'],
        frozen_binding=dict(facts['frozen_binding'], executed_workflow=workflow),
        current_admission=facts['current_admission'], executed_workflow=workflow,
        prior_full_verification=first_proof, source_requests=0, plaintext_published=False,
        production_promoted=False, actual_purchases=False)
    provenance = output / 'provenance.json'
    with provenance.open('xb') as stream:
        os.chmod(provenance, 0o600)
        stream.write(_wire(proof) + b'\n')
    return dict(execution_root=str(execution), git_root=str(objects.root), intent_head=intent_head,
                execution_head=execution_head, provenance_path=str(provenance))


class _GithubJsonReader:
    def json(self, path):
        need(type(path) is str and re.fullmatch(r'(?:pulls/71|git/(?:commits|trees|blobs)/[a-f0-9]{40}|'
             r'actions/runs/[1-9][0-9]{0,19}(?:/attempts/1(?:/jobs\?per_page=100)?)?)', path), 'GITHUB_ROUTE')
        try:
            value = subprocess.run(['gh', 'api', 'repos/' + REPOSITORY + '/' + path],
                                   capture_output=True, timeout=50, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('OFFICIAL_FROZEN_GITHUB_READ') from None
        need(value.returncode == 0, 'GITHUB_READ')
        return _json(value.stdout, 52 * 1024 * 1024)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-root', required=True)
    parser.add_argument('--intent-head', required=True)
    parser.add_argument('--kind', choices=('issue', 'prepare'), required=True)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args(argv)
    try:
        outputs = prepare_execution(args.git_root, args.intent_head, reader=_GithubJsonReader(),
                                    kind=args.kind, out_dir=args.out_dir)
        if os.environ.get('GITHUB_OUTPUT'):
            need(all(type(value) is str and '\n' not in value and '\r' not in value for value in outputs.values()), 'SAFE_OUTPUT')
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('ready=true\n')
                for name, value in outputs.items():
                    stream.write(name + '=' + value + '\n')
        print(json.dumps(dict(ready=True, state='VERIFIED_FROZEN_EXECUTION_PREPARED', source_requests=0,
                              intent_head_sha=outputs['intent_head'], execution_head_sha=outputs['execution_head']), sort_keys=True))
        return 0
    except Exception as exc:
        reason = str(exc)
        reason = reason if re.fullmatch(r'OFFICIAL_FROZEN_[A-Z0-9_]{1,100}', reason) else 'FROZEN_EXECUTION_UNAVAILABLE'
        print(json.dumps(dict(ready=False, state='HOLD_FROZEN_EXECUTION', reason=reason, source_requests=0), sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
