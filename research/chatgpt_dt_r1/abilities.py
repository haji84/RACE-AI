"""Five-ability extension: prior evidence, competitive pressure, dynamic states,
failure sensitivity and bounded training-only discovery.

All "load" values are dimensionless proxies, not measured human energy or
causal race outcomes. No invented video measurements or current-race results.
The existing ranker, time gates, independent support and original ledger remain
the authorities. Old feature schemas remain readable.
"""
from __future__ import annotations
from collections import defaultdict
from itertools import combinations
from zoneinfo import ZoneInfo
import re
import numpy as np
from .features import _bind_feature_input
from .model import _verify_feature_binding, digest, RankModel
from .observations import Provenance, SourceKind, utc, day, finite

VERSION = 'dt-five-abilities-v1'
MOTION_SCHEMA = 'dt-reviewed-motion-v2'
LEGACY_MOTION_SCHEMA = 'dt-reviewed-motion-v1'
PREFIX = 'history_dt_'
DISC = PREFIX + 'discovery_'
# Bounds are validation limits, not population statistics. Units are explicit.
MOTION = {'mean_speed_m_s': (0,40,20), 'max_speed_m_s': (0,40,20),
          'mean_acceleration_m_s2': (-20,20,5), 'speed_retention_ratio': (0,2,1),
          'exposed_fraction': (0,1,1), 'extra_distance_m': (0,1000,100),
          'tactical_success_fraction': (0,1,1), 'attack_count': (0,30,10)}
MEASURED_METRICS = {'mean_speed_m_s':'measured_speed_mean_m_s',
                   'max_speed_m_s':'measured_speed_max_m_s',
                   'mean_acceleration_m_s2':'measured_acceleration_mean_m_s2'}
MEASUREMENT_FIELDS = ('measured_motion_segments', 'measured_speed_uncertainty_m_s',
                      *MEASURED_METRICS.values(), 'measured_acceleration_uncertainty_m_s2')
CORE = ('form_change','form_change_known','recent_load_proxy','recent_load_known',
        'rival_pressure','rival_pressure_known','rival_strength_gap','rival_strength_known',
        'third_line_opportunity','third_line_known','line_front_exposure_proxy',
        'line_shelter_proxy','line_state_known','load_x_pressure','agari_x_pressure',
        'weather_load_proxy','weather_load_known')
MOTION_NAMES = tuple(PREFIX+'motion_'+scope+'_'+m+'_'+s
    for scope in ('overall','venue') for m in MOTION for s in ('mean','std','count','missing'))
DISC_INPUTS = ('history_agari_venue_relative','history_agari_overall_relative',
    'history_form_relative','history_b_rate','history_s_rate','history_rest_days_log',
    'line_size_fraction','line_predecessor_points_gap','points_relative',
    PREFIX+'rival_pressure',PREFIX+'third_line_opportunity',PREFIX+'recent_load_proxy')
DISC_PAIRS = tuple(combinations(DISC_INPUTS,2))
DISC_NAMES = tuple(DISC+str(i).zfill(2) for i in range(len(DISC_PAIRS)))
ABILITY_NAMES = tuple(PREFIX+k for k in CORE) + MOTION_NAMES + DISC_NAMES
DISCOVERY_CONFIG = {'max_features':12,'min_variable_races_per_half':100,
    'method':'within-race centered association with first-place label; require same sign in two chronological halves',
    'pool':{n:list(p) for n,p in zip(DISC_NAMES,DISC_PAIRS)},'selection_uses':'fit only'}


def uses_abilities(names):
    return any(n.startswith(PREFIX) for n in names)


def _sha(v):
    return isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) is not None


def _measured_metrics(evidence):
    """Validate the same calibrated evidence at creation and serialized reload."""
    if not isinstance(evidence,dict) or set(evidence)!=set(MEASUREMENT_FIELDS):
        raise ValueError('MOTION_MEASUREMENT_EVIDENCE_REQUIRED')
    segments=evidence['measured_motion_segments']
    if type(segments) is not int or segments<1:
        raise ValueError('CALIBRATED_MOTION_SEGMENTS_REQUIRED')
    finite(evidence['measured_speed_uncertainty_m_s'],'motion uncertainty',low=0,high=5)
    values={}
    for dest,src in MEASURED_METRICS.items():
        value=evidence[src]
        if dest=='mean_acceleration_m_s2' and value is None:
            continue
        lo,hi,_=MOTION[dest]
        finite(value,dest,low=lo,high=hi)
        if dest=='mean_acceleration_m_s2':
            if segments<2:
                raise ValueError('CALIBRATED_ACCELERATION_SEGMENTS_REQUIRED')
            finite(evidence['measured_acceleration_uncertainty_m_s2'],
                   'acceleration uncertainty',low=0,high=5)
        values[dest]=value
    if values['max_speed_m_s']<values['mean_speed_m_s']:
        raise ValueError('MOTION_SPEED_SUMMARY_INVALID')
    return values


