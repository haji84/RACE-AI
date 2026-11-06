"""Original frozen venue observations -> the existing two-family shadow fitter.

No historical backfill, source-rights grant, baseline edits or promotion.
Callers authenticate originals first; analysis does not authorize training.
"""
import hmac,json,re,sqlite3
from pathlib import Path
from .actions_contract import digest
from .boat_observed_pairwise_models import MODEL_IDS,_validate
from .boat_venue_feature_adapter import RIGHTS,FIELDS
from .boat_venue_dataset import INPUT,PREFIX,_seal,_open,_bytes,_sha
from .observed_weight_learning import fit_from_verified,MIN_RACES,ts,seal,verify_training
from scripts.boat_venue_history import _manifest_mac
from scripts.boat_all_racers import _key_ready,_write,_read
from .teiai_history import need

RESULT_RIGHTS='OWNER_PERSONAL_OFFICIAL_RESULT_EVALUATION_20261106'

def _pin(p):
    need(type(p) is dict and p.get('schema')==INPUT and p.get('status')=='READY' and
         p.get('repository_id')=='1416489937' and re.fullmatch('[a-f0-9]{64}',str(p.get('dataset_sha256',''))) and
         re.fullmatch('[a-f0-9]{40}',str(p.get('source_commit',''))) and
         p.get('dataset_path')==PREFIX+'datasets/'+p['dataset_sha256']+'/dataset.json','VENUE_LEARNING_PIN_REQUIRED')
    return 'https://raw.githubusercontent.com/haji84/RACE-AI/'+p['source_commit']+'/'+p['dataset_path']

def fit_venue_rows(rows,observations,*,dataset_pointer,now,allow_training=None):
    """Subset authenticated reader rows, never attach today's profile to them.

    Select the latest observed input before filtering for the pinned dataset.
    The existing fitter still owns outcome validation, train/holdout splitting,
    minimum race count, equations and low-support coefficient preservation.
    """
    url=_pin(dataset_pointer);sha=dataset_pointer['dataset_sha256'];sid='official-venue-grid-'+sha[:16]
    selected={};excluded=[]
    for row in rows:
        snap=row.get('learning_snapshot')
        if snap is None or row['model_id'] not in MODEL_IDS:continue
        _validate(snap);need(digest(snap)==row['learning_snapshot_sha256'],'VENUE_LEARNING_SNAPSHOT_BINDING')
        key=(ts(row['as_of']),row['stage']);old=selected.get(row['race_id'])
        if old is not None and key==(ts(old['as_of']),old['stage']):
            need(row['learning_snapshot_sha256']==old['learning_snapshot_sha256'],'VENUE_LEARNING_SAME_TIME_CONFLICT')
        if old is None or key>(ts(old['as_of']),old['stage']):selected[row['race_id']]=row
    eligible=[];permissions=set()
    for rid,row in sorted(selected.items()):
        snap=row['learning_snapshot'];source=next((s for s in snap['sources'] if s['source_id']==sid),None)
        used=any(f.get('source_id')==sid for p in snap['participants'] for name,f in p['features'].items() if name in FIELDS)
        if source is None or not used:
            excluded.append(dict(race_id=rid,reason='NO_FROZEN_VENUE_FEATURE'));continue
        need(source['source_url']==url and source['source_sha256']==sha and source['source_rights_ref']==RIGHTS,'VENUE_LEARNING_SOURCE_PIN_MISMATCH')
        eligible.append(row);permissions.update((s['source_url'],s['source_rights_ref']) for s in snap['sources'])
    ids={r['race_id'] for r in eligible};obs=[o for o in observations if o['race_id'] in ids]
    permissions.update((o['source_url'],RESULT_RIGHTS) for o in obs)
    unapproved=sum(not callable(allow_training) or allow_training(u,r,'model_training') is not True for u,r in sorted(permissions))
    summary=dict(schema='RACE_AI_VENUE_LEARNING_CONNECTION_COUNTS_V1',dataset_sha256=sha,
        observed_unique_races=len(selected),eligible_venue_races=len(eligible),minimum_fit_races=MIN_RACES,
        unapproved_training_sources=unapproved,excluded_races_count=len(excluded),actual_purchases=False,
        production_promoted=False,new_model_created=False,historical_inputs_backfilled=False,baseline_coefficients_changed=False)
    if not eligible or unapproved:
        summary['state']='HOLD_MODEL_TRAINING_PERMISSION' if unapproved else 'INSUFFICIENT_VERIFIED_RACES'
        return dict(summary=summary,training=None,excluded=excluded)
    training=fit_from_verified(eligible,obs,now=now)
    receipts={r['race_id']:r.get('input_receipt') for r in eligible}
    for lineage in training['source_lineage']:
        if receipts[lineage['race_id']] is not None:lineage['input_receipt']=receipts[lineage['race_id']]
    training.update(venue_dataset_sha256=sha,venue_input_policy='ORIGINAL_FROZEN_INPUT_ONLY_NO_BACKFILL')
    seal(training,'training_sha256');summary.update(state=training['state'],train_races=training['train_races'],
        validation_races=training['validation_races'],fitted_model_count=len(training['models']),training_sha256=training['training_sha256'])
    return dict(summary=summary,training=training,excluded=excluded)


