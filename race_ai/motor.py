"""Motor observations with rider-adjusted *research* evidence, not a calibrated prediction.

A poor finish by a rookie does not by itself establish a weak motor.
Expected top-2 probabilities must be external, pre-race and motor-blind.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime, timezone

from .core import SourceError, source, utc

MOTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS motor_observation (
 venue TEXT NOT NULL, motor_cycle TEXT NOT NULL, motor_no INTEGER NOT NULL,
 race_id TEXT NOT NULL, meeting_id TEXT, racer_id TEXT NOT NULL, lane INTEGER NOT NULL,
 actual_course INTEGER NOT NULL, finish INTEGER, race_at TEXT NOT NULL,
 racer_experience_starts INTEGER, rider_label TEXT NOT NULL,
 baseline_top2 REAL, baseline_model TEXT, baseline_decision_at TEXT,
 published_at TEXT NOT NULL, captured_at TEXT NOT NULL,
 sha TEXT NOT NULL REFERENCES provenance(sha),
 PRIMARY KEY (venue,motor_cycle,motor_no,race_id,sha)
);
CREATE INDEX IF NOT EXISTS ix_motor_obs ON motor_observation(venue,motor_cycle,motor_no,race_at);
CREATE TABLE IF NOT EXISTS motor_service (
 venue TEXT NOT NULL, motor_cycle TEXT NOT NULL, motor_no INTEGER NOT NULL,
 event_id TEXT NOT NULL, service_at TEXT NOT NULL,
 change_type TEXT NOT NULL, published_at TEXT NOT NULL, captured_at TEXT NOT NULL,
 sha TEXT NOT NULL REFERENCES provenance(sha),
 PRIMARY KEY (venue,motor_cycle,motor_no,event_id,sha)
);
"""
MAJOR_EVENTS = frozenset(("motor_cycle_reset","gear_case_replaced","major_parts_replaced"))
SERVICE_KINDS = MAJOR_EVENTS | {"propeller_adjusted","propeller_replaced","inspection","minor_parts_replaced"}
RIDER_LABELS = {"rookie","other","unknown"}


def _validate_identity(record:dict) -> tuple[str,str,int]:
    venue = str(record.get('venue',''))
    motor_cycle = str(record.get('motor_cycle',''))
    motor_no = record.get('motor_no')
    if not re.fullmatch(r'\d{2}',venue) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',motor_cycle):
        raise SourceError('venue must be two digits; motor_cycle must identify actual motor allocation period')
    if type(motor_no) is not int or not 1 <= motor_no <= 999:
        raise SourceError('invalid motor_no')
    return venue,motor_cycle,motor_no


def setup_motor(db:sqlite3.Connection)->None:
    db.executescript(MOTOR_SCHEMA)


