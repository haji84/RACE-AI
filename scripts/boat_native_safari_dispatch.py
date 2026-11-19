"""Request the existing native Safari acceptance workflow from a trusted release.

Metadata-only GitHub reads and one fixed dispatch. This is neither forecast
authority nor acceptance proof. An uncertain POST is never retried.
"""
import base64
from collections.abc import Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

from scripts.boat_main_dispatch_gate import RELEASE_SHA


REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
PREFIX = 'boat-owner-release: single-real-session-20261111'
MAIN_PATH = '/repos/haji84/RACE-AI/git/ref/heads/main'
SOURCE_PATH = '/repos/haji84/RACE-AI/git/ref/heads/production/boat-p0-p1-20261111'
RUNS_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/runs'
POST_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725/dispatches'
REPOSITORY_PATH = '/repos/haji84/RACE-AI'
WORKFLOW_PATH = '/repos/haji84/RACE-AI/actions/workflows/416758725'
COMMITS_PATH = '/repos/haji84/RACE-AI/commits/'
NATIVE_WORKFLOW = '.github/workflows/boat-owner-formal-live-pages-proof.yml'
CONTENTS_PATH = '/repos/haji84/RACE-AI/contents/' + NATIVE_WORKFLOW
CHECKER_PATH = 'scripts/boat_native_safari_acceptance.py'
CHECKER_CONTENTS_PATH = '/repos/haji84/RACE-AI/contents/' + CHECKER_PATH
CANDIDATE_STEP = 'Checkout the exact reviewed UI candidate for synthetic capture only'
CANDIDATE_PATH = '.native-safari-ui-candidate'
PAYLOAD = {'ref': 'main', 'inputs': {'browser': 'native-safari'}}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REASONS = frozenset(('TRUSTED_RELEASE_PUSH_REQUIRED', 'CURRENT_MAIN_MISMATCH',
    'SOURCE_RELEASE_MISMATCH', 'RUN_HISTORY_INVALID', 'GITHUB_READ_FAILED',
    'GITHUB_RESPONSE_INVALID', 'DISPATCH_ACK_UNCERTAIN', 'INPUT_INVALID',
    'GITHUB_CREDENTIAL_UNAVAILABLE', 'SAFARI_DISPATCH_FAILED',
    'CANDIDATE_CHANGE_PROOF_INVALID', 'EXISTING_NATIVE_WORKFLOW_REQUIRED'))


class DispatchHold(ValueError):
    def __init__(self, reason, *, request_attempted=False):
        super().__init__(reason)
        self.request_attempted = request_attempted is True


def require(value, reason, *, attempted=False):
    if not value:
        raise DispatchHold(reason, request_attempted=attempted)


def failure_report(error):
    reason = str(error) if isinstance(error, DispatchHold) and str(error) in REASONS else 'SAFARI_DISPATCH_FAILED'
    attempted = getattr(error, 'request_attempted', False) is True
    return {'status': 'NATIVE_SAFARI_DISPATCH_HOLD', 'reason': reason,
        'dispatch_requested': None if attempted else False, 'request_attempted': attempted,
        'request_acknowledged': False, 'native_verification_proven': False,
        'official_provider_gets': 0, 'owner_key_read': False}


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    def finite(value):
        raise ValueError('nonfinite number')
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite number')
        return number
    require(type(raw) is bytes and 0 < len(raw) <= MAX_RESPONSE_BYTES, 'GITHUB_RESPONSE_INVALID')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=finite, parse_float=finite_float)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise DispatchHold('GITHUB_RESPONSE_INVALID')


