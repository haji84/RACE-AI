"""Reproduce the existing ranker/residual comparison on private dated inputs.

Fit and evaluate are separate commands. The selected model is frozen before
evaluation; evaluation never selects or refits it. Public output is aggregate
metrics only. An archive reconstruction is not a pre-cutoff original.
"""
from collections import Counter,defaultdict
from datetime import date,datetime,timezone
from hashlib import sha256
from math import fsum,log
from pathlib import Path
import argparse
import json
import os

import numpy as np

from race_ai.keirin_joint_finish import _distribution,_validate_finish,TailTrainingRace,fit_tail
from race_ai.keirin_nationwide_auto_generator import AutomaticForecastError
from scripts import keirin_boosted_choice_study as residual
from scripts.keirin_line_event_study import SavedRanker
from scripts.keirin_fit_ranking_weights import read
from scripts.keirin_line_version_study import write_private

BASE='docs/evidence/keirin-ordered-ticket-20261124/recent-config.json'
TRAIN_END='20260731'
TUNE_END='20260930'
TEST_END='20261122'
SCHEMA='KEIRIN_FROZEN_RESIDUAL_COMPARISON_V1'


def model_examples(examples):
    """Keep source-valid races with usable features, independent of outcomes."""
    accepted=[];held=Counter()
    for row in examples:
        try:residual.frame(row['input'])
        except AutomaticForecastError as error:
            if str(error) != 'COMPETITION_POINTS_UNAVAILABLE_FOR_ALL':raise
            held[str(error)]+=1
        else:accepted.append(row)
    return accepted,dict(held)


def choose_arm(totals):
    """Predeclared: preserve exactaTop2/tripleTop4, then prefer tripleTop4."""
    baseline=totals['saved']
    eligible=[name for name,row in totals.items()
              if row['n'] == baseline['n'] > 0 and row['top2_2t'] >= baseline['top2_2t']
              and row['top4_3t'] >= baseline['top4_3t']]
    if not eligible:raise ValueError('No comparable calibration races.')
    return max(eligible,key=lambda name:(totals[name]['top4_3t'],totals[name]['top2_2t'],
        -totals[name]['logloss_3t'],totals[name]['top8_3t'],
        -sum(residual.ARMS[name][0])*residual.ARMS[name][1]))


def score_distribution(cars,probabilities,truth):
    cars,probabilities=_distribution(cars,probabilities)
    truth=_validate_finish(cars,truth)
    pairs=defaultdict(float)
    for order,p in probabilities.items():pairs[order[:2]]+=p
    tri=sorted(probabilities,key=lambda order:(-probabilities[order],order))
    two=sorted(pairs,key=lambda order:(-pairs[order],order))
    p3,p2=probabilities[truth[:3]],pairs[truth[:2]]
    return dict(n=1,top1_3t=int(truth[:3] in tri[:1]),top4_3t=int(truth[:3] in tri[:4]),
                top8_3t=int(truth[:3] in tri[:8]),top1_2t=int(truth[:2] in two[:1]),
                top2_2t=int(truth[:2] in two[:2]),logloss_3t=-log(max(p3,1e-300)),
                logloss_2t=-log(max(p2,1e-300)),
                brier_3t=fsum(p*p for p in probabilities.values())-2*p3+1,
                brier_2t=fsum(p*p for p in pairs.values())-2*p2+1,
                top4_mass_3t=fsum(probabilities[t] for t in tri[:4]),
                top8_mass_3t=fsum(probabilities[t] for t in tri[:8]),
                top2_mass_2t=fsum(pairs[t] for t in two[:2]))


def day_bootstrap_interval(rows):
    if not rows:return None
    blocks=defaultdict(list)
    for day,value in rows:blocks[day].append(value)
    sums=np.array([sum(v) for v in blocks.values()]);counts=np.array([len(v) for v in blocks.values()])
    chosen=np.random.default_rng(20261125).integers(0,len(sums),size=(2000,len(sums)))
    values=sums[chosen].sum(axis=1)/counts[chosen].sum(axis=1)
    return np.quantile(values,[.025,.975]).tolist()


