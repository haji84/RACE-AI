"""Compare frozen research flow with separately recorded observations.

No model, result authenticator, network client or learning loop lives here.
Source categories are attestations by the observation producer; a hash and a
category do not independently authenticate a video, article or official record.
User observations receive provisional categories only. AI estimates never stand
in for an observed race. Missing predictions cannot be filled from observations.
"""
from collections import Counter, defaultdict
import json
import re

from .keirin_nationwide_auto_generator import when


SCHEMA = 'KEIRIN_FLOW_OBSERVATIONS_V1'
METHOD = 'separate-finish-and-flow-20261125-v1'
PHASES = ('INITIAL', 'BELL', 'FINAL_HOME', 'FINAL_BACK', 'FOURTH_CORNER')
LEADER_PHASES = ('BELL', 'FINAL_HOME', 'FINAL_BACK')
METRICS = ('phase_order', 'front_runner', 'initiative', 'leader', 'attack_order')
CONFIRMED_KINDS = {'OFFICIAL_RECORD', 'VIDEO_OBSERVATION', 'PUBLISHED_REPORT'}
SOURCE_KINDS = CONFIRMED_KINDS | {'USER_OBSERVATION', 'AI_ESTIMATE'}
REQUIRED = ({('phase_order', phase) for phase in PHASES}
            | {('leader', phase) for phase in LEADER_PHASES} | {('attack_order', 'RACE')})
SHA = re.compile(r'[a-f0-9]{64}')


def need(condition, code):
    if not condition:
        raise ValueError(code)


def _value(metric, phase, value, starters):
    need(type(metric) is str and type(phase) is str, 'FLOW_METRIC_INVALID')
    if metric == 'phase_order':
        need(phase in PHASES and type(value) is list
             and all(type(car) is int for car in value)
             and len(value) == len(starters) and set(value) == starters,
             'FLOW_PHASE_ORDER_INVALID')
    elif metric in ('leader', 'front_runner', 'initiative'):
        allowed = LEADER_PHASES if metric == 'leader' else ('INITIAL',) if metric == 'front_runner' else ('RACE',)
        need(phase in allowed and type(value) is int and value in starters,
             'FLOW_LEADER_INVALID')
    elif metric == 'attack_order':
        need(phase == 'RACE' and type(value) is list and len(value) <= 32, 'FLOW_ATTACK_ORDER_INVALID')
        tokens = []
        latest_attempt = {}
        for event in value:
            need(type(event) is dict and set(event) == {'car', 'attempt'}
                 and type(event['car']) is int and event['car'] in starters
                 and type(event['attempt']) is int and 1 <= event['attempt'] <= 32,
                 'FLOW_ATTACK_EVENT_INVALID')
            need(event['attempt'] > latest_attempt.get(event['car'], 0), 'FLOW_ATTACK_ATTEMPT_ORDER_INVALID')
            latest_attempt[event['car']] = event['attempt']
            tokens.append((event['car'], event['attempt']))
        need(len(tokens) == len(set(tokens)), 'FLOW_DUPLICATE_ATTACK_EVENT')
    else:
        raise ValueError('FLOW_METRIC_INVALID')


def _prediction(expected, starters):
    need(type(expected) is dict and expected.keys() <= {
        'phase_orders', 'leaders', 'attack_order', 'initial_front', 'initiative'},
         'FLOW_PREDICTION_INVALID')
    values = {}
    for field, metric in (('phase_orders', 'phase_order'), ('leaders', 'leader')):
        by_phase = expected.get(field, {})
        need(type(by_phase) is dict, 'FLOW_PREDICTION_INVALID')
        for phase, value in by_phase.items():
            _value(metric, phase, value, starters)
            values[metric, phase] = value
    if 'attack_order' in expected:
        _value('attack_order', 'RACE', expected['attack_order'], starters)
        values['attack_order', 'RACE'] = expected['attack_order']
    for field, metric, phase in (('initial_front', 'front_runner', 'INITIAL'),
                                 ('initiative', 'initiative', 'RACE')):
        if field in expected:
            _value(metric, phase, expected[field], starters)
            values[metric, phase] = expected[field]
    if 'initial_front' in expected and 'INITIAL' in expected.get('phase_orders', {}):
        need(expected['initial_front'] == expected['phase_orders']['INITIAL'][0],
             'FLOW_ORIGINAL_INITIAL_CONFLICT')
    return values


