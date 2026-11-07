"""Gate the first V5 router on actual noncompleted publishers' pinned readers.

Only fresh GitHub workflow metadata and public Git code objects are read. A
verified legacy reader is a normal V4 wait; incomplete metadata, Git failures
and identity conflicts stop publication. Neither workflow controls nor official
race sources are used here.
"""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote

REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
WORKFLOW = 405276784
BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
STATUSES = ('queued', 'in_progress', 'waiting', 'pending', 'requested')
SOURCE_PATH = 'race_ai/saved_view_feed.py'
MAX_ACTIVE = 16
MAX_PAGE = 4*1024*1024
MAX_SOURCE = 512*1024
INSPECTION_SECONDS = 120


def _need(value, reason):
    if not value:
        raise ValueError('HISTORY_'+reason)


def _head(value):
    _need(type(value) is str and re.fullmatch('[a-f0-9]{40}', value), 'RUN_IDENTITY_INVALID')
    return value


def _run_id(value):
    _need(type(value) is int and 0 < value < 10**20, 'RUN_IDENTITY_INVALID')
    return value


def _page(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_PAGE, 'RUN_PAGE_INVALID')

    def unique(items):
        output = {}
        for key, value in items:
            _need(key not in output, 'RUN_PAGE_INVALID')
            output[key] = value
        return output

    def nonfinite(_):
        raise ValueError('HISTORY_RUN_PAGE_INVALID')

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('HISTORY_RUN_PAGE_INVALID') from None
    _need(type(value) is dict and type(value.get('total_count')) is int and
          0 <= value['total_count'] <= 100 and type(value.get('workflow_runs')) is list and
          len(value['workflow_runs']) == value['total_count'], 'RUN_PAGE_INCOMPLETE')
    return value['workflow_runs']


def _identity(row, status):
    _need(type(row) is dict, 'RUN_IDENTITY_INVALID')
    _run_id(row.get('id')); _head(row.get('head_sha'))
    _need(type(row.get('workflow_id')) is int and row['workflow_id'] == WORKFLOW and
          row.get('head_branch') == BRANCH and row.get('status') == status, 'RUN_IDENTITY_INVALID')
    for field in ('repository', 'head_repository'):
        repository = row.get(field)
        _need(type(repository) is dict and type(repository.get('id')) is int and
              repository['id'] == REPO_ID and repository.get('full_name') == REPO, 'RUN_IDENTITY_INVALID')
    return row['id'], row['head_sha']