def joint_distributions(contexts,ranker,boosters,arms=None):
    phases=[residual.batch_stage(contexts,ranker,booster,stage) for stage,booster in enumerate(boosters)]
    arms=tuple(residual.ARMS) if arms is None else tuple(arms)
    for index,context in enumerate(contexts):
        cars=context[0][0][0];n=len(cars)
        head,second=residual.stage_prefix(cars,2)
        laws={}
        for arm in arms:
            iterations,factor=residual.ARMS[arm]
            selected=[phases[k][index][step if factor != .5 else -step] for k,step in enumerate(iterations)]
            first,following,last=selected
            pairs=first[0,head]*following[head,second]
            weights=pairs[:,None]*last
            laws[arm]={(cars[int(h)],cars[int(s)],cars[t]):float(weights[pos,t])
                       for pos,(h,s) in enumerate(zip(head,second,strict=True))
                       for t in range(n) if t != h and t != s}
            _distribution(cars,laws[arm])
        yield cars,laws


def forecasts(examples,ranker,boosters,*,arms=None,batch_size=192):
    for start in range(0,len(examples),batch_size):
        batch=examples[start:start+batch_size]
        contexts=[residual.frame(row['input']) for row in batch]
        yield from zip(batch,joint_distributions(contexts,ranker,boosters,arms),strict=True)


def summarize(totals):
    result={}
    for arm,row in totals.items():
        n=row['n'];item=dict(row)
        for key in row:
            if key.startswith(('logloss','brier','top4_mass','top8_mass','top2_mass')):
                item[key]=row[key]/n if n else None
        item['rates']={key:row[key]/n if n else None for key in (
            'top1_3t','top4_3t','top8_3t','top1_2t','top2_2t')}
        result[arm]=item
    return result