def reviewed_motion_record(measurements, *, race_id, rider_id, registration_id, venue_id,
                           event_at, event_day, provenance, identity_receipt_sha256,
                           measurement_receipt_sha256, extra=None):
    """Adapter from observations.motion_features calibrated metre measurements.
    Review receipts bind identity/calibration externally; this is not authentication.
    Never accept pixel speeds or uncalibrated estimates as metre data.
    """
    if not _sha(identity_receipt_sha256) or not _sha(measurement_receipt_sha256):
        raise ValueError('MOTION_REVIEW_RECEIPTS_REQUIRED')
    p=Provenance(**provenance)
    if p.kind != SourceKind.REVIEWED_VIDEO:
        raise ValueError('REVIEWED_VIDEO_REQUIRED')
    evidence={key:measurements.get(key) for key in MEASUREMENT_FIELDS}
    values=_measured_metrics(evidence)
    if extra:
        if set(extra)&set(MEASURED_METRICS):
            raise ValueError('MOTION_METRIC_REQUIRES_MEASUREMENT_EVIDENCE')
        values.update(extra)
    result={'schema':MOTION_SCHEMA,'race_id':race_id,'rider_id':rider_id,'registration_id':registration_id,
            'venue_id':venue_id,'event_at':event_at,'event_day':event_day,'provenance':provenance,
            'identity_receipt_sha256':identity_receipt_sha256,'measurement_receipt_sha256':measurement_receipt_sha256,
            'measurement_evidence':evidence,'metrics':values}
    result['observation_id']=digest(result)
    validate_motion(result)
    return result


def validate_motion(record):
    if record.get('schema')==LEGACY_MOTION_SCHEMA:
        # The old shape did not retain quality evidence. Never invent it or
        # silently rewrite an original into the new reviewed format.
        raise ValueError('LEGACY_MOTION_REVIEW_REQUIRED')
    required={'schema','race_id','rider_id','registration_id','venue_id','event_at','event_day','provenance',
              'identity_receipt_sha256','measurement_receipt_sha256','measurement_evidence','metrics','observation_id'}
    if set(record)!=required or record['schema']!=MOTION_SCHEMA:
        raise ValueError('MOTION_SCHEMA_INVALID')
    if not all(isinstance(record[k],str) and record[k] for k in ('race_id','rider_id','registration_id','venue_id')):
        raise ValueError('MOTION_IDENTITY_REQUIRED')
    if not all(_sha(record[k]) for k in ('identity_receipt_sha256','measurement_receipt_sha256','observation_id')):
        raise ValueError('MOTION_REVIEW_RECEIPTS_REQUIRED')
    if digest({k:v for k,v in record.items() if k!='observation_id'})!=record['observation_id']:
        raise ValueError('MOTION_RECORD_HASH_MISMATCH')
    p=Provenance(**record['provenance'])
    if p.kind != SourceKind.REVIEWED_VIDEO:
        raise ValueError('REVIEWED_VIDEO_REQUIRED')
    event=utc(record['event_at'])
    if event.astimezone(ZoneInfo('Asia/Tokyo')).date()!=day(record['event_day']) or event>utc(p.retrieved_at):
        raise ValueError('MOTION_EVENT_CLOCK_INVALID')
    metrics=record['metrics']
    if not isinstance(metrics,dict) or not metrics or not set(metrics)<=set(MOTION):
        raise ValueError('MOTION_METRICS_INVALID')
    for k,v in metrics.items():
        lo,hi,_=MOTION[k]
        finite(v,k,low=lo,high=hi)
    measured=_measured_metrics(record['measurement_evidence'])
    if {k:v for k,v in metrics.items() if k in MEASURED_METRICS}!=measured:
        raise ValueError('MOTION_MEASUREMENT_MISMATCH')
    return record


