"""Automatically fit parameter versions of the TWO EXISTING observed families.

Keeps their exact observed contrast features and PL outcome equations. Does not
change the five frozen baselines, invent missing observations, grant source
rights, place wagers, or auto-promote a challenger. Historical holdout scores
are NOT prospective scores; future shadows need independent server receipts.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib, io, json, math, zipfile

from .actions_contract import digest
from .boat_observed_pairwise_models import (
    MODEL_IDS, WEIGHTS, FEATURE_RANGES, ROOT_FIELDS, SCHEMA, _validate, _contrasts,
)
from .four_sport_learning import _gradient, _all_triples
from .boat_private_original_archive import open_original_zip

SCHEMA_TRAIN = 'RACE_AI_EXISTING_OBSERVED_WEIGHT_FIT_V1'
SCHEMA_SHADOW = 'RACE_AI_EXISTING_OBSERVED_LEARNED_SHADOW_V1'
MIN_RACES = 8
EPOCHS = 80
LR = .05
L2 = .10
FEATURES = tuple(FEATURE_RANGES)


def need(condition, reason):
    if not condition: raise ValueError(reason)


def ts(value):
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(d.utcoffset() is not None, 'aware learning timestamp required')
    return d


def seal(value, field):
    value[field] = digest({k:v for k,v in value.items() if k != field})
    return value


def check(value, field):
    need(value.get(field) == digest({k:v for k,v in value.items() if k != field}),
         'learning integrity mismatch: ' + field)


def source_snapshot(suite):
    """Recover exact bound input, not post-result guessed features."""
    snap = {k:deepcopy(suite[k]) for k in ROOT_FIELDS if k not in ('schema','sources','participants')}
    snap.update(schema=SCHEMA, sources=deepcopy(suite['source_evidence']),
                participants=deepcopy(suite['observations']))
    need(digest(snap) == suite['snapshot_sha256'], 'learning snapshot binding mismatch')
    _validate(snap)
    return snap


def vectors(snapshot):
    """Same active-entrant contrast divisor as the fixed model; no imputation."""
    _validate(snapshot)
    values, _, _ = _contrasts(snapshot)
    lanes=sorted(row['lane'] for row in snapshot['participants'])
    return {i:[float(sum((v[i]-v[j] for j in lanes if j != i and i in v and j in v), 0)/len(lanes))
               for name in FEATURES for v in (values[name],)] for i in lanes}


def _metrics(records, weights):
    hits=0; loss=0.; received=0;stake=0
    for row in records:
        ranking=_all_triples(row['vectors'], weights)
        stake+=len(ranking[:8])*100
        hit=row['winner'] in [x['combination'] for x in ranking[:8]]
        hits+=hit; received+=row['payout'] if hit else 0
        loss+=_gradient(row['vectors'],row['winner'],weights)[1]
    n=len(records)
    return dict(races=n, hits=hits, hit_at_8=hits/n if n else None,
                mean_log_loss=loss/n if n else None, stake_yen=stake,
                received_yen=received, roi=received/stake if stake else None,
                prospective=False)


def fit_from_verified(rows, observations, *, now, video_contexts=None, video_receipt_verifier=None):
    """Caller supplies already authenticated read_p0/read_p1 rows and results.

    Select one input per race (latest pre-cutoff observed snapshot, P1 before
    P0); never multiply one outcome by the number of models. Missing-feature
    coefficients remain unchanged until enough TRAIN rows actually observe them.
    """
    if video_contexts is not None:
        from .boat_video_learning import fit_with_video
        return fit_with_video(rows, observations, video_contexts, now=now,
                              receipt_verifier=video_receipt_verifier)
    from .frozen_day_cycle import settle, official_id, check_clock
    need(now.utcoffset() is not None, 'aware fit time required')
    by_result={o['race_id']:o for o in observations}
    need(len(by_result)==len(observations), 'duplicate training result')
    selected={}; excluded=[]
    for row in rows:
        snap=row.get('learning_snapshot')
        if snap is None or row['model_id'] not in MODEL_IDS: continue
        _validate(snap)
        need(snap['scope']=='OPERATOR_SUPPLIED_RESEARCH','synthetic input cannot fit a live candidate')
        need(digest(snap)==row['learning_snapshot_sha256'] and official_id(snap['race_id'])==row['race_id']
             and snap['stage']==row['stage'] and ts(snap['as_of'])==ts(row['as_of'])
             and ts(snap['sales_cutoff_at'])==ts(row['cutoff_at']), 'learning row/snapshot binding')
        check_clock(row['as_of'],row['cutoff_at'],row['server_saved_at'])
        need(ts(row['server_saved_at'])<=now, 'future input receipt cannot train')
        rid=row['race_id']; old=selected.get(rid)
        if old is None or (ts(row['as_of']),row['stage'])>(ts(old['as_of']),old['stage']):
            selected[rid]=row
        elif row['stage']==old['stage'] and row['as_of']==old['as_of']:
            need(row['learning_snapshot_sha256']==old['learning_snapshot_sha256'], 'same-time training inputs conflict')
    records=[]
    for rid,row in sorted(selected.items()):
        result=by_result.get(rid)
        if result is None: continue
        if ts(result['captured_at'])>now:
            excluded.append(dict(race_id=rid,reason='RESULT_NOT_YET_AVAILABLE'));continue
        try: verdict=settle(row,result)
        except (ValueError,TypeError,KeyError) as exc:
            excluded.append(dict(race_id=rid,reason='RESULT_REJECTED: '+str(exc)[:120]));continue
        if verdict['state'] not in ('HIT','MISS'):
            excluded.append(dict(race_id=rid,reason=verdict['state']));continue
        records.append(dict(race_id=rid,phase=row['stage'],cutoff_at=row['cutoff_at'],
            snapshot_sha256=row['learning_snapshot_sha256'],forecast_sha256=row['model_sha256'],
            input_artifact_id=row['artifact_id'],input_saved_at=row['server_saved_at'],
            result_sha256=result['source_sha256'],result_captured_at=result['captured_at'],
            winner=verdict['winning_combination'],payout=verdict['payout_per_100_yen'],
            vectors=vectors(row['learning_snapshot'])))
    # Split on outcome availability. This is retrospective holdout, never a
    # claim that the fitted artifact already existed at those historical races.
    records.sort(key=lambda r:(ts(r['result_captured_at']),r['race_id']))
    public_rows=[{k:v for k,v in row.items() if k not in ('vectors','winner','payout')} for row in records]
    out=dict(schema=SCHEMA_TRAIN,created_at=now.isoformat(),state='INSUFFICIENT_VERIFIED_RACES',
        feature_schema=list(FEATURES),source_family_ids=list(MODEL_IDS),unique_races=len(records),
        observed_phase_counts=dict(Counter(r['phase'] for r in records)),minimum_fit_races=MIN_RACES,
        source_lineage=public_rows,training_data_sha256=digest(records),excluded_races=excluded,
        train_races=0,validation_races=0,models={},auto_promoted=False,
        accuracy_improvement_proven=False,validation_type='RETROSPECTIVE_AVAILABILITY_ORDERED_HOLDOUT',
        target_scope='OPERATOR_SUPPLIED_RESEARCH',
        training_policy=dict(epochs=EPOCHS,learning_rate=LR,l2_to_existing_weights=L2,
                             weight_min=0.,weight_max=4.,minimum_observed_train_races=4),
        limitations=['Small sample; prospective paired comparison required.',
                     'One outcome per race; P0/P1 feature availability is explicitly recorded.',
                     'Unobserved or poorly supported features retain their original coefficient.',
                     'No trained candidate is automatically adopted as the production model.'])
    if len(records)<MIN_RACES:return seal(out,'training_sha256')
    nv=max(2,len(records)//4); train,holdout=records[:-nv],records[-nv:]
    # Keep simultaneous result observations entirely on one side of the split.
    boundary=ts(holdout[0]['result_captured_at'])
    while train and ts(train[-1]['result_captured_at'])==boundary:
        holdout.insert(0,train.pop())
    if len(train)<6:return seal(out,'training_sha256')
    supports=[sum(any(abs(vector[j])>0 for vector in row['vectors'].values()) for row in train)
              for j in range(len(FEATURES))]
    out.update(state='FITTED_SHADOW_ONLY',train_races=len(train),validation_races=len(holdout),
        train_race_ids=[r['race_id'] for r in train],validation_race_ids=[r['race_id'] for r in holdout],
        data_available_until=max((r['result_captured_at'] for r in records),key=ts),
        feature_support_train=dict(zip(FEATURES,supports)))
    for mid in MODEL_IDS:
        base=list(WEIGHTS[mid]); weights=base[:]
        for _ in range(EPOCHS):
            gradients=[_gradient(r['vectors'],r['winner'],weights)[0] for r in train]
            weights=[min(4.,max(0.,w+LR*(sum(g[j] for g in gradients)/(3*len(train))-L2*(w-base[j]))))
                     if supports[j]>=4 else base[j] for j,w in enumerate(weights)]
        active=any(len(row['vectors'])!=6 for row in records)
        out['models'][mid]=dict(model_id=mid,model_version=(
            '0.2.0-FITTED-SHADOW-ACTIVE-ROSTER' if active else '0.2.0-FITTED-SHADOW'),
            weights=weights,base_weights=base,coefficients_changed=weights!=base,
            training=_metrics(train,weights),holdout=_metrics(holdout,weights),
            holdout_baseline=_metrics(holdout,base),calibrated=False,
            performance_claim='NOT_A_PROSPECTIVE_ACCURACY_RESULT')
    return seal(out,'training_sha256')


def verify_training(training):
    if training.get('schema') == 'RACE_AI_ALL_EXISTING_MODEL_FIT_V1':
        from .all_existing_model_learning import verify_training as verify_all_training
        return verify_all_training(training)
    if training.get('schema') == 'RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1':
        from .boat_video_learning import verify_video_training
        return verify_video_training(training)
    check(training,'training_sha256')
    need(training['schema']==SCHEMA_TRAIN and training['feature_schema']==list(FEATURES)
         and training['auto_promoted'] is False and training['accuracy_improvement_proven'] is False,
         'training schema or promotion claim')
    need(set(training['models']).issubset(MODEL_IDS), 'foreign trained family')
    if training['state']=='FITTED_SHADOW_ONLY':
        need(set(training['models'])==set(MODEL_IDS) and training['train_races']>=6,
             'incomplete fitted family')
        need(not set(training['train_race_ids']) & set(training['validation_race_ids']), 'train/holdout overlap')
        for mid,m in training['models'].items():
            need(m['base_weights']==list(WEIGHTS[mid]) and len(m['weights'])==len(FEATURES)
                 and all(type(w) in (int,float) and math.isfinite(w) and 0<=w<=4 for w in m['weights']),
                 'invalid fitted parameters')


def make_shadows(snapshot, baseline_suite, context, *, video_context=None, video_receipt_verifier=None):
    """Use only an externally frozen training artifact, never today's result."""
    if context is None:return []
    if context['training'].get('schema') == 'RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1':
        from .boat_video_learning import make_video_shadows
        return make_video_shadows(snapshot, baseline_suite, context, video_context,
                                  receipt_verifier=video_receipt_verifier)
    training=context['training']; receipt=context['receipt'];verify_training(training)
    if training['state']!='FITTED_SHADOW_ONLY':return []
    _validate(snapshot);check(baseline_suite,'suite_sha256')
    need(snapshot['scope']==training['target_scope'], 'training/inference scope mismatch')
    need(baseline_suite['snapshot_sha256']==digest(snapshot), 'candidate/baseline input mismatch')
    need(receipt.get('expired') is False and receipt['workflow_run']['head_repository_id']==1416489937
         and isinstance(receipt.get('digest'),str) and receipt['digest'].startswith('sha256:'), 'training receipt identity')
    created,saved,asof=ts(training['created_at']),ts(receipt['created_at']),ts(snapshot['as_of'])
    need(created<=saved+timedelta_one_second() and saved<asof and created<asof
         and ts(training['data_available_until'])<=created, 'candidate training/receipt must precede input')
    from .frozen_day_cycle import official_id
    rid=official_id(snapshot['race_id'])
    need(rid not in {r['race_id'] for r in training['source_lineage']}, 'target result leaked into training')
    x=vectors(snapshot);out=[]
    for mid in MODEL_IDS:
        model=training['models'][mid]; ranked=_all_triples(x,model['weights'])
        version=model['model_version']
        if len(x)!=6 and not version.endswith('-ACTIVE-ROSTER'):
            version+='-ACTIVE-ROSTER'
        record=dict(schema=SCHEMA_SHADOW,variant='LEARNED_SHADOW',model_id=mid,model_version=version,
            race_id=rid,stage=snapshot['stage'],as_of=snapshot['as_of'],cutoff_at=snapshot['sales_cutoff_at'],
            input_sha256=digest(snapshot),training_sha256=training['training_sha256'],
            training=deepcopy(training),training_receipt=deepcopy(receipt),
            baseline_model_sha256=baseline_suite['models'][mid]['prediction_sha256'],
            candidates=ranked,ordered_top8=[v['combination'] for v in ranked[:8]],
            candidate_count=len(ranked),calibrated=False,auto_promoted=False,actual_purchases=False)
        out.append(seal(record,'prediction_sha256'))
    return out