def _facts(facts, starters, observed_at):
    need(type(facts) is list and len(facts) <= 256, 'FLOW_FACTS_INVALID')
    for fact in facts:
        need(type(fact) is dict and set(fact) == {'metric', 'phase', 'value', 'complete', 'source'},
             'FLOW_FACT_INVALID')
        metric, phase = fact['metric'], fact['phase']
        _value(metric, phase, fact['value'], starters)
        need(type(fact['complete']) is bool and (metric == 'attack_order' or fact['complete']),
             'FLOW_COMPLETENESS_INVALID')
        need(fact['complete'] or len(fact['value']) >= 2, 'FLOW_PARTIAL_SEQUENCE_WITHOUT_ORDER')
        source = fact['source']
        need(type(source) is dict and set(source) == {'kind', 'reference', 'recorded_at', 'sha256'}
             and type(source['kind']) is str and source['kind'] in SOURCE_KINDS
             and type(source['reference']) is str and 0 < len(source['reference']) <= 2048,
             'FLOW_SOURCE_INVALID')
        need(when(source['recorded_at']) <= observed_at, 'FLOW_OBSERVATION_CLOCK_INVALID')
        digest = source['sha256']
        need((digest is None and source['kind'] in {'USER_OBSERVATION', 'AI_ESTIMATE'})
             or (type(digest) is str and SHA.fullmatch(digest)), 'FLOW_SOURCE_DIGEST_REQUIRED')


def _matches(metric, expected, fact):
    actual = fact['value']
    if metric != 'attack_order' or fact['complete']:
        return expected == actual
    # An incomplete observation asserts ordering of the events that were seen,
    # not the absence of any additional attacks. Attempts distinguish repeated
    # accelerations by the same car. No distance, velocity or time is inferred.
    positions = {(e['car'], e['attempt']): n for n, e in enumerate(expected)}
    indices = [positions.get((e['car'], e['attempt'])) for e in actual]
    return all(index is not None for index in indices) and indices == sorted(indices)


def _assessment(expected, grouped, result_hit):
    metrics = {name: dict(compared=0, matched=0, conflicting=0, missing_prediction=0, partial=0)
               for name in METRICS}
    complete_keys, mismatch = set(), False
    for key, facts in grouped.items():
        metric, _ = key
        counts = metrics[metric]
        distinct = {json.dumps(f['value'], sort_keys=True) for f in facts}
        if len(distinct) > 1:
            counts['conflicting'] += 1
            continue
        if key not in expected:
            counts['missing_prediction'] += 1
            continue
        # Prefer a complete observation only when its value agrees with every
        # source in this group. Duplicated sources never add comparisons.
        actual = next((fact for fact in facts if fact['complete']), facts[0])
        correct = _matches(metric, expected[key], actual)
        counts['compared'] += 1
        counts['matched'] += correct
        counts['partial'] += not actual['complete']
        mismatch |= not correct
        if actual['complete']:
            complete_keys.add(key)
    complete = REQUIRED <= complete_keys
    category = None
    if result_hit is not None:
        category = ('B' if result_hit else 'D') if mismatch else (
            ('A' if result_hit else 'C') if complete else 'E')
    return category, complete, metrics


def evaluate_case(expected, facts, *, starters, result_hit, observed_at):
    """Return count-only diagnostics for one selected, pre-specified flow path.

    A/C require all five non-goal phase orders, initiative at bell/home/back,
    and a complete attack sequence. One confirmed contradiction suffices for
    B/D; partial matching alone is E. GOAL is deliberately not a flow metric.
    Missing results produce no A–E category, while flow comparisons still run.
    Callers own result admission and source attestation/authentication.
    """
    need(type(starters) is set and 3 <= len(starters) <= 9
         and all(type(car) is int and 1 <= car <= 9 for car in starters), 'FLOW_STARTERS_INVALID')
    need(result_hit is None or type(result_hit) is bool, 'FLOW_RESULT_HIT_INVALID')
    observed = when(observed_at)
    predicted = _prediction(expected, starters)
    _facts(facts, starters, observed)
    confirmed, users = defaultdict(list), defaultdict(list)
    source_counts = Counter()
    for fact in facts:
        key = fact['metric'], fact['phase']
        kind = fact['source']['kind']
        source_counts[kind] += 1
        if kind in CONFIRMED_KINDS:
            confirmed[key].append(fact)
        elif kind == 'USER_OBSERVATION':
            users[key].append(fact)
    provisional = dict(users)
    provisional.update(confirmed)  # A user report cannot override independent evidence.
    category, complete, metrics = _assessment(predicted, confirmed, result_hit)
    reference, reference_complete, reference_metrics = _assessment(predicted, provisional, result_hit)
    return dict(classification=category, provisional_classification=reference, result_hit=result_hit,
                confirmed_flow_complete=complete, provisional_flow_complete=reference_complete,
                confirmed_metrics=metrics, provisional_metrics=reference_metrics,
                source_fact_counts=dict(source_counts), original_flow_present=bool(predicted))