def import_motor_observation(db:sqlite3.Connection,record:dict)->dict:
    """Append a rights-authorized row with the observed finish and optional pre-race baseline.

    Rider label is descriptive ONLY. No special weight is assigned to 'rookie'.
    """
    venue,cycle,no = _validate_identity(record)
    lane,course=record.get('lane'),record.get('actual_course')
    if type(lane) is not int or type(course) is not int or lane not in range(1,7) or course not in range(1,7):
        raise SourceError('invalid lane/course')
    racer_id=str(record.get('racer_id',''))
    if not re.fullmatch(r'\d{4}',racer_id):
        raise SourceError('racer_id required')
    race_id=str(record.get('race_id',''))
    if not re.fullmatch(r'\d{8}-\d{2}-\d{2}',race_id) or not race_id.startswith(venue,9):
        raise SourceError('race ID must be YYYYMMDD-VV-RR for venue')
    meeting_id=record.get('meeting_id')
    if meeting_id is not None and (not isinstance(meeting_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}', meeting_id)):
        raise SourceError('invalid meeting_id (explicit event identity required)')
    finish=record.get('finish')
    if finish is not None and (type(finish) is not int or finish not in range(1,7)):
        raise SourceError('finish must be 1..6 or null')
    experience=record.get('racer_experience_starts')
    if experience is not None and (type(experience) is not int or experience<0):
        raise SourceError('invalid experience starts')
    rider_label=record.get('rider_label','unknown')
    if rider_label not in RIDER_LABELS:
        raise SourceError('rider label is not recognized')
    if not record.get('rights_confirmed'):
        raise SourceError('documented source/usage rights required')
    race_at=utc(record['race_at'])
    published=utc(record['published_at']); captured=utc(record['captured_at'])
    if not (race_at<=published<=captured):
        raise SourceError('result cannot be published or captured before the race')
    baseline=record.get('baseline_top2')
    model=record.get('baseline_model')
    baseline_at=record.get('baseline_decision_at')
    if baseline is not None:
        if type(baseline) not in (int,float) or not math.isfinite(baseline) or not 0<=baseline<=1:
            raise SourceError('invalid baseline probability')
        if not isinstance(model,str) or not model.strip() or not baseline_at:
            raise SourceError('baseline model and recorded pre-race decision time required')
        baseline_at=utc(baseline_at)
        if not baseline_at<race_at:
            raise SourceError('baseline prediction must predate this race')
        if not record.get('baseline_excludes_motor'):
            raise SourceError('baseline must be motor-blind to avoid circular adjustment')
    elif model is not None or baseline_at is not None:
        raise SourceError('baseline fields must be supplied together')
    raw=json.dumps(record,sort_keys=True,ensure_ascii=False).encode('utf-8')
    setup_motor(db)
    with db:
        digest=source(db,'MOTOR_RESULT',raw,record.get('source_name','manual'),published,captured,False)
        db.execute('''INSERT OR IGNORE INTO motor_observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (venue,cycle,no,race_id,meeting_id,racer_id,lane,course,finish,race_at,
                    experience,rider_label,baseline,model,baseline_at,published,captured,digest))
    return {'sha256':digest,'accepted_as':'unverified_operator_source',
            'baseline_audited':False,'rows':1}


def import_motor_service(db:sqlite3.Connection,record:dict)->dict:
    venue,cycle,no=_validate_identity(record)
    event=str(record.get('event_id',''))
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}',event):
        raise SourceError('invalid event_id')
    kind=record.get('change_type')
    if kind not in SERVICE_KINDS:
        raise SourceError('invalid service type')
    if not record.get('rights_confirmed'):
        raise SourceError('documented source/usage rights required')
    service_at=utc(record['service_at'])
    published=utc(record['published_at'])
    captured=utc(record['captured_at'])
    if not service_at<=published<=captured:
        raise SourceError('service timestamps out of order')
    raw=json.dumps(record,sort_keys=True,ensure_ascii=False).encode('utf-8')
    setup_motor(db)
    with db:
        digest=source(db,'MOTOR_SERVICE',raw,record.get('source_name','manual'),published,captured,False)
        db.execute('INSERT OR IGNORE INTO motor_service VALUES (?,?,?,?,?,?,?,?,?)',
                   (venue,cycle,no,event,service_at,kind,published,captured,digest))
    return {'sha256':digest,'rows':1,'status':'unverified_operator_source'}


def _recent_asof(db:sqlite3.Connection,venue:str,cycle:str,no:int,cutoff:str):
    rows=db.execute('''SELECT * FROM (
     SELECT o.*, ROW_NUMBER() OVER(
       PARTITION BY race_id ORDER BY captured_at DESC,sha DESC) AS revision_rank
     FROM motor_observation o
     WHERE venue=? AND motor_cycle=? AND motor_no=?
       AND race_at<? AND published_at<=? AND captured_at<=?
    ) WHERE revision_rank=1 ORDER BY race_at DESC,race_id DESC''',
    (venue,cycle,no,cutoff,cutoff,cutoff)).fetchall()
    return rows


def analyze_motor(db:sqlite3.Connection, venue:str,motor_cycle:str,motor_no:int,
                  asof:str,half_life_days:float=45,prior_races:float=10,
                  target_meeting_id:str|None=None)->dict:
    """Descriptive, shrinkage-adjusted motor signal; NEVER claimed calibrated.

    The baseline is supposed to condition on racer ability, course and opponents,
    but that assertion and its out-of-time quality require independent auditing.
    """
    venue,cycle,no=_validate_identity(dict(venue=venue,motor_cycle=motor_cycle,motor_no=motor_no))
    cutoff=utc(asof)
    if target_meeting_id is not None and (not isinstance(target_meeting_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,80}',target_meeting_id)):
        raise SourceError('invalid target meeting identity')
    if not math.isfinite(half_life_days) or half_life_days<=0 or not math.isfinite(prior_races) or prior_races<=0:
        raise SourceError('half-life and prior strength must be positive')
    setup_motor(db)
    services=db.execute('''SELECT service_at,change_type FROM motor_service
      WHERE venue=? AND motor_cycle=? AND motor_no=?
        AND service_at<=? AND published_at<=? AND captured_at<=?
      ORDER BY service_at DESC''',(venue,cycle,no,cutoff,cutoff,cutoff)).fetchall()
    major=[s for s in services if s['change_type'] in MAJOR_EVENTS]
    since=major[0]['service_at'] if major else None
    all_rows=_recent_asof(db,venue,cycle,no,cutoff)
    rows=[r for r in all_rows if since is None or r['race_at']>=since]
    valid=[r for r in rows if r['finish'] in (1,2,3,4,5,6)]
    adjusted=[r for r in valid if r['baseline_top2'] is not None]
    latest=rows[0] if rows else None
    def summary(r):
        return {'race_id':r['race_id'],'racer_id':r['racer_id'],
                'rider_label':r['rider_label'],'lane':r['lane'],'course':r['actual_course'],
                'finish':r['finish'],'top2_expected':r['baseline_top2']}
    recent=[summary(r) for r in rows[:10]]
    prior_meeting=None
    if target_meeting_id is not None:
        # The most recent *different* meet before asof. Missing IDs never count.
        match=next((r['meeting_id'] for r in rows if r['meeting_id'] is not None
                    and r['meeting_id']!=target_meeting_id),None)
        if match is not None:
            group=[r for r in rows if r['meeting_id']==match]
            finished=[r for r in group if r['finish'] is not None]
            prior_meeting={'meeting_id':match,'starts':len(group),
                           'rookie_starts':sum(r['rider_label']=='rookie' for r in group),
                           'riders':sorted({r['racer_id'] for r in group}),
                           'raw_top2_rate':round(sum(r['finish']<=2 for r in finished)/len(finished),6) if finished else None,
                           'baseline_coverage':sum(r['baseline_top2'] is not None for r in group),
                           'status':'descriptive_only_not_rider_adjusted'}
    total_rate=(sum(r['finish']<=2 for r in valid)/len(valid)) if valid else None
    n_rookie=sum(r['rider_label']=='rookie' for r in valid)
    signal=None; effective_n=None
    if adjusted:
        d=datetime.fromisoformat(cutoff)
        weights=[2**(-max(0,(d-datetime.fromisoformat(r['race_at'])).total_seconds()/86400)/half_life_days) for r in adjusted]
        summed=sum(weights)
        if summed>0:
            effective_n=summed**2/sum(w*w for w in weights)
            residual=sum(w*((1 if r['finish']<=2 else 0)-r['baseline_top2']) for w,r in zip(weights,adjusted))/summed
            signal=round(residual*effective_n/(effective_n+prior_races),6)
    return {
      'venue':venue,'motor_cycle':cycle,'motor_no':no,'asof':cutoff,
      'motor_since_major_service':since,'service_warning':bool(services),
      'raw_top2_rate':round(total_rate,6) if total_rate is not None else None,
      'finish_sample_n':len(valid),'rookie_ridden_n':n_rookie,
      'adjusted_rider_neutral_residual':signal,'adjusted_sample_n':len(adjusted),
      'adjusted_effective_n':round(effective_n,3) if effective_n is not None else None,
      'recent_10':recent,'latest_observed_rider':summary(latest) if latest else None,
      'latest_previous_rider':summary(latest) if latest else None,
      'previous_meet':prior_meeting,
      'confidence':'NOT_VALIDATED' if signal is not None else 'INSUFFICIENT_BASELINE',
      'interpretation':'A residual is not a calibrated win probability or intrinsic motor speed.',
      'warnings':['Previous rider grade alone never alters motor scoring.',
                  'No audited opponent/course/rider baseline, motor adjustments or video proof yet.',
                  'Rate comparisons across races with different conditions are confounded.']
    }