def timedelta_one_second():
    from datetime import timedelta
    return timedelta(seconds=1)


def read_shadow_rows(doc, receipt, baseline_rows, *, video_receipt_verifier=None):
    """Verify embedded parameters after the caller authenticates the P1 archive.

    A saved video version additionally requires a caller-supplied independent
    receipt reader. Embedded JSON proofs cannot authenticate video evidence.
    """
    from .frozen_day_cycle import check_clock, rank_check
    by_key={(r['race_id'],r['stage'],r['model_id']):r for r in baseline_rows}
    bundles={b['race_id']:b for b in doc.get('observed_pairwise_p1_bundles',[]) if 'suite' in b}
    out=[];seen=set()
    for p in doc.get('learned_pairwise_shadows',[]):
        video=p.get('schema') == 'RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1'
        check(p,'prediction_sha256');need((p['schema']==SCHEMA_SHADOW or video) and not p['auto_promoted'],'candidate schema')
        key=(p['race_id'],p['stage'],p['model_id']);need(key not in seen and key in by_key,'duplicate/foreign candidate');seen.add(key)
        base=by_key[key];bundle=bundles[p['race_id']]
        context=dict(training=p['training'],receipt=p['training_receipt'])
        if video:
            need(callable(video_receipt_verifier), 'saved video shadow requires independent receipt verifier')
            need(base['roster']=={str(r['lane']):r['registration_no'] for r in bundle['snapshot']['participants']},
                 'video shadow/baseline roster mismatch')
            envelope=dict(video_context=p['video_context'],receipt=p['video_receipt'])
            recreated={q['model_id']:q for q in make_shadows(bundle['snapshot'],bundle['suite'],context,
                video_context=envelope,video_receipt_verifier=video_receipt_verifier)}
            need(p['model_id'] in recreated, 'candidate replay differs')
        else:
            recreated={q['model_id']:q for q in make_shadows(bundle['snapshot'],bundle['suite'],context)}
        need(recreated[p['model_id']]==p and p['baseline_model_sha256']==base['model_sha256'], 'candidate replay differs')
        check_clock(p['as_of'],p['cutoff_at'],receipt['created_at'])
        ranked=[q['combination'] for q in p['candidates']]
        rank_check(ranked,p['ordered_top8'],lanes=[int(lane) for lane in base['roster']])
        row={k:deepcopy(v) for k,v in base.items() if k not in ('learning_snapshot','learning_snapshot_sha256')}
        row.update(top8=p['ordered_top8'],ranked=ranked,model_sha256=p['prediction_sha256'],
            variant=p['variant'] if video else 'LEARNED_SHADOW',training_sha256=p['training_sha256'],
            baseline_model_sha256=p['baseline_model_sha256'],
            training_artifact_id=p['training_receipt']['id'],training_receipt_digest=p['training_receipt']['digest'])
        out.append(row)
    return out


