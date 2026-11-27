"""JSON CLI and chronological holdout evaluation for DT-R1. Research only."""
import argparse
import json
from math import log, fsum
from keirin_chat_dt_r1 import clock, digest, fit, forecast, need, validate


def evaluate(rows, fitted):
    """Require all provided rows; separately report invalid/missing examples."""
    seen=set(); held=[]; metrics={m:{k:0 for k in ks} for m,ks in [('trifecta',(1,2,4,9,12)),('exacta',(1,2))]}
    probs={m:{k:[] for k in ks} for m,ks in [('trifecta',(1,2,4,9,12)),('exacta',(1,2))]}
    losses={m:[] for m in metrics}; briers={m:[] for m in metrics}; valid=0
    for row in rows:
        rid=row.get('snapshot',{}).get('race_id')
        try:
            need(rid not in seen and rid is not None,'DUPLICATE_OR_MISSING_RACE');seen.add(rid)
            s=row['snapshot']; at=row['prediction_at']; cars=validate(s,at)
            need(clock(fitted['trained_at'])<clock(at),'NOT_STRICT_HOLDOUT')
            need(clock(row['result_at'])>clock(s['published_cutoff_at']),'RESULT_CLOCK')
            y=row['official_top3'];need(len(y)==3 and len(set(y))==3 and set(y)<=set(cars),'UNSUPPORTED_RESULT')
            f=forecast(s,at,fitted)
        except (KeyError,ValueError,TypeError,AttributeError) as e:
            held.append({'race_id':rid,'reason':str(e)});continue
        valid+=1
        for m, size in [('trifecta',3),('exacta',2)]:
            target=y[:size]; ranked=f[m]; actual=next(x['probability'] for x in ranked if x['order']==target)
            losses[m].append(-log(max(actual,1e-300)))
            briers[m].append(fsum((x['probability']-int(x['order']==target))**2 for x in ranked))
            for k in metrics[m]:
                top=ranked[:k]; hit=int(any(x['order']==target for x in top))
                metrics[m][k]+=hit;probs[m][k].append(fsum(x['probability'] for x in top))
    return {'scope':'RESEARCH_HOLDOUT_NOT_SOURCE_ATTESTED','input_sha256':digest(rows),'model_sha256':digest(fitted),
            'requested':len(rows),'evaluated':valid,'held':held,'confidence':'HOLD',
            'markets':{m:{'log_loss':fsum(losses[m])/valid if valid else None,
                          'brier':fsum(briers[m])/valid if valid else None,
                          'top_k':{k:{'hits':hits,'hit_rate':hits/valid if valid else None,
                                      'mean_raw_probability':fsum(probs[m][k])/valid if valid else None}
                                   for k,hits in metrics[m].items()}} for m in metrics}}


def load(path):
    with open(path,encoding='utf-8') as f:return json.load(f)


def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['fit','forecast','evaluate']);p.add_argument('input');p.add_argument('--at');p.add_argument('--model');a=p.parse_args()
    data=load(a.input);model=load(a.model) if a.model else None
    if a.operation=='fit':
        need(a.at is not None,'TRAINED_AT_REQUIRED');out=fit(data,a.at)
    elif a.operation=='forecast':
        need(a.at is not None,'PREDICTION_AT_REQUIRED');out=forecast(data,a.at,model)
    else:
        need(model is not None,'FITTED_MODEL_REQUIRED');out=evaluate(data,model)
    print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
