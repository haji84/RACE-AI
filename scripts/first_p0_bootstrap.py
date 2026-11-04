"""Create or recover the FIRST current-day P0 only after exhaustive same-workflow receipt checks.

This helper does not alter the existing five models, touch old ZIP bytes, or
interpret a missing index as proof that the original is absent. The only
repository write is a create-only metadata index on the existing PR branch.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess

from race_ai.cycle_recovery import day_runs, p0_original_or_empty
from race_ai.frozen_day_cycle import archive_json, need, read_p0, ts
from race_ai.repeated_cycle import matches
from scripts.github_existing_cycle import ROOT, REPO, JST, gh, original

BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
WORKFLOW = 405276784


def index_path(day):
    return ROOT / 'docs' / 'evidence' / day / 'p0-first-receipt.json'


def receipt_index(raw, meta, day):
    doc, rows = read_p0(raw, meta, expected_day=day)
    need(doc.get('race_count', 0) > 0 and len(rows) == doc['model_forecast_count'],
         'FIRST_P0_EMPTY_OR_INCOMPLETE')
    _, body_sha = archive_json(raw, meta, 'forecasts.json',
                               f"boat-p0-existing-{meta['workflow_run']['id']}")
    need(all(r['original_json_sha256'] == body_sha for r in rows), 'P0_BODY_HASH_CONFLICT')
    return dict(schema='RACE_AI_P0_FIRST_RECEIPT_V1', day_jst=day,
                artifact_id=meta['id'], run_id=meta['workflow_run']['id'],
                server_created_at=meta['created_at'], zip_sha256=meta['digest'][7:],
                json_sha256=body_sha, race_count=doc['race_count'],
                model_forecast_count=doc['model_forecast_count'],
                no_regeneration=True, retention_days=7,
                permanent_private_storage_proven=False)


def previous_first_receipt(day, run_id):
    """Enumerate every earlier run in the existing workflow, failing closed."""
    candidates = []
    for run in day_runs(gh, day, current_run=run_id):
        data = json.loads(gh(f"actions/runs/{run['id']}/artifacts?per_page=100"))
        artifacts = data['artifacts']
        need(data.get('total_count', len(artifacts)) == len(artifacts),
             'FIRST_P0_ARTIFACT_PAGINATION_INCOMPLETE')
        for item in artifacts:
            if not matches(item['name'], f"boat-p0-existing-{run['id']}"):
                continue
            meta = json.loads(gh(f"actions/artifacts/{item['id']}"))
            need(meta['id'] == item['id'] and
                 meta['workflow_run']['id'] == run['id'], 'FOREIGN_FIRST_P0_ARTIFACT')
            raw = gh(f"actions/artifacts/{item['id']}/zip")
            # Empty/failed early source attempts are retained, never fabricated.
            doc, rows = p0_original_or_empty(raw, meta, day)
            if rows:
                candidates.append((ts(meta['created_at']), meta['id'], raw, meta))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, _, raw, meta = candidates[0]
    return raw, meta


def _remote_file(path):
    cmd = ['gh', 'api', f'repos/{REPO}/contents/{path}?ref={BRANCH}']
    reply = subprocess.run(cmd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=50)
    if reply.returncode:
        if b'HTTP 404' in reply.stderr:
            return None
        raise RuntimeError('P0_REGISTRY_REMOTE_READ_FAILED: ' +
                           reply.stderr.decode(errors='replace')[:200])
    return json.loads(reply.stdout)


def register(day, raw, meta):
    """Write-once GitHub index, then check the server-returned bytes."""
    need(datetime.now(timezone.utc).astimezone(JST).date().isoformat() == day,
         'DAY_CHANGED_BEFORE_FIRST_P0_INDEX')
    path = index_path(day)
    value = receipt_index(raw, meta, day)
    body = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')) + '\n'
    rel = path.relative_to(ROOT).as_posix()
    existing = _remote_file(rel)
    if existing is not None:
        decoded = base64.b64decode(existing['content'].replace('\n', ''))
        need(decoded == body.encode('utf-8'), 'FIRST_RECEIPT_EXISTS_WITH_OTHER_ORIGINAL')
    else:
        payload = dict(message=f"evidence(boat): register first authenticated P0 for {day}",
                       content=base64.b64encode(body.encode('utf-8')).decode(),
                       branch=BRANCH)
        result = subprocess.run(
            ['gh', 'api', '--method', 'PUT', f'repos/{REPO}/contents/{rel}', '--input', '-'],
            input=json.dumps(payload).encode(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=50)
        need(result.returncode == 0,
             'FIRST_RECEIPT_INDEX_CREATE_REJECTED: ' +
             result.stderr.decode(errors='replace')[:180])
    checked = _remote_file(rel)
    need(checked is not None and
         base64.b64decode(checked['content'].replace('\n', '')) == body.encode('utf-8'),
         'FIRST_RECEIPT_INDEPENDENT_READBACK_MISMATCH')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        need(path.read_bytes() == body.encode(), 'LOCAL_FIRST_RECEIPT_CONFLICT')
    else:
        with path.open('xb') as f:
            f.write(body.encode())
    original(day)
    return value


def output_capture(value):
    target = os.environ.get('GITHUB_OUTPUT')
    if target:
        with open(target, 'a', encoding='utf-8') as f:
            f.write('capture=' + ('true' if value else 'false') + '\n')


def preflight(day, run_id):
    prior = previous_first_receipt(day, run_id)
    path = index_path(day)
    if path.is_file():
        _, rows, meta, _ = original(day)
        need(rows, 'REGISTERED_FIRST_P0_EMPTY')
        if prior is not None:
            _, first_meta = prior
            need(first_meta['id'] == meta['id'], 'INDEX_IS_NOT_EARLIEST_FIRST_P0')
        output_capture(False)
        return 'REGISTERED_P0_REUSED'
    if prior is not None:
        raw, meta = prior
        register(day, raw, meta)
        output_capture(False)
        return 'PREVIOUS_FIRST_P0_RECOVERED'
    output_capture(True)
    return 'NO_SAME_WORKFLOW_FIRST_P0_FOUND_CAPTURE_REQUIRED'


def capture(day, run_id):
    # Cross-check again immediately before the only official GET.
    need(not index_path(day).exists(), 'FIRST_P0_ALREADY_INDEXED')
    need(previous_first_receipt(day, run_id) is None,
         'FIRST_P0_ALREADY_PRESENT_NO_REGENERATION')
    from scripts.existing_day_program import collect
    result = collect()
    need(result.get('day_jst') == day and result.get('source_requests') == 1 and
         result.get('race_count', 0) > 0 and result.get('model_forecast_count', 0) > 0,
         'FIRST_P0_SOURCE_OR_MODEL_BLOCKED: ' +
         str(result.get('failure_class', result.get('state', 'unknown'))) + ': ' +
         str(result.get('reason', ''))[:120])
    folder = ROOT / 'boat_all_day_output'
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    with (folder / 'forecasts.json').open('xb') as f:
        f.write(payload)
    return dict(state='FIRST_P0_CREATED_PENDING_SERVER_RECEIPT',
                races=result['race_count'], models=result['model_forecast_count'],
                json_sha256=hashlib.sha256(payload).hexdigest())


def finalize(day, run_id, artifact_id):
    need(not index_path(day).exists(), 'FIRST_P0_INDEX_ALREADY_EXISTS')
    need(previous_first_receipt(day, run_id) is None,
         'PRIOR_FIRST_P0_FOUND_BEFORE_FINALIZE')
    meta = json.loads(gh(f'actions/artifacts/{artifact_id}'))
    need(meta.get('workflow_run', {}).get('id') == run_id and
         meta.get('name') == f'boat-p0-existing-{run_id}',
         'FIRST_P0_THIS_RUN_ARTIFACT_IDENTITY')
    raw = gh(f'actions/artifacts/{artifact_id}/zip')
    indexed = receipt_index(raw, meta, day)
    local = (ROOT / 'boat_all_day_output' / 'forecasts.json').read_bytes()
    need(hashlib.sha256(local).hexdigest() == indexed['json_sha256'],
         'FIRST_P0_UPLOAD_DOES_NOT_MATCH_LOCAL_SOURCE')
    return register(day, raw, meta)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('preflight', 'capture', 'finalize'))
    p.add_argument('--artifact-id', type=int)
    a = p.parse_args()
    day = datetime.now(timezone.utc).astimezone(JST).date().isoformat()
    run_id = int(os.environ['GITHUB_RUN_ID'])
    if a.command == 'preflight':
        result = preflight(day, run_id)
    elif a.command == 'capture':
        result = capture(day, run_id)
    else:
        need(a.artifact_id is not None and a.artifact_id > 0,
             'FIRST_P0_ARTIFACT_ID_REQUIRED')
        result = finalize(day, run_id, a.artifact_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
