"""Independent DT-R1 v0: trainable latent-scenario rank model, not physical telemetry.
Only Python stdlib; input is a pre-race facts snapshot, never a rival prediction.
The six stages are latent utility states, not measured locations or joules.
"""
from datetime import datetime
from hashlib import sha256
from itertools import permutations, product
from math import exp, fsum, isfinite, log, sqrt
import json

MODEL = 'chat-dt-r1-v0'
PHASES = ('INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER', 'GOAL')
DEFAULT = {'strength': 1.0, 'line': 0.6, 'fatigue': 0.4, 'temperature': 1.0}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def clock(s):
    t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    need(t.utcoffset() is not None, 'TIMEZONE_REQUIRED')
    return t


def digest(obj):
    return sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode()).hexdigest()


def validate(s, at):
    t, cutoff = clock(at), clock(s['published_cutoff_at'])
    need(clock(s['as_of']) <= t and (cutoff-t).total_seconds() >= 900, 'PRE_CUTOFF_REQUIRED')
    riders = s['riders']; cars = [r['car'] for r in riders]
    need(3 <= len(cars) <= 9 and len(set(cars)) == len(cars) and
         all(type(c) is int and 1 <= c <= 9 for c in cars), 'ROSTER')
    groups = s['line_groups']
    need(all(groups) and sorted(c for g in groups for c in g) == sorted(cars), 'LINE_PARTITION')
    need(s.get('competition') != 'GIRLS' or all(len(g)==1 for g in groups), 'GIRLS_LINES')
    for r in riders:
        for k, lo, hi in [('competition_points',0,150), ('recent_form_score',0,1), ('h_count',0,99), ('b_count',0,99)]:
            v=r[k]; need(type(v) in (float,int) and isfinite(v) and lo<=v<=hi, 'RIDER_FEATURE')
    return sorted(cars)


def norm(weights):
    m = max(weights.values()); a = {k: exp(v-m) for k,v in weights.items()}; z=fsum(a.values())
    return {k:v/z for k,v in a.items()}


def scenarios(s, p):
    """Enumerate alternative main lines; six latent utility states per branch."""
    riders={r['car']:r for r in s['riders']}; groups=s['line_groups']; cars=sorted(riders)
    points=[r['competition_points'] for r in riders.values()]; avg=fsum(points)/len(points)
    scale=max(3.0,sqrt(fsum((v-avg)**2 for v in points)/len(points)))
    strength={c:p['strength']*((r['competition_points']-avg)/scale + .6*(r['recent_form_score']-.5)) for c,r in riders.items()}
    drive={c: log(1+r['h_count']+r['b_count'])/log(199) for c,r in riders.items()}
    # The hypotheses below are priors, not physiological measurements.
    priors=norm({i: .7*strength[g[0]]+1.4*drive[g[0]] for i,g in enumerate(groups)})
    for i, g in enumerate(groups):
        front=g[0]; state={c:0.0 for c in cars}; fatigue={c:0.0 for c in cars}; phases=[]
        for j, phase in enumerate(PHASES):
            progress=j/5
            for c in cars:
                in_line=c in g; follower=in_line and c!=front
                attack=drive[c] if c==front else (.35*drive[c] if not in_line else .1*drive[c])
                fatigue[c]+=attack*(1 if j>=1 else 0)/5
                kick=.28 if riders[c].get('style') in ('MAKURI','SASHI') else 0.0
                line_effect=(.9 if c==front else .6/(g.index(c)) if follower else 0.0)
                state[c]=strength[c]+p['line']*line_effect*(.3+.7*progress)-p['fatigue']*fatigue[c]+kick*progress**3
            phases.append({'phase':phase,'latent_order':sorted(cars,key=lambda c:(-state[c],c))})
        yield priors[i], norm({c:state[c]/p['temperature'] for c in cars}), phases


def distribution(s, p):
    """Mixture of coherent Plackett-Luce top-3 distributions, exact enumeration."""
    need(set(p)==set(DEFAULT) and all(type(v) in (int,float) and isfinite(v) and v>0 for v in p.values()), 'PARAMETERS')
    cars=sorted(r['car'] for r in s['riders']); mass={t:0.0 for t in permutations(cars,3)}; branches=[]
    for q, w, phases in scenarios(s,p):
        branches.append({'weight':q,'phases':phases})
        for a,b,c in mass:
            mass[a,b,c]+=q*w[a]*w[b]/fsum(w[x] for x in cars if x!=a)*w[c]/fsum(w[x] for x in cars if x not in (a,b))
    z=fsum(mass.values()); return {t:v/z for t,v in mass.items()},branches


def fit(rows, trained_at):
    """Grid fit on past source snapshots + unique official top3; no future labels.
    Caller must independently authenticate snapshot/result source receipts.
    """
    t=clock(trained_at); need(len(rows)>=30, 'TRAINING_MINIMUM_30_NOT_CERTIFICATION')
    seen=set()
    for row in rows:
        s=row['snapshot']; cars=validate(s,row['prediction_at']); y=tuple(row['official_top3'])
        need(s['race_id'] not in seen and len(y)==3 and len(set(y))==3 and set(y)<=set(cars), 'TRAINING_ID_OR_RESULT')
        need(clock(s['published_cutoff_at']) < clock(row['result_at']) <= t, 'FUTURE_RESULT')
        seen.add(s['race_id'])
    best=None
    for strength,line,fatigue,temp in product((.5,1.,1.5),(.2,.6,1.),(.15,.4,.8),(.7,1.,1.4)):
        p=dict(strength=strength,line=line,fatigue=fatigue,temperature=temp)
        loss=0.0
        for r in rows:
            y=tuple(r['official_top3']); a,b,c=y; cars=[x['car'] for x in r['snapshot']['riders']]
            prob=fsum(q*w[a]*w[b]/fsum(w[x] for x in cars if x!=a)*w[c]/fsum(w[x] for x in cars if x not in (a,b)) for q,w,_ in scenarios(r['snapshot'],p))
            loss-=log(max(prob,1e-300))
        loss/=len(rows)
        if best is None or loss<best[0]: best=(loss,p)
    return {'model':MODEL,'trained_at':trained_at,'n':len(rows),'training_log_loss':best[0], 'params':best[1], 'training_sha256':digest(rows)}


def forecast(s, at, fitted=None):
    cars=validate(s,at)
    if fitted is not None:
        need(fitted['model']==MODEL and clock(fitted['trained_at'])<=clock(at), 'MODEL_FROM_FUTURE')
    p=DEFAULT if fitted is None else fitted['params']; mass,branches=distribution(s,p)
    exacta={t:0.0 for t in permutations(cars,2)}
    for t,v in mass.items(): exacta[t[:2]]+=v
    def ranked(d): return [{'order':list(k),'probability':v} for k,v in sorted(d.items(),key=lambda kv:(-kv[1],kv[0]))]
    return {'model':MODEL,'race_id':s['race_id'],'prediction_at':at,'input_sha256':digest(s),
            'model_sha256':digest(fitted if fitted is not None else DEFAULT),
            'status':'UNVALIDATED_FITTED' if fitted else 'UNTRAINED_PRIOR', 'confidence':'HOLD',
            'trifecta':ranked(mass),'exacta':ranked(exacta),'branches':branches,
            'missing_modules':['observed_phase_labels','verified_lap_times','venue_geometry','weather','measured_energy','probability_calibration'],
            'scope':'RESEARCH_ONLY_NO_OFFICIAL_ATTESTATION'}