def _reader_supports_history(raw):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_SOURCE, 'PINNED_SOURCE_INVALID')
    try:
        tree = ast.parse(raw, filename=SOURCE_PATH)
    except (ValueError, SyntaxError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('HISTORY_PINNED_SOURCE_INVALID') from None
    name = 'HISTORY_READER_PROTOCOL'
    declarations = [node for node in tree.body if isinstance(node, ast.Assign) and
                    len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and
                    node.targets[0].id == name]
    bindings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == name:
            bindings.append(node)
        elif isinstance(node, ast.alias) and (node.name == '*' or (node.asname or node.name.split('.')[0]) == name):
            bindings.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            bindings.append(node)
    if len(declarations) != 1 or len(bindings) != 1:
        return False
    value = declarations[0].value
    return isinstance(value, ast.Constant) and type(value.value) is int and value.value == 5


def inspect_publishers(get, read_code, *, current_run_id, current_head):
    """Return aggregate compatibility; transports are explicit read capabilities.

    Each status page is filtered to this workflow and source branch. Repeated
    IDs across statuses are allowed while a run moves through the queue, but
    their pinned head cannot change. No metadata/code error becomes an empty
    active set or a legacy wait.
    """
    _run_id(current_run_id); _head(current_head)
    found = {}
    for status in STATUSES:
        path = (f'actions/workflows/{WORKFLOW}/runs?branch={quote(BRANCH, safe="")}'
                f'&status={status}&per_page=100&page=1')
        try:
            raw = get(path)
        except Exception:
            raise ValueError('HISTORY_GITHUB_READ_FAILED') from None
        seen = set()
        for row in _page(raw):
            ident, head = _identity(row, status)
            _need(ident not in seen, 'RUN_PAGE_DUPLICATE'); seen.add(ident)
            _need(ident not in found or found[ident] == head, 'RUN_IDENTITY_CONFLICT')
            found[ident] = head
            _need(len(found) <= MAX_ACTIVE, 'ACTIVE_RUN_BOUND')
    if current_run_id in found:
        _need(found[current_run_id] == current_head, 'CURRENT_RUN_IDENTITY_CONFLICT')
        del found[current_run_id]
    known, compatible = {}, 0
    for head in found.values():
        if head not in known:
            try:
                source = read_code(head)
            except Exception:
                raise ValueError('HISTORY_PINNED_SOURCE_UNAVAILABLE') from None
            known[head] = _reader_supports_history(source)
        compatible += int(known[head])
    return dict(compatible=compatible == len(found), active_publishers=len(found),
                compatible_publishers=compatible, legacy_publishers=len(found)-compatible)


class _Inspection:
    """One shared deadline for fresh metadata and exact Git code-object reads."""
    def __init__(self, git, *, runner, clock):
        self.repo = Path(git.repo).resolve()
        self.remote = git.fetch_url
        _need(self.remote in {'https://github.com/'+REPO, 'https://github.com/'+REPO+'.git',
                             'git@github.com:'+REPO+'.git'}, 'GIT_REPOSITORY_REJECTED')
        self.runner, self.clock = runner, clock
        self.deadline = clock()+INSPECTION_SECONDS

    def run(self, args, *, seconds=15, limit=MAX_PAGE):
        left = self.deadline-self.clock()
        _need(left > 0, 'INSPECTION_TIMEOUT')
        try:
            result = self.runner(args, cwd=self.repo, capture_output=True, timeout=min(seconds, left))
        except (OSError, subprocess.SubprocessError):
            raise ValueError('HISTORY_INSPECTION_READ_FAILED') from None
        _need(self.clock() <= self.deadline, 'INSPECTION_TIMEOUT')
        _need(type(result.stdout) is bytes and len(result.stdout) <= limit, 'INSPECTION_READ_BOUND')
        return result

    def get(self, path):
        result = self.run(['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                           f'repos/{REPO}/'+path])
        _need(result.returncode == 0, 'GITHUB_READ_FAILED')
        return result.stdout

    def read_code(self, head):
        _head(head)
        present = self.run(['git', 'cat-file', '-t', head])
        if present.returncode != 0:
            _need(present.returncode == 128, 'GIT_OBJECT_READ_FAILED')
            rewrites = self.run(['git', 'config', '--get-regexp', r'^url\..*\.(insteadof|pushinsteadof)$'])
            _need(rewrites.returncode == 1, 'GIT_URL_REWRITES_REJECTED')
            fetched = self.run(['git', 'fetch', '--no-tags', '--no-write-fetch-head', '--depth=1',
                                self.remote, head], seconds=30)
            _need(fetched.returncode == 0, 'GIT_FETCH_FAILED')
            present = self.run(['git', 'cat-file', '-t', head])
        _need(present.returncode == 0 and present.stdout == b'commit\n', 'GIT_OBJECT_IDENTITY_INVALID')
        target = head+':'+SOURCE_PATH
        size = self.run(['git', 'cat-file', '-s', target])
        _need(size.returncode == 0 and re.fullmatch(rb'[0-9]+\n', size.stdout), 'GIT_SOURCE_READ_FAILED')
        length = int(size.stdout)
        _need(0 < length <= MAX_SOURCE, 'PINNED_SOURCE_BOUND')
        source = self.run(['git', 'show', target], limit=MAX_SOURCE)
        _need(source.returncode == 0 and len(source.stdout) == length, 'GIT_SOURCE_READ_FAILED')
        return source.stdout


def check_history_activation(git, *, environment=None, runner=None, clock=None):
    """Inspect production publishers without changing their workflow or state."""
    env = os.environ if environment is None else environment
    ident = env.get('GITHUB_RUN_ID')
    _need(type(ident) is str and re.fullmatch('[1-9][0-9]{0,19}', ident), 'CURRENT_RUN_IDENTITY_INVALID')
    current_head = _head(env.get('GITHUB_SHA'))
    inspection = _Inspection(git, runner=runner or subprocess.run, clock=clock or time.monotonic)
    return inspect_publishers(inspection.get, inspection.read_code,
                              current_run_id=int(ident), current_head=current_head)