def merge_shadow_rows(rows):
    """One first candidate per race/phase/family; a retrain cannot rewrite it."""
    first={}
    for row in sorted(rows,key=lambda r:(ts(r['server_saved_at']),r['artifact_id'])):
        key=(row['race_id'],row['stage'],row['model_id'])
        old=first.setdefault(key,row)
        if old['artifact_id']==row['artifact_id']:need(old==row,'conflicting candidate at same receipt')
    return list(first.values())


def score_shadows(rows, baseline_rows, observations):
    from .frozen_day_cycle import settle
    by_result={o['race_id']:o for o in observations}
    bases={(r['race_id'],r['stage'],r['model_id']):r for r in baseline_rows}
    entries=[];groups=defaultdict(list)
    for row in merge_shadow_rows(rows):
        base=bases.get((row['race_id'],row['stage'],row['model_id']))
        need(base is not None and base['model_sha256']==row['baseline_model_sha256'],'paired baseline missing')
        try:
            candidate=settle(row,by_result.get(row['race_id']));baseline=settle(base,by_result.get(row['race_id']))
            paired=candidate['state'] in ('HIT','MISS') and baseline['state'] in ('HIT','MISS')
            item=dict(race_id=row['race_id'],stage=row['stage'],model_id=row['model_id'],
                training_sha256=row['training_sha256'],prediction_sha256=row['model_sha256'],
                server_saved_at=row['server_saved_at'],top8=row['top8'],baseline_top8=base['top8'],
                training_artifact_id=row['training_artifact_id'],state=candidate['state'],paired=paired,
                candidate_hit=candidate['state']=='HIT' if paired else None,
                baseline_hit=baseline['state']=='HIT' if paired else None,
                candidate_received_yen=candidate.get('received_yen') if paired else None,
                baseline_received_yen=baseline.get('received_yen') if paired else None)
            if paired and (candidate['stake_yen']!=800 or baseline['stake_yen']!=800):
                item.update(candidate_stake_yen=candidate['stake_yen'],baseline_stake_yen=baseline['stake_yen'])
        except (ValueError,KeyError,TypeError) as exc:
            item=dict(race_id=row['race_id'],stage=row['stage'],model_id=row['model_id'],
                training_sha256=row['training_sha256'],state='RESULT_REJECTED',paired=False,reason=str(exc)[:160])
        entries.append(item)
        if item['paired']:groups[(row['stage'],row['model_id'],row['training_sha256'])].append(item)
    board=[]
    for (phase,mid,sha),items in groups.items():
        n=len(items);ch=sum(i['candidate_hit'] for i in items);bh=sum(i['baseline_hit'] for i in items)
        board.append(dict(stage=phase,model_id=mid,training_sha256=sha,paired_races=n,
            candidate_hits=ch,baseline_hits=bh,candidate_hit_rate=ch/n,baseline_hit_rate=bh/n,
            candidate_roi=sum(i['candidate_received_yen'] for i in items)/sum(i.get('candidate_stake_yen',800) for i in items),
            baseline_roi=sum(i['baseline_received_yen'] for i in items)/sum(i.get('baseline_stake_yen',800) for i in items),
            promotion_allowed=False))
    return dict(saved_shadow_forecasts=len(entries),paired_forecasts=sum(e['paired'] for e in entries),
        per_forecast=entries,scoreboard=board,accuracy_improvement_proven=False,auto_promoted=False,
        separate_from_baseline_counts=True)


