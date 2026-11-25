"""Identity-bound serialization of the existing full joint finish law.

Full records are private research material. Public display uses a derived
projection with all per-rider places and only selected market outcomes. Neither
probability consistency nor a source digest authenticates a pre-cutoff original
or establishes empirical calibration.
"""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations
from math import fsum, isfinite
import re
from zoneinfo import ZoneInfo

from .keirin_joint_finish import JointFinish
from .keirin_nationwide_auto_generator import digest, when

SCHEMA = 'RACE_AI_KEIRIN_JOINT_FORECAST_V1'
PROJECTION = 'RACE_AI_KEIRIN_JOINT_PROJECTION_V1'
JST = ZoneInfo('Asia/Tokyo')
EPS = 1e-8
META = ('race_id','generated_at','cutoff_at','source_as_of','model_id','model_version',
        'input_sha256','source_packet_sha256','source_forecast_generated_at')


def _need(ok):
    if not ok:
        raise ValueError('KEIRIN_JOINT_FORECAST_INVALID')


def _number(value):
    return type(value) in (int,float) and isfinite(value)


def _probability(value):
    return _number(value) and 0 <= value <= 1


def _same(left,right):
    return abs(left-right) <= EPS


def _metadata(record):
    _need(type(record) is dict and all(key in record for key in META))
    rid=record['race_id']
    _need(type(rid) is str and re.fullmatch(r'20[0-9]{10}',rid))
    for field in ('model_id','model_version'):
        _need(type(record[field]) is str and 0 < len(record[field]) <= 160)
    for field in ('input_sha256','source_packet_sha256'):
        _need(type(record[field]) is str and re.fullmatch('[0-9a-f]{64}',record[field]))
    generated,cutoff,source,original=(when(record[k]) for k in (
        'generated_at','cutoff_at','source_as_of','source_forecast_generated_at'))
    _need(source <= original <= generated)
    day=cutoff.astimezone(JST).date()
    race_day=when(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}T00:00:00+09:00').astimezone(JST).date()
    _need(race_day <= day <= race_day+timedelta(days=1))
    scope='PROSPECTIVE_RESEARCH' if generated < cutoff else 'RETROSPECTIVE_RESEARCH'
    _need(record.get('scope') == scope and record.get('premise') == 'ALL_FINISH_NO_TIES'
          and record.get('calibration_status') == 'UNVALIDATED')
    if scope == 'PROSPECTIVE_RESEARCH':
        _need(source < cutoff and original < cutoff)
    return scope


def _market(rows,cars,width):
    _need(type(rows) is list and len(rows) == len(list(permutations(cars,width))))
    result={}
    for row in rows:
        _need(type(row) is dict and set(row) == {'order','probability'})
        order=row['order']
        _need(type(order) is list and len(order) == width
              and all(type(c) is int and c in cars for c in order)
              and len(set(order)) == width and _probability(row['probability']))
        key=tuple(order)
        _need(key not in result)
        result[key]=row['probability']
    _need(_same(fsum(result.values()),1.))
    return result


def validate_forecast(record):
    """Check identity, chronology and all market/rank marginal relationships."""
    _metadata(record)
    _need(record.get('schema') == SCHEMA)
    cars=record.get('cars')
    _need(type(cars) is list and 3 <= len(cars) <= 9
          and all(type(car) is int and 1 <= car <= 9 for car in cars) and len(set(cars)) == len(cars))
    triples=_market(record.get('trifectas'),cars,3)
    pairs=_market(record.get('exactas'),cars,2)
    for pair,value in pairs.items():
        _need(_same(value,fsum(p for order,p in triples.items() if order[:2] == pair)))
    riders=record.get('riders')
    _need(type(riders) is list and len(riders) == len(cars))
    indexed={r['car']:r for r in riders if type(r) is dict and type(r.get('car')) is int}
    _need(len(indexed) == len(riders) and set(indexed) == set(cars))
    registrations=[]
    for car,row in indexed.items():
        _need(type(row.get('name')) is str and 0 < len(row['name']) <= 100)
        registration=row.get('registration')
        _need(registration is None or type(registration) is str and re.fullmatch('[0-9]{6}',registration)
              and registration != '000000')
        if registration is not None:registrations.append(registration)
        probabilities=row.get('rank_probabilities')
        _need(type(probabilities) is list and len(probabilities) == len(cars)
              and all(_probability(p) for p in probabilities) and _same(fsum(probabilities),1.))
        for rank in range(3):
            _need(_same(probabilities[rank],fsum(p for order,p in triples.items() if order[rank] == car)))
        expected=dict(top2_probability=fsum(probabilities[:2]),top3_probability=fsum(probabilities[:3]),
                      outside_top3_probability=fsum(probabilities[3:]),
                      expected_rank=fsum((index+1)*p for index,p in enumerate(probabilities)))
        for key,value in expected.items():
            _need(_number(row.get(key)) and _same(row[key],value))
        _need(type(row.get('most_likely_rank')) is int and row['most_likely_rank'] ==
              max(range(1,len(cars)+1),key=lambda rank:probabilities[rank-1]))
    _need(len(registrations) == len(set(registrations)))
    for rank in range(len(cars)):
        _need(_same(fsum(row['rank_probabilities'][rank] for row in riders),1.))
    return record


def build_forecast(joint,*,race_id,generated_at,cutoff_at,source_as_of,model_id,model_version,
                   input_sha256,source_packet_sha256,source_forecast_generated_at,riders):
    """Serialize one existing JointFinish; do not infer missing registrations."""
    _need(isinstance(joint,JointFinish) and type(riders) is list)
    marginals=joint.marginals()
    cars=list(marginals)
    identities={row['car']:row for row in riders if type(row) is dict and type(row.get('car')) is int}
    _need(len(identities) == len(riders) == len(cars) and set(identities) == set(cars))
    summaries=joint.rider_summary()['riders']
    def market(values):
        return [dict(order=list(order),probability=float(value))
                for order,value in sorted(values.items(),key=lambda item:(-item[1],item[0]))]
    generated,cutoff=when(generated_at),when(cutoff_at)
    record=dict(schema=SCHEMA,race_id=race_id,generated_at=generated_at,cutoff_at=cutoff_at,
                source_as_of=source_as_of,model_id=model_id,model_version=model_version,
                input_sha256=input_sha256,source_packet_sha256=source_packet_sha256,
                source_forecast_generated_at=source_forecast_generated_at,
                scope='PROSPECTIVE_RESEARCH' if generated < cutoff else 'RETROSPECTIVE_RESEARCH',
                premise='ALL_FINISH_NO_TIES',calibration_status='UNVALIDATED',cars=cars,
                trifectas=market(joint.trifectas()),exactas=market(joint.exactas()),riders=[
                    dict(car=car,name=identities[car].get('name'),registration=identities[car].get('registration'),
                         rank_probabilities=list(map(float,marginals[car])),**summaries[car]) for car in cars])
    validate_forecast(record)
    return record


def public_projection(record):
    """Retain public marginals and selected picks without exposing the full law."""
    validate_forecast(record)
    projection={key:deepcopy(value) for key,value in record.items() if key not in {'trifectas','exactas'}}
    projection.update(schema=PROJECTION,source_joint_sha256=digest(record),ranked_markets={
        '3t':deepcopy(sorted(record['trifectas'],key=lambda r:(-r['probability'],r['order']))[:8]),
        '2t':deepcopy(sorted(record['exactas'],key=lambda r:(-r['probability'],r['order']))[:4])})
    return projection
