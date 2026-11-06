"""Publish encrypted result comparisons using the existing Actions writer only."""
import argparse
import base64
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import race_ai
race_ai.__path__.append(str(ROOT/'pr64-reference/race_ai'))
from race_ai import saved_view_feed as F
from race_ai.boat_pdca_state import need,sha
from race_ai.boat_pdca_recipient import _json
from race_ai.boat_history_store import wire
from race_ai.saved_pages import _read
from race_ai.cycle_recovery import result_archive,_result_day

def gh(path):
    p=subprocess.run(['gh','api','repos/haji84/RACE-AI/'+path],capture_output=True,timeout=90)
    need(p.returncode==0,'FEED_GITHUB_READ_FAILED');need(len(p.stdout)<=32*1024*1024,'FEED_ARCHIVE_BOUND');return p.stdout

def observations(ident,*,day,expected_sha=None,allow_other_day=False):
    need(type(ident) is int and ident>0,'FEED_ARTIFACT_ID')
    meta=_json(gh(f'actions/artifacts/{ident}'),32768)
    run=meta.get('workflow_run',{});need(run.get('repository_id')==1416489937 and run.get('head_repository_id')==1416489937,'FEED_ARTIFACT_REPOSITORY')
    info=_json(gh(f'actions/runs/{run["id"]}'),128*1024)
    need(info.get('workflow_id')==405276784 and info.get('head_branch')=='feat/four-sport-forecast-audit-view-20261022'
         and info.get('head_sha')==run.get('head_sha'),'FEED_ARTIFACT_WORKFLOW')
    raw=gh(f'actions/artifacts/{ident}/zip')
    if expected_sha is not None:need(sha(raw)==expected_sha,'FEED_CATCHUP_HASH')
    if allow_other_day and _result_day(raw,meta)!=day:return []
    return result_archive(raw,meta,day)

def git_auth():
    token=os.environ.get('GH_TOKEN');need(token and '\n' not in token and '\r' not in token,'FEED_GITHUB_TOKEN_REQUIRED')
    # One process-scoped, repository-specific credential; never saved to Git.
    count=int(os.environ.get('GIT_CONFIG_COUNT','0'));need(0<=count<=32,'FEED_GIT_CONFIG_BOUND')
    os.environ.update({f'GIT_CONFIG_KEY_{count}':'http.https://github.com/haji84/RACE-AI.extraheader',
                       f'GIT_CONFIG_VALUE_{count}':'AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode(),
                       'GIT_CONFIG_COUNT':str(count+1)})

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seed-only',action='store_true');p.add_argument('--result-artifact',type=int)
    a=p.parse_args(argv)
    try:
        config=_json(_read(ROOT/'audit/state/boat-saved-view-input.json',8192),8192)
        need(set(config)=={'schema','bootstrap','bootstrap_sha256','catchup_artifact_id','catchup_sha256'}
             and config['schema']=='RACE_AI_SAVED_VIEW_INPUT_V1','FEED_INPUT_INVALID')
        raw=base64.b64decode(config['bootstrap'],validate=True);need(sha(raw)==config['bootstrap_sha256'],'FEED_BOOTSTRAP_HASH')
        bootstrap=F.open_bootstrap(raw);git_auth();git=F.FeedRepository(ROOT)
        parent,previous,generation,view=F.current_view(git,bootstrap)
        if a.seed_only:
            if parent:print(wire(dict(status='ENCRYPTED_VIEW_ALREADY_INITIALIZED',generation=generation)));return 0
        else:
            days={r['event_date_jst'] for r in view['records']};need(len(days)==1,'FEED_SINGLE_SAVED_DAY_REQUIRED');day=days.pop()
            missing={r['race_id'] for r in view['records'] if not r['result'] or r['result']['status'] in ('pending','unsupported')}
            if not a.result_artifact and not missing:
                print(wire(dict(status='SAVED_RESULTS_ALREADY_COMPLETE',generation=generation)));return 0
            ident=a.result_artifact or config['catchup_artifact_id']
            items=observations(ident,day=day,expected_sha=None if a.result_artifact else config['catchup_sha256'],allow_other_day=bool(a.result_artifact))
            if not a.result_artifact:
                # Initial catch-up fills gaps. Settled seed observations and their
                # raw-backed references remain intact; later same-day rounds
                # handle revisions using retained raw captures.
                items=[o for o in items if o['race_id'] in missing]
            capture_dir=Path(os.environ['RUNNER_TEMP'])/'boat-saved-view-captures'
            from datetime import date
            from race_ai.official_race_updates import endpoint
            urls={endpoint(date.fromisoformat(r['event_date_jst']),r['race_id'][9:11],int(r['race_id'][-2:]),'raceresult') for r in view['records']}
            captures=[c for c in F.load_captures(capture_dir) if c[1]['source_url'] in urls]
            if not items and not captures:
                print(wire(dict(status='SAVED_DAY_UNCHANGED',generation=generation)));return 0
            view=F.update_view(view,items,captures=captures,synced_at=datetime.now(timezone.utc).isoformat())
        report=F.publish_view(git,bootstrap,view,parent=parent,previous=previous,generation=generation)
        print(wire(report));return 0
    except Exception as e:
        reason=str(e) if isinstance(e,ValueError) and re.fullmatch('FEED_[A-Z0-9_]{1,90}',str(e)) else 'FEED_OPERATION_FAILED'
        print(wire(dict(status='ENCRYPTED_VIEW_REJECTED',reason=reason)));return 2

if __name__=='__main__':raise SystemExit(main())
