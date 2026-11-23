"""Research the existing conditional finish ranking with planned keirin lines."""

from collections import Counter
from pathlib import Path
import argparse
import json
import re

import numpy as np

from scripts import keirin_fit_ranking_weights as fitter
from scripts import keirin_small_ticket_study as previous


MODES = ('entry_only', 'published_line', 'line_with_history')
LINE_FIELDS = ('line_leader', 'line_second', 'line_rear', 'line_solo',
               'line_size', 'line_average_score', 'line_leader_score')
PHASE_FIELDS = ('s', 'b', 'front_win')
PAIR_FIELDS = ('same_line', 'next_in_order', 'precedes_winner', 'same_leading_line')
CAPS = {'2t': (1, 2, 4), '3t': (4, 8)}


def observed_rate(counts, *, admitted):
    """Return a value and sample weight; sparse or unbound observations stay missing."""
    if not admitted or not isinstance(counts, dict):
        return 0.0, 0.0
    n, yes = counts.get('n'), counts.get('yes')
    if type(n) is not int or type(yes) is not int or not 0 <= yes <= n:
        raise ValueError('Invalid past phase observation counts.')
    return (yes/n, n/(n+6)) if n>=3 else (0.0, 0.0)


def frame(snapshot):
    cars, base = previous.rider_evidence(snapshot)
    group_count = snapshot['line_groups']
    membership = {}
    for group, line in enumerate(group_count):
        if not line:
            raise ValueError('Empty published line.')
        for pos, car in enumerate(line):
            if car in membership:
                raise ValueError('Duplicate starter in published line.')
            membership[car] = (group, pos, len(line))
    if set(membership) != set(cars):
        raise ValueError('Published lines and starter set do not agree.')
    group, position, sizes = np.array([membership[car] for car in cars]).T
    current = {r['car']: r for r in snapshot['riders']}
    registered = [
        re.fullmatch(r'[0-9]{6}', str(current[car].get('registration') or '')) is not None
        for car in cars
    ]
    points, known = base['relative_points'], base['relative_points_known']
    metrics, leaders = {}, {}
    for line_id in range(len(group_count)):
        mask = (group == line_id) & (known > 0)
        metrics[line_id] = float(np.mean(points[mask])) if np.any(mask) else 0.0
        first = cars.index(group_count[line_id][0])
        leaders[line_id] = points[first] if known[first] else 0.0
    columns = {
        'line_leader': (position==0) & (sizes>1), 'line_second': position==1,
        'line_rear': position>=2, 'line_solo': sizes==1,
        'line_size': sizes/9, 'line_average_score': np.array([metrics[g] for g in group]),
        'line_leader_score': np.array([leaders[g] for g in group]),
    }
    for metric in PHASE_FIELDS:
        history = [observed_rate(current[car].get('history', {}).get(metric), admitted=admitted)
                   for car, admitted in zip(cars, registered)]
        value, confidence = np.array(history).T
        columns['previous_'+metric+'_rate'] = value*confidence
        columns['previous_'+metric+'_support'] = confidence
    return cars, base, columns, group, position, sizes


def names_for(mode, stage):
    names = previous.feature_names('prior_finishers', stage)
    if stage==2 or mode=='entry_only':
        return names
    names += LINE_FIELDS
    if stage==1:
        names += PAIR_FIELDS
    if mode=='line_with_history':
        names += tuple('previous_'+key+'_'+kind for key in PHASE_FIELDS for kind in ('rate','support'))
    return names


def design(info, mode, prefix):
    cars, base, columns, group, position, sizes = info
    stage=len(prefix)
    original=previous.choice_matrix(base, previous.feature_names('prior_finishers', stage), prefix)
    if stage==2 or mode=='entry_only':
        return original
    cols=np.column_stack([columns[key] for key in LINE_FIELDS])
    blocks=[original,np.broadcast_to(cols,(original.shape[0],*cols.shape))]
    if stage==1:
        head=prefix[0][:,None]
        same=group[head]==group
        blocks.append(np.stack((same, same & (position==position[head]+1),
                                same & (position<position[head]),
                                same & (sizes[head]>=3)),axis=-1))
    if mode=='line_with_history':
        history=np.column_stack([columns['previous_'+key+'_'+kind]
                                 for key in PHASE_FIELDS for kind in ('rate','support')])
        blocks.append(np.broadcast_to(history,(original.shape[0],*history.shape)))
    return np.concatenate(blocks,axis=-1)