def split_sidecars(records):
    timing=[]; motion=[]
    for record in records:
        if isinstance(record,dict) and record.get('schema') in (MOTION_SCHEMA,LEGACY_MOTION_SCHEMA):
            motion.append(validate_motion(record))
        else:
            timing.append(record)
    # A duplicate rider/race observation needs explicit review rather than
    # counting two camera clips as two performances.
    keys=[(r['race_id'],r['rider_id']) for r in motion]
    if len(set(keys))!=len(keys):
        raise ValueError('DUPLICATE_MOTION_RACE_RIDER')
    return timing,motion


def motion_history(row, records, as_of):
    """Strict prior-day, exact registration, source-available reviewed history."""
    target_day=day(row['day']); limit=utc(as_of)
    admitted={}
    for rider in row['riders']:
        registration=rider.get('official_registration_id')
        if rider.get('identity_usable') is not True or not registration:
            continue
        identity=rider.get('identity_key',rider.get('athlete_id'))
        selected=[r for r in records if r['rider_id']==str(identity) and
            r['registration_id']==str(registration) and r['race_id']!=row['race_id'] and
            day(r['event_day'])<target_day and utc(r['event_at'])<limit and
            utc(r['provenance']['available_at'])<=limit]
        selected.sort(key=lambda r:(utc(r['event_at']),r['race_id']))
        stats={}
        for scope,source in (('overall',selected),('venue',[r for r in selected if r['venue_id']==str(row.get('venue_code'))])):
            for metric,(_,_,scale) in MOTION.items():
                vals=[r['metrics'][metric]/scale for r in source if metric in r['metrics']][-20:]
                key=scope+'_'+metric
                stats[key]={'mean':float(np.mean(vals)) if vals else 0.,
                    'std':float(np.std(vals)) if vals else 0.,'count':len(vals)/20.,'missing':float(not vals)}
        if selected:
            admitted[str(rider['car'])]={'stats':stats,'records_sha256':digest(selected),'count':len(selected)}
    return admitted


def augment_abilities(rows):
    out=[]
    for original in rows:
        _verify_feature_binding(original)
        names=tuple(original['feature_names'])
        if uses_abilities(names):
            raise ValueError('ABILITIES_ALREADY_ATTACHED')
        row=dict(original); x=np.asarray(row['features'],dtype=float); n=len(x)
        cols={name:x[:,i] for i,name in enumerate(names)}; zero=np.zeros(n)
        def c(name): return cols.get(name,zero)
        ready=row.get('feature_status')=='READY'
        history=(c('history_missing')==0)&(c('history_count_last5')>0)&ready
        bknown=(c('history_sb_missing')==0)&(c('history_entries_log')>0)&ready
        restknown=(c('history_rest_missing')==0)&ready
        form=np.where(history,c('history_form_last5')-c('history_form_last30'),0.)
        load=np.where(restknown,c('history_starts_7d')*(1-c('history_rest_days_log')),0.)
        lineknown=ready and n>0 and np.all(c('line_known')>.5)
        cars=[r['car'] for r in row['riders']]; idx={car:i for i,car in enumerate(cars)}
        groups=row.get('line_groups') or []
        groups=groups if lineknown else []
        fronts=[idx[g[0]] for g in groups]
        vals={k:zero.copy() for k in CORE}
        vals.update(form_change=form,form_change_known=history.astype(float),
                    recent_load_proxy=load,recent_load_known=restknown.astype(float))
        if lineknown:
            for g in groups:
                lead=idx[g[0]]; others=[j for j in fronts if j!=lead]
                observed=[j for j in others if bknown[j]]
                known_points=[j for j in others if c('points_missing')[j]==0]
                for pos,car in enumerate(g):
                    i=idx[car]
                    vals['line_state_known'][i]=1.
                    vals['line_front_exposure_proxy'][i]=float(pos==0)
                    vals['line_shelter_proxy'][i]=float(pos>0)
                    if observed and bknown[lead]:
                        pressure=float(c('history_b_rate')[lead]*sum(c('history_b_rate')[j] for j in observed))
                        vals['rival_pressure'][i]=pressure; vals['rival_pressure_known'][i]=1.
                    if known_points and c('points_missing')[lead]==0:
                        vals['rival_strength_gap'][i]=max(c('points_relative')[j] for j in known_points)-c('points_relative')[lead]
                        vals['rival_strength_known'][i]=1.
                    if len(observed)>=2 and len(known_points)>=2:
                        candidates=sorted((j for j in observed if j in known_points),key=lambda j:(-c('points_relative')[j],j))
                        if len(candidates)>=2:
                            a,z=candidates[:2]
                            vals['third_line_opportunity'][i]=(c('history_b_rate')[a]*c('history_b_rate')[z]/
                                (1+abs(c('points_relative')[a]-c('points_relative')[z])))
                            vals['third_line_known'][i]=1.
        vals['load_x_pressure']=load*vals['rival_pressure']
        vals['agari_x_pressure']=c('history_agari_venue_relative')*vals['rival_pressure']
        if 'context_weather_wind_speed_m_s_missing' in cols:
            wk=(c('context_weather_wind_speed_m_s_missing')==0)&(vals['line_state_known']>0)
            vals['weather_load_known']=wk.astype(float)
            vals['weather_load_proxy']=np.where(wk,c('context_weather_wind_speed_m_s')*vals['line_front_exposure_proxy'],0.)
        motion=row['history_evidence'].get('reviewed_motion',{})
        motion_columns=[]
        for scope in ('overall','venue'):
            for metric in MOTION:
                for stat in ('mean','std','count','missing'):
                    motion_columns.append(np.array([motion.get(str(car),{}).get('stats',{}).get(scope+'_'+metric,{}).get(stat,float(stat=='missing')) for car in cars],dtype=float))
        allcols=dict(cols);allcols.update({PREFIX+k:v for k,v in vals.items()})
        derived=[allcols.get(a,zero)*allcols.get(z,zero) for a,z in DISC_PAIRS]
        extra=np.column_stack([vals[k] for k in CORE]+motion_columns+derived)
        if extra.shape!=(n,len(ABILITY_NAMES)) or not np.isfinite(extra).all():
            raise ValueError('ABILITIES_FEATURE_MATRIX_INVALID')
        row['features']=np.concatenate((x,extra),axis=1)
        row['feature_names']=names+ABILITY_NAMES
        row['feature_version']=row['feature_version']+'+'+VERSION
        row['history_evidence']=dict(row['history_evidence'],five_abilities={
            'version':VERSION,'reviewed_motion_riders':len(motion),
            'competition_proxy_riders':int(vals['rival_pressure_known'].sum()),
            'physical_energy_measured':False})
        out.append(_bind_feature_input(row))
    return out


