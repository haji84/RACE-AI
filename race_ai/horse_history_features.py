"""Evidence-preserving horse-history transforms for the existing four models.

This module is an input adapter, not a new forecast model. Proxy definitions are
fixed engineering hypotheses, NOT fitted/calibrated horse abilities. No network,
no implicit source authorization, no imputation, no wagering. Unknown inputs are
omitted with a reason. Original publication times are never backdated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date, timezone, timedelta
from hashlib import sha256
from itertools import permutations
import json
import math
import statistics
from typing import Callable, Any

REQUIRED = ('ability','recent_form','start_reliability','finishing_power',
            'course_compatibility','stamina','tactical_adaptability','consistency',
            'speed_figure','closing_sectional','jockey_fit','distance_surface_fit')
ENVIRONMENT = ('wind_mps','rain_mm_h','humidity_pct','air_temp_c','surface_wetness',
               'going_wetness','course_cushion','rail_position','pace_pressure')
MODEL_IDS = ('multisport-factor-interaction-v1','multisport-scenario-ensemble-v1',
             'multisport-conditional-duel-v1','multisport-race-trajectory-v1')
VERSION = 'horse-history-proxies-v1-unvalidated'
JST = timezone(timedelta(hours=9))


def digest(value: Any) -> str:
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                 ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()


def stamp(value: str) -> datetime:
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError()
        return dt
    except (TypeError,ValueError,AttributeError) as exc:
        raise ValueError('timezone-aware timestamp required') from exc


def numeric(value: Any, lo: float, hi: float, name: str) -> float:
    if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:
        raise ValueError('invalid '+name)
    return float(value)


def _validate_history(rows: list[dict], as_of: str, horse_id: str | None = None) -> list[dict]:
    clock=stamp(as_of); seen=set(); valid=[]
    for original in rows:
        r=dict(original)
        identity=(r.get('horse_id'),r.get('race_id'))
        if not all(isinstance(k,str) and k for k in identity):
            raise ValueError('stable horse and historical race identity required')
        if horse_id is not None and r['horse_id']!=horse_id: raise ValueError('horse identity mismatch')
        if identity in seen: raise ValueError('duplicate historical observation')
        seen.add(identity)
        if date.fromisoformat(r['event_date'])>=clock.astimezone(JST).date():
            raise ValueError('same-day or future history cannot be resolved before as_of')
        capture=stamp(r['captured_at'])
        if capture>clock: raise ValueError('source capture later than as_of')
        if r.get('published_at') is not None and stamp(r['published_at'])>capture:
            raise ValueError('source publication later than capture')
        if not isinstance(r.get('source_ref'),str) or not r['source_ref']:
            raise ValueError('source reference missing')
        if r.get('surface') not in ('turf','dirt','jumps') or not r.get('venue'):
            raise ValueError('historical surface/venue missing')
        numeric(r.get('distance_m'),100,10000,'distance')
        n=r.get('field_size')
        if type(n) is not int or not 2<=n<=40: raise ValueError('invalid field size')
        state=r.get('status')
        if state not in ('FINISHED','DNF','DISQUALIFIED','WITHDRAWN','CANCELLED'):
            raise ValueError('explicit finish status required')
        pos=r.get('finish_position')
        if state=='FINISHED':
            if type(pos) is not int or not 1<=pos<=n: raise ValueError('invalid finish position')
        elif pos is not None:
            raise ValueError('nonfinish must not masquerade as a numeric placing')
        for k in ('first_corner_position','last_corner_position','last3f_rank'):
            if r.get(k) is not None and (type(r[k]) is not int or not 1<=r[k]<=n):
                raise ValueError('invalid '+k)
        for k in ('elapsed_seconds','last3f_seconds'):
            if r.get(k) is not None: numeric(r[k],.001,1500,k)
        if r.get('start_incident') is not None and type(r['start_incident']) is not bool:
            raise ValueError('start incident must be observed bool, not absence of a comment')
        valid.append(r)
    return sorted(valid,key=lambda r:(r['event_date'],r['race_id']),reverse=True)


def fit_reference(rows: list[dict], *, fitted_at: str, data_captured_at: str,
                  allow_source: Callable | None = None,
                  scope: str = 'OPERATOR_SUPPLIED_RESEARCH') -> dict:
    """Freeze TRAIN-only speed baselines. No hypothetical or target-race data."""
    if scope not in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH'):
        raise ValueError('invalid reference scope')
    if stamp(data_captured_at)>stamp(fitted_at): raise ValueError('reference capture after fitting')
    checked=_validate_history(rows,data_captured_at)
    if not checked: raise ValueError('training reference is empty')
    if scope!='SYNTHETIC_ONLY':
        if not callable(allow_source) or any(
            allow_source(r['source_ref'],r.get('source_rights_ref'),'analysis') is not True for r in checked):
            raise ValueError('independent training-source authorizer required')
    artifact={'schema':'HORSE_TRAIN_REFERENCE_V1','scope':scope,'fitted_at':fitted_at,
              'captured_at':data_captured_at,'records':checked,'role':'TRAIN',
              'method_status':'UNVALIDATED_REFERENCE_DISTRIBUTION'}
    artifact['sha256']=digest(artifact)
    return artifact


def _performance(r: dict) -> float:
    return 1-(r['finish_position']-1)/(r['field_size']-1)


def _style(r: dict) -> str | None:
    if r.get('first_corner_position') is None: return None
    x=(r['first_corner_position']-1)/(r['field_size']-1)
    return 'front' if x<=.25 else 'stalker' if x<=.60 else 'closer'


def derive(rows: list[dict], target: dict, *, as_of: str, reference: dict | None = None,
           distance_band_m: int = 200, scope: str = 'OPERATOR_SUPPLIED_RESEARCH') -> dict:
    """Produce actual calculable observations, lineage, and explicit omissions.

    ability/course/jockey/distance/stamina are finish-percentile proxies, not
    measurements of a latent biological ability. Class, race pace and track
    variants are NOT corrected. Single-start certainty is never asserted.
    """
    if scope not in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH'):
        raise ValueError('invalid derived-data scope')
    if reference is not None and reference.get('scope')!=scope:
        raise ValueError('reference/derived scope mismatch')
    if not target.get('horse_id') or target.get('surface') not in ('turf','dirt','jumps'):
        raise ValueError('target identity and surface required')
    numeric(target.get('distance_m'),100,10000,'target distance')
    numeric(distance_band_m,0,1000,'distance band')
    checked=_validate_history(rows,as_of,target['horse_id'])
    finished=[r for r in checked if r['status']=='FINISHED']
    comparable=[r for r in finished if r['surface']==target['surface']]
    features={}; missing={}; lineage={}; bounds={}

    def add(name, values, used, *, min_n=1, compute=None, note=''):
        if len(values)<min_n:
            missing[name]=note or 'INSUFFICIENT_OBSERVED_SUPPORT'
            return
        v=compute(values) if compute else statistics.fmean(values)
        v=numeric(v,0,1,name)
        sources=[{k:r.get(k) for k in ('horse_id','race_id','event_date','source_ref',
                    'published_at','captured_at','source_rights_ref','sectional_source_ref')} for r in used]
        key='derived:'+digest({'method':VERSION,'feature':name,'sources':sources,
                              'target':target,'value':v,'reference':reference.get('sha256') if reference else None})
        lineage[key]=sources
        features[name]={'value':v,'published_at':as_of,'captured_at':as_of,
                        'source_ref':key,'source_rights_ref':'derived-lineage:'+VERSION,
                        'sample_n':len(values),'transform_id':VERSION+':'+name}
        bounds[name]={'support_n':len(values),'reference_n':0,
                      'interpretation':'UNVALIDATED_OBSERVATIONAL_PROXY'}

    add('ability',[_performance(r) for r in comparable],comparable)
    recent=comparable[:3]
    add('recent_form',[_performance(r) for r in recent],recent,
        compute=lambda x:sum(v*(len(x)-i) for i,v in enumerate(x))/sum(range(1,len(x)+1)))
    starts=[r for r in checked if r['status'] not in ('WITHDRAWN','CANCELLED') and
            r['surface']==target['surface'] and type(r.get('start_incident')) is bool]
    add('start_reliability',[1-float(r['start_incident']) for r in starts],starts,
        note='OBSERVED_START_INCIDENT_FLAGS_REQUIRED')
    moves=[r for r in comparable if r.get('last_corner_position') is not None]
    add('finishing_power',[.5+.5*(r['last_corner_position']-r['finish_position'])/(r['field_size']-1)
                          for r in moves],moves,note='LAST_CORNER_POSITION_REQUIRED')
    course=[r for r in comparable if r['venue']==target.get('venue')]
    add('course_compatibility',[_performance(r) for r in course],course,
        note='NO_OBSERVED_SAME_VENUE_SURFACE_START')
    long=[r for r in comparable if r['distance_m']>=target['distance_m']]
    add('stamina',[_performance(r) for r in long],long,note='NO_OBSERVED_TARGET_OR_LONGER_DISTANCE')
    by_style=defaultdict(list)
    for r in comparable:
        s=_style(r)
        if s is not None:by_style[s].append(r)
    if len(by_style)>=2:
        # Average the represented regime means; no extrapolation to unobserved styles.
        flat=[r for vals in by_style.values() for r in vals]
        vals=[statistics.fmean(_performance(r) for r in batch) for batch in by_style.values()]
        add('tactical_adaptability',vals,flat,min_n=2)
        features['tactical_adaptability']['sample_n']=len(flat)
        bounds['tactical_adaptability']['support_n']=len(flat)
        bounds['tactical_adaptability']['observed_regimes']=len(by_style)
    else:missing['tactical_adaptability']='AT_LEAST_TWO_OBSERVED_POSITION_REGIMES_REQUIRED'
    add('consistency',[_performance(r) for r in comparable],comparable,min_n=2,
        compute=lambda x:max(0.,min(1.,1-2*statistics.pstdev(x))),
        note='AT_LEAST_TWO_FINISHED_STARTS_REQUIRED')

    reference_rows=[]
    if reference is not None:
        if reference.get('sha256')!=digest({k:v for k,v in reference.items() if k!='sha256'}):
            raise ValueError('reference hash mismatch')
        if reference.get('role')!='TRAIN' or stamp(reference['fitted_at'])>=stamp(as_of):
            raise ValueError('reference is not a prior TRAIN artifact')
        reference_rows=_validate_history(reference['records'],reference['captured_at'])
        current={(r['horse_id'],r['race_id']) for r in checked}
        if current.intersection((r['horse_id'],r['race_id']) for r in reference_rows):
            raise ValueError('reference overlaps target historical observations')

    speeds=[];speed_rows=[];baseline_used=[]
    for r in comparable:
        pool=[b for b in reference_rows if b['status']=='FINISHED' and b['surface']==r['surface'] and
              b['distance_m']==r['distance_m'] and b.get('elapsed_seconds') is not None]
        if r.get('elapsed_seconds') is not None and len(pool)>=2:
            v=r['distance_m']/r['elapsed_seconds']
            bvals=[b['distance_m']/b['elapsed_seconds'] for b in pool]
            speeds.append((sum(x<v for x in bvals)+.5*sum(x==v for x in bvals))/len(bvals))
            speed_rows.append(r);baseline_used.extend(pool)
    add('speed_figure',speeds,speed_rows+baseline_used,note='DISJOINT_PRIOR_TRAIN_SPEED_REFERENCE_REQUIRED')
    if speeds:bounds['speed_figure']['reference_n']=len({(r['horse_id'],r['race_id']) for r in baseline_used})
    sections=[r for r in comparable if r.get('last3f_rank') is not None]
    add('closing_sectional',[1-(r['last3f_rank']-1)/(r['field_size']-1) for r in sections],sections,
        note='OBSERVED_WITHIN_RACE_LAST3F_RANK_REQUIRED')
    jockey=[r for r in comparable if target.get('jockey_id') and r.get('jockey_id')==target['jockey_id']]
    add('jockey_fit',[_performance(r) for r in jockey],jockey,note='CONFIRMED_CURRENT_JOCKEY_AND_PAST_PAIR_REQUIRED')
    distances=[r for r in comparable if abs(r['distance_m']-target['distance_m'])<=distance_band_m]
    add('distance_surface_fit',[_performance(r) for r in distances],distances,
        note='NO_OBSERVED_NEARBY_DISTANCE_SURFACE_START')
    report={'scope':scope,'schema':'HORSE_HISTORY_DERIVED_V1','horse_id':target['horse_id'],'target':dict(target),
            'as_of':as_of,'transform_version':VERSION,'method_status':'UNVALIDATED_RESEARCH_TRANSFORM',
            'features':features,'missing':missing,'lineage':lineage,'support':bounds,
            'source_rows':len(checked),'finished_rows':len(finished),
            'nonfinish_count':sum(r['status'] in ('DNF','DISQUALIFIED') for r in checked),
            'withdrawn_count':sum(r['status'] in ('WITHDRAWN','CANCELLED') for r in checked),
            'raw_history_sha256':digest(rows),'reference_sha256':reference.get('sha256') if reference else None,
            'independent_source_authorization_verified':False,'formal_model_ready':False}
    report['sha256']=digest(report)
    return report


def build_snapshot(race: dict, entrants: list[dict], environment: dict, *, as_of: str,
                   scope='OPERATOR_SUPPLIED_RESEARCH') -> dict:
    """Assemble the original schema; no defaults for missing draw/environment."""
    if race.get('discipline')!='flat': raise ValueError('unvalidated jumping discipline')
    if race.get('surface')=='dirt':
        raise ValueError('native horse schema requires turf cushion for dirt; no fabricated substitution')
    if scope not in ('SYNTHETIC_ONLY','OPERATOR_SUPPLIED_RESEARCH'): raise ValueError('scope')
    keys=('race_id','sport','venue','event_date_jst','sales_cutoff_at','distance_m','surface','race_kind','race_revision')
    if any(k not in race for k in keys) or race.get('sport')!='horse': raise ValueError('native race metadata incomplete')
    if not 3<=len(entrants)<=18: raise ValueError('horse field size')
    if set(environment)!=set(ENVIRONMENT): raise ValueError('environment incomplete')
    if stamp(as_of)>=stamp(race['sales_cutoff_at']): raise ValueError('past cutoff')
    if stamp(race['sales_cutoff_at']).astimezone(JST).date().isoformat()!=race['event_date_jst']:
        raise ValueError('cutoff date mismatch')
    participants=[];seen=set()
    for e in entrants:
        report=e['report']
        if report.get('sha256')!=digest({k:v for k,v in report.items() if k!='sha256'}): raise ValueError('derived report hash mismatch')
        if report.get('scope')!=scope:raise ValueError('derived/native scope mismatch')
        if report.get('horse_id')!=e.get('horse_id') or stamp(report['as_of'])>stamp(as_of): raise ValueError('horse evidence identity/time')
        if set(report['features'])!=set(REQUIRED): raise ValueError('mandatory features missing')
        if report['target']['venue']!=race['venue'] or report['target']['surface']!=race['surface'] or report['target']['distance_m']!=race['distance_m']:
            raise ValueError('feature target/race mismatch')
        if type(e.get('number')) is not int or not 1<=e['number']<=99 or e['number'] in seen:
            raise ValueError('confirmed distinct horse numbers required')
        if type(e.get('draw')) is not int or not 1<=e['draw']<=len(entrants): raise ValueError('actual draw missing')
        if e.get('style') not in ('front','stalker','closer','allround','unknown'): raise ValueError('style')
        seen.add(e['number'])
        participants.append({'number':e['number'],'identity':e['horse_id'],'draw':e['draw'],
                            'style':e['style'],'group_id':None,'features':report['features']})
    return {'schema':'RACE_AI_FOUR_SPORT_EVIDENCED_SNAPSHOT_V1','scope':scope,
            'race':{**{k:race[k] for k in keys},'as_of':as_of},
            'participants':participants,'environment':environment}


def run_existing_four(snapshot: dict, *, allow_source=None) -> dict:
    """Original suite entry point. Never bypass its authorization/validation."""
    from .four_sport_model_suite import run_suite, verify_suite
    native=run_suite(snapshot,allow_source=allow_source)
    if not verify_suite(native):raise ValueError('native suite verification failed')
    return {'native_suite':native,'summary':summarize_suite(native)}


def summarize_suite(suite: dict) -> dict:
    """Output every horse's marginal MODEL SCORE and all four original Top8s."""
    if tuple(suite.get('models',{}))!=MODEL_IDS:raise ValueError('original four-model roster required')
    if suite.get('suite_sha256')!=digest({k:v for k,v in suite.items() if k!='suite_sha256'}):
        raise ValueError('suite hash mismatch')
    if suite.get('official_prediction') is not False:raise ValueError('research suite only')
    summaries={};universe=None
    for name,p in suite['models'].items():
        if p.get('prediction_sha256')!=digest({k:v for k,v in p.items() if k!='prediction_sha256'}):raise ValueError('native prediction hash')
        if p.get('snapshot_sha256',p.get('input_sha256'))!=suite['input_sha256']:raise ValueError('different input snapshots')
        candidates=p['candidates'];by_combo={};win=defaultdict(float);place=defaultdict(float)
        for row in candidates:
            c=tuple(row['combination']);v=numeric(row['score'],0,1,'model score')
            if len(c)!=3 or len(set(c))!=3 or c in by_combo:raise ValueError('invalid/duplicate trifecta')
            by_combo[c]=v;win[c[0]]+=v
            for h in c:place[h]+=v
        ids=set(win)
        if set(by_combo)!=set(permutations(sorted(ids),3)) or not math.isclose(sum(by_combo.values()),1.,abs_tol=1e-9):
            raise ValueError('incomplete distribution')
        if universe is not None and universe!=set(by_combo):raise ValueError('different entrant universes')
        universe=set(by_combo)
        expected=sorted(by_combo,key=lambda c:(-by_combo[c],c))[:8]
        if [tuple(x) for x in p['ordered_top8']]!=expected:raise ValueError('Top8 differs from original ranking')
        summaries[name]={'win_score_by_horse':dict(sorted(win.items())),
                         'top3_score_by_horse':dict(sorted(place.items())),
                         'ordered_top8':p['ordered_top8'],
                         'top8_score_sum':sum(by_combo[c] for c in expected),
                         'prediction_sha256':p['prediction_sha256'],
                         'calibrated_win_probability':None}
    tops={name:max(v['win_score_by_horse'],key=v['win_score_by_horse'].get) for name,v in summaries.items()}
    counts={h:sum(x==h for x in tops.values()) for h in sorted(set(tops.values()))}
    return {'models':summaries,'top_horse_votes':counts,'input_sha256':suite['input_sha256'],
            'same_data_models_not_independent':True,'confidence':None,'expected_value':None,
            'interpretation':'UNTRAINED_UNCALIBRATED_MODEL_SCORES_NOT_EMPIRICAL_WIN_PROBABILITIES'}


def quote_ev(probability: float, decimal_odds: float, *, calibrated: bool) -> dict:
    """Conditional arithmetic only; odds source/time and calibration supplied externally."""
    if calibrated is not True:raise ValueError('calibrated probability is required for a betting EV claim')
    p=numeric(probability,0,1,'probability');o=numeric(decimal_odds,1,1e9,'actual decimal odds')
    return {'gross_return_per_unit':p*o,'net_return_per_unit':p*o-1,
            'assumes_quoted_odds_are_final':True,'not_a_purchase_instruction':True}