def context_from_result_archive(raw, receipt):
    """Authenticates candidate parameters within a separately saved result ZIP."""
    need(receipt.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest() and receipt.get('expired') is False,
         'training archive authentication failed')
    need(receipt['workflow_run']['head_repository_id']==1416489937,'foreign training archive')
    with open_original_zip(raw,receipt,expected_kind='RESULT',max_plain_zip_bytes=32*1024*1024) as z:
        need(len(z.namelist())==len(set(z.namelist())), 'duplicate training ZIP members')
        if 'trained_observed_models.json' not in z.namelist():return None
        need(z.getinfo('trained_observed_models.json').file_size<4*1024*1024,'training artifact too large')
        training=json.loads(z.read('trained_observed_models.json'));report=json.loads(z.read('status.json'))
    verify_training(training);check(report,'report_sha256')
    need(report['automatic_learning']['training_sha256']==training['training_sha256'], 'training/report mismatch')
    need(ts(training['created_at'])<=ts(receipt['created_at'])+timedelta_one_second(), 'training saved before creation')
    fitted=training['state']=='FITTED_SHADOW_ONLY' or (
        training['schema']=='RACE_AI_EXISTING_OBSERVED_VIDEO_WEIGHT_FIT_V1'
        and training['state']=='FITTED_VIDEO_EXPERIMENTAL')
    return dict(training=training,receipt=deepcopy(receipt)) if fitted else None


