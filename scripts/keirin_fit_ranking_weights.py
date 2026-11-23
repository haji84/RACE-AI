"""Fit existing keirin A/B finish adjustments on earlier, admitted races."""
from collections import defaultdict
from itertools import permutations
from pathlib import Path
import argparse
import gzip
import json

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_ranking_adjustment as adjustment

POINTS = ('relative_points','relative_points_known')
RATES = (('win_rate',), ('top2_rate',), ('top3_rate',))
FINISH_RATES = (('win_rate',), ('win_rate','second_only_rate'),
                ('win_rate','second_only_rate','third_only_rate'))
VARIANTS = ('cumulative', 'separate_finish_rates', 'separate_finish_rates_and_style')
BLENDS = (.35,.65,1.0)


def fields(variant, omit=None):
    rates = RATES if variant=='cumulative' else FINISH_RATES
    groups = []
    for position in range(3):
        names = []
        if omit!='points':
            names.extend(POINTS)
        if omit!='marks':
            names.extend(adjustment.MARK_FIELDS)
        if omit!='rates':
            for rate in rates[position]:
                names.extend((rate, rate.removesuffix('_rate')+'_known'))
        if variant==VARIANTS[-1] and omit!='style':
            names.extend(adjustment.STYLE_FIELDS)
        groups.append(tuple(names))
    return groups


def fit_records(rows, end):
    usable = []
    for record in rows:
        race = record['input']
        if race['race_id'][:8]>end or record['cohort']!='annual' or race['line_groups'] is not None:
            raise ValueError('Learned weights require the declared historical training partition.')
        labels = record['outcomes']
        # Multiple paid orders are scored in evaluation. They do not supply a
        # unique finish order for the conditional likelihood used in fitting.
        if len(labels['3t'])!=1 or len(labels['2t'])!=1:
            continue
        podium = labels['3t'][0]
        vectors = adjustment.feature_vectors(core._evidence_profiles(race)[0])
        cars = sorted(vectors)
        if len(podium)!=3 or len(set(podium))!=3 or list(podium[:2])!=list(labels['2t'][0]):
            raise ValueError('Training markets do not agree.')
        usable.append((vectors,cars,[cars.index(car) for car in podium]))
    if not usable:
        raise ValueError('No admitted training races.')
    x = np.zeros((len(usable),9,len(adjustment.FEATURES)))
    mask = np.zeros((len(usable),9),dtype=bool)
    outcomes = np.zeros((len(usable),3),dtype=np.int64)
    for index,(vectors,cars,places) in enumerate(usable):
        mask[index,:len(cars)] = True
        x[index,:len(cars)] = [[vectors[car][name] for name in adjustment.FEATURES] for car in cars]
        outcomes[index] = places
    return x,mask,outcomes


def fit_weights(training, variant, omit=None):
    x,available,outcomes = training
    available = available.copy()
    rows = np.arange(len(x))
    result = []
    for position,names in enumerate(fields(variant,omit)):
        data = x[:,:,[adjustment.FEATURES.index(name) for name in names]]
        expected = outcomes[:,position]

        def objective(weights):
            logits = np.einsum('rnf,f->rn',data,weights)
            masked = np.where(available,logits,-np.inf)
            denominator = logsumexp(masked,axis=1)
            chosen = logits[rows,expected]
            error = np.exp(masked-denominator[:,None])
            error[rows,expected] -= 1
            gradient = np.einsum('rn,rnf->f',error,data)/len(x)
            return (float(np.mean(denominator-chosen)+.001*np.dot(weights,weights)),
                    gradient+.002*weights)

        best = minimize(objective,np.zeros(len(names)),jac=True,method='L-BFGS-B',
                        bounds=[(-12,12)]*len(names), options={'ftol':1e-12,'maxiter':180})
        if not best.success:
            raise RuntimeError(f'Conditional fit failed for slot {position+1}.')
        result.append(dict(zip(names,[round(float(x),10) for x in best.x])))
        available[rows,expected] = False
    return result