def rows_from_journal(state,root,*,now,_fetch=None):
    """Read immutable originals and recheck their real external GitHub clocks.

    A run ID is a run ID, never an Actions artifact ID. Source receipt metadata
    survives fitting separately from the existing artifact-reader contract.
    """
    from .boat_history_prospective import verify_retained_trials,admit_pair_result
    from .boat_history_comparison import load_pair
    from .github_freeze_receipt import BASE,_github_json
    root=Path(root);before=state.content_sha256()
    need(state.mode=='production','VENUE_LEARNING_PRODUCTION_JOURNAL_REQUIRED')
    verify_retained_trials(state,root,now)
    latest={};cache={};rows=[];observations={}
    def fetch(url):
        if url not in cache:cache[url]=(_fetch or _github_json)(url)
        return cache[url]
    for ident, in state.db.execute("SELECT sha FROM files WHERE name LIKE 'prospective-admissions/%.json'"):
        report=json.loads(state._get(ident));key=report['pair_sha256'];old=latest.get(key)
        if old is None or ts(report['result_captured_at'])>ts(old['result_captured_at']):latest[key]=report
    for key,report in sorted(latest.items()):
        path=root/'pairs'/f'{key}.json';pair=load_pair(path)
        matches=[json.loads(r[0]) for r in state.db.execute('SELECT body FROM results WHERE race_id=?',(pair['race_id'],))]
        obs=max(matches,key=lambda r:ts(r['captured_at']))
        receipt=report['freeze_receipt']
        live=admit_pair_result(path,obs,receipt,now,manifest=report['freeze_receipt_kind']=='PAIR_MANIFEST_V2',_fetch=fetch)
        need(live==report,'VENUE_LEARNING_RETAINED_ADMISSION_CHANGED')
        run=fetch(BASE+'/actions/runs/'+str(receipt['run_id']))
        need(ts(run['created_at'])<=ts(now),'VENUE_LEARNING_FUTURE_RECEIPT')
        observations[pair['race_id']]=obs
        version=pair['history'];snap=version['snapshot'];suite=version['suite']
        proof=dict(receipt,kind=report['freeze_receipt_kind'],head_sha=run['head_sha'],
                   created_at=run['created_at'],pair_sha256=key)
        for mid,model in suite['models'].items():
            if mid not in MODEL_IDS:continue
            rows.append(dict(race_id=pair['race_id'],stage=snap['stage'],model_id=mid,as_of=snap['as_of'],
                cutoff_at=snap['sales_cutoff_at'],server_saved_at=run['created_at'],artifact_id=None,input_receipt=proof,
                roster={str(p['lane']):p['registration_no'] for p in snap['participants']},
                top8=model['ordered_top8'],ranked=[r['combination'] for r in model['candidates']],
                model_sha256=model['prediction_sha256'],learning_snapshot=snap,learning_snapshot_sha256=digest(snap)))
    need(state.content_sha256()==before,'VENUE_LEARNING_ORIGINAL_JOURNAL_CHANGED')
    return rows,list(observations.values())


def seal_candidate(payload,output):
    """Owner-encrypted research candidate; public output contains counts only."""
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED');root=Path(output)
    root.mkdir(parents=True,mode=0o700,exist_ok=True)
    need(not root.is_symlink() and not any(root.iterdir()),'VENUE_LEARNING_OUTPUT_EXISTS_DO_NOT_RESET')
    if payload['training'] is not None:verify_training(payload['training'])
    db=sqlite3.connect(':memory:')
    try:
        db.execute('CREATE TABLE candidate(document BLOB NOT NULL)');raw=_bytes(payload)
        db.execute('INSERT INTO candidate VALUES (?)',(raw,));db.commit()
        part=_seal(db,root/'learning.enc',{})
    finally:db.close()
    manifest=dict(schema='RACE_AI_ENCRYPTED_VENUE_LEARNING_V1',part=part,payload_sha256=_sha(raw))
    _write(root/'learning.json',_bytes(dict(state=manifest,mac=_manifest_mac(manifest))))
    status=dict(payload['summary'],encrypted_readback_verified=read_candidate(root)==payload,plaintext_published=False)
    _write(root/'summary.json',_bytes(status));return status


def read_candidate(root):
    need(_key_ready(),'OWNER_STATE_KEY_REQUIRED');root=Path(root)
    record=json.loads(_read(root/'learning.json',1000000));s=record['state']
    need(record.keys()=={'state','mac'} and hmac.compare_digest(record['mac'],_manifest_mac(s)) and
         s['schema']=='RACE_AI_ENCRYPTED_VENUE_LEARNING_V1' and s['part']['path']=='learning.enc',
         'VENUE_LEARNING_AUTHENTICATION_FAILED')
    db=_open(root,s['part'])
    try:rows=db.execute('SELECT document FROM candidate').fetchall()
    finally:db.close()
    need(len(rows)==1 and _sha(rows[0][0])==s['payload_sha256'],'VENUE_LEARNING_PAYLOAD_HASH_INVALID')
    payload=json.loads(rows[0][0])
    if payload['training'] is not None:verify_training(payload['training'])
    return payload