def summarize_flow(predictions, observations, *, forecast_sha256, result_hits, starters_by_race):
    """Aggregate after existing SHA/cutoff/result checks, disclosing no picks.

    The observation envelope is separate from the immutable prediction bytes.
    `flow` must already be in those bytes: {published: {...}, trial: {...}}.
    No best-fitting scenario is selected after seeing the race.
    """
    need(type(observations) is dict and set(observations) == {
        'schema', 'forecast_sha256', 'recorded_at', 'races'} and observations['schema'] == SCHEMA,
        'FLOW_OBSERVATIONS_SCHEMA_INVALID')
    need(observations['forecast_sha256'] == forecast_sha256 and type(forecast_sha256) is str
         and SHA.fullmatch(forecast_sha256), 'FLOW_FORECAST_SHA_MISMATCH')
    observed_at = when(observations['recorded_at'])
    need(type(observations['races']) is list, 'FLOW_RACES_INVALID')
    indexed = {}
    for row in observations['races']:
        need(type(row) is dict and set(row) == {'race_id', 'facts'}
             and type(row['race_id']) is str and row['race_id'] not in indexed, 'FLOW_RACE_INVALID')
        indexed[row['race_id']] = row['facts']
    forecasts = {row['race_id']: row for row in predictions['races']}
    need(indexed.keys() <= forecasts.keys(), 'FLOW_UNREGISTERED_RACE')
    need(result_hits.keys() == forecasts.keys() == starters_by_race.keys(), 'FLOW_RESULT_SCOPE_MISMATCH')
    result = dict(method=METHOD, registered=len(forecasts), observation_races=len(indexed),
                  result_unavailable=sum(result_hits[key]['published'] is None for key in forecasts),
                  observations_recorded_at=observations['recorded_at'],
                  source_authority='PRODUCER_ATTESTATIONS_NOT_INDEPENDENT_AUTHENTICATION',
                  independent_source_authentication_performed=False)
    for side in ('published', 'trial'):
        categories = dict.fromkeys('ABCDE', 0)
        provisional = dict.fromkeys('ABCDE', 0)
        totals = {name: Counter() for name in METRICS}
        missing_original = 0
        for key, row in forecasts.items():
            facts = indexed.get(key, [])
            cutoff = when(row['cutoff_at'])
            need(not facts or cutoff <= observed_at, 'FLOW_OBSERVATIONS_PRECEDE_CUTOFF')
            selected = row.get('flow', {})
            need(type(selected) is dict and selected.keys() <= {'published', 'trial'}, 'FLOW_SIDES_INVALID')
            scored = evaluate_case(selected.get(side, {}), facts, starters=starters_by_race[key],
                                   result_hit=result_hits[key][side], observed_at=observations['recorded_at'])
            need(all(cutoff <= when(f['source']['recorded_at']) for f in facts),
                 'FLOW_OBSERVATIONS_PRECEDE_CUTOFF')
            if scored['classification'] is not None:
                categories[scored['classification']] += 1
                provisional[scored['provisional_classification']] += 1
            missing_original += not scored['original_flow_present']
            for metric in METRICS:
                totals[metric].update(scored['confirmed_metrics'][metric])
        result[side] = dict(categories=categories, provisional_categories=provisional,
                            missing_original_flow=missing_original,
                            confirmed_metrics={k: dict(v) for k, v in totals.items()})
    return result
