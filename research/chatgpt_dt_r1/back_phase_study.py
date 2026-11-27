"""Real archived B-mark supervision for a DT-R1 research candidate.

B marks identify the final-back leader, not the full order or measured fatigue.
Learn P(B leader | pre-race features), then the conditional finish law.
At prediction marginalize over ALL possible B leaders. The target B/result
is never read in inference. Same labeled training cohort for direct baseline.
No betting, promotion, or replacement of the five-ability frozen model.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from hashlib import sha256
import argparse
import json
import math
import subprocess
import unicodedata
import re
import os
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from .data import load_archives, SOURCE_COMMIT, PINNED_SOURCE_SHA256, _verify_file
from .features import build_features, _bind_feature_input, retired_timing_feature
from .model import fit_ranker, RankModel, _verify_feature_binding, digest
from .agari import augment_agari
from .abilities import augment_abilities
from .pipeline import DEFAULT_SPLITS, partition, _result_key, write_private_json

VERSION='dt-r1-back-latent-mixture-v1'
SCENARIO_NAMES=('scenario_B_self','scenario_B_same_line','scenario_B_predecessor',
                'scenario_B_successor','scenario_B_other_line','scenario_B_line_unknown')
SOURCE='https://keirin.jp/pc/static/beginner/basics/racecard.html'
K=(1,2,4,9,12)


def back_label(row):
    """One explicit B marker and a complete matched result roster; otherwise unknown."""
    cars=[r['car'] for r in row['riders']]
    results=row.get('result_rows') or []
    seen=[r.get('car') for r in results]
    if len(seen)!=len(set(seen)) or set(seen)!=set(cars):
        return None,'RESULT_ROSTER_INCOMPLETE'
    if str(row.get('result_status','')).upper() in ('CANCELLED','MISSING','PENDING'):
        return None,'RESULT_UNAVAILABLE'
    hits=[]
    for r in results:
        mark=r.get('sb_mark')
        if mark is None:
            continue
        if not isinstance(mark,str):
            return None,'MARK_UNRECOGNIZED'
        mark=re.sub(r'[\s,／/・]+','',unicodedata.normalize('NFKC',mark).upper())
        if mark in ('','-','―','－'):
            continue
        if not re.fullmatch('[SHB]+',mark):
            return None,'MARK_UNRECOGNIZED'
        if 'B' in mark:
            hits.append(r['car'])
    if len(hits)!=1:
        return None,'NO_EXPLICIT_B' if not hits else 'AMBIGUOUS_B'
    return hits[0],'UNIQUE_ARCHIVED_B'


def prepare(records):
    """Compact pre-race schema: core histories, agari and five-ability proxies.
    No unavailable video or weather fields and no discovery search on test."""
    rows=augment_abilities(augment_agari(build_features(records)))
    out=[]
    for row in rows:
        names=row['feature_names']
        keep=[i for i,n in enumerate(names) if not retired_timing_feature(n)
            and not n.startswith(('history_agari_context_','history_dt_motion_','history_dt_discovery_'))]
        r=dict(row,features=np.asarray(row['features'])[:,keep],
               feature_names=tuple(names[i] for i in keep),feature_version=row['feature_version']+'+'+VERSION)
        out.append(_bind_feature_input(r))
    return out


def scenario_row(row, leader):
    _verify_feature_binding(row)
    cars=[r['car'] for r in row['riders']]
    if leader not in cars:
        raise ValueError('B_SCENARIO_OUTSIDE_ROSTER')
    if any(n.startswith('scenario_B_') for n in row['feature_names']):
        raise ValueError('B_SCENARIO_ALREADY_BOUND')
    groups=row.get('line_groups') or []
    known=(row.get('lines_known') is True and row.get('lines_applicable') is True and
           all(groups) and sorted(c for g in groups for c in g)==sorted(cars))
    pos={c:(i,j) for i,g in enumerate(groups) for j,c in enumerate(g)} if known else {}
    extra=[]
    for c in cars:
        same=known and pos[c][0]==pos[leader][0] and c!=leader
        extra.append((c==leader,same,same and pos[c][1]+1==pos[leader][1],
                      same and pos[c][1]==pos[leader][1]+1,
                      known and pos[c][0]!=pos[leader][0],not known))
    r=dict(row,features=np.column_stack((row['features'],np.asarray(extra,dtype=float))),
           feature_names=tuple(row['feature_names'])+SCENARIO_NAMES,
           feature_version=row['feature_version']+'+B-scenario')
    r['history_evidence']=dict(row['history_evidence'],back_scenario={'candidate_car':leader,
         'scope':'hypothetical_condition_not_observed_target'})
    return _bind_feature_input(r)


def fit_leader(rows,before,ridge=.01):
    if len(rows)<30 or any(r['day']>=before for r in rows) or len({r['race_id'] for r in rows})!=len(rows):
        raise ValueError('B_TRAINING_BOUNDARY_OR_COUNT')
    matrices=[];labels=[]
    names=tuple(rows[0]['feature_names'])
    for row in rows:
        _verify_feature_binding(row)
        leader,status=back_label(row)
        if leader is None or tuple(row['feature_names'])!=names:
            raise ValueError('B_TRAINING_LABEL_OR_SCHEMA')
        matrices.append(np.asarray(row['features'],dtype=float))
        labels.append([r['car'] for r in row['riders']].index(leader))
    xall=np.concatenate(matrices);mean=xall.mean(0);scale=xall.std(0);scale[scale<1e-6]=1.
    x=np.zeros((len(rows),9,len(names)));valid=np.zeros((len(rows),9),bool)
    for i,m in enumerate(matrices):
        x[i,:len(m)]=np.clip((m-mean)/scale,-12,12);valid[i,:len(m)]=True
    y=np.asarray(labels);ix=np.arange(len(rows));flat=x.reshape(-1,len(names))
    def objective(w):
        scores=(flat@w).reshape(len(rows),9);scores=np.where(valid,scores,-np.inf)
        normal=logsumexp(scores,axis=1)
        loss=np.mean(normal-scores[ix,y]) + ridge*float(w@w)/2
        diff=np.exp(scores-normal[:,None]);diff[ix,y]-=1
        return float(loss),flat.T@diff.ravel()/len(rows)+ridge*w
    result=minimize(objective,np.zeros(len(names)),method='L-BFGS-B',jac=True,options={'maxiter':160,'ftol':1e-9,'gtol':1e-5})
    if not np.isfinite(result.x).all() or not np.isfinite(result.fun):
        raise ValueError('B_OPTIMIZATION_FAILED')
    return {'schema':VERSION,'feature_names':list(names),'mean':mean.tolist(),'scale':scale.tolist(),
            'weights':result.x.tolist(),'before':before,'training_n':len(rows),'converged':bool(result.success),
            'training_fingerprint':digest([(r['race_id'],r['feature_input_sha256'],back_label(r)[0]) for r in rows])}


def leader_prob(model,row):
    _verify_feature_binding(row)
    if tuple(row['feature_names'])!=tuple(model['feature_names']):
        raise ValueError('B_SCHEMA_MISMATCH')
    mean=np.asarray(model['mean']);scale=np.asarray(model['scale']);w=np.asarray(model['weights'])
    if not np.isfinite(w).all() or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale<=0):
        raise ValueError('B_MODEL_VALUES')
    z=np.clip((np.asarray(row['features'])-mean)/scale,-12,12)@w
    p=np.exp(z-logsumexp(z))
    return dict(zip((r['car'] for r in row['riders']),map(float,p)))


def mixture(leader,conditional,row):
    """No target labels consulted. Marginalize all scenario distributions."""
    p=leader_prob(leader,row);mass=Counter();by_leader={}
    for car,weight in p.items():
        triples=conditional.distribution(scenario_row(row,car))['trifectas']
        conditional_wins=Counter()
        for t in triples:
            order=tuple(t['cars']);prob=t['probability']
            mass[order]+=weight*prob;conditional_wins[order[0]]+=prob
        by_leader[car]=conditional_wins
    z=math.fsum(mass.values())
    if abs(z-1)>1e-8:
        raise ValueError('B_MIXTURE_MASS_INVALID')
    mass={k:v/z for k,v in mass.items()}
    wins=Counter();exacta=Counter()
    for k,v in mass.items():
        wins[k[0]]+=v;exacta[k[:2]]+=v
    favorite=max(wins,key=lambda c:(wins[c],-c))
    return {'trifectas':[{'cars':list(k),'probability':v} for k,v in sorted(mass.items(),key=lambda t:(-t[1],t[0]))],
            'exactas':[{'cars':list(k),'probability':v} for k,v in sorted(exacta.items(),key=lambda t:(-t[1],t[0]))],
            'back_leader':p,'favorite_car':favorite,
            'favorite_loss_by_back_leader':[{'back_leader':c,'scenario_probability':w,
                 'conditional_loss_probability':max(0.,min(1.,1-by_leader[c][favorite]))} for c,w in sorted(p.items())],
            'scope':'ARCHIVE_TRAINED_STATISTICAL_SCENARIO_NOT_VIDEO_OR_CAUSAL'}


def score(rows,leader,conditional,direct):
    counts=Counter(); b_hits=0;b_loss=[];all_n=0
    hits={name:{str(k):0 for k in K} for name in ('direct','mixture')}
    exactas={name:{str(k):0 for k in (1,2)} for name in hits}
    losses={name:[] for name in hits}
    for row in rows:
        b,status=back_label(row);counts[status]+=1
        if row.get('feature_status')!='READY':
            counts['FEATURE_HOLD']+=1;continue
        p=leader_prob(leader,row)
        if b is not None:
            b_hits+=int(max(p,key=lambda c:(p[c],-c))==b)
            b_loss.append(-math.log(max(p[b],1e-300)))
        y=_result_key(row)
        if not y:
            continue
        y=tuple(y);all_n+=1
        laws={'direct':direct.distribution(row),'mixture':mixture(leader,conditional,row)}
        for name,law in laws.items():
            ranked=law['trifectas'];q=next(t['probability'] for t in ranked if tuple(t['cars'])==y)
            losses[name].append(-math.log(max(q,1e-300)))
            for k in K:hits[name][str(k)]+=int(y in [tuple(t['cars']) for t in ranked[:k]])
            for k in (1,2):exactas[name][str(k)]+=int(y[:2] in [tuple(t['cars']) for t in law['exactas'][:k]])
    return {'registered':len(rows),'finish_evaluable':all_n,'B_label_counts':dict(counts),
            'B_evaluable':len(b_loss),'B_top1_hits':b_hits,'B_top1_rate':b_hits/len(b_loss) if b_loss else None,
            'B_log_loss':float(np.mean(b_loss)) if b_loss else None,
            'finish':{name:{'top3_log_loss':float(np.mean(losses[name])) if all_n else None,
                           'trifecta_hits':hits[name],'exacta_hits':exactas[name]} for name in hits}}


def study(paths,destination):
    records,audit=load_archives(paths)
    rows=prepare(records);groups=partition(rows,DEFAULT_SPLITS)
    train=[r for r in groups['fit'] if r.get('feature_status')=='READY' and _result_key(r) and back_label(r)[0] is not None]
    before=DEFAULT_SPLITS['tune']['start']
    print('B_STUDY_TRAINING '+str(len(train)),flush=True)
    leader=fit_leader(train,before)
    conditional=fit_ranker([scenario_row(r,back_label(r)[0]) for r in train],before=before)
    direct=fit_ranker(train,before=before)
    # Freeze before evaluating. No final-period choice or calibration transfer.
    artifact={'schema':VERSION,'source_dataset_sha256':audit['dataset_sha256'],
              'leader':leader,'conditional':conditional.to_dict(),'direct':direct.to_dict(),
              'source_definition':SOURCE,'production_promoted':False}
    artifact['artifact_sha256']=digest(artifact)
    destination.mkdir(mode=0o700,parents=True,exist_ok=False)
    write_private_json(destination/'back_candidate.json',artifact)
    report={'schema':VERSION,'scope':'REUSED_RETROSPECTIVE_ARCHIVE_NOT_PROSPECTIVE',
            'source_definition':SOURCE,'archive_races':audit['unique_races'],'training_labeled':len(train),
            'artifact_sha256':artifact['artifact_sha256'],'optimizers_converged':{
                 'leader':leader['converged'],'conditional':conditional.fit_meta['optimizer_converged'],
                 'direct':direct.fit_meta['optimizer_converged']},
            'tune':score(groups['tune'],leader,conditional,direct),
            'test':score(groups['test'],leader,conditional,direct),
            'video_kinematics_measured':False,'full_phase_order_measured':False,'production_promoted':False}
    write_private_json(destination/'aggregate.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('private',type=Path)
    args=parser.parse_args();private=args.private.resolve()
    if not private.is_dir() or any((p/'.git').exists() for p in (private,*private.parents)):
        raise ValueError('PRIVATE_RUNNER_PATH_REQUIRED')
    paths=[]
    for name in PINNED_SOURCE_SHA256:
        path=private/name
        url=f'https://raw.githubusercontent.com/sumidatadayoshi/keirin-data/{SOURCE_COMMIT}/data/{name}'
        subprocess.run(['curl','--fail','--silent','--show-error','--location','--proto','=https',
                        '--proto-redir','=https','--connect-timeout','15','--max-time','180','--output',str(path),url],
                       check=True)
        _verify_file(path,PINNED_SOURCE_SHA256);paths.append(path)
    result=study(paths,private/'B-study')
    print('DT_R1_B_AGGREGATE '+json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False),flush=True)

if __name__=='__main__':main()