def discover_features(rows, *, before, min_races=100, max_features=12):
    """Generate a bounded discovery mask using only training-period results.
    Per-race centering removes race-constant signals. Two temporal halves must
    agree on sign; candidate usefulness is still selected on later tune data.
    """
    if type(min_races) is not int or min_races<2 or not 1<=max_features<=12:
        raise ValueError('DISCOVERY_LIMITS')
    ordered=sorted(rows,key=lambda r:(r['day'],r['race_id']))
    if len({r['race_id'] for r in ordered})!=len(ordered) or any(r['day']>=before for r in ordered):
        raise ValueError('DISCOVERY_TRAINING_BOUNDARY')
    days=sorted({r['day'] for r in ordered})
    if len(days)<2:
        return {'selected':[],'scores':{},'reason':'INSUFFICIENT_CHRONOLOGICAL_SUPPORT'}
    middle=days[len(days)//2]
    # x*y / sqrt(x*x*y*y), aggregated within each half.
    sums=np.zeros((2,len(DISC_NAMES),4))
    for row in ordered:
        _verify_feature_binding(row)
        if not row.get('top3') or row.get('feature_status')!='READY':
            continue
        names=tuple(row['feature_names']); columns=[names.index(k) for k in DISC_NAMES]
        x=np.asarray(row['features'])[:,columns]; x=x-x.mean(axis=0)
        cars=[r['car'] for r in row['riders']]
        y=np.array([float(car==row['top3'][0]) for car in cars]);y-=y.mean()
        h=int(row['day']>=middle)
        xx=(x*x).sum(axis=0); yy=float(y@y)
        sums[h,:,0]+=(x*y[:,None]).sum(axis=0)
        sums[h,:,1]+=xx;sums[h,:,2]+=yy;sums[h,:,3]+=(xx>1e-12)
    scores={}
    for i,name in enumerate(DISC_NAMES):
        a,z=sums[:,i]
        if min(a[3],z[3])<min_races or min(a[1],z[1],a[2],z[2])<=0:
            continue
        corr=[float(v[0]/np.sqrt(v[1]*v[2])) for v in (a,z)]
        if corr[0]*corr[1]>0:
            scores[name]={'score':min(map(abs,corr)),'half_correlations':corr,
                'variable_races':[int(a[3]),int(z[3])],'inputs':list(DISC_PAIRS[i])}
    selected=sorted(scores,key=lambda k:(-scores[k]['score'],k))[:max_features]
    return {'selected':selected,'scores':scores,'split_day':middle,'fit_before':before,
            'fit_races':len(ordered),'future_data_used':False}


STATE_NAMES=('phase_dt_front_fraction','phase_dt_position_gain','phase_dt_position_loss',
             'phase_dt_ahead_teammate_fraction','phase_dt_pressure_exposure','phase_dt_load_proxy',
             'phase_dt_prior_steps_fraction')
def phase_state_features(row, past_orders):
    """Dynamic, dimensionless state from *past* orders only, not the phase being predicted."""
    cars=[r['car'] for r in row['riders']]; n=len(cars)
    names=tuple(row['feature_names']);x=np.asarray(row['features'])
    pressure=x[:,names.index(PREFIX+'rival_pressure')] if PREFIX+'rival_pressure' in names else np.zeros(n)
    groups=row.get('line_groups') or []
    known='line_known' in names and n and np.all(x[:,names.index('line_known')]>.5)
    line={c:set(g) for g in groups for c in g} if known else {}
    if len(past_orders)>5 or any(len(o)!=n or set(o)!=set(cars) for o in past_orders):
        raise ValueError('INVALID_DYNAMIC_PHASE_HISTORY')
    values=[]
    for i,car in enumerate(cars):
        pos=[o.index(car) for o in past_orders];m=len(pos)
        if not m:
            values.append([0.]*len(STATE_NAMES));continue
        front=sum(p==0 for p in pos)/m
        gain=sum(max(0,a-z) for a,z in zip(pos,pos[1:]))/max(1,5*(n-1))
        loss=sum(max(0,z-a) for a,z in zip(pos,pos[1:]))/max(1,5*(n-1))
        sheltered=sum(any(c in line.get(car,set()) for c in o[:o.index(car)]) for o in past_orders)/m
        pressure_exposure=float(pressure[i]*front)
        # Proxy inputs, not joules or power. Coefficients are learned by phase ranker.
        load=(front*(1+float(pressure[i]))+gain+loss)/(1+sheltered)*m/5
        values.append([front,gain,loss,sheltered,pressure_exposure,load,m/5])
    return np.asarray(values,dtype=float).reshape(n,len(STATE_NAMES))


def favorite_failure(model,row):
    """Exact model probability and group-weight sensitivity. Not causal claims."""
    full=model.distribution(row,full=True)
    win={r['car']:r['win_probability'] for r in full['riders']}
    favorite=max(win,key=lambda c:(win[c],-c))
    def ablate(prefixes):
        clone=RankModel.from_dict(model.to_dict())
        mask=[any(n.startswith(p) for p in prefixes) for n in clone.feature_names]
        clone.weights[:,mask]=0.
        law=clone.distribution(row,full=True)
        p=next(r['win_probability'] for r in law['riders'] if r['car']==favorite)
        return {'affected_columns':int(sum(mask)),'p_favorite_wins_without_group':p,
                'delta_win_probability':p-win[favorite]}
    groups={'prior_agari':('history_half_lap_','history_venue_half_lap_','history_agari_','history_observed_agari_'),
        'competition':(PREFIX+'rival_',PREFIX+'third_line_',PREFIX+'agari_x_pressure',PREFIX+'load_x_pressure'),
        'load':(PREFIX+'recent_load_',PREFIX+'weather_load_',PREFIX+'load_x_pressure'),
        'reviewed_motion':(PREFIX+'motion_',),'discovery':(DISC,)}
    return {'status':'MODEL_SENSITIVITY_NOT_CAUSAL','favorite_car':favorite,
            'favorite_win_probability':win[favorite],'favorite_loss_probability':1-win[favorite],
            'alternative_winners':[{'car':c,'probability':p} for c,p in sorted(win.items(),key=lambda v:-v[1]) if c!=favorite],
            'weight_group_sensitivity':{k:ablate(v) for k,v in groups.items()},
            'scope':'frozen model probabilities, not validated physical loss conditions'}
