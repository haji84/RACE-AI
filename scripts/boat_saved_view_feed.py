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
from race_ai.boat_saved_view_intake import append_views,project_native_state
from race_ai.saved_pages import MAX_VIEW

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
    actual=_result_day(raw,meta)
    days={day} if type(day) is str else set(day)
    if allow_other_day and actual not in days:return []
    need(actual in days,'FEED_RESULT_DAY_REQUIRED')
    return result_archive(raw,meta,actual)

def intake_saved_models(view):
    """Use authenticated private runtime/readback; never request official pages."""
    additions=[];names=None
    config=ROOT/'audit/state/boat-model-runtime-input.json'
    if config.exists():
        from scripts.boat_all_model_cycle import prepare_runtime
        runtime=prepare_runtime(round_no=0);files=runtime['runtime_files']
        if files.get('native-view.json'):
            additions.append(_json(_read(Path(files['native-view.json']),MAX_VIEW),MAX_VIEW))
        # Registry names are explicitly bound to a verified source and ID.
        if files.get('racers.sqlite'):
            import sqlite3
            registry={};db=sqlite3.connect(Path(files['racers.sqlite']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
            try:
                for ident,url,captured,source,raw in db.execute('SELECT id,url,captured_at,sha,raw FROM sources'):
                    need(sha(raw)==source,'FEED_RACER_SOURCE_HASH')
                    for pid,body in db.execute('SELECT racer_id,document FROM racers WHERE source_id=?',(ident,)):
                        document=_json(body.encode(),128*1024)
                        need(document.get('racer_id')==pid,'FEED_RACER_NAME_BINDING')
                        registry[pid]=dict(name=document['name'],verified=True,source_url=url,source_sha256=source,captured_at=captured)
            finally:db.close()
            names=dict(registry=registry,races={})
    continuity=ROOT/'cycle_recovery_output/continuity.json'
    if continuity.is_file():
        state=_json(_read(continuity,32*1024*1024),32*1024*1024)
        additions.append(project_native_state(state))
    reference=Path(os.environ['RUNNER_TEMP'])/'boat-all-model-readback.json'
    if reference.is_file():
        from race_ai.boat_all_model_store import restore_forecasts
        from race_ai.boat_all_model_cycle import project_round
        record=_json(_read(reference,64*1024),64*1024)
        need(str(record.get('run_id'))==os.environ.get('GITHUB_RUN_ID'),'FEED_MODEL_READBACK_RUN')
        payload=restore_forecasts(record['pointer'],ROOT)
        projected=project_round(payload,record['receipt'])
        additions.append(projected)
    return append_views(view,additions,names=names) if additions or names else view

def git_auth():
    token=os.environ.get('GH_TOKEN');need(token and '\n' not in token and '\r' not in token,'FEED_GITHUB_TOKEN_REQUIRED')
    # One process-scoped, repository-specific credential; never saved to Git.
    count=int(os.environ.get('GIT_CONFIG_COUNT','0'));need(0<=count<=32,'FEED_GIT_CONFIG_BOUND')
    name='http.https://github.com/haji84/RACE-AI.extraheader'
    value='AUTHORIZATION: basic '+base64.b64encode(('x-access-token:'+token).encode()).decode()
    existing=[os.environ.get(f'GIT_CONFIG_VALUE_{i}') for i in range(count)
              if os.environ.get(f'GIT_CONFIG_KEY_{i}')==name]
    need(not existing or len(existing)==1 and existing[0]==value,'FEED_GIT_CREDENTIAL_SCOPE_CONFLICT')
    if existing:return
    os.environ.update({f'GIT_CONFIG_KEY_{count}':name,
                       f'GIT_CONFIG_VALUE_{count}':value,
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
            previous_view=view;view=intake_saved_models(view)
            changed=wire(view)!=wire(previous_view)
            days={r['event_date_jst'] for r in view['records']}
            missing={r['race_id'] for r in view['records'] if not r['result'] or r['result']['status'] in ('pending','unsupported')}
            if not a.result_artifact and not missing and not changed:
                print(wire(dict(status='SAVED_RESULTS_ALREADY_COMPLETE',generation=generation)));return 0
            ident=a.result_artifact or config['catchup_artifact_id']
            items=observations(ident,day=days,expected_sha=None if a.result_artifact else config['catchup_sha256'],allow_other_day=True)
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
            if not items and not captures and not changed:
                print(wire(dict(status='SAVED_DAY_UNCHANGED',generation=generation)));return 0
            view=F.update_view(view,items,captures=captures,synced_at=datetime.now(timezone.utc).isoformat())
        report=F.publish_view(git,bootstrap,view,parent=parent,previous=previous,generation=generation)
        print(wire(report));return 0
    except Exception as e:
        reason=str(e) if isinstance(e,ValueError) and re.fullmatch('(?:FEED|MODEL_RUNTIME|ALL_MODEL_CLI|BOAT_ALL_MODEL_CYCLE|STATE|GITHUB)_[A-Z0-9_]{1,90}',str(e)) else 'FEED_OPERATION_FAILED'
        import traceback
        frames=traceback.extract_tb(e.__traceback__)
        location=Path(frames[-1].filename).name+':'+str(frames[-1].lineno) if frames else None
        print(wire(dict(status='ENCRYPTED_VIEW_REJECTED',reason=reason,failure_class=type(e).__name__,failure_at=location)));return 2

if __name__=='__main__':raise SystemExit(main())
