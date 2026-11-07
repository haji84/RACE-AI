"""Key-free exact GitHub history-witness check; no dataset or source access."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import race_ai
ROOT=Path(__file__).resolve().parents[1]
race_ai.__path__.extend(str(ROOT/p/'race_ai') for p in ('pr64-reference','pr72-reference'))
from race_ai import boat_venue_future_grid as grid
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts.boat_all_model_cycle import _prospective_grid_get
from scripts.boat_all_racers import _read

PUBLIC_INPUT='audit/state/boat-venue-future-grid-input.json'
SCHEMA='RACE_AI_BOAT_HISTORY_WITNESS_COUNTS_V1'


def _need(ok,reason):
    if not ok:raise ValueError('HISTORY_WITNESS_'+reason)


def _report():
    return dict(schema=SCHEMA,state='HOLD_HISTORY_WITNESS',verified=False,metadata_pass=False,
        actual_log_sha256=None,expected_log_sha256=None,actual_log_bytes=None,reason=None)


def check_witness(manifest,*,gh,now):
    """Use only selected registered API routes; hash log bytes without decoding."""
    report=_report()
    try:
        selected=grid.validate_manifest(manifest)['readback']
        report['expected_log_sha256']=selected['log_sha256']
        routes=(f'actions/runs/{selected["run_id"]}/attempts/1',
            f'actions/runs/{selected["run_id"]}/attempts/1/jobs?per_page=100',
            f'actions/jobs/{selected["job_id"]}/logs')
        _need(callable(gh) and set(routes)<=grid.readback_routes(),'EXACT_READER_ROUTES')
        bodies=[]
        for path,limit in zip(routes,(2*1024*1024,8*1024*1024,2*1024*1024),strict=True):
            raw=gh(path)
            if path==routes[-1] and type(raw) is bytes:report['actual_log_bytes']=len(raw)
            _need(type(raw) is bytes and 0<len(raw)<=limit,'RAW_READ_BOUND')
            bodies.append(raw)
        log=bodies[-1];report['actual_log_sha256']=sha256(log).hexdigest()
        run,jobs=(read_json_bytes(raw) for raw in bodies[:2])
        try:grid.verify_readback(manifest,run,jobs,log,now=now)
        except ValueError as exc:
            # The existing verifier checks the exact metadata projection before
            # log bytes and physical chronology. No alternate hash is admitted.
            report['metadata_pass']=str(exc) in ('PROSPECTIVE_BOAT_GRID_READBACK_LOG_MISMATCH',
                'PROSPECTIVE_BOAT_GRID_READBACK_FROM_FUTURE')
            raise
        report.update(state='HISTORY_WITNESS_VERIFIED',verified=True,metadata_pass=True)
    except Exception as exc:
        code=str(exc);report['reason']=code if re.fullmatch(
            r'(?:HISTORY_WITNESS|PROSPECTIVE_BOAT_GRID)_[A-Z_]{1,100}',code) else 'HISTORY_WITNESS_CHECK_FAILED'
    return report


def _actions_scope():
    _need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI' and
        os.environ.get('GITHUB_REPOSITORY_ID')=='1416489937' and os.environ.get('GITHUB_EVENT_NAME')=='pull_request' and
        os.environ.get('GITHUB_RUN_ATTEMPT')=='1' and os.environ.get('GITHUB_ACTOR')=='haji84' and
        os.environ.get('GITHUB_ACTOR_ID')=='173585154' and os.environ.get('GITHUB_TRIGGERING_ACTOR')=='haji84','OWNER_PR_ATTEMPT_ONE')
    event=read_json_bytes(_read(Path(os.environ.get('GITHUB_EVENT_PATH','')),1024*1024));pr=event.get('pull_request',{})
    _need(event.get('number')==71 and pr.get('user',{}).get('login')=='haji84' and
        pr.get('user',{}).get('id')==173585154 and pr.get('head',{}).get('repo',{}).get('full_name')=='haji84/RACE-AI' and
        pr.get('head',{}).get('ref')=='feat/four-sport-forecast-audit-view-20261022' and
        pr.get('base',{}).get('ref')=='codex/actions-four-sport-e2e','OWNER_SAME_REPOSITORY_PR71')


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        _actions_scope()
        manifest=read_json_bytes(_read(ROOT/PUBLIC_INPUT,65536))
        report=check_witness(manifest,gh=_prospective_grid_get,now=datetime.now(timezone.utc))
    except Exception:
        report=_report();report['reason']='HISTORY_WITNESS_INPUT_OR_SCOPE_REJECTED'
    print(json.dumps(report,sort_keys=True));return 0 if report['verified'] else 1


if __name__=='__main__':raise SystemExit(main())
