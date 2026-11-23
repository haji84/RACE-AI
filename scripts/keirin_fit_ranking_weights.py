"""Fit existing keirin A/B finish adjustments on earlier, admitted races."""
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
import argparse
import gzip
import json

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
    import numpy as np

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
    import numpy as np
    from scipy.optimize import minimize
    from scipy.special import logsumexp

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


def score_validation_race(record, trials):
    snapshot = record['input']
    base = core.generate_evidence_analysis(snapshot)
    profiles = {row['car']: row for row in base['feature_audit']['riders']}
    paid = {market: {tuple(order) for order in record['outcomes'][market]}
            for market in ('2t', '3t')}

    def score(forecast):
        return {
            market: int(any(tuple(ticket) in orders
                            for ticket in forecast['candidate_tickets'][market][:4]))
            for market, orders in paid.items()
        }

    original = base['A']
    comparisons = [
        score(adjustment.adjust(snapshot, original, 'A', weights, blend, profiles=profiles))
        for weights, blend in trials
    ]
    return score(original), comparisons


def validation_totals(executor, rows, trials):
    original = {'2t': 0, '3t': 0}
    totals = [dict(original) for _ in trials]
    score = partial(score_validation_race, trials=trials)
    for baseline, comparisons in executor.map(score, rows, chunksize=24):
        for market in original:
            original[market] += baseline[market]
            for total, comparison in zip(totals, comparisons):
                total[market] += comparison[market]
    return original, totals


def read(path):
    with gzip.open(path,'rt') as raw:
        return json.load(raw)


def train(training_rows, validation_rows, train_end, validation_end):
    if not validation_rows or any(
        not train_end < row['input']['race_id'][:8] <= validation_end
        or row['cohort'] != 'annual' or row['input']['line_groups'] is not None
        for row in validation_rows
    ):
        raise ValueError('Validation needs ability-only races within the declared validation dates.')
    fit = fit_records(training_rows, train_end)
    coefficients = {variant: fit_weights(fit, variant) for variant in VARIANTS}
    options = [(variant, blend) for variant in VARIANTS for blend in BLENDS]
    trials = [(coefficients[variant], blend) for variant, blend in options]
    with ProcessPoolExecutor(max_workers=4) as executor:
        original, scores = validation_totals(executor, validation_rows, trials)
        candidates = [dict(variant=variant, blend=blend, hits=hits)
                      for (variant, blend), hits in zip(options, scores)]
        eligible = [candidate for candidate in candidates if candidate['hits']['2t'] >= original['2t']]
        if not eligible:
            raise ValueError('No candidate preserves the original validation 2t performance.')
        chosen = max(eligible, key=lambda c: (c['hits']['3t'], c['hits']['2t'],
                                               -c['blend'], -VARIANTS.index(c['variant'])))
        groups = ('points', 'marks', 'rates', 'style') if chosen['variant'] == VARIANTS[-1] else (
            'points', 'marks', 'rates')
        controls = [(fit_weights(fit, chosen['variant'], omit=group), chosen['blend'])
                    for group in groups]
        _, control_scores = validation_totals(executor, validation_rows, controls)
    ablations = dict(zip(groups, control_scores))
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