def coverage_audit(rows, schedule, *, now, observations=None, learned_rows=None):
    from .boat_ab_shadow import MODEL_IDS as AB
    from .boat_live_feature_shadow import MODEL_ID as C
    expected=set(AB)|{C}|set(MODEL_IDS)
    by_id=defaultdict(set)
    for row in rows:
        if row['stage']=='P1':by_id[row['race_id']].add(row['model_id'])
    need(len({s['race_id'] for s in schedule})==len(schedule),'duplicate coverage schedule')
    ended=[s for s in schedule if ts(s['cutoff_at'])<=now]; missing=[]
    for race in ended:
        absent=sorted(expected-by_id[race['race_id']])
        if absent:missing.append(dict(race_id=race['race_id'],cutoff_at=race['cutoff_at'],
            missing_model_ids=absent,reason='NO_PRE_CUTOFF_P1_RECEIPT',
            exhibition_availability_at_that_time_verified=False))
    out = dict(checked_at=now.isoformat(),scheduled_races=len(schedule),ended_races=len(ended),
        future_races=len(schedule)-len(ended),complete_five_model_p1=len(ended)-len(missing),
        missing_p1_model_predictions=sum(len(r['missing_model_ids']) for r in missing),missing=missing,
        zero_misses_proven=False,missing_races_not_removed_from_denominator=True)
    if observations is not None:
        from .all_race_top8_target import all_race_top8_target
        out['all_race_top8_target'] = all_race_top8_target(
            rows, schedule, observations, now=now, expected_models=expected,
            learned_rows=learned_rows)
    return out


