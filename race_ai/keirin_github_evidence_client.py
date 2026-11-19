"""Bounded read-only GitHub API transport for independent forecast evidence."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from http.client import HTTPException
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .keirin_github_origin_evidence import DEFAULT_POLICY

API = 'https://api.github.com/repos/haji84/RACE-AI'
MAX_BYTES = 8_000_000


class GitHubEvidenceError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise GitHubEvidenceError(code)


def only_named(items, name):
    need(type(items) is list and all(type(x) is dict for x in items),
         'GITHUB_EVIDENCE_LIST_REQUIRED')
    matched = [x for x in items if x.get('name') == name]
    need(len(matched) == 1, 'GITHUB_EVIDENCE_NAMED_OBJECT_MISSING_OR_AMBIGUOUS')
    return matched[0]


def _server_time(value):
    need(type(value) is str and re.fullmatch(
         r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z', value),
         'GITHUB_EVIDENCE_SERVER_TIMESTAMP_INVALID')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise GitHubEvidenceError('GITHUB_EVIDENCE_SERVER_TIMESTAMP_INVALID') from None


def _job_for_artifact(items, name, artifact):
    need(type(items) is list and all(type(item) is dict for item in items),
         'GITHUB_EVIDENCE_LIST_REQUIRED')
    created = _server_time(artifact.get('created_at'))
    candidates = []
    for job in items:
        if (job.get('name') != name or job.get('status') != 'completed' or
                job.get('conclusion') != 'success'):
            continue
        if _server_time(job.get('started_at')) <= created <= _server_time(job.get('completed_at')):
            candidates.append(job)
    # A later rerun can reuse the same job name. Only the successful job whose
    # server-recorded execution contains this immutable upload is relevant.
    return only_named(candidates, name)


def _artifact_url_allowed(url):
    if type(url) is not str or any(ord(char) < 32 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and parsed.username is None and
                parsed.password is None and parsed.port in (None, 443) and
                not parsed.fragment and
                (host.endswith('.blob.core.windows.net') or
                 host.endswith('.githubusercontent.com')))
    except ValueError:
        return False


def _strict_pairs(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, 'GITHUB_EVIDENCE_JSON_DUPLICATE_FIELD')
        value[key] = item
    return value


def _invalid_number(_):
    raise GitHubEvidenceError('GITHUB_EVIDENCE_JSON_NONFINITE_NUMBER')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise GitHubEvidenceError('GITHUB_API_UNEXPECTED_REDIRECT')


class ArtifactRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        need(_artifact_url_allowed(newurl),
             'GITHUB_ARTIFACT_REDIRECT_NOT_TRUSTED')
        # Authorization is an unredirected header. Explicit removal also
        # protects this method if a future caller supplied an ordinary header.
        clean = {k: v for k, v in req.headers.items()
                 if k.lower() not in ('authorization', 'cookie', 'proxy-authorization')}
        return Request(newurl, headers=clean, method='GET')


class GitHubEvidenceClient:
    def __init__(self, *, token=None, open_request=None):
        self._token = os.environ.get('GITHUB_TOKEN', '') if token is None else token
        # Invalid header exceptions can contain their value. Reject malformed
        # secrets before constructing a request, using only a fixed error code.
        need(type(self._token) is str and len(self._token) <= 4096 and
             all(33 <= ord(char) <= 126 for char in self._token),
             'GITHUB_EVIDENCE_TOKEN_INVALID')
        self._open = open_request
        self._cache = {}
        self._stopped_reason = None

    @property
    def stopped_reason(self):
        """Stable public code after denial/rate limit; never retry this client."""
        return self._stopped_reason

    def _read(self, path, *, archive=False):
        need(type(path) is str and re.fullmatch(
            r'/actions/(?:runs/[1-9][0-9]{0,17}(?:/(?:jobs\?per_page=100&filter=all|artifacts\?per_page=100))?|artifacts/[1-9][0-9]{0,17}/zip)', path),
            'GITHUB_EVIDENCE_PATH_NOT_ALLOWED')
        need(type(archive) is bool and path.endswith('/zip') == archive,
             'GITHUB_EVIDENCE_PATH_MODE_MISMATCH')
        if self._stopped_reason is not None:
            raise GitHubEvidenceError(self._stopped_reason)
        if path in self._cache:
            return self._cache[path]
        request = Request(API + path, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'RACE-AI-GitHub-Evidence/1.0',
        }, method='GET')
        if self._token:
            request.add_unredirected_header('Authorization', 'Bearer ' + self._token)
        opener = self._open or build_opener(
            ArtifactRedirect() if archive else NoRedirect()).open
        try:
            with opener(request, timeout=20) as response:
                need(response.status == 200, 'GITHUB_EVIDENCE_RESPONSE_NOT_OK')
                response_url = getattr(response, 'url', None)
                need(response_url == request.full_url or
                     (archive and _artifact_url_allowed(response_url)),
                     'GITHUB_EVIDENCE_RESPONSE_URL_INVALID')
                data = response.read(MAX_BYTES + 1)
                need(0 < len(data) <= MAX_BYTES, 'GITHUB_EVIDENCE_BYTES_INVALID')
        except HTTPError as exc:
            code = 'GITHUB_EVIDENCE_HTTP_' + str(exc.code)
            if exc.code in (401, 403, 429):
                self._stopped_reason = code
            raise GitHubEvidenceError(code) from None
        except (URLError, OSError, TimeoutError, HTTPException):
            raise GitHubEvidenceError('GITHUB_EVIDENCE_UNAVAILABLE') from None
        self._cache[path] = data
        return data

    def json(self, path):
        try:
            value = json.loads(self._read(path).decode('utf-8'),
                               object_pairs_hook=_strict_pairs,
                               parse_constant=_invalid_number)
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise GitHubEvidenceError('GITHUB_EVIDENCE_JSON_INVALID') from None
        need(type(value) is dict, 'GITHUB_EVIDENCE_OBJECT_REQUIRED')
        return value

    def read_run_bundle(self, run_id, *, policy=DEFAULT_POLICY):
        need(type(run_id) is str and re.fullmatch(r'[1-9][0-9]{0,17}', run_id),
             'GITHUB_EVIDENCE_RUN_ID_INVALID')
        run = self.json('/actions/runs/' + run_id)
        need(type(run.get('id')) is int and run['id'] == int(run_id) and
             run.get('url') == API + '/actions/runs/' + run_id and
             run.get('head_branch') == policy.allowed_ref.removeprefix('refs/heads/') and
             run.get('event') in policy.allowed_events and
             run.get('path') in (policy.producer_workflow_path, policy.readback_workflow_path),
             'GITHUB_EVIDENCE_RUN_LINEAGE_MISMATCH')
        for field in ('repository', 'head_repository'):
            repository = run.get(field)
            need(type(repository) is dict and
                 repository.get('id') == policy.repository_id and
                 repository.get('full_name') == policy.repository_full_name == 'haji84/RACE-AI',
                 'GITHUB_EVIDENCE_REPOSITORY_LINEAGE_MISMATCH')
        job_data = self.json('/actions/runs/' + run_id + '/jobs?per_page=100&filter=all')
        artifact_data = self.json('/actions/runs/' + run_id + '/artifacts?per_page=100')
        for data, label in ((job_data, 'jobs'), (artifact_data, 'artifacts')):
            need(type(data.get(label)) is list and
                 type(data.get('total_count')) is int and
                 data['total_count'] <= 100 and
                 data['total_count'] == len(data[label]),
                 'GITHUB_EVIDENCE_PAGINATION_INCOMPLETE')
        selected = {}
        for role in ('producer', 'readback'):
            name = getattr(policy, role+'_artifact_name').format(run_id=run_id)
            artifact = only_named(artifact_data['artifacts'], name)
            job = _job_for_artifact(job_data['jobs'],
                                    getattr(policy, role+'_job_name'), artifact)
            need(type(artifact.get('id')) is int and artifact['id'] > 0 and
                 artifact.get('expired') is False,
                 'GITHUB_EVIDENCE_ARTIFACT_EXPIRED_OR_INVALID')
            need(type(artifact.get('digest')) is str and re.fullmatch(
                 r'sha256:[0-9a-f]{64}', artifact['digest']) is not None,
                 'GITHUB_EVIDENCE_ARTIFACT_DIGEST_INVALID')
            artifact_id = str(artifact['id'])
            lineage = artifact.get('workflow_run')
            need(type(lineage) is dict and lineage.get('id') == int(run_id) and
                 lineage.get('repository_id') == policy.repository_id and
                 lineage.get('head_repository_id') == policy.repository_id and
                 lineage.get('head_sha') == run.get('head_sha') and
                 lineage.get('head_branch') == run.get('head_branch') and
                 artifact.get('url') == API + '/actions/artifacts/' + artifact_id and
                 artifact.get('archive_download_url') ==
                     API + '/actions/artifacts/' + artifact_id + '/zip' and
                 job.get('run_id') == int(run_id) and
                 job.get('run_url') == run['url'] and
                 job.get('head_sha') == run.get('head_sha'),
                 'GITHUB_EVIDENCE_ARTIFACT_OR_JOB_LINEAGE_MISMATCH')
            need(job.get('status') == 'completed' and job.get('conclusion') == 'success',
                 'GITHUB_EVIDENCE_JOB_NOT_SUCCESSFUL')
            selected[role] = (job, artifact)
        output = {}
        for role, (job, artifact) in selected.items():
            raw = self._read('/actions/artifacts/' + str(artifact['id']) + '/zip',
                             archive=True)
            # The caller may persist this bundle before per-race verification.
            # Never turn a truncated/corrupt HTTP 200 download into the only
            # durable copy of an otherwise valid immutable artifact.
            need(artifact['digest'] == 'sha256:' + sha256(raw).hexdigest(),
                 'GITHUB_EVIDENCE_ARTIFACT_DIGEST_MISMATCH')
            output[role] = {'run': run, 'job': job, 'artifact': artifact,
                            'archive_bytes': raw}
        return output
