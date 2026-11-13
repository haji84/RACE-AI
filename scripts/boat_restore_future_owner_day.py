"""Source-free daily projection of independently attested frozen owner P0/P1.

Uses the immutable original release, same GitHub AES state, and signed physical
artifacts from the completed producing workflow. Never requests the racing
provider or regenerates a pre-cutoff prediction after the deadline.
"""
import base64
from collections import Counter
from datetime import date,datetime,timezone,timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SOURCE_SHA='0da3f00b0f5c5115f956658d306ddcb9833ec7af'
PROOF_SCHEMA='BOAT_OWNER_AUTOMATIC_SIGNED_DAY_RECONCILIATION_V1'


def require(valid, code):
    if not valid:
        raise ValueError('BOAT_NEW_DAY_'+code)


def coverage(view, day):
    require(type(view) is dict and type(view.get('records')) is list,
            'VIEW_SHAPE')
    wanted=[r for r in view['records']
            if r.get('sport')=='boat' and r.get('event_date_jst')==day]
    require(len(wanted)==len({r['race_id'] for r in wanted}),
            'RACE_DUPLICATE')
    stage=Counter()
    race_ids={'P0':set(),'P1':set()}
    verified_prior={'P0':0,'P1':0}
    for row in wanted:
        predictions=[row.get('prediction'),*(row.get('comparison_predictions') or [])]
        for p in predictions:
            if type(p) is not dict or p.get('stage') not in race_ids:
                continue
            st=p['stage']
            stage[st]+=1
            race_ids[st].add(row['race_id'])
            if p.get('eligible_pre_cutoff') is True:
                verified_prior[st]+=1
    return dict(races=len(wanted),forecasts=dict(stage),
                stage_races={k:len(v) for k,v in race_ids.items()},
                eligible_pre_cutoff_counts=verified_prior)