class GitHubAPI:
    def __init__(self, token):
        require(type(token) is str and 0 < len(token) <= 8192 and '\n' not in token and '\r' not in token,
                'GITHUB_CREDENTIAL_UNAVAILABLE')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, method, path, body=None):
        history = type(path) is str and re.fullmatch(re.escape(RUNS_PATH) +
            r'\?branch=main&event=workflow_dispatch&head_sha=[a-f0-9]{40}&per_page=100&page=(?:[1-9]|10)', path)
        metadata = type(path) is str and (
            path in (MAIN_PATH, SOURCE_PATH, REPOSITORY_PATH, WORKFLOW_PATH)
            or re.fullmatch(re.escape(COMMITS_PATH) + r'[a-f0-9]{40}', path)
            or re.fullmatch(re.escape(CONTENTS_PATH) + r'\?ref=[a-f0-9]{40}', path)
            or re.fullmatch(re.escape(CHECKER_CONTENTS_PATH) + r'\?ref=[a-f0-9]{40}', path))
        valid = type(method) is str and type(path) is str and (
            method == 'GET' and body is None and (metadata or history)
            or method == 'POST' and path == POST_PATH and type(body) is dict and body == PAYLOAD)
        require(valid, 'INPUT_INVALID')
        try:
            request = urllib.request.Request('https://api.github.com' + path,
                data=json.dumps(body, separators=(',', ':'), allow_nan=False).encode() if method == 'POST' else None,
                method=method, headers={'Authorization': 'Bearer ' + self.token,
                    'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                    'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'RACE-AI-fixed-native-acceptance/1'})
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(1 if method == 'POST' else MAX_RESPONSE_BYTES + 1)
                if method == 'POST':
                    require(response.status == 204 and raw == b'', 'DISPATCH_ACK_UNCERTAIN', attempted=True)
                    return None
                require(response.status == 200, 'GITHUB_RESPONSE_INVALID')
                return strict_json(raw)
        except urllib.error.HTTPError as error:
            try:
                error.close()
            finally:
                raise DispatchHold('DISPATCH_ACK_UNCERTAIN' if method == 'POST' else 'GITHUB_READ_FAILED',
                                   request_attempted=method == 'POST') from None
        except Exception as error:
            if isinstance(error, DispatchHold) and method == 'GET':
                raise
            raise DispatchHold('DISPATCH_ACK_UNCERTAIN' if method == 'POST' else 'GITHUB_READ_FAILED',
                               request_attempted=method == 'POST') from None


def repository(value):
    return (type(value) is dict and type(value.get('id')) is int and value['id'] == REPO_ID
            and value.get('full_name') == REPO and value.get('private') is False)


def trusted_head(environment, event):
    require(isinstance(environment, Mapping) and type(event) is dict, 'TRUSTED_RELEASE_PUSH_REQUIRED')
    head = environment.get('GITHUB_SHA')
    commit = event.get('head_commit')
    require(type(head) is str and re.fullmatch('[a-f0-9]{40}', head)
        and environment.get('GITHUB_ACTIONS') == 'true' and environment.get('GITHUB_EVENT_NAME') == 'push'
        and environment.get('GITHUB_RUN_ATTEMPT') == '1'
        and environment.get('GITHUB_REPOSITORY') == REPO and environment.get('GITHUB_REF') == 'refs/heads/main'
        and environment.get('GITHUB_WORKFLOW_REF') == REPO + '/.github/workflows/boat-racer-daily.yml@refs/heads/main'
        and repository(event.get('repository')) and event.get('ref') == 'refs/heads/main'
        and event.get('after') == head and type(commit) is dict and commit.get('id') == head
        and type(commit.get('message')) is str and commit['message'].startswith(PREFIX),
        'TRUSTED_RELEASE_PUSH_REQUIRED')
    require(type(RELEASE_SHA) is str and re.fullmatch('[a-f0-9]{40}', RELEASE_SHA), 'SOURCE_RELEASE_MISMATCH')
    return head


def read(request, path):
    try:
        return request('GET', path)
    except DispatchHold:
        raise
    except Exception:
        raise DispatchHold('GITHUB_READ_FAILED') from None


def current_refs(request, head):
    for path, ref, expected, reason in (
            (MAIN_PATH, 'refs/heads/main', head, 'CURRENT_MAIN_MISMATCH'),
            (SOURCE_PATH, 'refs/heads/production/boat-p0-p1-20261111', RELEASE_SHA, 'SOURCE_RELEASE_MISMATCH')):
        value = read(request, path)
        require(type(value) is dict and value.get('ref') == ref and type(value.get('object')) is dict
                and value['object'].get('sha') == expected, reason)


