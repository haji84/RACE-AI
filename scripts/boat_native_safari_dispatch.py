"""Request the existing native Safari acceptance workflow from a trusted release.

Metadata-only GitHub reads and one fixed dispatch. This is neither forecast
authority nor acceptance proof. An uncertain POST is never retried.
"""
from collections.abc import Mapping
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
PAYLOAD = {'ref': 'main', 'inputs': {'browser': 'native-safari'}}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REASONS = frozenset(('TRUSTED_RELEASE_PUSH_REQUIRED', 'CURRENT_MAIN_MISMATCH',
    'SOURCE_RELEASE_MISMATCH', 'RUN_HISTORY_INVALID', 'GITHUB_READ_FAILED',
    'GITHUB_RESPONSE_INVALID', 'DISPATCH_ACK_UNCERTAIN', 'INPUT_INVALID',
    'GITHUB_CREDENTIAL_UNAVAILABLE', 'SAFARI_DISPATCH_FAILED'))


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
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def __call__(self, method, path, body=None):
        history = type(path) is str and re.fullmatch(re.escape(RUNS_PATH) +
            r'\?branch=main&event=workflow_dispatch&head_sha=[a-f0-9]{40}&per_page=100&page=(?:[1-9]|10)', path)
        valid = (method == 'GET' and body is None and (path in (MAIN_PATH, SOURCE_PATH) or history)) or (
            method == 'POST' and path == POST_PATH and type(body) is dict and body == PAYLOAD)
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
            error.close()
            raise DispatchHold('DISPATCH_ACK_UNCERTAIN' if method == 'POST' else 'GITHUB_READ_FAILED',
                               request_attempted=method == 'POST') from None
        except Exception as error:
            if isinstance(error, DispatchHold) and method == 'GET':
                raise
            raise DispatchHold('DISPATCH_ACK_UNCERTAIN' if method == 'POST' else 'GITHUB_READ_FAILED',
                               request_attempted=method == 'POST') from None


def repository(value):
    return (type(value) is dict and type(value.get('id')) is int and value['id'] == REPO_ID
            and value.get('full_name') == REPO)


def trusted_head(environment, event):
    require(isinstance(environment, Mapping) and type(event) is dict, 'TRUSTED_RELEASE_PUSH_REQUIRED')
    head = environment.get('GITHUB_SHA')
    commit = event.get('head_commit')
    require(type(head) is str and re.fullmatch('[a-f0-9]{40}', head)
        and environment.get('GITHUB_ACTIONS') == 'true' and environment.get('GITHUB_EVENT_NAME') == 'push'
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
