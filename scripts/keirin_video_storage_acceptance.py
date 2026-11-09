#!/usr/bin/env python3
"""Secret-safe acceptance checks for the EXISTING KEIRIN S3 archive.

Never records, decrypts, creates a bucket, changes IAM, or trains a model.
A separate workflow consumes only the trusted main uploader's successful
job attestation, then performs a new HEAD/GET/SHA in a fresh runner.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

REPO = 'haji84/RACE-AI'
REPO_ID = 1416489937
WORKFLOWS = {
    '.github/workflows/keirin-github-autonomous.yml',
    '.github/workflows/keirin-personal-hourly-canary.yml',
}
ARCHIVE_STEP = 'Owner-private S3 upload must fail visibly if configured and readback fails'
HEX64 = re.compile(r'^[a-f0-9]{64}$')
HEX40 = re.compile(r'^[a-f0-9]{40}$')
MAX_BYTES = 4 * 1024 ** 3


def require(condition, code):
    if not condition:
        raise ValueError(code)


def configuration_status(env):
    required = {
        'ARCHIVE_BUCKET': 'RACE_AI_KEIRIN_S3_BUCKET',
        'AWS_ACCESS_KEY_ID': 'RACE_AI_KEIRIN_S3_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY': 'RACE_AI_KEIRIN_S3_SECRET_ACCESS_KEY',
    }
    missing = [name for field, name in required.items()
               if not isinstance(env.get(field), str) or not env[field].strip()]
    return {'configured': not missing, 'missing': missing,
            'values_redacted': True, 'connection_verified': False,
            'durable_storage_verified': False}


def validate_producer(event):
    source = event.get('workflow_run') if isinstance(event, dict) else None
    require(isinstance(source, dict), 'UNTRUSTED_SOURCE_EVENT')
    require(source.get('head_branch') == 'main'
            and source.get('event') in ('schedule', 'workflow_dispatch')
            and source.get('path') in WORKFLOWS
            and (source.get('repository') or {}).get('id') == REPO_ID
            and (source.get('head_repository') or {}).get('id') == REPO_ID,
            'UNTRUSTED_SOURCE_PRODUCER')
    require(type(source.get('id')) is int and source['id'] > 0
            and isinstance(source.get('head_sha'), str)
            and HEX40.fullmatch(source['head_sha']), 'INVALID_SOURCE_IDENTITY')
    return source


def archive_job_id(payload):
    require(isinstance(payload, dict) and isinstance(payload.get('jobs'), list),
            'INVALID_SOURCE_JOB_LIST')
    matches = []
    for job in payload['jobs']:
        require(isinstance(job, dict), 'INVALID_SOURCE_JOB')
        name = job.get('name', '')
        if not (name == 'capture-completed-races'
                or name.endswith('/ capture-completed-races')):
            continue
        steps = job.get('steps') or []
        if any(s.get('name') == ARCHIVE_STEP and s.get('conclusion') == 'success'
               for s in steps if isinstance(s, dict)):
            require(type(job.get('id')) is int and job['id'] > 0,
                    'INVALID_SOURCE_JOB_ID')
            matches.append(job['id'])
    require(len(matches) == 1, 'NO_UNIQUE_SUCCESSFUL_ARCHIVE_JOB')
    return matches[0]


def parse_attestation(log_text, expected_run):
    require(isinstance(log_text, str) and len(log_text) <= 32 * 1024 ** 2,
            'UPLOAD_ATTESTATION_LOG_TOO_LARGE')
    found = []
    for line in log_text.splitlines():
        line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line)
        start = line.find('{')
        if start < 0:
            continue
        try:
            row = json.loads(line[start:])
        except (ValueError, TypeError):
            continue
        if isinstance(row, dict) and row.get('status') == 'DURABLE_CIPHERTEXT_READBACK_VERIFIED':
            found.append(row)
    require(len(found) == 1, 'UPLOAD_ATTESTATION_MISSING_OR_AMBIGUOUS')
    row = found[0]
    require(row.get('github_run_id') == str(expected_run), 'UPLOAD_ATTESTATION_WRONG_RUN')
    day = row.get('day_jst')
    require(isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day),
            'UPLOAD_ATTESTATION_INVALID_DAY')
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError('UPLOAD_ATTESTATION_INVALID_DAY') from None
    require(isinstance(row.get('sha256'), str) and HEX64.fullmatch(row['sha256']),
            'UPLOAD_ATTESTATION_INVALID_SHA')
    require(type(row.get('cipher_objects')) is int and row['cipher_objects'] > 0,
            'UPLOAD_ATTESTATION_EMPTY_ARCHIVE')
    return {k: row[k] for k in ('day_jst', 'github_run_id', 'cipher_objects', 'sha256')}


def object_key(receipt):
    day = receipt['day_jst']
    run = receipt['github_run_id']
    require(isinstance(day, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', day),
            'INVALID_OBJECT_DAY')
    date.fromisoformat(day)
    require(isinstance(run, str) and re.fullmatch(r'[0-9]+', run), 'INVALID_OBJECT_RUN')
    return f'keirin/{day}/{run}/rsa-aes-sealed-wave.zip'


def verify_bytes(path, receipt):
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= MAX_BYTES, 'INVALID_READBACK_BYTES')
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    actual = digest.hexdigest()
    require(hmac.compare_digest(actual, receipt['sha256']),
            'INDEPENDENT_READBACK_SHA_MISMATCH')
    return actual


def run_command(argv, code, *, timeout=300):
    try:
        process = subprocess.run(argv, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=timeout,
                                 check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(code) from None
    require(process.returncode == 0, code)
    return process.stdout


def aws(arguments):
    command = ['aws']
    endpoint = os.environ.get('RACE_VIDEO_S3_ENDPOINT', '')
    if endpoint:
        parts = urlsplit(endpoint)
        require(parts.scheme == 'https' and parts.hostname
                and not parts.username and not parts.password
                and not parts.query and not parts.fragment,
                'UNSAFE_STORAGE_ENDPOINT')
        command += ['--endpoint-url', endpoint]
    return run_command(command + arguments, 'PRIVATE_STORAGE_REQUEST_FAILED')


def github(route):
    require(os.environ.get('GITHUB_REPOSITORY') == REPO
            and bool(os.environ.get('GH_TOKEN')), 'GITHUB_READER_NOT_AUTHORIZED')
    return run_command(['gh', 'api', '-H', 'Accept: application/vnd.github+json',
                        route], 'SOURCE_EVIDENCE_UNAVAILABLE')


def preflight():
    result = configuration_status(os.environ)
    if not result['configured']:
        return {**result, 'status': 'DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED'}, 2
    aws(['s3api', 'head-bucket', '--bucket', os.environ['ARCHIVE_BUCKET']])
    return {**result, 'connection_verified': True,
            'status': 'CONNECTION_CONFIRMED_NOT_ARCHIVED'}, 0


def readback():
    event_path = Path(os.environ['GITHUB_EVENT_PATH'])
    require(event_path.stat().st_size < 2 * 1024 ** 2, 'SOURCE_EVENT_TOO_LARGE')
    source = validate_producer(json.loads(event_path.read_text()))
    source_id = source['id']
    consumer_id = os.environ.get('GITHUB_RUN_ID', '')
    require(consumer_id.isdecimal() and consumer_id != str(source_id),
            'INDEPENDENT_WORKFLOW_RUN_REQUIRED')
    # Re-query the producer rather than trusting a caller-supplied artifact URL.
    remote = json.loads(github(f'/repos/{REPO}/actions/runs/{source_id}'))
    checked = validate_producer({'workflow_run': remote})
    require(checked['id'] == source_id and checked['head_sha'] == source['head_sha'],
            'SOURCE_IDENTITY_CHANGED')
    jobs = json.loads(github(f'/repos/{REPO}/actions/runs/{source_id}/jobs?per_page=100'))
    require(jobs.get('total_count', len(jobs.get('jobs', []))) <= 100,
            'SOURCE_JOB_LIST_TRUNCATED')
    try:
        job_id = archive_job_id(jobs)
    except ValueError as exc:
        if str(exc) != 'NO_UNIQUE_SUCCESSFUL_ARCHIVE_JOB':
            raise
        return {'status': 'SOURCE_ARCHIVE_NOT_ATTESTED',
                'source_run_id': source_id, 'consumer_run_id': consumer_id,
                'independent_readback_verified': False}, 2
    logs = github(f'/repos/{REPO}/actions/jobs/{job_id}/logs').decode('utf-8-sig', 'replace')
    receipt = parse_attestation(logs, source_id)
    status = configuration_status(os.environ)
    require(status['configured'], 'DURABLE_PRIVATE_STORAGE_NOT_CONFIGURED')
    bucket = os.environ['ARCHIVE_BUCKET']
    key = object_key(receipt)
    head = json.loads(aws(['s3api', 'head-object', '--bucket', bucket, '--key', key]))
    require(type(head.get('ContentLength')) is int
            and 0 < head['ContentLength'] <= MAX_BYTES
            and head.get('Metadata', {}).get('sha256') == receipt['sha256'],
            'INDEPENDENT_HEAD_MISMATCH')
    with TemporaryDirectory(prefix='keirin-cipher-readback-') as directory:
        target = Path(directory) / 'ciphertext.zip'
        aws(['s3api', 'get-object', '--bucket', bucket, '--key', key, str(target)])
        require(target.stat().st_size == head['ContentLength'], 'INDEPENDENT_SIZE_MISMATCH')
        actual = verify_bytes(target, receipt)
    return {'status': 'INDEPENDENT_WORKFLOW_S3_GET_SHA_VERIFIED',
            'source_run_id': source_id, 'source_commit': source['head_sha'],
            'consumer_run_id': consumer_id, 'day_jst': receipt['day_jst'],
            'ciphertext_sha256': actual, 'cipher_objects': receipt['cipher_objects'],
            'independent_readback_verified': True,
            'raw_video_decrypted': False, 'model_modified': False,
            'forever_retention_guaranteed': False}, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('preflight', 'readback'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result, code = preflight() if args.mode == 'preflight' else readback()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        message = str(exc)
        safe_code = message if re.fullmatch(r'[A-Z_0-9]+', message) else 'ACCEPTANCE_INPUT_OR_RUNTIME_FAILURE'
        result, code = {'status': safe_code, 'independent_readback_verified': False,
                        'durable_storage_verified': False, 'values_redacted': True}, 2
    text = json.dumps(result, sort_keys=True, ensure_ascii=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text + '\n', encoding='utf-8')
    args.output.chmod(0o600)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a', encoding='utf-8') as stream:
            stream.write('\n## KEIRIN storage acceptance\n\n```json\n' + text + '\n```\n')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
