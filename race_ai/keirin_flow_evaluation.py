"""Count-only forward-score adapter to the existing race-development PDCA.

This is not a second flow classifier or a source authenticator. Predictions,
result admission and externally verified evidence retain their existing owners.
Source receipts here are producer attestations, not issuer signatures.
"""
from collections import Counter
import re

from . import keirin_form_fall_blind_pdca as pdca
from .keirin_nationwide_auto_generator import when

SCHEMA = 'KEIRIN_FLOW_OBSERVATIONS_V1'
METHOD = 'existing-development-pdca-forward-adapter-20261125-v1'
SHA = re.compile(r'[a-f0-9]{64}')


def need(condition, code):
    if not condition:
        raise ValueError(code)


def _observations(rows, *, race_id, cutoff, recorded_at):
    need(type(rows) is list and len(rows) <= 256, 'FLOW_OBSERVATIONS_INVALID')
    for row in rows:
        need(type(row) is dict and set(row) == {
            'race_id','aspect','observed','source','complete','receipt'}
             and row['race_id'] == race_id and type(row['source']) is str
             and row['source'] in {'video','official','article','user','estimate'}, 'FLOW_OBSERVATION_INVALID')
        receipt = row['receipt']
        need(type(receipt) is dict and set(receipt) == {'reference','recorded_at','sha256'}
             and type(receipt['reference']) is str and 0 < len(receipt['reference']) <= 2048,
             'FLOW_SOURCE_INVALID')
        need(cutoff <= when(receipt['recorded_at']) <= recorded_at, 'FLOW_OBSERVATION_CLOCK_INVALID')
        digest = receipt['sha256']
        need((digest is None and row['source'] in {'user','estimate'})
             or type(digest) is str and SHA.fullmatch(digest), 'FLOW_SOURCE_DIGEST_REQUIRED')
        # No observed relative order exists in a zero/one-event partial sample.
        if row['aspect'] == 'ATTACK_ORDER' and row['complete'] is False:
            need(type(row['observed']) is list and len(row['observed']) >= 2,
                 'FLOW_PARTIAL_SEQUENCE_WITHOUT_ORDER')


def _counts(aspects):
    return {aspect: dict(compared=int(row['state'] in {'match','partial_match','different'}),
                         matched=int(row['state'] in {'match','partial_match'}),
                         conflicting=int(row['state'] == 'conflict'),
                         missing_prediction=int(row['state'] == 'forecast_missing' and bool(row['sources'])),
                         partial=int(row['state'] == 'partial_match'))
            for aspect,row in aspects.items()}


def summarize_flow(predictions, observations, *, forecast_sha256, receipt, orders_by_race, starters_by_race):
    """Use the canonical PDCA for each original's pre-specified flow, then redact.

    Call after forward-score's SHA, roster, cutoff and result checks. A receipt
    describing normalization after a race cutoff cannot admit the normalized
    flow-bearing bytes for that race, even when it preserves an older ticket
    freeze timestamp. Legacy finish scoring remains unaffected.
    """
    need(type(observations) is dict and set(observations) == {
        'schema','forecast_sha256','recorded_at','races'} and observations['schema'] == SCHEMA,
        'FLOW_OBSERVATIONS_SCHEMA_INVALID')
    need(observations['forecast_sha256'] == forecast_sha256 and type(forecast_sha256) is str
         and SHA.fullmatch(forecast_sha256), 'FLOW_FORECAST_SHA_MISMATCH')
    observed_at = when(observations['recorded_at'])
    need(type(observations['races']) is list, 'FLOW_RACES_INVALID')
    indexed = {}
    for row in observations['races']:
        need(type(row) is dict and set(row) == {'race_id','observations'}
             and type(row['race_id']) is str and row['race_id'] not in indexed, 'FLOW_RACE_INVALID')
        indexed[row['race_id']] = row['observations']
    forecasts = {row['race_id']:row for row in predictions['races']}
    need(indexed.keys() <= forecasts.keys(), 'FLOW_UNREGISTERED_RACE')
    need(orders_by_race.keys() == forecasts.keys() == starters_by_race.keys(), 'FLOW_RESULT_SCOPE_MISMATCH')
    frozen = when(receipt['frozen_at'])
    normalized = when(receipt['normalized_at']) if 'normalized_at' in receipt else None
    need(normalized is None or frozen <= normalized, 'FLOW_NORMALIZATION_PRECEDES_FREEZE')
    ambiguous_origin = normalized is None and receipt.get('timestamp_semantics') == 'original_ticket_forecast_freeze'
    report = dict(method=METHOD, classifier='keirin_form_fall_blind_pdca.compare_race_development',
                  evaluation_scope='RESEARCH_COMPARISON_NOT_OFFICIAL_SETTLEMENT',
                  registered=len(forecasts), observation_races=len(indexed),
                  result_unavailable=sum(order is None for order in orders_by_race.values()),
                  observations_recorded_at=observations['recorded_at'],
                  source_authority='PRODUCER_ATTESTATIONS_NOT_INDEPENDENT_AUTHENTICATION',
                  original_clock_authority='RECEIPT_DECLARATION_REQUIRES_EXTERNAL_VERIFICATION',
                  independent_source_authentication_performed=False)
    for side in ('published','trial'):
        categories, provisional = dict.fromkeys('ABCDE',0), dict.fromkeys('ABCDE',0)
        totals = {aspect:Counter() for aspect in pdca._FLOW_ASPECTS}
        missing_original = origin_not_admitted = 0
        for rid,row in forecasts.items():
            cutoff = when(row['cutoff_at'])
            facts = indexed.get(rid,[])
            _observations(facts, race_id=rid, cutoff=cutoff, recorded_at=observed_at)
            saved = row.get('flow',{})
            need(type(saved) is dict and saved.keys() <= {'published','trial'}, 'FLOW_SIDES_INVALID')
            expected = saved.get(side,{})
            missing_original += not bool(expected)
            origin_admitted = not ambiguous_origin and (normalized or frozen) < cutoff
            origin_not_admitted += not origin_admitted
            forecast = dict(scope='registered', race_id=rid, sealed_at=(normalized or frozen).isoformat(),
                            cutoff_at=row['cutoff_at'], tickets=row[side][:row['points']], flow=expected)
            order = orders_by_race[rid]
            result = dict(race_id=rid, winning_triples=[order]) if order is not None else None
            args = dict(race_id=rid, starters=sorted(starters_by_race[rid]), forecast=forecast,
                        order=result, observations=facts,
                        verify_forecast=lambda _:origin_admitted, verify_order=lambda _:True,
                        verify_observation=lambda fact:fact['source'] in {'video','official','article'})
            scored = pdca.compare_race_development(**args)
            if not origin_admitted:
                continue
            if scored['grade'] is not None:
                categories[scored['grade']] += 1
                # Provisional diagnostics use the SAME saved flow and canonical
                # comparison; the reference scope never creates a formal origin.
                args['forecast'] = dict(forecast, scope='conversation_reference')
                reference = pdca.compare_race_development(**args)
                provisional[reference['reference_grade']] += 1
            for aspect,counts in _counts(scored['flow']['aspects']).items():
                totals[aspect].update(counts)
        report[side] = dict(categories=categories, provisional_categories=provisional,
                            origin_not_admitted=origin_not_admitted, missing_original_flow=missing_original,
                            confirmed_metrics={k:dict(v) for k,v in totals.items()})
    return report