def _private(root):
    root=Path(root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or root.stat().st_mode&0o777 != 0o700:
        raise ValueError('A pre-existing private0700 folder is required.')
    if any((parent/'.git').exists() for parent in (root,*root.parents)):
        raise ValueError('Private model must remain outside the public Git checkout.')
    return root


def fit_comparison(examples_path,root):
    root=_private(root)
    raw=Path(examples_path).read_bytes();examples,feature_holds=model_examples(read(examples_path))
    if len({row['input']['race_id'] for row in examples}) != len(examples):raise ValueError('Duplicate study races.')
    train=[row for row in examples if row['input']['race_id'][:8] <= TRAIN_END]
    tune=[row for row in examples if TRAIN_END < row['input']['race_id'][:8] <= TUNE_END]
    if not train or not tune:raise ValueError('Disjoint earlier training and tuning data are required.')
    baseline=json.loads(Path(BASE).read_bytes());ranker=SavedRanker(baseline)
    collected,dropouts=residual.collect_training(train)
    boosters=[];hashes=[]
    for stage in range(3):
        booster=residual.fit_stage(collected,ranker,stage);boosters.append(booster)
        text=booster.model_to_string().encode();path=root/f'stage-{stage}.txt'
        with path.open('xb') as output:output.write(text)
        path.chmod(0o600);hashes.append(sha256(text).hexdigest())
        print(json.dumps({'stage_trained':stage,'races':len(train)}),flush=True)
    totals={arm:Counter() for arm in residual.ARMS}
    for row,(cars,laws) in forecasts(tune,ranker,boosters):
        for arm,law in laws.items():totals[arm].update(score_distribution(cars,law,row['finish_order']))
    calibrated=summarize(totals);selected=choose_arm(calibrated)
    # Fit only the suffix using earlier complete finishes. Top3 stays unchanged.
    suffix=[]
    for row,(cars,laws) in forecasts(train,ranker,boosters,arms=(selected,)):
        suffix.append(TailTrainingRace(date.fromisoformat(row['input']['race_id'][:8]),tuple(cars),laws[selected],tuple(row['finish_order'])))
    tail=fit_tail(suffix,before=date(2026,8,1))
    frozen=datetime.now(timezone.utc).isoformat()
    payload=dict(schema=SCHEMA,model_id='keirin-comparison-B-residual',frozen_at=frozen,
        examples_sha256=sha256(raw).hexdigest(),base_configuration=baseline,
        base_configuration_sha256=sha256(Path(BASE).read_bytes()).hexdigest(),stage_sha256=hashes,
        fit_end=TRAIN_END,tune_end=TUNE_END,test_end=TEST_END,fit_races=len(train),tune_races=len(tune),
        selected_arm=selected,mark_dropout_training_races=dropouts,tail_coefficients=list(tail),
        feature_holds=feature_holds,
        tuning=calibrated,calibration_status='UNVALIDATED',source_scope='RETROSPECTIVE_ARCHIVE_NO_PRE_CUTOFF_ATTESTATION',
        source_files_sha256={file:sha256(Path(file).read_bytes()).hexdigest() for file in (
            'scripts/keirin_accuracy_study.py','scripts/keirin_boosted_choice_study.py',
            'scripts/keirin_ordered_ticket_study.py','scripts/keirin_line_event_study.py',
            'race_ai/keirin_archive_study.py','race_ai/keirin_joint_finish.py')})
    write_private(root/'model.json',payload)
    return {key:payload[key] for key in ('model_id','frozen_at','fit_races','tune_races','selected_arm','tuning','calibration_status')}


def load_model(root):
    import lightgbm as lgb
    root=_private(root);payload=json.loads((root/'model.json').read_bytes())
    if payload['schema'] != SCHEMA or payload['selected_arm'] not in residual.ARMS:raise ValueError('Unknown comparison model.')
    boosters=[]
    for stage,expected in enumerate(payload['stage_sha256']):
        text=(root/f'stage-{stage}.txt').read_bytes()
        if sha256(text).hexdigest() != expected:raise ValueError('Frozen booster digest mismatch.')
        boosters.append(lgb.Booster(model_str=text.decode()))
    if len(boosters) != 3:raise ValueError('Three frozen conditional stages are required.')
    return payload,SavedRanker(payload['base_configuration']),boosters


def evaluate_comparison(examples_path,root):
    root=_private(root);payload,ranker,boosters=load_model(root)
    if sha256(Path(examples_path).read_bytes()).hexdigest() != payload['examples_sha256']:
        raise ValueError('Evaluation inputs differ from the frozen study dataset.')
    examples,feature_holds=model_examples([row for row in read(examples_path)
                                         if TUNE_END < row['input']['race_id'][:8] <= TEST_END])
    if not examples:raise ValueError('No later evaluation races.')
    selected=payload['selected_arm'];arms=tuple(dict.fromkeys(('saved',selected)))
    totals={arm:Counter() for arm in arms};paired=defaultdict(list);daily=defaultdict(lambda:dict(saved=Counter(),candidate=Counter()))
    for row,(cars,laws) in forecasts(examples,ranker,boosters,arms=arms):
        scores={arm:score_distribution(cars,law,row['finish_order']) for arm,law in laws.items()}
        day=row['input']['race_id'][:8]
        for arm,values in scores.items():totals[arm].update(values)
        for metric in ('top4_3t','top8_3t','top2_2t','logloss_3t','brier_3t'):
            paired[metric].append((day,scores[selected][metric]-scores['saved'][metric]))
        daily[day]['saved'].update(scores['saved']);daily[day]['candidate'].update(scores[selected])
    report=dict(schema='KEIRIN_RESIDUAL_HOLDOUT_SCORE_V1',evaluated_at=datetime.now(timezone.utc).isoformat(),
        frozen_model_sha256=sha256((root/'model.json').read_bytes()).hexdigest(),selected_arm=selected,
        scope='RETROSPECTIVE_CHRONOLOGICAL_RECONSTRUCTION_NOT_FUTURE_INDEPENDENT',
        evaluation_dates=['20261001',TEST_END],races=len(examples),metrics=summarize(totals),
        feature_holds=feature_holds,
        paired_day_bootstrap_95={key:day_bootstrap_interval(rows) for key,rows in paired.items()},
        paired_deltas={key:sum(value for _,value in rows)/len(rows) for key,rows in paired.items()},
        days={day:{key:dict(value) for key,value in data.items()} for day,data in daily.items()},
        production_weights_promoted=False,pre_cutoff_originals_created=False)
    write_private(root/'evaluation.json',report)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('fit','evaluate'))
    parser.add_argument('--examples',required=True,type=Path)
    parser.add_argument('--private-root',required=True,type=Path)
    args=parser.parse_args(argv)
    action=fit_comparison if args.command == 'fit' else evaluate_comparison
    report=action(args.examples,args.private_root)
    print(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2))


if __name__=='__main__':main()