def step_end(lines, start):
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith('      - ') or line.strip() and not line.startswith('      '):
            return index
    return len(lines)


def workflow_candidate(value):
    reason = 'CANDIDATE_CHANGE_PROOF_INVALID'
    require(type(value) is dict and value.get('type') == 'file'
        and value.get('path') == NATIVE_WORKFLOW and value.get('encoding') == 'base64'
        and type(value.get('size')) is int and 0 < value['size'] <= MAX_RESPONSE_BYTES
        and type(value.get('sha')) is str and re.fullmatch('[a-f0-9]{40}', value['sha'])
        and type(value.get('content')) is str and 0 < len(value['content']) <= 2 * MAX_RESPONSE_BYTES,
        reason)
    try:
        encoded = value['content']
        require(re.fullmatch(r'[A-Za-z0-9+/=\n]+', encoded), reason)
        compact = encoded.replace('\n', '')
        raw = base64.b64decode(compact, validate=True)
        require(len(raw) == value['size'] and base64.b64encode(raw).decode('ascii') == compact
            and hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() == value['sha'],
            reason)
        body = raw.decode('utf-8')
    except DispatchHold:
        raise
    except Exception:
        raise DispatchHold(reason) from None
    require('\0' not in body and '\r' not in body, reason)
    lines = body.split('\n')
    label = '      - name: ' + CANDIDATE_STEP
    starts = [index for index, line in enumerate(lines) if line == label]
    require(len(starts) == 1 and body.count(CANDIDATE_STEP) == 1, reason)
    start = starts[0]
    end = step_end(lines, start)
    block = lines[start:end]
    position = 1
    if position < len(block) and block[position].startswith('        if: '):
        position += 1
    require(position + 1 < len(block)
        and re.fullmatch(r'        uses: actions/checkout@(?:[a-f0-9]{40}|v[1-9][0-9]*)', block[position])
        and block[position + 1] == '        with:', reason)
    inputs = {}
    input_lines = {}
    for offset in range(position + 2, len(block)):
        line = block[offset]
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'          (ref|path|persist-credentials): (.+)', line)
        require(match is not None and match[1] not in inputs, reason)
        inputs[match[1]] = match[2]
        input_lines[match[1]] = start + offset
    candidate = inputs.get('ref')
    require(type(candidate) is str and re.fullmatch('[a-f0-9]{40}', candidate)
        and inputs.get('path') == CANDIDATE_PATH
        and ('persist-credentials' not in inputs or inputs['persist-credentials'] == 'false'), reason)

    # The only second changing token is the candidate prefix in the existing
    # upload step's artifact name. Other occurrences remain byte-for-byte.
    uploads = [index for index, line in enumerate(lines)
               if line.startswith('        uses: actions/upload-artifact@')]
    require(len(uploads) == 1 and re.fullmatch(
        r'        uses: actions/upload-artifact@(?:[a-f0-9]{40}|v[1-9][0-9]*)', lines[uploads[0]]), reason)
    upload_index = uploads[0]
    upload_starts = [index for index in range(upload_index) if lines[index].startswith('      - ')]
    require(bool(upload_starts), reason)
    upload_start = upload_starts[-1]
    upload_end = step_end(lines, upload_start)
    require(upload_start != start and upload_index < upload_end, reason)
    uses_lines = [index for index in range(upload_start + 1, upload_end)
                  if re.match(r'\s*uses:', lines[index])]
    with_lines = [index for index in range(upload_start + 1, upload_end)
                  if lines[index] == '        with:']
    require(uses_lines == [upload_index] and len(with_lines) == 1
        and with_lines[0] > upload_index, reason)
    with_end = upload_end
    for index in range(with_lines[0] + 1, upload_end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith('#') and not line.startswith('          '):
            with_end = index
            break
    name_lines = [index for index in range(with_lines[0] + 1, with_end)
                  if re.match(r'\s*name:', lines[index])]
    require(len(name_lines) == 1, reason)
    artifact_index = name_lines[0]
    name_match = re.fullmatch(r'          name: (.+)', lines[artifact_index])
    require(name_match is not None, reason)
    name = name_match[1]
    prefix = candidate[:8]
    tokens = list(re.finditer(r'(?<![A-Za-z0-9_])' + re.escape(prefix) + r'(?![A-Za-z0-9_])', name))
    require(name.count(prefix) == 1 and len(tokens) == 1, reason)
    token = tokens[0]
    normalized = list(lines)
    normalized[input_lines['ref']] = '          ref: \0CANDIDATE_40\0'
    normalized[artifact_index] = '          name: ' + name[:token.start()] + '\0CANDIDATE_8\0' + name[token.end():]
    return candidate, '\n'.join(normalized)


def _candidate_change_proof(request, head):
    require(repository(read(request, REPOSITORY_PATH)), 'EXISTING_NATIVE_WORKFLOW_REQUIRED')
    workflow = read(request, WORKFLOW_PATH)
    require(type(workflow) is dict and type(workflow.get('id')) is int
        and workflow['id'] == 416758725 and workflow.get('path') == NATIVE_WORKFLOW
        and workflow.get('state') == 'active', 'EXISTING_NATIVE_WORKFLOW_REQUIRED')
    commit = read(request, COMMITS_PATH + head)
    reason = 'CANDIDATE_CHANGE_PROOF_INVALID'
    require(type(commit) is dict and commit.get('sha') == head
        and type(commit.get('parents')) is list and 1 <= len(commit['parents']) <= 2, reason)
    parents = []
    for parent in commit['parents']:
        require(type(parent) is dict and type(parent.get('sha')) is str
            and re.fullmatch('[a-f0-9]{40}', parent['sha'])
            and parent['sha'] != head and parent['sha'] not in parents, reason)
        parents.append(parent['sha'])
    current, current_body = workflow_candidate(read(request, CONTENTS_PATH + '?ref=' + head))
    previous, previous_body = workflow_candidate(read(request, CONTENTS_PATH + '?ref=' + parents[0]))
    require(current_body == previous_body, reason)
    return current != previous, parents[0]


def candidate_changed(request, head):
    return _candidate_change_proof(request, head)[0]


def _checker_body(value):
    """Bind complete immutable checker bytes without evaluating their contents."""
    reason = 'CANDIDATE_CHANGE_PROOF_INVALID'
    require(type(value) is dict and value.get('type') == 'file'
        and value.get('path') == CHECKER_PATH and value.get('encoding') == 'base64'
        and type(value.get('size')) is int and 0 < value['size'] <= MAX_RESPONSE_BYTES
        and type(value.get('sha')) is str and re.fullmatch('[a-f0-9]{40}', value['sha'])
        and type(value.get('content')) is str and 0 < len(value['content']) <= 2 * MAX_RESPONSE_BYTES,
        reason)
    try:
        encoded = value['content']
        require(re.fullmatch(r'[A-Za-z0-9+/=\n]+', encoded), reason)
        compact = encoded.replace('\n', '')
        raw = base64.b64decode(compact, validate=True)
        require(len(raw) == value['size'] and base64.b64encode(raw).decode('ascii') == compact
            and hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest() == value['sha'],
            reason)
        text = raw.decode('utf-8')
        require('\0' not in text and '\r' not in text, reason)
        return raw
    except DispatchHold:
        raise
    except Exception:
        raise DispatchHold(reason) from None


def checker_changed(request, head, first_parent):
    """One exact checker path at two distinct immutable, authenticated refs."""
    require(type(head) is str and re.fullmatch('[a-f0-9]{40}', head)
        and type(first_parent) is str and re.fullmatch('[a-f0-9]{40}', first_parent)
        and head != first_parent, 'CANDIDATE_CHANGE_PROOF_INVALID')
    current = _checker_body(read(request, CHECKER_CONTENTS_PATH + '?ref=' + head))
    previous = _checker_body(read(request, CHECKER_CONTENTS_PATH + '?ref=' + first_parent))
    return current != previous


def existing_count(request, head):
    total, seen, page = None, set(), 1
    while True:
        path = RUNS_PATH + '?branch=main&event=workflow_dispatch&head_sha=' + head + '&per_page=100&page=' + str(page)
        value = read(request, path)
        require(type(value) is dict and type(value.get('total_count')) is int
            and 0 <= value['total_count'] <= 1000 and type(value.get('workflow_runs')) is list,
            'RUN_HISTORY_INVALID')
        if total is None:
            total = value['total_count']
        require(value['total_count'] == total, 'RUN_HISTORY_INVALID')
        rows = value['workflow_runs']
        require(len(rows) == min(100, total - len(seen)), 'RUN_HISTORY_INVALID')
        for row in rows:
            require(type(row) is dict and type(row.get('id')) is int and 0 < row['id'] < 2**63
                and row['id'] not in seen and type(row.get('workflow_id')) is int and row['workflow_id'] == 416758725
                and row.get('event') == 'workflow_dispatch' and row.get('head_branch') == 'main'
                and row.get('head_sha') == head and repository(row.get('repository'))
                and repository(row.get('head_repository')) and type(row.get('status')) is str
                and 0 < len(row['status']) <= 100
                and (row.get('conclusion') is None or type(row.get('conclusion')) is str
                     and 0 < len(row['conclusion']) <= 100), 'RUN_HISTORY_INVALID')
            seen.add(row['id'])
        if len(seen) == total:
            return total
        page += 1
        require(page <= 10, 'RUN_HISTORY_INVALID')


def execute(environment, event, *, request):
    head = trusted_head(environment, event)
    current_refs(request, head)
    candidate_delta, first_parent = _candidate_change_proof(request, head)
    if not candidate_delta and not checker_changed(request, head, first_parent):
        return {'status': 'NATIVE_SAFARI_CANDIDATE_UNCHANGED', 'dispatch_requested': False,
            'request_attempted': False, 'request_acknowledged': False, 'existing_runs_count': None,
            'native_verification_proven': False, 'official_provider_gets': 0, 'owner_key_read': False}
    count = existing_count(request, head)
    if count:
        return {'status': 'NATIVE_SAFARI_ALREADY_REQUESTED_FOR_HEAD', 'dispatch_requested': False,
            'request_attempted': False, 'request_acknowledged': False, 'existing_runs_count': count,
            'native_verification_proven': False, 'official_provider_gets': 0, 'owner_key_read': False}
    # The API has no atomic compare-and-dispatch or idempotency key. Recheck
    # both refs immediately before the one POST; never retry an uncertain ACK.
    current_refs(request, head)
    try:
        result = request('POST', POST_PATH, {'ref': 'main', 'inputs': {'browser': 'native-safari'}})
        require(result is None, 'DISPATCH_ACK_UNCERTAIN', attempted=True)
    except Exception:
        raise DispatchHold('DISPATCH_ACK_UNCERTAIN', request_attempted=True) from None
    return {'status': 'NATIVE_SAFARI_DISPATCH_REQUESTED', 'dispatch_requested': True,
        'request_attempted': True, 'request_acknowledged': True, 'existing_runs_count': 0,
        'native_verification_proven': False, 'official_provider_gets': 0, 'owner_key_read': False}


def main(argv=None):
    try:
        require(not (sys.argv[1:] if argv is None else argv), 'INPUT_INVALID')
        name = os.environ.get('GITHUB_EVENT_PATH')
        require(type(name) is str and bool(name), 'INPUT_INVALID')
        path = Path(name)
        require(not path.is_symlink() and path.is_file() and 0 < path.stat().st_size <= 1024 * 1024, 'INPUT_INVALID')
        event = strict_json(path.read_bytes())
        result = execute(os.environ, event, request=GitHubAPI(os.environ.get('GH_TOKEN')))
    except Exception as error:
        print(json.dumps(failure_report(error), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