def _run():
    require(os.environ.get('GITHUB_EVENT_NAME')=='workflow_run',
            'PRODUCER_EVENT_REQUIRED')
    raw_run=os.environ.get('RACE_AI_OWNER_RUN_ID','')
    require(re.fullmatch(r'[1-9][0-9]{7,18}',raw_run) is not None,
            'RUN_ID_REQUIRED')
    run=int(raw_run)
    raw_time=os.environ.get('RACE_AI_OWNER_RUN_CREATED_AT','')
    require(type(raw_time) is str and len(raw_time)<=50 and raw_time.endswith('Z'),
            'OWNER_RUN_CLOCK_REQUIRED')
    try:
        moment=datetime.fromisoformat(raw_time.replace('Z','+00:00'))
    except ValueError:
        raise ValueError('BOAT_NEW_DAY_RUN_CLOCK_INVALID') from None
    now=datetime.now(timezone.utc)
    require(moment.utcoffset() is not None and
            timedelta(0)<=now-moment<=timedelta(days=45),
            'OWNER_RUN_AGE_REJECTED')
    day=(moment+timedelta(hours=9)).date().isoformat()
    root=Path.cwd().resolve()
    require((root/'race_ai/saved_view_feed.py').is_file(), 'OWNER_SOURCE_MISSING')
    release=subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=root,timeout=12).decode().strip()
    require(release==SOURCE_SHA, 'OWNER_RELEASE_SHA_CHANGED')
    sys.path.insert(0,str(root))
    import race_ai
    for directory in ('pr64-reference','pr72-reference'):
        dep=root/directory/'race_ai'
        require(dep.is_dir(), 'ORIGINAL_PARSER_MISSING')
        race_ai.__path__.append(str(dep.resolve()))
    from scripts.boat_private_original_vault import _environment
    from scripts.boat_saved_view_feed import git_auth,intake_saved_models
    from scripts.boat_original_maintenance import protect_new_forecast_originals
    from race_ai import saved_view_feed as F
    from race_ai.boat_pdca_state import sha
    from race_ai.boat_pdca_recipient import _json
    _environment(root)
    require(date.fromisoformat(day).isoformat()==day,'DAY_INVALID')
    raw_config=(root/'audit/state/boat-saved-view-input.json').read_bytes()
    require(0<len(raw_config)<=8192,'BOOTSTRAP_BOUND')
    configuration=_json(raw_config,8192)
    require(type(configuration) is dict and
            set(configuration)=={'schema','bootstrap','bootstrap_sha256',
                                'catchup_artifact_id','catchup_sha256'} and
            configuration['schema']=='RACE_AI_SAVED_VIEW_INPUT_V1',
            'BOOTSTRAP_INVALID')
    bootstrap_raw=base64.b64decode(configuration['bootstrap'],validate=True)
    require(sha(bootstrap_raw)==configuration['bootstrap_sha256'],
            'BOOTSTRAP_SHA_MISMATCH')
    git_auth()
    bootstrap=F.open_bootstrap(bootstrap_raw)
    git=F.FeedRepository(root)
    parent,original_cipher,generation,previous=F.current_view(git,bootstrap)
    require(type(parent) is str and re.fullmatch('[a-f0-9]{40}',parent) and
            type(original_cipher) is str and re.fullmatch('[a-f0-9]{64}',original_cipher) and
            type(generation) is int and generation>=1,'AES_PARENT_UNVERIFIED')
    require(getattr(git,'_saved_history_context',None) is not None,
            'V5_HISTORY_REQUIRED')
    try:
        current_parent,current_cipher,current_gen,previous=F.current_view(
            git,bootstrap,day=day)
    except ValueError as exc:
        require(str(exc)=='HISTORY_DAY_UNAVAILABLE',
                'EXISTING_DATE_INTEGRITY_REJECTED')
        current_parent,current_cipher,current_gen,previous=F.current_view(
            git,bootstrap)
    require((current_parent,current_cipher,current_gen)==(
        parent,original_cipher,generation),'PARENT_CHANGED_BEFORE_INTAKE')
    original_anchor=F.forecast_anchor(previous)
    original_inventory=F.forecast_inventory(previous)
    from_view=intake_saved_models(previous,hydrate=True,day=day,
                                  recover_runs=[run])
    require(F.forecast_anchor(from_view)==original_anchor,
            'SOURCE_BASE_ANCHOR_CHANGED')
    candidate_inventory=F.ensure_append_only(previous,from_view)
    require(all(candidate_inventory.get(k)==v
                for k,v in original_inventory.items()),
            'OLDER_FORECAST_MUTATED')
    counts=coverage(from_view,day)
    if not counts['races'] or not sum(counts['forecasts'].values()):
        print(json.dumps(dict(schema=PROOF_SCHEMA,
            status='HOLD_NO_SIGNED_FORECASTS_FOR_OWNER_DAY',
            day=day,run_id=run,source_provider_gets=0,
            original_forecasts_overwritten=False),sort_keys=True))
        return 0
    # Before publishing, verify every newly referenced physical GitHub ZIP
    # already exists in owner-only permanent vault or retain its exact bytes.
    originals=protect_new_forecast_originals(previous,from_view,root)
    require(originals.get('complete') is True,
            'NEW_FORECAST_VAULT_READBACK_UNVERIFIED')
    require(git.head()==parent,'CONCURRENT_AES_HEAD_CHANGED')
    if from_view==previous:
        new_parent,new_cipher,new_gen,read=parent,original_cipher,generation,previous
    else:
        report=F.publish_view(git,bootstrap,from_view,parent=parent,
            previous=original_cipher,generation=generation)
        require(report.get('status')=='ENCRYPTED_HISTORY_VIEW_PUBLISHED',
                'V5_PUBLICATION_REQUIRED')
        new_cipher=report['cipher_sha256']
        new_parent,cipher,new_gen,read=F.current_view(git,bootstrap,day=day)
        require(new_parent==report['commit'] and cipher==new_cipher and
                new_gen==generation+1,'NEW_DAY_INDEPENDENT_ROUTER_MISMATCH')
    require(F.forecast_anchor(read)==original_anchor,
            'ORIGINAL_FORECAST_ANCHOR_CHANGED')
    # The final receiver performs its own independent fresh-runner readback.
    read_counts=coverage(read,day)
    require(read_counts==counts,'NEW_DAY_READBACK_COUNTS_MISMATCH')
    require(F.forecast_inventory(read)==F.forecast_inventory(
        dict(from_view,records=[r for r in from_view['records']
            if r.get('event_date_jst')==day])),'NEW_DAY_READBACK_INVENTORY_MISMATCH')
    output=dict(schema=PROOF_SCHEMA,status='ENCRYPTED_OWNER_DAY_P0_P1_RECONCILED',
                day=day,run_id=run,old_generation=generation,
                new_generation=new_gen,new_cipher_sha256=new_cipher,
                restored_races=counts['races'],
                saved_stage_forecasts=counts['forecasts'],
                covered_stage_races=counts['stage_races'],
                eligible_pre_cutoff_forecasts=counts['eligible_pre_cutoff_counts'],
                source_provider_gets=0,new_predictions_generated=0,
                original_forecasts_overwritten=False,
                original_artifact_vault_verified=True,
                new_day_router_readback_verified=True,
                nationwide_program_complete_proven=False,
                p1_all_races_complete_proven=False)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            stream.write('cipher='+new_cipher+'\n')
    print(json.dumps(output,sort_keys=True))
    return 0


def main():
    try:
        return _run()
    except Exception as exc:
        value=getattr(exc,'reason_code',None) or str(exc)
        reason=value if (type(value) is str and
            re.fullmatch('[A-Z0-9_]{3,110}',value)) else 'OWNER_ORIGINAL_RESTORE_INTEGRITY_HOLD'
        print(json.dumps(dict(status='BOAT_NEW_DAY_RESTORE_HOLD',
              reason=reason,source_provider_gets=0,
              no_generated_forecasts=True),sort_keys=True))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