def validation_groups(rows, low, high):
    grouped = defaultdict(list)
    for record in rows:
        race = record['input']
        if not low<=race['race_id'][:8]<=high or record['cohort']!='annual':
            raise ValueError('Validation dates must be outside training and before the final test.')
        profiles = core._evidence_profiles(race)[0]
        grouped[len(profiles)].append((profiles,adjustment.feature_vectors(profiles),record))
    result = []
    for size,members in sorted(grouped.items()):
        pairs = np.array(list(permutations(range(size),2)))
        triples = np.array(list(permutations(range(size),3)))
        pair_index = {tuple(pair): index for index,pair in enumerate(pairs)}
        repeats = np.array([pair_index[tuple(triple[:2])] for triple in triples])
        features, power, truth2, truth3, originals = [], [], [], [], []
        for profiles,vector,record in members:
            cars = sorted(profiles)
            features.append([[vector[car][key] for key in adjustment.FEATURES] for car in cars])
            power.append([[max(.001,profiles[car][key]) for car in cars]
                          for key in ('head_strength','second_strength','third_strength')])
            hit = {m:{tuple(cars.index(car) for car in combo) for combo in record['outcomes'][m]}
                   for m in ('2t','3t')}
            truth2.append([tuple(pair) in hit['2t'] for pair in pairs])
            truth3.append([tuple(triple) in hit['3t'] for triple in triples])
            originals.append({market: int(any(pick in record['outcomes'][market]
                                               for pick in record['old']['current_A'][market]['top']))
                              for market in ('2t','3t')})
        result.append(dict(x=np.array(features),power=np.array(power),pairs=pairs,triples=triples,
                           repeat=repeats,truth2=np.array(truth2),truth3=np.array(truth3),
                           originals=originals))
    return result


def validation_hits(groups, coeffs, blend):
    table = np.array([[stage.get(name,0.0) for name in adjustment.FEATURES] for stage in coeffs])
    hits = {'2t':0,'3t':0}
    for g in groups:
        pairs,triples = g['pairs'],g['triples']
        a,b = pairs.T
        i,j,k = triples.T
        p = g['power']
        logits = np.einsum('rnf,sf->rsn',g['x'],table)
        e = np.exp(logits-logits.max(axis=2,keepdims=True))
        original = p[:,0,a]**2*p[:,1,b]**1.3
        learned = (e[:,0,a]/e[:,0,:].sum(axis=1,keepdims=True)
                   * e[:,1,b]/(e[:,1,:].sum(axis=1,keepdims=True)-e[:,1,a]))
        pair = original**(1-blend)*learned**blend
        third = p[:,2,:]**(.8*(1-blend))*e[:,2,:]**blend
        denom = third.sum(axis=1,keepdims=True)-third[:,i]-third[:,j]
        triple = pair[:,g['repeat']]*third[:,k]/denom
        for market,prob,truth in (('2t',pair,g['truth2']),('3t',triple,g['truth3'])):
            indices = np.argsort(-prob,axis=1,kind='stable')[:,:4]
            hits[market] += int(np.take_along_axis(truth,indices,axis=1).any(axis=1).sum())
    return hits


def read(path):
    with gzip.open(path,'rt') as raw:
        return json.load(raw)


def train(training_rows, validation_rows, train_end, validation_end):
    if any(r['input']['race_id'][:8]<=train_end for r in validation_rows):
        raise ValueError('Validation overlaps with training.')
    fit = fit_records(training_rows,train_end)
    validate = validation_groups(validation_rows,min(r['input']['race_id'][:8] for r in validation_rows),validation_end)
    original = {market:sum(row[market] for group in validate for row in group['originals'])
                for market in ('2t','3t')}
    candidates, coefficients = [], {}
    for variant in VARIANTS:
        weights = fit_weights(fit,variant)
        coefficients[variant] = weights
        for blend in BLENDS:
            candidates.append(dict(variant=variant, blend=blend, hits=validation_hits(validate,weights,blend)))
    # Primary metric remains 3t at the same budget, with a 2t no-loss guard.
    eligible = [c for c in candidates if c['hits']['2t']>=original['2t']]
    if not eligible:
        raise ValueError('No candidate preserves the original validation 2t performance.')
    chosen = max(eligible,key=lambda c:(c['hits']['3t'],c['hits']['2t'],-c['blend'],-VARIANTS.index(c['variant'])))
    ablations = {}
    for omitted in ('points','marks','rates','style'):
        if omitted=='style' and chosen['variant']!=VARIANTS[-1]:
            continue
        control = fit_weights(fit,chosen['variant'],omit=omitted)
        ablations[omitted] = validation_hits(validate,control,chosen['blend'])
    return {'schema':'KEIRIN_RESEARCH_RANK_ADJUSTMENT_V1',
            'fit_end':train_end,'validation_end':validation_end, 'fit_unique_results':len(fit[0]),
            'validation_races':len(validation_rows),'original_validation_hits':original,
            'candidates':candidates,'selected':chosen,
            'feature_ablation_validation_hits':ablations,
            'coefficients':coefficients[chosen['variant']]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fit',required=True,type=Path)
    parser.add_argument('--validate',required=True,type=Path)
    parser.add_argument('--fit-end',required=True)
    parser.add_argument('--validation-end',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    study=train(read(args.fit),read(args.validate),args.fit_end,args.validation_end)
    with args.output.open('x') as f:
        json.dump(study,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write('\n')
    print(json.dumps({k:v for k,v in study.items() if k!='coefficients'},ensure_ascii=False))


if __name__=='__main__':
    main()
