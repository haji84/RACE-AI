"""Read immutable DT future ciphertext on a distinct protected manual runner.

Uses the existing GitHub evidence transport and server-artifact verifier. Local
readback is only a receipt; a later reader must verify this job's actual server
completion time before admitting a forecast as T-15 evidence. No owner key,
provider request, forecast reconstruction, state publication or scoring here.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import argparse
import json
import os
from pathlib import Path
import re
import stat
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED

from race_ai import keirin_github_origin_evidence as origin
from race_ai.keirin_github_evidence_client import (
    GitHubEvidenceClient, only_named, _job_for_artifact)


POLICY = origin.OriginPolicy(
    allowed_events=('workflow_dispatch',),
    producer_workflow_path='.github/workflows/keirin-result-live.yml',
    readback_workflow_path='.github/workflows/keirin-result-live.yml',
    producer_job_name='observe-results', readback_job_name='observe-results',
    producer_artifact_name='keirin-result-live-receipt-{run_id}',
    readback_artifact_name='keirin-result-live-receipt-{run_id}',
    producer_report_member='summary.json', readback_report_member='summary.json',
    minimum_margin_seconds=900)
CIPHER_ARTIFACT = 'keirin-dt-r1-future-cipher-{run_id}'
SCHEMA = 'DT_R1_FUTURE_SHADOW_READBACK_V1'
MAX_EXPANDED_BYTES = 128_000_000


def _need(ok, reason):
    if not ok:
        raise ValueError('DT_R1_FUTURE_READBACK_' + reason)


def _run_id(value):
    _need(type(value) is str and re.fullmatch('[1-9][0-9]{0,17}', value) is not None,
          'RUN_ID_REQUIRED')
    return value


def _inventory(client, run_id):
    run_id = _run_id(run_id)
    path = '/actions/runs/' + run_id
    run = client.json(path)
    _need(type(run.get('id')) is int and run['id'] == int(run_id), 'RUN_ID_MISMATCH')
    jobs = client.json(path + '/jobs?per_page=100&filter=all')
    artifacts = client.json(path + '/artifacts?per_page=100')
    for data, field in ((jobs, 'jobs'), (artifacts, 'artifacts')):
        _need(type(data.get(field)) is list and type(data.get('total_count')) is int and
              0 <= data['total_count'] <= 100 and data['total_count'] == len(data[field]),
              'PAGINATION_INCOMPLETE')
    return run, jobs['jobs'], artifacts['artifacts']


def _packet(client, run_id, artifact_name):
    run, jobs, artifacts = _inventory(client, run_id)
    artifact = only_named(artifacts, artifact_name)
    _need(type(artifact.get('id')) is int and 0 < artifact['id'] < 10 ** 18 and
          artifact.get('expired') is False, 'ARTIFACT_EXPIRED_OR_INVALID')
    job = _job_for_artifact(jobs, 'observe-results', artifact)
    raw = client._read('/actions/artifacts/' + str(artifact['id']) + '/zip', archive=True)
    return dict(run=run, job=job, artifact=artifact, archive_bytes=raw)


def fetch_report(client, run_id):
    """Fetch one exact safe report through existing bounded authenticated GETs."""
    run_id = _run_id(run_id)
    packet = _packet(client, run_id, POLICY.producer_artifact_name.format(run_id=run_id))
    result = origin._bundle(packet, role='producer', policy=origin._checked_policy(POLICY))
    result['packet'] = deepcopy(packet)
    return result


def _cipher_packet(client, run_id, producer):
    packet = _packet(client, run_id, CIPHER_ARTIFACT.format(run_id=run_id))
    artifact = packet['artifact']; reference = producer['packet']['artifact']
    _need(packet['run'] == producer['packet']['run'] and
          packet['job'] == producer['packet']['job'] and
          artifact.get('workflow_run') == reference['workflow_run'] and
          artifact.get('url') == 'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/' + str(artifact['id']) and
          artifact.get('archive_download_url') == artifact['url'] + '/zip' and
          artifact['id'] != reference['id'], 'CIPHER_ARTIFACT_LINEAGE')
    raw = packet['archive_bytes']
    _need(artifact.get('digest') == 'sha256:' + sha256(raw).hexdigest() and
          type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= origin.MAX_ARCHIVE_BYTES,
          'CIPHER_ARTIFACT_DIGEST')
    return packet


def _extract(raw, directory):
    """Bounded exact-name ZIP extraction into a new private temporary directory."""
    from race_ai import keirin_official_run_history as codec
    from race_ai import keirin_official_nationwide_records as records
    _need(type(raw) is bytes and 0 < len(raw) <= origin.MAX_ARCHIVE_BYTES, 'ZIP_BYTES')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            members = archive.infolist(); names = [m.filename for m in members]
            _need(1 <= len(members) <= records.MAX_RACES + 1 and len(names) == len(set(names)) and
                  'manifest.json' in names and sum(m.file_size for m in members) <= MAX_EXPANDED_BYTES,
                  'ZIP_INVENTORY')
            for item in members:
                _need(item.filename == 'manifest.json' or
                      re.fullmatch('[0-9a-f]{64}\\.sealed\\.json', item.filename) is not None, 'ZIP_MEMBER_NAME')
                limit = 2_000_000 if item.filename == 'manifest.json' else codec.MAX_CIPHER_BYTES
                _need(not item.is_dir() and not item.flag_bits & 1 and
                      not stat.S_ISLNK(item.external_attr >> 16) and
                      item.compress_type in (ZIP_DEFLATED, ZIP_STORED) and
                      0 < item.file_size <= limit, 'ZIP_MEMBER_TYPE_OR_SIZE')
            for item in members:
                with archive.open(item) as stream:
                    content = stream.read(item.file_size + 1)
                _need(len(content) == item.file_size, 'ZIP_MEMBER_TRUNCATED')
                fd = os.open(directory / item.filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
    except (BadZipFile, OSError, EOFError, RuntimeError):
        raise ValueError('DT_R1_FUTURE_READBACK_ZIP_INVALID') from None


@contextmanager
def verified_producer(producer_run_id, *, client=None):
    """Yield only verified ciphertext; cleanup occurs even if the caller fails."""
    from scripts import keirin_dt_r1_future_shadow as producer_code
    client = client or GitHubEvidenceClient()
    producer = fetch_report(client, producer_run_id)
    report = producer['report']
    _need(type(report) is dict and report.get('schema') == producer_code.SUMMARY_SCHEMA and
          type(report.get('manifest_sha256')) is str and
          re.fullmatch('[0-9a-f]{64}', report['manifest_sha256']) is not None,
          'PRODUCER_SUMMARY_REQUIRED')
    cipher = _cipher_packet(client, producer_run_id, producer)
    with TemporaryDirectory(prefix='dt-future-cipher-readback-') as temporary:
        directory = Path(temporary)
        _extract(cipher['archive_bytes'], directory)
        manifest = producer_code.verify_output(directory, expected_manifest_sha256=report['manifest_sha256'])
        saved = [entry['cipher'] for entry in manifest['entries'] if entry['cipher'] is not None]
        expected_report = dict(manifest['summary'], manifest_sha256=report['manifest_sha256'],
            manifest_bytes=(directory / 'manifest.json').stat().st_size,
            cipher_files=len(saved), cipher_bytes=sum(item['bytes'] for item in saved))
        _need(report == expected_report and
              report['reader_run_id'] == producer_run_id and report['reader_code_commit'] == producer['commit'] and
              producer['started_at'] <= origin._time(report['started_at']) <=
              origin._time(report['finished_at']) <= producer['completed_at'], 'PRODUCER_IDENTITY_OR_CLOCK')
        yield dict(directory=directory, manifest=manifest, manifest_sha256=report['manifest_sha256'],
                   producer=producer, cipher_packet=cipher)


def _receipt(verified, reader_run_id, reader_code_commit, observed):
    _run_id(reader_run_id)
    _need(type(reader_code_commit) is str and re.fullmatch('[0-9a-f]{40}', reader_code_commit) is not None,
          'READER_COMMIT_REQUIRED')
    producer = verified['producer']; manifest = verified['manifest']
    _need(reader_run_id != str(producer['run_id']) and observed >= producer['completed_at'],
          'DISTINCT_LATER_RUN_REQUIRED')
    rows = []
    for entry in manifest['entries']:
        if entry['cipher'] is not None:
            rows.append(dict(slot_sha256=entry['slot_sha256'], cipher_sha256=entry['cipher']['sha256'],
                plaintext_sha256=entry['cipher']['plaintext_sha256'], cutoff_at=entry['clocks']['cutoff_at']))
    rows.sort(key=lambda row: row['slot_sha256'])
    artifact = verified['cipher_packet']['artifact']
    return dict(schema=SCHEMA, state='CIPHERTEXT_VERIFIED_PENDING_SERVER_PROOF',
        day_jst=manifest['summary']['day_jst'], model=deepcopy(manifest['model']),
        source_archive_commit=manifest['summary']['source_archive_commit'], registry=deepcopy(manifest['registry']),
        manifest_sha256=verified['manifest_sha256'], producer_run_id=str(producer['run_id']),
        producer_code_commit=producer['commit'], producer_job_id=producer['job_id'],
        producer_receipt_artifact_id=producer['artifact_id'],
        producer_receipt_archive_sha256=producer['archive_sha256'],
        producer_cipher_artifact_id=artifact['id'], producer_cipher_archive_sha256=artifact['digest'][7:],
        reader_run_id=reader_run_id, reader_code_commit=reader_code_commit,
        observed_at=observed.isoformat(), registered_races=len(manifest['entries']),
        verified_cipher_files=len(rows), records=rows,
        locally_read_back_before_t15=sum(observed <= origin._time(row['cutoff_at']) - timedelta(minutes=15)
                                        for row in rows),
        independent_server_timing_verified=False, owner_decryption_verified=False,
        source_authenticated=False, official_result_verified=False, production_promoted=False,
        provider_source_requests=0, state_writes=0, new_forecasts=0, training_runs=0,
        confidence='HOLD', formal_three_way_races=0)


def readback(producer_run_id, *, reader_run_id, reader_code_commit, client=None,
             clock=lambda: datetime.now(timezone.utc)):
    _need(_run_id(reader_run_id) != _run_id(producer_run_id), 'DISTINCT_LATER_RUN_REQUIRED')
    with verified_producer(producer_run_id, client=client) as verified:
        observed = origin._time(clock().isoformat())
        return _receipt(verified, reader_run_id, reader_code_commit, observed)


def verify_readback(verified, readback_run_id, *, client=None):
    """Re-fetch the independent receipt; derive T-15 only from GitHub clocks."""
    client = client or GitHubEvidenceClient()
    second = fetch_report(client, readback_run_id)
    first = verified['producer']; report = second['report']
    _need(first['run_id'] != second['run_id'] and first['job_id'] != second['job_id'] and
          first['artifact_id'] != second['artifact_id'] and
          second['started_at'] >= first['completed_at'], 'INDEPENDENT_JOB_REQUIRED')
    if origin._id(first['runner_id']) and origin._id(second['runner_id']):
        _need(first['runner_id'] != second['runner_id'], 'INDEPENDENT_RUNNER_REQUIRED')
    _need(type(report) is dict and type(report.get('observed_at')) is str, 'READER_REPORT_REQUIRED')
    observed = origin._time(report['observed_at'])
    _need(second['started_at'] <= observed <= second['completed_at'] and
          report == _receipt(verified, str(second['run_id']), second['commit'], observed), 'READBACK_BINDING')
    latest = max(first['completed_at'], second['completed_at'])
    eligible, held = [], {}
    for entry in verified['manifest']['entries']:
        if entry['cipher'] is None:
            continue
        slot = entry['slot_sha256']
        if entry['state'] != 'SEALED_PENDING_INDEPENDENT_READBACK':
            held[slot] = 'PRODUCER_ORIGINAL_HELD'
        elif latest > origin._time(entry['clocks']['cutoff_at']) - timedelta(minutes=15):
            held[slot] = 'SERVER_READBACK_AFTER_T15'
        else:
            eligible.append(slot)
    return dict(schema='DT_R1_FUTURE_SERVER_ORIGIN_V1',
        producer_run_id=str(first['run_id']), readback_run_id=str(second['run_id']),
        producer_job_id=first['job_id'], readback_job_id=second['job_id'],
        producer_artifact_id=first['artifact_id'], readback_artifact_id=second['artifact_id'],
        producer_archive_sha256=first['archive_sha256'], readback_archive_sha256=second['archive_sha256'],
        manifest_sha256=verified['manifest_sha256'], latest_server_evidence_at=latest.isoformat(),
        eligible_slots=sorted(eligible), held_slots=held, minimum_margin_seconds=900,
        source_authenticated=False, official_result_verified=False, production_promoted=False)


def _runtime(repo):
    from race_ai import keirin_nationwide_cipher_history as archive
    expected = 'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main'
    _need(os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('GITHUB_REPOSITORY') == archive.REPO and
          os.getenv('GITHUB_REPOSITORY_ID') == archive.REPO_ID and os.getenv('GITHUB_REF') == 'refs/heads/main' and
          os.getenv('GITHUB_EVENT_NAME') == 'workflow_dispatch' and os.getenv('GITHUB_WORKFLOW_REF') == expected and
          os.getenv('GITHUB_JOB') == 'observe-results', 'TRUSTED_MANUAL_RUNTIME_REQUIRED')
    run = _run_id(os.getenv('GITHUB_RUN_ID'))
    commit = os.getenv('GITHUB_SHA', '')
    _need(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'READER_COMMIT_REQUIRED')
    checked = archive._remote(Path(repo).resolve(), synthetic_local=False)
    _need(archive._cmd(checked, 'rev-parse', 'HEAD')[1] == commit, 'CHECKOUT_CODE_CHANGED')
    return run, commit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--producer-run', required=True)
    args = parser.parse_args(argv)
    os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', None)
    try:
        run, commit = _runtime(args.repo)
        report = readback(args.producer_run, reader_run_id=run, reader_code_commit=commit)
    except Exception:
        report = dict(schema=SCHEMA, state='HOLD_CIPHERTEXT_OR_RUNTIME_UNVERIFIED',
            confidence='HOLD', independent_server_timing_verified=False, owner_decryption_verified=False,
            source_authenticated=False, production_promoted=False, provider_source_requests=0, state_writes=0)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['state'] == 'CIPHERTEXT_VERIFIED_PENDING_SERVER_PROOF' else 2


if __name__ == '__main__':
    raise SystemExit(main())