def fit(examples):
    rows=[]
    for item in examples:
        paid=item['outcomes']
        if len(paid['2t'])!=1 or len(paid['3t'])!=1:
            continue
        observed=paid['3t'][0]
        if len(observed)!=3 or len(set(observed))!=3 or observed[:2]!=paid['2t'][0]:
            raise ValueError('Fitting result orders disagree across the two markets.')
        info=frame(item['input'])
        rows.append((info,[info[0].index(car) for car in observed]))
    if not rows:
        raise ValueError('No unambiguous earlier paid order.')
    allowed=np.array([np.arange(9)<len(info[0]) for info,_ in rows])
    placements=np.array([finish for _,finish in rows])
    output={mode:[] for mode in MODES}
    for stage in range(3):
        rich='line_with_history' if stage<2 else 'entry_only'
        design_data=np.zeros((len(rows),9,len(names_for(rich,stage))))
        for index,(info,order) in enumerate(rows):
            prefix=tuple(np.array([earlier]) for earlier in order[:stage])
            design_data[index,:len(info[0])]=design(info,rich,prefix)[0]
        for mode in MODES if stage<2 else ('entry_only',):
            names=names_for(mode,stage)
            coefficients=fitter.fit_choice(design_data[:,:,:len(names)],allowed,placements[:,stage])
            output[mode].append(dict(zip(names,coefficients)))
        allowed[np.arange(len(rows)),placements[:,stage]]=False
    return output, len(rows)


def distribution(info, coefficients, mode, prefix):
    weight=coefficients[mode][len(prefix)]
    logits=design(info,mode,prefix)@np.array([weight[key] for key in names_for(mode,len(prefix))])
    for fixed in prefix:
        logits[np.arange(len(fixed)),fixed]=-np.inf
    mass=np.exp(logits-np.max(logits,axis=1,keepdims=True))
    return mass/mass.sum(axis=1,keepdims=True)


def predict(snapshot, coefficients):
    info=frame(snapshot)
    cars=info[0]
    n=len(cars)
    heads,seconds=np.where(~np.eye(n,dtype=bool))
    common_third=distribution(info,coefficients,'entry_only',(heads,seconds))
    masks=np.arange(n)
    output={}
    for mode in MODES:
        first=distribution(info,coefficients,mode,())[0]
        second=distribution(info,coefficients,mode,(masks,))
        paired=first[heads]*second[heads,seconds]
        triple=(paired[:,None]*common_third).ravel()
        two=np.argsort(-paired,kind='stable')[:max(CAPS['2t'])]
        three=np.argsort(-triple,kind='stable')[:max(CAPS['3t'])]
        output[mode]={
            '2t':[(cars[heads[i]],cars[seconds[i]]) for i in two],
            '3t':[(cars[heads[i//n]],cars[seconds[i//n]],cars[i%n]) for i in three],
        }
    return output


def examples(path, start, end):
    items=fitter.read(path)
    dates=[row['input']['race_id'] for row in items]
    if not dates or len(set(dates))!=len(dates) or not all(start<=x[:8]<=end for x in dates):
        raise ValueError('Training and evaluation windows must be chronological and disjoint.')
    return items


def learn(train, calibration):
    coefficients,n=fit(train)
    scores={mode:Counter() for mode in MODES}
    for item in calibration:
        truth={m:{tuple(order) for order in item['outcomes'][m]} for m in CAPS}
        for mode, orders in predict(item['input'],coefficients).items():
            for market,caps in CAPS.items():
                for cap in caps:
                    scores[mode][f'{market}_{cap}']+=any(order in truth[market] for order in orders[market][:cap])
    selected=max(MODES,key=lambda mode:(scores[mode]['2t_2'],scores[mode]['2t_4'],scores[mode]['3t_8']))
    return {'schema':'KEIRIN_PUBLISHED_LINE_HISTORY_STUDY_V1','fit_unique':n,
            'calibration_races':len(calibration),'selected':selected,'coefficients':coefficients,
            'validation_counts':{mode:dict(summary) for mode,summary in scores.items()}}


def main():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--fit',required=True,type=Path)
    args.add_argument('--tune',required=True,type=Path)
    args.add_argument('--output',required=True,type=Path)
    config=args.parse_args()
    model=learn(examples(config.fit,'20260903','20261020'),
                examples(config.tune,'20261021','20261031'))
    with config.output.open('x') as file:
        json.dump(model,file,ensure_ascii=False,indent=2,allow_nan=False)
        file.write('\n')
    print(json.dumps({k:v for k,v in model.items() if k!='coefficients'},ensure_ascii=False))


if __name__=='__main__':
    main()