def validate_shadow_training(rows, proofs):
    """Proofs must be populated from independently read result ZIPs, not a P1 claim."""
    for row in rows:
        proof=proofs.get(str(row['training_artifact_id']))
        need(proof is not None and proof['training_sha256']==row['training_sha256']
             and proof['digest']==row['training_receipt_digest'],
             'learned forecast lacks independently verified training receipt')


def training_proof(context):
    return dict(training_sha256=context['training']['training_sha256'],
                digest=context['receipt']['digest'],created_at=context['receipt']['created_at'])


def attach_snapshots(doc, rows):
    """Enrich verified reader output without changing any historical forecast."""
    suites=doc.get('predictions',[])+[b['suite'] for b in doc.get('observed_pairwise_p1_bundles',[]) if 'suite' in b]
    from .frozen_day_cycle import official_id
    snapshots={}
    for suite in suites:
        check(suite,'suite_sha256')
        snapshot=source_snapshot(suite)
        for mid,model in suite['models'].items():
            snapshots[(official_id(suite['race_id']),suite['stage'],mid,model['prediction_sha256'])]=snapshot
    out=deepcopy(rows)
    for row in out:
        snapshot=snapshots.get((row['race_id'],row['stage'],row['model_id'],row['model_sha256']))
        if snapshot is not None:
            row['learning_snapshot']=snapshot;row['learning_snapshot_sha256']=digest(snapshot)
    return out
